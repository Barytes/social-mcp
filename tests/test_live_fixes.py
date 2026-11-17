"""Branches confirmed on a logged-in session on 2026-11-17, exercised here without the sites."""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from bili_mcp.flow import login_qr_wait as bili_wait
from bili_mcp.flow import login_status as bili_status
from bili_mcp.policy import BiliPolicy
from mcp_browser.session import document_log_target, keep_one_page
from mcp_browser.smoke import poll_qr_wait
from xhs_mcp.flow import login_qr_wait as xhs_wait
from xhs_mcp.flow import login_sms_submit, login_status as xhs_status
from xhs_mcp.policy import XhsPolicy
from xhs_mcp.xvfb import ensure_xvfb


class Box:
    def __init__(self, text: str = "", attrs: dict | None = None, size: dict | None = None) -> None:
        self.text = text
        self.attrs = attrs or {}
        self.size = size
        self.clicked = False
        self.filled = None

    @property
    def first(self):
        return self

    def nth(self, _index: int):
        return self

    async def count(self) -> int:
        return 1 if self.size or self.text or self.attrs else 0

    async def bounding_box(self):
        return self.size

    async def inner_text(self) -> str:
        return self.text

    async def get_attribute(self, name: str):
        return self.attrs.get(name)

    async def click(self, timeout: int | None = None) -> None:
        self.clicked = True

    async def fill(self, value: str, timeout: int | None = None) -> None:
        self.filled = value

    async def screenshot(self, path: str) -> None:
        Path(path).write_bytes(b"png")

    async def is_checked(self) -> bool:
        return False


class Page:
    def __init__(self, html: str, url: str) -> None:
        self.html = html
        self.url = url
        self.gotos: list[str] = []
        self.waits = 0
        self.boxes: dict[str, Box] = {}
        self.texts: dict[str, Box] = {}
        self.clicked: list[str] = []

    async def goto(self, url: str, **_kwargs):
        self.gotos.append(url)
        self.url = url
        return SimpleNamespace(status=200)

    async def content(self) -> str:
        if "/user/profile/" in (self.url or ""):
            return '<div class="user-name">阿花</div>'
        return self.html

    async def inner_text(self, _selector: str) -> str:
        from bs4 import BeautifulSoup

        if "/user/profile/" in (self.url or ""):
            return "阿花"
        return BeautifulSoup(self.html, "html.parser").get_text("\n", strip=True)

    async def wait_for_selector(self, _selector: str, timeout: int | None = None) -> None:
        return None

    async def wait_for_timeout(self, ms: int) -> None:
        self.waits += 1

    def locator(self, selector: str) -> Box:
        return self.boxes.get(selector, Box())

    def get_by_text(self, label: str, exact: bool = False) -> Box:
        box = self.texts.get(label, Box())

        class Clickable(Box):
            async def click(self, timeout: int | None = None) -> None:
                await Box.click(self, timeout)
                page.clicked.append(label)

        page = self
        return Clickable(box.text, box.attrs, box.size)


def session(page: Page, policy, tmp_path: Path):
    holder = SimpleNamespace(
        page=page,
        policy=policy,
        last_blocked_url=None,
        last_allowed_document=None,
        config=SimpleNamespace(screenshot_dir=tmp_path / "shots", qr_path=tmp_path / "qr.png"),
    )

    async def call(_name, func):
        return await func(page)

    holder.call = call
    return holder


def advance(monkeypatch, module: str, page: Page):
    clock = {"t": 0.0}

    def monotonic() -> float:
        return clock["t"]

    async def wait(ms: int) -> None:
        clock["t"] += ms / 1000
        page.waits += 1

    monkeypatch.setattr(f"{module}.time.monotonic", monotonic)
    page.wait_for_timeout = wait


def test_bili_scanned_qr_blocks_until_the_timeout(monkeypatch, tmp_path: Path) -> None:
    page = Page("<html><body>请在手机上确认</body></html>", "https://passport.bilibili.com/pc/passport/login")
    page.boxes[".login-scan__qrcode canvas"] = Box(size={"width": 140, "height": 140})
    advance(monkeypatch, "bili_mcp.flow", page)
    payload = asyncio.run(bili_wait(session(page, BiliPolicy(), tmp_path), 4))
    assert payload["status"] == "awaiting_confirmation"
    assert page.waits >= 2
    assert page.gotos == []


def test_bili_cross_domain_then_blocked_home_is_logged_in(tmp_path: Path) -> None:
    page = Page(
        '<span class="home-top-msg-name">真昵称</span><p>UID: 42</p>',
        "chrome-error://chromewebdata/",
    )
    holder = session(page, BiliPolicy(), tmp_path)
    holder.last_blocked_url = "https://www.bilibili.com/"
    holder.last_allowed_document = "https://passport.biligame.com/x/passport-login/web/crossDomain?d=1"
    payload = asyncio.run(bili_wait(holder, 5))
    assert payload["status"] == "logged_in"
    assert payload["nickname"] == "真昵称"
    assert payload["uid"] == "42"
    assert "https://www.bilibili.com/" not in page.gotos
    assert page.gotos[0].startswith("https://account.bilibili.com/account/home")


def test_other_biligame_path_is_not_treated_as_login_success(tmp_path: Path) -> None:
    page = Page('<div class="header-avatar-unlogin-entry">登录</div>', "chrome-error://chromewebdata/")
    holder = session(page, BiliPolicy(), tmp_path)
    holder.last_blocked_url = "https://www.bilibili.com/"
    holder.last_allowed_document = "https://passport.biligame.com/x/passport-login/web/other"
    payload = asyncio.run(bili_wait(holder, 5))
    assert payload["logged_in"] is False
    assert payload["status"] == "logged_out"


def test_bili_account_home_nickname(tmp_path: Path) -> None:
    page = Page('<span class="home-top-msg-name">真昵称</span><p>UID：42</p>', "about:blank")
    payload = asyncio.run(bili_status(session(page, BiliPolicy(), tmp_path)))
    assert payload["status"] == "logged_in"
    assert payload["nickname"] == "真昵称"
    assert payload["nickname_selector_verified_live"] is True


def test_xhs_sms_modal_returns_immediately(tmp_path: Path) -> None:
    page = Page(
        "<html><body>短信验证码验证 验证码已发送至 +86 183******99 请输入验证码 验证 重新发送</body></html>",
        "https://www.xiaohongshu.com/login",
    )
    payload = asyncio.run(xhs_wait(session(page, XhsPolicy(), tmp_path), 30))
    assert payload["status"] == "sms_verification_required"
    assert payload["masked_phone"] == "+86 183******99"
    assert "重新发送" in payload["message"]
    assert page.waits == 0
    assert page.gotos == []


def test_xhs_scanned_qr_blocks_until_the_timeout(monkeypatch, tmp_path: Path) -> None:
    page = Page("<html><body>请在手机上确认</body></html>", "https://www.xiaohongshu.com/login")
    page.boxes["img.qrcode-img"] = Box(size={"width": 180, "height": 180})
    advance(monkeypatch, "xhs_mcp.flow", page)
    payload = asyncio.run(xhs_wait(session(page, XhsPolicy(), tmp_path), 4))
    assert payload["status"] == "awaiting_confirmation"
    assert page.waits >= 2
    assert page.gotos == []


def test_xhs_sms_submit_clicks_verify_and_confirms_off_the_feed(tmp_path: Path) -> None:
    page = Page(
        "<html><body>短信验证码验证 验证码已发送至 +86 183******99</body></html>",
        "https://www.xiaohongshu.com/login",
    )
    page.boxes["input[placeholder*='验证码']"] = Box(attrs={"placeholder": "请输入验证码", "type": "text"})
    page.texts["验证"] = Box(text="验证", size={"width": 80, "height": 32})
    holder = session(page, XhsPolicy(), tmp_path)

    original = page.get_by_text

    def get_by_text(label: str, exact: bool = False):
        box = original(label, exact)

        class Mark(type(box)):
            pass

        async def click(timeout: int | None = None) -> None:
            await type(box).click(box, timeout)
            page.html = '<a href="/user/profile/abc1234567">me</a>'
            holder.last_blocked_url = "https://www.xiaohongshu.com/explore?channel_id=homefeed_recommend"

        box.click = click
        return box

    page.get_by_text = get_by_text
    payload = asyncio.run(login_sms_submit(holder, "123456"))
    assert page.clicked == ["验证"]
    assert "重新发送" not in page.clicked
    assert payload["status"] == "logged_in"
    assert payload["uid"] == "abc1234567"
    assert payload["nickname"] == "阿花"
    assert not any("/explore" in url for url in page.gotos)


def test_xhs_nickname_comes_from_the_profile_page(tmp_path: Path) -> None:
    page = Page('<a href="/user/profile/abc1234567">主页</a>', "about:blank")
    payload = asyncio.run(xhs_status(session(page, XhsPolicy(), tmp_path)))
    assert payload["status"] == "logged_in"
    assert payload["uid"] == "abc1234567"
    assert payload["nickname"] == "阿花"
    assert any("/user/profile/abc1234567" in url for url in page.gotos)
    assert not any("/explore" in url for url in page.gotos)


def test_poll_qr_wait_stays_up_through_confirmation(monkeypatch) -> None:
    clock = {"t": 0.0}
    monkeypatch.setattr("mcp_browser.smoke.time.monotonic", lambda: clock["t"])

    async def sleep(seconds: float) -> None:
        clock["t"] += seconds

    monkeypatch.setattr("mcp_browser.smoke.asyncio.sleep", sleep)
    calls: list[float] = []

    async def wait(_session, step: float) -> dict:
        calls.append(step)
        if len(calls) < 3:
            return {"ok": True, "status": "awaiting_confirmation"}
        return {"ok": True, "status": "logged_in", "logged_in": True}

    payload = asyncio.run(poll_qr_wait(wait, None, 10, "/tmp/qr.png"))
    assert payload["status"] == "logged_in"
    assert payload["qr_path"] == "/tmp/qr.png"
    assert len(calls) == 3


def test_poll_qr_wait_stops_for_sms(monkeypatch) -> None:
    monkeypatch.setattr("mcp_browser.smoke.time.monotonic", lambda: 0.0)
    calls = {"n": 0}

    async def wait(_session, _step: float) -> dict:
        calls["n"] += 1
        return {"ok": True, "status": "sms_verification_required", "logged_in": False}

    payload = asyncio.run(poll_qr_wait(wait, None, 30, None))
    assert payload["status"] == "sms_verification_required"
    assert calls["n"] == 1


def test_blocked_navigation_log_drops_the_query() -> None:
    host, path = document_log_target("https://www.xiaohongshu.com/search_result?keyword=a&xsec_token=secret")
    assert host == "www.xiaohongshu.com"
    assert path == "/search_result"
    assert "secret" not in host and "secret" not in path


def test_startup_keeps_one_page_and_leaves_a_restored_feed(tmp_path: Path) -> None:
    class Tab:
        def __init__(self, url: str, ctx) -> None:
            self.url = url
            self.ctx = ctx
            self.closed = False
            self.gotos: list[str] = []

        async def close(self) -> None:
            self.closed = True
            self.ctx.pages = [item for item in self.ctx.pages if item is not self]

        async def goto(self, url: str, **_kwargs) -> None:
            self.gotos.append(url)
            self.url = url

    class Ctx:
        def __init__(self) -> None:
            self.pages = [Tab("https://www.bilibili.com/", self), Tab("chrome-error://chromewebdata/", self)]

        async def new_page(self):
            tab = Tab("about:blank", self)
            self.pages.append(tab)
            return tab

    ctx = Ctx()
    kept = asyncio.run(keep_one_page(ctx, BiliPolicy()))
    assert len(ctx.pages) == 1
    assert kept.url == "about:blank"
    assert ctx.pages[0].gotos == ["about:blank"]


def test_xvfb_launcher_reuses_a_live_display(tmp_path: Path) -> None:
    (tmp_path / "X90").write_text("", encoding="utf-8")
    called: list = []
    ensure_xvfb(":90", tmp_path, popen=lambda *args, **kwargs: called.append(args))
    assert called == []


def test_xvfb_launcher_starts_when_the_socket_is_missing(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("xhs_mcp.xvfb._binary_exists", lambda _name: True)

    def popen(args, **_kwargs):
        (tmp_path / "X90").write_text("", encoding="utf-8")
        assert args[:2] == ["Xvfb", ":90"]
        return None

    ensure_xvfb(":90", tmp_path, popen=popen)
    assert (tmp_path / "X90").is_file()


def test_xvfb_launcher_fails_clearly_without_the_binary(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("xhs_mcp.xvfb._binary_exists", lambda _name: False)
    with pytest.raises(SystemExit, match="Xvfb"):
        ensure_xvfb(":90", tmp_path, popen=lambda *args, **kwargs: None)
