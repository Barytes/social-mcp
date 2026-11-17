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


def _space_url(href: str | None) -> str | None:
    if not href:
        return None
    if href.startswith("//"):
        href = "https:" + href
    elif href.startswith("/"):
        href = "https://space.bilibili.com" + href
    if not href.startswith("http"):
        return None
    from urllib.parse import urlsplit, urlunsplit

    parts = urlsplit(href)
    if not parts.netloc:
        return None
    path = parts.path.rstrip("/") or "/"
    return urlunsplit((parts.scheme or "https", parts.netloc, path, "", ""))


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
    duration_el = soup.select_one(".bpx-player-ctrl-time-duration")
    parts: list[str] = []
    for part in soup.select(".video-pod__item, .video-episode-card, .multi-page-item"):
        text = _clean(part.get_text(" ", strip=True))
        if text and text not in parts:
            parts.append(text)
    stats = {
        "play_count": _clean(soup.select_one(".view-text").get_text(" ", strip=True) if soup.select_one(".view-text") else None),
        "like_count": _clean(soup.select_one(".video-like-info").get_text(" ", strip=True) if soup.select_one(".video-like-info") else None),
        "coin_count": _clean(soup.select_one(".video-coin-info").get_text(" ", strip=True) if soup.select_one(".video-coin-info") else None),
        "favorite_count": _clean(soup.select_one(".video-fav-info").get_text(" ", strip=True) if soup.select_one(".video-fav-info") else None),
        "share_count": _clean(soup.select_one(".video-share-info").get_text(" ", strip=True) if soup.select_one(".video-share-info") else None),
        "duration": _clean(duration_el.get_text(" ", strip=True) if duration_el else None),
    }
    return {
        "bvid": bvid,
        "title": title,
        "url": f"https://www.bilibili.com/video/{bvid}",
        "up_name": _clean(up_el.get_text(" ", strip=True) if up_el else None),
        "up_space_url": _space_url(up_el.get("href") if up_el else None),
        "description": description[:4000] or None,
        "tags": tags[:30],
        "publish_date": _clean(date_el.get_text(" ", strip=True) if date_el else None),
        "duration": stats["duration"],
        "stats": stats,
        "parts": parts[:100],
    }


_FOLDER_KIND = {
    "我创建的收藏夹": "created",
    "我追的合集/收藏夹": "followed",
    "其他收藏": "other",
}
_DURATION = re.compile(r"^\d{1,2}:\d{2}(?::\d{2})?$")


def _folder_count(text: str | None) -> int | None:
    cleaned = _clean(text)
    if cleaned and cleaned.isdigit():
        return int(cleaned)
    return None


def parse_bili_favorite_folders(html: str, page_url: str = "") -> list[dict]:
    """Sidebar on space.bilibili.com/<uid>/favlist. Ids are the row id when the DOM has one."""
    from urllib.parse import parse_qs, urlsplit

    soup = BeautifulSoup(html, "html.parser")
    query_fid = (parse_qs(urlsplit(page_url).query).get("fid") or [None])[0]
    if query_fid and not str(query_fid).isdigit():
        query_fid = None
    folders: list[dict] = []
    for collapse in soup.select(".fav-collapse"):
        header = collapse.select_one(".vui_collapse_item_header")
        label = _clean(header.get_text(" ", strip=True) if header else None) or ""
        kind = _FOLDER_KIND.get(label)
        if kind is None:
            continue
        for row in collapse.select(".fav-sidebar-item"):
            name = _clean(row.get("title")) or _clean(row.get_text(" ", strip=True))
            if not name or name in {"新建收藏夹"}:
                continue
            count_el = row.select_one(".vui_sidebar-item-right")
            raw_id = (row.get("id") or "").strip()
            folder_id = raw_id if raw_id.isdigit() else None
            active = row.select_one(".vui_sidebar-item--active") is not None
            if folder_id is None and active and query_fid:
                folder_id = str(query_fid)
            invalid = row.select_one(".vui_sidebar-item--disabled") is not None or "已失效" in name
            folders.append(
                {
                    "id": folder_id,
                    "name": name,
                    "count": _folder_count(count_el.get_text(" ", strip=True) if count_el else None),
                    "kind": kind,
                    "invalid": invalid,
                }
            )
    return folders


def parse_bili_folder_videos(html: str) -> list[dict]:
    """Video cards inside a favorite folder. Does not read the sidebar."""
    soup = BeautifulSoup(html, "html.parser")
    root = soup.select_one(".favlist-main") or soup
    videos: list[dict] = []
    seen: set[str] = set()
    for card in root.select(".bili-video-card"):
        link = card.select_one("a[href*='/video/BV']")
        if link is None:
            continue
        match = _BV.search(link.get("href") or "")
        if match is None:
            continue
        bvid = match.group(1)
        if bvid in seen:
            continue
        seen.add(bvid)
        title_el = card.select_one(".bili-video-card__title")
        title = _clean((title_el.get("title") if title_el else None) or (title_el.get_text(" ", strip=True) if title_el else None)) or ""
        author_el = card.select_one(".bili-video-card__author span[title]") or card.select_one(".bili-video-card__subtitle")
        author_raw = _clean((author_el.get("title") if author_el else None) or (author_el.get_text(" ", strip=True) if author_el else None)) or ""
        up_name = author_raw
        saved_at = None
        if "收藏于" in author_raw:
            up_name, _, when = author_raw.partition("收藏于")
            up_name = up_name.strip(" ·・•")
            saved_at = when.strip() or None
        stats = [_clean(item.get_text(" ", strip=True)) for item in card.select(".bili-cover-card__stat")]
        stats = [item for item in stats if item]
        play_count = next((item for item in stats if not _DURATION.match(item)), None)
        duration = next((item for item in stats if _DURATION.match(item)), None)
        videos.append(
            {
                "title": title,
                "bvid": bvid,
                "url": f"https://www.bilibili.com/video/{bvid}",
                "up_name": up_name or None,
                "play_count": play_count,
                "duration": duration,
                "saved_at": saved_at,
                "invalid": title == "已失效视频",
            }
        )
    return videos


def parse_bili_watch_later(html: str) -> dict:
    """Right-hand 稍后再看 panel. Recommendation cards under the player are ignored."""
    soup = BeautifulSoup(html, "html.parser")
    count_el = soup.select_one(".list-count")
    count_text = _clean(count_el.get_text(" ", strip=True) if count_el else None) or ""
    current_index = None
    total = None
    count_match = re.search(r"(\d+)\s*/\s*(\d+)", count_text)
    if count_match:
        current_index = int(count_match.group(1))
        total = int(count_match.group(2))
    items: list[dict] = []
    for index, wrap in enumerate(soup.select(".action-list-body .action-list-item-wrap"), start=1):
        bvid = (wrap.get("data-key") or "").strip()
        if not _BV.search("/video/" + bvid):
            continue
        title_el = wrap.select_one(".title")
        views_el = wrap.select_one(".views")
        title = _clean((title_el.get("title") if title_el else None) or (title_el.get_text(" ", strip=True) if title_el else None)) or ""
        items.append(
            {
                "position": index,
                "title": title,
                "bvid": bvid,
                "url": f"https://www.bilibili.com/video/{bvid}",
                "up_name": None,
                "play_count": _clean(views_el.get_text(" ", strip=True) if views_el else None),
            }
        )
    return {"items": items, "current_index": current_index, "total": total, "list_count": count_text or None}


def parse_bili_identity(html: str, url: str) -> dict:
    """Logged-out detection uses the passport redirect and the unlogin header, both seen live.

    The logged-in nickname on account.bilibili.com/account/home is span.home-top-msg-name
    (seen 2026-11-17). Older class names stay as fallbacks.
    """
    if "passport.bilibili.com" in url:
        return {"logged_in": False, "nickname": None, "uid": None}
    soup = BeautifulSoup(html, "html.parser")
    if soup.select_one(".header-avatar-unlogin-entry"):
        return {"logged_in": False, "nickname": None, "uid": None}
    nickname = None
    for selector in (
        "span.home-top-msg-name",
        ".home-top-msg-name",
        ".home-name",
        ".nickname",
        ".user-name",
        "#h-name",
        ".header-uname",
    ):
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
