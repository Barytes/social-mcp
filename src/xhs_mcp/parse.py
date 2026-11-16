"""Parse rendered Xiaohongshu HTML.

The login wall phrase and the risk-control page were seen live. Note-card selectors
are the structure the next logged-in session should match; they were not confirmed
live because search required a login and this environment did not sign in.
"""

from __future__ import annotations

import re
from urllib.parse import urlsplit, urlunsplit

from bs4 import BeautifulSoup

_NOTE_HREF = re.compile(r"/(?:explore|discovery/item|search_result)/([A-Za-z0-9]{6,64})")
_EMPTY = ("未找到相关", "没有找到相关", "换个词", "搜索结果为空", "暂无搜索结果")


def _clean(text: str | None) -> str | None:
    if not text:
        return None
    cleaned = re.sub(r"\s+", " ", text).strip()
    return cleaned or None


def _absolute(href: str) -> str:
    if href.startswith("//"):
        return "https:" + href
    if href.startswith("/"):
        return "https://www.xiaohongshu.com" + href
    return href


def _note_from_href(href: str) -> tuple[str, str] | None:
    match = _NOTE_HREF.search(urlsplit(href).path)
    if match is None:
        return None
    # Reject the bare feed query, which has no note id in the path.
    note_id = match.group(1)
    absolute = _absolute(href)
    parts = urlsplit(absolute)
    # Drop fragments only. Keep xsec_token and every other query the page itself used.
    absolute = urlunsplit((parts.scheme or "https", parts.netloc or "www.xiaohongshu.com", parts.path, parts.query, ""))
    return note_id, absolute


def _card_type(card) -> str | None:
    if card.select_one(".play-icon, .video-icon, [data-type='video']"):
        return "video"
    if card.select_one("[data-type='normal'], [data-type='image'], .image-icon"):
        return "image"
    return None


def parse_xhs_search(html: str) -> tuple[list[dict], str]:
    soup = BeautifulSoup(html, "html.parser")
    cards = soup.select("section.note-item, div.note-item")
    parser_id = "note-item"
    if not cards:
        cards = []
        for anchor in soup.select("a[href*='xsec_token']"):
            if _note_from_href(anchor.get("href") or "") is not None:
                cards.append(anchor)
        parser_id = "xsec-anchor"
    results: list[dict] = []
    seen: set[str] = set()
    for card in cards:
        anchor = card if getattr(card, "name", None) == "a" else card.select_one("a[href]")
        if anchor is None:
            continue
        parsed = _note_from_href(anchor.get("href") or "")
        if parsed is None:
            continue
        note_id, url = parsed
        if note_id in seen:
            continue
        seen.add(note_id)
        title_el = card.select_one(".footer .title, a.title, .title")
        author_el = card.select_one(".author .name, .author-wrapper .name, .name")
        like_el = card.select_one(".like-wrapper .count, .like-wrapper")
        image = card.select_one("img[src]")
        title = _clean(title_el.get_text(" ", strip=True) if title_el else None)
        like_text = _clean(like_el.get_text(" ", strip=True) if like_el else None)
        results.append(
            {
                "title": title,
                "note_id": note_id,
                "url": url,
                "author": _clean(author_el.get_text(" ", strip=True) if author_el else None),
                "like_count": like_text,
                "cover_url": _media(image.get("src") if image else None),
                "type": _card_type(card),
            }
        )
    return results, parser_id if results else "none"


def _media(src: str | None) -> str | None:
    if not src:
        return None
    src = src.strip()
    if src.startswith("//"):
        return "https:" + src
    if src.startswith("/"):
        return "https://www.xiaohongshu.com" + src
    if src.startswith("http://") or src.startswith("https://"):
        return src
    return None


def classify_xhs_search(html: str, url: str, text: str) -> dict:
    from mcp_browser.actions import challenge_from_text

    plain = text or BeautifulSoup(html, "html.parser").get_text(" ", strip=True)
    if challenge_from_text(url, plain) is not None:
        return {"kind": "needs_human_verification"}
    if "登录后查看搜索结果" in plain:
        return {"kind": "logged_out"}
    notes, parser_id = parse_xhs_search(html)
    if notes:
        return {"kind": "results", "notes": notes, "parser_id": parser_id}
    if "手机号登录" in plain and "获取验证码" in plain:
        return {"kind": "logged_out"}
    if any(phrase in plain for phrase in _EMPTY):
        return {"kind": "no_results"}
    return {"kind": "not_understood"}


def parse_xhs_note(html: str, url: str) -> dict | None:
    soup = BeautifulSoup(html, "html.parser")
    title_el = soup.select_one("#detail-title, .note-content .title, .note-scroller .title")
    if title_el is None:
        return None
    desc_el = soup.select_one("#detail-desc, .note-content .desc, .note-text")
    author_el = soup.select_one(".author-container .username, .author-wrapper .name, .username")
    tags: list[str] = []
    for tag in soup.select("a.tag, #hash-tag a, a.hash-tag"):
        text = tag.get_text(" ", strip=True).lstrip("#")
        if text and text not in tags:
            tags.append(text)
    parsed = _note_from_href(urlsplit(url).path)
    note_id = parsed[0] if parsed else None
    if note_id is None:
        match = _NOTE_HREF.search(urlsplit(url).path)
        note_id = match.group(1) if match else None
    description = desc_el.get_text(" ", strip=True) if desc_el else ""
    return {
        "note_id": note_id,
        "url": url,
        "title": title_el.get_text(" ", strip=True),
        "author": _clean(author_el.get_text(" ", strip=True) if author_el else None),
        "description": description[:4000] or None,
        "tags": tags[:30],
    }


def parse_xhs_identity(html: str, url: str, text: str) -> dict:
    """Login-form and login-wall detection were seen live. A logged-in nickname was not."""
    if "登录后查看搜索结果" in text or "passport" in url:
        return {"logged_in": False, "nickname": None, "uid": None}
    soup = BeautifulSoup(html, "html.parser")
    if soup.select_one("img.qrcode-img") or soup.select_one("input[placeholder*='手机号']"):
        if "登录" in text or "扫码" in text:
            return {"logged_in": False, "nickname": None, "uid": None}
    nickname = None
    for selector in (".user-name", ".side-bar .name", ".header-user .name", "a.user .name"):
        element = soup.select_one(selector)
        if element is None:
            continue
        value = element.get_text(" ", strip=True)
        if value and value not in {"登录", "我"}:
            nickname = value
            break
    uid = None
    profile = soup.select_one("a[href*='/user/profile/']")
    if profile is not None:
        match = re.search(r"/user/profile/([A-Za-z0-9]{6,64})", profile.get("href") or "")
        if match:
            uid = match.group(1)
    if nickname or uid:
        return {"logged_in": True, "nickname": nickname, "uid": uid}
    return {"logged_in": None, "nickname": None, "uid": None}
