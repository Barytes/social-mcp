"""One persistent Chrome context per server, serialized, with crash recovery."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import TypeVar
from urllib.parse import urlsplit

from mcp_browser.config import SiteConfig
from mcp_browser.errors import BrowserFailed, SiteError
from mcp_browser.policy import ALLOW, FEED, DocumentPolicy
from mcp_browser.singleton import prepare_profile

log = logging.getLogger(__name__)

_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
_FRAMELESS_MARKERS = (
    "service worker",
    "associated frame",
    "frame for this navigation request is not available",
)

T = TypeVar("T")

_CLOSED_MARKERS = (
    "has been closed",
    "target closed",
    "browser closed",
    "connection closed",
    "browser has disconnected",
)


def document_log_target(url: str) -> tuple[str, str]:
    """Host and path only. Query strings can carry xsec_token and must not be logged."""
    parts = urlsplit(url or "")
    return parts.hostname or "", parts.path or ""


async def keep_one_page(context, policy: DocumentPolicy):
    """Drop restored tabs. If the one that remains is a feed, leave it for about:blank."""
    pages = list(context.pages)
    for extra in pages[1:]:
        try:
            await extra.close()
        except Exception:
            log.info("could not close a restored tab")
    remaining = list(context.pages)
    page = remaining[0] if remaining else await context.new_page()
    try:
        current = page.url or ""
    except Exception:
        current = ""
    if current and policy.classify(current) != ALLOW:
        try:
            await page.goto("about:blank", wait_until="domcontentloaded", timeout=5000)
        except Exception:
            log.info("could not leave a restored tab")
    return page


def is_browser_closed(exc: BaseException) -> bool:
    message = str(exc).lower()
    return any(marker in message for marker in _CLOSED_MARKERS)


def _lookup_frame(request) -> tuple[object | None, str]:
    """Return the frame and why it is missing.

    Service-worker requests raise from `request.frame`. A navigation issued before
    its frame exists raises a different error. Both still have to face the allowlist.
    """
    try:
        return request.frame, "frame"
    except Exception as exc:
        message = str(exc).lower()
        if "service worker" in message or "associated frame" in message:
            return None, "service_worker"
        if "frame for this navigation request is not available" in message:
            return None, "early_navigation"
        if any(marker in message for marker in _FRAMELESS_MARKERS):
            return None, "service_worker"
        raise


def _is_navigation(request) -> bool:
    try:
        return bool(request.is_navigation_request())
    except Exception:
        return False


def _resource_type(request) -> str:
    try:
        return request.resource_type or ""
    except Exception:
        return ""


def _method(request) -> str:
    try:
        return (request.method or "GET").upper()
    except Exception:
        return "GET"


def is_main_document(request) -> bool:
    frame, kind = _lookup_frame(request)
    navigation = _is_navigation(request)
    if kind == "frame":
        parent = getattr(frame, "parent_frame", None)
        return navigation and parent is None
    # No frame: service worker, or a navigation that started before the frame existed.
    # A document load is still a document load.
    return navigation or _resource_type(request) == "document"


def should_block_request(policy: DocumentPolicy, request) -> bool:
    """Block feed documents and anything a service worker must not be allowed to do.

    Frameless requests are not given a free pass. Feed URLs are refused even when
    they are not the main document, and a service worker may not send a write method.
    Ordinary subresources (scripts, images, the page's own GET fetches) continue,
    matching framed requests: we do not read those bodies, and we do not turn them
    into a data source.
    """
    url = request.url
    decision = policy.classify(url)
    if decision == FEED:
        return True
    _frame, kind = _lookup_frame(request)
    if kind == "service_worker" and _method(request) not in _SAFE_METHODS:
        return True
    if is_main_document(request) and decision != ALLOW:
        return True
    return False


class BrowserSession:
    """Owns the Playwright persistent context. Callers share it through `call`."""

    def __init__(self, config: SiteConfig, policy: DocumentPolicy) -> None:
        self.config = config
        self.policy = policy
        self.last_blocked_url: str | None = None
        self.last_allowed_document: str | None = None
        self._lock = None  # created lazily so importing this module does not require a running loop
        self._playwright = None
        self._context = None
        self._page = None

    def _mutex(self):
        if self._lock is None:
            import asyncio

            self._lock = asyncio.Lock()
        return self._lock

    async def call(self, operation: str, func: Callable[..., Awaitable[T]]) -> T:
        async with self._mutex():
            await self._ensure()
            try:
                return await func(self._page)
            except SiteError:
                raise
            except Exception as exc:
                if not is_browser_closed(exc):
                    raise
                log.warning("browser closed during %s; restarting once", operation)
                await self._dispose()
                await self._ensure()
                return await func(self._page)

    async def shutdown(self) -> None:
        async with self._mutex():
            await self._dispose()

    async def _ensure(self) -> None:
        if self._context is not None:
            try:
                if self._page is None or self._page.is_closed():
                    await self._dispose()
            except Exception:
                await self._dispose()
        if self._context is not None:
            return
        chrome = self.config.chrome_path
        from pathlib import Path

        if not Path(chrome).is_file():
            raise BrowserFailed(
                f"System Chrome was not found at {chrome}. Set MCP_CHROME_PATH or the site-specific override.",
            )
        try:
            prepare_profile(self.config.profile_dir)
        except SiteError:
            raise
        log.info(
            "starting chrome profile=%s headed=%s",
            self.config.profile_dir,
            self.config.headed,
        )
        try:
            from playwright.async_api import async_playwright

            self._playwright = await async_playwright().start()
            self._context = await self._playwright.chromium.launch_persistent_context(
                user_data_dir=str(self.config.profile_dir),
                executable_path=chrome,
                headless=not self.config.headed,
                viewport={"width": 1366, "height": 900},
                locale="zh-CN",
                args=[
                    "--disable-dev-shm-usage",
                    "--no-first-run",
                    "--no-default-browser-check",
                    "--disable-sync",
                    "--disable-features=Translate",
                    "--disable-session-crashed-bubble",
                    "--hide-crash-restore-bubble",
                ],
                timeout=60_000,
            )
            self._context.set_default_navigation_timeout(30_000)
            self._context.set_default_timeout(15_000)
            await self._context.route("**/*", self._route)
            self._page = await keep_one_page(self._context, self.policy)
        except Exception as exc:
            await self._dispose()
            message = str(exc)
            if "in use" in message.lower() or "singleton" in message.lower():
                from mcp_browser.errors import ProfileInUse

                raise ProfileInUse(
                    "Chrome refused to open this profile because another process holds it.",
                    profile_dir=str(self.config.profile_dir),
                ) from exc
            raise BrowserFailed(f"Chrome failed to start: {message[:300]}") from exc

    async def _route(self, route) -> None:
        request = route.request
        try:
            blocked = should_block_request(self.policy, request)
        except Exception:
            log.warning("could not classify a request; aborting it")
            await route.abort()
            return
        if blocked:
            try:
                self.last_blocked_url = request.url
                host, path = document_log_target(request.url)
            except Exception:
                self.last_blocked_url = None
                host, path = "", ""
            log.warning("blocked document navigation host=%s path=%s", host, path)
            await route.abort()
            return
        try:
            if is_main_document(request):
                self.last_allowed_document = request.url
        except Exception:
            pass
        await route.continue_()

    async def _dispose(self) -> None:
        context = self._context
        playwright = self._playwright
        self._context = None
        self._page = None
        self._playwright = None
        if context is not None:
            try:
                await asyncio.wait_for(context.close(), timeout=15)
            except Exception:
                log.warning("closing the browser context failed", exc_info=True)
        if playwright is not None:
            try:
                await asyncio.wait_for(playwright.stop(), timeout=10)
            except Exception:
                log.warning("stopping Playwright failed", exc_info=True)
