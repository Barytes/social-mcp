"""Parsers for the logged-in favorites captures. No live site and no tokens."""

import json
from pathlib import Path

from bili_mcp.parse import parse_bili_favorite_folders, parse_bili_folder_videos, parse_bili_video, parse_bili_watch_later
from mcp_browser.list_cache import contains_query, save_cache
from xhs_mcp.parse import parse_xhs_board_tab, parse_xhs_favorite_notes
from xhs_mcp.policy import XhsPolicy

FIXTURES = Path(__file__).parent / "fixtures"


def read(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_bili_sidebar_folders_keep_ids_and_kinds() -> None:
    folders = parse_bili_favorite_folders(read("bili_favlist.html"))
    by_name = {item["name"]: item for item in folders}
    assert by_name["默认收藏夹"]["kind"] == "created"
    assert by_name["默认收藏夹"]["count"] == 228
    assert by_name["默认收藏夹"]["id"] is None
    assert by_name["宝宝专看"] == {"id": "3953102056", "name": "宝宝专看", "count": 30, "kind": "created", "invalid": False}
    assert by_name["Unhooked 不被困住"]["kind"] == "followed"
    assert by_name["Unhooked 不被困住"]["id"] is None
    assert by_name["该合集已失效"]["invalid"] is True
    assert by_name["话题收藏"]["kind"] == "other"
    assert "新建收藏夹" not in by_name
    active = parse_bili_favorite_folders(read("bili_favlist.html"), "https://space.bilibili.com/19098356/favlist?fid=123&ftype=create")
    assert next(item for item in active if item["name"] == "默认收藏夹")["id"] == "123"


def test_bili_folder_cards_include_invalid_videos() -> None:
    videos = parse_bili_folder_videos(read("bili_favlist.html"))
    first = videos[0]
    assert first["bvid"] == "BV1EE716zEnT"
    assert first["up_name"] == "AliAbdaal"
    assert first["saved_at"] == "11月1日"
    assert first["play_count"] == "6250"
    assert first["duration"] == "13:40"
    assert first["url"] == "https://www.bilibili.com/video/BV1EE716zEnT"
    invalid = next(item for item in videos if item["invalid"])
    assert invalid["title"] == "已失效视频"
    assert invalid["bvid"].startswith("BV")


def test_watch_later_panel_uses_data_key_and_skips_recommendations() -> None:
    parsed = parse_bili_watch_later(read("bili_watchlater.html"))
    assert parsed["current_index"] == 1
    assert parsed["total"] == 489
    assert parsed["items"][0]["bvid"] == "BV138WN6hEvK"
    assert parsed["items"][0]["position"] == 1
    assert parsed["items"][0]["play_count"] == "531播放"
    assert parsed["items"][0]["up_name"] is None
    assert all(item["url"].endswith(item["bvid"]) for item in parsed["items"])
    titles = " ".join(item["title"] for item in parsed["items"])
    assert "故事环" not in titles
    assert "删除" not in titles


def test_player_fields_from_the_watch_later_capture() -> None:
    parsed = parse_bili_video(read("bili_player.html"), "BV138WN6hEvK")
    assert parsed["title"].startswith("如何解锁你的创作天赋")
    assert parsed["up_name"] == "静里见明"
    assert parsed["up_space_url"] == "https://space.bilibili.com/82138737"
    assert parsed["publish_date"] == "2026-11-10 02:03:55"
    assert parsed["duration"] == "06:13"
    assert parsed["stats"]["play_count"] == "531"
    assert parsed["stats"]["like_count"] == "25"
    assert parsed["stats"]["favorite_count"] == "61"
    assert "中英字幕" in parsed["tags"]
    assert parsed["parts"] == []
    assert parsed["url"] == "https://www.bilibili.com/video/BV138WN6hEvK"
    multi = parse_bili_video('<h1 class="video-title">分P</h1><div class="video-pod__item">P1 上</div><div class="video-pod__item">P2 下</div>', "BV1bbbbbbbbb")
    assert multi["parts"] == ["P1 上", "P2 下"]


def test_xhs_favorite_notes_keep_a_scrubbed_token() -> None:
    html = read("xhs_fav.html")
    assert "AB2L" not in html
    notes = parse_xhs_favorite_notes(html)
    assert notes
    first = notes[0]
    assert first["note_id"] == "6916c54b000000000703b6f3"
    assert first["title"].startswith("沉浸式宅家美食")
    assert first["author"] == "杨大懿"
    assert first["like_count"] == "2738"
    assert "xsec_token=fixture-token" in first["url"]
    assert "/user/profile/" in first["url"]
    assert XhsPolicy().is_note(first["url"]) is True
    boards = parse_xhs_board_tab(html)
    assert boards["album_count"] == 1
    assert boards["boards"] == []


def test_list_search_is_a_casefold_substring() -> None:
    assert contains_query("羊肉", "沉浸式宅家美食.用电饭煲做一锅《羊肉抓饭》")
    assert contains_query("ali", "AliAbdaal")
    assert contains_query("中英", "如何解锁你的创作天赋？【中英字幕】")
    assert not contains_query("不存在的词", "羊肉抓饭")


def test_list_cache_drops_tokens(tmp_path: Path) -> None:
    saved = save_cache(
        tmp_path / "list-cache" / "xhs-favorites.json",
        [
            {
                "title": "羊肉抓饭",
                "note_id": "6916c54b000000000703b6f3",
                "url": "https://www.xiaohongshu.com/explore/6916c54b000000000703b6f3?xsec_token=secret-value&xsec_source=pc_user",
                "author_url": "https://www.xiaohongshu.com/user/profile/abc?xsec_token=other-secret",
                "xsec_token": "secret-value",
                "cookie": "SESSDATA=nope",
            }
        ],
    )
    blob = json.dumps(saved, ensure_ascii=False)
    assert "secret" not in blob
    assert "SESSDATA" not in blob
    assert saved["items"][0]["note_id"] == "6916c54b000000000703b6f3"
    assert "xsec_source=pc_user" in saved["items"][0]["url"]
    assert saved["fetched_at"]
