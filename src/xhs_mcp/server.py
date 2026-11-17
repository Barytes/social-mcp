"""Read-only Xiaohongshu MCP server."""

from __future__ import annotations

from mcp.server.mcpserver import Image, MCPServer
from mcp.types import ToolAnnotations

from mcp_browser.smoke import dumps

from xhs_mcp import flow, lists

READ = ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=True)
LOGIN = ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=False, open_world_hint=True)

INSTRUCTIONS = (
    "只读访问当前这一个小红书账号：登录状态、扫码或短信登录、搜索、笔记详情、自己的收藏。"
    "不要点赞、收藏、评论、关注，也不要打开发现页或首页推荐（/explore 不带笔记 id）。"
    "新的网页登录会把同一账号的其他网页会话踢下线。"
    "出现风控或验证页时停止，不要尝试绕过。无头模式在部分网络上会直接进入安全限制页，这时改用有界面模式。"
    "收藏从自己的主页 tab=fav 读取，不点收藏按钮。"
)


def build_server(session) -> MCPServer:
    server = MCPServer(
        "xiaohongshu",
        instructions=INSTRUCTIONS,
        log_level="WARNING",
    )

    @server.tool(annotations=READ, structured_output=False)
    async def login_status() -> str:
        """查看当前持久配置里的小红书是否已登录。

        未登录和被新的网页登录踢下线都会返回 logged_in=false，reason 为 session_absent_or_replaced。
        风控页返回 needs_human_verification，而不是未登录。
        """
        return dumps(await flow.login_status(session))

    @server.tool(annotations=LOGIN, structured_output=False)
    async def login_qr_start() -> str | list[str | Image]:
        """在官方登录页截取二维码，返回 PNG 绝对路径，并附上图片内容。

        可用小红书或微信扫码。新的网页登录会使这个账号的其他网页会话失效。
        """
        payload = await flow.login_qr_start(session)
        image = payload.pop("_image_path", None)
        text = dumps(payload)
        if image and payload.get("ok") and payload.get("status") == "qr_ready":
            return [text, Image(path=image)]
        return text

    @server.tool(annotations=READ, structured_output=False)
    async def login_qr_wait(timeout_s: float = 90) -> str:
        """在当前登录页上等扫码完成、过期、短信二次验证，或出现需要人处理的验证。

        timeout_s 为 1–180。同一张二维码在过期前可以反复调用。手机已扫但还没确认时，这次调用会继续等到超时，而不是马上返回。
        新设备弹出「短信验证码验证」时返回 sms_verification_required 和页面上已经打码的手机号。把验证码交给 login_sms_submit，不要自动重发。
        """
        return dumps(await flow.login_qr_wait(session, timeout_s))

    @server.tool(annotations=LOGIN, structured_output=False)
    async def login_sms_request(phone: str) -> str:
        """在官方登录页请求短信验证码。phone 不会写入日志。不提供密码参数。"""
        return dumps(await flow.login_sms_request(session, phone))

    @server.tool(annotations=LOGIN, structured_output=False)
    async def login_sms_submit(code: str) -> str:
        """提交短信验证码。code 不会写入日志或回显。

        扫码之后的新设备弹窗用页面上的「验证」按钮。不会点击「重新发送」。
        验证成功后网站会跳到首页推荐，这个跳转会被拦住，然后改到非推荐页确认登录。
        """
        return dumps(await flow.login_sms_submit(session, code))

    @server.tool(annotations=READ, structured_output=False)
    async def search(keyword: str, limit: int = 10) -> str:
        """打开小红书搜索页并读取笔记卡片。不打开发现页推荐。

        未登录时搜索页会要求登录，这时返回 logged_out，而不是空列表。
        每条结果含 title、note_id、url（保留页面链接里的 xsec_token）、author、like_count、cover_url、type。
        """
        return dumps(await flow.search_notes(session, keyword, limit))

    @server.tool(annotations=READ, structured_output=False)
    async def get_note(url: str = "", note_id: str = "", xsec_token: str = "") -> str:
        """打开一条笔记。可以传列表里的 url，或 note_id 加页面上的 xsec_token。

        读取标题、作者和主页、正文、标签、图片、是否视频、时间和页面上的赞藏评计数。
        不点赞、收藏或关注。发现页推荐流会被拒绝。
        """
        return dumps(await flow.get_note(session, url, note_id, xsec_token))

    @server.tool(annotations=READ, structured_output=False)
    async def list_favorites(limit: int = 30) -> str:
        """打开自己的主页「收藏 → 笔记」，滚动读取笔记卡片。

        每条含 title、note_id、url（保留 href 里的 xsec_token）、author、like_count、cover。
        """
        return dumps(await lists.list_favorites(session, limit))

    @server.tool(annotations=READ, structured_output=False)
    async def list_favorite_boards() -> str:
        """打开收藏里的专辑子页。页面上有 /board/ 链接才返回专辑；只有「专辑 · N」而没有链接时不算空列表。"""
        return dumps(await lists.list_favorite_boards(session))

    @server.tool(annotations=READ, structured_output=False)
    async def get_favorite_board(board_id: str, limit: int = 30) -> str:
        """打开 /board/{id} 并读取里面的笔记卡片。打不开成普通文档时返回 page_not_understood。"""
        return dumps(await lists.get_favorite_board(session, board_id, limit))

    @server.tool(annotations=READ, structured_output=False)
    async def search_favorites(query: str, board_id: str = "", refresh: bool = False) -> str:
        """在自己的收藏里按标题或作者搜索。网页没有收藏内搜索，所以滚动后在本地过滤。

        缓存不保存 xsec_token。board_id 为空时搜笔记收藏。
        """
        return dumps(await lists.search_favorites(session, query, board_id or None, refresh))

    return server
