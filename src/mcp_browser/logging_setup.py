"""Send logs to stderr and a file. Never stdout: stdout is the MCP protocol."""

from __future__ import annotations

import logging
import sys
from pathlib import Path

from mcp_browser.redact import RedactingFormatter


def install_redacting_logs(log_file: Path, level: int = logging.INFO) -> None:
    log_file.parent.mkdir(parents=True, exist_ok=True)
    formatter = RedactingFormatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(level)
    stderr = logging.StreamHandler(sys.stderr)
    stderr.setFormatter(formatter)
    root.addHandler(stderr)
    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)
    logging.getLogger("playwright").setLevel(logging.WARNING)
    logging.getLogger("asyncio").setLevel(logging.WARNING)
