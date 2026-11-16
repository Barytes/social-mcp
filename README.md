# 个人只读 MCP：B 站与小红书

在一台 Linux 上跑两个 **stdio MCP** 服务，给同一个人的助手读取自己的 B 站和小红书内容。本阶段能做的是：保持登录、搜索、报告登录状态。收藏夹和 B 站「稍后再看」只留了允许访问的地址和未实现的函数，**没有注册成工具，也没有在真站上试过**。

这个仓库是个人用途，请保持私有。浏览器配置目录里有登录会话，不能提交。

## 保证

- 只用系统安装的 Google Chrome 打开正常网页（Playwright `executable_path`），每个站点一个持久 `user-data-dir`。数据来自渲染后的 DOM。
- 不调用未公开接口，不算 wbi / x-s / x-t 签名，不把页面 XHR 当作数据源，不从浏览器数据库导出 cookie，也不要用户粘贴 cookie 或 token，不伪装官方 App。
- 出现验证码、滑块或风控页时停止，返回 `needs_human_verification`，带上当前 URL 和截图路径。不会尝试绕过。
- 只读。代码里的点击必须带允许的登录用途，并且控件文案要精确匹配（短信登录、获取验证码、登录、同意协议的复选框）。点赞、投币、收藏、评论、关注、发布、返回首页会被拒绝。搜索不点击结果。
- 不打开推荐流：`https://www.bilibili.com/`、`/v/popular`、`https://www.xiaohongshu.com/explore`（没有笔记 id 的发现页，包括 `channel_id=homefeed_recommend`）。笔记详情 `/explore/{id}` 可以打开。被重定向到推荐流时会关掉页面，不返回那里的内容。
- 密码、短信验证码、cookie、`qrcode_key`、`xsec_token` 不会写进日志。日志只走 stderr 和数据目录里的日志文件，并做脱敏。搜索结果里的笔记链接会保留页面自己带的 `xsec_token`，否则链接打不开；这条只出现在工具结果里，不出现在日志里。
- 一个进程只有一个浏览器上下文，操作串行。浏览器崩溃会重启一次。退出时关闭 Chrome，让配置写回磁盘。崩溃留下的 `SingletonLock` 只在确认没有 Chrome 还占用该目录时删除，不会删 `Cookies`。
- 小红书同一账号新的网页登录会踢掉其他网页会话。`login_status` 在看不到登录态时返回 `logged_in: false`、`reason: session_absent_or_replaced`。它分不清「还没登录」和「被踢」，两种都会明确报未登录，而不是空结果。

无头模式没有加反检测参数。本机探测时，无头 Chrome 打开小红书会进安全限制页（`error_code=300012`，文案是「当前网络存在风险」）；同一个有界面的窗口能打开正常登录页。这不是绕过，有界面模式就是给人自己操作的。

## 环境

目标机器：Debian 13、Python 3.13、uv、Google Chrome（`/usr/bin/google-chrome`）。代码要求 Python 3.12 及以上。

不需要 `playwright install`，也不下载 Playwright 自带的浏览器。

```bash
uv python install 3.13   # 机器上还没有 3.13 时
uv sync
```

## 环境变量

| 变量 | 默认 | 作用 |
| --- | --- | --- |
| `MCP_CHROME_PATH` | `/usr/bin/google-chrome` | 系统 Chrome |
| `MCP_HEADED` | 关 | `1` 时显示窗口，人和验证码都用这个窗口 |
| `BILI_HEADED` / `XHS_HEADED` | 跟随 `MCP_HEADED` | 单站覆盖 |
| `BILI_CHROME_PATH` / `XHS_CHROME_PATH` | 跟随上面的 Chrome | 单站覆盖 |
| `BILI_DATA_DIR` | `~/.local/share/bili-mcp` | 日志、截图、二维码 |
| `BILI_PROFILE_DIR` | `$BILI_DATA_DIR/profile` | Chrome 用户目录 |
| `XHS_DATA_DIR` | `~/.local/share/xhs-mcp` | 同上 |
| `XHS_PROFILE_DIR` | `$XHS_DATA_DIR/profile` | 同上 |

有界面模式需要 `$DISPLAY` 或 `$WAYLAND_DISPLAY`，否则进程直接报错，不会偷偷改成无头。

配置目录如果落在 git 仓库里面，启动会拒绝。两个服务不要同时打开同一个 profile。冒烟脚本也占用 profile，不要和 MCP 进程一起跑。

## 注册成 stdio MCP

把 `/ABS/PATH` 换成仓库绝对路径：

```json
{
  "mcpServers": {
    "bilibili": {
      "command": "uv",
      "args": ["run", "--directory", "/ABS/PATH", "bili-mcp"]
    },
    "xiaohongshu": {
      "command": "uv",
      "args": ["run", "--directory", "/ABS/PATH", "xhs-mcp"],
      "env": {
        "XHS_HEADED": "1"
      }
    }
  }
}
```

有界面时给这个进程准备好 `DISPLAY`。助手侧只应看到 JSON-RPC；日志在 stderr。

命令：

```bash
uv run bili-mcp
uv run xhs-mcp
```

## 登录

同一套 profile。进程正常退出后，下次启动还是这个登录态。`kill -9` 可能来不及把会话写盘，但下次启动会清掉已经死掉的 `SingletonLock`，而不是删掉整个 profile。

1. **扫码（优先）**  
   `login_qr_start` 打开官方登录页，把二维码截成 PNG，返回绝对路径，并作为 MCP 图片内容返回。用手机相册或另一块屏幕扫。  
   B 站用 App 扫。登录页会自己跳到 `?site=OVERSEAS&lang=zh-Hans` 或 `lang=en`，这次跳转会让第一次 `goto` 变成 `net::ERR_ABORTED`；只要最后还停在 `passport.bilibili.com` 上并且文档加载了，就当作打开成功，不报 `page_load_failed`。二维码画在 `.login-scan__qrcode` 里的 `canvas`（旁边可能还有一个没有 class 的 `img`），会比 DOMContentLoaded 晚几秒，截的是这块 canvas。语言参数不影响选择器。不点击「密码登录 / Password login」或「登录 / Login」，有界面窗口里账号、密码和短信表单留给人自己填。  
   小红书页面写的是小红书或微信。  
   `login_qr_wait`（默认 90 秒，单次最长 180 秒）在当前页等到：已登录、二维码过期、需要人处理，或这一轮时间用完。等待期间这个浏览器被占用。  
   同一张二维码在过期前可以反复调用 `login_qr_wait`。它不会重新打开登录页，所以不会把正在扫的码换掉。还没扫完时返回 `qr_pending`，`qr_still_valid` 为 true。页面显示出过期时返回 `qr_expired`，这时才重新 `login_qr_start`。冒烟命令的 `--wait` 仍然最长 180 秒。
2. **短信**  
   `login_sms_request(phone)` 再 `login_sms_submit(code)`。号码和验证码只作为工具参数，不进日志，也不会在结果里回显。  
   B 站短信页写着未注册手机号会自动注册，这是官网表单的行为。  
   没有密码参数。密码只由人在有界面的窗口里输入（浏览器自己的密码填充也行）。
3. **有界面**  
   `BILI_HEADED=1` 或 `XHS_HEADED=1`。验证码、协议勾选、密码都在这个窗口里完成。同一 profile。

`login_status` 会打开非推荐流页面核对：

- B 站：`https://account.bilibili.com/account/home`。未登录时会跳到 `passport.bilibili.com`。已登录应能看到昵称或 UID；选择器对不上就返回 `login_state_unclear`，不会假装已登录。扫码和短信打开的是 `https://passport.bilibili.com/pc/passport/login`。裸的 `https://passport.bilibili.com/login` 会 HTTP 404，Chrome 把它当成下载；这时返回 `page_load_failed`，并写明页面没有作为文档打开。账号页如果也因此打不开，会再试一次这个 PC 登录页，用来区分「未登录」和「登录页没加载」。
- 小红书：先打开 `/login`。能看到二维码或手机号框就是未登录。若被重定向到发现页，会立刻离开，再看搜索页头部。风控页单独返回 `needs_human_verification`。

## 工具

两边都有：`login_status`、`login_qr_start`、`login_qr_wait`、`login_sms_request`、`login_sms_submit`、`search`。

- B 站 `search(keyword, limit=10, page=1)`。`limit` 1–30，`page` 1–50。直接打开 `https://search.bilibili.com/all?keyword=&page=`。结果字段：`title`、`bvid`、`url`、`up_name`、`play_count`（卡片上的播放文案）、`duration`、`publish_date`、`cover_url`。还有 `get_video(bvid)`：标题、简介、标签、UP 主。
- 小红书 `search(keyword, limit=10)`。打开搜索页。未登录时页面是「登录后查看搜索结果」，返回 `logged_out`，不是空列表。结果字段：`title`、`note_id`、`url`（保留 `xsec_token`）、`author`、`like_count`、`cover_url`、`type`（看得到播放或图文标记才填）。还有 `get_note(url)`，只接受笔记 URL。

空结果是 `status: no_results`。页面打不开、被风控、或结构和预期不符，是失败状态，不会报成 0 条。

## 还没做

`bili_mcp/future.py` 和 `xhs_mcp/future.py`：

- B 站收藏夹：`https://space.bilibili.com/{uid}/favlist`
- B 站稍后再看：`https://www.bilibili.com/watchlater`
- 小红书收藏：打算打开用户主页，不点击「收藏」。具体 tab 未核对。

这些 URL 在导航白名单里，函数固定返回 `not_implemented` 且 `tested: false`。

## 冒烟

在目标机器上对真站跑。失败时 JSON 里有错误类型；页面类失败会把截图放进数据目录。

```bash
uv run bili-mcp-smoke doctor
uv run bili-mcp-smoke login-status
uv run bili-mcp-smoke --headed login-qr
uv run bili-mcp-smoke search '关键词' --limit 5 --page 1
uv run bili-mcp-smoke get-video BVxxxxxxxxxx

uv run xhs-mcp-smoke doctor
uv run xhs-mcp-smoke --headed login-status
uv run xhs-mcp-smoke --headed login-qr
uv run xhs-mcp-smoke --headed search '关键词' --limit 5
uv run xhs-mcp-smoke get-note 'https://www.xiaohongshu.com/explore/笔记id?xsec_token=...'
```

退出码：`0` 成功，`2` 未登录，`3` 需要人处理，`4` 页面没解析成，`5` profile 被占用，`1` 其他失败。`doctor` 不打开网站。

单元测试（不访问这两个网站，除了本地 Chrome 对 `127.0.0.1` 的会话测试）：

```bash
uv run pytest
```

这条浏览器测试检查：配置目录在正常关闭后还在、崩溃后的锁能清掉并再次打开、推荐流文档导航会被拦住、点赞按钮点不下去。

## 开发时实际看过的页面

在这台能访问公网的环境里，用系统 Chrome 打开过公开页面，用来核对选择器。没有登录，没有提交短信，没有扫码成功。

看过并且写进选择器的：

- B 站搜索页卡片：`.bili-video-card`、标题、BV 链接、UP 主、播放文案、时长、日期、`button.vui_pagenation--btn-side`（「下一页」）。`page=2` 会换一批结果，地址会变成 `/zh-Hans/all`。
- B 站未登录时，`account.bilibili.com/account/home` 会跳到 `passport.bilibili.com`。无头打开 `https://passport.bilibili.com/pc/passport/login` 时，第一次导航会被客户端跳转到 `?site=OVERSEAS&lang=zh-Hans` 打断（`net::ERR_ABORTED`）；等地址稳定后就是登录页。这台机器上可见的码是 `.login-scan__qrcode img`（alt 为 Scan me!，约 140px），同级 `canvas` 在 DOM 里但布局尺寸是 0。目标机器的有界面页面则是 canvas 有尺寸、img 没有 class。两种都截有尺寸的那一个，优先 canvas。截图放大后能解成一条 https 二维码；内容没有记下来，也没有拿去扫码登录。英文界面还有 Password login 和 SMS Login，工具不点 Login、不填密码。裸的 `/login` 在目标机器上会 HTTP 404，Chrome 把它当成下载。
- B 站搜索页未登录头部有 `.header-avatar-unlogin-entry`。
- B 站视频页：`h1.video-title`、`.desc-info-text`、`a.up-name`、`.video-tag-container a.tag-link`。页面会先闪一下「出错啦」再出来，所以详情会多等几秒。发布日期选择器没有在真站上对上，可能是空的。
- 小红书有界面登录页：`img.qrcode-img`、`input[placeholder=输入手机号]`、`input[placeholder=输入验证码]`、`获取验证码`、`button.submit`「登录」。
- 小红书未登录搜索页文案是「登录后查看搜索结果」，并且页头有指向 `/explore?channel_id=homefeed_recommend` 的链接。这些链接被白名单拒绝。
- 小红书无头模式进入 `/website-login/error`，标题「安全限制」，正文「当前网络存在风险」，`error_code=300012`。

没看过、选择器是按页面结构写的，真登录后可能要改：

- 已登录时的昵称 / UID（B 站账号页、小红书头像或个人主页）。
- 小红书笔记卡片（`section.note-item`、`xsec_token` 链接、作者、赞数、播放图标）。未登录时搜索页不给卡片。
- 小红书笔记详情标题和正文。
- 非海外版 B 站登录页（国内 IP 可能不是 `site=OVERSEAS` 这套 DOM）。
- 收藏夹、稍后再看。
- 短信是否必须先勾选协议。代码只会点一个可见的 `input[type=checkbox]`；没有复选框就不会乱点。页面如果提示先同意，会返回 `sms_form_not_ready`。

单元测试用的是按上述结构写的 HTML 片段，不是从网站整页抓下来的文件，所以仓库里没有别人的内容和 token。

## 风险

- 目标机器如果在美国，小红书可能直接给风控页或 500。无头模式在这里已经复现了 300012。先用 `XHS_HEADED=1` 让人在窗口里处理。不要加 stealth。
- B 站从非中国网络会进海外登录页，短信登录可能给未注册号码开户。
- 小红书新的网页登录会踢掉这个 profile 里的网页会话。手机 App 一般还在，但别的网页端会掉线。
- 二维码 PNG 等价于一次登录入口，只放在 `~/.local/share/.../qr/`，不要拷进仓库。
- 播放量取的是搜索卡片左侧第一项文案，和页面上看到的一致，不另做换算。
- 搜索标题里的 HTML 实体（例如 `OP&amp;ED`）会解成普通字符。链接里的 `xsec_token` 仍原样保留。
- 小红书有界面模式会注册 Service Worker。这类请求没有 frame，路由不能因此抛错，也不能因此放行推荐流或非 GET/HEAD/OPTIONS 的 worker 请求。
