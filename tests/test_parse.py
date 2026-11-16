from pathlib import Path

from bili_mcp.parse import (
    bili_has_more,
    classify_bili_search,
    parse_bili_identity,
    parse_bili_search,
    parse_bili_video,
)
from bili_mcp.urls import bili_search_url
from xhs_mcp.parse import classify_xhs_search, parse_xhs_identity, parse_xhs_note, parse_xhs_search

FIXTURES = Path(__file__).parent / "fixtures"


def read(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_bili_search_url_encodes_keyword() -> None:
    assert bili_search_url("测试", 2) == "https://search.bilibili.com/all?keyword=%E6%B5%8B%E8%AF%95&page=2"


def test_bili_search_fixture() -> None:
    videos, parser_id = parse_bili_search(read("bili_search.html"))
    assert parser_id == "bili-video-card"
    assert [item["bvid"] for item in videos] == ["BV1aaaaaaaaa", "BV2bbbbbbbbb"]
    first, second = videos
    assert first["title"] == "示例标题甲"
    assert first["url"] == "https://www.bilibili.com/video/BV1aaaaaaaaa"
    assert first["up_name"] == "示例UP"
    assert first["play_count"] == "12.3万"
    assert first["duration"] == "03:21"
    assert first["publish_date"] == "11月12日"
    assert first["cover_url"].startswith("https://i0.hdslb.com/bfs/archive/cover-a.jpg")
    assert second["up_name"] is None
    assert second["publish_date"] == "11月2日"
    assert second["play_count"] == "88"
    assert bili_has_more(read("bili_search.html")) is True


def test_bili_has_more_false_when_next_disabled() -> None:
    html = '<button class="vui_button vui_button--disabled vui_pagenation--btn-side">下一页</button>'
    assert bili_has_more(html) is False


def test_bili_empty_is_not_a_parse_failure() -> None:
    outcome = classify_bili_search(read("bili_search_empty.html"), "https://search.bilibili.com/all?keyword=none")
    assert outcome["kind"] == "no_results"


def test_bili_unknown_page_is_not_empty() -> None:
    outcome = classify_bili_search(read("not_understood.html"), "https://search.bilibili.com/all?keyword=x")
    assert outcome["kind"] == "not_understood"


def test_bili_passport_url_is_logged_out_even_with_cards() -> None:
    outcome = classify_bili_search(read("bili_search.html"), "https://passport.bilibili.com/login")
    assert outcome["kind"] == "logged_out"


def test_bili_video_fixture() -> None:
    parsed = parse_bili_video(read("bili_video.html"), "BV1aaaaaaaaa")
    assert parsed is not None
    assert parsed["title"] == "示例视频标题"
    assert parsed["up_name"] == "示例UP"
    assert "简介" in parsed["description"]
    assert parsed["tags"] == ["话题甲", "知识", "旅行"]
    assert parsed["publish_date"] == "2026-11-12 10:00"


def test_bili_identity_states() -> None:
    logged_out = parse_bili_identity(read("bili_logged_out.html"), "https://search.bilibili.com/all?keyword=x")
    assert logged_out["logged_in"] is False
    home = parse_bili_identity(read("bili_account_home.html"), "https://account.bilibili.com/account/home")
    assert home == {"logged_in": True, "nickname": "示例昵称", "uid": "12345678"}
    passport = parse_bili_identity(read("bili_account_home.html"), "https://passport.bilibili.com/login")
    assert passport["logged_in"] is False


def test_xhs_search_keeps_token_and_ignores_feed_link() -> None:
    notes, parser_id = parse_xhs_search(read("xhs_search.html"))
    assert parser_id == "note-item"
    assert [item["note_id"] for item in notes] == ["64f0abc123456789abcd1234", "abc123def4567890"]
    video, image = notes
    assert video["type"] == "video"
    assert video["title"] == "笔记标题甲"
    assert video["author"] == "作者甲"
    assert video["like_count"] == "1.2万"
    assert video["cover_url"] == "https://example.com/cover-a.jpg"
    assert "xsec_token=token-value" in video["url"]
    assert video["url"].startswith("https://www.xiaohongshu.com/explore/64f0abc123456789abcd1234?")
    assert image["type"] == "image"
    assert "xsec_token=other-token" in image["url"]
    assert all("homefeed" not in item["url"] for item in notes)


def test_xhs_login_wall_is_not_empty_results() -> None:
    html = read("xhs_login_wall.html")
    outcome = classify_xhs_search(html, "https://www.xiaohongshu.com/search_result?keyword=test", "")
    assert outcome["kind"] == "logged_out"
    assert parse_xhs_search(html)[0] == []


def test_xhs_risk_page_is_not_search_results() -> None:
    html = read("xhs_risk.html")
    text = "安全限制 当前网络存在风险，请切换可靠网络后重试 300012 返回首页"
    outcome = classify_xhs_search(
        html,
        "http://www.xiaohongshu.com/website-login/error?error_code=300012",
        text,
    )
    assert outcome["kind"] == "needs_human_verification"


def test_xhs_note_and_identity_fixtures() -> None:
    url = "https://www.xiaohongshu.com/explore/64f0abc123456789abcd1234?xsec_token=token-value&xsec_source=pc_search"
    parsed = parse_xhs_note(read("xhs_note.html"), url)
    assert parsed is not None
    assert parsed["title"] == "笔记详情标题"
    assert "正文" in parsed["description"]
    assert parsed["tags"] == ["标签甲", "标签乙"]
    assert parsed["url"] == url
    assert parsed["note_id"] == "64f0abc123456789abcd1234"
    wall = read("xhs_login_wall.html")
    identity = parse_xhs_identity(wall, "https://www.xiaohongshu.com/login", "登录后查看搜索结果 扫码 手机号登录")
    assert identity["logged_in"] is False
