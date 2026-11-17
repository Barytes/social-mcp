"""Operator checks against the live site. Not an MCP server."""

from __future__ import annotations

import argparse
import asyncio
import os
import sys

from mcp_browser.config import SiteConfig
from mcp_browser.errors import SiteError
from mcp_browser.session import BrowserSession
from mcp_browser.smoke import doctor, emit, poll_qr_wait

from xhs_mcp import flow
from xhs_mcp.policy import XhsPolicy


def main() -> None:
    parser = argparse.ArgumentParser(prog="xhs-mcp-smoke")
    parser.add_argument("--headed", action="store_true", help="Show the same Chrome profile. Requires $DISPLAY.")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("doctor")
    sub.add_parser("login-status")
    qr = sub.add_parser("login-qr")
    qr.add_argument("--wait", type=float, default=0, help="Seconds to wait for the scan after saving the QR.")
    search = sub.add_parser("search")
    search.add_argument("keyword")
    search.add_argument("--limit", type=int, default=5)
    note = sub.add_parser("get-note")
    note.add_argument("url")
    args = parser.parse_args()
    if args.headed:
        os.environ["XHS_HEADED"] = "1"
    try:
        config = SiteConfig.load("xhs-mcp", "XHS")
    except SiteError as exc:
        raise SystemExit(emit(exc.payload())) from exc
    if args.cmd == "doctor":
        raise SystemExit(emit(doctor(config)))

    session = BrowserSession(config, XhsPolicy())

    async def run() -> dict:
        try:
            if args.cmd == "login-status":
                return await flow.login_status(session)
            if args.cmd == "login-qr":
                payload = await flow.login_qr_start(session)
                payload.pop("_image_path", None)
                if args.wait and payload.get("status") == "qr_ready":
                    return await poll_qr_wait(flow.login_qr_wait, session, args.wait, payload.get("qr_path"))
                return payload
            if args.cmd == "search":
                return await flow.search_notes(session, args.keyword, args.limit)
            return await flow.get_note(session, args.url)
        finally:
            await session.shutdown()

    try:
        payload = asyncio.run(run())
    except Exception as exc:
        print(f"smoke crashed: {exc.__class__.__name__}", file=sys.stderr)
        raise SystemExit(1) from exc
    raise SystemExit(emit(payload))
