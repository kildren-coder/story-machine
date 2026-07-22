# Gigafact Parser 研究：断言抽取与发言人标注的架构参考

> AFK 调研票 [#17](https://github.com/kildren-coder/story-machine/issues/17)。为「归因补全流程与额度分配」（[#13](https://github.com/kildren-coder/story-machine/issues/13)）供弹药，自身不做决策；与「说话人分离方案选型」（[#15](https://github.com/kildren-coder/story-machine/issues/15)）弱相关不阻塞。
>
> **来源限制声明**：Gigafact Parser 是闭源托管服务，读不到代码。本报告是**架构层借鉴**，不是实现细节。全文用【确认】/【存疑·公开材料未明】两类标记严格区分事实与不可证内容；换算/推理处标「据此推断」。所有网页来源访问日期均为 **2026-07-22**。

---

## 问题

Gigafact Parser（[gigafact.org/parser](https://gigafact.org/parser/)）是一个面向新闻编辑室的 AI 工具，从政客/公众人物的音视频里自动转写、抽取"断言（claim）"并标注"是谁说的"。本票要挖四件事，都是给我们**归因层（#13）**和**说话人层（#15 下游 schema）**当参照：

1. 它怎么定义/抽取 "claim"，怎么把断言跟"是谁说的"绑定；
2. 公开材料里有没有透露**置信度/校验机制**（对照我们"置信度与依据必填"的要求）；
3. **处理速度/成本**的公开数据（如"100+ 小时人工 → 2 小时"），当吞吐量参照系；
4. 明确区分**能查到的**和**查不到只能存疑的**，不把营销页说法当技术事实。

---

## 结论（TL;DR）

**能确认的架构骨架（对我们有直接借鉴价值）：**

- Parser 的数据单元是 **claim → speaker → 数据库中的 canonical profile + 时间戳级原始录音引用** 的四元绑定。这与我们规划的 `claim → 发言人 → entities.json 规范名 + 时间戳 provenance` 架构**同构**——是对我们方向的一次外部印证。
- **发言人标注（speaker identification）是它专门反复迭代的难点**，不是顺带功能：官网 changelog 有独立的 "speaker identification is now 60% more accurate"（v1.7）、以及"广告/外部片段检测"（v1.75）——后者存在的理由正是"错误识别的语音段会污染 claim 归因"。
- 质量保证走的是 **人工在环（HITL）+ 可覆盖（override）+ 暴露模型推理 + 回链原始录音**，**不是**公开的数值置信度分数。官方明确"不允许 AI 自动从第三方网站抓取内容，Parser 让记者留在环里以保证入库内容高质量、准确"。
- 吞吐量量级：**机器**处理"一小时音频 → 分钟级"；**端到端人工时间**压缩约 50×（24 小时音频，人工"轻松超过 100 小时"→ Parser 工作流"两小时"），但那"两小时"含人工筛出 claim 列表，不是纯机器时间【据此推断】。而且这是"**发现** claim"的加速，**不含**事实查证。

**查不到、只能存疑的：**

- 底层用什么模型、claim 的算法定义/阈值、diarization 如何映射到具名 profile、是否内部存在数值置信度——公开材料一律没有。
- 任何准确率/错误率/幻觉率数据。连 partner 撰写的 Wisconsin Watch 长文里也**一句都没有**（跨两遍核验）。
- 任何金钱/单位算力成本（Parser 对 partner 免费，靠基金会资助）。

**对本项目的净建议（详见「对 story-machine 的影响」）：**

1. **确认**我们的"断言+发言人+规范实体+时间戳回链"绑定架构合理——Parser 就是这么落地的。
2. **#13 的"依据必填"**与 Parser 的"回链原始录音 + 暴露模型推理"高度契合，建议做成 **provenance-first**（每条归因必须能点回逐字稿的确切时间戳）。我们的"**置信度数值**必填"比 Parser 公开做的更严格——这是我们的加法，不是抄来的，Parser 无对照数据可支撑某个具体阈值。
3. **#15**：Parser 用血泪证明 **diarization 错误会向下传染成 claim 归因错误**；我们的 `语域`立场指纹强依赖发言人判对，必须给**人工覆盖**留位，并把**广告/开场白/花絮片段**当作已知失败模式。
4. **量级参照**支持"每天 1–2 集"节奏可行；但绝对数字不可照搬（英语 vs 中英混杂、政客闭集 vs 开放实体）。

---

## 论证

### 0. 研究方法与来源分级（先声明可信度）

票面判断"Parser 大概率不开源"，我做了一手核验：GitHub 用户 `gigafact` 存在但 **`public_repos: 0`**（`gh api users/gigafact`），仓库搜索 `gigafact parser` 无本体代码命中（`gh search repos`，返回的全是 Tesla Gigafactory / 电池仿真项目）。**确认：Parser 本体未在 GitHub 公开。** 因此只能读公开材料。

| # | 来源 | 类型 | 可信度 | 状态 |
|---|---|---|---|---|
| 1 | [gigafact.org/parser](https://gigafact.org/parser/) | 一手（官网产品页：营销 + 版本 changelog + 用户证言） | 高（但含营销口径，需与独立来源交叉） | 已读 |
| 2 | [gigafact.org 方法论页](https://gigafact.org/guidelines-principles-and-methodologies/) | 一手 | 高——**但描述的是人工 Fact Brief 编辑标准，不是 Parser 抽取逻辑，务必区分** | 已读 |
| 3 | [Wisconsin Watch 报道](https://wisconsinwatch.org/2025/06/wisconsin-watch-ai-fact-check-audio-misinformation-parser-gigafact/) | 二手（新闻报道） | 中——**Wisconsin Watch 是 Gigafact 的"early user and partner"，作者亲自"worked with Gigafact using Parser"，属 partner 撰写的正面报道，非独立评测** | 已读，取逐字引用 |
| 4 | [Techstination 访谈](https://www.techstination.com/interview.jsp?interviewId=5324) | 一手（联合创始人访谈） | —— | **未能访问正文**（音频页，只取到元数据：受访者 Robyn Sundlee，Gigafact 联合创始人，2024-09-25）。不据训练记忆脑补其内容。 |
| 5 | [INN 活动页](https://inn.org/event/inn-gigafact-finding-public-political-commentary-with-parser/) | 一手 | —— | **未能访问**（HTTP 403） |
| 6 | 资助/OpenAI 关系（Forbes、American Journalism Project） | 二手 | 低—中——**仅取自搜索引擎摘要，未逐字 fetch 全文** | 仅用于"底层栈"的循证推断，见 §5 |

> 因为最有价值的两个一手渠道（创始人访谈正文、INN 活动页）都没访问到，本报告的"确认"部分主要建立在官网 changelog 的**具体功能描述**上——这类描述比营销标语可信（它在列已发布的产品能力），但仍是厂商自述，未经独立复现。

### 1. Claim 的定义与抽取

**【确认】** Parser 抽取的是"有新闻价值的断言"，并把它作为一等公民对象呈现：

- 官网：Parser "can recognize comments and claims that have journalistic relevance"（能识别有新闻价值的评论与断言），"civic-smart"；profile 页有 "Highlighted Claims" 版块，即"the most important claims identified by our model"（我们的模型识别出的最重要断言）。
- Wisconsin Watch 逐字："identify specific claims made during the audio segment and even the person making the claim"；配图说明显示 claim 列在逐字稿**右侧栏**（一个 Ron Johnson 参议员访谈的截图）。

**【存疑·公开材料未明】**

- claim 的**算法/schema 定义**、什么阈值算"journalistically relevant"、是否像我们一样**给每条断言分类型**（史实/时事断言/观点）——公开材料完全没有。
- **务必区分**：方法论页（来源 2）里定义的"可查证 claim"标准——"answerable with a definitive 'yes' or 'no' using publicly available sources"、"explainable in 150 words or less"、"topical, substantive, moderate public engagement"——**是人工 Fact Brief 产品的编辑筛选标准，不等于 Parser 模型的抽取标准**。不要把这套人工标准当成 Parser 的技术定义来抄。

> 对我们的意义：Parser 佐证了"把 claim 抽成结构化一等对象、挂在逐字稿旁"这条路，但它**不分 claim 类型**（至少未公开），而我们 spec 阶段 2 的 `史实类/时事断言类/观点类` 三分类是我们特有设计——Parser 无对照，属我们的加法。

### 2. Claim → Speaker（"是谁说的"）的绑定

这是本票最核心的问题。**【确认】** 绑定是多层的：

1. **断言绑发言人**：官网/WW 都强调 "even the person making the claim"——claim 与说话人是绑定的。
2. **发言人识别是独立、被反复迭代的模块**（官网 changelog 逐字）：
   - v1.7 "Upload & Speaker ID Improvements"：**"Parser's speaker identification is now 60% more accurate"**；用户"can override the model's decision if it gets it wrong"，且"the model's reasoning is exposed to provide deeper transparency"；speaker identification 弹窗会提示逐字稿质量问题。
   - v1.75 "Smarter Transcripts"：**"Advertisement & External Clip Detection"**——重标广告与外部音频片段（如播客/电台里的插播），"increases the accuracy of extracted claims and subjects, and improves speaker identification"。→ **广告/外部片段检测存在的唯一理由，就是这些段落会被错分给主发言人、污染 claim 归因。**
3. **发言人归一到 canonical profile**：Parser 有一个预建的发言人**数据库**——"hundreds of national profile politicians in Congress, Senate and State roles"，"thousands of audio and video recordings transcribed and analyzed"。抽出的 claim 挂到对应 profile 下，形成"跨录音可检索的 claims/talking points 数据库"。
4. **provenance 回链**：每条 claim 带 "View in Transcript" 按钮（"exactly where that claim appears in the transcript"）+ "direct citations back to the original recording"——即**时间戳级、可回溯到原始音频**的出处。

**【存疑·公开材料未明】** 具体绑定算法：用的是哪种 diarization、如何把 diarize 出的匿名说话人段映射到**具名** profile（是靠已知声纹？靠元数据？靠人工？）、"60% more accurate" 是相对什么基线、绝对 DER 是多少——一律没有。

> 对我们的意义（**这是给 #13/#15 的核心弹药**）：
> - 我们规划的 `断言 → 发言人 → entities.json 规范名 + 时间戳 provenance` 四元绑定，与 Parser 的落地形态**同构**——外部印证方向没走偏。
> - Parser 把"发言人→具名 profile"做得相对轻松，**是因为它面对的是已知美国政客的闭集 + 预建 profile 库**；我们面对的是中英混杂、开放实体、无预建库，这一步对我们更难 → 强化对实体索引/消歧（开发优先级 #4）的投资。
> - Parser 专门为 speaker ID 做广告/片段检测，说明**播客类素材的插播/开场白/花絮是真实且必须处理的失败模式**（见「未决问题」）。

### 3. 置信度 / 校验机制

**【确认】** 公开材料里**没有出现任何数值置信度分数**。Parser 的质量保证是一套**定性 + 人工在环**机制：

- **HITL 硬闸**（官网逐字）："Gigafact does not allow AI to automatically ingest content from third-party websites. Parser keeps journalists in the loop to ensure content being added to the community database is high-quality and accurate."（不允许 AI 自动从第三方网站抓取；让记者留在环里保证入库质量与准确。）
- **可覆盖 + 推理透明**：用户可 override 模型判断；"the model's reasoning is exposed"。
- **质量旗标**：speaker ID 弹窗提示逐字稿质量问题；广告/外部片段检测降低误分。
- **区分产品**：Gigafact 的 **Fact Brief**（人工查证产品，非 Parser）用**二元 yes/no** 结论（"A 'yes' or 'no' conclusion is displayed at the top of the page"），无中间置信档，且"All Fact Briefs must be carefully reviewed by a newsroom editor"。**但这是下游人工查证的结论评级，不是 Parser 对抽取结果的置信度。**

**【存疑·公开材料未明】** Parser 内部**是否**对每条 claim / 每个 speaker 打了置信度分数（很可能有，用于驱动那些质量旗标，但从未公开）、任何准确率/错误率/幻觉率——Wisconsin Watch 全文（含 partner 视角）**零提及**（跨两遍核验确认缺席）。

> 对我们的意义（**给 #13**）：
> - Parser 的"依据"= **回链到原始录音 + 暴露模型推理**，而非一个数字。这与我们 spec 阶段 4 "查证结果必须附来源链接"、以及 #13 "依据必填"**同一哲学**——建议把归因做成 **provenance-first**：每条归因都必须能点回逐字稿确切时间戳/原话。
> - 我们要求"**置信度（数值/档位）必填**"比 Parser 公开做的**更严格**。这是我们自己的设计选择，Parser 既不能背书也不能反驳某个具体阈值——**#13 定"低于什么档不写入索引"时，公开材料无外部锚点可援引，只能靠我们自己的领域判断。**
> - Parser 的 **override + 推理透明**值得借鉴到我们阶段 3 人工核对：把模型的归因**依据**摊给用户看、并允许一键改判（见「未决问题」）。

### 4. 吞吐量 / 成本

**【确认】** 逐字数据（区分两个不同量级）：

| 指标 | 数值 | 来源 | 备注 |
|---|---|---|---|
| 机器处理速度 | "process an hourlong audio file in a matter of minutes" | 官网 + WW | 纯机器，转写+抽取 |
| 端到端人工基线 | 24 小时音频，人工"took easily over 100 hours to produce a list of claims" | WW（作者叙述） | 含"even with a transcription tool" |
| 端到端 Parser 工作流 | 同样 24 小时音频 → "We came up with a list of claims in **two hours**" | WW，作者 Matthew DeFour 第一人称 | **含人工筛选 claim 列表**，非纯机器 |
| 瓶颈定性 | "almost half the time was spent just searching for a claim" | WW | 说明"发现 claim"本身是主瓶颈 |
| 单场证言 | "it saved me at least 90 minutes of work"（一场 Utah 州长辩论） | 官网证言，Maeve Conran（Rocky Mountain Community Radio） | |
| 单人证言 | 从"hours"降到"minutes"（"Gigafact surfaces those claims for me in minutes"） | 官网证言，Tom Kertscher（Wisconsin Watch） | |

**据此推断**：100 h → 2 h ≈ **50× 人工时间压缩**——但这"2 小时"是人+机的端到端工作流（机器抽取 + 人工筛出 claim 列表），不是纯机器时间；且**这是"发现 claim"的加速，完全不含事实查证**。票面提到的"100+ 小时 → 2 小时"说法**已核到一手引用并确认**（出自 partner 报道的作者第一人称）。

**【存疑·公开材料未明】** 无任何金钱成本 / 单位算力成本数据（Parser 对 partner 新闻室免费，靠基金会资助运营）；无"每条 claim 花多少 token/多少钱"这类可与我们成本模型对齐的数字。

> 对我们的意义：
> - Parser 印证了流水线的**成本分层**：抽取/发现这一段可以做到快而廉（对应我们阶段 2 Gemini Flash 的 Map），**昂贵的是下游**（对应我们阶段 4 的查证，我们已设每集 10–20 条上限）。方向一致。
> - 量级上"一小时音频→分钟级"机器处理，支撑我们 spec 里"每天 1–2 集"的节奏在算力时间上**可行**（3 小时音频 ≈ 机器分钟级 + 人工核对）。但**绝对数字不可照搬**：英语 vs 中英混杂、政客闭集 vs 开放实体，都会拉高我们这边的难度与耗时。

### 5. 底层技术（大部分不可确认）

**【存疑·循证推断，置信度低】** Gigafact 与 OpenAI 有资金/产品关系（搜索摘要提到 American Journalism Project 的 Product & AI Studio 报道中一笔 "$5M+ partnership with OpenAI"，以及 Google $250K 等资助）。**据此可以推断** Parser 很可能构建在 OpenAI 栈上（Whisper 系转写 + GPT 系抽取），**但官方从未就 Parser 具体证实用什么模型**，且该资助信息我只拿到搜索摘要、未逐字核验一手全文——因此这一条只作背景，不作结论。

**【确认】** 一些外围功能面（官网 changelog）：YouTube URL 直接粘贴上传（自动下载 MP3 + 抽取元数据）、错误通知页与删除按钮、Topic Briefings（突发新闻的决策者关键引语）、"In Their Own Words" 免费 newsletter。

---

## 对 story-machine 的影响

落到 spec 的具体环节（`audio-obsidian-pipeline-spec.md` 章节号）：

1. **阶段 2「结构化提取」+ 阶段 4「查证」的分工（对应 #3 schema / #13）**
   Parser 印证了"抽取/归因"与"查证"**必须分离**：它抽 claim + 标发言人，但**不做查证**，查证留给记者。这与我们 spec 阶段 2（提取打标签，不查证）/ 阶段 4（只对 `史实类`/`时事断言类` 查证）的分层**一致**。**确认这条设计，无需改。**

2. **#13 归因补全——建议 provenance-first，置信度阈值靠自决**
   - **建议**：`_index/sources.json` 里每条归因**必须带回链**（逐字稿时间戳/原话），对齐 Parser 的"direct citations back to the original recording" + spec 阶段 4"附来源链接"。这是 Parser 唯一可迁移的"依据"形态。
   - **确认**：我们"置信度必填 + 依据必填"的方向与 Parser 的"暴露推理 + 回链"同源，且我们**更严**（多了数值化）。
   - **提示 #13 注意**：Parser 面对**闭集政客 + 预建 profile 库**，其归因难度天然低于我们的开放实体场景；#13 的"补全难度分级"（机构报告 > 已有作者名 > 媒体+时间窗 > 模糊私人）在 Parser 那里对应不到公开数据，**"低于什么档不写入索引"这个阈值没有外部锚点，只能我们自决。**

3. **#15 说话人层——发言人错误会向下传染，必须留人工覆盖位**
   - **确认痛点**：Parser 专门为 speaker ID 迭代（"60% more accurate"）并加广告/片段检测，证明**diarization 错误会污染 claim 归因**。我们 spec 决议里 `语域` 立场指纹**强依赖发言人判对**（同一句话主播说还是嘉宾说，指纹相反），这条保真链在 speaker 出错时会整段崩。
   - **建议**：#15 落 schema 时，除了在 `HH:MM:SS` 逐字稿上加说话人标签字段，还应预留 **人工覆盖（override）** 通道（对齐 Parser 的 "override the model's decision"）——很可能并入阶段 3 人工核对。

4. **阶段 1/2 预处理——播客插播/开场白/花絮检测（新范围，见未决问题）**
   Parser 认为"广告/外部片段检测"是必要功能。我们的政经播客同样有开场白、赞助口播、片尾花絮，会污染抽取与归因。**这是本票冒出的相邻问题，不在本票范围，列入未决。**

5. **实体索引（开发优先级 #4）——我们没有 Parser 那样的预建 profile 库**
   Parser 靠预建的"数百政客 profile"闭集把"发言人→规范名"做轻松了；我们是开放实体、零预建库。**这反向加重了 `entities.json` + 别名 + 消歧的重要性**——它是我们这边"发言人/实体归一"能否成立的地基。**确认现有优先级排序合理。**

6. **参数取值——量级可参照，具体值无外部锚点**
   Parser 的吞吐量支撑"每天 1–2 集"节奏在时间上可行；但每集查证上限（我们暂定 10–20）、置信度写入门槛等具体参数，**Parser 公开材料给不出任何对照数字**，仍需按 spec 第 9 节"先用保守值跑通几集再调优"。

---

## 未决问题

（调研中冒出、但超出本票范围，供开新票；本票**不**顺手研究掉）

1. **播客插播/开场白/赞助口播/片尾花絮的检测与剔除**是否应作为阶段 1/2 的预处理步骤？Parser 的经验（专设"广告/外部片段检测"）表明对播客类素材必要，否则会污染抽取与发言人归因。——建议开新票评估。
2. **阶段 3 人工核对是否应展示"模型归因依据 + 一键改判"**（对齐 Parser 的 override + 推理透明）？涉及 `_review/` 交互形态。——归 #15 下游或新票。
3. **`sources.json` 置信度是"数值分"还是"依据 + 离散档位"，写入门槛定在哪档**？Parser 无外部锚点，纯属我们领域自决。——归 #13。
4. **若未来想复现 Parser 级的具名发言人识别**（diarize 匿名段 → 映射到已知实体），需要一手技术来源确认其方法；当前公开材料不可得。——低优先，需一手技术信源才值得开票。
5. **Techstination 创始人访谈正文、INN 活动页**未能访问（音频页 / HTTP 403）。若后续这两个渠道能拿到正文，可能补上"claim 抽取算法"和"底层模型"的一手信息——目前只能存疑。

---

## 来源清单（访问日期均为 2026-07-22）

一手：
- Gigafact Parser 产品页（营销 + 版本 changelog + 用户证言）：<https://gigafact.org/parser/>
- Gigafact 方法论页（**注意：是人工 Fact Brief 编辑标准，非 Parser**）：<https://gigafact.org/guidelines-principles-and-methodologies/>
- GitHub `gigafact` 用户（`public_repos: 0`，一手核验 Parser 未开源）：<https://github.com/gigafact>

二手 / 半独立：
- Wisconsin Watch 报道（**partner 撰写，非独立评测**；吞吐量数字与逐字引用来源）：<https://wisconsinwatch.org/2025/06/wisconsin-watch-ai-fact-check-audio-misinformation-parser-gigafact/>

未能访问（如实记录，未据记忆脑补内容）：
- Techstination 创始人访谈（受访者 Robyn Sundlee，2024-09-25，仅取到元数据）：<https://www.techstination.com/interview.jsp?interviewId=5324>
- INN 活动页（HTTP 403）：<https://inn.org/event/inn-gigafact-finding-public-political-commentary-with-parser/>

背景（仅搜索摘要，未逐字核验全文，置信度低—中，仅用于 §5 循证推断）：
- Forbes、American Journalism Project 关于 Gigafact 资助与 OpenAI 关系的报道。
