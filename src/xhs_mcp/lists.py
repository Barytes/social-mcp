"""Own-profile favorites. Scroll the collection page. Do not open the feed."""

from __future__ import annotations

import logging
import re

from mcp_browser.actions import goto_allowed, silence_media
from mcp_browser.errors import InvalidArgument, PageNotUnderstood, SiteError
from mcp_browser.list_cache import cache_file, contains_query, load_cache, save_cache
from mcp_browser.redact import redact

from xhs_mcp.flow import _LOGGED_OUT, _ensure_no_challenge, _read_identity
from xhs_mcp.parse import parse_xhs_board_tab, parse_xhs_favorite_notes
from xhs_mcp.urls import xhs_board_url, xhs_favorites_url

log = logging.getLogger(__name__)

_SCROLL_CAP = 300
_RESULT_CAP = 200


def _query(value: str) -> str:
    text = (value or "").strip()
    if not text or len(text) > 80 or re.search(r"[\x00-\x1f]", text):
        raise InvalidArgument("query must be 1–80 characters and contain no control characters.")
    return text


def _limit(value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 100:
        raise InvalidArgument("limit must be an integer from 1 to 100.")
    return value


def _board_id(value: str) -> str:
    text = (value or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9]{6,64}", text):
        raise InvalidArgument("board_id must be the id from a /board/ link.")
    return text


def _logged_out(url: str) -> dict:
    from mcp_browser.errors import NotLoggedIn

    return NotLoggedIn(_LOGGED_OUT, url=url, reason="session_absent_or_replaced").payload()


async def _owner(page, session) -> dict:
    cached = getattr(session, "owner_uid", None)
    if cached:
        return {"logged_in": True, "uid": cached, "nickname": getattr(session, "owner_nickname", None)}
    identity = await _read_identity(page, session)
    if identity.get("logged_in") is True and identity.get("uid"):
        session.owner_uid = identity["uid"]
        session.owner_nickname = identity.get("nickname")
    return identity


async def _scroll_notes(page, session, url: str, want: int) -> tuple[list[dict], str, bool]:
    await silence_media(page)
    final = await goto_allowed(page, url, session.policy, session)
    try:
        await page.wait_for_selector("section.note-item, .reds-tab-item", timeout=12000)
    except Exception:
        pass
    await _ensure_no_challenge(page, session)
    target = min(want, _SCROLL_CAP)
    last = -1
    stagnant = 0
    notes = parse_xhs_favorite_notes(await page.content())
    for _ in range(40):
        notes = parse_xhs_favorite_notes(await page.content())
        if len(notes) >= target:
            break
        if len(notes) == last:
            stagnant += 1
            if stagnant >= 2:
                break
        else:
            stagnant = 0
            last = len(notes)
        try:
            await page.mouse.wheel(0, 1600)
            await page.wait_for_timeout(700)
        except Exception:
            break
        await silence_media(page)
    truncated = len(notes) >= _SCROLL_CAP and len(notes) < want
    return notes[:_SCROLL_CAP], page.url or final, truncated


async def list_favorites(session, limit: int = 30) -> dict:
    try:
        limit_n = _limit(limit)
    except SiteError as exc:
        return exc.payload()

    async def op(page):
        identity = await _owner(page, session)
        if identity.get("logged_in") is not True or not identity.get("uid"):
            return identity, [], page.url, False
        notes, landed, truncated = await _scroll_notes(page, session, xhs_favorites_url(identity["uid"], "note"), limit_n)
        return identity, notes, landed, truncated

    try:
        identity, notes, landed, truncated = await session.call("list_favorites", op)
    except SiteError as exc:
        return exc.payload()
    except Exception as exc:
        log.exception("list_favorites failed")
        return {"ok": False, "error_type": "internal_error", "status": "internal_error", "message": redact(str(exc))[:300]}
    if identity.get("logged_in") is not True:
        return _logged_out(landed or identity.get("url") or "")
    return {
        "ok": True,
        "status": "results" if notes else "no_results",
        "uid": identity.get("uid"),
        "count": min(len(notes), limit_n),
        "results": notes[:limit_n],
        "has_more": len(notes) > limit_n or truncated,
        "truncated": truncated,
        "url": landed,
    }


async def list_favorite_boards(session) -> dict:
    async def op(page):
        identity = await _owner(page, session)
        if identity.get("logged_in") is not True or not identity.get("uid"):
            return identity, "", ""
        final = await goto_allowed(page, xhs_favorites_url(identity["uid"], "board"), session.policy, session)
        try:
            await page.wait_for_selector(".reds-tab-item, a[href*='/board/']", timeout=12000)
        except Exception:
            pass
        await _ensure_no_challenge(page, session)
        return identity, await page.content(), page.url or final

    try:
        identity, html, landed = await session.call("list_favorite_boards", op)
    except SiteError as exc:
        return exc.payload()
    except Exception as exc:
        log.exception("list_favorite_boards failed")
        return {"ok": False, "error_type": "internal_error", "status": "internal_error", "message": redact(str(exc))[:300]}
    if identity.get("logged_in") is not True:
        return _logged_out(landed or "")
    parsed = parse_xhs_board_tab(html)
    if parsed["boards"]:
        return {
            "ok": True,
            "status": "results",
            "uid": identity.get("uid"),
            "album_count": parsed["album_count"],
            "count": len(parsed["boards"]),
            "boards": parsed["boards"],
            "url": landed,
        }
    if parsed["album_count"] == 0:
        return {
            "ok": True,
            "status": "no_results",
            "uid": identity.get("uid"),
            "album_count": 0,
            "count": 0,
            "boards": [],
            "url": landed,
        }
    return PageNotUnderstood(
        "The favorites tab shows an 专辑 count but the document has no /board/ link. "
        "The saved capture is the 笔记 subtab, so the board document was not available to match. "
        "Not reporting an empty board list.",
        url=landed,
        status="page_not_understood",
        album_count=parsed["album_count"],
    ).payload()


async def get_favorite_board(session, board_id: str, limit: int = 30) -> dict:
    try:
        board = _board_id(board_id)
        limit_n = _limit(limit)
    except SiteError as exc:
        return exc.payload()

    async def op(page):
        identity = await _owner(page, session)
        if identity.get("logged_in") is not True:
            return identity, [], page.url, False
        notes, landed, truncated = await _scroll_notes(page, session, xhs_board_url(board), limit_n)
        return identity, notes, landed, truncated

    try:
        identity, notes, landed, truncated = await session.call("get_favorite_board", op)
    except SiteError as exc:
        return exc.payload()
    except Exception as exc:
        log.exception("get_favorite_board failed")
        return {"ok": False, "error_type": "internal_error", "status": "internal_error", "message": redact(str(exc))[:300]}
    if identity.get("logged_in") is not True:
        return _logged_out(landed or "")
    if not notes:
        return PageNotUnderstood(
            "The board URL opened but no note cards were found. If this document is not a normal page, use list_favorite_boards only.",
            url=landed,
            status="page_not_understood",
        ).payload()
    return {
        "ok": True,
        "status": "results",
        "board_id": board,
        "count": min(len(notes), limit_n),
        "results": notes[:limit_n],
        "truncated": truncated,
        "url": landed,
    }


def _filter_notes(notes: list[dict], query: str, board_id: str | None) -> list[dict]:
    matches = []
    for note in notes:
        if board_id and note.get("board_id") not in {None, board_id}:
            continue
        if contains_query(query, note.get("title"), note.get("author"), note.get("description")):
            matches.append(note)
    return matches


async def search_favorites(session, query: str, board_id: str | None = None, refresh: bool = False) -> dict:
    try:
        text = _query(query)
        board = _board_id(board_id) if board_id else None
    except SiteError as exc:
        return exc.payload()
    path = cache_file(session.config.data_dir, "xhs-favorites")
    if not refresh:
        cached = load_cache(path)
        if cached is not None:
            matches = _filter_notes(cached["items"], text, board)
            return {
                "ok": True,
                "status": "results" if matches else "no_results",
                "query": text,
                "board_id": board,
                "from_cache": True,
                "fetched_at": cached.get("fetched_at"),
                "count": min(len(matches), _RESULT_CAP),
                "results": matches[:_RESULT_CAP],
                "truncated": len(matches) > _RESULT_CAP,
                "token_note": "Cached rows omit xsec_token. Open a fresh list_favorites result when the note URL needs one.",
            }

    async def op(page):
        identity = await _owner(page, session)
        if identity.get("logged_in") is not True or not identity.get("uid"):
            return identity, [], "", False
        url = xhs_board_url(board) if board else xhs_favorites_url(identity["uid"], "note")
        notes, landed, truncated = await _scroll_notes(page, session, url, _SCROLL_CAP)
        for note in notes:
            note["board_id"] = board
        return identity, notes, landed, truncated

    try:
        identity, notes, landed, truncated = await session.call("search_favorites", op)
    except SiteError as exc:
        return exc.payload()
    except Exception as exc:
        log.exception("search_favorites failed")
        return {"ok": False, "error_type": "internal_error", "status": "internal_error", "message": redact(str(exc))[:300]}
    if identity.get("logged_in") is not True:
        return _logged_out(landed or "")
    fetched_at = None
    if board is None:
        stored = save_cache(path, notes)
        notes = stored["items"]
        fetched_at = stored["fetched_at"]
    matches = _filter_notes(notes, text, board)
    return {
        "ok": True,
        "status": "results" if matches else "no_results",
        "query": text,
        "board_id": board,
        "uid": identity.get("uid"),
        "from_cache": False,
        "fetched_at": fetched_at,
        "count": min(len(matches), _RESULT_CAP),
        "results": matches[:_RESULT_CAP],
        "truncated": truncated or len(matches) > _RESULT_CAP,
        "url": landed,
        "token_note": "A live result keeps the page's xsec_token. The on-disk cache drops it.",
    }
