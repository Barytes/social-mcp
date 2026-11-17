from urllib.parse import urlencode

ACCOUNT_URL = "https://account.bilibili.com/account/home"
# Bare https://passport.bilibili.com/login answers HTTP 404 and Chrome treats it as a
# download. The PC passport page is the official web login document (HTTP 200).
LOGIN_URL = "https://passport.bilibili.com/pc/passport/login"
FAVORITES_URL = "https://space.bilibili.com/{uid}/favlist"
SPACE_HOME = "https://space.bilibili.com/"
# /watchlater/#/list is a client route Playwright treats as a download.
# The list that actually renders is the player page's right-hand panel.
WATCH_LATER_URL = "https://www.bilibili.com/list/watchlater"


def bili_search_url(keyword: str, page: int) -> str:
    # A bare &page=1 leaves the logged-in result list empty (checked live 2026-11-17).
    # Page 1 is the plain keyword URL. Later pages use the site's own page/o pair.
    params: dict[str, str | int] = {"keyword": keyword}
    if page > 1:
        params["page"] = page
        params["o"] = (page - 1) * 30
    return f"https://search.bilibili.com/all?{urlencode(params)}"


def bili_video_url(bvid: str) -> str:
    return f"https://www.bilibili.com/video/{bvid}"


def bili_favlist_url(uid: str, fid: str | None = None) -> str:
    base = f"https://space.bilibili.com/{uid}/favlist"
    if not fid:
        return base
    return f"{base}?{urlencode({'fid': fid, 'ftype': 'create'})}"
