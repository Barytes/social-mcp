"""Planned reads. Not registered as tools and not exercised against the live site."""

from __future__ import annotations

from bili_mcp.urls import FAVORITES_URL, WATCH_LATER_URL


def list_favorites(uid: str) -> dict:
    """Open the user's favlist by URL. Do not click 收藏."""
    return {
        "ok": False,
        "error_type": "not_implemented",
        "status": "not_implemented",
        "tested": False,
        "message": "Bilibili favorites are planned. The URL is allowlisted so a later change can navigate there directly.",
        "planned_url": FAVORITES_URL.format(uid=uid),
    }


def list_watch_later() -> dict:
    return {
        "ok": False,
        "error_type": "not_implemented",
        "status": "not_implemented",
        "tested": False,
        "message": "稍后再看 is planned. Not implemented and not tested.",
        "planned_url": WATCH_LATER_URL,
    }
