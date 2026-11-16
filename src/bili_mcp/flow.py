"""Bilibili login and search. Every browser call holds the single-session lock."""

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
    InvalidArgument,
    LoginUiNotFound,
    NeedsHumanVerification,
    NotLoggedIn,
    PageLoadFailed,
    PageNotUnderstood,
    SiteError,
    SmsFormNotReady,
    SmsRejected,
)
from mcp_browser.guard import ClickPurpose, FillPurpose
from mcp_browser.qr import expired_error, not_ready_payload, pending_payload, text_says_expired
from mcp_browser.redact import redact

from bili_mcp.parse import classify_bili_search, parse_bili_identity, parse_bili_video
from bili_mcp.urls import ACCOUNT_URL, LOGIN_URL, bili_search_url, bili_video_url

log = logging.getLogger(__name__)

_BVID = re.compile(r"^BV[0-9A-Za-z]{10}$")
_QR_CONFIRM = ("扫描成功", "请在手机上确认", "确认登录")


def _keyword(keyword: str) -> str:
    text = (keyword or "").strip()
    if not text or len(text) > 80 or re.search(r"[\x00-\x1f]", text):
        raise InvalidArgument("keyword must be 1–80 characters and contain no control characters.")
    return text


def _limit(limit: int) -> int:
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 30:
        raise InvalidArgument("limit must be an integer from 1 to 30.")
    return limit


def _page(page: int) -> int:
    if isinstance(page, bool) or not isinstance(page, int) or not 1 <= page <= 50:
        raise InvalidArgument("page must be an integer from 1 to 50.")
    return page


def _bvid(bvid: str) -> str:
    text = (bvid or "").strip()
    if not _BVID.fullmatch(text):
        raise InvalidArgument("bvid must look like BV followed by 10 letters or digits.")
    return text


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


async def _shot(page, session, name: str) -> str | None:
    return await save_screenshot(page, session.config.screenshot_dir, name, session.policy)


async def _raise_with_shot(page, session, exc: SiteError) -> None:
    if exc.screenshot_path is None:
        exc.screenshot_path = await _shot(page, session, exc.error_type)
    if exc.url is None:
        try:
            exc.url = page.url
        except Exception:
            pass
    raise exc


async def _body_text(page) -> str:
    try:
        return await page.inner_text("body")
    except Exception:
        return ""


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
    raise LoginUiNotFound(
        f"Could not find a visible login control labelled {label}.",
        selectors_tried=[label],
    )


async def _read_identity(page, session) -> dict:
    try:
        final = await goto_allowed(page, ACCOUNT_URL, session.policy, session)
    except PageLoadFailed:
        # A logged-out account page redirects at passport /login, which 404s and
        # Chrome may treat as a download. The PC passport page is the document.
        log.info("account page did not load; opening the official login page")
        final = await goto_allowed(page, LOGIN_URL, session.policy, session)
    try:
        await page.wait_for_selector(
            ".header-avatar-unlogin-entry, .home-name, .nickname, .user-name",
            timeout=8000,
        )
    except Exception:
        pass
    await _ensure_no_challenge(page, session)
    html = await page.content()
    identity = parse_bili_identity(html, page.url or final)
    identity["url"] = page.url or final
    return identity


def _logged_out(url: str) -> dict:
    return NotLoggedIn(
        "Not logged in. The account page redirected to the official login page.",
        url=url,
        reason="not_authenticated",
    ).payload()


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
        "The account page opened, but no nickname or uid was visible, and it was not the login page. "
        "Not claiming this session is logged in. Nickname selectors still need a logged-in check on your machine.",
        url=identity.get("url"),
        status="login_state_unclear",
    ).payload()


async def login_qr_start(session) -> dict:
    async def op(page):
        identity = await _read_identity(page, session)
        if identity["logged_in"] is True:
            payload = _logged_in(identity)
            payload["status"] = "already_logged_in"
            return payload
        # Account home often redirects here already. Opening the login URL again
        # aborts the document that is painting the QR.
        if "passport.bilibili.com" not in (page.url or ""):
            await goto_allowed(page, LOGIN_URL, session.policy, session)
        await _ensure_no_challenge(page, session)
        # Do not click Password login, Login, or SMS Login. Those controls stay on the
        # page so a person can use them in the headed window. Language (zh-Hans or en) is ignored.
        saved = await _capture_qr(page, session.config.qr_path)
        if not saved:
            raise LoginUiNotFound(
                "The official login page did not show a QR canvas inside .login-scan__qrcode. "
                "The code is drawn a few seconds after the document loads; lang=zh-Hans and lang=en use the same box.",
                url=page.url,
                selectors_tried=[".login-scan__qrcode canvas", ".login-scan__qrcode img", ".login-scan__qrcode"],
            )
        return {
            "ok": True,
            "status": "qr_ready",
            "message": (
                "Scan this QR with the Bilibili mobile app. The PNG is the canvas inside the QR box, outside the repo. "
                "Password login and SMS Login stay on the page; this tool does not type a password."
            ),
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


_QR_CANVAS = ".login-scan__qrcode canvas"
_QR_IMG = ".login-scan__qrcode img"
_QR_BOX = ".login-scan__qrcode"


async def _sized(page, selector: str, minimum: float = 80):
    locator = page.locator(selector).first
    try:
        if await locator.count() == 0:
            return None
        box = await locator.bounding_box()
    except Exception:
        return None
    if not box or box.get("width", 0) < minimum or box.get("height", 0) < minimum:
        return None
    return locator


async def _current_qr(page, *, allow_container: bool):
    """Prefer the canvas that actually paints the code, then a real image, then the box."""
    for selector in (_QR_CANVAS, _QR_IMG):
        found = await _sized(page, selector)
        if found is not None:
            return found
    if allow_container:
        return await _sized(page, _QR_BOX)
    return None


async def _capture_qr(page, dest) -> bool:
    dest.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + 15
    target = None
    while time.monotonic() < deadline:
        target = await _current_qr(page, allow_container=False)
        if target is not None:
            break
        await page.wait_for_timeout(400)
    if target is None:
        target = await _current_qr(page, allow_container=True)
    if target is None:
        return False
    # The bitmap is painted just after the element gets a size.
    try:
        await page.wait_for_timeout(400)
    except Exception:
        pass
    refreshed = await _current_qr(page, allow_container=False)
    if refreshed is not None:
        target = refreshed
    try:
        await target.screenshot(path=str(dest))
    except Exception:
        log.info("qr screenshot failed")
        return False
    try:
        return dest.is_file() and dest.stat().st_size > 32
    except OSError:
        return False


async def _qr_visible(page) -> bool:
    if await _current_qr(page, allow_container=False) is not None:
        return True
    return await _current_qr(page, allow_container=True) is not None


async def _qr_text(page) -> str:
    parts: list[str] = []
    locator = page.locator(".login-scan").first
    try:
        if await locator.count():
            parts.append(await locator.inner_text())
    except Exception:
        pass
    try:
        parts.append(await page.inner_text("body"))
    except Exception:
        pass
    return "\n".join(parts)


async def login_qr_wait(session, timeout_s: float = 90) -> dict:
    if not isinstance(timeout_s, (int, float)) or isinstance(timeout_s, bool) or not 1 <= float(timeout_s) <= 180:
        return InvalidArgument("timeout_s must be between 1 and 180.").payload()
    timeout_s = float(timeout_s)

    async def op(page):
        # Stay on the current document. Opening the login URL again would replace the QR.
        if text_says_expired(await _qr_text(page)):
            raise expired_error(page.url)
        if not await _qr_visible(page):
            if "passport.bilibili.com" not in (page.url or ""):
                return await _read_identity(page, session)
            return {"pending": "qr_not_ready", "url": page.url}
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            await _ensure_no_challenge(page, session)
            scan_text = await _qr_text(page)
            if text_says_expired(scan_text):
                raise expired_error(page.url)
            if not await _qr_visible(page):
                if "passport.bilibili.com" not in (page.url or ""):
                    return await _read_identity(page, session)
                return {"pending": "qr_not_ready", "url": page.url}
            if any(phrase in scan_text for phrase in _QR_CONFIRM):
                return {"logged_in": None, "pending": "awaiting_confirmation", "url": page.url}
            await page.wait_for_timeout(2000)
        if text_says_expired(await _qr_text(page)):
            raise expired_error(page.url)
        return {"logged_in": None, "pending": "qr_pending", "url": page.url}

    try:
        identity = await session.call("login_qr_wait", op)
    except SiteError as exc:
        return exc.payload()
    except Exception as exc:
        log.exception("login_qr_wait failed")
        return {"ok": False, "error_type": "internal_error", "status": "internal_error", "message": redact(str(exc))[:300]}
    return _finish_qr_wait(identity)


def _finish_qr_wait(identity: dict) -> dict:
    if identity.get("logged_in") is True:
        return _logged_in(identity)
    if identity.get("logged_in") is False:
        return _logged_out(identity.get("url") or "")
    pending = identity.get("pending")
    url = identity.get("url")
    if pending == "qr_pending":
        return pending_payload(url)
    if pending == "qr_not_ready":
        return not_ready_payload(url)
    if pending == "awaiting_confirmation":
        return {
            "ok": True,
            "status": "awaiting_confirmation",
            "message": "The page says the QR was scanned. Confirm it on the phone, then call login_qr_wait again.",
            "url": url,
        }
    return {
        "ok": False,
        "error_type": "timeout",
        "status": "timeout",
        "message": "The QR was not confirmed before the timeout. If it is still on screen, call login_qr_wait again.",
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
        await _click_exact(page, "短信登录", ClickPurpose.SWITCH_LOGIN_METHOD)
        await page.wait_for_timeout(300)
        field = page.locator("input[placeholder*='手机号']").first
        if await field.count() == 0:
            raise LoginUiNotFound("Could not find the phone input.", url=page.url, selectors_tried=["input[placeholder*='手机号']"])
        await safe_fill(field, number, FillPurpose.PHONE)
        await _click_exact(page, "获取验证码", ClickPurpose.REQUEST_SMS_CODE)
        await page.wait_for_timeout(800)
        await _ensure_no_challenge(page, session)
        text = await _body_text(page)
        return {"ok": True, "status": "code_requested", "message": _sms_hint(text), "url": page.url}

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
                "The SMS code field is not on the current page. Call login_sms_request first and stay on that page.",
                url=page.url,
            )
        await safe_fill(field, sms, FillPurpose.SMS_CODE)
        await page.wait_for_timeout(300)
        button = page.get_by_text("登录/注册", exact=True)
        if await button.count() == 0:
            button = page.get_by_text("登录", exact=True)
        target = None
        count = await button.count()
        for index in range(min(count, 6)):
            item = button.nth(index)
            box = await item.bounding_box()
            if box and box.get("width", 0) >= 8:
                target = item
                break
        if target is None:
            raise LoginUiNotFound("Could not find the login button.", url=page.url)
        class_name = (await target.get_attribute("class") or "")
        if "disabled" in class_name.split():
            raise SmsFormNotReady(
                "The login button is still disabled. The site did not accept the form, or a human check is required.",
                url=page.url,
            )
        await safe_click(target, ClickPurpose.SUBMIT_LOGIN)
        await page.wait_for_timeout(1500)
        await _ensure_no_challenge(page, session)
        text = await _body_text(page)
        if any(phrase in text for phrase in ("验证码错误", "验证码不正确", "验证码已过期")):
            raise SmsRejected("The site rejected the SMS code. The code was not logged.", url=page.url)
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
        "The form was submitted, but the account page did not show a nickname or uid.",
        url=identity.get("url"),
        status="login_state_unclear",
    ).payload()


def _sms_hint(text: str) -> str:
    for phrase in ("验证码已发送", "发送成功", "请稍后再试", "过于频繁", "格式不正确"):
        if phrase in text:
            return (
                f"The page said: {phrase}. An unregistered number can create an account; "
                "that is the official form, and the code was not logged."
            )
    return (
        "Requested an SMS code from the official login form. The code is never logged. "
        "An unregistered mobile number can create a Bilibili account because that is what this form does."
    )


async def search_videos(session, keyword: str, limit: int = 10, page: int = 1) -> dict:
    try:
        text = _keyword(keyword)
        limit_n = _limit(limit)
        page_n = _page(page)
    except SiteError as exc:
        return exc.payload()
    url = bili_search_url(text, page_n)

    async def op(browser_page):
        final = await goto_allowed(browser_page, url, session.policy, session)
        try:
            await browser_page.wait_for_selector(".bili-video-card__info--tit, .search-page", timeout=15000)
        except Exception:
            pass
        await _ensure_no_challenge(browser_page, session)
        html = await browser_page.content()
        body = await _body_text(browser_page)
        return final, html, body, browser_page.url

    try:
        final, html, body, landed = await session.call("search", op)
    except SiteError as exc:
        return exc.payload()
    except Exception as exc:
        log.exception("search failed")
        return {"ok": False, "error_type": "internal_error", "status": "internal_error", "message": redact(str(exc))[:300]}
    outcome = classify_bili_search(html, landed or final)
    if outcome["kind"] == "logged_out":
        return _logged_out(landed or final)
    if outcome["kind"] == "no_results":
        return {
            "ok": True,
            "status": "no_results",
            "keyword": text,
            "page": page_n,
            "count": 0,
            "results": [],
            "has_more": False,
            "url": landed or final,
        }
    if outcome["kind"] != "results":
        return PageNotUnderstood(
            "The search page loaded but no video cards and no empty-state message were found. This is not reported as zero results.",
            url=landed or final,
            status="page_not_understood",
            body_excerpt=redact(body)[:180],
        ).payload()
    videos = outcome["videos"]
    return {
        "ok": True,
        "status": "results",
        "keyword": text,
        "page": page_n,
        "count": min(len(videos), limit_n),
        "results": videos[:limit_n],
        "has_more": len(videos) > limit_n or outcome["has_more"],
        "parser_id": outcome["parser_id"],
        "url": landed or final,
    }


async def get_video(session, bvid: str) -> dict:
    try:
        video_id = _bvid(bvid)
    except SiteError as exc:
        return exc.payload()
    url = bili_video_url(video_id)

    async def op(page):
        final = await goto_allowed(page, url, session.policy, session)
        for _ in range(15):
            try:
                if await page.locator("h1.video-title").count():
                    break
            except Exception:
                pass
            await page.wait_for_timeout(1000)
        await _ensure_no_challenge(page, session)
        html = await page.content()
        return final, html, page.url

    try:
        final, html, landed = await session.call("get_video", op)
    except SiteError as exc:
        return exc.payload()
    except Exception as exc:
        log.exception("get_video failed")
        return {"ok": False, "error_type": "internal_error", "status": "internal_error", "message": redact(str(exc))[:300]}
    parsed = parse_bili_video(html, video_id)
    if parsed is None:
        return PageNotUnderstood(
            "The video page did not show h1.video-title. The page sometimes flashes an error shell before the player; the wait already retried.",
            url=landed or final,
            status="page_not_understood",
        ).payload()
    parsed.update({"ok": True, "status": "ok"})
    return parsed
