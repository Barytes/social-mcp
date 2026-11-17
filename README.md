# 个人只读 MCP：B 站与小红书

在一台 Linux 上跑两个 **stdio MCP** 服务，给同一个人的助手读取自己的 B 站和小红书内容。本阶段能做的是：保持登录、搜索、报告登录状态。收藏夹和 B 站「稍后再看」只留了允许访问的地址和未实现的函数，**没有注册成工具，也没有在真站上试过**。

这个仓库是个人用途，请保持私有。浏览器配置目录里有登录会话，不能提交。

## 保证

- 只用系统安装的 Google Chrome 打开正常网页（Playwright `executable_path`），每个站点一个持久 `user-data-dir`。数据来自渲染后的 DOM。
- 不调用未公开接口，不算 wbi / x-s / x-t 签名，不把页面 XHR 当作数据源，不从浏览器数据库导出 cookie，也不要用户粘贴 cookie 或 token，不伪装官方 App。
- 出现验证码、滑块或风控页时停止，返回 `needs_human_verification`，带上当前 URL 和截图路径。不会尝试绕过。
- 只读。代码里的点击必须带允许的登录用途，并且控件文案要精确匹配（短信登录、获取验证码、登录、新设备弹窗上的「验证」、同意协议的复选框）。点赞、投币、收藏、评论、关注、发布、返回首页、「重新发送」会被拒绝。搜索不点击结果。
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
      "args": ["run", "--directory", "/ABS/PATH", "xhs-mcp-xvfb"]
    }
  }
}
```

`xhs-mcp-xvfb` 在 `:90` 上没有显示时启动 `Xvfb :90`，然后以 `DISPLAY=:90` 和 `XHS_HEADED=1` 跑同一个服务。已经有人占用这块显示时不会再起一个。机器上没有 `Xvfb` 时直接退出并说明。助手侧只应看到 JSON-RPC；日志在 stderr。

命令：

```bash
uv run bili-mcp
uv run xhs-mcp-xvfb
```

## 登录

同一套 profile。进程正常退出后，下次启动还是这个登录态。`kill -9` 可能来不及把会话写盘，但下次启动会清掉已经死掉的 `SingletonLock`，而不是删掉整个 profile。启动前会删掉 `Default/Sessions` 和 Current/Last Session、Tabs，并把 `restore_on_startup` 设成 5，避免 Chrome 把上次的几十个标签（包括首页和 `chrome-error`）重新打开。不删 Cookies，也不删 Login Data。打开之后只留一个标签；留下的如果是推荐流或错误页，就改成 `about:blank`。

1. **扫码（优先）**  
   `login_qr_start` 打开官方登录页，把二维码截成 PNG，返回绝对路径，并作为 MCP 图片内容返回。用手机相册或另一块屏幕扫。  
   B 站用 App 扫。登录页会自己跳到 `?site=OVERSEAS&lang=zh-Hans` 或 `lang=en`，这次跳转会让第一次 `goto` 变成 `net::ERR_ABORTED`；只要最后还停在 `passport.bilibili.com` 上并且文档加载了，就当作打开成功，不报 `page_load_failed`。二维码画在 `.login-scan__qrcode` 里的 `canvas`（旁边可能还有一个没有 class 的 `img`），会比 DOMContentLoaded 晚几秒，截的是这块 canvas。语言参数不影响选择器。不点击「密码登录 / Password login」或「登录 / Login」，有界面窗口里账号、密码和短信表单留给人自己填。  
   小红书页面写的是小红书或微信。  
   手机确认后，B 站会把主框架打开到 `passport.biligame.com`、`passport.bigfunapp.cn` 或 `passport.bilibili.cn` 上的 `/x/passport-login/web/crossDomain`，然后再去 `www.bilibili.com/`。只放行那一条路径。首页仍然拦住。拦住之后改打开账号页确认登录，不把这次跳转报成未登录。  
   `login_qr_wait`（默认 90 秒，单次最长 180 秒）会一直等到：已登录、二维码过期、小红书弹出短信二次验证、需要人处理，或这一轮时间用完。手机已经扫到但还没确认时，这次调用不会马上返回。等待期间这个浏览器被占用。  
   同一张二维码在过期前可以反复调用 `login_qr_wait`。它不会重新打开登录页，所以不会把正在扫的码换掉。还没扫完并且这次时间用完时返回 `qr_pending`，`qr_still_valid` 为 true。页面显示出过期时返回 `qr_expired`，这时才重新 `login_qr_start`。  
   小红书新设备会在扫码后弹出「短信验证码验证」，页面上已经写着打码的手机号。这时返回 `sms_verification_required`。把收到的数字交给 `login_sms_submit`。不要点「重新发送」，验证码会过期，重发由人决定。点「验证」之后网站会去首页，这次跳转被拦住，再在非推荐页上确认登录。  
   冒烟命令的 `login-qr --wait` 会按墙上时钟继续等，直到已登录、过期、需要短信、或 `--wait` 的秒数用完。它不会在「请在手机上确认」时退出并把浏览器关掉。单次内部等待仍不超过 180 秒，更长的 `--wait` 会接着等。
2. **短信**  
   `login_sms_request(phone)` 再 `login_sms_submit(code)`。号码和验证码只作为工具参数，不进日志，也不会在结果里回显。扫码后的新设备弹窗走同一个提交工具，点的是「验证」。  
   B 站短信页写着未注册手机号会自动注册，这是官网表单的行为。  
   没有密码参数。密码只由人在有界面的窗口里输入（浏览器自己的密码填充也行）。
3. **有界面**  
   `BILI_HEADED=1` 或 `XHS_HEADED=1`。验证码、协议勾选、密码都在这个窗口里完成。同一 profile。

`login_status` 会打开非推荐流页面核对：

- B 站：`https://account.bilibili.com/account/home`。未登录时会跳到 `passport.bilibili.com`。已登录时昵称在 `span.home-top-msg-name`（2026-11-17 在已登录的账号页上看见）。选择器对不上就返回 `login_state_unclear`，不会假装已登录。扫码和短信打开的是 `https://passport.bilibili.com/pc/passport/login`。裸的 `https://passport.bilibili.com/login` 会 HTTP 404，Chrome 把它当成下载；这时返回 `page_load_failed`，并写明页面没有作为文档打开。账号页如果也因此打不开，会再试一次这个 PC 登录页，用来区分「未登录」和「登录页没加载」。
- 小红书：先打开 `/login`。能看到二维码或手机号框就是未登录。若被重定向到发现页，会立刻离开，再看搜索页头部。已经有 uid 但头部没有昵称时，再打开这个 uid 的 `/user/profile/<uid>`，不打开发现页。风控页单独返回 `needs_human_verification`。

## 工具

两边都有：`login_status`、`login_qr_start`、`login_qr_wait`、`login_sms_request`、`login_sms_submit`、`search`。

- B 站 `search(keyword, limit=10, page=1)`。`limit` 1–30，`page` 1–50。第一页是 `https://search.bilibili.com/all?keyword=`，不带 `page=1`（带上之后已登录的结果列表是空的）。后面的页是 `page=N&o=(N-1)*30`。先等 `.bili-video-card__info--tit`，因为 `.search-page` 会比卡片更早出现。结果字段：`title`、`bvid`、`url`、`up_name`、`play_count`（卡片上的播放文案）、`duration`、`publish_date`、`cover_url`。还有 `get_video(bvid)`：标题、UP 主和空间地址、发布时间、时长、简介、标签、页面上的播放/赞/币/藏/转发、分 P。不播放。
- 小红书 `search(keyword, limit=10)`。打开搜索页。未登录时页面是「登录后查看搜索结果」，返回 `logged_out`，不是空列表。结果字段：`title`、`note_id`、`url`（保留 `xsec_token`）、`author`、`like_count`、`cover_url`、`type`（看得到播放或图文标记才填）。还有 `get_note(url)` 或 `get_note(note_id, xsec_token)`。笔记地址可以是 `/explore/{id}`，也可以是收藏里的 `/user/profile/{uid}/{note_id}`。详情读取标题、作者和主页、正文、标签、图片、是否视频、时间和页面上的计数。收藏页上的卡片选择器来自抓取；详情页多出来的计数字段没有在真站上再对过。

空结果是 `status: no_results`。页面打不开、被风控、或结构和预期不符，是失败状态，不会报成 0 条。

## 收藏和稍后再看

都是读渲染后的页面。不点赞、不收藏、不点「播放全部」「批量操作」「删除」「新建收藏夹」。

- B 站 `list_favorite_folders`。先打开 `https://space.bilibili.com/`，等它跳到 `/<uid>`，这个 uid 在本次进程里记住。再打开 `/<uid>/favlist`。侧栏「我创建的收藏夹」的 fid 是那一行的 `id`；「默认收藏夹」在地址没有 `fid` 时没有 id。跟过的合集在这次抓到的页面上没有 fid。`kind` 为 `created`、`followed` 或 `other`。
- B 站 `get_favorite_folder(fid, page=1, sort=recent)`。地址是 `/<uid>/favlist?fid=<fid>&ftype=create`。`sort` 只点「最近收藏 / 最多播放 / 最近投稿」。翻页只点「下一页」。可选 `keyword` 填收藏夹自己的「请输入关键词」，再按标题和 UP 主滤一遍。
- B 站 `list_watch_later(page, limit)`。`/watchlater/#/list` 在 Playwright 里会变成下载，匿名 `curl` 对 `/watchlater` 和 `/list/watchlater` 都是 HTTP 200、没有 `Location`。能读到列表的是 `https://www.bilibili.com/list/watchlater`，这是播放器页，右侧「稍后再看 1/489」。条目的 bvid 在 `data-key`。面板不显示 UP 主。播放器下面的推荐不解析。滚动的是 `.action-list-body`。
- B 站 `search_favorites` / `search_watch_later`。没有可靠的全库搜索地址时，就逐页或滚动后在本地做不区分大小写的子串匹配（中文按原文）。结果带文件夹名和 bvid。本机 `list-cache` 记下 `fetched_at`，`refresh=true` 才重抓。缓存不写 cookie。
- 小红书 `list_favorites(limit)`。自己的 `/user/profile/<uid>?tab=fav&subTab=note`。卡片链接是 `/user/profile/<uid>/<note_id>?xsec_token=...`，原样返回。
- 小红书 `list_favorite_boards` / `get_favorite_board`。专辑子页是 `subTab=board`。抓到的页面是笔记子页，只有「专辑 · 1」，没有 `/board/` 链接；这时返回 `page_not_understood`，不当成空列表。`/board/<id>` 若是普通文档就按笔记卡片读，否则也是 `page_not_understood`。
- 小红书 `search_favorites`。网页没有收藏内搜索，滚动后本地过滤。缓存去掉 `xsec_token`。

打开视频或稍后再看时：Chrome 用 `--autoplay-policy=document-user-activation-required`；路由丢掉 `.m4s`、`.flv`、`.m3u8`、`playurl`、`/x/v2/history`、`/x/click-interface/`；页面里的 `video` / `audio` 会静音并暂停。没有在已登录会话里核对历史记录是否原样没变。播放器文档本身仍会打开，这一步有没有被记进历史，还没验证。

## 冒烟

在目标机器上对真站跑。失败时 JSON 里有错误类型；页面类失败会把截图放进数据目录。

```bash
uv run bili-mcp-smoke doctor
uv run bili-mcp-smoke login-status
uv run bili-mcp-smoke --headed login-qr
uv run bili-mcp-smoke search '关键词' --limit 5 --page 1
uv run bili-mcp-smoke get-video BVxxxxxxxxxx
uv run bili-mcp-smoke list-favorite-folders
uv run bili-mcp-smoke get-favorite-folder 3953102056 --page 1
uv run bili-mcp-smoke list-watch-later --limit 20
uv run bili-mcp-smoke search-favorites '关键词'
uv run bili-mcp-smoke search-watch-later '关键词'

uv run xhs-mcp-smoke doctor
uv run xhs-mcp-smoke --headed login-status
uv run xhs-mcp-smoke --headed login-qr
uv run xhs-mcp-smoke --headed search '关键词' --limit 5
uv run xhs-mcp-smoke get-note 'https://www.xiaohongshu.com/explore/笔记id?xsec_token=...'
uv run xhs-mcp-smoke list-favorites --limit 10
uv run xhs-mcp-smoke list-favorite-boards
uv run xhs-mcp-smoke search-favorites '关键词'
```

退出码：`0` 成功，`2` 未登录，`3` 需要人处理，`4` 页面没解析成，`5` profile 被占用，`1` 其他失败。`doctor` 不打开网站。

单元测试（不访问这两个网站，除了本地 Chrome 对 `127.0.0.1` 的会话测试）：

```bash
uv run pytest
```

这条浏览器测试检查：配置目录在正常关闭后还在、崩溃后的锁能清掉并再次打开、推荐流文档导航会被拦住、点赞按钮点不下去。

## 开发时实际看过的页面

开发环境里用系统 Chrome 打开过公开页面来核对选择器，当时没有登录。下面单独标出的已登录行为，是 2026-11-17 在目标机器的真实 profile 上看的。

看过并且写进选择器的：

- B 站搜索页卡片：`.bili-video-card`、标题、BV 链接、UP 主、播放文案、时长、日期、`button.vui_pagenation--btn-side`（「下一页」）。未登录时 `page=2` 会换一批结果，地址会变成 `/zh-Hans/all`。已登录时带裸的 `page=1` 会画出 0 张卡片；第一页必须是不带 `page` 的地址，第二页是 `page=2&o=30`，并且和第一页的 BV 不同。卡片选择器要等 `.bili-video-card__info--tit`，不能只等 `.search-page`。
- B 站未登录时，`account.bilibili.com/account/home` 会跳到 `passport.bilibili.com`。无头打开 `https://passport.bilibili.com/pc/passport/login` 时，第一次导航会被客户端跳转到 `?site=OVERSEAS&lang=zh-Hans` 打断（`net::ERR_ABORTED`）；等地址稳定后就是登录页。这台机器上可见的码是 `.login-scan__qrcode img`（alt 为 Scan me!，约 140px），同级 `canvas` 在 DOM 里但布局尺寸是 0。目标机器的有界面页面则是 canvas 有尺寸、img 没有 class。两种都截有尺寸的那一个，优先 canvas。截图放大后能解成一条 https 二维码；内容没有记下来，也没有拿去扫码登录。英文界面还有 Password login 和 SMS Login，工具不点 Login、不填密码。裸的 `/login` 在目标机器上会 HTTP 404，Chrome 把它当成下载。
- B 站搜索页未登录头部有 `.header-avatar-unlogin-entry`。
- B 站视频页：`h1.video-title`、`.desc-info-text`、`a.up-name`、`.video-tag-container a.tag-link`。页面会先闪一下「出错啦」再出来，所以详情会多等几秒。发布日期选择器没有在真站上对上，可能是空的。
- 小红书有界面登录页：`img.qrcode-img`、`input[placeholder=输入手机号]`、`input[placeholder=输入验证码]`、`获取验证码`、`button.submit`「登录」。
- 小红书未登录搜索页文案是「登录后查看搜索结果」，并且页头有指向 `/explore?channel_id=homefeed_recommend` 的链接。这些链接被白名单拒绝。
- 小红书无头模式进入 `/website-login/error`，标题「安全限制」，正文「当前网络存在风险」，`error_code=300012`。

2026-11-17 在已登录的 profile 上核对过（这是使用方在目标机器上做的，本仓库的自动化测试没有再登一次）：

- B 站扫码确认后主框架会打开 `passport.biligame.com/x/passport-login/web/crossDomain`，随后去首页。只放行这条路径；首页仍拒绝。账号页昵称是 `span.home-top-msg-name`。
- B 站已登录搜索的第一页和第二页都能读到卡片，第二页的 BV 和第一页不同。
- 小红书扫码后新设备弹出「短信验证码验证」，正文是「验证码已发送至」加已经打码的号码，按钮是「验证」，旁边是「重新发送」。提交后会跳首页，这次跳转被拒绝，登录态留在 profile 里。`login_status` 能读到 uid。已登录搜索返回 10 条笔记。
- 两个 profile 在进程退出再开之后还在。Chrome 会把上次的标签恢复出来（包括首页和 `chrome-error`），所以启动时清会话文件并只留一个标签。
- `f1c56f8` 之后又核对过：B 站 `login_status` 昵称是 Barytes；小红书用 `xhs-mcp-xvfb` 时昵称 `barytes` 来自 `/user/profile/<uid>` 的 `.user-name`（这条现在算核对过）。小红书搜索 `Eric Clapton` 返回 10 条笔记。

收藏夹和稍后再看的选择器是对着已登录时保存的 HTML 写的，本环境没有再打开这两个网站核对：

- B 站收藏夹侧栏 `.fav-sidebar-item`、视频卡片、稍后再看 `.action-list-item-wrap` 的 `data-key`、播放器上的标题 / UP / 简介 / 标签 / 计数。播放器下面的推荐卡片不读。
- 小红书收藏笔记是 `section.note-item`，链接带 `xsec_token`。夹具里的 token 已换成 `fixture-token`。专辑子页没有单独的抓取，所以专辑列表在只有计数、没有 `/board/` 链接时返回 `page_not_understood`。
- 笔记详情里多出来的图片、时间、赞藏评计数，夹具是按常见 class 补的，不在那份收藏抓取里，也没有再对过真站。
- 历史记录有没有因为打开播放器页而增加：没有在已登录会话里核对。

没看过、选择器是按页面结构写的，真登录后可能要改：

- 小红书搜索结果卡片（和收藏卡片不是同一次核对）。
- 小红书笔记详情标题和正文。
- 非海外版 B 站登录页（国内 IP 可能不是 `site=OVERSEAS` 这套 DOM）。
- 短信是否必须先勾选协议。代码只会点一个可见的 `input[type=checkbox]`；没有复选框就不会乱点。页面如果提示先同意，会返回 `sms_form_not_ready`。

单元测试里，登录和搜索用的是按页面结构写的片段。收藏和稍后再看用的是抓取页裁掉脚本和无关节点后的片段，查询串里的 `xsec_token` 已替换。仓库里没有 cookie。

## 风险

- 目标机器如果在美国，小红书可能直接给风控页或 500。无头模式在这里已经复现了 300012。先用 `XHS_HEADED=1` 让人在窗口里处理。不要加 stealth。
- B 站从非中国网络会进海外登录页，短信登录可能给未注册号码开户。
- 小红书新的网页登录会踢掉这个 profile 里的网页会话。手机 App 一般还在，但别的网页端会掉线。
- 二维码 PNG 等价于一次登录入口，只放在 `~/.local/share/.../qr/`，不要拷进仓库。
- 播放量取的是搜索卡片左侧第一项文案，和页面上看到的一致，不另做换算。
- 搜索标题里的 HTML 实体（例如 `OP&amp;ED`）会解成普通字符。链接里的 `xsec_token` 仍原样保留。
- 小红书有界面模式会注册 Service Worker。这类请求没有 frame，路由不能因此抛错，也不能因此放行推荐流或非 GET/HEAD/OPTIONS 的 worker 请求。
- 被拒绝的文档导航只把主机名和路径写进日志，不写查询串，避免 `xsec_token` 进日志。
