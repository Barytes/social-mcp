"""Xiaohongshu login and search. One browser, serialized. Never opens /explore without a note id."""

from __future__ import annotations

import logging
import re
import time

from mcp_browser.actions import (
    challenge_from_text,
    goto_allowed,
    safe_click,
    safe_fill,
    save_screenshot,
    visible_challenge,
)
from mcp_browser.errors import (
    FeedBlocked,
    InvalidArgument,
    LoginUiNotFound,
    NeedsHumanVerification,
    NotLoggedIn,
    PageNotUnderstood,
    SiteError,
    SmsFormNotReady,
    SmsRejected,
)
from mcp_browser.guard import ClickPurpose, FillPurpose
from mcp_browser.qr import expired_error, not_ready_payload, pending_payload, text_says_expired
from mcp_browser.redact import redact

from xhs_mcp.parse import classify_xhs_search, parse_xhs_identity, parse_xhs_note, parse_xhs_profile_name
from xhs_mcp.urls import LOGIN_URL, xhs_profile_url, xhs_search_url

log = logging.getLogger(__name__)

_QR_CONFIRM = ("扫描成功", "请在手机上确认", "确认登录")
_MASKED_PHONE = re.compile(r"(\+?\d{1,4}\s*\d{2,4}\*+\d{2,4})")
_LOGGED_OUT = (
    "未登录。小红书同一账号只保留一个网页会话：新的网页登录会把这次会话踢下线。"
    "这次检查分不清「还没登录」和「被新的网页登录替换」。"
)


def _keyword(keyword: str) -> str:
    text = (keyword or "").strip()
    if not text or len(text) > 80 or re.search(r"[\x00-\x1f]", text):
        raise InvalidArgument("keyword must be 1–80 characters and contain no control characters.")
    return text


def _limit(limit: int) -> int:
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 30:
        raise InvalidArgument("limit must be an integer from 1 to 30.")
    return limit


def _phone(phone: str) -> str:
    digits = re.sub(r"[\s-]", "", (phone or "").strip())
    if digits.startswith("+86"):
        digits = digits[3:]
    elif digits.startswith("86") and len(digits) == 13:
        digits = digits[2:]
    if not re.fullmatch(r"1[3-9]\d{9}", digits):
        raise InvalidArgument("Phone number must be a mainland China mobile number. It was not logged.")
    return digits


def _code(code: str) -> str:
    text = (code or "").strip()
    if not re.fullmatch(r"\d{4,8}", text):
        raise InvalidArgument("SMS code must be 4–8 digits. It was not logged.")
    return text


def _logged_out(url: str) -> dict:
    return NotLoggedIn(_LOGGED_OUT, url=url, reason="session_absent_or_replaced").payload()


def _logged_in(identity: dict) -> dict:
    return {
        "ok": True,
        "status": "logged_in",
        "logged_in": True,
        "nickname": identity.get("nickname"),
        "uid": identity.get("uid"),
        "url": identity.get("url"),
        "nickname_selector_verified_live": False,
    }


async def _body_text(page) -> str:
    try:
        return await page.inner_text("body")
    except Exception:
        return ""


async def _raise_with_shot(page, session, exc: SiteError) -> None:
    if exc.screenshot_path is None:
        exc.screenshot_path = await save_screenshot(page, session.config.screenshot_dir, exc.error_type, session.policy)
    if exc.url is None:
        try:
            exc.url = page.url
        except Exception:
            pass
    raise exc


async def _ensure_no_challenge(page, session) -> None:
    text = await _body_text(page)
    challenge = challenge_from_text(page.url, text)
    if challenge is None and await visible_challenge(page):
        challenge = NeedsHumanVerification(
            "A visible captcha or slider is on the page. No bypass was attempted.",
            url=page.url,
            status="needs_human_verification",
        )
    if challenge is not None:
        await _raise_with_shot(page, session, challenge)


async def _click_exact(page, label: str, purpose: ClickPurpose) -> None:
    locator = page.get_by_text(label, exact=True)
    count = await locator.count()
    for index in range(min(count, 6)):
        item = locator.nth(index)
        try:
            box = await item.bounding_box()
        except Exception:
            continue
        if not box or box.get("width", 0) < 8 or box.get("height", 0) < 8:
            continue
        await safe_click(item, purpose)
        return
    raise LoginUiNotFound(f"Could not find a visible login control labelled {label}.", selectors_tried=[label])


async def _maybe_terms(page) -> None:
    locator = page.locator("input[type='checkbox']")
    try:
        count = await locator.count()
    except Exception:
        return
    for index in range(min(count, 3)):
        item = locator.nth(index)
        try:
            box = await item.bounding_box()
            if not box or box.get("width", 0) < 8:
                continue
            if await item.is_checked():
                return
            await safe_click(item, ClickPurpose.ACCEPT_LOGIN_TERMS)
            return
        except SiteError:
            raise
        except Exception:
            continue


async def _open_login(page, session) -> str:
    try:
        return await goto_allowed(page, LOGIN_URL, session.policy, session)
    except FeedBlocked as exc:
        # A logged-in visit to /login often redirects at the recommendation feed.
        # Leave it immediately and inspect the search page header instead.
        log.info("login url redirected to a feed; checking the search page instead")
        await goto_allowed(page, xhs_search_url("."), session.policy, session)
        exc.url = page.url
        return page.url


async def _read_identity(page, session) -> dict:
    await _open_login(page, session)
    try:
        await page.wait_for_selector("img.qrcode-img, input[placeholder*='手机号'], .user-name", timeout=8000)
    except Exception:
        pass
    await _ensure_no_challenge(page, session)
    text = await _body_text(page)
    html = await page.content()
    identity = parse_xhs_identity(html, page.url, text)
    if identity["logged_in"] is None and "登录后查看搜索结果" not in text:
        # The login form was not showing. Look at search once more for a nickname.
        if "/search_result" not in (page.url or ""):
            await goto_allowed(page, xhs_search_url("."), session.policy, session)
            await _ensure_no_challenge(page, session)
            text = await _body_text(page)
            html = await page.content()
            identity = parse_xhs_identity(html, page.url, text)
    identity["url"] = page.url
    return await _attach_profile_name(page, session, identity)


async def _attach_profile_name(page, session, identity: dict) -> dict:
    """The search header exposes a uid. The nickname is on that user's profile, not the feed."""
    if identity.get("logged_in") is not True or identity.get("nickname") or not identity.get("uid"):
        return identity
    url = xhs_profile_url(identity["uid"])
    if session.policy.classify(url) != "allow":
        return identity
    try:
        await goto_allowed(page, url, session.policy, session)
    except FeedBlocked:
        return identity
    try:
        await page.wait_for_selector(".user-name, .user-nickname", timeout=8000)
    except Exception:
        pass
    html = await page.content()
    name = parse_xhs_profile_name(html)
    if name:
        identity["nickname"] = name
        identity["nickname_from"] = "user_profile"
    identity["url"] = page.url
    return identity


def sms_second_factor(text: str) -> dict | None:
    """New-device modal. The phone on the page is already masked. Do not resend the code."""
    if "短信验证码验证" not in text and "验证码已发送至" not in text:
        return None
    match = _MASKED_PHONE.search(text or "")
    masked = match.group(1) if match else ""
    return {
        "pending": "sms_verification_required",
        "masked_phone": masked,
        "message": (
            "新设备需要短信验证码。页面上的码已经发出，请把收到的数字传给 login_sms_submit。"
            "不要点重新发送；过期后再由人决定要不要重发。"
        ),
    }


async def login_status(session) -> dict:
    try:
        identity = await session.call("login_status", lambda page: _read_identity(page, session))
    except SiteError as exc:
        return exc.payload()
    except Exception as exc:
        log.exception("login_status failed")
        return {"ok": False, "error_type": "internal_error", "status": "internal_error", "message": redact(str(exc))[:300]}
    if identity["logged_in"] is False:
        return _logged_out(identity.get("url") or "")
    if identity["logged_in"] is True:
        return _logged_in(identity)
    return PageNotUnderstood(
        "The login check did not show the login form, a risk-control page, or a nickname/uid. "
        "Not claiming this session is logged in.",
        url=identity.get("url"),
        status="login_state_unclear",
    ).payload()


async def _capture_qr(page, dest) -> bool:
    dest.parent.mkdir(parents=True, exist_ok=True)
    for selector in ("img.qrcode-img", ".qrcode-img"):
        locator = page.locator(selector).first
        try:
            if await locator.count() == 0:
                continue
            box = await locator.bounding_box()
            if not box or box.get("width", 0) < 80 or box.get("height", 0) < 80:
                continue
            await locator.screenshot(path=str(dest))
            return True
        except Exception:
            continue
    return False


async def login_qr_start(session) -> dict:
    async def op(page):
        identity = await _read_identity(page, session)
        if identity["logged_in"] is True:
            payload = _logged_in(identity)
            payload["status"] = "already_logged_in"
            return payload
        if "/login" not in (page.url or ""):
            await goto_allowed(page, LOGIN_URL, session.policy, session)
        try:
            await page.wait_for_selector("img.qrcode-img", timeout=10000)
        except Exception:
            pass
        await _ensure_no_challenge(page, session)
        if not await _capture_qr(page, session.config.qr_path):
            raise LoginUiNotFound(
                "The login page did not show img.qrcode-img. Headless Chrome on this network was sent to a risk page; headed mode loaded the QR.",
                url=page.url,
                selectors_tried=["img.qrcode-img"],
            )
        return {
            "ok": True,
            "status": "qr_ready",
            "message": "Scan this QR with the Xiaohongshu or WeChat app. A new web login replaces other web sessions of this account.",
            "qr_path": str(session.config.qr_path),
            "url": page.url,
            "_image_path": str(session.config.qr_path),
        }

    try:
        return await session.call("login_qr_start", op)
    except SiteError as exc:
        return exc.payload()
    except Exception as exc:
        log.exception("login_qr_start failed")
        return {"ok": False, "error_type": "internal_error", "status": "internal_error", "message": redact(str(exc))[:300]}


async def _qr_visible(page) -> bool:
    locator = page.locator("img.qrcode-img").first
    try:
        if await locator.count() == 0:
            return False
        box = await locator.bounding_box()
    except Exception:
        return False
    return bool(box and box.get("width", 0) >= 80 and box.get("height", 0) >= 80)


async def _qr_text(page) -> str:
    # Visible text, not a single widget: the expiry line is not always inside one class.
    try:
        return await page.inner_text("body")
    except Exception:
        return ""


async def login_qr_wait(session, timeout_s: float = 90) -> dict:
    if not isinstance(timeout_s, (int, float)) or isinstance(timeout_s, bool) or not 1 <= float(timeout_s) <= 180:
        return InvalidArgument("timeout_s must be between 1 and 180.").payload()

    async def op(page):
        # Do not open the login URL here. A second navigation replaces the QR.
        # Scanned-but-not-confirmed stays inside this call until the timeout.
        text = await _qr_text(page)
        if text_says_expired(text):
            raise expired_error(page.url)
        factor = sms_second_factor(text)
        if factor is not None:
            factor["url"] = page.url
            return factor
        deadline = time.monotonic() + float(timeout_s)
        saw_confirm = False
        while time.monotonic() < deadline:
            await _ensure_no_challenge(page, session)
            text = await _qr_text(page)
            if text_says_expired(text):
                raise expired_error(page.url)
            factor = sms_second_factor(text)
            if factor is not None:
                factor["url"] = page.url
                return factor
            if any(phrase in text for phrase in _QR_CONFIRM):
                saw_confirm = True
            elif not await _qr_visible(page) and "/login" not in (page.url or "") and "website-login/error" not in (page.url or ""):
                identity = await _read_identity(page, session)
                if identity.get("logged_in") is True or identity.get("logged_in") is False:
                    return identity
            await page.wait_for_timeout(2000)
        text = await _qr_text(page)
        if text_says_expired(text):
            raise expired_error(page.url)
        factor = sms_second_factor(text)
        if factor is not None:
            factor["url"] = page.url
            return factor
        if saw_confirm:
            return {"logged_in": None, "pending": "awaiting_confirmation", "url": page.url}
        if await _qr_visible(page):
            return {"logged_in": None, "pending": "qr_pending", "url": page.url}
        if "/login" not in (page.url or "") and "website-login/error" not in (page.url or ""):
            return await _read_identity(page, session)
        return {"logged_in": None, "pending": "qr_not_ready", "url": page.url}

    try:
        identity = await session.call("login_qr_wait", op)
    except SiteError as exc:
        return exc.payload()
    except Exception as exc:
        log.exception("login_qr_wait failed")
        return {"ok": False, "error_type": "internal_error", "status": "internal_error", "message": redact(str(exc))[:300]}
    if identity.get("logged_in") is True:
        return _logged_in(identity)
    if identity.get("logged_in") is False:
        return _logged_out(identity.get("url") or "")
    pending = identity.get("pending")
    url = identity.get("url")
    if pending == "sms_verification_required":
        return {
            "ok": True,
            "status": "sms_verification_required",
            "logged_in": False,
            "masked_phone": identity.get("masked_phone") or "",
            "message": identity.get("message"),
            "url": url,
        }
    if pending == "qr_pending":
        return pending_payload(url)
    if pending == "qr_not_ready":
        return not_ready_payload(url)
    if pending == "awaiting_confirmation":
        return {
            "ok": True,
            "status": "awaiting_confirmation",
            "message": "页面显示已经扫到。请在手机上确认。确认后再次调用 login_qr_wait。新的网页登录会使这个账号的其他网页会话失效。",
            "url": url,
        }
    return {
        "ok": False,
        "error_type": "timeout",
        "status": "timeout",
        "message": "这次等待结束时二维码还没确认。如果它还在页面上，再次调用 login_qr_wait，不要重新 login_qr_start。",
        "url": url,
    }


async def login_sms_request(session, phone: str) -> dict:
    try:
        number = _phone(phone)
    except SiteError as exc:
        return exc.payload()

    async def op(page):
        await goto_allowed(page, LOGIN_URL, session.policy, session)
        await _ensure_no_challenge(page, session)
        await _maybe_terms(page)
        field = page.locator("input[placeholder*='手机号']").first
        if await field.count() == 0:
            raise LoginUiNotFound("Could not find the phone input.", url=page.url, selectors_tried=["input[placeholder*='手机号']"])
        await safe_fill(field, number, FillPurpose.PHONE)
        await _click_exact(page, "获取验证码", ClickPurpose.REQUEST_SMS_CODE)
        await page.wait_for_timeout(800)
        await _ensure_no_challenge(page, session)
        text = await _body_text(page)
        hint = "Requested an SMS code. It is never logged. A new web login replaces other web sessions of this account."
        for phrase in ("验证码已发送", "发送成功", "请稍后再试", "过于频繁", "请同意", "请阅读"):
            if phrase in text:
                hint = f"The page said: {phrase}. {hint}"
                break
        return {"ok": True, "status": "code_requested", "message": hint, "url": page.url}

    try:
        return await session.call("login_sms_request", op)
    except SiteError as exc:
        return exc.payload()
    except Exception as exc:
        log.exception("login_sms_request failed")
        return {"ok": False, "error_type": "internal_error", "status": "internal_error", "message": redact(str(exc))[:300]}


async def login_sms_submit(session, code: str) -> dict:
    try:
        sms = _code(code)
    except SiteError as exc:
        return exc.payload()

    async def op(page):
        field = page.locator("input[placeholder*='验证码']").first
        if await field.count() == 0:
            raise LoginUiNotFound(
                "The SMS code field is not on the current page. Call login_sms_request first.",
                url=page.url,
            )
        await safe_fill(field, sms, FillPurpose.SMS_CODE)
        await _maybe_terms(page)
        await page.wait_for_timeout(300)
        text = await _body_text(page)
        # The new-device modal's button is 验证. Do not click 重新发送; the code was already sent.
        if sms_second_factor(text) is not None:
            await _click_exact(page, "验证", ClickPurpose.SUBMIT_LOGIN)
        else:
            await _click_exact(page, "登录", ClickPurpose.SUBMIT_LOGIN)
        try:
            await page.wait_for_timeout(2000)
        except Exception:
            pass
        blocked = getattr(session, "last_blocked_url", None) or ""
        if session.policy.classify(blocked) == "feed":
            # 验证 succeeds by navigating to the home feed, which this server refuses.
            # The session is the part that matters; confirm it on a non-feed page.
            return await _read_identity(page, session)
        await _ensure_no_challenge(page, session)
        text = await _body_text(page)
        if any(phrase in text for phrase in ("验证码错误", "验证码不正确", "验证码已过期")):
            raise SmsRejected("The site rejected the SMS code. The code was not logged.", url=page.url)
        if any(phrase in text for phrase in ("请先同意", "请阅读并同意", "请勾选")):
            raise SmsFormNotReady(
                "The site still wants the agreement checkbox. Tick it in headed mode; this server will not click through a dialog.",
                url=page.url,
            )
        return await _read_identity(page, session)

    try:
        identity = await session.call("login_sms_submit", op)
    except SiteError as exc:
        return exc.payload()
    except Exception as exc:
        log.exception("login_sms_submit failed")
        return {"ok": False, "error_type": "internal_error", "status": "internal_error", "message": redact(str(exc))[:300]}
    if identity.get("logged_in") is True:
        return _logged_in(identity)
    if identity.get("logged_in") is False:
        return _logged_out(identity.get("url") or "")
    return PageNotUnderstood(
        "The form was submitted, but no nickname or uid was visible.",
        url=identity.get("url"),
        status="login_state_unclear",
    ).payload()


async def _collect_notes(page, session, keyword: str, limit: int) -> dict:
    url = xhs_search_url(keyword)
    final = await goto_allowed(page, url, session.policy, session)
    try:
        await page.wait_for_selector("section.note-item, img.qrcode-img, input[placeholder*='手机号']", timeout=12000)
    except Exception:
        pass
    await page.wait_for_timeout(500)
    await _ensure_no_challenge(page, session)
    scrolls = 0
    html = await page.content()
    text = await _body_text(page)
    outcome = classify_xhs_search(html, page.url or final, text)
    while outcome["kind"] == "results" and len(outcome["notes"]) < limit and scrolls < 3:
        before = len(outcome["notes"])
        try:
            await page.mouse.wheel(0, 1400)
        except Exception:
            break
        await page.wait_for_timeout(800)
        html = await page.content()
        text = await _body_text(page)
        outcome = classify_xhs_search(html, page.url, text)
        scrolls += 1
        if outcome["kind"] != "results" or len(outcome.get("notes") or []) <= before:
            break
    outcome["url"] = page.url or final
    outcome["text"] = text
    return outcome


async def search_notes(session, keyword: str, limit: int = 10) -> dict:
    try:
        text = _keyword(keyword)
        limit_n = _limit(limit)
    except SiteError as exc:
        return exc.payload()

    try:
        outcome = await session.call("search", lambda page: _collect_notes(page, session, text, limit_n))
    except SiteError as exc:
        return exc.payload()
    except Exception as exc:
        log.exception("search failed")
        return {"ok": False, "error_type": "internal_error", "status": "internal_error", "message": redact(str(exc))[:300]}
    landed = outcome.get("url")
    if outcome["kind"] == "needs_human_verification":
        return NeedsHumanVerification(
            "Xiaohongshu showed a risk-control or verification page instead of search results. No bypass was attempted. "
            "Headless Chrome hit this on a US network; a visible window loaded the normal login page instead.",
            url=landed,
        ).payload()
    if outcome["kind"] == "logged_out":
        return _logged_out(landed or "")
    if outcome["kind"] == "no_results":
        return {
            "ok": True,
            "status": "no_results",
            "keyword": text,
            "count": 0,
            "results": [],
            "has_more": False,
            "url": landed,
        }
    if outcome["kind"] != "results":
        return PageNotUnderstood(
            "The search page loaded but there were no note cards, no login wall, and no empty-state message. "
            "This is not reported as zero results. Note-card selectors were not confirmed while logged in.",
            url=landed,
            status="page_not_understood",
            body_excerpt=redact(outcome.get("text") or "")[:180],
        ).payload()
    notes = outcome["notes"]
    return {
        "ok": True,
        "status": "results",
        "keyword": text,
        "count": min(len(notes), limit_n),
        "results": notes[:limit_n],
        "has_more": len(notes) > limit_n,
        "parser_id": outcome.get("parser_id"),
        "url": landed,
        "note_card_selectors_verified_live": False,
    }


async def get_note(session, url: str) -> dict:
    target = (url or "").strip()
    if not session.policy.is_note(target):
        return InvalidArgument(
            "url must be a Xiaohongshu note page such as /explore/{id}, including the xsec_token query the page itself showed. The explore feed is refused."
        ).payload()

    async def op(page):
        final = await goto_allowed(page, target, session.policy, session)
        try:
            await page.wait_for_selector("#detail-title, .note-content .title, img.qrcode-img", timeout=12000)
        except Exception:
            pass
        await _ensure_no_challenge(page, session)
        html = await page.content()
        text = await _body_text(page)
        return final, html, text, page.url

    try:
        final, html, text, landed = await session.call("get_note", op)
    except SiteError as exc:
        return exc.payload()
    except Exception as exc:
        log.exception("get_note failed")
        return {"ok": False, "error_type": "internal_error", "status": "internal_error", "message": redact(str(exc))[:300]}
    parsed = parse_xhs_note(html, landed or target)
    if parsed is None:
        if "手机号登录" in text and "获取验证码" in text:
            return _logged_out(landed or final)
        return PageNotUnderstood(
            "The note page did not contain a detail title. These selectors were not confirmed while logged in.",
            url=landed or final,
            status="page_not_understood",
        ).payload()
    parsed.update({"ok": True, "status": "ok", "detail_selectors_verified_live": False})
    return parsed
