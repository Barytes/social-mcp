from mcp_browser.policy import ALLOW, DENY, FEED
from bili_mcp.policy import BiliPolicy
from bili_mcp.urls import WATCH_LATER_URL, bili_favlist_url
from xhs_mcp.policy import XhsPolicy
from xhs_mcp.urls import xhs_favorites_url, xhs_note_url


def test_bilibili_feed_and_allowed_pages() -> None:
    policy = BiliPolicy()
    assert policy.classify("https://www.bilibili.com/") == FEED
    assert policy.classify("https://www.bilibili.com/?spm_id_from=333") == FEED
    assert policy.classify("https://bilibili.com/") == FEED
    assert policy.classify("https://www.bilibili.com/v/popular/all") == FEED
    assert policy.classify("https://search.bilibili.com/zh-Hans/all?keyword=test&page=2&o=30") == ALLOW
    assert policy.classify("https://www.bilibili.com/video/BV1HJWu69EAY/") == ALLOW
    assert policy.classify("https://passport.bilibili.com/login?site=OVERSEAS") == ALLOW
    assert policy.classify("https://passport.bilibili.com/pc/passport/login") == ALLOW
    assert policy.classify("https://account.bilibili.com/account/home") == ALLOW
    assert policy.classify("https://space.bilibili.com/123/favlist") == ALLOW
    assert policy.classify(bili_favlist_url("19098356", "3953102056")) == ALLOW
    assert policy.classify("https://space.bilibili.com/") == ALLOW
    assert policy.classify("https://space.bilibili.com/19098356") == ALLOW
    assert policy.classify("https://space.bilibili.com/19098356/dynamic") == DENY
    assert policy.classify("https://www.bilibili.com/watchlater") == DENY
    assert policy.classify("https://www.bilibili.com/watchlater/") == DENY
    assert policy.classify(WATCH_LATER_URL) == ALLOW
    assert policy.classify(WATCH_LATER_URL + "?oid=1&bvid=BV1aaaaaaaaa") == ALLOW
    assert policy.classify("https://passport.biligame.com/x/passport-login/web/crossDomain?x=1") == ALLOW
    assert policy.classify("https://passport.bigfunapp.cn/x/passport-login/web/crossDomain") == ALLOW
    assert policy.classify("https://passport.bilibili.cn/x/passport-login/web/crossDomain") == ALLOW
    assert policy.classify("https://passport.biligame.com/x/passport-login/web/other") == DENY
    assert policy.classify("https://passport.biligame.com/") == DENY
    assert policy.classify("https://t.bilibili.com/") == DENY
    assert policy.classify("about:blank") == ALLOW


def test_xiaohongshu_feed_note_and_risk_page() -> None:
    policy = XhsPolicy()
    assert policy.classify("https://www.xiaohongshu.com/") == FEED
    assert policy.classify("https://www.xiaohongshu.com/explore") == FEED
    assert policy.classify("https://www.xiaohongshu.com/explore/") == FEED
    assert policy.classify("https://www.xiaohongshu.com/explore?channel_id=homefeed_recommend") == FEED
    note = "https://www.xiaohongshu.com/explore/64f0abc123456789abcd1234?xsec_token=abc&xsec_source=pc_search"
    assert policy.classify(note) == ALLOW
    assert policy.is_note(note) is True
    assert policy.is_note("https://www.xiaohongshu.com/explore?channel_id=homefeed_recommend") is False
    assert policy.classify("https://www.xiaohongshu.com/search_result?keyword=test") == ALLOW
    assert policy.classify("https://www.xiaohongshu.com/search_result/?keyword=test") == ALLOW
    assert policy.classify("https://www.xiaohongshu.com/login") == ALLOW
    assert policy.classify("http://www.xiaohongshu.com/website-login/error?error_code=300012") == ALLOW
    assert policy.classify("https://edith.xiaohongshu.com/api/sns/web/v1/search/notes") == DENY
    assert policy.classify("https://www.xiaohongshu.com/user/profile/abc123456") == ALLOW
    fav_note = "https://www.xiaohongshu.com/user/profile/63313a0b00000000230241c0/6916c54b000000000703b6f3?xsec_token=fixture-token"
    assert policy.classify(fav_note) == ALLOW
    assert policy.is_note(fav_note) is True
    assert policy.is_note(xhs_favorites_url("63313a0b00000000230241c0")) is False
    assert policy.classify("https://www.xiaohongshu.com/board/abc1234567") == ALLOW
    assert policy.is_note(xhs_note_url("6916c54b000000000703b6f3", "fixture-token")) is True
