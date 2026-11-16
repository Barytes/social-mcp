"""Bilibili login navigation and QR capture. No live site, no password entry."""

import asyncio
from pathlib import Path
from types import SimpleNamespace

from bili_mcp.flow import _capture_qr, _qr_visible
from bili_mcp.policy import BiliPolicy
from bili_mcp.urls import LOGIN_URL
from mcp_browser.actions import goto_allowed
from mcp_browser.errors import FeedBlocked, PageLoadFailed

_OVERSEAS = {
    "zh-Hans": LOGIN_URL + "?site=OVERSEAS&lang=zh-Hans",
    "en": LOGIN_URL + "?site=OVERSEAS&lang=en",
}


class _GotoPage:
    def __init__(self, landed: str, *, error: str) -> None:
        self.url = "about:blank"
        self.landed = landed
        self.error = error
        self.blanked = False

    async def goto(self, url: str, **_kwargs):
        if url == "about:blank":
            self.blanked = True
            self.url = url
            return SimpleNamespace(status=200)
        self.url = self.landed
        raise RuntimeError(self.error)

    async def wait_for_load_state(self, _state: str, timeout: int | None = None) -> None:
        return None

    async def wait_for_timeout(self, _ms: int) -> None:
        return None


def test_account_home_abort_can_settle_on_the_passport_document() -> None:
    page = _GotoPage(
        _OVERSEAS["en"],
        error="Page.goto: net::ERR_ABORTED at https://passport.bilibili.com/pc/passport/login",
    )

    async def flaky_wait(_ms: int) -> None:
        raise RuntimeError("page is navigating")

    page.wait_for_timeout = flaky_wait
    final = asyncio.run(goto_allowed(page, "https://account.bilibili.com/account/home", BiliPolicy()))
    assert final == _OVERSEAS["en"]
    assert page.blanked is False


def test_same_site_redirect_abort_settles_for_either_language() -> None:
    for landed in _OVERSEAS.values():
        page = _GotoPage(
            landed,
            error=f"Page.goto: net::ERR_ABORTED at {LOGIN_URL}",
        )
        final = asyncio.run(goto_allowed(page, LOGIN_URL, BiliPolicy()))
        assert final == landed
        assert page.blanked is False


def test_aborted_navigation_to_the_feed_still_fails() -> None:
    page = _GotoPage(
        "https://www.bilibili.com/",
        error="Page.goto: net::ERR_ABORTED at https://www.bilibili.com/",
    )
    try:
        asyncio.run(goto_allowed(page, "https://www.bilibili.com/video/BV1aaaaaaaaa", BiliPolicy()))
    except FeedBlocked as exc:
        assert exc.error_type == "feed_blocked"
    else:
        raise AssertionError("an aborted navigation that lands on the home feed must fail")
    assert page.blanked is True


def test_download_is_still_a_page_load_failure() -> None:
    page = _GotoPage(LOGIN_URL, error="Download is starting")
    try:
        asyncio.run(goto_allowed(page, LOGIN_URL, BiliPolicy()))
    except PageLoadFailed as exc:
        assert "did not load as a document" in exc.message
    else:
        raise AssertionError("a download is not a same-site redirect")
    assert page.blanked is True


class _QrLocator:
    def __init__(self, page, kind: str) -> None:
        self.page = page
        self.kind = kind

    @property
    def first(self):
        return self

    async def count(self) -> int:
        return 1 if self.kind in self.page.present else 0

    async def bounding_box(self):
        if self.kind not in self.page.present:
            return None
        if self.kind == "img" and not self.page.img_large:
            return {"width": 8, "height": 8}
        return {"width": 180, "height": 180}

    async def screenshot(self, path: str) -> None:
        self.page.shots.append(self.kind)
        Path(path).write_bytes(self.page.png)

    async def click(self, timeout: int | None = None) -> None:
        raise AssertionError("qr capture must not click the login form")

    async def fill(self, value: str, timeout: int | None = None) -> None:
        raise AssertionError("qr capture must not type")


class _QrPage:
    def __init__(self, png: bytes) -> None:
        self.png = png
        self.present = {"img"}
        self.img_large = False
        self.shots: list[str] = []
        self.polls = 0

    def locator(self, selector: str) -> _QrLocator:
        if selector.endswith("canvas"):
            kind = "canvas"
        elif selector.endswith("img"):
            kind = "img"
        else:
            kind = "box"
        return _QrLocator(self, kind)

    async def wait_for_timeout(self, _ms: int) -> None:
        self.polls += 1
        if self.polls >= 2:
            self.present.add("canvas")


def test_qr_capture_waits_for_the_canvas_and_ignores_a_tiny_img(tmp_path: Path) -> None:
    png = _sample_png()
    page = _QrPage(png)
    dest = tmp_path / "login-qr.png"
    assert asyncio.run(_capture_qr(page, dest)) is True
    assert page.shots[0] == "canvas"
    assert dest.read_bytes().startswith(b"\x89PNG")
    assert asyncio.run(_qr_visible(page)) is True


def test_sample_png_decodes_as_a_qr() -> None:
    decoded = _decode_qr(_sample_png())
    if decoded is None:
        return
    assert decoded == "https://example.test/bili-qr-fixture"


def _sample_png() -> bytes:
    """A real QR when segno is installed. Otherwise a tiny PNG so capture can still be checked."""
    return _qr_png_bytes()


def _decode_qr(png: bytes) -> str | None:
    """Decode a QR PNG. A 140px screenshot needs to be scaled before zbar sees the modules."""
    try:
        from io import BytesIO

        from PIL import Image
        from pyzbar.pyzbar import decode
    except Exception:
        return None

    def once(image) -> str | None:
        symbols = decode(image)
        if not symbols:
            return None
        return symbols[0].data.decode("utf-8")

    image = Image.open(BytesIO(png))
    found = once(image)
    if found:
        return found
    scaled = image.resize((image.width * 4, image.height * 4), Image.Resampling.NEAREST)
    return once(scaled)


def _qr_png_bytes() -> bytes:
    try:
        import io

        import segno
    except Exception:
        return _FALLBACK_PNG
    buffer = io.BytesIO()
    segno.make("https://example.test/bili-qr-fixture", error="m").save(buffer, kind="png", scale=4, border=2)
    return buffer.getvalue()


# 1x1 PNG so the capture test still has a PNG header when segno is absent.
# The decode test no-ops in that case.
_FALLBACK_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\xcf\xc0"
    b"\x00\x00\x00\x03\x00\x01\x00\x05\xfe\xd4\xef\x00\x00\x00\x00IEND\xaeB`\x82"
)
