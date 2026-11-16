"""stdio entrypoint: `uv run xhs-mcp`."""

from __future__ import annotations

import json
import sys

import anyio

from mcp_browser.config import SiteConfig
from mcp_browser.errors import SiteError
from mcp_browser.logging_setup import install_redacting_logs
from mcp_browser.runtime import serve
from mcp_browser.session import BrowserSession

from xhs_mcp.policy import XhsPolicy
from xhs_mcp.server import build_server


def main() -> None:
    try:
        config = SiteConfig.load("xhs-mcp", "XHS")
    except SiteError as exc:
        print(json.dumps(exc.payload(), ensure_ascii=False), file=sys.stderr)
        raise SystemExit(1) from exc
    session = BrowserSession(config, XhsPolicy())
    server = build_server(session)
    install_redacting_logs(config.log_file)
    anyio.run(serve, server, session)
