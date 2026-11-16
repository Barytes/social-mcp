import asyncio
from pathlib import Path
from types import SimpleNamespace

from bili_mcp.flow import search_videos
from bili_mcp.policy import BiliPolicy
from xhs_mcp.flow import search_notes
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

    async def wait_for_selector(self, _selector: str, timeout: int | None = None) -> None:
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


def test_xhs_risk_page_stops(tmp_path: Path) -> None:
    page = FakePage((FIXTURES / "xhs_risk.html").read_text(encoding="utf-8"))
    session = FakeSession(page, XhsPolicy(), tmp_path)
    payload = asyncio.run(search_notes(session, "测试", 5))
    assert payload["ok"] is False
    assert payload["error_type"] == "needs_human_verification"
    assert payload.get("results") is None
    assert page.scrolled == 0
