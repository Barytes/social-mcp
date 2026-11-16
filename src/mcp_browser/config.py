"""Paths and Chrome settings. Profiles default to ~/.local/share and must stay outside the repo."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from mcp_browser.errors import ConfigError


def _flag(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


def _repo_root(path: Path) -> Path | None:
    start = path if path.is_dir() else path.parent
    for candidate in (start, *start.parents):
        git_entry = candidate / ".git"
        if git_entry.exists():
            return candidate
    return None


def assert_outside_repo(path: Path, *, what: str) -> None:
    root = _repo_root(path)
    if root is not None:
        raise ConfigError(
            f"{what} must live outside the git repository ({root}). "
            "The browser profile holds the login session and must not be committed.",
            path=str(path),
        )


def _reject_broad_path(path: Path, *, what: str) -> None:
    resolved = path.resolve()
    banned = {Path.home().resolve(), Path("/").resolve(), Path("/tmp").resolve(), Path("/var/tmp").resolve()}
    if resolved in banned:
        raise ConfigError(f"{what} is too broad: {resolved}")


@dataclass(frozen=True)
class SiteConfig:
    name: str
    chrome_path: str
    headed: bool
    data_dir: Path
    profile_dir: Path
    log_file: Path
    screenshot_dir: Path
    qr_path: Path

    @classmethod
    def load(cls, name: str, env_prefix: str) -> SiteConfig:
        data_default = Path.home() / ".local" / "share" / name
        data_dir = Path(os.environ.get(f"{env_prefix}_DATA_DIR", str(data_default))).expanduser()
        profile_dir = Path(os.environ.get(f"{env_prefix}_PROFILE_DIR", str(data_dir / "profile"))).expanduser()
        chrome = (
            os.environ.get(f"{env_prefix}_CHROME_PATH")
            or os.environ.get("MCP_CHROME_PATH")
            or "/usr/bin/google-chrome"
        )
        headed = _flag(os.environ.get(f"{env_prefix}_HEADED", os.environ.get("MCP_HEADED")))
        _reject_broad_path(data_dir, what=f"{env_prefix} data dir")
        _reject_broad_path(profile_dir, what=f"{env_prefix} profile dir")
        assert_outside_repo(data_dir, what=f"{env_prefix} data dir")
        assert_outside_repo(profile_dir, what=f"{env_prefix} profile dir")
        if headed and not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
            raise ConfigError(
                "Headed mode needs $DISPLAY or $WAYLAND_DISPLAY so a person can use the same Chrome window.",
                name=name,
            )
        return cls(
            name=name,
            chrome_path=chrome,
            headed=headed,
            data_dir=data_dir,
            profile_dir=profile_dir,
            log_file=data_dir / "logs" / f"{name}.log",
            screenshot_dir=data_dir / "screenshots",
            qr_path=data_dir / "qr" / "login-qr.png",
        )
