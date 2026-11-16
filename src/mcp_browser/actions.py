"""Navigation and input helpers. Clicks go through the read-only gate."""

from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from mcp_browser.errors import FeedBlocked, NavigationDenied, PageLoadFailed, SiteError
from mcp_browser.guard import ClickPurpose, ClickTarget, FillPurpose, assert_click_allowed, assert_fill_allowed
from mcp_browser.policy import ALLOW, FEED, DocumentPolicy
from mcp_browser.redact import redact

log = logging.getLogger(__name__)


def page_load_message(exc: BaseException, url: str) -> str:
    """Turn a Playwright navigation error into something an operator can act on."""
    text = str(exc)
    if "download is starting" in text.lower():
        return (
            "The page did not load as a document. The browser started a download instead, "
            "which usually means this URL is not an HTML page (often HTTP 404). "
            f"URL: {url}"
        )
    return redact(text)[:300]


def _target_from_attributes(attrs: dict[str, str], text: str) -> ClickTarget:
    return ClickTarget(
        text=text,
        aria=attrs.get("aria-label") or "",
        title=attrs.get("title") or "",
        class_name=attrs.get("class") or "",
        elem_id=attrs.get("id") or "",
        href=attrs.get("href") or "",
        placeholder=attrs.get("placeholder") or "",
        input_type=attrs.get("type") or "",
        name=attrs.get("name") or "",
    )


async def _read_target(locator: Any) -> ClickTarget:
    text = ""
    try:
        text = (await locator.inner_text() or "").strip()
    except Exception:
        text = ""
    attrs: dict[str, str] = {}
    for key in ("aria-label", "title", "class", "id", "href", "placeholder", "type", "name"):
        try:
            value = await locator.get_attribute(key)
        except Exception:
            value = None
        if value:
            attrs[key] = value
    return _target_from_attributes(attrs, text)


async def safe_click(locator: Any, purpose: ClickPurpose) -> None:
    target = await _read_target(locator)
    assert_click_allowed(purpose, target)
    await locator.click(timeout=5000)


async def safe_fill(locator: Any, value: str, purpose: FillPurpose) -> None:
    target = await _read_target(locator)
    assert_fill_allowed(purpose, target)
    await locator.fill(value, timeout=5000)


def _navigation_aborted(exc: BaseException) -> bool:
    text = str(exc).lower()
    return "err_aborted" in text or "interrupted by another navigation" in text


def _hostname(url: str) -> str:
    return (urlsplit(url).hostname or "").lower()


def _aborted_landing_ok(requested: str, landed: str, policy: DocumentPolicy) -> bool:
    """A client redirect may change the query, or move account home onto the passport document."""
    if policy.classify(landed) != ALLOW:
        return False
    landed_host = _hostname(landed)
    requested_host = _hostname(requested)
    if not landed_host:
        return False
    if landed_host == requested_host:
        return True
    return landed_host == "passport.bilibili.com" and requested_host.endswith("bilibili.com")


async def _url_after_abort(page: Any, timeout_s: float = 8) -> str:
    """Wait until a redirect that aborted `goto` has a stable document URL.

    `page.wait_for_timeout` itself throws while that navigation is still being
    replaced, so the wait uses asyncio. The page is left in place.
    """
    deadline = time.monotonic() + timeout_s
    last = ""
    stable = 0
    while time.monotonic() < deadline:
        try:
            await page.wait_for_load_state("domcontentloaded", timeout=1000)
        except Exception:
            pass
        try:
            current = page.url or ""
        except Exception:
            current = ""
        usable = current not in {"", "about:blank"} and not current.startswith("chrome-error:")
        if usable and current == last:
            stable += 1
            if stable >= 2:
                return current
        else:
            stable = 0
        last = current
        await asyncio.sleep(0.25)
    if last in {"", "about:blank"} or last.startswith("chrome-error:"):
        return ""
    return last


async def _blank(page: Any) -> None:
    try:
        await page.goto("about:blank", wait_until="domcontentloaded", timeout=5000)
    except Exception:
        log.debug("could not leave the blocked document")


async def goto_allowed(
    page: Any,
    url: str,
    policy: DocumentPolicy,
    session: Any | None = None,
    *,
    timeout_ms: int = 30000,
) -> str:
    decision = policy.classify(url)
    if decision == FEED:
        raise FeedBlocked(
            "Refusing to open a home or recommendation feed.",
            url=url,
        )
    if decision != ALLOW:
        raise NavigationDenied("That URL is not on the allowlist for this server.", url=url)
    if session is not None:
        session.last_blocked_url = None
    try:
        response = await page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
    except Exception as exc:
        blocked = getattr(session, "last_blocked_url", None) if session is not None else None
        if blocked and policy.classify(blocked) == FEED:
            await _blank(page)
            raise FeedBlocked(
                "The page redirected to a home or recommendation feed. No feed content was read.",
                url=blocked,
            ) from exc
        if blocked:
            await _blank(page)
            raise NavigationDenied("Navigation left the allowlist.", url=blocked) from exc
        # passport.bilibili.com/pc/passport/login replaces itself with ?site=OVERSEAS&lang=...
        # Chrome aborts the first navigation. The document that remains is the login page.
        if _navigation_aborted(exc):
            final = await _url_after_abort(page)
            decision = policy.classify(final)
            if decision == FEED:
                await _blank(page)
                raise FeedBlocked(
                    "The page redirected to a home or recommendation feed. No feed content was read.",
                    url=final,
                ) from exc
            if _aborted_landing_ok(url, final, policy):
                log.info("navigation aborted by a same-site redirect; using the settled document")
                return final
            await _blank(page)
            raise PageLoadFailed(page_load_message(exc, final or url), url=final or url) from exc
        await _blank(page)
        raise PageLoadFailed(page_load_message(exc, url), url=url) from exc
    final = page.url
    final_decision = policy.classify(final)
    if final_decision == FEED:
        await _blank(page)
        raise FeedBlocked(
            "The page redirected to a home or recommendation feed. No feed content was read.",
            url=final,
        )
    if final_decision != ALLOW:
        await _blank(page)
        raise NavigationDenied("Landed on a URL that is not allowlisted.", url=final)
    status = getattr(response, "status", None) if response is not None else None
    if isinstance(status, int) and status >= 400:
        await _blank(page)
        raise PageLoadFailed(
            f"The page failed to load (HTTP {status}). URL: {final or url}",
            url=final or url,
            http_status=status,
        )
    return final


async def save_screenshot(page: Any, directory: Path, name: str, policy: DocumentPolicy) -> str | None:
    try:
        current = page.url
    except Exception:
        return None
    if policy.classify(current) != ALLOW:
        return None
    directory.mkdir(parents=True, exist_ok=True)
    from datetime import datetime

    path = directory / f"{name}-{datetime.now().strftime('%Y%m%d-%H%M%S')}.png"
    try:
        await page.screenshot(path=str(path), full_page=False)
    except Exception:
        log.warning("screenshot failed for %s", name)
        return None
    return str(path)


async def visible_challenge(page: Any) -> bool:
    """True when a captcha widget is actually on screen, not merely present in the DOM."""
    selectors = (
        ".geetest_panel",
        ".geetest_holder",
        ".body__captcha-input",
        ".captcha-box",
        "input[placeholder*='图片']",
    )
    for selector in selectors:
        locator = page.locator(selector).first
        try:
            if await locator.count() == 0:
                continue
            box = await locator.bounding_box()
        except Exception:
            continue
        if box and box.get("width", 0) > 40 and box.get("height", 0) > 20:
            return True
    return False


def challenge_from_text(url: str, text: str) -> SiteError | None:
    from mcp_browser.errors import NeedsHumanVerification

    lowered = url.lower()
    if "website-login/error" in lowered or "error_code=300012" in lowered:
        return NeedsHumanVerification(
            "Xiaohongshu showed a risk-control page (network risk / error 300012). "
            "No bypass was attempted. Switch to a network the site accepts, or set headed mode "
            "and complete the check in the visible window, then retry.",
            url=url,
            status="needs_human_verification",
        )
    for phrase in ("当前网络存在风险", "安全限制", "安全验证", "滑动验证", "请完成验证", "人机验证"):
        if phrase in text:
            return NeedsHumanVerification(
                f"The page is asking for a human check ({phrase}). No bypass was attempted.",
                url=url,
                status="needs_human_verification",
            )
    return None
