"""Shared smoke-test output. Stdout is fine here; these commands are not MCP servers."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from mcp_browser.config import SiteConfig


def dumps(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2)


def emit(payload: dict[str, Any]) -> int:
    print(dumps(payload))
    status = payload.get("status")
    error_type = payload.get("error_type")
    if status == "needs_human_verification" or error_type == "needs_human_verification":
        return 3
    if payload.get("logged_in") is False:
        return 2
    if payload.get("ok"):
        return 0
    if error_type == "profile_in_use":
        return 5
    if error_type in {"page_load_failed", "page_not_understood", "login_ui_not_found"}:
        return 4
    return 1


def doctor(config: SiteConfig) -> dict[str, Any]:
    chrome = Path(config.chrome_path)
    version = None
    if chrome.is_file():
        try:
            version = subprocess.check_output([str(chrome), "--version"], text=True, stderr=subprocess.STDOUT, timeout=15).strip()
        except (OSError, subprocess.SubprocessError) as exc:
            version = f"failed: {exc.__class__.__name__}"
    display = bool(__import__("os").environ.get("DISPLAY") or __import__("os").environ.get("WAYLAND_DISPLAY"))
    ok = chrome.is_file() and not (config.headed and not display)
    return {
        "ok": ok,
        "status": "ok" if ok else "config_error",
        "chrome_path": str(chrome),
        "chrome_exists": chrome.is_file(),
        "chrome_version": version,
        "headed": config.headed,
        "display_available": display,
        "profile_dir": str(config.profile_dir),
        "data_dir": str(config.data_dir),
        "log_file": str(config.log_file),
        "message": "Doctor does not open the site or the browser profile.",
    }
