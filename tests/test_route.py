"""Route allowlist, including service-worker requests that have no frame."""

import asyncio

from mcp_browser.session import BrowserSession, is_playback_request, should_block_request
from xhs_mcp.policy import XhsPolicy

_SW_ERROR = "Service Worker requests do not have an associated frame."
_EXPLORE = "https://www.xiaohongshu.com/explore"
_LOGIN = "https://www.xiaohongshu.com/login"
_SCRIPT = "https://www.xiaohongshu.com/fe/sw.js"


class Frame:
    def __init__(self, parent=None) -> None:
        self.parent_frame = parent


class Request:
    def __init__(
        self,
        url: str,
        *,
        frame=None,
        frame_error: str | None = None,
        navigation: bool = False,
        resource: str = "other",
        method: str = "GET",
    ) -> None:
        self.url = url
        self._frame = frame
        self._frame_error = frame_error
        self._navigation = navigation
        self.resource_type = resource
        self.method = method

    @property
    def frame(self):
        if self._frame_error:
            raise RuntimeError(self._frame_error)
        return self._frame

    def is_navigation_request(self) -> bool:
        return self._navigation


class Route:
    def __init__(self, request: Request) -> None:
        self.request = request
        self.action = None

    async def abort(self) -> None:
        self.action = "abort"

    async def continue_(self) -> None:
        self.action = "continue"


def _sw(url: str, **kwargs) -> Request:
    return Request(url, frame_error=_SW_ERROR, **kwargs)


def test_service_worker_navigation_still_obeys_the_allowlist() -> None:
    policy = XhsPolicy()
    assert should_block_request(policy, _sw(_EXPLORE, navigation=True, resource="document")) is True
    assert should_block_request(policy, _sw(_LOGIN, navigation=True, resource="document")) is False
    assert should_block_request(policy, _sw(_SCRIPT, resource="script")) is False


def test_service_worker_cannot_fetch_the_feed_or_send_a_write() -> None:
    policy = XhsPolicy()
    assert should_block_request(policy, _sw(_EXPLORE, resource="fetch")) is True
    assert should_block_request(policy, _sw(_LOGIN, method="POST", resource="fetch")) is True
    assert should_block_request(policy, _sw(_LOGIN, method="GET", resource="fetch")) is False


def test_framed_document_navigation_is_unchanged() -> None:
    policy = XhsPolicy()
    feed = Request(_EXPLORE, frame=Frame(), navigation=True, resource="document")
    search = Request(
        "https://www.xiaohongshu.com/search_result?keyword=test",
        frame=Frame(),
        navigation=True,
        resource="document",
    )
    script = Request(_SCRIPT, frame=Frame(), resource="script")
    assert should_block_request(policy, feed) is True
    assert should_block_request(policy, search) is False
    assert should_block_request(policy, script) is False


def test_route_handler_survives_a_service_worker_request() -> None:
    session = BrowserSession(None, XhsPolicy())

    async def run() -> None:
        blocked = Route(_sw(_EXPLORE, navigation=True, resource="document"))
        allowed = Route(_sw(_SCRIPT, resource="script"))
        await session._route(blocked)
        await session._route(allowed)
        assert blocked.action == "abort"
        assert session.last_blocked_url == _EXPLORE
        assert allowed.action == "continue"

    asyncio.run(run())


def test_playback_and_history_reports_are_aborted() -> None:
    policy = XhsPolicy()
    assert is_playback_request(Request("https://upos-sz-mirrorcos.bilivideo.com/upgcxcode/a.m4s", resource="xhr"))
    assert should_block_request(policy, Request("https://api.bilibili.com/x/player/wbi/playurl?bvid=BV1", resource="xhr"))
    assert should_block_request(policy, Request("https://api.bilibili.com/x/v2/history/report", resource="xhr"))
    assert should_block_request(policy, Request("https://api.bilibili.com/x/click-interface/click/web/h5", resource="xhr"))
    image = Request("https://i0.hdslb.com/bfs/archive/cover.jpg", resource="image")
    assert is_playback_request(image) is False
    assert should_block_request(policy, Request(_LOGIN, resource="image")) is False
