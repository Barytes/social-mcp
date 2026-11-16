from bili_mcp.server import build_server as build_bili
from xhs_mcp.server import build_server as build_xhs


def _names(server) -> set[str]:
    return {tool.name for tool in server._tool_manager.list_tools()}


def test_registered_tools_are_read_paths_only() -> None:
    bili = _names(build_bili(object()))
    xhs = _names(build_xhs(object()))
    assert {"login_status", "login_qr_start", "login_qr_wait", "login_sms_request", "login_sms_submit", "search", "get_video"} <= bili
    assert {"login_status", "login_qr_start", "search", "get_note"} <= xhs
    assert "list_favorites" not in bili
    assert "list_watch_later" not in bili
    assert "list_favorites" not in xhs
