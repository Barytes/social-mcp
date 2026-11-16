import logging
from pathlib import Path

from mcp_browser.logging_setup import install_redacting_logs
from mcp_browser.redact import redact


def test_redacts_secrets_and_keeps_ordinary_numbers() -> None:
    raw = (
        "phone 13812345678 code=123456 "
        '{"code": "654321", "password": "hunter2"} '
        "https://www.xiaohongshu.com/explore/abc?xsec_token=secret-token&xsec_source=pc "
        "qrcode_key=abc123 SESSDATA=sess bili_jct=jct "
        "Cookie: SESSDATA=sess; bili_jct=jct\n"
        "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAIwAAACM\n"
        "play 12.3万 year 2026 count 123456"
    )
    cleaned = redact(raw)
    assert "13812345678" not in cleaned
    assert "123456" not in cleaned.split("play")[0]
    assert "654321" not in cleaned
    assert "hunter2" not in cleaned
    assert "secret-token" not in cleaned
    assert "xsec_token=[REDACTED]" in cleaned
    assert "qrcode_key=[REDACTED]" in cleaned
    assert "sess" not in cleaned
    assert "iVBORw0KGgo" not in cleaned
    assert "12.3万" in cleaned
    assert "2026" in cleaned
    assert "count 123456" in cleaned


def test_log_formatter_redacts_before_the_file_is_written(tmp_path: Path) -> None:
    log_file = tmp_path / "app.log"
    install_redacting_logs(log_file)
    logging.getLogger("test.redact").info("login code=112233 phone 13900001111")
    text = log_file.read_text(encoding="utf-8")
    assert "112233" not in text
    assert "13900001111" not in text
    assert "[REDACTED]" in text
    assert "[PHONE]" in text
