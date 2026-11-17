"""Read-only Bilibili MCP server."""

from __future__ import annotations

from mcp.server.mcpserver import Image, MCPServer
from mcp.types import ToolAnnotations

from mcp_browser.smoke import dumps

from bili_mcp import flow, lists

READ = ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=True)
LOGIN = ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=False, open_world_hint=True)

INSTRUCTIONS = (
    "只读访问当前这一个 B 站账号：登录状态、扫码或短信登录、搜索、视频详情、自己的收藏夹和稍后再看。"
    "不要点赞、投币、收藏、评论、关注、播放全部、批量操作或删除，也不要打开首页推荐。"
    "视频页和稍后再看会拦住播放请求。验证码、滑块或风控页出现时停止，让人在有界面的浏览器里处理。"
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

        打开账号页而不是首页。已登录时返回昵称和 uid。昵称在 span.home-top-msg-name。
        未登录时 logged_in 为 false，而不是空结果。
        """
        return dumps(await flow.login_status(session))

    @server.tool(annotations=LOGIN, structured_output=False)
    async def login_qr_start() -> str | list[str | Image]:
        """在官方登录页截取二维码，返回 PNG 绝对路径，并附上图片内容。

        二维码画在 .login-scan__qrcode 里的 canvas 上，可能比 DOMContentLoaded 晚几秒。
        zh-Hans 和 en 都是这一块。不点击密码登录或短信登录，有界面窗口里这两块表单留给人自己用。
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

        timeout_s 为 1 到 180 秒。同一张二维码在过期前可以反复调用本工具，不会重新打开登录页。
        手机已扫但还没点确认时，这次调用会继续等到超时，而不是马上返回。
        确认后官网会打开 passport 的 crossDomain，再跳到首页。首页仍会被拦住；这时改打开账号页确认登录。
        还没扫完时返回 qr_pending（qr_still_valid 为 true）。二维码过期时返回 qr_expired，这时才重新 login_qr_start。
        登录页打不开时返回 page_load_failed，而不是一段浏览器下载错误。
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
        """打开视频页，读取标题、UP 主和空间地址、发布时间、时长、简介、标签、页面上的计数和分 P。

        不播放媒体：播放地址、分片和历史上报请求会被丢掉，视频元素会静音并暂停。
        没有在已登录会话里核对「历史记录没有新增」。
        """
        return dumps(await flow.get_video(session, bvid))

    @server.tool(annotations=READ, structured_output=False)
    async def list_favorite_folders() -> str:
        """列出自己的收藏夹。先打开 space.bilibili.com 得到自己的 uid，再读收藏夹侧栏。

        每条含 id（fid，页面上有才填）、name、count、kind（created / followed / other）。
        """
        return dumps(await lists.list_favorite_folders(session))

    @server.tool(annotations=READ, structured_output=False)
    async def get_favorite_folder(fid: str, page: int = 1, sort: str = "recent", keyword: str = "") -> str:
        """打开一个自己创建的收藏夹并读取视频卡片。

        sort 为 recent、most_played 或 recent_submit。keyword 只填收藏夹自己的搜索框，结果仍按标题和 UP 主再滤一遍。
        翻页只点「下一页」。不点播放全部、批量操作或收藏。
        """
        return dumps(await lists.get_favorite_folder(session, fid, page, sort, keyword or None))

    @server.tool(annotations=READ, structured_output=False)
    async def list_watch_later(page: int = 1, limit: int = 30) -> str:
        """读取稍后再看面板。打开 /list/watchlater，不打开会触发下载的 /watchlater/#/list。

        滚动右侧面板，不解析播放器下面的推荐。返回 title、bvid、url、play_count、position。面板上没有 UP 主名字。
        """
        return dumps(await lists.list_watch_later(session, page, limit))

    @server.tool(annotations=READ, structured_output=False)
    async def search_favorites(query: str, folder_id: str = "", refresh: bool = False) -> str:
        """在自己的收藏夹里按标题或 UP 主搜索。folder_id 为空时遍历有 fid 的自建夹。

        重复搜索用本机缓存（不写 cookie）。refresh 为 true 时重新打开页面。
        """
        return dumps(await lists.search_favorites(session, query, folder_id or None, refresh))

    @server.tool(annotations=READ, structured_output=False)
    async def search_watch_later(query: str, refresh: bool = False) -> str:
        """在稍后再看里按标题搜索。列表会滚到上限后在本地过滤，并记下不含 cookie 的缓存。"""
        return dumps(await lists.search_watch_later(session, query, refresh))

    return server
