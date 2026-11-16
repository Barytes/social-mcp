from pathlib import Path

import pytest

from mcp_browser.config import assert_outside_repo
from mcp_browser.errors import ConfigError, ProfileInUse
from mcp_browser.singleton import prepare_profile


def test_stale_lock_is_removed_and_cookies_stay(tmp_path: Path) -> None:
    profile = tmp_path / "profile"
    profile.mkdir()
    (profile / "Cookies").write_text("keep", encoding="utf-8")
    outside = tmp_path / "outside"
    outside.write_text("keep-target", encoding="utf-8")
    (profile / "SingletonLock").symlink_to(outside)
    (profile / "SingletonSocket").write_text("", encoding="utf-8")
    prepare_profile(profile, pids_using_profile=lambda _path: [])
    assert not (profile / "SingletonLock").exists()
    assert not (profile / "SingletonSocket").exists()
    assert (profile / "Cookies").read_text(encoding="utf-8") == "keep"
    assert outside.read_text(encoding="utf-8") == "keep-target"


def test_live_chrome_keeps_the_lock(tmp_path: Path) -> None:
    profile = tmp_path / "profile"
    profile.mkdir()
    (profile / "SingletonLock").symlink_to("host-99")
    with pytest.raises(ProfileInUse) as caught:
        prepare_profile(profile, pids_using_profile=lambda _path: [99])
    assert caught.value.error_type == "profile_in_use"
    assert (profile / "SingletonLock").is_symlink()


def test_profile_inside_a_repo_is_refused(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    with pytest.raises(ConfigError):
        assert_outside_repo(repo / "profile", what="profile")
