"""On-disk copies of list rows so a later search can skip the crawl.

The file lives under the site data dir, next to logs, not in the browser profile.
Cookies and URL tokens are removed before anything is written.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit, urlunsplit

_DROPPED_KEYS = {"xsec_token", "token", "cookie", "cookies", "sessdata", "bili_jct", "password"}
_DROPPED_QUERY = {"xsec_token", "token", "cookie", "sessdata"}


def cache_file(data_dir: Path, name: str) -> Path:
    return data_dir / "list-cache" / f"{name}.json"


def scrub(value):
    if isinstance(value, dict):
        cleaned = {}
        for key, item in value.items():
            if str(key).lower() in _DROPPED_KEYS:
                continue
            cleaned[key] = scrub(item)
        if "url" in cleaned and isinstance(cleaned["url"], str):
            cleaned["url"] = _scrub_url(cleaned["url"])
        if "author_url" in cleaned and isinstance(cleaned["author_url"], str):
            cleaned["author_url"] = _scrub_url(cleaned["author_url"])
        return cleaned
    if isinstance(value, list):
        return [scrub(item) for item in value]
    return value


def _scrub_url(url: str) -> str:
    parts = urlsplit(url)
    query = [(key, val) for key, val in parse_qsl(parts.query, keep_blank_values=True) if key.lower() not in _DROPPED_QUERY]
    from urllib.parse import urlencode

    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), ""))


def load_cache(path: Path) -> dict | None:
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict) or not isinstance(data.get("items"), list):
        return None
    return data


def save_cache(path: Path, items: list[dict]) -> dict:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "fetched_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "items": scrub(items),
    }
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return payload


def contains_query(query: str, *fields: str | None) -> bool:
    needle = (query or "").casefold()
    if not needle:
        return False
    return any(needle in (field or "").casefold() for field in fields)
