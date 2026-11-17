"""Start Xiaohongshu's headed MCP server on a dedicated X display.

Headless Chrome is sent to Xiaohongshu's risk page. Register this command instead of
`xhs-mcp` when the machine has no real display:

    uv run xhs-mcp-xvfb

It starts Xvfb on :90 if that display is not already up, then runs the same server
with XHS_HEADED=1. The password and SMS forms stay in that window for a person.
"""

from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

DISPLAY = ":90"
_SOCKET_DIR = Path("/tmp/.X11-unix")


def display_socket(display: str = DISPLAY, socket_dir: Path = _SOCKET_DIR) -> Path:
    number = display.split(":", 1)[-1]
    return socket_dir / f"X{number}"


def ensure_xvfb(display: str = DISPLAY, socket_dir: Path = _SOCKET_DIR, popen=subprocess.Popen) -> None:
    if display_socket(display, socket_dir).exists():
        return
    if not _binary_exists("Xvfb"):
        raise SystemExit("Xvfb is not installed. Install the xvfb package, then run xhs-mcp-xvfb again.")
    popen(
        ["Xvfb", display, "-screen", "0", "1366x900x24", "-nolisten", "tcp"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if display_socket(display, socket_dir).exists():
            return
        time.sleep(0.1)
    raise SystemExit(f"Xvfb did not create {display_socket(display, socket_dir)}.")


def _binary_exists(name: str) -> bool:
    return any((Path(entry) / name).is_file() for entry in os.environ.get("PATH", "").split(os.pathsep) if entry)


def main() -> None:
    ensure_xvfb()
    os.environ["DISPLAY"] = DISPLAY
    os.environ["XHS_HEADED"] = "1"
    from xhs_mcp.cli import main as serve

    serve()
