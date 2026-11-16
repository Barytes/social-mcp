"""Operator checks against the live site. Not an MCP server."""

from __future__ import annotations

import argparse
import asyncio
import os
import sys

from mcp_browser.config import SiteConfig
from mcp_browser.errors import SiteError
from mcp_browser.session import BrowserSession
from mcp_browser.smoke import doctor, emit

from bili_mcp import flow
from bili_mcp.policy import BiliPolicy


def main() -> None:
    parser = argparse.ArgumentParser(prog="bili-mcp-smoke")
    parser.add_argument("--headed", action="store_true", help="Show the same Chrome profile. Requires $DISPLAY.")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("doctor")
    sub.add_parser("login-status")
    qr = sub.add_parser("login-qr")
    qr.add_argument("--wait", type=float, default=0, help="Seconds to wait for the scan after saving the QR.")
    search = sub.add_parser("search")
    search.add_argument("keyword")
    search.add_argument("--limit", type=int, default=5)
    search.add_argument("--page", type=int, default=1)
    video = sub.add_parser("get-video")
    video.add_argument("bvid")
    args = parser.parse_args()
    if args.headed:
        os.environ["BILI_HEADED"] = "1"
    try:
        config = SiteConfig.load("bili-mcp", "BILI")
    except SiteError as exc:
        raise SystemExit(emit(exc.payload())) from exc
    if args.cmd == "doctor":
        raise SystemExit(emit(doctor(config)))

    session = BrowserSession(config, BiliPolicy())

    async def run() -> dict:
        try:
            if args.cmd == "login-status":
                return await flow.login_status(session)
            if args.cmd == "login-qr":
                payload = await flow.login_qr_start(session)
                payload.pop("_image_path", None)
                if args.wait and payload.get("status") == "qr_ready":
                    waited = await flow.login_qr_wait(session, args.wait)
                    waited["qr_path"] = payload.get("qr_path")
                    return waited
                return payload
            if args.cmd == "search":
                return await flow.search_videos(session, args.keyword, args.limit, args.page)
            return await flow.get_video(session, args.bvid)
        finally:
            await session.shutdown()

    try:
        payload = asyncio.run(run())
    except Exception as exc:
        print(f"smoke crashed: {exc.__class__.__name__}", file=sys.stderr)
        raise SystemExit(1) from exc
    raise SystemExit(emit(payload))
