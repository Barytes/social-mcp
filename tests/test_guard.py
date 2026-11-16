import asyncio

import pytest

from mcp_browser.actions import safe_click, safe_fill
from mcp_browser.errors import ReadOnlyViolation
from mcp_browser.guard import ClickPurpose, ClickTarget, FillPurpose, assert_click_allowed, assert_fill_allowed


def target(**kwargs) -> ClickTarget:
    return ClickTarget(**kwargs)


@pytest.mark.parametrize(
    "text",
    ["点赞", "投币", "收藏", "取消收藏", "评论", "关注", "已关注", "返回首页", "发布"],
)
def test_write_labels_are_refused(text: str) -> None:
    with pytest.raises(ReadOnlyViolation):
        assert_click_allowed(ClickPurpose.SUBMIT_LOGIN, target(text=text))


def test_like_count_control_is_refused_by_class() -> None:
    with pytest.raises(ReadOnlyViolation) as caught:
        assert_click_allowed(ClickPurpose.SUBMIT_LOGIN, target(text="1.2万", class_name="like-wrapper"))
    assert caught.value.error_type == "read_only_violation"


def test_sms_tab_is_not_a_submit() -> None:
    assert_click_allowed(ClickPurpose.SWITCH_LOGIN_METHOD, target(text="短信登录"))
    with pytest.raises(ReadOnlyViolation):
        assert_click_allowed(ClickPurpose.SUBMIT_LOGIN, target(text="短信登录"))


@pytest.mark.parametrize("label", ["登录", "登录/注册"])
def test_login_submit_labels(label: str) -> None:
    assert_click_allowed(ClickPurpose.SUBMIT_LOGIN, target(text=label))


def test_request_code_and_terms() -> None:
    assert_click_allowed(ClickPurpose.REQUEST_SMS_CODE, target(text="获取验证码"))
    assert_click_allowed(ClickPurpose.ACCEPT_LOGIN_TERMS, target(input_type="checkbox"))
    with pytest.raises(ReadOnlyViolation):
        assert_click_allowed(ClickPurpose.REQUEST_SMS_CODE, target(text="点赞"))


def test_large_container_is_refused() -> None:
    with pytest.raises(ReadOnlyViolation):
        assert_click_allowed(ClickPurpose.SUBMIT_LOGIN, target(text="登录" * 20))


def test_fill_rules() -> None:
    assert_fill_allowed(FillPurpose.PHONE, target(placeholder="请输入手机号", input_type="text"))
    assert_fill_allowed(FillPurpose.SMS_CODE, target(placeholder="输入验证码", input_type="number"))
    with pytest.raises(ReadOnlyViolation):
        assert_fill_allowed(FillPurpose.PHONE, target(placeholder="请输入密码", input_type="password"))
    with pytest.raises(ReadOnlyViolation):
        assert_fill_allowed(FillPurpose.SMS_CODE, target(placeholder="发一条评论", input_type="text"))
    with pytest.raises(ReadOnlyViolation):
        assert_fill_allowed(FillPurpose.PHONE, target(placeholder="搜索", input_type="text"))


class _Locator:
    def __init__(self, text: str, **attrs: str) -> None:
        self.text = text
        self.attrs = attrs
        self.clicked = False
        self.filled = None

    async def inner_text(self) -> str:
        return self.text

    async def get_attribute(self, name: str) -> str | None:
        return self.attrs.get(name)

    async def click(self, timeout: int | None = None) -> None:
        self.clicked = True

    async def fill(self, value: str, timeout: int | None = None) -> None:
        self.filled = value


def test_safe_click_does_not_press_like() -> None:
    async def inner() -> None:
        like = _Locator("点赞", **{"class": "video-like"})
        with pytest.raises(ReadOnlyViolation):
            await safe_click(like, ClickPurpose.SUBMIT_LOGIN)
        assert like.clicked is False
        sms = _Locator("短信登录")
        await safe_click(sms, ClickPurpose.SWITCH_LOGIN_METHOD)
        assert sms.clicked is True

    asyncio.run(inner())


def test_safe_fill_accepts_phone_only_in_phone_field() -> None:
    async def inner() -> None:
        phone = _Locator("", placeholder="输入手机号", type="text")
        await safe_fill(phone, "13800138000", FillPurpose.PHONE)
        assert phone.filled == "13800138000"
        secret = _Locator("", placeholder="请输入密码", type="password")
        with pytest.raises(ReadOnlyViolation):
            await safe_fill(secret, "hunter2", FillPurpose.PHONE)
        assert secret.filled is None

    asyncio.run(inner())
