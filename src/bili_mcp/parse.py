"""Parse rendered Bilibili HTML. Selectors match the public search and video pages observed in Chrome."""

from __future__ import annotations

import html
import re

from bs4 import BeautifulSoup

_BV = re.compile(r"/video/(BV[0-9A-Za-z]{10})")
_UID_TEXT = re.compile(r"UID[:：\s]*(\d{1,16})")
_SPACE_UID = re.compile(r"space\.bilibili\.com/(?:[\w-]+/)?(\d{3,})")
_EMPTY = ("没有找到相关", "没有相关数据", "搜索结果为空", "啥都没找到", "未找到相关")


def _clean(text: str | None) -> str | None:
    if not text:
        return None
    cleaned = html.unescape(text).replace("·", " ")
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned or None


def _media(src: str | None) -> str | None:
    if not src:
        return None
    src = src.strip()
    if src.startswith("//"):
        return "https:" + src
    if src.startswith("http://") or src.startswith("https://"):
        return src
    return None


def parse_bili_search(html: str) -> tuple[list[dict], str]:
    soup = BeautifulSoup(html, "html.parser")
    results: list[dict] = []
    seen: set[str] = set()
    for card in soup.select(".bili-video-card"):
        title_el = card.select_one(".bili-video-card__info--tit")
        link = card.select_one("a[href*='/video/BV']")
        if title_el is None or link is None:
            continue
        match = _BV.search(link.get("href") or "")
        if match is None:
            continue
        bvid = match.group(1)
        if bvid in seen:
            continue
        seen.add(bvid)
        play_el = card.select_one(".bili-video-card__stats--left .bili-video-card__stats--item")
        author_el = card.select_one(".bili-video-card__info--author")
        date_el = card.select_one(".bili-video-card__info--date")
        duration_el = card.select_one(".bili-video-card__stats__duration")
        image = card.select_one("img[src]")
        title = _clean(title_el.get("title") or title_el.get_text(" ", strip=True)) or ""
        results.append(
            {
                "title": title,
                "bvid": bvid,
                "url": f"https://www.bilibili.com/video/{bvid}",
                "up_name": _clean(author_el.get_text(" ", strip=True) if author_el else None),
                "play_count": _clean(play_el.get_text(" ", strip=True) if play_el else None),
                "duration": _clean(duration_el.get_text(" ", strip=True) if duration_el else None),
                "publish_date": _clean(date_el.get_text(" ", strip=True) if date_el else None),
                "cover_url": _media(image.get("src") if image else None),
            }
        )
    return results, "bili-video-card"


def bili_has_more(html: str) -> bool:
    soup = BeautifulSoup(html, "html.parser")
    for button in soup.select("button.vui_pagenation--btn-side"):
        classes = button.get("class") or []
        if "下一页" in button.get_text(strip=True) and "vui_button--disabled" not in classes:
            return True
    return False


def classify_bili_search(html: str, url: str) -> dict:
    if "passport.bilibili.com" in url:
        return {"kind": "logged_out"}
    videos, parser_id = parse_bili_search(html)
    if videos:
        return {
            "kind": "results",
            "videos": videos,
            "parser_id": parser_id,
            "has_more": bili_has_more(html),
        }
    text = BeautifulSoup(html, "html.parser").get_text(" ", strip=True)
    if any(phrase in text for phrase in _EMPTY):
        return {"kind": "no_results"}
    return {"kind": "not_understood"}


def parse_bili_video(html: str, bvid: str) -> dict | None:
    soup = BeautifulSoup(html, "html.parser")
    title_el = soup.select_one("h1.video-title")
    if title_el is None:
        return None
    title = _clean(title_el.get_text(" ", strip=True)) or ""
    if not title or "出错啦" in title:
        return None
    desc_el = soup.select_one(".desc-info-text") or soup.select_one(".basic-desc-info")
    up_el = soup.select_one("a.up-name") or soup.select_one(".up-name")
    date_el = soup.select_one(".pubdate-ip-text") or soup.select_one(".pubdate-text") or soup.select_one(".pubdate")
    tags: list[str] = []
    for tag in soup.select(".video-tag-container a.tag-link"):
        text = _clean(tag.get_text(" ", strip=True))
        if text and text not in tags:
            tags.append(text)
    description = _clean(desc_el.get_text(" ", strip=True) if desc_el else None) or ""
    return {
        "bvid": bvid,
        "title": title,
        "url": f"https://www.bilibili.com/video/{bvid}",
        "up_name": _clean(up_el.get_text(" ", strip=True) if up_el else None),
        "description": description[:4000] or None,
        "tags": tags[:30],
        "publish_date": _clean(date_el.get_text(" ", strip=True) if date_el else None),
    }


def parse_bili_identity(html: str, url: str) -> dict:
    """Logged-out detection uses the passport redirect and the unlogin header, both seen live.

    Nickname selectors on the account page were not confirmed against a logged-in session.
    """
    if "passport.bilibili.com" in url:
        return {"logged_in": False, "nickname": None, "uid": None}
    soup = BeautifulSoup(html, "html.parser")
    if soup.select_one(".header-avatar-unlogin-entry"):
        return {"logged_in": False, "nickname": None, "uid": None}
    nickname = None
    for selector in (".home-name", ".nickname", ".user-name", "#h-name", ".header-uname"):
        element = soup.select_one(selector)
        if element is None:
            continue
        text = _clean(element.get_text(" ", strip=True))
        if text and text not in {"登录", "登录/注册"}:
            nickname = text
            break
    uid = None
    uid_match = _UID_TEXT.search(soup.get_text(" ", strip=True))
    if uid_match:
        uid = uid_match.group(1)
    space_match = _SPACE_UID.search(url)
    if space_match:
        uid = space_match.group(1)
    if nickname or uid:
        return {"logged_in": True, "nickname": nickname, "uid": uid}
    return {"logged_in": None, "nickname": None, "uid": None}
