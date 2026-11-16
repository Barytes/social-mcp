from urllib.parse import urlencode

ACCOUNT_URL = "https://account.bilibili.com/account/home"
LOGIN_URL = "https://passport.bilibili.com/login"
FAVORITES_URL = "https://space.bilibili.com/{uid}/favlist"
WATCH_LATER_URL = "https://www.bilibili.com/watchlater"


def bili_search_url(keyword: str, page: int) -> str:
    query = urlencode({"keyword": keyword, "page": page})
    return f"https://search.bilibili.com/all?{query}"


def bili_video_url(bvid: str) -> str:
    return f"https://www.bilibili.com/video/{bvid}"
