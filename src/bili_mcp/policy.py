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


class BiliPolicy(DocumentPolicy):
    def classify(self, url: str) -> str:
        special = classify_common(url)
        if special is not None:
            return special
        host = _host(url)
        path = _path(url)
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
