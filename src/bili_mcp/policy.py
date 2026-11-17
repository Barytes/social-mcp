"""Bilibili document allowlist. The site home page is the recommendation feed."""

from __future__ import annotations

from mcp_browser.policy import ALLOW, DENY, FEED, DocumentPolicy, _host, _path, classify_common, under

_WWW = {"www.bilibili.com", "bilibili.com", "m.bilibili.com"}
_WWW_PREFIXES = (
    "/video",
    "/zh-Hans/video",
    "/zh-Hant/video",
    "/account",
    "/watchlater",
    "/list/watchlater",
    "/medialist/play/watchlater",
    "/blackboard",
)

# After the QR is confirmed, the official web login sets the session by loading
# this one document on a sibling passport host, then sends the browser to the
# home feed. Only this path is allowed. The home feed stays blocked.
SSO_HOSTS = frozenset({"passport.biligame.com", "passport.bigfunapp.cn", "passport.bilibili.cn"})
SSO_PATH = "/x/passport-login/web/crossDomain"


class BiliPolicy(DocumentPolicy):
    def classify(self, url: str) -> str:
        special = classify_common(url)
        if special is not None:
            return special
        host = _host(url)
        path = _path(url)
        if host in SSO_HOSTS and path == SSO_PATH:
            return ALLOW
        if host == "search.bilibili.com":
            return ALLOW
        if host in {"passport.bilibili.com", "account.bilibili.com", "space.bilibili.com"}:
            return ALLOW
        if host in _WWW:
            if path in {"/", "/index.html"}:
                return FEED
            if under(path, "/v/popular"):
                return FEED
            if any(under(path, prefix) for prefix in _WWW_PREFIXES):
                return ALLOW
            return DENY
        return DENY
