# 结构化 Markdown 约定综述：Dataview 行内字段 / Obsidian 原生 Properties·Bases 的可解析性与选型

> AFK 调研票 [#39](https://github.com/kildren-coder/story-machine/issues/39)，压在 [#7 结构化 Markdown 模板原型](https://github.com/kildren-coder/story-machine/issues/7) 上。本文只回答票面 Question，不做拍板；给 #7 的 prototype 会话供「有哪些约定可选、各自代价是什么」的弹药。
> 所有来源访问日期均为 **2026-07-24**。文中区分「来源直接写明」（事实）与「据此推断/据此分析」（我的推断）。

## 问题

#1 地图会话定死一条地基决策：**结构化 Markdown 是唯一权威存储**（frontmatter + 行内字段 + 固定标题锚点），下游四愿景（求真引擎、资产分析框架、故事素材库、信源信用档案）不直接读笔记，而是**吃解析器派生的文件**。这把一个事实变成单点风险：**如果行内字段语法没有可靠的 Obsidian 外解析器，整个下游就无法消费自己的权威存储。**

要回答五问：

1. **行内字段的可解析性**（最关键）：`key:: value` 是否有稳定、有文档、可被第三方实现的规范？有哪些现成的 Obsidian 外解析器，成熟度如何？若「只有 Dataview 能读」，这是必须上报的架构风险。
2. **原生 vs 插件**：Properties/Bases 现在的能力边界，能否覆盖本项目字段需求？押原生还是押 Dataview？
3. **成对/嵌套结构怎么表达**：#3 的「保真层 + 结构层分离」要求同一概念存原文与规范化两份。哪种表达在「人手改不容易改坏」与「程序解析不容易歧义」之间平衡最好？
4. **固定标题锚点的稳定性**：靠 `## 来源记录` 定位段落，程序改写时怎么保证不破坏用户手写内容？有没有现成的「按锚点安全插入」实现可抄。
5. **能抄什么 / 不能抄什么**：给 1–2 套具体字段书写约定候选（含实际片段）。

---

## 结论（TL;DR）

**一句话：把「程序要读的结构化真相」放进 YAML frontmatter 和已定的 JSON 边车索引（`entities.json`/`sources.json`），不要让 Obsidian 正式笔记正文里的 `key:: value` 行内字段成为下游四愿景的唯一机器真相——因为行内字段没有任何成熟的 Obsidian 外解析器，Dataview 自己的 TypeScript 实现事实上是唯一忠实实现。**

分点：

- **【本票最关键结论 · 架构风险 ✅ 上报】** `key:: value` 行内字段**没有正式语法规范**，是 Dataview 源码 `src/data-import/inline-field.ts`（MIT，257 行）里**实现定义（implementation-defined）**的行为——官方文档不给转义规则、不给语法文法。**Obsidian 之外没有任何成熟、在维护的解析器忠实复现它**：全网调研的 6 个候选里，只有 `py-obsidianmd` 尝试解析行内字段，却是朴素正则（含经典 `[A-z]` 键类 bug）、自 2022-12 起休眠、且不声称与 Dataview 语义一致；`obsidiantools`、`obsidianmd-parser`、`turbovault`、`goldmark-obsidian`、`obsidian-export` 全部**只解析 YAML frontmatter**。**若权威存储依赖正文行内字段，下游要么移植 Dataview 的 TS、要么在管线里常驻一个 Node+Dataview、要么容忍近似解析——三条路都是负债。**
- **【原生 vs 插件】押原生 frontmatter（Properties），不押正文行内字段。** frontmatter 是 YAML 1.2，`python-frontmatter` 等库久经沙场、有规范、跨语言——**可解析性是行内字段没法比的**。Obsidian 原生 Properties（1.4，2023-07）、Bases（1.9，2025-05）都**只读 frontmatter，不读正文行内字段**（这是 Bases 已确认的限制）。代价：frontmatter 是**页级、扁平**的，装不下「每条论断 8 个字段」「每条关系带原文」这种**正文级、可重复**的结构——那些本就不该塞 frontmatter。
- **【本项目已经走对了一半】** #3 定稿已经把最复杂的成对/嵌套数据（别名对象带语域、归因补全层）放进 **`entities.json` / `sources.json` JSON 边车**，frontmatter 的 `aliases:` 由 `entities.json` **派生**。这正是本文要推荐的架构。**建议把这条原则显式化并推广**：凡是「下游程序要读 + 成对/嵌套/可重复」的数据，机器真相落 JSON 边车或 frontmatter 扁平字段；正文只放**保真层原文（纯 prose，不需解析即无损）** + `[[双链]]` + 固定标题锚点。
- **【行内字段不是全盘不能用】** 有一处它是安全的：**阶段 2/2.5 的 `_review/` 草稿**。草稿的消费者是**阶段 4 的 Claude Code（一个 LLM）**，LLM 对松散 `key:: value` 天然容忍——解析风险在这里不咬人。所以 #3 schema 里草稿大量用 `时态::`/`性质::`/`归因原文::` 是合理的。**风险只在正式笔记、且被四愿景当机器真相直读时才致命。**
- **【成对/嵌套】** 「保真层 + 结构层分离」的最佳落法是**物理分层而非语法嵌套**：**原文（保真层）落正文 prose**（照抄即无损，零解析成本），**规范化值（结构层）落 frontmatter 扁平字段或 JSON 边车**（有类型、可解析）。别用 frontmatter 嵌套对象——Obsidian Properties UI **明确不支持编辑嵌套属性**（「请用 source mode」），一嵌套就破了「人手改不容易改坏」。
- **【标题锚点安全插入】** 「按 `## 来源记录` 追加、不碰用户手写段落」是成熟模式：把笔记 parse 成 mdast（remark/unified 生态，活跃、庞大），定位标题节点、只在该 section 的节点范围内插入、只 stringify 改动段落。`section-remark`（MIT）是这套模式的现成 proof-of-concept（但 2020 后无维护、0 star，只能抄思路不能当依赖）。零依赖版：按行扫到锚点标题、扫到下一个同级或更高级标题、在其前插入。**铁律：只在 section 内追加、绝不整文件重写；锚点缺失时新建标题而非猜位置。**
- **给 #7 的两套候选约定**（详见「论证 §7」）：**约定 A「frontmatter-first」（推荐）** = 页级字段进 frontmatter + 保真原文进正文 + 复杂数据进 JSON 边车；**约定 B「Dataview 行内字段」= 只在 `_review/` 草稿用**，不进正式笔记的机器真相层。

---

## 论证

### 1. 行内字段 `key:: value` 的可解析性（Q1，本票最关键）

#### 1.1 没有正式规范，只有实现定义的行为

Dataview 官方文档《Adding Metadata》给的是**用法说明**，不是**语法文法**：键值间用双冒号 `::`（区别于 frontmatter 的单冒号），`::` 之后到换行为止都是值；行内嵌句要用方括号 `[key:: value]` 或圆括号 `(key:: value)`（圆括号在阅读模式隐藏键）。键会被**归一化**：转小写、空格转连字符、去掉加粗/斜体等格式记号。（来源：Dataview 官方文档《Adding Metadata》，<https://blacksmithgu.github.io/obsidian-dataview/annotation/add-metadata/>，访问 2026-07-24）

关键事实：**官方文档不给转义规则，不涉及值里含 `::`、URL 里的冒号、多行值等边界**。对 Dataview 源码的第三方分析（DeepWiki）明确写道，解析逻辑「appears **implementation-defined** rather than formally specified—no grammar or comprehensive syntax rules are provided」。（来源：DeepWiki《Inline Fields》，<https://deepwiki.com/blacksmithgu/obsidian-dataview/6.3-inline-fields>，访问 2026-07-24）

#### 1.2 直读源码：语法的真实边界（一手，MIT）

我直读了 `blacksmithgu/obsidian-dataview` 的 `src/data-import/inline-field.ts`（一手源码，`gh api`，访问 2026-07-24，<https://github.com/blacksmithgu/obsidian-dataview/blob/master/src/data-import/inline-field.ts>），把「实现定义」的行为固化如下——这是任何外部解析器必须复刻的语义：

| 语义点 | 源码事实 | 对本项目的含义 |
|---|---|---|
| **分隔符** | `findSeparator` 取**第一个** `::`，键 = `::` 前 trim，值 = `::` 后 | 值里可以含 `::`（只切第一个）；键里**不能**含 `::` |
| **整行形式** `Key:: Value` | `extractFullLineField`：整行是一条字段，值 = 首个 `::` 后到行尾 trim。**无转义机制**，值是字面到行尾 | #3 schema 大多数字段（`时限原文::` 等独占一行）走这条 |
| **括号形式** `[key:: value]` / `(key:: value)` | `findClosing` 扫匹配闭括号，**支持反斜杠 `\` 转义**、支持嵌套计数 | 唯一支持转义的形式；值里要放 `]` 需 `\]` |
| **键字符集** | 整行键允许数字、任意 Unicode 字母（`\p{Letter}`，**含中文**）、`_ / -`、空格 | `时限原文`、`归因类型` 这类中文键**合法** |
| **键归一化** | 键由 `canonicalizeVarName`（在同目录 import 管线 `src/util/normalize.ts`）转小写、空格转连字符、去无效字符；原名与归一名都存 | 查询时大小写不敏感；程序读要认归一名 |
| **多值** | 同名键多次出现 → 收进数组；行内亦可逗号分隔 | 「一条信息只存一处」与之相容，但要小心同名键意外并数组 |
| **嵌套对象** | `parseInlineValue` 注释直言「**Inline field objects are not currently supported**」 | **行内字段不能表达嵌套对象**——嵌套只能进 frontmatter |

**据此推断**：这套语法**可以**被第三方复刻（源码紧凑、MIT、可读），但**没有规范文档、没有一致性测试套件、随插件版本可能变**——复刻是「追着一个私有实现跑」，不是「实现一份公开标准」。这是与 YAML frontmatter 的本质区别：后者有 YAML 1.2 规范和几十个跨语言成熟实现。

#### 1.3 Obsidian 外解析器普查：没有一个忠实且在维护（子 agent 深读，访问 2026-07-24）

| 工具 | 语言 | 解析行内 `key::`？ | 维护状态 | 结论 |
|---|---|---|---|---|
| **py-obsidianmd**（`selimrbd/py-obsidianmd`）| Python | **是**（整行 + 括号两式）| PyPI 冻在 **0.1.7 / 2022-12**，库码自 2022 起无实质更新，314⭐ | 唯一尝试者，但朴素正则（含 `[A-z]` 键类 bug）、不声称 Dataview 一致、**已休眠** |
| **obsidiantools**（`mfarragher/obsidiantools`）| Python | **否**，仅 frontmatter + tags + wikilinks | v0.11.0 / 2025-07，活跃，566⭐ | frontmatter-only |
| **obsidianmd-parser**（PyPI，Codeberg `paddyd/obsidian-parser`）| Python | **否**（它的「Dataview 支持」是解析 **query 代码块**，不是行内字段）| 0.4.1 / 2026-06，活跃，MIT | 易混淆：query ≠ field |
| **turbovault**（`epistates/turbovault`）| Rust | **否**，frontmatter-only（连它的 SQL-over-metadata 也只吃 frontmatter）| v1.6.0 / 2026-07，活跃，143⭐，MIT | frontmatter-only |
| **goldmark-obsidian**（`powerman/goldmark-obsidian`）| Go | **否**，Properties = 仅 frontmatter | 活跃 / 2026-07，MIT | frontmatter-only |
| **metadataframe**（`SkepticMystic/metadataframe`）| JS 插件 | 「是」但**靠 Dataview 自己的索引** | 2021 后废弃 | **不算独立解析器**（跑在 Obsidian 内、要求启用 Dataview）|

- **remark / markdown-it（JS/TS）**：搜遍 npm 与 GitHub，**没有**独立、在维护的 Dataview 行内字段解析插件；唯一相关的 npm 包 `obsidian-dataview` 就是 Dataview 自己发布的源码/类型。（来源：npm <https://www.npmjs.com/package/obsidian-dataview>；子 agent 检索，访问 2026-07-24）
- **综合结论（事实）**：**没有成熟、在维护、Obsidian 独立的解析器忠实复现 Dataview 行内字段解析。Dataview 自己的 `inline-field.ts` 事实上是唯一忠实实现。** 要在 Obsidian 外拿到 Dataview 级精度，现实选项只有：移植/改写那份 TS、用 Node 跑 Dataview、或接受 `py-obsidianmd` 的近似正则。（来源：上表各仓 `gh api` 元数据 + README 直读，访问 2026-07-24）

> **这就是票面要求上报的架构风险。** 若正式笔记正文的 `key:: value` 是四愿景的唯一机器真相，本项目等于自建并长期维护一个私有格式的解析器——违背「MVP 不开发插件、只定约定」的初衷，也把「派生解析器」这个环节的成本顶到了最高档。

---

### 2. 原生 Properties / Bases vs Dataview（Q2）

#### 2.1 版本、能力、类型系统（一手）

- **Properties**：Obsidian **1.4.0**（Early Access 2023-07-26，公开版 1.4.5 于 2023-08-31）引入。原生 frontmatter 可视化编辑器，类型：**Text（可含内链）/ List（可含内链）/ Number / Checkbox / Date / Date&time**，外加专用 **Tags**。**存为 YAML frontmatter**——「readable in any plain text app, and compatible with many tools that support YAML frontmatter」。（来源：Obsidian 官方 changelog 1.4.0，<https://obsidian.md/changelog/2023-07-26-desktop-v1.4.0/>；官方帮助《Properties》，<https://help.obsidian.md/properties>；访问 2026-07-24）
- **Properties 明确限制**：**不支持嵌套属性**——「To view nested properties, we recommend using the source mode」；不支持批量编辑、不支持属性内 Markdown 渲染；每个笔记内属性名唯一。（来源：官方帮助《Properties》，同上）
- **Bases**：Obsidian **1.9.0**（Early Access 2025-05-21）引入，**1.9.10** 转为对所有人可用的核心插件。原生数据库视图（Table / List / Cards / Map），支持 Formulas / Functions，配置存 `.base`（YAML）或嵌进代码块。**数据源是 frontmatter properties**——「All the data in Obsidian Bases is stored in your local Markdown files and their properties」。（来源：官方帮助《Bases》，<https://help.obsidian.md/bases>；官方 changelog 1.9.0，<https://obsidian.md/changelog/2025-05-21-desktop-v1.9.0/>；Neowin 报道 1.9.10，<https://www.neowin.net/news/obsidian-1910-lands-with-a-new-core-plugin-bug-fixes-and-more/>；访问 2026-07-24）
- **Bases 已确认限制（关键）**：**Bases 只读 YAML properties，不读正文里的 Dataview `key:: value` 行内字段**——「Obsidian Bases reads YAML properties, not Dataview-style inline fields written in the note body. This is a confirmed limitation.」要用行内字段得先用 `Dataview (to) Properties` 类插件迁进 frontmatter。（来源：多篇迁移实录，如 practicalpkm《How to Migrate to Obsidian Bases from Dataview》<https://practicalpkm.com/moving-to-obsidian-bases-from-dataview/>、robcoles.net<https://robcoles.net/posts/dataview-and-inline-to-datacore-bases-and-yaml/>；二手一致，置信度高，访问 2026-07-24）
- **Bases 尚不能全替 Dataview**：缺 `dataviewjs` 那种任意 JS 逃生舱，表达不了「拉取散落正文中段的行内字段」。（来源：danholloran.me、practicalpkm 等对比文，访问 2026-07-24）

#### 2.2 推荐：押原生 frontmatter，把行内字段挡在正式笔记的机器真相层之外

**推荐（带理由）**：本项目的机器真相层应**押原生 frontmatter Properties**，而非正文 Dataview 行内字段。理由：

1. **可解析性是压倒性的**（回到 Q1）：frontmatter = YAML，跨语言成熟库一大把；行内字段 = 单厂实现、无外部解析器。四愿景要在 Obsidian 外、headless 管线里读数据，frontmatter 是唯一无痛路径。
2. **少一个插件依赖**：CONTEXT 明确「MVP 不开发 Obsidian 插件，只定约定」。押 frontmatter 后，Dataview / Bases 都退化成**可选的视图层**（在 vault 里好看、好查），**不是解析依赖**。用户装不装 Dataview，都不影响下游能不能读。
3. **原生 UI 护栏**：Properties 有类型化编辑器，`type`/`tags`/`aliases` 这类页级字段人手改不容易改坏；Bases 还能给用户一个「像 Notion 表格」的浏览面，零插件、移动端也快。

**代价与边界（诚实说明）**：frontmatter 是**页级、扁平**的，装不下「每条论断带 8 个字段、一集几十条」「每条关系带原文」这类**正文级、可重复、关系型**结构。这些数据本就不该进 frontmatter——见 §3、§4 的分层方案。**据此推断**：押原生不是「全用 frontmatter」，而是「frontmatter 承载页级机器真相 + JSON 边车承载复杂机器真相 + 正文承载保真原文与人读内容」的三层分工。

> **顺带评估 Logseq / Dendron（票面候选，快速定性）**：
> - **Logseq** 的属性也用 **`key:: value`**（与 Dataview 撞语法），且支持 block 级属性（比 Obsidian 更接近「每条目一组属性」），其 **DB 版 + EDN/JSON 导出**能完整捕获图谱、程序消费更干净。**但**这套导出与 DB 是 **Logseq 工具锁定**——本项目是 Obsidian 栈，换工具成本远超收益，且 Logseq 的 `key::` 同样缺 Obsidian 外通用解析器。**结论：不适用，仅印证「block 级属性 + 显式类型」是更利于程序消费的方向。**（来源：Logseq DeepWiki《Property System》<https://deepwiki.com/logseq/logseq/3.2-property-system>；Logseq docs `db-version.md`；访问 2026-07-24）
> - **Dendron schema** 是**层级/命名空间的类型系统**（描述 `project.*` 这种笔记层级、挂模板、自动补全合法子节点），不是字段级 schema，且强依赖 Dendron 工具。**结论：其「schema 先行」思路值得借鉴到目录/命名约定（本项目已有 `20-People/` 等前缀目录），但字段书写约定抄不了。**（来源：Dendron 官方 wiki《Schemas》<https://wiki.dendron.so/notes/c5e5adde-5459-409b-b34d-a0d75cbb1052/>，访问 2026-07-24）

---

### 3. 成对 / 嵌套结构怎么表达（Q3：保真层 + 结构层分离）

#3 的骨干原则要求同一概念存两份（别名 + 语域、时限原文 + 规范时间、归因原文 + 补全层、数据点口径原文 + 指标名）。四种候选表达：

| 方案 | 人手改不容易改坏 | 程序解析不容易歧义 | 可重复/关系型 | 评价 |
|---|---|---|---|---|
| **A. frontmatter 嵌套对象** | ✗ Properties UI 不能编辑嵌套（要 source mode）| ✓ YAML 对象类型清晰 | ✗ 页级、不便重复 | 机器友好但**破了人手护栏** |
| **B. 两个扁平行内字段**（`时限原文::` + `时限规范::`）| ✓ 正文里直观 | ✗ 行内字段解析风险 + 配对全靠约定（无物绑定）| △ 多条时配对易乱 | 草稿里可以，正式笔记机器真相层不行 |
| **C. 固定标题锚点下的列表** | ✓ 最贴近人读 | ✗ 每字段是 prose，仍要行内格式才可解析 | ✓ 天然可重复 | 适合保真层原文（人读为主）|
| **D. JSON 边车对象**（`entities.json`/`sources.json`）| ✗ 不在 vault 里手改 | ✓ 机器完美 | ✓ 数组/引用自如 | 适合结构层 + 关系型 |

**推荐：物理分层，不用语法嵌套。** 把「保真层」与「结构层」**放到不同物理位置**，而不是在一条 `key:: value` 里嵌套：

- **保真层（原文照抄）→ 正文 prose**。原文是纯文本，**照抄即无损，零解析成本**——它靠「被逐字复制」保真，根本不需要程序去 parse 它的结构。放在 `## 来源记录` 等锚点下，人读友好。
- **结构层（规范化值）→ frontmatter 扁平字段 或 JSON 边车**。有类型、可查询、可被通用库解析。

**现成项目佐证（Vault-LD，直接对口本题）**：Vault-LD 是一套「Markdown vault 即 Linked Data」的开放规范，明确**只用 YAML frontmatter 承载结构化语义，正文只放 prose**——「a person editing notes, and a machine reasoning over a graph」共享同一份资源；靠一个 `context.jsonld`（YAML-LD）做 @context，`vault_to_rdf.py`/`rdf_to_vault.py` 做**双向无损 roundtrip**。它**刻意不用正文行内字段**。这正是本文推荐的「frontmatter 承载机器真相、正文保持人读」的成熟先例。（来源：Vault-LD 仓库 <https://github.com/The-Knowledge-Graph-Guys/vault-ld>、官网 <https://vault-ld.org/>，访问 2026-07-24）

**本项目已经走对**：#3 定稿把别名对象（带 `语域`）放 `entities.json`、frontmatter 的 `aliases:` 由它**派生**；归因补全层放 `sources.json`、正文只留原文 + 指针 `归因索引:: S-0117`。**建议把这条「原文进正文/frontmatter 扁平、结构层进 JSON 边车」显式写成 spec 的通用规则**，让 #7 的模板照此办理，而不是每个字段临时决定。

---

### 4. 固定标题锚点的稳定性与安全插入（Q4）

**问题拆两半**：(a) 锚点本身稳不稳；(b) 程序改写怎么不碰用户手写内容。

**(a) 锚点稳定性**：靠 `## 来源记录` 这类标题文本定位，风险是**标题文本漂移**（用户改字、本地化、加 emoji）。缓解：把锚点标题文本当**约定契约**固定下来（模板里写死、spec 里列清单）；解析时对标题做归一化匹配（trim、去格式记号）再比对；**锚点缺失时新建该标题，而非猜位置往别处插**。

**(b) 安全插入的成熟模式**：把笔记 parse 成 **mdast**（remark/unified 生态，活跃、庞大、维护良好），用 `unist-util-visit` 定位目标标题节点，只在「该标题到下一个同级/更高级标题之间」的节点范围内插入，**只 stringify 改动的那段、拼回其余原文**——其他 section 的用户手写内容**逐字节不动**。

- **现成实现**：`section-remark`（`vweevers/section-remark`，MIT）是这套模式的现成 proof-of-concept——「only transforms (or adds) one Markdown section … stringifies it and concatenates the result with the rest of your markdown, while other sections are left alone」。**但它 2020 后无维护、0 star**（`gh api` 核实，访问 2026-07-24）——**只能抄思路，不能当运行时依赖**。维护良好的底座是 remark/unified 本体（<https://github.com/remarkjs/remark>）+ `unist-util-visit` + `mdast-util-*`。（来源：`vweevers/section-remark` <https://github.com/vweevers/section-remark>；remark 生态；访问 2026-07-24）
- **零依赖版（据此推断，最稳）**：不引 mdast 也行——按行扫到锚点标题行，向下扫到**下一个 `#` 级别 ≤ 当前**的标题行，在其前一行插入新内容。这正是 #3 阶段 4「在其笔记『来源记录』追加内容」要的操作，实现十几行、无外部解析依赖、对用户其余手写内容零风险。
- **铁律**：**只在 section 内追加，绝不整文件重写；用稳定归一化字符串匹配锚点；锚点缺失就建标题。**

---

### 5. 能抄什么 / 不能抄什么：两套字段书写约定候选（Q5）

给 #7 的 prototype 会话两套可直接上手的约定（含真实片段，字段取自 #3 定稿）。

#### 约定 A（推荐）：frontmatter-first + 保真原文进正文 + 复杂数据进 JSON 边车

正式人物笔记 `20-People/本雅明·内塔尼亚胡.md`：

```markdown
---
type: person
子类型: 政党                      # 机构才有；人物可省
aliases: [Bibi, 比比]            # 由 entities.json 派生，扁平数组
tags: [以色列, 中东政治]
首见: EP12@00:34:02
---
# 本雅明·内塔尼亚胡

## 概述
以色列政治人物。（首次创建时一句话定位）

## 相关笔记
- [[利库德集团]]、[[2023 以色列司法改革]]

## 来源记录
- [[EP12 中东局势]] 00:41:22 —— 「把极右翼的本-格维尔拉进来才凑够 64 席」
```

- **机器真相**：`type`/`子类型`/`aliases`/`tags` 全在 frontmatter，`python-frontmatter` 直读；别名对象（带 `语域`/`来源已查证`）在 `entities.json`，`aliases:` 由其派生。
- **保真层**：「来源记录」下的原话是 prose，照抄无损，`[[双链]]` + 时间戳人读友好。
- **不需要任何 Dataview 解析**。下游派生解析器 = 标准 YAML + JSON，零单厂依赖。
- **成对字段落法**：`时限原文` 进正文 prose，`时限规范`（机械解析出的日期）进 frontmatter 或预测专用 JSON——**不在正文里 `时限规范:: 2025-01` 让下游去 parse 行内字段**。

#### 约定 B：Dataview 行内字段——**只在 `_review/` 草稿用**

阶段 2 草稿 `_review/EP12_draft.md`（消费者是阶段 4 的 Claude Code = LLM，容忍松散语法）：

```markdown
## 三、论断

- C-63：内塔尼亚胡靠拉本-格维尔凑够 64 席组阁
  时态:: 过去
  性质:: 陈述
  原文表述:: 本-格维尔
  归因类型:: 无外部归因
  时间戳:: 00:41:22

- C-64：美联储政策空间已经很小了
  时态:: 当下
  性质:: 陈述
  数据点:: 是
  指标名:: 美联储资产负债表规模
  潜在数据源:: FRED WALCL
  时间戳:: 00:47:10
```

- **能抄**：草稿里 `key:: value` 每条论断一组、人审时好读好改；`时态::`/`性质::` 一眼可见；这是 Dataview 语法**唯一安全的用武之地**。
- **不能抄**：**别把这套原样搬进正式笔记当四愿景的机器真相**——一旦搬过去，就把「无外部解析器的单厂格式」变成了权威存储的解析入口。草稿→正式笔记的阶段 4 转换里，应把这些行内字段**归位**到 frontmatter / JSON 边车。
- **关系表达**（#3 §10）同理：草稿里 `- [[A]] —[同盟]→ [[B]]` + `关系原文::` 好读；但若四愿景要**图谱的边**，建议阶段 4 **把关系镜像进一份边车 `edges.json`**（`{from, to, 大类, 原文, 集数, 时间戳}`），别让下游靠解析正文行内字段来重建图——这是正文行内字段唯一「载荷型」的地方，务必镜像。

**一句话给 #7**：拿**约定 A** 做正式笔记的实物模板；**约定 B** 只做 `_review/` 草稿的实物模板；两者之间的「行内字段归位到 frontmatter/JSON」是阶段 4 的转换职责，不是模板要解决的。

---

## 对 story-machine 的影响

落到 spec 的具体章节：

1. **spec 第 5 节「Vault 结构与模板」+ 第 7 节「关键设计原则」**：建议新增一条原则——**「机器真相分层」：下游程序读的数据落 frontmatter（页级扁平）或 JSON 边车（复杂/关系型）；正文只放保真原文 prose + `[[双链]]` + 固定标题锚点。正式笔记正文不得出现被下游当唯一机器真相直读的 `key:: value` 行内字段。**
2. **#1 地图的地基决策措辞**：原表述「结构化 Markdown = frontmatter + 行内字段 + 固定标题锚点」里的**「行内字段」需要限定**——它安全的作用域是 `_review/` 草稿（LLM 消费），不是四愿景直读的正式笔记。建议在地图上把这条风险与限定记一笔（本票不改地图，交编排器/人处理）。
3. **确认 #3 已做对的部分**：`entities.json`/`sources.json` 作为复杂数据的机器真相、frontmatter `aliases:` 派生生成——这套分层是对的，建议 spec 显式化为通用规则并让 #7 遵循。
4. **#7 prototype 直接可用**：约定 A（正式笔记）+ 约定 B（草稿）两套片段可直接拿去做实物给用户过目；阶段 4「行内字段归位」的转换责任要在 #7 的说明里点明。
5. **派生解析器选型（下游票的输入）**：解析正式笔记 = `python-frontmatter`（frontmatter）+ 标准 `json`（边车）+ 十几行的锚点 section 安全插入器（零依赖或 remark）。**不需要、也不建议**在管线里常驻 Node+Dataview 或自研 Dataview 行内字段解析器。
6. **参数/约定取值**：锚点标题文本（`## 概述`/`## 相关笔记`/`## 来源记录`）应在 spec 里**列成固定清单**当契约；frontmatter 字段只用 Obsidian Properties 原生支持的扁平类型（Text/List/Number/Checkbox/Date），**不用嵌套对象**（Properties UI 不能编辑嵌套）。

---

## 未决问题

（调研中冒出、超出本票范围，供开新票；不在本票顺手研究）

1. **关系图谱的边车格式**：若四愿景（尤其求真引擎/资产分析框架）要消费实体间关系，正文的关系块是否需要镜像进 `edges.json`？格式、与 `entities.json` 的一致性、谁在阶段 4 写——是独立的数据建模决策，建议开票。
2. **`_review/` 草稿→正式笔记的「行内字段归位」转换**：阶段 4 把草稿里的 `key:: value` 归位到 frontmatter/JSON 的具体映射表与实现，属于阶段 4 流程票，不在本票。
3. **frontmatter 扁平类型 vs #3 复杂字段的完整映射**：#3 定稿字段（预测的 6 个字段、归因的 5 类、数据点字段组）逐一落到「frontmatter / JSON 边车 / 正文」的完整对照表，值得在 #7 或一张专门的「字段落位表」票里定死。
4. **锚点标题的国际化/用户改名防护**：是否需要在标题旁加隐藏稳定标记（如 HTML 注释 `<!-- anchor:sources -->`）以防用户改标题文本导致锚点失配——是模板健壮性的细节权衡，实跑遇到再定。
5. **派生文件的刷新时机与增量**：下游「吃解析器派生文件」——派生文件何时重算、全量还是增量、放哪——是管线工程问题，另票。
