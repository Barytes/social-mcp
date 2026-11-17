"""Read-only click and fill gate.

Search itself does not click the page. Login is allowed only through an explicit
purpose whose visible label is on a short allowlist. Write actions are refused
even if a caller picks an allowed purpose.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

from mcp_browser.errors import ReadOnlyViolation

# Substrings that mark a write or a navigation back to a recommendation home.
_FORBIDDEN_TEXT = (
    "点赞",
    "投币",
    "收藏",
    "评论",
    "关注",
    "取关",
    "充电",
    "三连",
    "发布",
    "发弹幕",
    "弹幕",
    "转发",
    "私信",
    "回复",
    "返回首页",
    "不感兴趣",
    "like",
    "unlike",
    "coin",
    "favorite",
    "favourite",
    "follow",
    "unfollow",
    "comment",
)

_FORBIDDEN_CLASS = re.compile(
    r"(?:^|[^a-z0-9])(like|unlike|coin|favorite|favourite|follow|unfollow|comment|collect|reward)(?:[^a-z0-9]|$)",
    re.IGNORECASE,
)

_MAX_CLICK_TEXT = 24


class ClickPurpose(StrEnum):
    SWITCH_LOGIN_METHOD = "switch_login_method"
    REQUEST_SMS_CODE = "request_sms_code"
    SUBMIT_LOGIN = "submit_login"
    REFRESH_QR = "refresh_qr"
    ACCEPT_LOGIN_TERMS = "accept_login_terms"


class FillPurpose(StrEnum):
    PHONE = "phone"
    SMS_CODE = "sms_code"


_CLICK_TEXT = {
    ClickPurpose.SWITCH_LOGIN_METHOD: ("短信登录", "验证码登录", "手机号登录", "扫码登录", "二维码登录"),
    ClickPurpose.REQUEST_SMS_CODE: ("获取验证码", "发送验证码", "重新获取"),
    ClickPurpose.SUBMIT_LOGIN: ("登录/注册", "登录", "验证"),
    ClickPurpose.REFRESH_QR: ("点击刷新", "刷新二维码", "二维码已失效", "刷新"),
    ClickPurpose.ACCEPT_LOGIN_TERMS: ("我已阅读并同意", "同意"),
}


@dataclass(frozen=True)
class ClickTarget:
    text: str = ""
    aria: str = ""
    title: str = ""
    class_name: str = ""
    elem_id: str = ""
    href: str = ""
    placeholder: str = ""
    input_type: str = ""
    name: str = ""


def _compact(value: str) -> str:
    return re.sub(r"\s+", "", value or "")


def _blob(target: ClickTarget) -> str:
    return " ".join(
        (
            target.text,
            target.aria,
            target.title,
            target.href,
            target.placeholder,
            target.name,
        )
    )


def _reject_write_markers(target: ClickTarget) -> None:
    blob = _blob(target).lower()
    for token in _FORBIDDEN_TEXT:
        if token.lower() in blob:
            raise ReadOnlyViolation(f"refusing to activate a control that matches {token!r}")
    class_id = f"{target.class_name} {target.elem_id}"
    if _FORBIDDEN_CLASS.search(class_id):
        raise ReadOnlyViolation("refusing to activate a control whose class looks like a write action")


def assert_click_allowed(purpose: ClickPurpose, target: ClickTarget) -> None:
    if not isinstance(purpose, ClickPurpose):
        raise ReadOnlyViolation("refusing a click with no allowlisted purpose")
    _reject_write_markers(target)
    if purpose is ClickPurpose.ACCEPT_LOGIN_TERMS and target.input_type == "checkbox":
        return
    text = _compact(target.text) or _compact(target.aria)
    if len(text) > _MAX_CLICK_TEXT:
        raise ReadOnlyViolation("refusing to click a large container")
    # Exact label match. "短信登录" must not satisfy the submit allowlist just because it contains "登录".
    if text not in _CLICK_TEXT[purpose]:
        raise ReadOnlyViolation("control label is not allowlisted for this login step")


def assert_fill_allowed(purpose: FillPurpose, target: ClickTarget) -> None:
    if not isinstance(purpose, FillPurpose):
        raise ReadOnlyViolation("refusing to type with no allowlisted purpose")
    _reject_write_markers(target)
    hint = " ".join((target.placeholder, target.aria, target.name, target.input_type, target.class_name)).lower()
    if target.input_type == "password" or "password" in hint or "密码" in hint:
        raise ReadOnlyViolation("password is entered only by a person in the visible browser window")
    if any(token in hint for token in ("评论", "comment", "弹幕", "danmaku", "私信")):
        raise ReadOnlyViolation("refusing to type into a comment or message field")
    if purpose is FillPurpose.PHONE:
        if not any(token in hint for token in ("手机", "phone", "mobile", "tel")):
            raise ReadOnlyViolation("refusing to type a phone number into an unrelated field")
        return
    if not any(token in hint for token in ("验证码", "code", "sms")):
        raise ReadOnlyViolation("refusing to type an SMS code into an unrelated field")
