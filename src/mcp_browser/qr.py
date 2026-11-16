"""Shared QR-wait results.

`login_qr_wait` may be called again while the same code is on screen. It must not
open the login page a second time, because that replaces the code the person is scanning.
"""

from __future__ import annotations

from mcp_browser.errors import QrExpired

EXPIRED_PHRASES = ("二维码已过期", "二维码已失效", "二维码失效", "二维码过期")


def text_says_expired(text: str) -> bool:
    return any(phrase in (text or "") for phrase in EXPIRED_PHRASES)


def pending_payload(url: str | None) -> dict:
    return {
        "ok": False,
        "error_type": "qr_pending",
        "status": "qr_pending",
        "qr_still_valid": True,
        "message": (
            "二维码还在，这次等待结束前没有扫完。再次调用 login_qr_wait 即可，"
            "不要调用 login_qr_start，否则会换成新的二维码。"
        ),
        "url": url,
    }


def not_ready_payload(url: str | None) -> dict:
    return {
        "ok": False,
        "error_type": "qr_not_ready",
        "status": "qr_not_ready",
        "qr_still_valid": False,
        "message": "当前页面没有可等待的二维码。请先调用 login_qr_start。",
        "url": url,
    }


def expired_error(url: str | None) -> QrExpired:
    return QrExpired(
        "二维码已过期。请重新调用 login_qr_start 获取新二维码。",
        url=url,
        qr_still_valid=False,
    )
