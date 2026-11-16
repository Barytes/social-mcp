"""Document-navigation policy. Feeds are rejected; everything else is denied unless listed."""

from __future__ import annotations

from urllib.parse import urlsplit

FEED = "feed"
ALLOW = "allow"
DENY = "deny"


def _host(url: str) -> str:
    return (urlsplit(url).hostname or "").lower()


def _path(url: str) -> str:
    path = urlsplit(url).path or "/"
    if path != "/":
        path = path.rstrip("/") or "/"
    return path


def under(path: str, prefix: str) -> bool:
    return path == prefix or path.startswith(prefix + "/")


def classify_common(url: str) -> str | None:
    """about:blank is the escape hatch after a blocked feed. Other schemes are denied."""
    if not url or url.startswith("about:"):
        return ALLOW
    parts = urlsplit(url)
    if parts.scheme not in {"http", "https"} or not parts.hostname:
        return DENY
    return None


class DocumentPolicy:
    def classify(self, url: str) -> str:
        raise NotImplementedError

    def is_feed(self, url: str) -> bool:
        return self.classify(url) == FEED
