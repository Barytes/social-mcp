"""Favorite folders and 稍后再看. Read from the rendered page. Do not play the video."""

from __future__ import annotations

import logging
import re

from mcp_browser.actions import goto_allowed, safe_click, safe_fill, silence_media
from mcp_browser.errors import InvalidArgument, NotLoggedIn, PageNotUnderstood, SiteError
from mcp_browser.guard import ClickPurpose, FillPurpose
from mcp_browser.list_cache import cache_file, contains_query, load_cache, save_cache
from mcp_browser.redact import redact

from bili_mcp.flow import _ensure_no_challenge, _read_identity
from bili_mcp.parse import (
    bili_has_more,
    parse_bili_favorite_folders,
    parse_bili_folder_videos,
    parse_bili_watch_later,
)
from bili_mcp.urls import SPACE_HOME, WATCH_LATER_URL, bili_favlist_url

log = logging.getLogger(__name__)

_UID_IN_URL = re.compile(r"space\.bilibili\.com/(\d{3,16})")
_PAGE_CAP = 15
_WATCH_CAP = 500
_RESULT_CAP = 200
_SORTS = {
    "recent": "最近收藏",
    "most_played": "最多播放",
    "recent_submit": "最近投稿",
}
_HISTORY_NOTE = (
    "Playback requests (.m4s, .flv, m3u8, playurl) and history-report / click-interface "
    "requests are aborted. Video and audio elements are muted and paused, and Chrome is "
    "started with autoplay blocked until a gesture. Whether the history list itself stays "
    "unchanged was not checked on a logged-in session: the player document still loads."
)


def _query(value: str) -> str:
    text = (value or "").strip()
    if not text or len(text) > 80 or re.search(r"[\x00-\x1f]", text):
        raise InvalidArgument("query must be 1–80 characters and contain no control characters.")
    return text


def _fid(value: str) -> str:
    text = (value or "").strip()
    if not text.isdigit() or not 1 <= len(text) <= 20:
        raise InvalidArgument("folder id must be the numeric fid from list_favorite_folders.")
    return text


def _page(value: int, cap: int = 50) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= cap:
        raise InvalidArgument(f"page must be an integer from 1 to {cap}.")
    return value


def _limit(value: int, cap: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= cap:
        raise InvalidArgument(f"limit must be an integer from 1 to {cap}.")
    return value


def _uid_from_url(url: str) -> str | None:
    match = _UID_IN_URL.search(url or "")
    return match.group(1) if match else None


async def _click_exact(page, label: str, purpose: ClickPurpose) -> bool:
    locator = page.get_by_text(label, exact=True)
    try:
        count = await locator.count()
    except Exception:
        return False
    for index in range(min(count, 6)):
        item = locator.nth(index)
        try:
            class_name = (await item.get_attribute("class")) or ""
            if "disabled" in class_name:
                continue
            box = await item.bounding_box()
        except Exception:
            continue
        if not box or box.get("width", 0) < 8 or box.get("height", 0) < 8:
            continue
        await safe_click(item, purpose)
        return True
    return False


async def owner_uid(page, session) -> str:
    cached = getattr(session, "owner_uid", None)
    if cached:
        return cached
    await goto_allowed(page, SPACE_HOME, session.policy, session)
    uid = None
    for _ in range(8):
        uid = _uid_from_url(page.url or "")
        if uid:
            break
        try:
            await page.wait_for_timeout(500)
        except Exception:
            break
    if not uid:
        identity = await _read_identity(page, session)
        uid = identity.get("uid")
        if identity.get("logged_in") is False:
            raise NotLoggedIn(
                "Not logged in. space.bilibili.com did not redirect to a numeric uid.",
                url=page.url,
                reason="not_authenticated",
            )
    if not uid:
        raise PageNotUnderstood(
            "space.bilibili.com did not redirect to /<uid>, and the account page had no uid.",
            url=page.url,
            status="page_not_understood",
        )
    session.owner_uid = str(uid)
    return session.owner_uid


def _logged_out(url: str) -> dict:
    return NotLoggedIn(
        "Not logged in. The favorites page redirected to the official login page.",
        url=url,
        reason="not_authenticated",
    ).payload()


async def list_favorite_folders(session) -> dict:
    async def op(page):
        uid = await owner_uid(page, session)
        final = await goto_allowed(page, bili_favlist_url(uid), session.policy, session)
        try:
            await page.wait_for_selector(".fav-sidebar-item, .header-avatar-unlogin-entry", timeout=12000)
        except Exception:
            pass
        await _ensure_no_challenge(page, session)
        return uid, final, await page.content(), page.url

    try:
        uid, final, html, landed = await session.call("list_favorite_folders", op)
    except SiteError as exc:
        return exc.payload()
    except Exception as exc:
        log.exception("list_favorite_folders failed")
        return {"ok": False, "error_type": "internal_error", "status": "internal_error", "message": redact(str(exc))[:300]}
    if "passport.bilibili.com" in (landed or ""):
        return _logged_out(landed or final)
    folders = parse_bili_favorite_folders(html, landed or final)
    if not folders:
        return PageNotUnderstood(
            "The favorites page loaded but the sidebar had no folder rows.",
            url=landed or final,
            status="page_not_understood",
        ).payload()
    return {
        "ok": True,
        "status": "results",
        "uid": uid,
        "count": len(folders),
        "folders": folders,
        "url": landed or final,
        "id_note": "Created folders expose fid as the row id, except 默认收藏夹 when the address has no fid query. Followed rows in this capture had no fid.",
    }


async def _open_folder(page, session, uid: str, fid: str | None, sort: str | None, query: str | None) -> bool:
    await goto_allowed(page, bili_favlist_url(uid, fid), session.policy, session)
    try:
        # .favlist-main renders about a second before its cards; wait for the cards themselves.
        await page.wait_for_selector(".favlist-main .bili-video-card", timeout=12000)
    except Exception:
        pass
    await _ensure_no_challenge(page, session)
    if sort and sort != "recent":
        await _click_exact(page, _SORTS[sort], ClickPurpose.SORT_LIST)
        try:
            await page.wait_for_timeout(800)
        except Exception:
            pass
    used = False
    if query:
        field = page.locator("input.fav-list-header-filter__search").first
        try:
            if await field.count():
                await safe_fill(field, query, FillPurpose.LIST_FILTER)
                # The box only filters after Enter; filling alone leaves the full page in place.
                await field.press("Enter")
                used = True
                await page.wait_for_timeout(2000)
        except Exception:
            log.info("folder search box was not used")
    return used


async def _collect_folder_pages(page, limit_pages: int) -> tuple[list[dict], bool]:
    collected: list[dict] = []
    seen: set[str] = set()
    truncated = False
    for index in range(limit_pages):
        html = await page.content()
        for video in parse_bili_folder_videos(html):
            if video["bvid"] in seen:
                continue
            seen.add(video["bvid"])
            collected.append(video)
        if not bili_has_more(html):
            return collected, False
        if index + 1 >= limit_pages:
            return collected, True
        moved = await _click_exact(page, "下一页", ClickPurpose.TURN_PAGE)
        if not moved:
            return collected, False
        try:
            await page.wait_for_timeout(800)
        except Exception:
            pass
    truncated = True
    return collected, truncated


async def get_favorite_folder(session, fid: str, page: int = 1, sort: str | None = None, keyword: str | None = None) -> dict:
    try:
        folder_id = _fid(fid)
        page_n = _page(page)
        if sort is not None and sort not in _SORTS:
            raise InvalidArgument("sort must be recent, most_played, or recent_submit.")
        text = _query(keyword) if keyword else None
    except SiteError as exc:
        return exc.payload()

    async def op(browser_page):
        uid = await owner_uid(browser_page, session)
        used = await _open_folder(browser_page, session, uid, folder_id, sort, text)
        if page_n > 1:
            for _ in range(page_n - 1):
                html = await browser_page.content()
                if not bili_has_more(html):
                    break
                moved = await _click_exact(browser_page, "下一页", ClickPurpose.TURN_PAGE)
                if not moved:
                    break
                await browser_page.wait_for_timeout(800)
        html = await browser_page.content()
        return uid, used, html, browser_page.url

    try:
        uid, used, html, landed = await session.call("get_favorite_folder", op)
    except SiteError as exc:
        return exc.payload()
    except Exception as exc:
        log.exception("get_favorite_folder failed")
        return {"ok": False, "error_type": "internal_error", "status": "internal_error", "message": redact(str(exc))[:300]}
    if "passport.bilibili.com" in (landed or ""):
        return _logged_out(landed)
    videos = parse_bili_folder_videos(html)
    if text:
        videos = [video for video in videos if contains_query(text, video.get("title"), video.get("up_name"))]
    if not videos and not (landed and "favlist" in landed):
        return PageNotUnderstood(
            "The folder URL did not render a favorites document.",
            url=landed,
            status="page_not_understood",
        ).payload()
    return {
        "ok": True,
        "status": "results" if videos else "no_results",
        "uid": uid,
        "folder_id": folder_id,
        "page": page_n,
        "sort": sort or "recent",
        "keyword": text,
        "search_box_used": used,
        "count": len(videos),
        "results": videos,
        "has_more": bili_has_more(html),
        "url": landed,
    }


async def _crawl_created_folders(page, session, folder_id: str | None) -> tuple[list[dict], bool, str]:
    uid = await owner_uid(page, session)
    await goto_allowed(page, bili_favlist_url(uid), session.policy, session)
    try:
        await page.wait_for_selector(".fav-sidebar-item", timeout=12000)
    except Exception:
        pass
    folders = parse_bili_favorite_folders(await page.content(), page.url or "")
    created = [folder for folder in folders if folder["kind"] == "created" and not folder["invalid"]]
    if folder_id:
        created = [folder for folder in created if folder["id"] == folder_id] or [{"id": folder_id, "name": None, "kind": "created"}]
    items: list[dict] = []
    truncated = False
    for folder in created:
        await _open_folder(page, session, uid, folder.get("id"), None, None)
        videos, hit_cap = await _collect_folder_pages(page, _PAGE_CAP)
        truncated = truncated or hit_cap
        for video in videos:
            video["folder_id"] = folder.get("id")
            video["folder_name"] = folder.get("name")
            items.append(video)
    return items, truncated, uid


async def search_favorites(session, query: str, folder_id: str | None = None, refresh: bool = False) -> dict:
    try:
        text = _query(query)
        folder = _fid(folder_id) if folder_id else None
    except SiteError as exc:
        return exc.payload()
    path = cache_file(session.config.data_dir, "bili-favorites")
    if not refresh:
        cached = load_cache(path)
        if cached is not None:
            matches = [
                item
                for item in cached["items"]
                if (folder is None or item.get("folder_id") == folder)
                and contains_query(text, item.get("title"), item.get("up_name"))
            ]
            return {
                "ok": True,
                "status": "results" if matches else "no_results",
                "query": text,
                "folder_id": folder,
                "from_cache": True,
                "fetched_at": cached.get("fetched_at"),
                "count": min(len(matches), _RESULT_CAP),
                "results": matches[:_RESULT_CAP],
                "truncated": len(matches) > _RESULT_CAP,
            }

    async def op(page):
        return await _crawl_created_folders(page, session, folder)

    try:
        items, truncated, uid = await session.call("search_favorites", op)
    except SiteError as exc:
        return exc.payload()
    except Exception as exc:
        log.exception("search_favorites failed")
        return {"ok": False, "error_type": "internal_error", "status": "internal_error", "message": redact(str(exc))[:300]}
    fetched_at = None
    saved = items
    if folder is None:
        stored = save_cache(path, items)
        saved = stored["items"]
        fetched_at = stored["fetched_at"]
    matches = [item for item in saved if contains_query(text, item.get("title"), item.get("up_name"))]
    return {
        "ok": True,
        "status": "results" if matches else "no_results",
        "query": text,
        "folder_id": folder,
        "uid": uid,
        "from_cache": False,
        "fetched_at": fetched_at,
        "count": min(len(matches), _RESULT_CAP),
        "results": matches[:_RESULT_CAP],
        "truncated": truncated or len(matches) > _RESULT_CAP,
        "crawled": len(saved),
    }


async def _collect_watch_later(page, session, want: int) -> tuple[dict, bool]:
    await silence_media(page)
    final = await goto_allowed(page, WATCH_LATER_URL, session.policy, session)
    try:
        await page.wait_for_selector(".action-list-item-wrap, .list-count", timeout=12000)
    except Exception:
        pass
    await silence_media(page)
    await _ensure_no_challenge(page, session)
    last = -1
    stagnant = 0
    truncated = False
    parsed = parse_bili_watch_later(await page.content())
    target = min(want, _WATCH_CAP)
    for _ in range(40):
        parsed = parse_bili_watch_later(await page.content())
        count = len(parsed["items"])
        if count >= target:
            break
        if count == last:
            stagnant += 1
            if stagnant >= 2:
                break
        else:
            stagnant = 0
            last = count
        # The scrolling element is .action-list (overflow-y: auto); .action-list-body does not scroll.
        locator = page.locator(".action-list-item-wrap").last
        try:
            if await locator.count():
                await locator.scroll_into_view_if_needed()
            else:
                await page.mouse.wheel(0, 1400)
        except Exception:
            break
        try:
            await page.wait_for_timeout(1500)
        except Exception:
            break
        await silence_media(page)
    else:
        truncated = True
    if len(parsed["items"]) >= _WATCH_CAP and (parsed.get("total") or 0) > _WATCH_CAP:
        truncated = True
    parsed["url"] = page.url or final
    return parsed, truncated


async def list_watch_later(session, page: int = 1, limit: int = 30) -> dict:
    try:
        page_n = _page(page, 20)
        limit_n = _limit(limit, 100)
    except SiteError as exc:
        return exc.payload()
    want = page_n * limit_n

    async def op(browser_page):
        return await _collect_watch_later(browser_page, session, min(want, _WATCH_CAP))

    try:
        parsed, truncated = await session.call("list_watch_later", op)
    except SiteError as exc:
        return exc.payload()
    except Exception as exc:
        log.exception("list_watch_later failed")
        return {"ok": False, "error_type": "internal_error", "status": "internal_error", "message": redact(str(exc))[:300]}
    landed = parsed.get("url") or ""
    if "passport.bilibili.com" in landed:
        return _logged_out(landed)
    if not parsed["items"] and not parsed.get("list_count"):
        return PageNotUnderstood(
            "The watch-later player page did not show the 稍后再看 panel. /watchlater/#/list is not opened; it starts a download.",
            url=landed,
            status="page_not_understood",
        ).payload()
    start = (page_n - 1) * limit_n
    window = parsed["items"][start : start + limit_n]
    total = parsed.get("total")
    has_more = start + len(window) < len(parsed["items"]) or (total is not None and start + limit_n < total)
    return {
        "ok": True,
        "status": "results" if window else "no_results",
        "page": page_n,
        "limit": limit_n,
        "count": len(window),
        "total": total,
        "current_index": parsed.get("current_index"),
        "results": window,
        "has_more": has_more,
        "truncated": truncated or want > _WATCH_CAP,
        "url": landed,
        "up_name": None,
        "up_name_note": "The 稍后再看 panel shows title, play count, and data-key bvid. It does not show the UP name. Recommendations under the player are not parsed.",
        "media_blocked": True,
        "history_write_verified": False,
        "history_note": _HISTORY_NOTE,
    }


async def search_watch_later(session, query: str, refresh: bool = False) -> dict:
    try:
        text = _query(query)
    except SiteError as exc:
        return exc.payload()
    path = cache_file(session.config.data_dir, "bili-watch-later")
    if not refresh:
        cached = load_cache(path)
        if cached is not None:
            matches = [item for item in cached["items"] if contains_query(text, item.get("title"), item.get("up_name"))]
            return {
                "ok": True,
                "status": "results" if matches else "no_results",
                "query": text,
                "from_cache": True,
                "fetched_at": cached.get("fetched_at"),
                "count": min(len(matches), _RESULT_CAP),
                "results": matches[:_RESULT_CAP],
                "truncated": len(matches) > _RESULT_CAP,
            }

    async def op(page):
        return await _collect_watch_later(page, session, _WATCH_CAP)

    try:
        parsed, truncated = await session.call("search_watch_later", op)
    except SiteError as exc:
        return exc.payload()
    except Exception as exc:
        log.exception("search_watch_later failed")
        return {"ok": False, "error_type": "internal_error", "status": "internal_error", "message": redact(str(exc))[:300]}
    stored = save_cache(path, parsed["items"])
    matches = [item for item in stored["items"] if contains_query(text, item.get("title"), item.get("up_name"))]
    return {
        "ok": True,
        "status": "results" if matches else "no_results",
        "query": text,
        "from_cache": False,
        "fetched_at": stored["fetched_at"],
        "count": min(len(matches), _RESULT_CAP),
        "results": matches[:_RESULT_CAP],
        "truncated": truncated or len(matches) > _RESULT_CAP or (parsed.get("total") or 0) > len(parsed["items"]),
        "crawled": len(stored["items"]),
        "total": parsed.get("total"),
        "media_blocked": True,
        "history_write_verified": False,
        "history_note": _HISTORY_NOTE,
    }
