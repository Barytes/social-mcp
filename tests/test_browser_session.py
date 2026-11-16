import asyncio
import os
from pathlib import Path

import pytest

from mcp_browser.actions import safe_click
from mcp_browser.config import SiteConfig
from mcp_browser.errors import ReadOnlyViolation
from mcp_browser.guard import ClickPurpose
from mcp_browser.policy import ALLOW, FEED, DocumentPolicy
from mcp_browser.session import BrowserSession
from mcp_browser.singleton import chrome_pids_for_profile


class LocalPolicy(DocumentPolicy):
    def classify(self, url: str) -> str:
        if not url or url.startswith("about:"):
            return ALLOW
        if "/feed" in url:
            return FEED
        if url.startswith("http://127.0.0.1") or url.startswith("http://localhost"):
            return ALLOW
        return "deny"


def _config(tmp_path: Path) -> SiteConfig:
    data = tmp_path / "data"
    return SiteConfig(
        name="browser-test",
        chrome_path="/usr/bin/google-chrome",
        headed=False,
        data_dir=data,
        profile_dir=tmp_path / "profile",
        log_file=data / "logs" / "test.log",
        screenshot_dir=data / "shots",
        qr_path=data / "qr" / "login-qr.png",
    )


def test_profile_survives_restart_and_blocks_feed(tmp_path: Path) -> None:
    if not Path("/usr/bin/google-chrome").is_file():
        pytest.skip("system Chrome is not installed")

    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    ok_html = """<!DOCTYPE html><html><head><title>kept-ok</title></head><body>
    <h1 id="ok">ok</h1>
    <button id="like" onclick="this.dataset.clicked='yes'">点赞</button>
    <button id="sms" onclick="this.dataset.clicked='yes'">短信登录</button>
    </body></html>"""
    feed_html = "<!DOCTYPE html><html><body><p>FEED_MARKER</p></body></html>"

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            body = (feed_html if self.path.startswith("/feed") else ok_html).encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, _format, *_args):
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    port = server.server_address[1]
    import threading

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{port}"
    config = _config(tmp_path)

    async def scenario() -> None:
        session = BrowserSession(config, LocalPolicy())

        async def first(page):
            await page.goto(f"{base}/ok", wait_until="domcontentloaded")
            await page.evaluate("localStorage.setItem('kept', 'yes')")
            like = page.locator("#like")
            try:
                await safe_click(like, ClickPurpose.SUBMIT_LOGIN)
            except ReadOnlyViolation:
                pass
            else:
                raise AssertionError("like button was clickable")
            assert await like.get_attribute("data-clicked") is None
            await safe_click(page.locator("#sms"), ClickPurpose.SWITCH_LOGIN_METHOD)
            assert await page.locator("#sms").get_attribute("data-clicked") == "yes"
            try:
                await page.goto(f"{base}/feed", wait_until="domcontentloaded")
            except Exception:
                pass
            blocked = session.last_blocked_url or ""
            assert "/feed" in blocked
            # Aborting the document leaves Chrome on chrome-error://, which
            # races the next navigation. Wait it out, then retry once.
            await page.wait_for_timeout(300)
            try:
                await page.goto(f"{base}/ok", wait_until="domcontentloaded")
            except Exception:
                await page.goto(f"{base}/ok", wait_until="domcontentloaded")
            content = await page.content()
            assert "FEED_MARKER" not in content
            return True

        try:
            assert await session.call("first", first)
        finally:
            await session.shutdown()

        async def second(page):
            await page.goto(f"{base}/ok", wait_until="domcontentloaded")
            return await page.evaluate("localStorage.getItem('kept')")

        again = BrowserSession(config, LocalPolicy())
        try:
            assert await again.call("second", second) == "yes"
            pids = chrome_pids_for_profile(config.profile_dir)
            assert pids
            for pid in pids:
                try:
                    os.kill(pid, 9)
                except ProcessLookupError:
                    pass
            await asyncio.sleep(0.5)

            async def third(page):
                await page.goto(f"{base}/ok", wait_until="domcontentloaded")
                return await page.title()

            # The killed browser is recovered, and the profile can be opened again.
            title = await again.call("third", third)
            assert title
        finally:
            await again.shutdown()

    try:
        asyncio.run(scenario())
    finally:
        server.shutdown()
