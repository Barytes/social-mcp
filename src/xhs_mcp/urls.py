from urllib.parse import urlencode

LOGIN_URL = "https://www.xiaohongshu.com/login"
PROFILE_URL = "https://www.xiaohongshu.com/user/profile"
FAVORITES_NOTE = "https://www.xiaohongshu.com/user/profile/{user_id}"


def xhs_profile_url(uid: str) -> str:
    return f"https://www.xiaohongshu.com/user/profile/{uid}"


def xhs_favorites_url(uid: str, sub_tab: str = "note") -> str:
    return f"{xhs_profile_url(uid)}?{urlencode({'tab': 'fav', 'subTab': sub_tab})}"


def xhs_board_url(board_id: str) -> str:
    return f"https://www.xiaohongshu.com/board/{board_id}"


def xhs_note_url(note_id: str, xsec_token: str = "") -> str:
    base = f"https://www.xiaohongshu.com/explore/{note_id}"
    if not xsec_token:
        return base
    return f"{base}?{urlencode({'xsec_token': xsec_token, 'xsec_source': 'pc_user'})}"


def xhs_search_url(keyword: str) -> str:
    query = urlencode({"keyword": keyword, "source": "web_search_result_notes"})
    return f"https://www.xiaohongshu.com/search_result?{query}"
