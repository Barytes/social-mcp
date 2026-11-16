"""Redact secrets from log lines. Tool results keep xsec_token inside note URLs."""

from __future__ import annotations

import logging
import re

_PHONE = re.compile(r"(?<!\d)(?:\+?86[-\s]?)?1[3-9]\d{9}(?!\d)")
_CODE_FIELD = re.compile(
    r"(?i)((?:\"|')?(?:code|sms|sms_code|verify_code|验证码)(?:\"|')?\s*[:=：]\s*(?:\"|')?)(\d{4,8})"
)
_SECRET_FIELD = re.compile(
    r"(?i)((?:\"|')?(?:password|passwd|pwd|密码|token|access_token|refresh_token|sessdata|bili_jct)"
    r"(?:\"|')?\s*[:=：]\s*(?:\"|')?)(\S+)"
)
_QUERY_SECRET = re.compile(
    r"(?i)((?:xsec_token|qrcode_key|sessdata|bili_jct|dedeuserid|access_token|refresh_token)=)[^&\s\"']+"
)
_COOKIE = re.compile(r"(?i)(cookie\s*[:=]\s*)[^\n]+")
_DATA_IMAGE = re.compile(r"data:image/[a-zA-Z0-9.+-]+;base64,[A-Za-z0-9+/=]{16,}")


def redact(text: str) -> str:
    """Mask phones, SMS codes, cookies, and session tokens. Leave ordinary numbers."""
    if not text:
        return text
    text = _DATA_IMAGE.sub("data:image/[REDACTED]", text)
    text = _COOKIE.sub(r"\1[REDACTED]", text)
    text = _QUERY_SECRET.sub(r"\1[REDACTED]", text)
    text = _SECRET_FIELD.sub(r"\1[REDACTED]", text)
    text = _CODE_FIELD.sub(r"\1[REDACTED]", text)
    text = _PHONE.sub("[PHONE]", text)
    return text


class RedactingFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return redact(super().format(record))
