"""Xiaohongshu document allowlist. /explore with no note id is the recommendation feed."""

from __future__ import annotations

import re

from mcp_browser.policy import ALLOW, DENY, FEED, DocumentPolicy, _host, _path, classify_common, under

_HOSTS = {"www.xiaohongshu.com", "xiaohongshu.com"}
_NOTE = re.compile(r"^/(explore|discovery/item)/[A-Za-z0-9]{6,64}$")


class XhsPolicy(DocumentPolicy):
    def classify(self, url: str) -> str:
        special = classify_common(url)
        if special is not None:
            return special
        host = _host(url)
        path = _path(url)
        if host not in _HOSTS:
            return DENY
        if path in {"/", "/explore", "/discovery"}:
            return FEED
        if under(path, "/website-login") or under(path, "/login"):
            return ALLOW
        if under(path, "/search_result"):
            return ALLOW
        if path == "/user/profile" or under(path, "/user/profile"):
            # /user/profile is both equal and under itself. Keep the explicit form.
            return ALLOW
        if under(path, "/board"):
            return ALLOW
        if _NOTE.match(path):
            return ALLOW
        return DENY

    def is_note(self, url: str) -> bool:
        if self.classify(url) != ALLOW:
            return False
        return _NOTE.match(_path(url)) is not None
