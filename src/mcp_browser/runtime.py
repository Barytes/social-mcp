"""Run a stdio MCP server and close Chrome on exit, including SIGTERM."""

from __future__ import annotations

import logging
import signal
from typing import Any

import anyio

log = logging.getLogger(__name__)


async def _cancel_on_signal(cancel_scope: anyio.CancelScope) -> None:
    with anyio.open_signal_receiver(signal.SIGTERM, signal.SIGINT) as signals:
        async for _signum in signals:
            log.info("received signal, shutting down")
            cancel_scope.cancel()
            return


async def serve(server: Any, session: Any) -> None:
    try:
        async with anyio.create_task_group() as task_group:
            task_group.start_soon(_cancel_on_signal, task_group.cancel_scope)
            await server.run_stdio_async()
            task_group.cancel_scope.cancel()
    finally:
        log.info("closing browser")
        await session.shutdown()
