"""Structured failures returned to the MCP client. Messages must not contain secrets."""

from __future__ import annotations

from typing import Any


class SiteError(Exception):
    error_type = "internal_error"

    def __init__(
        self,
        message: str,
        *,
        url: str | None = None,
        screenshot_path: str | None = None,
        **extra: Any,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.url = url
        self.screenshot_path = screenshot_path
        self.extra = extra

    def payload(self) -> dict[str, Any]:
        body: dict[str, Any] = {
            "ok": False,
            "error_type": self.error_type,
            "status": self.extra.get("status", self.error_type),
            "message": self.message,
        }
        if self.url:
            body["url"] = self.url
        if self.screenshot_path:
            body["screenshot_path"] = self.screenshot_path
        for key, value in self.extra.items():
            if key == "status" or value is None:
                continue
            body[key] = value
        return body


class ConfigError(SiteError):
    error_type = "config_error"


class InvalidArgument(SiteError):
    error_type = "invalid_argument"


class ProfileInUse(SiteError):
    error_type = "profile_in_use"


class BrowserFailed(SiteError):
    error_type = "browser_failed"


class ReadOnlyViolation(SiteError):
    error_type = "read_only_violation"


class FeedBlocked(SiteError):
    error_type = "feed_blocked"


class NavigationDenied(SiteError):
    error_type = "navigation_denied"


class PageLoadFailed(SiteError):
    error_type = "page_load_failed"


class PageNotUnderstood(SiteError):
    error_type = "page_not_understood"


class NeedsHumanVerification(SiteError):
    error_type = "needs_human_verification"


class LoginUiNotFound(SiteError):
    error_type = "login_ui_not_found"


class QrExpired(SiteError):
    error_type = "qr_expired"


class SmsFormNotReady(SiteError):
    error_type = "sms_form_not_ready"


class SmsRejected(SiteError):
    error_type = "sms_rejected"


class NotLoggedIn(SiteError):
    """The check itself succeeded and the session is not authenticated."""

    error_type = "not_authenticated"

    def payload(self) -> dict[str, Any]:
        body = super().payload()
        # A completed check that found no session is a result, not a crash.
        body["ok"] = True
        body["logged_in"] = False
        body["status"] = "logged_out"
        body.setdefault("reason", self.extra.get("reason", "not_authenticated"))
        return body
