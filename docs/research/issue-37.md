# 人工审核确认信号的现成做法综述：Decap CMS / paperless-ngx / Obsidian 原生等对 _review 触发机制的参考价值

> AFK 调研票 [#37](https://github.com/kildren-coder/story-machine/issues/37)，压在 [#4 `_review` 确认信号机制](https://github.com/kildren-coder/story-machine/issues/4) 上。本文只回答票面 Question，不拍板 CLI 命令形状/配置/断点续跑（那是 [#5](https://github.com/kildren-coder/story-machine/issues/5) 的地界）；给 #4 的 HITL 会话供弹药。
> 来源访问日期 **2026-07-23 至 07-24**。文中区分「来源直接写明」（事实）与「据此推断/换算」（推断）。

## 问题

阶段 3 是本流水线不可省略的人工质量闸门（spec 第 7 节硬原则「人工核对是质量闸门，不是可选项」）：用户在 Obsidian 里打开 `Vault/_review/EP{n}_draft.md` 校对（改实体名、删幻觉条目、对存疑打 `?`、对阶段 2.5 的「建议合并」点头摇头），改完需要一个信号触发阶段 4（合并、消歧、事实核查、写正式笔记）。**这个信号一旦误触发，未审核的草稿会直接进入正式笔记网络——所以误触发抵抗力是首要指标，不是易用性。** 同时触发时刻就是快照时刻（写 `_pairs/EP{n}/chunk{k}_post.md` 只读留档），机制必须能明确定位「就是这一刻的文件内容」。

要回答：

1. **四种机制的取舍**——frontmatter 字段 / 文件名 / 目录移动 / 显式 CLI 命令，各自在①**误触发抵抗力**②**部分完成的表达能力**③**幂等与重放**三维度上，现成项目踩过哪些坑、怎么解的。
2. **目录监听的竞态**——若走目录移动/文件监听，Obsidian 的写盘行为会不会导致读到半截文件？现成项目用什么办法确认「文件已稳定」。
3. **Obsidian 特有约束**——`_review/` 里的文件被索引，frontmatter 进 Properties UI、文件名改动连带改双链。哪种机制与 Obsidian 默认行为冲突最小？（MVP 不开发插件，只定约定 + 外部脚本。）
4. **能抄什么/不能抄什么**——带推荐的对比结论，供 #4 拍板。

---

## 结论（TL;DR）

**四种机制里没有单独一种同时满足「误触发抵抗力第一 + Obsidian 原生 + 无竞态 + 能表达部分完成」。现成项目里同构度最高的 Decap CMS 给出的答案是把两件事拆开：状态放在人好改的地方（frontmatter），但真正推进流水线的是一个显式的、不会被手滑/模板默认值触发的动作。据此推荐 story-machine 抄这个「双层」结构：**

- **人面的信号 = frontmatter 布尔字段**（Obsidian 原生 `checkbox` property，如 `reviewed: true`）。它是四选项里唯一同时满足「Obsidian 原生渲染成真复选框、移动端可点、跨设备按内容编辑同步（不改文件名、无双链副作用）、Bases 可直接筛出」的表示法（论证 §3）。草稿模板把默认值播成 `reviewed: false`——这是 Hugo 的关键教训：**安全默认值是「未通过」，「通过」必须是一次显式的正向翻转**（论证 §1.1）。
- **推进流水线 = 一条显式 CLI 命令**（形状归 #5，本票只认定「信号本身该是显式命令」）。人校对完、存盘后手动跑它，命令做三件事：①**读 `reviewed: true` 当前置条件**，为 false 就拒绝推进——双重闸门；②**在这一刻读文件存 `chunk{k}_post.md` 快照**——人是存盘后才敲命令，文件处于静止态，无监听竞态、无半截文件（论证 §2）；③推进后把草稿移出 `_review/`（或盖 `processed` 戳），实现单发幂等（论证 §1.3）。

**为什么这么分而不是四选一：**

- **误触发抵抗力**：显式命令最高（正向意图、与编辑动作解耦、模板默认值和批量操作都触发不了它）——这正是 Decap「Approve and publish」是显式点击而非自动合并的道理（§1.1）。frontmatter 单字段翻转太轻、易被模板默认值/批量脚本误设，**故不能让它单独当闸门**，只当命令的前置条件。
- **目录移动 / 文件监听**当闸门**不推荐**：Obsidian 的写盘是否原子**官方无任何文档保证**（一则「外部工具读到截断文件」的报告被 Obsidian 开发者当场反驳、但也未被证伪为安全，§2），叠加移动端同步把移动/改名当「删+建」易起冲突（§3），对一个「误触发是头号恐惧」的质量闸门风险过高。它可作 paperless 式的**可选备用入口**，但不是主闸门。
- **文件名改名**当信号**排除**：Obsidian 改名默认连带重写双链（副作用），且 Syncthing/git/rclone 类文件级同步把改名当「删+建」，跨设备冲突面最大（§3）。
- **部分完成**（审了 3 块还剩 3 块）：单个 frontmatter 布尔是整文件级、表达不了；用**块级 checklist**（原生 `- [ ]`/`- [x]` 或 frontmatter 列表）补足——这是 Label Studio `drafts` / Argilla `draft` 状态的教训：「存了但没提交」是一等状态，和「审完」分开（§1.2、§4）。

一句话：**抄 Decap 的「状态可编辑、推进靠显式动作」双层结构——frontmatter `reviewed` 布尔当人面开关（安全默认 false）+ 块级 checklist 表达部分完成 + 一条显式 CLI 命令当唯一闸门兼快照时刻；不要让目录监听/改名当触发器。**

---

## 论证

### 0. 候选总览：每个生态把「状态」放在哪

先看各现成项目把「审核/发布状态」这个信号存在什么载体上——这是全篇的骨架：**信号在文件内（frontmatter/正文/文件名）还是文件外（分支/PR 标签/数据库/目录位置）**，直接决定它的三维表现。

| 项目 | ⭐ / 许可 / 活跃 | 信号载体 | 推进动作 | 对本票的价值 |
|---|---|---|---|---|
| **Decap CMS**（`decaporg/decap-cms`）| 19,252 / MIT / 推送 2026-07-23 | **文件外**：git 分支 `cms/<collection>/<slug>` + PR/MR 标签 | **显式**「Approve and publish」= 合并 PR + 删分支 | 同构度最高；「状态可编辑 + 显式推进」双层的原型 |
| **Hugo** | 官方 SSG | **文件内**：frontmatter `draft: true` | 无状态：每次 build 重读 `-D` 标志 | frontmatter 单字段先例；**安全默认值**教训 |
| **Jekyll** | 官方 SSG | **两套并存**：`_drafts/` 目录 + `published: false` frontmatter | 把文件移进 `_posts/` 并补日期名（两步） | 「目录 = 状态」与「字段 = 状态」的对照 |
| **paperless-ngx**（`paperless-ngx/paperless-ngx`）| 43,403 / GPL-3.0 / 推送 2026-07-23 | **文件外**：consume 目录位置 | 消费后从目录删除 | 目录移动作信号的代表；竞态处理的一手样本 |
| **Obsidian**（原生） | 官方 | **文件内**：frontmatter Properties / 正文 checkbox | 无（只是表示，需外部脚本消费） | 本项目落地环境；原生能力边界 |
| **Kanban 插件**（`mgmeyers/obsidian-kanban`）| 4,424 / GPL-3.0 / 推送 2026-03-06、**招维护者** | **文件内**：`kanban-plugin` frontmatter + `##` 泳道 + `- [ ]` 卡片 | 拖卡片 = 重写整个 md | 列＝状态；但整文件重写、竞态面最大 |
| **Tasks 插件**（`obsidian-tasks-group/obsidian-tasks`）| 3,897 / MIT / 推送 2026-07-23 | **文件内**：`- [x]` + `✅ YYYY-MM-DD` | 无（表示） | 完成标记 + 时间戳；per-item 部分完成 |
| **Label Studio**（`HumanSignal/label-studio`）| 27,906 / Apache-2.0 / 推送 2026-07-23 | **文件外**：数据库；`annotations` / `drafts` / `was_cancelled` | Submit / Skip；Accept/Reject 仅企业版 | 「审完 / 审了一半 / 跳过」三态分离 |
| **doccano**（`doccano/doccano`）| 10,712 / MIT / 推送 2026-04-14 | **文件外**：DB `ExampleState`(confirm) + `annotations_approved_by` | 打勾 confirm / 管理员 approve | confirm≠approve 两级；**无 reject 态** |
| **Prodigy**（`explosion/prodigy`，闭源商业） | 闭源（repo 404）/ 商业 | **文件外**：SQLite；每例一个 `answer` | accept/reject/ignore 三选一 | 三态最干净、近似 append-only |
| **Argilla**（`argilla-io/argilla`）| 5,046 / Apache-2.0 / 推送 2026-07-20 | **文件外**：DB；`pending/draft/submitted/discarded` | Submit / Discard；**永不回 pending** | 四态 + 单向约束 |

来源（`gh api repos/<repo>`，2026-07-24）：Decap <https://github.com/decaporg/decap-cms> · paperless-ngx <https://github.com/paperless-ngx/paperless-ngx>（最新 release v3.0.1）· Kanban <https://github.com/mgmeyers/obsidian-kanban>（README 顶部横幅「looking for new maintainers」，事实）· Tasks <https://github.com/obsidian-tasks-group/obsidian-tasks> · Label Studio <https://github.com/HumanSignal/label-studio> · doccano <https://github.com/doccano/doccano> · Argilla <https://github.com/argilla-io/argilla> · Prodigy 商业闭源，`repos/explosion/prodigy` 返回 404（事实）。

> **一眼可见的规律（推断）**：越是「质量闸门」性质的工具（Decap 发布、Label Studio/Prodigy/Argilla 标注、paperless 归档），越倾向把**推进动作**做成一个**显式的、与内容编辑解耦的动作**（点「发布」、点 Submit、拖进 consume 目录），而不是靠某个字段被动翻转就自动前进。frontmatter 单字段（Hugo/Jekyll）够用的场景，恰是**误发布代价低**的静态站——它「漏发」（默认 draft）比「误发」更常见、也更安全。本项目误触发代价高，属前一类。

---

### 1. 四种机制的三维取舍（Q1）

先给结论矩阵，再逐条摆现成项目的证据。

| 机制 | 误触发抵抗力 | 部分完成表达 | 幂等/重放 | 一句话 |
|---|---|---|---|---|
| **frontmatter 字段** | 中（单字段翻转轻、怕模板默认值/批量）；但**安全默认值**可让「漏」比「误」安全 | 整文件布尔，**表达不了**块级；需配 checklist | 字段可变、重读不消耗；但消费方要另存「已处理」态防重跑 | 表达力好、原生，但太轻不能单独当闸门 |
| **文件名改名** | 高（需刻意），但 Obsidian 里**脆**：改名重写双链 + 文件级同步当「删+建」 | 二值，无半态 | 改完源名即消失 → 天然单发 | 幂等好，但 Obsidian 副作用最大，排除 |
| **目录移动** | 高（刻意拖动） | 二值，无半态 | 消费即移出 → 天然单发；但重投同名文件会被再消费（需 hash 去重） | 高抵抗，但**有写盘竞态**（§2），当闸门风险高 |
| **显式 CLI 命令** | **最高**（正向意图、与编辑解耦、默认值/批量都触发不了） | 可带参数/读 checklist，最灵活 | 命令在已知时刻读文件、可记账 → 无竞态、可做幂等 | 抵抗力与快照最优，代价是要出 Obsidian 到终端 |

#### 1.1 误触发抵抗力：Hugo 的「安全默认值」与 Decap 的「显式推进」

- **Hugo（事实）**：`draft` 是 frontmatter 布尔，缺省即「非草稿、正常构建」；但**默认 archetype 模板写死 `draft: true`**，所以 `hugo new` 产出的新内容默认是草稿——发布要显式把字段翻成 `false`。来源：<https://gohugo.io/content-management/archetypes/>（默认 archetype = `date/draft: true/title`）、<https://gohugo.io/methods/page/draft/>（"By default, Hugo does not publish draft pages"）。
  - **教训（推断）**：把默认值设成「未通过」，一次手滑/漏改只会让内容**停在未发布**（fail-safe），绝不会误发。story-machine 的草稿模板应播 `reviewed: false`。
  - **反面风险（事实+推断）**：Hugo 用 `-D/--buildDrafts` 一个标志**一次性包含所有草稿**（<https://gohugo.io/commands/hugo/>）——这是「批量误触发」的典型：单个开关放行全部。story-machine 的消费命令**不应有「放行全部 `_review/`」的批量模式**当默认路径。

- **Decap CMS（事实）**：进阶到发布是**显式动作**——「Approve and publish」= 合并 PR + 删分支；且整个 editorial workflow 要显式开 `publish_mode: editorial_workflow`（默认 `simple` 是直接提交主干）。来源：<https://decapcms.org/docs/editorial-workflows/>、<https://decapcms.org/docs/configuration-options/>。状态字符串为 `draft` / `pending_review` / `pending_publish`（源码 `publishModes.ts`），标签形如 `decap-cms/draft`（`APIUtils.ts`，`CMS_BRANCH_PREFIX='cms'`）。
  - **坑（事实）**：Decap 把状态存在**文件外**（分支 + PR 标签），手工乱改标签会污染状态——issue [#6140](https://github.com/decaporg/decap-cms/issues/6140) 即手改 `netlify-cms/pending_review` 标签导致状态错乱。**推断**：文件外的可变状态易与内容漂移、且脆于手改。story-machine 若把 `reviewed` 放 frontmatter（文件内、随内容走），天然免疫这类漂移；而把「权威闸门」放在 CLI 命令而非 frontmatter 本身，又避免了「单字段被误设即推进」。
  - **推断**：Decap 没有硬约束强制 `pending_review` 必须先于 publish（有合并权者可跳过），安全是流程性的、非强制的。这印证：**表示（三态标签）解决不了误触发，把关的是那一次显式点击。**

- **Jekyll（事实）**：发布 = 把文件从 `_drafts/` **移进 `_posts/` 并给文件名补日期**（两步刻意动作），或用 `published: false` 单字段。来源：<https://jekyllrb.com/docs/posts/>、<https://jekyllrb.com/docs/front-matter/>。**推断**：`_drafts→_posts` 的「移动 + 改名」两步，误触发抵抗力比翻一个 `published` 字段高，但代价是两处改动——这正是「目录/文件名」类机制抵抗力高的来源，也预示了它们的副作用（§3）。

#### 1.2 部分完成的表达能力：标注工具的「草稿态」是一等公民

- **Label Studio（事实）**：任务对象上 `annotations`（已提交）与 `drafts`（自动保存的未提交半成品）是**两个独立数组**；`was_cancelled` 布尔标「跳过/取消」。来源：<https://labelstud.io/guide/task_format>、<https://labelstud.io/guide/skip>、<https://labelstud.io/guide/labeling>。即「审完 / 审了一半 / 看过但跳过」三态各有独立表示。
- **Argilla（事实）**：response 状态 `pending`（无响应）/ `draft`（存了未交）/ `submitted`（交了）/ `discarded`（看过搁置），且**只能单向、永不回 `pending`**。来源：<https://docs.argilla.io/latest/how_to_guides/annotate/>、<https://docs.argilla.io/latest/how_to_guides/distribution/>。
- **对照（事实）**：Prodigy 每例一个 `answer ∈ {accept, reject, ignore}`（<https://prodi.gy/docs/text-classification>），doccano 只有 confirm/approve、**无 reject 态**（源码 `examples/models.py` 有 `confirmed_by`/`annotations_approved_by`，无 reject 字段）——这两者**没有半成品态**，一例要么裁决要么没裁决。
  - **教训（推断）**：需要「审了一半」时，把它做成**独立于「审完」的一等状态**（draft/存盘未交），而不是用「审完」的缺省来兼表。story-machine 的草稿是**每集一个 `EP{n}_draft.md`、内含多块**，故「审了 3 块还剩 3 块」应由**块级 checklist**（原生 `- [ ]`/`- [x]` 或 frontmatter 列表）承载，与整集的 `reviewed` 布尔分开。frontmatter 单字段本身表达不了块级，这是它必须配 checklist 的原因。

#### 1.3 幂等与重放：收敛的共同模式是「消费即移出」

同一个信号被消费两次会怎样，各家的解法惊人一致——**推进后让源信号消失**：

- **paperless-ngx（事实）**：消费成功即从 consume 目录删除文件（usage 文档）；v3 的 watcher 维护 in-flight `queued` 集合，周期性全量重扫（`rescan_interval_s=300`）时跳过已入队者，「a file is never queued twice」。但**注意**：v3.0 起默认**允许重复文档再次消费**，除非开 `PAPERLESS_CONSUMER_DELETE_DUPLICATES`（按内容 hash 去重）。来源：<https://docs.paperless-ngx.com/configuration/>、`document_consumer.py`。
- **Decap（事实）**：发布即合并 PR + 删分支 → 信号单发、无从重放。
- **Jekyll（事实）**：`_drafts→_posts` 移动后，源目录里不再有它 → 单发。
- **Hugo（推断）**：无状态构建，`-D` 标志每次重读、从不「消费」，重复构建幂等——但这是「读取幂等」，不解决「同一草稿被推进两次」。

  - **教训（推断）**：frontmatter 字段是**可变标志**（Hugo/doccano `ExampleState`/Label Studio 都是 create-or-delete 的可变态），若消费方只认 `reviewed:true`，重跑就会重复处理阶段 4。要幂等，得学 paperless/Decap/Jekyll 的「**消费即移出**」：CLI 命令推进后把草稿移出 `_review/`（或盖 `stage: done` 第二字段 / 记内容 hash）。**这也顺带解决了「审后又改」——草稿已移出，再改不影响已入库版本，且 `_pairs/…_post.md` 已在推进时刻定格。**

---

### 2. 目录监听 / 文件监听的竞态（Q2）

**核心结论：能把「完整文件到达」信号做实的，只有两条——把文件原子 `rename()` 进被监听目录（靠 `IN_MOVED_TO` 检测），或本地就地写完后的 `IN_CLOSE_WRITE`。其余一切（网络盘、轮询、`watchdog`）都退化成同一个启发式：大小+mtime 连续 N 秒不变。而 Obsidian 的写盘是否满足前两条，官方无任何文档保证。**

- **rename 原子性（事实）**：`rename(2)` man page——「If newpath already exists, it will be atomically replaced, so that there is no point at which another process ... will find it missing」；但仅限**同一文件系统**（跨挂载点报 `EXDEV`，退化为拷贝+删除、会暴露半截文件）。来源：<https://man7.org/linux/man-pages/man2/rename.2.html>。
- **inotify 事件语义（事实）**：`IN_MODIFY` 在**写入过程中**就触发（不安全）；`IN_CLOSE_WRITE` = 「写打开的文件被关闭」；`IN_MOVED_TO` = 「文件被 rename 进本目录」。稳健的 watcher 忽略 `IN_MODIFY`/`IN_CREATE`，只认后两者。来源：<https://man7.org/linux/man-pages/man7/inotify.7.html>。
- **paperless 的稳定性闸门（事实）**：v3 的 `FileStabilityTracker`——「A file is considered stable when: 1. No new events ... within the stability delay 2. Its size and modification time haven't changed 3. It still exists as a regular file」，由 `PAPERLESS_CONSUMER_STABILITY_DELAY`（**默认 5.0 秒**）控制，文档明写「Increase this value if you experience issues with files being consumed before they are fully written」。网络盘（NFS/SMB/CIFS）inotify 不可靠时切 `PAPERLESS_CONSUMER_POLLING_INTERVAL` 轮询。来源：<https://docs.paperless-ngx.com/configuration/>、`document_consumer.py`（v2.x 时代该「大小+mtime 连续不变」检测只在轮询模式；v3 统一到原生+轮询两条路径）。
- **`watchdog`（事实+缺口）**：官方 API 有 `FileClosedEvent` / `on_closed`（"Called when a file opened for writing is closed"，即 inotify `IN_CLOSE_WRITE` 的封装，**仅 Linux**）。但官方文档**未明说** `on_created`/`on_modified` 会在文件写完前触发——「create/modify 先于写完」属社区共识、非一手文档。来源：<https://python-watchdog.readthedocs.io/en/stable/api.html>。
- **Hazel（事实）**：默认忽略 `.part` 等常见半下载文件；对任意拷贝则靠用户写「Date Last Modified 不在最近 N 分钟内」规则——同样是「大小/mtime 停止变化」启发式，而非内核 `CLOSE_WRITE` 信号。来源：<https://www.noodlesoft.com/manual/hazel/work-with-folders-rules/manage-folders/>、<https://www.noodlesoft.com/forums/viewtopic.php?f=4&t=1588>。

**Obsidian 侧的关键未知（事实）**：官方「How Obsidian stores data」只说笔记是纯文本、会「自动刷新以跟进外部改动」，**对磁盘写入机制（是否 temp+rename 原子写、外部读能否读到半截）只字未提**（<https://obsidian.md/help/data-storage>）。论坛一则「`adapter.write()` 后有 1–2 秒窗口，外部同步工具会读到截断副本」的报告，被 Obsidian 开发者 Licat 当场反驳（"The file watcher system is just a watcher, not a writer ... I am also unable to reproduce"），报告者随后也**复现不出**、归因于自己的插件测试。来源：<https://forum.obsidian.md/t/vault-cache-truncation-after-adapter-write/113139>。

> **净结论（推断）**：Obsidian 写盘既**未被证实会截断**，也**没有官方原子性保证**——两个方向都悬着。对一个「误触发是头号恐惧」的质量闸门，**押注「监听 `_review/` 能读到完整文件」是没有一手依据的赌注**。两条出路：
> - **要监听，就必须加稳定性闸门**（抄 paperless：大小+mtime 连续 ≥N 秒不变才算稳，默认取 5 秒量级），且只认 `IN_MOVED_TO`/`IN_CLOSE_WRITE`——但这引入调参与平台差异，且移动端同步延迟下更不可靠。
> - **更干净的是根本不监听**：让**人存盘后手动敲 CLI 命令**，此刻文件已静止、无写入方在场，命令读到的必然是完整内容——**竞态从根上消失**，而且这一刻正好是 `_pairs/…_post.md` 的快照时刻，一举两得。这是本文推荐 CLI 当闸门的第二个硬理由（第一个是误触发抵抗力，§1.1）。

---

### 3. Obsidian 特有约束：哪种机制冲突最小（Q3）

MVP 只用**原生功能 + 外部脚本**、不写插件。逐机制对照 Obsidian 的默认行为：

- **frontmatter 字段 = 冲突最小（事实）**：YAML frontmatter 原生渲染成 Properties，官方支持 `Checkbox` 类型——「Checkbox properties are either `true` or `false`. In Live Preview, this displays as a checkbox」（<https://obsidian.md/help/Editing+and+formatting/Properties>），即用户可在 Properties 面板直接勾 `reviewed`。它**按内容编辑同步**（不改文件名、不动双链），移动端可编辑。核心插件 **Bases**（Obsidian 1.9.0 起，2025-05；1.9.10 起 GA）能直接「view, edit, sort, and filter files and their properties」，即**原生就能筛出所有 `reviewed = true` 的草稿**、无需插件（<https://obsidian.md/help/bases>、<https://obsidian.md/changelog/2025-05-21-desktop-v1.9.0/>）。副作用：无——不碰双链、不改名。**误触发面**：checkbox property 在 Properties 面板、**不在正文点击面上**，比正文内联复选框更难手滑（但无二次确认）。
  - **注意（事实）**：Obsidian **无原生「给所有笔记批量加属性/设默认值」**功能（官方明说批量编辑请用 VSCode/脚本/社区插件）——好消息是「批量误设 `reviewed`」不会经原生 UI 意外发生；但**外部脚本**若批量写 frontmatter 要自己当心（呼应 §1.1 的批量风险）。
- **正文原生 checkbox `- [ ]`/`- [x]`（事实）**：Reading view 可勾（"You can toggle a task in Reading view by selecting the checkbox"，<https://obsidian.md/help/Editing+and+formatting/Basic+formatting+syntax>），移动端 Reading view 可点（一手文档未逐字确认移动端、属通用行为）。**优势**：真·per-item 态，天生适合「本集内哪几块审完」的块级部分完成（§1.2）。**代价**：在正文点击面、比 Properties 面板易手滑；Live Preview 直接点选社区反映不稳，建议靠命令或 Reading view。
- **Tasks 插件 `✅ YYYY-MM-DD`（事实）**：完成标记带时间戳（`- [x] ... ✅ 2023-04-17`，<https://publish.obsidian.md/tasks/Reference/Task+Formats/Tasks+Emoji+Format>）——比裸 `- [x]` 多一个「何时审完」的戳，但引入插件依赖（MVP 无插件原则下，只当「若已装」的加分项，不作硬依赖）。
- **文件名改名 = 冲突最大（事实）**：Obsidian「自动更新内部链接」默认开，改名会重写全库 `[[旧名]]` → `[[新名]]`（<https://obsidian.md/help/How+to/Internal+link>）。本项目 `_review/` 草稿按 spec「不加双链」，**这条副作用被削弱**——但 Obsidian Sync 不把改名当改名追踪历史、且 Syncthing/git/rclone 类文件级同步一律把改名当「删+建」，跨设备易起冲突（<https://forum.obsidian.md/t/obsidian-sync-keep-track-of-file-renames-and-moves-in-sync-history/26630>）。**排除当信号。**
- **目录移动（事实+推断）**：库内移动会触发重索引，但 `_review/` 本就排除出图谱、影响有限；移出库则脱离 Obsidian 视野。跨设备同步同样是「删+建」churn，叠加 §2 的写盘竞态。**可作备用入口，不作主闸门。**
- **Kanban 插件（事实）**：board = 单个 md（`kanban-plugin` frontmatter + `##` 泳道 + `- [ ]` 卡片），**每次拖卡片重写整文件**——竞态面与同步 churn 在所有选项里最大；且插件正**招维护者**（README 顶部横幅、~548 open issues）。人看着直观，但作机器解析的「已审」标志最差。**不推荐依赖。**

> **Obsidian 侧净结论（推断）**：机器可读、同步稳、无副作用的**整集**「审完」标志，**frontmatter `reviewed` 布尔（配 Bases 视图）是最强原生选项**；需要**块级**部分完成时，加**正文 `- [ ]`/`- [x]`**（装了 Tasks 就顺带拿到 `✅` 时间戳）。**避开改名/移动当信号**（双链重写 + 删建同步冲突 + 写盘竞态）。且因 Obsidian 写盘原子性无保证，外部脚本**不要押注单次读到完整文件**——最省心的是不监听、由人 CLI 触发（§2）。

---

### 4. 能抄什么 / 不能抄什么（Q4）

**抄 Decap 的双层结构**（状态可编辑、推进靠显式动作），落到本项目：

| 抄什么 | 来源依据 | 怎么落地 |
|---|---|---|
| **状态放 frontmatter、推进靠显式动作**（两者分开） | Decap：状态在标签、发布是「Approve and publish」显式点击（§1.1） | `reviewed` 布尔当人面开关；CLI 命令当唯一权威闸门 |
| **安全默认值 = 未通过** | Hugo archetype 默认 `draft:true`（§1.1） | 草稿模板播 `reviewed: false`，通过必须显式翻转 |
| **消费即移出，保幂等** | paperless 消费即删 / Decap 合并删分支 / Jekyll 移进 `_posts`（§1.3） | 命令推进后把草稿移出 `_review/`（或盖 `stage: done`）；配内容 hash 兜底 |
| **「审了一半」做成一等状态** | Label Studio `drafts` / Argilla `draft`（§1.2） | 块级 `- [ ]`/`- [x]` checklist，独立于整集 `reviewed` |
| **无监听、人触发时读文件 = 无竞态 + 天然快照点** | inotify 竞态 + Obsidian 写盘无原子保证（§2） | CLI 命令在人存盘后读文件，同刻写 `chunk{k}_post.md` |
| **三态区分：通过 / 打回 / 存疑** | Prodigy accept/reject/ignore、Argilla submitted/discarded（§1.2） | 复用 spec 现有语义：保留=通过、删条目=打回、`?`=存疑；`reviewed` 只表「过了一遍」 |

**不能抄 / 要避开：**

- **不抄 Decap 把状态放文件外**（分支/标签）：会与内容漂移、脆于手改（issue #6140，§1.1）。本项目 `reviewed` 放 frontmatter、随文件走。
- **不抄「一个标志被动翻转即自动推进」**（Hugo `-D` 放行全部、frontmatter 单字段当闸门）：批量/手滑误触发风险，违背「误触发抵抗力第一」。
- **不抄目录监听/改名当触发器**：写盘竞态（§2）+ Obsidian 双链/同步副作用（§3）。paperless 的目录移动模式在**本地、单机、原子 rename** 前提下才干净，Obsidian 库 + 移动端同步不满足该前提。
- **不硬依赖 Kanban 插件**（招维护者、整文件重写、竞态最大）。

---

## 对 story-machine 的影响

落到 spec 具体章节：

1. **spec 第 9 节「`_review/` 确认信号」开放问题——建议按本文拍板为「frontmatter `reviewed` 布尔 + 显式 CLI 命令」双层**（供 #4 HITL 会话确认）：
   - 草稿模板（阶段 2 写 `_review/EP{n}_draft.md` 时）在 frontmatter 播入 `reviewed: false`（安全默认）。
   - 阶段 3 用户校对完，在 Obsidian Properties 面板勾 `reviewed: true`（原生、移动端可点、无副作用）。
   - 触发阶段 4 = 用户存盘后**手动敲一条显式 CLI 命令**（命令形状/参数归 #5）。命令：①校验 `reviewed:true` 否则拒推进（双闸门）；②即刻读文件写 `_pairs/EP{n}/chunk{k}_post.md` 快照（无竞态）；③把草稿移出 `_review/`（幂等，防重跑）。

2. **spec 阶段 3「校对配对数据」——快照时刻即命令时刻**：现文档说「阶段 3 确认信号触发时存 `chunk{k}_post.md`」，本文给出该信号的具体形态（CLI 命令读静止文件），并指出这天然规避了「监听读到半截文件」的风险——建议在 spec 阶段 3 补一句「快照由确认命令在文件静止态读取，不走目录监听」。

3. **spec 阶段 3「部分完成」——补块级 checklist 约定**：因草稿是每集一文件、内含多块，「审了 3 块还剩 3 块」用整集 `reviewed` 布尔表达不了。建议约定在草稿里按块放 `- [ ]`/`- [x]`（或 frontmatter 列表），命令可据此只推进已勾块 / 或要求全勾方推进（取舍留 #4/#5）。

4. **参数取值建议（推断）**：若 #5 最终仍保留任何「目录监听/文件监听」旁路，稳定性延迟取 paperless 默认量级（**大小+mtime 连续 ≥5 秒不变**）、只认 `IN_MOVED_TO`/`IN_CLOSE_WRITE`；但主路径不建议走监听。

5. **与 #5 的边界**：本票只认定「信号 = frontmatter 前置条件 + 显式 CLI 命令」这个**形态**；命令叫什么、吃什么参数、如何断点续跑，全归 #5，两票不重叠。

---

## 未决问题

（调研中冒出、超出本票范围，供开新票）

1. **草稿的块↔集文件粒度**：spec 阶段 2 写「每集一个 `EP{n}_draft.md`」，而 `_pairs` 是「每块 `chunk{k}_post.md`」。一个整集草稿如何对应到多块快照（是集内分节、还是本就该每块一文件），影响块级 checklist 与快照的实现——建议在 #4/#5 明确，非本票「信号表示」范畴。
2. **frontmatter `reviewed` 与阶段 2.5「建议合并」裁决的关系**：用户对每条「建议合并」点头/摇头的裁决，是否也进 frontmatter/checklist、还是留在正文——涉及阶段 2.5 与阶段 3 的数据结构，超出「审完信号」本身。
3. **命令触发的移动端可达性**：CLI 命令要在终端敲，移动端 Obsidian 无终端。若用户有「手机上审完就想推进」的诉求，需要一个移动端可触达的旁路（如某个 frontmatter 值被笔记本侧轮询）——这会重新引入 §2 的竞态权衡，建议实跑确认是否真有此诉求再议。
4. **Obsidian 写盘原子性的实测**：本文只能确认「官方无文档保证、一则截断报告被反驳但未证伪」。若未来任何环节确实要监听 `_review/`，值得在 5070/笔记本真机各跑一次「写入中读取」实测确认，而非依赖公网结论。
