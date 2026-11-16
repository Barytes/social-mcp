from urllib.parse import urlencode

LOGIN_URL = "https://www.xiaohongshu.com/login"
PROFILE_URL = "https://www.xiaohongshu.com/user/profile"
FAVORITES_NOTE = "https://www.xiaohongshu.com/user/profile/{user_id}"


def xhs_search_url(keyword: str) -> str:
    query = urlencode({"keyword": keyword, "source": "web_search_result_notes"})
    return f"https://www.xiaohongshu.com/search_result?{query}"
