"""One persistent Chrome context per server, serialized, with crash recovery."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import TypeVar

from mcp_browser.config import SiteConfig
from mcp_browser.errors import BrowserFailed, SiteError
from mcp_browser.policy import ALLOW, DocumentPolicy
from mcp_browser.singleton import prepare_profile

log = logging.getLogger(__name__)

T = TypeVar("T")

_CLOSED_MARKERS = (
    "has been closed",
    "target closed",
    "browser closed",
    "connection closed",
    "browser has disconnected",
)


def is_browser_closed(exc: BaseException) -> bool:
    message = str(exc).lower()
    return any(marker in message for marker in _CLOSED_MARKERS)


class BrowserSession:
    """Owns the Playwright persistent context. Callers share it through `call`."""

    def __init__(self, config: SiteConfig, policy: DocumentPolicy) -> None:
        self.config = config
        self.policy = policy
        self.last_blocked_url: str | None = None
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
                ],
                timeout=60_000,
            )
            self._context.set_default_navigation_timeout(30_000)
            self._context.set_default_timeout(15_000)
            await self._context.route("**/*", self._route)
            pages = self._context.pages
            self._page = pages[0] if pages else await self._context.new_page()
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
        frame = request.frame
        is_main_document = request.is_navigation_request() and frame is not None and frame.parent_frame is None
        if is_main_document and self.policy.classify(request.url) != ALLOW:
            self.last_blocked_url = request.url
            log.warning("blocked document navigation")
            await route.abort()
            return
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
