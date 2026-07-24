# 多阶段媒体处理 CLI 综述：beets / paperless-ngx / yt-dlp 等对命令形状与状态管理的参考价值

> AFK research 票 [#38](https://github.com/kildren-coder/story-machine/issues/38)，压在 [#5 CLI 技术栈与命令形状](https://github.com/kildren-coder/story-machine/issues/5) 上——具体环节票开工前先查现成参考项目。
> 所有来源链接访问日期：**2026-07-24**。价格/文档随时可变，引用即快照。
> 来源纪律：优先一手（官方文档、GitHub 仓库本体源码、PEP 原文）；仅二手来源处已标注置信度；换算与推断用「据此推断」标出，与来源直述区分。
> **边界**：本票只管 CLI 骨架与状态管理。「人审完之后用什么信号触发下一步」是 [#4](https://github.com/kildren-coder/story-machine/issues/4) 的题；「markdown 模板与字段语法」是 [#7](https://github.com/kildren-coder/story-machine/issues/7) 的题——两者在文末「未决问题/边界」重申，本文不越界研究。

---

## 问题

多阶段媒体处理 CLI 是怎么组织的？beets / paperless-ngx / yt-dlp 等在「①子命令边界、②中间态存放、③断点续跑与幂等、④配置格式、⑤管线中途嵌人工确认、⑥Windows 分发」六件事上的具体做法，哪些可抄哪些不可抄？落到本项目 `transcribe` / `process` 两个子命令的具体形状建议上。

本项目管线有几个不常见的地方，是选参考项目时的盯防点：

- 管线中间**强制停下来等人**（阶段 3 人工核对），不是跑完拉倒；
- **跨机执行**：阶段 0 转写在 5070 主机（Tailscale + SSH），其余在笔记本；
- **每阶段产物都是永久资产**（逐字稿 JSON 正本、`_pairs` 快照、修复差分），不是可丢弃的中间文件；
- 一集要跑几十分钟到几小时，**中途崩溃必须能续**；
- 宿主是 **Windows 11**，5070 主机**未装 Docker**。

---

## 结论（TL;DR）

一句话：**没有任何一个现成项目的整体形状可以照抄，但每个项目都恰好在一个维度上给出了成熟范式——把它们拆开各取一件，比抄任何单一项目都合身。** 本项目的形状 = **beets 的"胖动词 + 置信度分档" + yt-dlp 的"纯文本可读账本 + 临时文件原子改名" + paperless 的"显式任务状态 + 昂贵环节不自动重试" + 一个 beets/yt-dlp/paperless 都没做的"退出-等人-重进"审核闸门**。

逐条落到 `transcribe` / `process` 两个子命令：

1. **子命令边界——抄 beets 的"胖动词"**：一个动词吃下整条管线，单步重跑靠**选择器/flag**（`--stage`、`--chunk`、按集号选），不靠切出一堆细动词。`transcribe` = 阶段 0（跨机），`process` = 阶段 1–5 的文本主链，`process` **可重入**、跑到审核闸门就退出、审核后再跑一次续上。**别把 `process` 切成 chunk/extract/review/merge/factcheck 五个动词让用户记参数**——这正是 beets 用一个 `import` 动词规避掉的坑（§1）。

2. **中间态——抄 yt-dlp/paperless 的"目录约定 + 人类可读侧车"，明确拒抄 beets 的"不透明 sqlite/pickle"**。本项目的硬约束是中间态就在用户 Obsidian vault 里、人要直接看懂和手改——这一条**直接判 beets 的 `library.db`（sqlite）+ `state.pickle`（二进制）出局**。人面向的态用文件（Markdown/JSON），程序面向的进度/幂等账本用一个人平时不碰的小机器文件（JSON，`_index/entities.json` 已是此形）。**关键分层：把"人要编辑的内容态"和"程序记的哪步跑完了"这两种状态分开存**（§2）。

3. **断点续跑与幂等——yt-dlp 的账本形态对，但粒度不够，须加阶段维**。yt-dlp 的 `--download-archive` 是**纯文本、一行一 id、追加式、可 grep 可手改**——工效学范式极好，**但它是整项二值（下过没下过），不记"跑到第几阶段"**。多阶段场景要把账本按 `(集号, 阶段, 块号)` 加键。落地范式：**每阶段产物文件的"存在"即完成标记**（paperless"文件离开 consume 目录=已处理"、whisper 系"`.json` 已存在则跳过"同理）+ 一个显式的**每集小 manifest 账本**兜住文件存在性判不清的情形（半写、第几块）。写文件用 **yt-dlp 的 `.part` 临时文件→成功才改名**范式，杜绝半写文件被误判为完成（跑几小时时至关重要）。真正的**去重风险不在转写、在阶段 4 合并**：重跑同一块的抽取必须是**幂等 upsert**（同一实体不重复追加"来源记录"行），否则崩溃后重进会把源记录写两遍（§3）。

4. **配置——抄 beets 的"共享层 + 机器本地覆盖层"分离**，格式选 **TOML**（Python 原生 `tomllib`，无 YAML 陷阱，与 uv/pyproject 生态同向）。**机器相关配置**（vault 路径、PC 的 Tailscale 名/SSH 目标、`E:\asr\` 路径）与**可共享配置**（分块时长、查证条数上限、模型名）分两处：可共享的进版本库，机器本地的走 `%APPDATA%\story-machine\` + 环境变量（SSH/PC 目标尤其走 env，别落进提交的文件）。这正是 beets 的 `BEETSDIR` / `include:` / `--config` 覆盖范式，和 paperless 的"机器相关=环境变量"范式的合流（§4）。

5. **管线中途等人——明确拒抄 beets 的阻塞式交互提示，本项目的"退出-等人-重进"是对的，且现成项目里没有直接先例**。beets 是**阻塞式 stdin 提示**（`[A]pply/[S]kip/…`），能不拖垮吞吐是因为把"问人"隔离成一个单协程流水线阶段。但 beets 每次决策是**秒级**（确认一张专辑的匹配）；本项目的审核是**重活**（在 Obsidian 里校对 20–30 分钟逐字稿草稿，可能跨越几小时甚至隔天，且在另一个 App 里）——**没法把 CLI 进程挂着等用户喝完咖啡回来**。所以 `_review/` 的"跑到断点就退出、人处理完再敲下一条命令"是**正解**，beets 的阻塞模型在这里不可抄。**可抄的是 beets 的置信度分档**：高置信自动采用、只对低置信问人——这正好映射阶段 2.5「精确命中零 API 自动采用、模糊命中才生成"建议合并"待人点头」。paperless 的审核是**异步旁路**（先自动入库，人事后在 Web UI 改标签），形态最接近但**不设入图闸门**，本项目要的"硬闸门"它没有（§5）。

6. **Windows 分发——用 uv；paperless 的 Docker 全家桶明确出局（5070 无 Docker，且 paperless 本身 Linux-only）**。发行选 **uv**（standalone PowerShell 安装器、自带 Python 供给、`uv tool install` 装 CLI、`uv run` 跑 PEP 723 单文件脚本、`uv self update`），比 Go 单二进制更贴本项目的纯 Python 栈。**两个已吃过的编码坑都有一手来源的定解**：(a) PS 5.1 读无 BOM 中文脚本 parse error → 微软文档确认「无 BOM 时按 ANSI 代码页解读」，定解是 **.ps1 存 UTF-8 带 BOM**（现有脚本已带 BOM，此坑已规避）或改用 pwsh 7+；(b) GBK 管道乱码 → Python 在 Windows 管道默认用 `mbcs`（cp936/GBK），定解是 **`PYTHONUTF8=1`**（UTF-8 模式，PEP 540）。本项目全链在阶段间管 Chinese 文本，CLI 入口应强制 UTF-8 模式；给 `claude -p` 喂大段逐字稿要**走文件路径而非管道**（stdin 有 10MB 上限，且旧版 Claude Code 在 Windows 上读不到 stdin 会静默崩）（§6）。

---

## 论证

四个候选按"各擅一维"排布。下表先给全局定位，后文逐维展开。

| 项目 | 整体形态 | 最值得抄的一件事 | 明确不能抄的一件事 |
|---|---|---|---|
| **beets** | 本地 CLI，音乐库导入 | 胖动词 `import` 吃整条管线 + 置信度分档（高置信自动、低置信问人） | 人面向态存不透明 sqlite/pickle；阻塞式交互确认 |
| **yt-dlp** | 本地 CLI，单命令+海量 flag | 纯文本可读账本 + `.part` 临时文件原子改名 + `.info.json` 侧车可重放 | 整项二值账本当唯一幂等记录（多阶段不够） |
| **paperless-ngx** | 服务/守护进程（Docker+Celery+Redis+DB） | 显式任务状态模型 + 昂贵环节不自动重试 + 双前门→单任务 | Docker/Celery/Redis/Postgres 编排（对单用户 1–2 集/天是重型过度，且 5070 无 Docker） |
| **whisper 系包装器** | 本地 CLI（faster-whisper 本体无 CLI） | 输出落盘约定（input 基名 + `--output_dir` + 词级时间戳 JSON） | 无一支持跨机执行或断点续跑——本项目须自造 |

---

### 1. 子命令边界

**beets：10 个核心动词，一个 `import` 吃下整条多阶段导入管线。** 命令参考页列出的核心动词是 `import` / `list` / `remove` / `modify` / `move` / `update` / `write` / `stats` / `fields` / `config`（[beets CLI 参考](https://beets.readthedocs.io/en/stable/reference/cli.html)，2026-07-24）。动词切分的原则很清晰：

- **摄取/打标签（`import`）与事后操作分离**：`import` 一个动词独占"读文件→MusicBrainz 查候选→人工确认→改标签/搬文件"整条流水线；`modify`（改库中元数据）/`update`（文件标签→库）/`write`（库→文件标签）/`list`（查询）是**摄取之后**在已持久化的库上做的独立动词。库↔文件双向同步被显式拆成 `write`（库→标签）和 `update`（标签→库）两个动词。
- **"单步重跑"靠选择器，不靠细动词**：beets 规避"切太细"用一个胖 `import`；规避"切太粗没法单步重跑"用**按 query 重导**（`import -L QUERY` 对已入库项按查询重跑）+ `modify`/`update`/`write` 这些可对任意 query 单独施加的后置动词。即：重跑的粒度来自**在持久化库上做查询选择**，不是来自一堆颗粒动词（据 CLI 参考页 + [config 参考](https://beets.readthedocs.io/en/stable/reference/config.html)，2026-07-24）。

**yt-dlp：一个 `yt-dlp URL` 干所有事，行为全靠 flag 雕。** 没有子命令树，`--download-archive`/`--continue`/`--write-info-json` 等 flag 决定形状（[yt-dlp README](https://github.com/yt-dlp/yt-dlp)，2026-07-24）。

**paperless-ngx：面向用户根本没有"子命令管线"——它是守护进程。** consume→OCR→index 是**服务**跑的异步任务，不是 CLI 动词；面向人的只有 Web UI，运维命令是 Django management command（[paperless usage 文档](https://docs.paperless-ngx.com/usage/)，2026-07-24）。这条对本项目的启示是**反面的**：把管线做成常驻服务对单用户 1–2 集/天是重型过度（详见 §6）。

> **对本项目（据此推断）**：`transcribe`/`process` 两动词的两分已定，恰合 beets 的胖动词范式——`transcribe`=阶段 0（跨机），`process`=阶段 1–5 文本主链。关键决策落在**`process` 内部不要再切成 chunk/extract/review/merge/factcheck 五个动词**，否则每步都要用户记参数（正是 beets 用单 `import` 规避的坑）。单步重跑（如"只重抽 EP12 的第 3 块"）应是 `process` 上的**选择器/flag**（如 `process EP12 --redo-chunk 3`），映射 beets 的"按 query 重跑"而非颗粒动词。因阶段 3 是硬人工闸门，`process` 天然要么"跑到 `_review/` 就退出"、要么"检测到审核完成再续"——这使 `process` 必须**可重入**（详见 §5）。

---

### 2. 中间态存哪

四个项目的中间态存法，按"人能否直接看懂/手改"这个本项目硬约束排：

| 项目 | 内容态（元数据/结果） | 进度/续跑态 | 人可直接读改？ |
|---|---|---|---|
| **beets** | `library.db`（**SQLite**，可查询元数据索引） | **`state.pickle`（Python pickle 二进制）** | **否**——设计上走 `list`/`modify` 访问，不手改 sqlite |
| **paperless** | DB 中 `Document` 行 + `PaperlessTask` 行 | 同 DB（任务表） | 经 Web UI/Tasks 视图看，不手改 DB |
| **yt-dlp** | `.info.json` 侧车（每项全量元数据） | `--download-archive` 纯文本 + `.part`/`.ytdl` | **是**——archive 是纯文本可 grep 可手改 |
| **本项目** | `_review/*.md` 草稿、`_pairs/` 快照、`EP{n}.json` 正本、`repairs.json` | （待定，本文建议） | **强制是**——就在 vault 里，人直接校对 |

**关键事实：beets 用了两个不透明存储，且续跑态不是 sqlite。** 库元数据在 SQLite `library.db`；但**断点续跑/增量的状态在一个独立的 `state.pickle`**（默认 `statefile: state.pickle`，源码 `beets/importer/state.py` 从 `config["statefile"]` 载入，`beets/config_default.yaml`，2026-07-24）。两者都不是给人手改的——beets 文档把用户导向 `modify`/`list` 命令，`library.db` 的官方定位是"最小 ORM 支撑的可查询索引"（[beets 库 API 文档](https://beets.readthedocs.io/en/stable/dev/library.html)，2026-07-24）。

**paperless 同理，态在 DB，人只经 UI 看**：`Document` 行（带 `checksum`/`archive_checksum`）+ `PaperlessTask` 行是持久记录，经 Tasks 视图与 `/api/tasks/` 可见，不手改（源码 `src/documents/models.py`，2026-07-24）。

**yt-dlp 是唯一"人可直接读改"派**：archive 文件是纯 UTF-8 文本、一行一条 `<extractor> <id>`（如 `youtube dQw4w9WgXcQ`），读入内存是个 set、写是追加，人可 grep、手删行强制重下（[yt-dlp README](https://github.com/yt-dlp/yt-dlp) + 源码 `preload_download_archive`；一行一 id 的实例见 [neilzone 博客](https://neilzone.co.uk/2026/01/yt-dlps-download-archive-flag/)，二手佐证，中高置信，2026-07-24）。

> **对本项目（据此推断）**：本项目的中间态在 Obsidian vault 里、人直接校对——**这条硬约束直接判 beets 的 sqlite+pickle 与 paperless 的 DB 出局**（人面向态不能是不透明存储）。正确范式是 yt-dlp/paperless-consume 的**目录约定 + 人类可读侧车文件**：spec 已经在这么做（`_review/EP{n}_draft.md`、`_pairs/`、`EP{n}.repairs.json`、`_index/entities.json`）。**要新增的分层认识**（beets 教训）：把**人要编辑的内容态**（草稿/审核，Markdown）和**程序记的"哪步跑完了"进度态**（JSON/小账本）**分开**——别逼用户在 vault 图谱里看见"第几块跑完了"这种簿记。`entities.json` 已是"程序读写、非面向人"的正确形；进度账本应同类（一个人平时不碰的小 JSON，或藏在 `_index/` 下），而非塞进审核动线。

---

### 3. 断点续跑与幂等

**beets 把"续跑"和"去重"当两个正交问题分开解**，这是最重要的一条认识（源码 `beets/importer/state.py`、`tasks.py`，2026-07-24）：

- **续跑（resume）**：`state.pickle` 里 `tagprogress` = `{顶层路径: [已处理子目录…]}`。崩溃后 `--resume`（默认 `resume: ask`）查这张表、在同一顶层路径上跳过已处理子目录续跑。**按 query 导入时禁用续跑**（"never save progress or try to resume"）。
- **增量（incremental）**：`taghistory` = 已导入过的目录集合；`import -i` 重跑时命中即"Skipping previously-imported path"跳过。粒度是**目录**（路径级）。
- **去重（duplicate detection）**：与前两者正交，是**内容/元数据查询**——`ImportTask.find_duplicates` 按 `duplicate_keys`（专辑默认 albumartist+album）查 `library.db`，命中按 `duplicate_action`（`skip`/`keep`/`remove`/`merge`/`ask`，默认 `ask`）处置。

即 beets 有三层：resume=按子目录的批内进度（在 pickle）；incremental=见过的目录集合（在 pickle）；dedup=按内容查库（在 sqlite）。

**paperless：昂贵环节故意不自动重试，失败靠状态可见性兜底。** 核心 OCR/consume 任务 `consume_file` 声明为 `@shared_task(bind=True)`、**无** `autoretry_for`/`max_retries`——异常被捕获、记录、重抛，**不触发 Celery 重试**（源码 `src/documents/tasks.py`，2026-07-24；对比 `index_document` 反而设了 `max_retries=5`）。失败落 `FAILURE` 态、文件留在 consume 目录（负信号），重处理靠人重投。任务状态是显式枚举 `pending`/`started`/`success`/`failure`/`revoked`（`PaperlessTask.Status`，终态集 `SUCCESS/FAILURE/REVOKED`），经 Tasks 视图可见（源码 `src/documents/models.py`；[troubleshooting 文档](https://docs.paperless-ngx.com/troubleshooting/)，2026-07-24）。幂等键是文件 SHA-256 校验和——但**注意反直觉发现**：当前 `main` 分支**默认不拒重复**，只 log 警告并再消费一份，须 `PAPERLESS_CONSUMER_DELETE_DUPLICATES=true` 才拒（源码 `src/documents/consumer.py`；`checksum` 列 `db_index=True` 但**非** `unique`，2026-07-24）。即 paperless 的教训是**"内容校验和当身份键"这个范式对，但"是否据此拒重"要显式开、别指望默认**。

**yt-dlp：两个专用存储——durable 二值账本 + ephemeral 续传文件。**（源码 `yt_dlp/downloader/http.py`、`fragment.py`，[README](https://github.com/yt-dlp/yt-dlp)，2026-07-24）

- **账本（哪些项已完成）**：`--download-archive FILE` 记 id、重跑跳过；`--break-on-existing` 遇到账本里已有项就停整轮。**追加式、纯文本、成功才写一行**。
- **续传（单项传到一半）**：下载写进 `<名>.part`，**成功才 `try_rename` 成最终名**——`.part` 存在=下载不完整。非分片文件靠 `.part` 自身字节长度做 `Range: bytes=N-` 续传（"文件自身长度即续传态"）；分片下载写 `.ytdl` JSON 记 `current_fragment` 续传。
- **可重放侧车**：`--write-info-json` 写每项 `.info.json`（全量元数据）；`--load-info-json FILE` 可**从存档的 info.json 重跑下载/后处理而不重打 extractor/不重访网站**——"每阶段产物即可重放输入"的成熟一等公民（继承自 youtube-dl）。局限（据此推断）：info.json 里的媒体 URL 常带时效签名会过期，纯后处理重放最稳。

**yt-dlp 的 archive 式方案在多阶段场景够不够用？——工效学够好，粒度不够。**（据此推断，综合上文）archive 刻意是**整项二值账本**：一行=这项完成过一次，**不记哪个阶段完成**。它连"下了但还没后处理"都不表达——跨阶段进度被拆到**另外**的 `.part`/`.ytdl`（且是每次传输、临时、完成即删）。所以 yt-dlp 实际用了**两个专用存储**：durable 二值账本 + ephemeral 续传文件。对"每阶段产永久资产、要在阶段边界续跑"的本项目，archive 的**工效学（纯文本/追加/可手改/set 判存）该抄**，但**须补上它缺的阶段维**——把账本按 `(项, 阶段[, 块])` 加键。

**whisper 系包装器：转写对单文件是原子的，无一支持文件内续跑或跳过。**（各 README，2026-07-24）whisperX/insanely-fast-whisper/whisper-ctranslate2/subsai 均无 resume/checkpoint/skip-if-exists 文档；崩了=整文件重来。faster-whisper 本体的 `segments` 是**生成器/流式**接口（技术上你自己的代码可边产边存段落做 checkpoint），但库本身不提供、CLI 包装器都是缓冲到完成才落盘（[faster-whisper README](https://github.com/SYSTRAN/faster-whisper)、[whisper-ctranslate2](https://github.com/Softcatala/whisper-ctranslate2)，2026-07-24）。

> **对本项目（据此推断）**：一集跑几十分钟到几小时、中途崩要续——**答案是 stage-keyed 完成模型**：
> 1. **每阶段产物文件的"存在"即完成标记**（`EP{n}.json` 正本存在→转写完；`_pairs/EP{n}/chunk{k}_pre.md` 存在→该块草稿已出；`repairs.json`/`glossary.json` 同理）。这与 paperless"文件离开 consume 目录=已处理"、whisper 系"输出 `.json` 已存在则跳过"是同一范式。
> 2. **原子写**：抄 yt-dlp 的 `.part`→成功才改名——写 `EP{n}.json.part` / `chunk{k}.md.tmp`，落盘完整才 `rename` 成最终名。跑几小时时这条杜绝"半写文件被当完成"，是硬需求。
> 3. **块级粒度**：修复 pass 与抽取已是 20–30 分钟块**顺序**处理、带滚动词表（spec 阶段 0/1）——续跑就该**按块**续（如 beets 按子目录续），账本记到 `(集号, 阶段, 块号)`。
> 4. **显式小 manifest 兜底**：文件存在性判不清（半写残留、某块跑没跑）时，一个每集 `EP{n}.manifest.json`（记各阶段/各块完成 + 参数快照）当权威——这是 yt-dlp"account + 续传两个存储"的本项目版：产物文件当续传态，manifest 当 durable 账本。
> 5. **真正的去重风险在阶段 4 合并，不在转写**：实体去重已由 `entities.json`（阶段 2.5/4）管；重跑同一块的抽取应**覆盖**其草稿而非追加。**阶段 4 的合并必须幂等**——重跑同一块不得给同一实体重复追加"来源记录"行。崩溃后重进最容易在这里写重（对应 paperless"默认不拒重复"的坑）：manifest 里记一个"哪些 `(集,块)` 已合并入图"的账本，重进跳过已合并块。**yt-dlp 的 archive 在多阶段不够用的答案：形态抄、按阶段加键、合并做幂等 upsert。**

---

### 4. 配置

| 项目 | 格式 | 位置 | 机器相关 vs 可共享的分离 |
|---|---|---|---|
| **beets** | YAML（`config.yaml`） | Linux `~/.config/beets/`；**Windows `%APPDATA%\beets\`**；`BEETSDIR` 覆盖 | `directory`/`library`/`statefile` 是机器相关路径；`include:` 叠加、`--config FILE` 叠加、`BEETSDIR` 整体重定位 |
| **paperless** | 环境变量 `PAPERLESS_*`（可从 `paperless.conf`/`docker-compose.env` 载） | `PAPERLESS_CONFIGURATION_PATH` → `/path/paperless.conf` → `/etc/…`，首个命中 | 机器相关（密钥、DB creds、`PAPERLESS_REDIS`、主机路径）就是环境变量，无独立 secrets vault |
| **yt-dlp** | 命令行 flag 逐行写文件（`#` 注释） | portable（二进制旁）→ home（`-P`）→ user（`%APPDATA%\yt-dlp\config`）→ system，逐层叠加 | 无专门分离，靠多层配置文件叠加 |

一手细节：

- **beets**：YAML 语法；Windows 默认 `%APPDATA%\beets\config.yaml`；`BEETSDIR` 环境变量"替换默认位置的配置，并影响库数据库等辅助文件的默认存放位置"；`include:` = "相对 config.yaml 目录的额外配置文件列表"（叠加）；`--config FILE` = "与现有选项合并……大部分配置不变、批量改几项"（[config 参考](https://beets.readthedocs.io/en/stable/reference/config.html)，2026-07-24）。机器相关的 `directory`/`library`/`statefile` 默认都相对 config 目录。
- **paperless**：`PAPERLESS_*` 环境变量，Docker 下 `paperless.conf` 不用、改写 `docker-compose.env`；UI 里设的选项优先级高于环境变量（[configuration 文档](https://docs.paperless-ngx.com/configuration/)，2026-07-24）。
- **yt-dlp**：配置文件里就是命令行同款开关（`-`/`--` 后不得有空格），`#` 开头是注释，一行一选项（[README CONFIGURATION](https://github.com/yt-dlp/yt-dlp)，2026-07-24）。

> **对本项目（据此推断）**：本项目的具体需求是把**机器相关配置**（vault 路径、PC 的 Tailscale 名/SSH 目标、`E:\asr\audio\` 及 `bili-cookies.txt` 路径——现有 `dl-audio.ps1`/`setup-5070-pc.ps1` 里正硬编码着这些）与**可共享配置**（分块时长、重叠、每集查证条数上限、模型名）分开。
> - **格式选 TOML**：Python 3.11+ 原生 `tomllib`、类型明确、无 YAML 的隐式类型/缩进陷阱，且与 uv/`pyproject.toml` 生态同向。（beets 用 YAML 是历史包袱，不必跟。）
> - **两层分离**（合流 beets 的 `include:`/`--config` 与 paperless 的"机器相关=env"）：可共享层进版本库（如 `story-machine.toml`），机器本地层放 `%APPDATA%\story-machine\config.toml`（gitignored），后者覆盖前者；**SSH/PC 目标、vault 绝对路径优先走环境变量**，绝不落进任何会提交的文件。
> - 位置对齐 beets 的 Windows 惯例：用户级 `%APPDATA%\story-machine\`，加一个可选的项目目录配置和一个 env 覆盖入口。

---

### 5. 管线中途等人

**beets：阻塞式 stdin 交互提示，靠流水线阶段隔离不拖垮吞吐。**（[tagger 指南](https://beets.readthedocs.io/en/stable/guides/tagger.html)、源码 `beets/util/pipeline.py`、`beets/importer/stages.py`，2026-07-24）

- 提示原文：**`[A]pply, More candidates, Skip, Use as-is, as Tracks, Enter search, enter Id, or aBort?`**——A 应用 / M 更多候选 / S 跳过 / U 原样导入 / T 当单曲 / E 输入搜索 / I 输入 ID / B 中止。
- **置信度分档**：高相似度自动应用（"因找到相似度 98.4% 的选项而自动继续"），低置信才"请你确认"。
- **架构**：beets 用生成器/协程流水线，可单线程或"每阶段一线程"并行跑。确认阶段 `user_query` 是**单协程阶段**（故一次处理一张专辑、串行问人），而上游 `lookup_candidates`（网络 I/O）可在为下一张取候选、下游 `manipulate_files`（磁盘 I/O）可在为上一张搬文件——经典**流水线并行**。"等人不拖垮吞吐"是**单协程阶段 + 队列背压的涌现性质**，不是专门的交互串行化代码。
- **非交互/谨慎模式**：`-q`/`--quiet`（"从不提示，保守跳过"）、`-t`/`--timid`（"什么都问你，连很好的匹配也确认"）、`--pretend`（干跑预览）、`-A`/`--noautotag`（原样批量导入）。

**paperless：不在管线中途停下等人——审核是异步旁路。** consume→OCR→index 全自动跑完、文档直接入库并索引；人对标签/correspondent 的更正是**事后**在 Web UI 做的，**不设"入库前的闸门"**（[usage 文档](https://docs.paperless-ngx.com/usage/)，2026-07-24）。形态上最接近本项目"人在另一个 UI 里事后审"，但**缺本项目要的硬闸门**（草稿必须先过 `_review/` 才进图）。

**yt-dlp：无人工介入环节。** 纯自动下载。

> **对本项目（据此推断）**：
> - **beets 的阻塞式提示在本项目不可抄，原因是决策时长量级不同**。beets 每次决策是**秒级**（确认一张专辑匹配），本项目的阶段 3 是**重活**——在 Obsidian 里逐字校对 20–30 分钟逐字稿草稿、点头/摇头"建议合并"、打存疑标记，可能耗时几十分钟、跨越几小时甚至隔天，且在**另一个 App**（Obsidian，非终端）里完成。把 CLI 进程阻塞挂着等这种审核既不现实也脆弱。**"跑到断点就退出、人处理完再敲下一条命令"（`_review/` 形态）是正解。**
> - **现成项目里没有"退出-等人-重进"的一等 CLI 先例**——beets 是阻塞提示，paperless 是异步旁路无闸门，yt-dlp 无介入。本项目这个形状是**它这条管线独有的**（人工闸门 + 硬续跑），自己显式设计是对的、不必削足适履去套谁。
> - **可抄的是 beets 的两件**：(1) **置信度分档**——高置信自动、低置信才问人，直接映射阶段 2.5「精确名/别名机械归一化命中→零 API 自动采用；模糊命中→Gemini 生成"建议合并"待人裁」，beets 的 98% 自动线是现成先例；(2) **非交互/干跑模式**——给 `process` 配 `--pretend`（预览要写哪些草稿不落盘）和"审核完成信号缺失时保守退出"的 quiet 语义。
> - **CLI 形状含义**：`process` 必须**可重入 / 可续**，能检测"审核完成"态并做对下一步。**"用什么信号判定审核完成"是 #4 的题，本文只确认 `process` 的骨架必须支持这种重进**（信号语义留 #4）。

---

### 6. Windows 分发

**paperless 的编排范式对本项目直接出局。** paperless 主发行是 **Docker Compose**（Redis/Valkey broker + DB + 可选 Gotenberg/Tika + webserver 内含 gunicorn+Celery worker+beat），且**官方明说"Paperless 只跑 Linux，不支持 Windows"**——Windows 上只能 Docker Desktop 或 WSL2（一个 Linux 环境）（[setup 文档](https://docs.paperless-ngx.com/setup/)，2026-07-24）。**本项目 5070 主机未装 Docker**，且是单用户 1–2 集/天——Celery+Redis+Postgres 全套编排是重型过度。这反证了 spec 的选择：阶段 0 用 **SSH 触发脚本**（非常驻服务）、阶段 1–5 用**笔记本本地顺序管线**，是右尺寸的。

**发行形态对比（Windows 11 视角）：**

| 方案 | 目标机需运行时？ | Windows 安装 | 隔离 | 自更新 |
|---|---|---|---|---|
| **uv tool / uvx** | 仅 uv 二进制（可自供 Python） | `irm https://astral.sh/uv/install.ps1 \| iex`，再 `uv tool install X` | 每工具一 venv，shim 上 PATH | `uv self update`（仅 standalone 装法） |
| **uv run + PEP 723** | 仅 uv 二进制 | 同上，再 `uv run script.py` | 每次运行按内联依赖建临时环境 | 脚本即真相；uv 自更新 |
| **pipx** | Python + pipx | `scoop install pipx` / `py -m pip install --user pipx` | 每 app 一 venv | `pipx upgrade[-all]` |
| **Go 单静态二进制** | **无**（自包含 .exe） | `scoop install X` 或直接下 .exe | 单二进制 | 重下 或 selfupdate 类库（据此推断） |

一手细节（[uv 安装](https://docs.astral.sh/uv/getting-started/installation/)、[uv tools](https://docs.astral.sh/uv/guides/tools/)、[uv scripts](https://docs.astral.sh/uv/guides/scripts/)、[PEP 723](https://peps.python.org/pep-0723/)，2026-07-24）：

- **uv** 是 standalone 二进制、**不需预装 Python**（还能 `uv python install` 自供 Python）；`uvx` = `uv tool run`（临时跑）、`uv tool install` 持久装 CLI 并把可执行放进 PATH；`uv self update` 重跑安装器自更新（仅 standalone 装法）。
- **PEP 723 内联脚本元数据**（状态 **Final**，2024-01-08）：单文件里写 `# /// script` … `dependencies = [...]` … `# ///`，`uv run script.py` **自动按内联依赖建临时隔离环境**跑，无需 `pyproject.toml` 脚手架。runner 支持：uv、`pipx run`、hatch。这是"声明依赖的单文件脚本、零项目脚手架"最成熟的形态。

**两个已吃过的编码坑——一手来源的定解：**

- **(a) PS 5.1 读无 BOM 中文脚本 parse error**：微软文档明写"无 BOM 时 Windows PowerShell 把脚本误判为 legacy 'ANSI' 代码页……ANSI 也是 PowerShell 引擎读源码时用的编码"——即**解析器本身**在无 BOM 时假设 ANSI，故 UTF-8-无-BOM 的含中文 `.ps1` 触发 parse error。定解："若脚本要用非 ASCII 字符，存为 **UTF-8 带 BOM**"；PowerShell 6/7+（`pwsh`）默认 UTF-8、无此问题（[about_Character_Encoding](https://learn.microsoft.com/en-us/powershell/module/microsoft.powershell.core/about/about_character_encoding)，2026-07-24）。**注：本项目现有 `dl-audio.ps1`/`setup-5070-pc.ps1` 文件头已带 BOM（`﻿`），此坑已规避**——建议把"含中文 .ps1 一律 UTF-8 带 BOM，或统一迁 pwsh 7+"写成硬约定。
- **(b) GBK/cp936 管道乱码**：PEP 540 明写"Windows 上若 stdin/stdout 重定向到**管道**，`sys.stdin`/`sys.stdout` 默认用 **`mbcs` 编码**而非 UTF-8"——`mbcs` = 系统 ANSI 代码页（简中 Windows 上是 cp936/GBK），非 ASCII 字节被误解=乱码（交互控制台已是 UTF-8，坑专在**管道**咬人，正合本项目所报）。定解：开 **UTF-8 模式** `PYTHONUTF8=1`（或 `-X utf8`）——"UTF-8 模式下 stdin/stdout 恒用 UTF-8"；亦可 `PYTHONIOENCODING=utf-8` 或 `chcp 65001`（[PEP 540](https://peps.python.org/pep-0540/)、[Python Windows 文档](https://docs.python.org/3/using/windows.html)、[cmdline 文档](https://docs.python.org/3/using/cmdline.html)，2026-07-24）。

**LLM 无头调用编进 CLI 管线：`claude -p` 是文档化的受支持范式。**（[Claude Code headless 文档](https://code.claude.com/docs/en/headless)，2026-07-24）`-p`/`--print` 非交互跑、**读 stdin 像 Unix 过滤器**（`cat build-error.txt | claude -p '...' > output.txt`）、`--output-format text|json|stream-json`、`--json-schema '{...}'` 约束结构化输出（结果落 `.structured_output`）、`--bare` 跳过 hooks/MCP/CLAUDE.md 自发现以求可复现（"将成为 `-p` 的默认"）、`--allowedTools`/`--permission-mode dontAsk|acceptEdits` 免交互授权。**Windows 相关注意**：stdin 上限 10MB（超限报错），且"v2.1.211 前 Windows 上读不到 stdin 会崩溃或静默无输出退出"——**给 `claude -p` 喂大段逐字稿应走文件路径引用而非管道**，并确保较新的 Claude Code 版本。

> **对本项目（据此推断）**：
> - **发行选 uv**：standalone PowerShell 安装器、自供 Python、`uv tool install` 装 CLI、`uv self update`；**PEP 723 单文件脚本**正好承接"哪些环节是脚本"——把机械步骤写成自带内联依赖的 `.py`、`uv run` 直跑、零 venv 脚手架，与"哪些环节是 Claude Code 会话"清晰两分。Go 单二进制的零运行时诱人，但全栈是 Python（faster-whisper、分块、Gemini/Claude SDK），uv 是务实选择。
> - **编码硬约定**：含中文 `.ps1` 一律 **UTF-8 带 BOM**（现状已合规，写成规矩）；Python CLI 入口**强制 `PYTHONUTF8=1`**，子进程管道显式 `encoding='utf-8'`——全链在阶段间管中文，这条不设就是定时炸弹。
> - **`claude -p`**（呼应 [#36](https://github.com/kildren-coder/story-machine/issues/36)）：阶段 4 的合并/查证走 `claude -p --output-format json`，逐字稿**以文件路径喂入**（避开 10MB 管道上限与 Windows stdin 崩溃史），`--bare` 求 AFK 夜跑可复现。

---

## 对 story-machine 的影响

落到 spec 的具体章节与 #5 CLI 形状决策：

1. **spec §总体架构 / #5 CLI 命令形状**：确认 `transcribe`/`process` 两个**胖动词**（beets 范式，§1）——`transcribe`=阶段 0 跨机，`process`=阶段 1–5 文本主链。**明确写入"不把 `process` 切成 chunk/extract/merge 等细动词"**；单步重跑走**选择器/flag**（`process EP{n} --stage extract --chunk k` 之类），映射 beets"按 query 重跑"。`process` 声明为**可重入 / 可续**。

2. **spec 新增「状态管理」小节**（本票核心产出，§2+§3）：
   - **人面向内容态**（草稿/审核/正本）用**人类可读文件**（Markdown/JSON），**明确拒绝 sqlite/pickle**（beets 出局理由：vault 里人要直接看改）；
   - **程序面向进度态**用一个人平时不碰的**每集 `EP{n}.manifest.json`**（记各阶段/各块完成 + 参数快照），与 `entities.json` 同类归 `_index/`；
   - **完成判定 = 每阶段产物文件"存在"**（paperless/whisper 范式）+ manifest 兜底；
   - **原子写 = 临时文件→成功才 rename**（yt-dlp `.part` 范式），跑几小时防半写误判；
   - 续跑**粒度到块**（阶段 0 修复 pass / 阶段 2 抽取本就按块顺序处理）。

3. **spec §阶段 4 合并**：补一条**幂等约束**——重跑同一 `(集, 块)` 的合并不得对同一实体重复追加"来源记录"行；manifest 记"已合并入图的块"以便崩溃后重进跳过。这是本项目真正的去重风险点（对应 paperless"默认不拒重复"坑，§3）。

4. **spec §阶段 2.5 / §阶段 3**：确认**置信度分档**有 beets 先例（§5）——精确/机械归一化命中自动采用、模糊命中才生成"建议合并"待人裁，对应 beets 高置信自动应用（98% 线）/低置信问人。**审核闸门确认走"退出-等人-重进"而非阻塞提示**，理由入 spec：本项目审核是重活/跨 App/可跨小时，beets 的秒级阻塞模型不适用。（"审核完成信号"留 #4。）

5. **spec §配置（新增 / #5）**：格式 **TOML**；**两层分离**——可共享层（分块时长、查证上限、模型名）进库，机器本地层（vault 路径、PC/Tailscale/SSH 目标、`E:\asr\` 路径）走 `%APPDATA%\story-machine\` + **环境变量**（SSH/PC 目标尤其走 env），范式合流 beets `include:`/`--config` 与 paperless"机器相关=env"（§4）。把现有 `.ps1` 里硬编码的机器路径外化到此。

6. **spec §Windows / 分发（新增）**：发行用 **uv**（`uv tool install` 装 CLI、`uv run` 跑 PEP 723 单文件脚本承接"脚本环节"）；编码硬约定——含中文 `.ps1` UTF-8 带 BOM（现状已合规）、Python CLI 入口 `PYTHONUTF8=1`；`claude -p` 喂逐字稿**走文件路径不走管道**（§6）。

7. **spec §阶段 0**：`transcribe` 子命令的 flag 面参照 **whisper-ctranslate2**（faster-whisper 的第三方 CLI；faster-whisper 本体无 CLI）——`--model`/`--output_dir`/`--output_format`/`--compute_type`/`--vad_filter`/`--batched --batch_size`/`--hf_token`；输出落盘约定 = input 基名 + `--output_dir` + 词级时间戳 JSON，正合 spec 的 `EP{n}.json` 正本。**跨机执行须自造**——whisper 系无一支持远程/客户端-服务端/断点续跑（§论证），确认 spec 的 SSH+scp 自造桥接无现成可抄、方向正确；阶段 0 续跑粒度为**整文件**（JSON 正本即完成标记，转写在所有包装器里都是文件级原子），可续跑的贵活在**文本主链的块级**、不在 ASR。

---

## 未决问题 / 边界

（调研中冒出或明确划归他票者，供开新票；不在本票研究掉）

- **「审核完成」用什么信号触发下一步**：明确是 [#4](https://github.com/kildren-coder/story-machine/issues/4) 的题。本票只定 `process` 骨架须支持"退出-等人-重进"，信号语义（改文件名/加 frontmatter/CLI flag）留 #4。两票在 beets 的交集：本票看它的**管线与状态**，#4 看它的**确认语义**。
- **markdown 模板与字段语法**：归 [#7](https://github.com/kildren-coder/story-machine/issues/7)，本票不碰 `_review/` 草稿与正式笔记的字段结构。
- **TOML vs 就用「env + CLI flag、不设配置文件」**：单用户低吞吐工具，是否需要配置文件本身、还是机器相关全走 env 足矣——本票建议 TOML 两层，但"MVP 要不要文件"可留一个轻量决策点（偏工程，非本票事实调查范围）。
- **uv 的 Python 供给与 5070 CUDA 栈的相容性**：5070 是 Blackwell、需 CUDA 12.8+ 的特定 PyTorch/CTranslate2 构建（spec 阶段 0）；uv `python install` 供的 Python 与这套 GPU 栈能否顺跑是**实机工程未知**，本票只做案头分发对比，不做实机验证——若走 uv 供 Python 路线须单独实测（属工程票）。
- **manifest 账本 vs 直接用 sqlite**：本票建议每集 JSON manifest（人可读、与 vault 文件同级）。若集数攒大到几百集、跨集查询"哪些集处理到哪"成为高频操作，是否上一个程序私有 sqlite（如 beets）值得实跑后再判——非 MVP 问题。
- **批处理队列模式**（spec §9 开放问题）：自动按每天 1–2 集消化积压，涉及触发编排，与 #4 相邻；本票只定单集 `process` 的可重入骨架，队列编排另议。
- **Go 重写换零运行时分发**：本票因纯 Python 栈判 uv 优先、Go 出局；若未来把管线核心收敛成少量无 Python 依赖的胶水，可重议——非当前问题。
