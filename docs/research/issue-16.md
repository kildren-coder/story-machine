# Simple Graph Builder 研究：实体消歧管线对本项目的参考价值

> AFK 调研文档，服务于 [#16](https://github.com/kildren-coder/story-machine/issues/16)，给「实体索引与消歧机制」（[#8](https://github.com/kildren-coder/story-machine/issues/8)）供弹药。本文只调研，不做决策。
>
> 调研对象：[`junhewk/simple-graph-builder`](https://github.com/junhewk/simple-graph-builder)（MIT，TypeScript，Obsidian 插件，默认分支 `master`，`pushed_at` 2026-05-16，8 stars）。以下简称 **SGB**。
> 全部代码引用访问日期 **2026-07-22**，来自 `master` 分支；行号以该日快照为准。

---

## 问题

票面要挖四件事（以票面 Question 为准，无评论修订）：

1. **分级消歧管线**：哈希精确匹配 → embedding 相似度 → LLM 兜底，每一级的触发条件、阈值、成本控制怎么写。
2. **"同一实体多种表述"（别名）怎么处理**：有没有类似我们「语域/立场」这种精细维度，还是纯字符串/语义相似度。
3. **触发时机**：自动 on-save vs 批量分析，各自的并发写入/一致性怎么处理（对应 #8 的"并发写与崩溃一致性"）。
4. **哪些设计不适用**我们的场景，明确指出差异，避免生搬硬套。

---

## 结论（TL;DR）

**一句话**：SGB 的**分级顺序和前四级（免 API 的哈希/别名精确匹配）可以近乎照抄**，是 #8 匹配流程的现成骨架；**embedding + LLM 两级思路可借鉴但要因为我们的"人工核对闸门"和"对象化别名"改写**；**并发写、崩溃一致性、`sources.json`、别名的语域/来源维度它全都没有，是 #8 必须自己设计的部分**。

一个贯穿全文的关键发现：**SGB 是一个"降级移植版"**。它的设计文档 `docs/KNOWLEDGE_GRAPH.md` 描述的是一套原生 **Python + PostgreSQL + pgvector（HNSW ANN 索引）** 的服务端管线（来自作者的 "Article Gatherer" 项目）；而**实际能跑的 Obsidian 插件**把这套东西降级成了**单进程、内存 Map + 防抖写单个 JSON**。**并发/一致性这一问，两套答案完全不同**——原版靠 PostgreSQL 的事务与 `UNIQUE` 约束天然安全，插件版则几乎没有任何并发保护。我们要抄的是"算法分级"，不是"插件的存储实现"。

具体到 #8 的落地粒度：

| 部分 | 归类 | 说明 |
|---|---|---|
| **分级顺序**（cache → session → exact name → alias → embedding → LLM → new） | **抄** | 直接作为 #8 匹配流程的主干；前四级零 API、O(1)，覆盖绝大多数命中 |
| **exact/alias 哈希精确匹配**（`Map<lowercase 表述, node>`） | **抄（键改成 `表述` 字段）** | 我们别名是对象，匹配键仍是 `表述`（小写），逻辑照搬 |
| **把已知标准名塞进抽取 prompt**（让抽取阶段就复用规范名） | **抄** | 直接用在阶段 2 Gemini Flash 抽取，是最便宜的一道去重 |
| **阈值默认值** 0.90 / 0.80（高置信自动合并 / 中间带 LLM 兜底） | **抄作起点** | 若我们启用 embedding，这是 #8 的参数默认值 |
| **持久化"决议缓存"**（`表述 → nodeId`，跨会话记住判定） | **抄，但要过人工闸门** | 见下方 Y 项风险 |
| **embedding 相似度 + LLM 兜底判定** | **改写（Y）** | SGB 只对**实体名**做 embedding、且**高置信自动合并不经人**——与我们的评论/审校闸门冲突；且名称歧义在政经题材更严重 |
| **别名结构**：flat `string[]` → 我们的**别名对象**（`表述/类型/语域/来源/来源已查证/首见`） | **改写（Y）** | 匹配逻辑能复用，但别名的**写入/合并/派生**要重做；SGB 的 `nodeByAlias` 假设"一个表述全局只属于一个实体" |
| **并发写 + 崩溃一致性** | **自己设计（Z）** | 插件版没有；且存在一个真实的一致性 bug（hash 先落盘、图谱防抖后落盘）可作反面教材 |
| **`sources.json`（归因索引）、信源跨集去重** | **自己设计（Z）** | SGB 完全没有这个概念，provenance 只有一个 `sourceNotes: string[]` |
| **别名的"语域/立场"维度** | **自己设计（Z），但与它的匹配算法正交** | SGB 的消歧是"是否同一实体"（共指），根本没有"这个表述在什么语域下被使用"的维度 |

---

## 论证

### 0. 两个 SGB：Obsidian 插件（能跑）vs. Python 原版（设计文档）

`docs/KNOWLEDGE_GRAPH.md`（[repo 内](https://github.com/junhewk/simple-graph-builder/blob/master/docs/KNOWLEDGE_GRAPH.md)，访问 2026-07-22）是**一手设计意图来源**，但它描述的是作者原版的服务端实现，不是插件：

- 原版存储：PostgreSQL + pgvector，`kg_entities` 表 `canonical_name VARCHAR UNIQUE`、`embedding VECTOR(1536)`、`aliases TEXT[]`，`hnsw (embedding vector_cosine_ops)` ANN 索引；relationships 有 `UNIQUE(source,target,type)` 约束和 `ON DELETE CASCADE`（文档 116–155 行）。
- 原版声称成本 **~$1.60 / 200 篇文章**（抽取 GPT-4o-mini $0.80 + embedding text-embedding-3-small $0.50 + LLM 验证 $0.30），对比 Microsoft GraphRAG $50–100+（文档 205–216 行）。
- 文档明确说实体类型**是要按领域自定义的**（"Step 1: Define Entity Types"，示例给了 `MEDICAL_CONDITION` / `REGULATION` 等，文档 235–253 行）。所以插件里"严格 10 类"不是这套方法的硬约束，只是插件的默认选择。

> **事实 vs 推断**：上面是文档直接写明的（事实）。**据此推断**：插件把"PostgreSQL 事务 + UNIQUE 约束 + HNSW"这套并发/一致性/检索基础设施，降级成了"单进程内存 Map + 线性扫描 + 防抖写 JSON"——因为 Obsidian 插件不能假设有数据库。这个降级正是"并发一致性"这一问在插件里几乎无解的根因。

下面除非特别说明，均以**插件实际代码**为准（那才是我们能读、能抄的东西）。

---

### 1. 分级消歧管线：顺序、触发条件、阈值、成本控制

核心在 `src/graph/resolver.ts`（`EntityResolver` 类）。类头注释（`resolver.ts:6-17`）自述了 7 级优先级，与实际代码一致：

| 级 | 名称 | 触发条件 | 代价 | 代码位置 |
|---|---|---|---|---|
| 1 | **持久决议缓存** | 该"表述"以前解析过（跨会话） | O(1)，零 API | `resolver.ts:72-89` → `cache.getResolvedNodeId` |
| 2 | **会话缓存** | 本次会话已解析过同名 | O(1)，零 API | `resolver.ts:91-96` |
| 3 | **精确名匹配** | `name.toLowerCase().trim()` 命中 `nodeByName` | O(1)，零 API | `resolver.ts:98-110` → `cache.getNodeByName` |
| 4 | **别名匹配** | 小写表述命中 `nodeByAlias` | O(1)，零 API | `resolver.ts:112-125` → `cache.getNodeByAlias` |
| 5 | **高置信 embedding** | 余弦相似度 ≥ `resolutionThresholdHigh`(0.90) | 1 次 embedding API | `resolver.ts:232-258` |
| 6 | **LLM 兜底** | 相似度落在 `[Low, High)` = `[0.80, 0.90)` 且开启 LLM 验证 | 每个候选 1 次 LLM 调用 | `resolver.ts:260-299` |
| 7 | **新建实体** | 以上全不中 | 零 API | `resolver.ts:132-143` |

**关键点，逐条对上票面：**

- **"哈希精确匹配"实为小写字符串精确匹配，不是 cyrb53 哈希**。第 3/4 级用的是 JS `Map`，键是 `name.toLowerCase()`（`cache.ts:212`）和 `alias.toLowerCase()`（`cache.ts:219`）——即"哈希表 O(1) 查找 + 精确字符串相等"。真正的 cyrb53 哈希（`src/graph/hashes.ts:24-41`）**只用于检测笔记内容是否变化**（增量分析的跳过判断），**与实体名匹配无关**。票面把两者并列成一条链，实际是两码事——这个区分对 #8 很重要。

- **实体 ID 本身就是去重键**：`generateNodeId = `${entityType.toLowerCase()}:${name.toLowerCase().trim()}``（`merge.ts:11-13`）。所以"同类型同名"天然折叠成同一节点。注意一个不对称：**精确名/别名匹配是跨类型的**（`getNodeByName` 不按 entityType 过滤，`cache.ts:349-351`），但 **embedding 匹配严格限定同 entityType**（`cache.ts:735`、`762`：`node.entityType !== entityType` 就跳过）。

- **阈值默认值**（`src/settings.ts:129-137`，`DEFAULT_SETTINGS`）：
  - `resolutionThresholdHigh = 0.90`（≥ 自动合并，不问人）
  - `resolutionThresholdLow = 0.80`（`[0.80, 0.90)` 交给 LLM 判）
  - `enableEmbeddings = false`（**默认关闭，opt-in，明确为了省 API 成本**——注释原文 "embeddings are opt-in to avoid API costs"，`types.ts:326`）
  - `enableLLMVerification = true`
  - 设计文档还给了调参指引（`KNOWLEDGE_GRAPH.md:283-295`）：更保守用 0.95/0.85（少误合并），更激进用 0.85/0.75。并声称 LLM 验证只落在 **~5-10% 的实体**上（`KNOWLEDGE_GRAPH.md:110`）。

- **成本控制怎么写的**（这是票面重点）：
  1. **分级本身就是成本控制**：前 4 级零 API，覆盖绝大多数命中；只有 miss 才进 embedding，只有落在 `[0.80,0.90)` 才花 LLM。
  2. **embedding 默认关**。关掉后 `mergeExtractionIntoCache`（无 resolver 的基础版，`merge.ts:87-152`）只做精确名匹配，整条管线**零 embedding、零 LLM 花费**。
  3. **批量 embedding**：`resolveBatch` 先一趟把能用缓存解决的解决掉，剩下的攒成一批一次 API 拿全部向量（`resolver.ts:176-203`、`311-350`；OpenAI `input: texts` 一次多条 `llm-client.ts:386-408`，Gemini `batchEmbedContents` `llm-client.ts:410-437`）。
  4. **只对实体名做 embedding**，不带描述（`resolver.ts:218` `getEmbeddings(opts, [name])`）——省 token，但也是精度短板（见 §4）。
  5. **决议缓存持久化**：命中过的判定写进 `resolutionCache`（`表述 → nodeId`）落盘，下次直接 O(1)（`cache.ts:580-584`）。
  6. **LLM 验证出错默认不合并**（`llm-client.ts:691` `return false`）——宁可漏合并也不误合并，成本与正确性都偏保守。

- **相似度实现**：纯 JS 余弦（`llm-client.ts:476-495`），每次查询对**全部** embedding 线性扫描 O(N·dim)（`cache.ts:725-745`）。插件版**没有 ANN 索引**（原版才有 pgvector HNSW）。我们规模（每项目累计实体量估计几百到低几千）线性扫完全够用。

---

### 2. 别名 / "同一实体多种表述" 的处理

**结论先行：SGB 是纯字符串 + 纯语义相似度，别名就是一个 `string[]`，没有任何"语域/立场/来源"维度。**

- 数据结构：`OntologyNode.properties.aliases?: string[]`（`types.ts:166`）。设计文档的 PostgreSQL 版也一样是 `aliases TEXT[]`（`KNOWLEDGE_GRAPH.md:123`）。**两层都是扁平字符串数组**。
- 别名怎么产生：命中第 5/6 级（embedding 高置信或 LLM 判定同一实体）时，把这次抽取到的表述作为**新别名**加到目标节点（`resolver.ts:248`、`288` → `cache.addAliasToNode`）；手动合并时把源节点的名和别名全部转移（`resolver.ts:395-404`）。
- 别名索引：`nodeByAlias: Map<string, node>`，键是小写表述（`cache.ts:29`、`219`）。**`addAliasToNode` 显式保证"一个表述全局最多属于一个节点"**：若该表述已属于别的节点就拒绝加入（`cache.ts:386-387`）。
- "同一实体多表述"靠什么判定为同一？——**共指（coreference）**：要么表述串命中别名表，要么名字 embedding 足够近，要么 LLM 回答 "yes"。LLM 的判定 prompt（`llm-client.ts:669-683`）问的是"这两个是不是**同一个现实世界实体**"，例子是 `"AI"` / `"Artificial Intelligence"` = yes、`"Apple (company)"` / `"apple (fruit)"` = no。**它没有、也不需要"这个表述在什么语域/立场下被使用"的概念**——那是描述性元数据，不影响"是不是同一实体"的判断。

对上票面：**它没有类似"语域/立场"这种精细维度，是纯字符串 + 纯语义相似度。** 我们的别名对象（`表述/类型/语域/来源/来源已查证/首见`，见 [#8](https://github.com/kildren-coder/story-machine/issues/8) 与 spec 决议）在它这里完全没有对应物。

> **关键澄清（避免生搬硬套时想歪）**：语域/立场维度**与 SGB 的匹配算法正交**。SGB 回答的是"A 和 B 是不是同一实体"；我们的语域/来源字段回答的是"表述 A 是在什么语境下、由谁提出的"。后者不改变前者的判定，只是在**别名对象落库那一步**多写几个字段。因此我们可以照抄它的"匹配分级"，同时在别名写入层挂上我们的对象化结构——两者不打架。

---

### 3. 触发时机与并发 / 崩溃一致性

**三种触发入口**（`src/commands/analyze.ts` + `src/main.ts`）：

1. **手动单篇**：命令 `analyze-current-note` → `analyzeCurrentNote`（`analyze.ts:14`）。
2. **自动 on-save**：设置 `autoAnalyzeOnSave`（**默认 false**，`settings.ts:118`）。注册在 `vault.on('modify')`（`main.ts:36-42`），外层包 `debounce(…, 2000, true)`——**存盘后等 2 秒静默期再分析**（`main.ts:18-22`）。
3. **批量整库**：`analyzeEntireVault`（`analyze.ts:298`）——**串行 for 循环**逐篇跑，每次成功 API 调用后 `sleep(500)` 限速（`analyze.ts:364-367`）。

**并发控制——只有一个模块级布尔量：**

- `vaultAnalysisState = { isRunning, isCancelled }`（`analyze.ts:8-12`），进程内单例。它防两件事：不能同时跑两次整库分析（`analyze.ts:302-305`）；整库跑的时候自动 on-save 直接跳过（`analyze.ts:414-416`）。
- **没有文件锁、没有跨进程锁、没有队列**。手动单篇分析（`analyzeCurrentNote`）**不检查** `isRunning`，可以和别的路径交叠。全靠 JS 单线程事件循环——内存 Map 的每次写是同步原子的，但 `await`（API 调用、防抖存盘）之间会交错。

**持久化模型**（`src/graph/cache.ts`）：全部状态塞进 Obsidian 的 `plugin.loadData()/saveData()`，写的是**插件目录下单个 `data.json`**（图谱节点+边、`resolutionCache`、`embeddingIndex`、settings、hashes 全在一个 blob 里）；embedding 向量单独存二进制 `embeddings.bin`（`llm-client.ts:547-605`）。写盘是**防抖 1000ms**（`SAVE_DEBOUNCE_MS = 1000`，`cache.ts:6`、`781-788`）的**全量覆盖写**——`flush()` 把整个 `nodes/edges` 数组序列化后整体 `saveData`（`cache.ts:793-838`）。**没有原子写（临时文件+rename）、没有 journal、没有 WAL。**

**崩溃一致性——插件里有一个真实可复现的坑**（对 #8 直接有用的反面教材）：

- 在 `analyzeCurrentNote` 里，抽取合并（改内存 → `markDirty` → 防抖 1s 后才落盘）之后，**立刻同步落盘 hash**：`await saveHashes(...)`（`analyze.ts:110-112`）。也就是说 **hash 先持久化，图谱改动还压在 1 秒防抖里**。
- 若这 1 秒窗口内进程崩溃/被杀：**hash 说"这篇已分析"，但它贡献的图谱节点丢了**。下次分析 `hasNoteChanged` 看 hash 相同直接跳过（`hashes.ts:46-49` + `analyze.ts:223`）→ **这篇内容永久不再进图谱**，除非手动 remove/clear 重来。
- 更隐蔽的一层：`saveHashes` 和 `cache.flush()` 是**两条独立的"读-改-写整个 `data.json`"路径**。`flush()` 先 `await loadData()` 拿快照，改自己那几段再 `saveData()`（`cache.ts:807-835`）——如果这中间另一条 `saveHashes` 完成了写入，`flush()` 会用旧快照把它覆盖掉。进程内也不安全。

> **事实 vs 推断**：三个入口、防抖参数、`isRunning` 单例、hash 先于图谱落盘——都是代码直接可读（事实）。"1 秒窗口崩溃 → 永久漏一篇"和"两条写路径互相覆盖"是**据代码推断的失败场景**，我未实机复现，但路径清晰、置信度高。

**对上票面**：SGB 插件版**基本没有为"并发写与崩溃一致性"做任何设计**——它假设单进程、单写者、优雅退出。设计文档里的 PostgreSQL 原版才有真正的并发安全（事务 + `UNIQUE` 约束）。而 [#8](https://github.com/kildren-coder/story-machine/issues/8) 的场景是"用户可能同时跑多集处理，两个 json 都会被多进程写"——**这正好是 SGB 最薄弱、最不能照抄的地方**。

---

### 4. 哪些设计不适用我们的场景（差异清单）

| SGB 的做法 | 我们的场景 | 为什么不能照搬 |
|---|---|---|
| **别名 = flat `string[]`**，`nodeByAlias` 假设一个表述全局只属于一个实体 | 别名 = **对象**（`表述/类型/语域/来源/来源已查证/首见`），来源还要"已查证"标记 | 索引值结构变了；别名的写入/合并/去重逻辑要重做；派生 Obsidian `aliases:` 扁平数组是我们额外的一步（#8 明确要） |
| **embedding 只对实体名做** | 政经/百年史题材**重名严重**（同名政治人物、同名地名、机构简称撞车） | 名称 embedding 区分力不够；描述性上下文只在 LLM 那一步才用到。要么改成 name+描述一起 embedding，要么更依赖人工闸门 |
| **高置信（≥0.90）自动合并，不问人** | **人工核对是非协商闸门**（spec §7.5、CONTEXT 非协商第 3 条），事实进图谱前必须过 `_review/` | 不能让程序自动 merge 进正式笔记网。合并动作要么只在阶段 4（Claude Code）产出"建议合并"供审校，要么只放行 exact/alias 两级，embedding/LLM 级一律降级为"待人确认" |
| **持久决议缓存自动记住判定**（`表述→nodeId`） | 判定可能是错的（Gemini 抽取阶段就可能识别错实体名） | 缓存会把一次错判固化并跨会话复用，绕过审校。要么缓存只存过了闸门的判定，要么给缓存加失效/回灌机制 |
| **严格 10 类扁平本体**（PERSON/ORGANIZATION/…/TOPIC，`types.ts:43-69`） | 我们类型更细，**含机构子类型**；核心是人物/事件/地区/概念/时期 + 机构类 | 类型体系本身要换（文档说本来就该按领域自定义，可行）；但注意 embedding 匹配按 entityType 精确相等过滤（`cache.ts:735`），有子类型时要想清楚过滤粒度（顶层类型 or 子类型） |
| **单进程内存 Map + 防抖全量写 JSON**，无锁无原子写 | 多集并发处理、两个索引（`entities.json` + `sources.json`）多进程写 | 存储/并发层要整个自己设计：单写者队列或文件锁 + 原子写（临时文件 + rename）+ 把 hash 落盘与图谱落盘绑成一次事务，避免它那个"hash 先落盘"的坑 |
| **provenance 只有 `sourceNotes: string[]`** | 我们要 `sources.json`（`补全状态/媒体/作者/链接/发表日期/置信度/被引用于`）+ **信源跨集去重**（`S-NNNN` 分配） | SGB 完全没有归因索引这个概念，Z 项，全自己设计 |
| **chunk ≈ 500 token，最多 3 并发抽取**（`prompts.ts:11`、`llm-client.ts:51-87`） | 我们 chunk 是 20–30 分钟 ≈ 1–2 万 token（spec §1 阶段 1） | 粒度目的不同（它切任意 Obsidian 笔记，我们切逐字稿）。chunk 策略不参考，但"把已知标准名喂进抽取 prompt 让其复用规范名"这个**便宜去重技巧值得抄到阶段 2** |

---

## 对 story-machine 的影响（落到 spec 具体环节）

对应 spec `audio-obsidian-pipeline-spec.md` 与 #8 的范围：

1. **阶段 4 · 步骤 1「实体匹配与合并」（spec §4）——抄 SGB 的分级骨架。**
   #8 的匹配流程建议直接采用 SGB 的顺序：**决议缓存 → 精确名匹配（`表述`）→ 别名匹配（`表述`）→ （可选）embedding → （可选）LLM 兜底 → 新建**。前三级零 API、O(1)，用 `Map<lowercase 表述, 实体>` 实现（照抄 `cache.ts` 的 `nodeByName`/`nodeByAlias` 思路，键从 SGB 的 `name`/`alias` 字符串换成我们别名对象的 `表述` 字段）。

2. **阶段 2 · Gemini Flash 抽取（spec §4 阶段 2）——抄"已知标准名注入 prompt"。**
   SGB 在抽取 prompt 里塞进现有实体名让 LLM 复用规范名（`prompts.ts:58-61`，取前 100 个）。这是最便宜的一道去重，且发生在草稿生成时、正好赶在人工核对之前——建议在阶段 2 就把 `entities.json` 的标准名（+ 常用别名表述）喂给 Gemini。

3. **消歧的"谁来判"（#8 明确的开放点）——分级路由到不同裁决者，尊重审校闸门。**
   建议：
   - **exact/alias 精确命中** → 程序规则自动判定（安全，零成本）。
   - **模糊命中** → **不自动合并进正式笔记**。可复用 SGB 的 `verifyEntityMatch` prompt（`llm-client.ts:669-683`）作为**给人看的合并建议**，但最终裁决权留在阶段 3/阶段 4 的人工/Claude Code 环节。**不要照搬它 ≥0.90 自动 merge 的行为**——那违反 CONTEXT 非协商第 3 条与 spec §7.5。

4. **是否引入 embedding——建议 MVP 先不上，与我们的成本纪律一致。**
   - SGB 自己就把 embedding 设为 `enableEmbeddings = false` 默认关（`settings.ts:130`），关掉后纯精确/别名匹配即可工作。这与我们"省 Claude 额度、Gemini 走免费额度"的取向一致。
   - 若日后要上：**Gemini 的 `gemini-embedding-001` 有免费额度**（官方 [ai.google.dev/gemini-api/docs/pricing](https://ai.google.dev/gemini-api/docs/pricing)，访问 2026-07-22；付费 $0.15/1M，batch $0.075/1M），比 OpenAI `text-embedding-3-small` 的 $0.02/1M（官方模型卡 [developers.openai.com](https://developers.openai.com/api/docs/models/text-embedding-3-small)，访问 2026-07-22）更贴合我们已在用 Gemini 免费额度的现状。**据此推断**：若上 embedding，优先 Gemini 免费额度，避免新增 OpenAI 依赖。
   - 参数起点直接用 SGB 默认：High=0.90 / Low=0.80；政经题材重名多，宁可保守，可取文档建议的 0.95/0.85 减少误合并。

5. **别名对象化——匹配逻辑复用，写入/派生自己写（#8 的 `entities.json` 结构）。**
   - 匹配键仍是 `表述`（小写），照抄 SGB。
   - **要重写**的是：别名对象的新增/合并（带 `语域/来源/来源已查证/首见`）、以及从别名对象数组**派生** Obsidian frontmatter 的扁平 `aliases:`（#8 明确要的方向）。SGB 的 `addAliasToNode`（`cache.ts:372-399`）可作参考实现（它处理了"别名等于本名""别名已存在""别名属于他人"三种拒绝情形），但字段结构要换。
   - 注意 SGB 的"一个表述全局只属于一个实体"约束（`cache.ts:386-387`）我们大概率要保留（呼应铁律"同一实体必须用同一名字"），但要在别名对象层面判重。

6. **并发写 + 崩溃一致性（#8 的第三块）——自己设计，拿 SGB 当反面教材。**
   - SGB 插件版**没有**可抄的东西；它的 `data.json` 全量覆盖写 + 无锁 + hash 先于图谱落盘，恰恰是我们要避免的。
   - 建议 #8 采纳：**单写者**（一个处理进程持锁写 `entities.json`/`sources.json`，或用 OS 文件锁 / lockfile）；**原子写**（写临时文件再 `rename`）；**把"标记已处理"与"图谱/索引落盘"绑成同一次提交**，杜绝 SGB 那个"hash 已存、节点丢失、永久漏一集"的窗口。设计文档里的 PostgreSQL 原版（`UNIQUE` + 事务）是"正确形态"的参照，但我们无需引入数据库，用文件锁 + 原子 rename 即可达到单机够用的一致性。

7. **`sources.json` 与信源跨集去重（#8 新增部分）——SGB 无参考，全自己设计。**
   SGB 的 provenance 只有 `sourceNotes: string[]`（哪些笔记提到过），没有信源实体、没有跨文档去重、没有 `媒体` 字段与机构标准名对齐的机制。#8 这部分从零设计，SGB 不供弹药。

---

## 未决问题（超出本票范围，供开新票）

1. **embedding 到底要不要上、什么时候上**：涉及成本/额度权衡与政经题材重名的实际严重程度，需要跑几集真实数据看精确/别名匹配的漏合并率再定。属参数与选型决策，应在 #8 或专门的"消歧引擎选型"票里决。
2. **模糊消歧的裁决者归属**：程序规则 / LLM / 人 的边界，与阶段 3 人工闸门、`_pairs` 校对配对数据如何联动——牵涉流程设计，建议在 #8 内细化或另开票。
3. **决议缓存与人工闸门的耦合**：缓存只存"过闸"判定，还是允许缓存未审校判定并事后回灌/失效——一致性与审校纪律的交叉点，值得单独讨论。
4. **别名的"语域/立场"维度的具体取值域与填充时机**：本调研只确认 SGB 没有此维度、且它与匹配算法正交；这个维度自己怎么定义、谁来填、是否需要 LLM 辅助标注，超出本票（本票只回答"能不能抄 SGB"）。

---

## 附：一手来源清单（均访问于 2026-07-22）

- SGB 仓库主页与许可证：<https://github.com/junhewk/simple-graph-builder>（MIT）
- 消歧管线：`src/graph/resolver.ts`、`src/graph/cache.ts`、`src/graph/merge.ts`、`src/graph/hashes.ts`
- 抽取与 LLM/embedding 客户端：`src/extraction/prompts.ts`、`src/extraction/llm-client.ts`
- 类型/本体/阈值默认值：`src/types.ts`、`src/settings.ts`
- 触发时机与事件注册：`src/commands/analyze.ts`、`src/main.ts`
- 原版设计意图（Python/pgvector）：`docs/KNOWLEDGE_GRAPH.md`
- OpenAI 嵌入定价（`text-embedding-3-small` $0.02/1M）：<https://developers.openai.com/api/docs/models/text-embedding-3-small>（官方模型卡）
- Gemini 嵌入定价与免费额度（`gemini-embedding-001` 免费额度 + $0.15/1M）：<https://ai.google.dev/gemini-api/docs/pricing>（官方定价页）

> 二手来源（**低置信**，仅作旁证，未采入结论）：Gemini 免费额度各家博客汇总（geotoolbox.ai、aifreeapi.com 等）给出的"embedding 免费额度 RPM/TPM"数字互相不一致，本文未采用其具体数值，只采用了 Google 官方页确认的"有免费额度"这一定性事实。
