"""Planned reads. Not registered as tools and not exercised against the live site."""

from __future__ import annotations

from xhs_mcp.urls import FAVORITES_NOTE


def list_favorites(user_id: str) -> dict:
    return {
        "ok": False,
        "error_type": "not_implemented",
        "status": "not_implemented",
        "tested": False,
        "message": "Xiaohongshu favorites are planned. Do not click 收藏; open the profile URL directly. The tab name is unverified.",
        "planned_url": FAVORITES_NOTE.format(user_id=user_id),
    }
