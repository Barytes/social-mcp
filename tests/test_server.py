from bili_mcp.server import build_server as build_bili
from xhs_mcp.server import build_server as build_xhs


def _names(server) -> set[str]:
    return {tool.name for tool in server._tool_manager.list_tools()}


def test_registered_tools_are_read_paths_only() -> None:
    bili = _names(build_bili(object()))
    xhs = _names(build_xhs(object()))
    assert {"login_status", "search", "get_video", "list_favorite_folders", "get_favorite_folder", "list_watch_later", "search_favorites", "search_watch_later"} <= bili
    assert {"login_status", "search", "get_note", "list_favorites", "list_favorite_boards", "get_favorite_board", "search_favorites"} <= xhs
