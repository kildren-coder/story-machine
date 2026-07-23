# yt-dlp Web 前端综述：MeTube / yt-dlp-web-ui 等对下载管理前端的参考价值

> AFK 调研票 [#25](https://github.com/kildren-coder/story-machine/issues/25)。本文只回答票面 Question，不做拍板；给下游「下载管理前端」grilling 票（自建 vs 现成）供弹药。
> 所有来源访问日期均为 **2026-07-23**。文中区分「来源直接写明」与「据此分析/推断」。

## 问题

`scripts/dl-audio.ps1` 已打通「笔记本给 B 站链接 → 5070 主机 yt-dlp 只抓音频流落 `E:\asr\audio\`」的**单链接 CLI** 链路。用户要一个专门前端，核心两个能力：**下载历史查看**与**批量链接导入**。在拍板「自建 vs 部署现成」前，先把 yt-dlp 的 self-hosted web 前端生态查清楚。要回答：

1. **Windows 部署形态**：5070 主机是 Windows 11。各项目有没有非 Docker 的原生跑法（pip / 单二进制 / NSSM 服务）？若都事实上绑死 Docker，本身就是结论。
2. **批量导入**：各项目的批量形态（多行粘贴 / 播放列表展开 / 订阅）；对 bilibili 链接（BV 号、多 P、`?p=N`）的实际支持——extractor 层都是 yt-dlp，差异在 UI/队列层。
3. **历史记录存法**：sqlite / json / 目录扫描？下载完成后能否挂 hook（回调 / 完成事件 / 目录监听），供后续「下载完→自动转写」串链？
4. **能抄什么 / 不能抄什么**：若自建，队列模型、状态展示、失败重试哪些做法值得抄；若直接部署某一个，给推荐与理由（部署成本、Tailscale 内网兼容）。

**评论修订的口径（2026-07-23，以此为准）：**
- 正文原写「未装 Docker」，用户更正：**PC 上应该有 Docker**。故 Docker 部署**不作排除项**，但仍一并记录各项目的非 Docker 跑法（多一条备选）。
- 实测网络约束：该机代理为 **TUN 全局模式**，B 站出口走 AWS 东京节点、裸请求被风控 **412**（正用 Clash 直连规则 + cookies 兜底处理）。任何下载前端落地都要继承此前提：**B 站流量需直连或带 cookies**。

---

## 结论（TL;DR）

**四个候选里，只有 MeTube 与 ytptube 真正契合「Windows + 音频-only + 历史 + 批量」的定位；yt-dlp-web-ui 是 Linux-first、无 Windows 发行、无完成 hook，本用例可排除；Tube Archivist（及同类 tubesync / pinchflat）是 YouTube 频道归档器 + 媒体库，过重，排除。**

- **Windows 部署**：没有一个提供 `pip install`（MeTube、ytptube 的 PyPI 均 404）。**ytptube 是唯一官方发 Windows 原生二进制的**（`ytptube-Windows-amd64/arm64` 捆绑可执行，非 Docker 也能跑，仅需 ffmpeg 在 PATH）。MeTube 官方只发 Docker 镜像，原生跑要自己 clone + 装 Node 22/Python 3.13 构建前端（可行但折腾）。yt-dlp-web-ui 虽是 Go 单二进制、**但只发 Linux 版**，Windows 二进制 issue（#266）至今 **OPEN**、仅实验性。**既然 PC 有 Docker，三者都能以 Docker 落地**；「绑死 Docker」不成立（ytptube 破例），但「非 Docker 原生跑」只有 ytptube 顺手。
- **批量导入**：三者都支持多条一次入队——MeTube 有「Batch Import」弹窗（**每行一条**、4 并发）；yt-dlp-web-ui 多行粘贴逐行提交 + playlist 勾选 + 直播监控；ytptube 多 URL 队列 + 计划任务/订阅 + 自定义 feed。extractor 都是 yt-dlp，**BV 号 / b23 短链 / cookies 会员内容都支持**。**关键差异在多 P 处理**：MeTube 在元数据抓取阶段**强制 `noplaylist:True`**，据源码分析，对 bilibili 多 P 录播（anthology）**默认只抓第 1 P**、`?p=N` 只抓第 N P——这与现有 `dl-audio.ps1`「多 P 默认全下」的语义**相反**（重要提醒，见论证 §2）。
- **历史存储**：MeTube = **纯 JSON 状态文件**（`queue.json` / `pending.json` / `completed.json` / `subscriptions.json`）；yt-dlp-web-ui v4 = **bbolt**（单文件 `bolt.db`，v3 曾是 sqlite `local.db`，README 未更新是滞后）；Tube Archivist = Elasticsearch 索引（重）。
- **完成 hook（串链关键）**：**MeTube 无原生 webhook**（#941 完成 webhook 提案已关、未合并；源码 grep `webhook` = 0 命中，与其「文件写完即止」的窄范围定位一致）；yt-dlp-web-ui 也无 webhook，只有 JSON-RPC/WebSocket 供客户端轮询/订阅；**ytptube 有真·事件驱动通知**：HTTP webhook + Apprise，事件含 `ITEM_COMPLETED`——**这是三者里唯一开箱即用的「下载完→触发下游」钩子**。
- **对下游 grilling 票的建议**：本项目的下载管理需求其实很窄（历史 + 批量 + 音频-only + cookies + 一个完成钩子）。**若走现成，首选 ytptube**——它一站式满足全部，等于「MeTube 加了 Windows 二进制 + 完成 webhook」，MIT 许可、活跃度最高（本文访问当天仍在推送）。**若走自建**，抄 MeTube 的「三态 JSON 队列 + WebSocket 进度推送 + cookies.txt 上传」，用**目录监听 `E:\asr\audio\`** 做串链（tool-agnostic，最稳）。**不必抄**订阅/频道监控（本项目手动逐集）与媒体库/播放器（过重）。**yt-dlp-web-ui 本用例不推荐**（Windows + 串链两处都最弱）。

一句话：**现成路线选 ytptube（Windows 二进制 + 批量 + 完成 webhook 全齐）；自建则以 MeTube 的 JSON 队列 + 目录监听为蓝本。**

---

## 论证

### 0. 候选总览（GitHub 一手元数据，`gh api`，2026-07-23）

| 项目 | ⭐ | 语言 | 最近推送 | 许可 | 官方形态 | 定位 |
|---|---|---|---|---|---|---|
| **MeTube**（`alexta69/metube`）| 14,215 | Python | 2026-07-21 | **AGPL-3.0** | Docker（多架构）| 最流行的 yt-dlp web UI，范围刻意窄 |
| **yt-dlp-web-ui**（`marcopiovanello/yt-dlp-web-ui`）| 2,523 | Go | 2026-07-14 | GPL-3.0 | Docker + **Linux** 单二进制 | Go 后端 + JSON-RPC，"a self hosted platform for a **Linux NAS**" |
| **ytptube**（`arabcoders/ytptube`）| 987 | Python | **2026-07-23** | **MIT** | Docker + **各平台捆绑可执行（含 Windows）** | MeTube 派生，功能更全（预设/计划任务/通知）|
| **Tube Archivist**（`tubearchivist/tubearchivist`）| 8,303 | Python | 2026-07-05 | GPL-3.0 | Docker（多容器 ES+Redis+Nginx）| **YouTube 归档 + 媒体库**，非通用下载器 |

来源：`gh api repos/<repo>`——
- MeTube — <https://github.com/alexta69/metube>（release 2026.07.21）
- yt-dlp-web-ui — <https://github.com/marcopiovanello/yt-dlp-web-ui>（release v4.0.0，2026-06-29）
- ytptube — <https://github.com/arabcoders/ytptube>（release v2.6.0，2026-07-18）
- Tube Archivist — <https://github.com/tubearchivist/tubearchivist>（release v0.5.10，2026-03-28）

**顺带扫到的同类活跃项目（快速排除）**：
- `Tzahi12345/YoutubeDL-Material`（⭐3,191，TS，推送 2026-03-08）：可 Node 原生跑，但自带媒体库/播放器/观看历史，偏「媒体管理器」而非极简队列；Windows 无文档路径（推断可跑，未测）。
- `meeb/tubesync`（⭐2,760，Python，2026-07-18）与 `kieraneglin/pinchflat`（⭐5,176，Elixir，2025-12-16）：都是 **YouTube 频道/播放列表 → 媒体服务器（Plex/Jellyfin）同步/PVR** 的订阅归档器，以「source」为中心，不是「粘链接就下」的下载管理器。均**排除**。

来源：`gh api repos/Tzahi12345/YoutubeDL-Material`、`.../meeb/tubesync`、`.../kieraneglin/pinchflat`。

---

### 1. Windows 部署形态（Q1）

**没有一个是 `pip install`。** PyPI 实测：`pypi.org/pypi/metube/json` → **HTTP 404**；`pypi.org/pypi/ytptube/json` → **HTTP 404**（`curl` 核对）。故所有「非 Docker 原生跑」都不是 pip 路径。

| 项目 | 非 Docker 原生跑法 | Windows 现实评价 |
|---|---|---|
| **MeTube** | 官方**只发 Docker 镜像**。原生跑要从源码构建：装 **Node.js 22 + Python 3.13**，`pnpm build` 前端 → `uv sync` → `uv run python3 app/main.py`（README「Building and running locally」）| 可行但折腾（要自己 build Angular 前端）；官方无单二进制、无 Windows 服务文档。**实践上 = Docker on Windows** |
| **yt-dlp-web-ui** | Go 单二进制，但 **releases 每一版都只有 `yt-dlp-webui_linux-{amd64,arm64,armv6,armv7}`**（逐版核对，无 `.exe`）。文档只给 **systemd**（Linux）| **无 Windows 发行**。issue [#266 "Windows Binary"](https://github.com/marcopiovanello/yt-dlp-web-ui/issues/266) **OPEN**（11 评论），维护者称「基础 Windows 支持在加、系统托盘免谈」，有人报告 `GOOS=windows go build` 能跑但 ffmpeg 转码未测。**据此推断**：Windows 原生要自己 build（Go + Node 构建前端 + make），unsupported |
| **ytptube** | README 明写「**A bundled executable version for Windows, macOS and Linux**」；release v2.6.0 实有 `ytptube-Windows-amd64-v2.6.0.zip`、`ytptube-Windows-arm64-v2.6.0.zip`（`gh api` 核对资产列表）| **唯一官方 Windows 原生二进制**。注意：非 Docker 需 **ffmpeg 在 PATH**；且部分特性「**In docker only**」——`curl-cffi` 指纹伪装、PO-token 插件、yt-dlp 自动更新 |
| **Tube Archivist** | 无。`docker-compose` 多容器（TubeArchivist + Elasticsearch + Redis + Nginx），文档明写「requires docker」、需 **2–4 GB 内存** | 无原生路径。**排除** |

来源：
- MeTube 本地构建步骤（Node 22 / Python 3.13 / uv）— <https://github.com/alexta69/metube>（README「🛠️ Building and running locally」）
- yt-dlp-web-ui 各版资产、systemd、"Linux NAS" 定位 — <https://github.com/marcopiovanello/yt-dlp-web-ui>；Windows issue — <https://github.com/marcopiovanello/yt-dlp-web-ui/issues/266>
- ytptube Windows 捆绑可执行、ffmpeg/curl-cffi 限制 — <https://github.com/arabcoders/ytptube>（README + release v2.6.0 资产）
- Tube Archivist 多容器 + 内存需求 — <https://github.com/tubearchivist/tubearchivist>（README「Installing」）

> **「全都绑死 Docker」这个假设不成立**：ytptube 有官方 Windows 二进制；yt-dlp-web-ui 有 Linux 单二进制。但**在 Windows 上、非 Docker、开箱即用**这三条同时满足的，只有 ytptube。**既然 PC 有 Docker**，MeTube / yt-dlp-web-ui 也都能落地——Docker 不再是天平砝码，天平回到「功能契合度」上。
>
> **NSSM / Windows 服务**：任何单进程（ytptube 二进制、或 `python app/main.py`、或 build 好的 yt-dlp-webui.exe）都能用 NSSM 包成 Windows 服务后台常驻；走 Docker 则用 Docker Desktop 开机自启更省事。这属通用手段，不构成选型差异。

---

### 2. 批量导入与 bilibili 支持（Q2）

**extractor 层同源**：四者都调 yt-dlp，故 **BV 号、`b23.tv` 短链（需 UI/yt-dlp 展开）、会员/风控内容（带 cookies）** 的支持是一致的——差异只在 **UI/队列层怎么组织批量与多 P**。

| 项目 | 批量形态 | 多 P / playlist 处理 |
|---|---|---|
| **MeTube** | **「Batch Import」弹窗**：文本框**每行一条 URL**，前端 `startBatchImport()` 按 `\r?\n` 拆分、**4 并发**逐条 `/add`（`ui/src/app/app.ts`）。单行输入框仍一次一条。另有频道/播放列表**订阅**（周期检查、自动入队新上传）| 元数据抓取阶段**强制** `extract_flat:True` + `noplaylist:True`（`app/ytdl.py`）。对**真**播放列表/频道会展开成逐条队列项；但对 bilibili 多 P 录播（anthology），`noplaylist` 使 yt-dlp 的 `_yes_playlist` 返回 False → **只返回单个视频**。**据源码分析推断**：裸 `BVxxxx` 只抓第 1 P、`BVxxxx?p=3` 只抓第 3 P（`?p=N` 原样透传、不被 strip）|
| **yt-dlp-web-ui** | 「add download」表单按 `\n` 拆分、逐行经 WebSocket JSON-RPC 提交；有 **playlist 勾选框**、**直播/预告监控**、频道**订阅** | 勾上 playlist → 服务端不加 noplaylist → 可展开全部分 P（推断：对 bilibili anthology 勾选后可全下）|
| **ytptube** | **多 URL 一次入队** + 计划任务/订阅 + 自定义 feed（含非 RSS 站点）+ 预设/单链选项/条件 | MeTube 派生，含 playlist 处理（**未逐一验证 bilibili 多 P 行为，推断**）|

来源：
- MeTube 批量弹窗按 `\r?\n` 拆分 + 4 并发 — `ui/src/app/app.ts` `startBatchImport()`；多 URL 请求 issue [#665](https://github.com/alexta69/metube/issues/665)（已关，指向既有 Import 功能）
- MeTube 强制 `noplaylist/extract_flat`、URL 原样透传 — `app/ytdl.py`（README「How the layers combine」亦明写「MeTube always forces its own flat-extract behaviour … `extract_flat`, `noplaylist`」）
- bilibili 多 P 判定逻辑 — yt-dlp `yt_dlp/extractor/bilibili.py`（`part_id = parse_qs(url).get('p')`；仅 `is_anthology and not part_id and _yes_playlist` 才展开成播放列表）— <https://github.com/yt-dlp/yt-dlp/blob/master/yt_dlp/extractor/bilibili.py>
- yt-dlp-web-ui 多行提交 + playlist 勾选 + 直播监控 — `frontend/src/components/DownloadDialog.tsx`、`server/internal/livestream/monitor.go`
- ytptube 多下载/订阅/feed — <https://github.com/arabcoders/ytptube>（README 功能列表）

> **⚠️ 多 P 语义冲突（重要）**：现有 `dl-audio.ps1` 的行为是「**多 P 录播默认全部下载**，URL 带 `?p=N` 时才 `--no-playlist` 只下第 N P」（脚本第 7 行注释 + 逻辑）。**MeTube 强制 `noplaylist:True`，会把多 P 录播默认只抓第 1 P**——语义与现脚本相反。**据此推断**：若下游选 MeTube 且要保「多 P 全下」，需在 UI/预设里显式关掉 noplaylist 或逐 P 入队；yt-dlp-web-ui 勾 playlist 可全下；自建则要明确定义多 P 策略。该行为为源码静态分析结论、**未在真机跑验证**，建议选型时实测一次。

**cookies（B 站风控前提）**：MeTube 有 **per-download `cookies.txt` 上传**按钮（Advanced Options → Upload Cookies，README「🍪 Using browser cookies」），直接对上「B 站需带 cookies」的约束；yt-dlp-web-ui / ytptube 走「自定义 yt-dlp 参数 / 预设」传 `cookiefile`。三者都能满足现脚本的 `--cookies` 兜底。

---

### 3. 历史存储与完成 hook（Q3）

| 项目 | 历史/状态存储 | 完成后可挂的 hook |
|---|---|---|
| **MeTube** | **纯 JSON 状态文件**：`queue.json` / `pending.json` / `completed.json` / `subscriptions.json`，落在 `STATE_DIR`（README「STATE_DIR」）| **无原生 webhook**。串链只能靠：① 监听 `completed.json` 变化；② **监听下载目录**（最稳）；③ `YTDL_OPTIONS` 里挂 yt-dlp 的 `exec` postprocessor（Docker 内执行，受限）|
| **yt-dlp-web-ui** | **bbolt**（`go.etcd.io/bbolt v1.4.3`，单文件 `bolt.db`；`server/server.go` 打开 `bolt.db`）。历史 = 内存 KV 快照进 bbolt bucket。**v3 曾用 sqlite `local.db`**（`modernc.org/sqlite`），v4 已迁 bbolt——**README 里 `--db local.db` / "sqlite database" 是过期文档**（`go.mod` 已无 sqlite 驱动，`gh` 核对）| **无 webhook**。仅 JSON-RPC 1.0（WebSocket + HTTP-POST）+ OpenAPI（`/openapi`）；进度经 WebSocket 推送。客户端需**轮询 `/running` 或订阅 WS**，无「完成回调」|
| **ytptube** | Python（存储后端未逐一验证，推断 sqlite/json）| **有真·事件驱动通知**：`app/features/notifications/` 定义事件 `ITEM_ADDED` / `ITEM_COMPLETED` / `ITEM_CANCELLED` / `LOG_ERROR` / `TEST`；投递目标 = **HTTP webhook**（JSON/FORM、POST/PUT、自定义 header）**+ Apprise**（100+ 服务）。`gh` 核对：仓库 notification 相关命中 69 处、`app/schema/notifications.json` 存在 |
| **Tube Archivist** | Elasticsearch 索引（重）| 归档器，不适用本用例 |

来源：
- MeTube JSON 状态文件 — <https://github.com/alexta69/metube>（README「STATE_DIR」）；完成 webhook 提案 [#941](https://github.com/alexta69/metube/issues/941) **已关未合并**（`state_reason: null`、无 cross-ref 合并 PR）、源码 grep `webhook` = **0 命中**；维护者窄范围声明「downloads well and **stops once the file is written**」（README「💡 Submitting feature requests」）
- yt-dlp-web-ui bbolt — `go.mod`（唯一数据存储依赖 `go.etcd.io/bbolt v1.4.3`，无 sqlite）、`server/server.go`；JSON-RPC/OpenAPI — README「Extendable」「Open-API」
- ytptube 通知/webhook — `app/features/notifications/`、`app/schema/notifications.json`（事件类型 + webhook/Apprise 目标）— <https://github.com/arabcoders/ytptube>

> **对「下载完→自动转写」串链的直接结论**：
> - **最 tool-agnostic 的钩子是「监听下载目录 `E:\asr\audio\`」**（Windows `FileSystemWatcher` / Python `watchdog`）——不管前端选谁都适用，且现流水线的音频**本就落这个目录**，天然的交接点。
> - **若选 ytptube**：直接用其 `ITEM_COMPLETED` webhook POST 到一个小监听器触发阶段 0 转写，**零额外轮询**，是三者里唯一开箱即用的推送式钩子。
> - MeTube / yt-dlp-web-ui **都没有完成推送**，串链只能回落到目录监听或轮询。

---

### 4. 能抄什么 / 不能抄什么 · 推荐（Q4）

**若下游拍板「自建轻量版」，值得抄的具体做法：**
- **队列三态模型**：MeTube 的 `pending / queue(下载中) / completed` 三段 + 并发上限（`MAX_CONCURRENT_DOWNLOADS`，默认 3）——用三个 JSON 文件持久化，简单、无需数据库，直接可抄。yt-dlp-web-ui / ytptube 也都有并发上限（`--qs` / `queue_size`）。
- **状态展示**：**WebSocket 实时推送进度**（MeTube、yt-dlp-web-ui 都用 WS 做实时刷新）——比轮询体验好，是标配。
- **失败重试**：MeTube UI 允许把失败项**重新入队**（completed/failed 列表可重加）；`CLEAR_COMPLETED_AFTER` 自动清理。这套「完成/失败」列表交互值得抄。
- **cookies.txt 上传**：MeTube 的 per-download cookies 上传——**直接服务 B 站 cookies 兜底**，自建也应留这个口。
- **Fake-IP / SSRF 教训**：MeTube 默认有 SSRF 守卫会拒绝内网地址；README **点名 Clash / Mihomo / sing-box 的 Fake-IP 模式**（解析到 `198.18.0.0/15`）需设 `ALLOW_PRIVATE_ADDRESSES=true` 才不被拦——**这正是本机 TUN 全局代理的场景**，自建时别复刻这个坑（或要留开关）。

**不必抄 / 过重：**
- 频道**订阅 / 自动检查新上传**（MeTube、yt-dlp-web-ui、ytptube 都有）——本项目是**手动逐集**处理，不需要自动订阅。
- 媒体**播放器 / 库管理 / 元数据索引**（Tube Archivist 那套 ES + 播放器）——与「抓音频喂转写」无关，纯负担。
- yt-dlp **参数三层（全局/预设/单次）**（MeTube 的优雅设计）——本项目其实只要固定 `-f ba`（音频-only）+ cookies，抄这套是过度工程。

**若下游拍板「部署现成」，推荐排序（含理由）：**

| 排名 | 项目 | 理由 | 顾虑 |
|---|---|---|---|
| **① 推荐** | **ytptube** | 一站式满足全部核心需求：**Windows 原生二进制或 Docker**、批量导入、历史、**`ITEM_COMPLETED` webhook 直接串转写**、MIT（抄改无 copyleft 负担）、活跃度最高（访问当天仍在推）、预设可锁「音频-only + cookies」| 存储后端/多 P 行为未逐一实测；`curl-cffi` 指纹伪装**仅 Docker**——若走 Windows 原生跑，绕 412 风控得另靠 cookies/直连（正好是既定网络前提）|
| ② 次选 | **MeTube** | 最流行、最稳、最简；JSON 历史直观；cookies 上传顺手；Docker 一行起 | **无完成 hook**（串链得靠目录监听）；**强制 noplaylist**（多 P 录播默认漏抓，需处理）；AGPL |
| ③ 本用例不推荐 | **yt-dlp-web-ui** | Go 轻量、JSON-RPC 可扩展 | **无 Windows 二进制**、**无完成 webhook**——Windows + 串链两处都最弱，与本项目最不契合 |
| — 排除 | Tube Archivist / tubesync / pinchflat | YouTube 归档器 + 媒体库，过重、非通用下载器 | — |

**Tailscale 内网兼容性**：三者都是绑 `0.0.0.0:PORT` 的 HTTP 服务（MeTube 8081 / yt-dlp-web-ui 3033 / ytptube 8081），**经 Tailscale IP（`100.x.x.x:port`）直接访问即可**，无需反代或额外配置（MeTube 的 `URL_PREFIX` 只在反代子路径时才需要）。全部 Tailscale-friendly，不构成选型差异。

---

## 对 story-machine 的影响

本票研究的是 **spec 阶段 0（转写）之前的「取音频」环节**——目前由 `scripts/dl-audio.ps1`（单链接 CLI）承担，本票是「下载管理前端」grilling 票的前置调研。落到具体：

1. **给 grilling 票的天平**：核心需求窄（历史 + 批量 + 音频-only + cookies + 一个完成钩子）。**建议优先评估「部署 ytptube」作为下载前端基线**——零代码即得全部能力，且其 `ITEM_COMPLETED` webhook 正好接上阶段 0 转写触发。自建只有在「要更深集成（如直接写进转写队列）」时才划算，而那点增量约等于「一个目录监听器 + 一层薄 UI」。
2. **串链机制落点**：无论选谁，**「监听 `E:\asr\audio\` 目录」是最稳的 tool-agnostic 交接点**，因为音频本就落这里。ytptube 额外提供推送式 webhook 作为更省事的上位选项。建议 spec 在阶段 0 前新增一句「取音频环节产物落 `E:\asr\audio\`，下游转写以目录监听或完成 webhook 触发」。
3. **网络前提继承**：任何方案都要处理 **Clash Fake-IP（`198.18.0.0/15`，MeTube 需 `ALLOW_PRIVATE_ADDRESSES=true`，自建别拦）** 与 **B 站 cookies/直连**。`dl-audio.ps1` 已有的 cookies 兜底逻辑（`E:\asr\bili-cookies.txt`）应在前端方案里延续。
4. **多 P 策略要对齐**：`dl-audio.ps1` 现为「多 P 默认全下」；MeTube 强制 noplaylist 会**改变**这一语义（默认只抓第 1 P）。选型/自建时必须显式定义多 P 行为——**spec 目前未规定多 P 下载策略**（列入未决）。
5. **不引入过重方案**：Tube Archivist / tubesync / pinchflat 这类「频道归档 + 媒体库」与本项目「抓音频喂转写」正交，明确排除，避免把 Elasticsearch/媒体服务器拖进来。

---

## 未决问题

（调研中冒出、但超出本票范围，列出供开新票，不在本票内研究掉）

1. **多 P 录播的下载策略**：全下 / 选 P / 每 P 独立入队？spec 未明确，且直接影响选型（MeTube 的 noplaylist 语义）。建议单开票在「取音频环节」定义清楚。
2. **「下载完→自动触发转写」的串链具体实现**：目录监听 vs webhook 监听器 vs 队列信号，属阶段 0 桥接工程，建议在 grilling 票或单独工程票里定。
3. **ytptube 真机验证**：若倾向 ytptube，需在 5070 Windows 上实测：① Windows 原生二进制能否脱离 Docker 跑通 B 站下载（`curl-cffi` 仅 Docker，绕 412 是否只能靠 cookies/直连）；② 历史存储后端（sqlite/json）；③ 多 P 录播行为。
4. **MeTube 多 P 行为的真机确认**：本文对 MeTube 强制 noplaylist → 多 P 只抓第 1 P 是**源码静态分析结论，未跑验证**；若下游倾向 MeTube，需实测一次并确定「多 P 全下」的配置手法。
5. **会员/风控内容下载稳定性**：cookies 时效、412 风控绕过的长期可靠性，属网络层，与前端选型正交。
