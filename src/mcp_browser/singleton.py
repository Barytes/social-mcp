"""Clear a Chrome profile lock left by a crash. Never delete cookies or login data."""

from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path

from mcp_browser.errors import ProfileInUse

_LOCK_NAMES = ("SingletonLock", "SingletonCookie", "SingletonSocket")
_ZOMBIE = re.compile(r"\)\s+Z\b")


def _is_zombie(pid: int) -> bool:
    try:
        stat = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    return _ZOMBIE.search(stat) is not None


def chrome_pids_for_profile(profile: Path) -> list[int]:
    """PIDs of live Chrome processes launched with this user-data-dir."""
    needle = str(profile.resolve())
    proc = Path("/proc")
    if not proc.is_dir():
        return []
    found: list[int] = []
    for entry in proc.iterdir():
        if not entry.name.isdigit():
            continue
        pid = int(entry.name)
        if _is_zombie(pid):
            continue
        try:
            raw = (entry / "cmdline").read_bytes()
        except OSError:
            continue
        command = raw.replace(b"\x00", b" ").decode("utf-8", "replace")
        lowered = command.lower()
        if "chrome" not in lowered and "chromium" not in lowered:
            continue
        if needle in command or str(profile) in command:
            found.append(pid)
    return found


def _remove_lock_file(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink()
        return
    if path.exists():
        raise ProfileInUse(
            f"Refusing to remove unexpected lock entry {path.name}; close the other browser first.",
            profile_dir=str(path.parent),
        )


def prepare_profile(
    profile: Path,
    *,
    pids_using_profile: Callable[[Path], list[int]] = chrome_pids_for_profile,
) -> None:
    """Create the profile dir and drop a lock whose Chrome process is already gone."""
    profile.mkdir(parents=True, exist_ok=True)
    pids = pids_using_profile(profile)
    if pids:
        raise ProfileInUse(
            "This profile is already open in Chrome. Stop the other MCP server or browser "
            "using the same profile, then retry.",
            profile_dir=str(profile),
            pids=pids,
        )
    for name in _LOCK_NAMES:
        _remove_lock_file(profile / name)
