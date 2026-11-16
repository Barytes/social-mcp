"""Read-only Bilibili MCP server."""

from __future__ import annotations

from mcp.server.mcpserver import Image, MCPServer
from mcp.types import ToolAnnotations

from mcp_browser.smoke import dumps

from bili_mcp import flow

READ = ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=True)
LOGIN = ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=False, open_world_hint=True)

INSTRUCTIONS = (
    "只读访问当前这一个 B 站账号：登录状态、扫码或短信登录、搜索、视频详情。"
    "不要点赞、投币、收藏、评论、关注，也不要打开首页推荐。"
    "收藏夹和稍后再看还没实现。"
    "验证码、滑块或风控页出现时停止，让人在有界面的浏览器里处理。"
)


def build_server(session) -> MCPServer:
    server = MCPServer(
        "bilibili",
        instructions=INSTRUCTIONS,
        log_level="WARNING",
    )

    @server.tool(annotations=READ, structured_output=False)
    async def login_status() -> str:
        """查看当前持久配置里的 B 站是否已登录。

        打开账号页而不是首页。已登录时返回昵称和 uid（昵称选择器尚未在已登录会话里核对）。
        未登录时 logged_in 为 false，而不是空结果。
        """
        return dumps(await flow.login_status(session))

    @server.tool(annotations=LOGIN, structured_output=False)
    async def login_qr_start() -> str | list[str | Image]:
        """在官方登录页截取二维码，返回 PNG 绝对路径，并附上图片内容。

        用手机相册或另一块屏幕扫码。不要把二维码写进仓库。
        """
        payload = await flow.login_qr_start(session)
        image = payload.pop("_image_path", None)
        text = dumps(payload)
        if image and payload.get("ok") and payload.get("status") == "qr_ready":
            return [text, Image(path=image)]
        return text

    @server.tool(annotations=READ, structured_output=False)
    async def login_qr_wait(timeout_s: float = 90) -> str:
        """在当前登录页上等扫码完成、过期，或出现需要人处理的验证。

        timeout_s 为 1 到 180 秒。等待期间同一浏览器被占用。
        """
        return dumps(await flow.login_qr_wait(session, timeout_s))

    @server.tool(annotations=LOGIN, structured_output=False)
    async def login_sms_request(phone: str) -> str:
        """在官方登录页切到短信登录并请求验证码。

        phone 只作为本次调用的参数，不会写入日志。未注册的手机号可能会被网站自动注册。
        不提供密码参数；密码只能由人在有界面的窗口里输入。
        """
        return dumps(await flow.login_sms_request(session, phone))

    @server.tool(annotations=LOGIN, structured_output=False)
    async def login_sms_submit(code: str) -> str:
        """提交短信验证码。code 不会写入日志或回显。"""
        return dumps(await flow.login_sms_submit(session, code))

    @server.tool(annotations=READ, structured_output=False)
    async def search(keyword: str, limit: int = 10, page: int = 1) -> str:
        """打开 B 站搜索页并读取视频卡片。不打开首页推荐。

        limit 为 1–30，page 为 1–50。没有结果和页面没解析成功是两种状态。
        每条结果含 title、bvid、url、up_name、play_count、duration、publish_date、cover_url。
        """
        return dumps(await flow.search_videos(session, keyword, limit, page))

    @server.tool(annotations=READ, structured_output=False)
    async def get_video(bvid: str) -> str:
        """打开视频页，读取标题、简介、标签和 UP 主。"""
        return dumps(await flow.get_video(session, bvid))

    return server
