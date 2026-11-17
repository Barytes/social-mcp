import asyncio
from pathlib import Path
from types import SimpleNamespace

from bili_mcp.flow import search_videos
from bili_mcp.policy import BiliPolicy
from bili_mcp.urls import LOGIN_URL
from mcp_browser.actions import goto_allowed
from mcp_browser.errors import PageLoadFailed
from xhs_mcp.flow import login_qr_wait, search_notes
from xhs_mcp.policy import XhsPolicy

FIXTURES = Path(__file__).parent / "fixtures"


class FakeLocator:
    @property
    def first(self):
        return self

    def nth(self, _index):
        return self

    async def count(self) -> int:
        return 0

    async def bounding_box(self):
        return None

    async def inner_text(self) -> str:
        return ""

    async def get_attribute(self, _name):
        return None

    async def click(self, timeout=None) -> None:
        raise AssertionError("search must not click the page")

    async def fill(self, value, timeout=None) -> None:
        raise AssertionError("search must not type into the page")


class FakePage:
    def __init__(self, html: str) -> None:
        self.html = html
        self.url = "about:blank"
        self.gotos: list[str] = []
        self.selectors: list[str] = []
        self.scrolled = 0
        self.mouse = SimpleNamespace(wheel=self._wheel)

    async def _wheel(self, _x: int, _y: int) -> None:
        self.scrolled += 1

    async def goto(self, url: str, **_kwargs):
        self.gotos.append(url)
        self.url = url
        return SimpleNamespace(status=200)

    async def content(self) -> str:
        return self.html

    async def title(self) -> str:
        return "fixture"

    async def inner_text(self, _selector: str) -> str:
        from bs4 import BeautifulSoup

        return BeautifulSoup(self.html, "html.parser").get_text("\n", strip=True)

    async def wait_for_selector(self, selector: str, timeout: int | None = None) -> None:
        self.selectors.append(selector)
        return None

    async def wait_for_timeout(self, _ms: int) -> None:
        return None

    def locator(self, _selector: str) -> FakeLocator:
        return FakeLocator()

    async def screenshot(self, path: str, full_page: bool = False) -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_bytes(b"png")


class FakeSession:
    def __init__(self, page: FakePage, policy, tmp_path: Path) -> None:
        self.page = page
        self.policy = policy
        self.last_blocked_url = None
        self.config = SimpleNamespace(screenshot_dir=tmp_path / "shots", qr_path=tmp_path / "qr.png")

    async def call(self, _name: str, func):
        return await func(self.page)


def test_bili_search_flow_reads_cards_without_clicking(tmp_path: Path) -> None:
    page = FakePage((FIXTURES / "bili_search.html").read_text(encoding="utf-8"))
    session = FakeSession(page, BiliPolicy(), tmp_path)

    payload = asyncio.run(search_videos(session, "测试", limit=1, page=2))
    assert payload["ok"] is True
    assert payload["status"] == "results"
    assert payload["count"] == 1
    assert payload["results"][0]["bvid"] == "BV1aaaaaaaaa"
    assert payload["has_more"] is True
    assert "keyword=%E6%B5%8B%E8%AF%95" in page.gotos[0]
    assert "page=2" in page.gotos[0]
    assert "o=30" in page.gotos[0]
    assert page.selectors[0] == ".bili-video-card__info--tit"
    assert page.scrolled == 0


def test_xhs_login_wall_is_logged_out(tmp_path: Path) -> None:
    page = FakePage((FIXTURES / "xhs_login_wall.html").read_text(encoding="utf-8"))
    session = FakeSession(page, XhsPolicy(), tmp_path)
    payload = asyncio.run(search_notes(session, "测试", 5))
    assert payload["ok"] is True
    assert payload["logged_in"] is False
    assert payload["status"] == "logged_out"
    assert payload["reason"] == "session_absent_or_replaced"
    assert "网页" in payload["message"]
    assert page.scrolled == 0
    assert "/explore" not in page.gotos[0]


class QrPage(FakePage):
    def __init__(self) -> None:
        super().__init__("<html><body>扫码</body></html>")
        self.url = "https://www.xiaohongshu.com/login"
        self.visible = "请使用小红书扫码 点击刷新"
        self.show_qr = True

    async def inner_text(self, _selector: str) -> str:
        return self.visible

    def locator(self, selector: str) -> FakeLocator:
        page = self

        class QrLocator(FakeLocator):
            async def count(self) -> int:
                if "qrcode-img" in selector and page.show_qr:
                    return 1
                return 0

            async def bounding_box(self):
                if "qrcode-img" in selector and page.show_qr:
                    return {"width": 180, "height": 180}
                return None

        return QrLocator()


def test_xhs_qr_wait_can_be_repeated_without_replacing_the_code(tmp_path: Path) -> None:
    page = QrPage()
    session = FakeSession(page, XhsPolicy(), tmp_path)
    first = asyncio.run(login_qr_wait(session, 1))
    second = asyncio.run(login_qr_wait(session, 1))
    assert first["status"] == "qr_pending"
    assert first["qr_still_valid"] is True
    assert "login_qr_wait" in first["message"]
    assert second["status"] == "qr_pending"
    assert page.gotos == []


def test_xhs_qr_wait_reports_expiry_without_opening_login(tmp_path: Path) -> None:
    page = QrPage()
    page.visible = "二维码已过期 点击刷新"
    session = FakeSession(page, XhsPolicy(), tmp_path)
    payload = asyncio.run(login_qr_wait(session, 30))
    assert payload["error_type"] == "qr_expired"
    assert payload["status"] == "qr_expired"
    assert payload["qr_still_valid"] is False
    assert "login_qr_start" in payload["message"]
    assert page.gotos == []


def test_login_page_download_and_http_error_are_page_load_failed() -> None:
    class Page:
        def __init__(self, status: int | None, download: bool) -> None:
            self.url = "about:blank"
            self.status = status
            self.download = download

        async def goto(self, url: str, **_kwargs):
            self.url = url
            if url == "about:blank":
                return SimpleNamespace(status=200)
            if self.download:
                raise RuntimeError("Download is starting")
            return SimpleNamespace(status=self.status)

    download = Page(status=None, download=True)
    try:
        asyncio.run(goto_allowed(download, LOGIN_URL, BiliPolicy()))
    except PageLoadFailed as exc:
        assert "did not load as a document" in exc.message
        assert LOGIN_URL in exc.message
        assert exc.error_type == "page_load_failed"
    else:
        raise AssertionError("download navigation should fail the page load")

    missing = Page(status=404, download=False)
    try:
        asyncio.run(goto_allowed(missing, LOGIN_URL, BiliPolicy()))
    except PageLoadFailed as exc:
        assert "HTTP 404" in exc.message
        assert exc.extra["http_status"] == 404
    else:
        raise AssertionError("HTTP 404 should fail the page load")


def test_xhs_risk_page_stops(tmp_path: Path) -> None:
    page = FakePage((FIXTURES / "xhs_risk.html").read_text(encoding="utf-8"))
    session = FakeSession(page, XhsPolicy(), tmp_path)
    payload = asyncio.run(search_notes(session, "测试", 5))
    assert payload["ok"] is False
    assert payload["error_type"] == "needs_human_verification"
    assert payload.get("results") is None
    assert page.scrolled == 0
