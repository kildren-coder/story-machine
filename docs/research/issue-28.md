# 提取引擎替代方案案头调查：开源 API 价格 / 国内托管合规 / opencode Go 套餐

> AFK research 票 [#28](https://github.com/kildren-coder/story-machine/issues/28)，自 [#14](https://github.com/kildren-coder/story-machine/issues/14) 拆出的**案头事实调查**部分。#14 的胜负手「幻觉率 A/B 实测」是 HITL，留在原票；本票只做不需要用户在场的事实调查。
> 与 [#6](https://github.com/kildren-coder/story-machine/issues/6)（Gemini 免费额度精确算账）分工：#6 算额度，本票管**价格 / 合规 / 替代引擎**。
> 所有链接访问日期：**2026-07-23**。价格随时可变，引用即快照。
> 来源纪律：优先一手（官方定价页 / 官方条款 / GitHub 仓库本体 / 论文原文）；仅有二手来源处已标注；换算与推断用「据此换算/推断」标出，与来源直述区分。

---

## 问题

#11 拍板的修复 pass 使每集 Gemini 用量翻倍以上（修复 60–90k tokens 进出各一遍 + 提取 8–10 块），Flash 免费额度不够从尾部风险变成大概率事件。替代引擎从备胎变成很可能要真用的东西，需要价格与合规底细先行。逐项：

1. **开源模型 API 按 token 计费**（DeepSeek-V3 / Qwen3 级别），**海外托管与国内托管分开列**，折算本项目用量下的每集/每月成本。
2. **国内托管对中国政治内容的硬阻断**：拒答/阉割的公开证据——一票否决项。
3. **订阅制通道 opencode 的 Go 套餐**：定价/模型清单、有无 API/程序化调用、速率上限、ToS 是否允许非交互式管线用法；同类「订阅换额度」通道一并对比。
4. **Google AI Studio 免费档数据条款**：「用于改进服务」对政治播客逐字稿逐块外传意味着什么。
5. **本地 14B 约束解码生态现状**：outlines / XGrammar / llama.cpp grammar 对 20+ 字段复杂 JSON schema 的成熟度——为 #14 本地路线铺垫。

**明确不做**：幻觉率实测、schema 遵守率实测（需用户亲判「什么叫编」，留 #14）。

---

## 结论（TL;DR）

- **成本根本不是问题，合规才是。** 用海外托管的开源模型 API 跑**整条修复 + 提取管线**，每集约 **$0.08–0.10**，按每天 1–2 集折算 **每月约 $2–6**（据此换算，见 §1）。这个量级下「Flash 免费额度不够」的成本焦虑基本消解——几美元/月就买到近乎无限的额度头寸。真正的选型分水岭是**合规与幻觉**，不是钱。

- **国内托管（DeepSeek 官方 API / 阿里百炼 / 硅基流动等 PRC 境内端点）对本题材是一票否决，且是法律强制、非厂商可选。** 中国《生成式人工智能服务管理暂行办法》(2023-08-15) 第 4 条强制「核心价值观」内容过滤；实测证据充分：DeepSeek 对六四/习/台湾/新疆类问题约 **85%** 拒答（1,360 条测试），阿里 Qwen 被问天安门直接报错、答「台湾不是国家」。3 小时中文政经逐字稿必然高频撞线 → **国内托管排除**（§2）。

- **关键且非显然的发现：审查是「两层」的。** API 层过滤（只在国内端点，PRC 强制）+ **权重内嵌**审查（随开源权重走到天涯海角）。海外托管同一份开源权重**只去掉 API 层、去不掉权重层**——所以海外开源模型对本题材**不是自动安全**：抽取时可能对敏感实体**静默漏抽/改写**。此项恰是 #14 HITL 实测要抓的，本票把它明确交回 #14（§2 末）。

- **opencode Go 套餐：技术上可程序化调用，但 ToS 明文不利于本项目的非交互批处理用法，且对本项目量级更贵——不建议作管线后端。** $10/月（首月 $5），含 16 个开源模型（含 DeepSeek V4 Pro/Flash、Qwen3.7），**给 API key、OpenAI/Anthropic 兼容端点**，先决问题「能否程序化调用」答**能**。但 ToS 明列禁止「以自动或程序方式提取数据或 Output」「在你未登录服务时运行/激活的进程」——**AFK 夜跑批处理逐块抽取正撞这两条**。且我们每月只需 $2–6 的 token，Go 的 $10/月地板价比按量付费还贵。速率上限（5h $12 / 周 $30 / 月 $60 usage）对我们绰绰有余，不是约束（§3）。

- **Google AI Studio 免费档 = 数据换免费。** 官方条款明写：免费档「用你提交的内容和生成的响应来提供、改进和开发 Google 产品和服务」，**人工审核员可读取、标注、处理你的 API 输入输出**，且明确警告「不要向免费服务提交敏感、机密或个人信息」。本项目整条流水线把政治播客逐字稿逐块外传给免费档 = 这批素材被拿去训练 Google 模型且可能被人读。想关掉这条只能开账单转付费档，而**开账单会立即抹掉该项目的免费额度**（每次调用从第一 token 计费）——即想要数据保护就得真付钱（§4）。

- **本地 14B 约束解码：schema 遵守率是「已解决」问题，幻觉率不是。** XGrammar 已是 vLLM/SGLang/TensorRT-LLM 默认后端（近零开销、复杂嵌套 schema 准确率 97%+）；5070/12GB 的现实运行时 llama.cpp 的 GBNF 也**够用**——20+ 字段 + 花名册/关系两节的嵌套结构落在其「支持子集」内。但两条硬约束：①部分 JSON Schema 关键字（`minimum/maximum` 仅整数、`patternProperties`/`uniqueItems`/`if-then-else` 等）**不支持且静默跳过** → 须补一道后置校验；②约束解码只保证**语法合规**，**强制每个必填字段出值**在抽取任务上反而可能诱发**编造**——这正是 #14 的幻觉痛点，约束解码解决不了。**结论：schema 遵守率不必留给 #14 实测（已定成熟），#14 的实测应聚焦幻觉率**（§5）。

**给 story-machine 的一句话建议**：若阶段 2/修复 pass 要脱离 Gemini 免费档，**首选海外托管的开源模型按量付费**（DeepInfra / Together 上的 DeepSeek-V3.x 或 Qwen3-235B，每月 $2–6），它同时解掉「免费额度不够」和「Gemini 免费档数据外传」两个问题；**国内托管因审查排除**；**opencode Go 因 ToS + 性价比排除**；本地路线的 schema 工具链已成熟，剩下的只有幻觉率——交给 #14 HITL 拍板。

---

## 论证

### 1. 开源模型 API 按 token 计费（海外 vs 国内）

#### 1.1 一手价格快照（每 1M token，2026-07-23）

> 注意版本代际：票面写「DeepSeek-V3 / Qwen3 级别」，但 2026-07 的现役模型已迭代到 **DeepSeek V4**（`deepseek-chat`/`deepseek-reasoner` 旧别名 2026-07-24 15:59 UTC 弃用）与 **Qwen3-235B-A22B-2507**。下表按现役型号列，价位与 V3/Qwen3 代际同档。

**国内托管（PRC 境内端点；下方 §2 证明对本题材一票否决，价格仅作参照）**

| 托管方 | 模型 | 输入 | 输出 | 币种 | 来源 |
|---|---|---|---|---|---|
| DeepSeek 官方 API（杭州，数据存 PRC） | deepseek-v4-flash | $0.14（cache miss）/ $0.0028（hit） | $0.28 | USD | 一手：[api-docs.deepseek.com/quick_start/pricing](https://api-docs.deepseek.com/quick_start/pricing) |
| DeepSeek 官方 API | deepseek-v4-pro | $0.435（miss）/ $0.003625（hit） | $0.87 | USD | 同上 |
| 阿里百炼 DashScope（北京） | qwen3-235b-a22b-2507 | ¥2（$0.28）| ¥8（$1.13） | CNY | 一手：[help.aliyun.com/zh/model-studio/model-pricing](https://help.aliyun.com/zh/model-studio/model-pricing)（子 agent 读取核对） |
| 硅基流动 SiliconFlow | DeepSeek-V3.2 | ¥4 | ¥6 | CNY | 一手：[siliconflow.cn/pricing](https://siliconflow.cn/pricing) |
| 硅基流动 | DeepSeek-V4-Pro / V4-Flash | ¥12 / ¥1 | ¥24 / ¥2 | CNY | 同上 |

> DeepSeek 官方 API 虽面向全球开放，但公司注册在杭州、数据存于 PRC、受中国法律管辖（[隐私政策](https://cdn.deepseek.com/policies/en-US/deepseek-privacy-policy.html)），且照 §2 施加审查，因此归**国内托管**类，非「海外」。

**海外托管（非 PRC 基础设施；跑同一份开源权重）**

| 托管方 | 模型 | 输入 | 输出 | 来源 / 说明 |
|---|---|---|---|---|
| DeepInfra | DeepSeek-V3.1 | $0.25 | $0.95 | 一手：[deepinfra.com/deepseek-ai/DeepSeek-V3.1](https://deepinfra.com/deepseek-ai/DeepSeek-V3.1) |
| DeepInfra / AtlasCloud | DeepSeek-V3.2 | $0.26 | $0.38 | [openrouter.ai/deepseek/deepseek-v3.2](https://openrouter.ai/deepseek/deepseek-v3.2) 列价 |
| DeepInfra | Qwen3-235B-A22B-2507 | $0.09 | $0.55 | [openrouter.ai/qwen/qwen3-235b-a22b-2507](https://openrouter.ai/qwen/qwen3-235b-a22b-2507) 列价 |
| Together AI | Qwen3-235B-A22B-2507（FP8） | $0.20 | $0.60 | 一手：[together.ai/pricing](https://www.together.ai/pricing) |
| Together AI | DeepSeek V4 Pro | $1.74（cache $0.20） | $3.48 | 同上（V3.x 已下架 serverless 列表） |
| Novita | DeepSeek-V3.1 | $0.27 | $1.00 | OpenRouter 列价 |
| 阿里 Model Studio 国际版（新加坡） | qwen3-235b-a22b-2507 | $0.23 | $0.92 | 一手：[alibabacloud.com/help/zh/model-studio/model-pricing](https://www.alibabacloud.com/help/zh/model-studio/model-pricing) |

**各模型最便宜的海外托管**：DeepSeek → DeepInfra（V3.2 $0.26/$0.38）；Qwen3-235B → DeepInfra（$0.09/$0.55），Together 为一手页确认的最低价（$0.20/$0.60）。（部分数字来自 OpenRouter 聚合列价，非托管方一手页；已在表中标注来源。Fireworks / Hyperbolic 的定价页 JS 未渲染或 404，未取到可信一手数，故未列。）

#### 1.2 本项目用量下的成本换算【据此换算】

**每集 token 预算假设**（据 spec §阶段 0 修复 pass + §阶段 1–2 提取；3hr 逐字稿 ≈ 4–6 万字 ≈ 60–90k tokens）：

| Pass | 输入 | 输出 | 说明 |
|---|---|---|---|
| 修复 pass | 75k | 75k | 全篇逐字稿进 + 约等长纠错稿出（取 60–90k 中点） |
| 提取 pass | 90k | 40k | 8–10 块（逐字稿 + 重叠 + 每块 schema/prompt）进；结构化草稿出 |
| **每集合计** | **≈165k** | **≈115k** | ≈280k tokens/集 |

**每集成本**（输入 0.165M、输出 0.115M）：

| 引擎（托管） | 计算 | 每集 | 每月（1 集/天 ≈30） | 每月（2 集/天 ≈60） |
|---|---|---|---|---|
| DeepInfra · DeepSeek-V3.2（海外） | 0.165×0.26 + 0.115×0.38 | **$0.087** | $2.6 | $5.2 |
| DeepInfra · Qwen3-235B（海外） | 0.165×0.09 + 0.115×0.55 | **$0.078** | $2.3 | $4.7 |
| Together · Qwen3-235B（海外） | 0.165×0.20 + 0.115×0.60 | **$0.102** | $3.1 | $6.1 |
| DeepSeek 官方 v4-flash（国内，仅参照） | 0.165×0.14 + 0.115×0.28 | $0.055 | $1.7 | $3.3 |

**结论**：海外托管开源模型跑整条修复 + 提取，**每集约 $0.08–0.10，每月约 $2–6**。这个量级对成本假设极不敏感——即便提取输出翻倍到 200k（$0.4–0.6/1M 的输出价），每集也只多 $0.05。**成本不是选型变量**。（cache-hit 折扣对我们帮助有限：输入主体是唯一的逐字稿文本、不可缓存，只有每块重复的 schema/prompt 能命中。）

---

### 2. 国内托管对中国政治内容的硬阻断（一票否决）

#### 2.1 法律基础：不是厂商选择，是强制合规

中国《生成式人工智能服务管理暂行办法》(2023-08-15 生效，[中央网信办原文](https://www.cac.gov.cn/2023-07/13/c_1690898327029107.htm)) 第 4 条要求生成内容坚持**社会主义核心价值观**，不得生成「煽动颠覆国家政权」「危害国家统一和社会稳定」等内容。凡在境内向公众提供生成式 AI 服务者**一律**须做内容过滤、算法备案、安全评估（[Haynes Boone 合规解读](https://www.haynesboone.com/getcontentasset/bd5dfcc8-3894-4961-a781-044645867637/141d77fc-2e06-49eb-b14c-2ff58f5ce730/china%20publishes%20interim%20measures%20for%20the%20management%20of%20generative%20artificial%20intelligence%20services.pdf)）。**故 DeepSeek 官方 API、阿里百炼、硅基流动等所有 PRC 境内端点必然带硬过滤层，无法关闭。**

#### 2.2 实测证据（拒答/阉割）

| 现象 | 证据 | 来源 |
|---|---|---|
| DeepSeek-R1 对 1,360 条敏感话题约 **85%** 拒答，答复带「过度民族主义腔调」 | PromptFoo 测评 | [TechCrunch 2025-01-29](https://techcrunch.com/2025/01/29/deepseeks-ai-avoids-answering-85-of-prompts-on-sensitive-topics-related-to-china) |
| 问「1989 天安门」→「Sorry, that's beyond my current scope.」 | 记者实测 | [CBC News](https://www.cbc.ca/news/business/deepseek-chatbot-chinese-censorship-1.7443419) |
| 更新版 R1「是迄今对批评中国政府最审查的 DeepSeek 模型」 | 测评 | [TechCrunch 2025-05-29](https://techcrunch.com/2025/05/29/deepseeks-updated-r1-ai-model-is-more-censored-test-finds) |
| 阿里 Qwen 被问「1989 年 6 月 3 日天安门」直接报错；答「台湾不是国家，是中国不可分割的一部分」 | 记者实测 | [The Register 2025-11-18](https://www.theregister.com/2025/11/18/alibaba_qwen_bot/) |
| DeepSeek/Qwen/Kimi 的内容管控「远超中国国内政治敏感范围」，英文语境也给中国正面导向 | 综述 | [China Media Project 2026-02-09](https://chinamediaproject.org/2026/02/09/tokens-of-ai-bias/) |

学术侧对审查机制有系统刻画：R1dacted（[arXiv:2505.12625](https://arxiv.org/html/2505.12625v1)）、DeepSeek 信息压制审计（[ScienceDirect S0020025525008357](https://www.sciencedirect.com/science/article/abs/pii/S0020025525008357)，对比 646 条敏感话题，发现敏感内容常出现在模型内部推理但在最终输出中被删/改写）。

#### 2.3 关键区分：审查是「两层」的——海外托管去不掉全部

多份研究一致指出审查由**两层机制**构成（[Carl Rannaberg 深挖](https://carlrannaberg.medium.com/deep-dive-into-censorship-of-deepseek-r1-based-models-17feec28c1da)、[QWE 解读](https://www.qwe.edu.pl/tutorial/deepseek-is-censored-what-it-means/)）：

1. **API/应用层过滤**：模型已开始在内部推理里作答，外部系统介入、抹掉推理、改吐拒答。**只存在于 PRC 境内端点。海外托管不带这层。**
2. **权重内嵌审查**：审查在训练/对齐期烘进权重本身，蒸馏模型都会继承。**随开源权重走，海外自托管/第三方托管照样部分保留**（针对 Qwen 有研究定位到「审查电路」，可单向量消融——反证它确实嵌在权重里：[Qwen 审查电路](https://victorinollc.com/thinking/qwen-censorship-circuit-brittle-alignment)）。

**对本项目的含义**：
- 海外托管同一份开源权重 = **去掉第 1 层、留下第 2 层**。所以海外开源模型对本题材**不是自动安全**。
- 但本项目的动作是**从已在眼前的逐字稿里抽取实体/论断**，不是「请评价天安门」。抽取时权重层审查的真实风险是：对敏感实体（六四、习、新疆、法轮功……）**静默漏抽或改写**，而非弹出拒答。这个失败模式**只能实测**，正是 #14「幻觉率/schema 遵守率」HITL 要抓的东西的近邻。
- **本票裁决**：国内托管一票否决（成立）；海外托管开源模型的「敏感实体静默漏抽」风险**移交 #14** 在真实逐字稿上实测确认，不在本票凭推理下结论。

---

### 3. opencode Go 套餐（用户点名候选）

#### 3.1 是什么 / 定价 / 模型清单（一手）

opencode 是终端 AI 编码 agent（SST 出品）。**Go** 是其「低价开源模型」订阅档（另有按量付费的 **Zen** 与企业网关 **Black**）。

- **定价**：首月 $5，之后 **$10/月**（[opencode.ai/docs/go](https://opencode.ai/docs/go/)、[opencode.ai/go](https://opencode.ai/go)）。
- **含 16 个模型**：Grok 4.5、GLM-5.2/5.1、Kimi K3/K2.7 Code/K2.6、MiMo-V2.5/Pro、MiniMax M3/M2.7、Qwen3.7 Max/Plus、Qwen3.6 Plus、**DeepSeek V4 Pro/Flash**、Hy3。
- **价值主张**：$10/月给约 **6×**（≈$60）用量，靠批量折扣 + 预留 GPU 转嫁。

#### 3.2 先决问题：能否程序化 / API 调用？→ **能**（但见 §3.4）

一手文档确认：订阅后拿到 **API key**，模型经 **OpenAI 兼容 / Anthropic 兼容端点** 暴露，config 用 `opencode-go/<model-id>`，**可脱离 opencode 客户端、用任意 OpenAI/Anthropic 兼容 SDK 调用**（[docs/go](https://opencode.ai/docs/go/)）。所以「仅限客户端内交互使用」这个担心**不成立**——技术上可作管线后端。

#### 3.3 速率/用量上限：对本项目不是约束

一手（[docs/go](https://opencode.ai/docs/go/)）三层限额：**5 小时 $12 usage / 每周 $30 / 每月 $60**（结构酷似 Claude 订阅的 5h 滚动 + 周上限）。本项目每集只吃约 $0.08–0.10 的 usage-value，1–2 集/天远在 $12/5h 之下 → **跑得动，限额非瓶颈**。

#### 3.4 ToS：明文不利于本项目的非交互批处理用法（红旗）

**这是先决问题的真正答案**。[opencode.ai/legal/terms-of-service](https://opencode.ai/legal/terms-of-service) 的禁止性条款（逐字摘录）里，**三条直接命中本项目用法**：

> You represent, warrant, and agree that you will not … use or interact with the Services, in a manner that:
> - violates any law or regulation … **or any other purpose not reasonably intended by OpenCode**;
> - **automatically or programmatically extracts data or Output (defined below)**;
> - … or **any processes that run or are activated while you are not logged into the Services**, or that otherwise interfere with the proper working of the Services …;
> - **copies or stores any significant portion of the Content**; …

对照本项目：①管线**以程序方式逐块抽取 Output** → 撞「automatically or programmatically extracts … Output」；②AFK/夜跑**在用户未登录时批量运行** → 撞「processes that run … while you are not logged into the Services」；③opencode 的**合理预期用途是交互式编码 agent**，非交互文本抽取批处理 → 撞「purpose not reasonably intended by OpenCode」；④我们把草稿落盘 → 沾「copies or stores … significant portion of the Content」。

> 平心而论，这份禁令清单形态偏「反滥用/反爬」（并列 spam、crawl、scrape），「programmatically extracts Output」在语境里更像针对爬服务；但其字面足够宽，叠加「未登录时运行的进程」一条，**无人值守批处理明显在其交互式编码用途的设计包络之外**。是否可接受由用户判；本调查的倾向是**不建议**把管线建在 Go 上。

另注：Go 里的 DeepSeek/Qwen 经 opencode（美国公司）网关，**无 PRC API 层过滤，但权重层审查照 §2.3 保留**——审查画像等同海外托管开源权重，非额外优势。

#### 3.5 同类「订阅换额度」通道对比

| 通道 | 价 | API 可调？ | 模型 | 对本项目的问题 |
|---|---|---|---|---|
| **opencode Go** | $10/月 | 是（OpenAI/Anthropic 兼容） | 16 个开源（DeepSeek V4、Qwen3.7、GLM、Kimi…） | ToS 不利于非交互批处理；地板价 > 按量成本 |
| **GLM Coding Plan**（智谱 z.ai） | $3–10/月起 | 是（Anthropic 兼容，`api.z.ai`） | GLM-5.2/Turbo/4.7 等 | ①同属「编码计划」，ToS 意图同样偏交互编码；②GLM 是中国模型，**审查两层皆可能命中**（z.ai 编码端点疑为 PRC 运营 → API 层 + 权重层）。来源：[z.ai 指南](https://www.aimadetools.com/blog/z-ai-api-complete-guide/)、[felloai](https://felloai.com/glm-pricing/)（二手，中置信度） |
| **Cursor / Copilot / Windsurf** | $10–20/月 | 否（锁客户端/IDE） | 混合闭源 | 无 API → 不能作管线后端，先决问题即出局 |
| **按量付费（DeepInfra/Together…）** | 用多少付多少 | 是 | 开源全家桶 | 本项目 $2–6/月，**比任何 $10 地板价订阅便宜**，且无编码用途 ToS 约束 |

**结论**：订阅制通道的经济性只在「你本会每月花 >$10 零售」时成立——高频交互编码者。本项目是**间歇性低吞吐批处理**，量小到「订阅换额度」的 6× 杠杆用不上，按量付费反而更省、且没有编码类 ToS 的用途错配。**opencode Go / GLM Coding Plan 均不建议作阶段 2 后端。**

---

### 4. Google AI Studio 免费档数据使用条款

#### 4.1 一手条款：免费 = 数据换额度

[ai.google.dev/gemini-api/terms](https://ai.google.dev/gemini-api/terms) 的「How Google Uses Your Data」明确区分免费/付费：

| 维度 | 免费档 / Unpaid（含 AI Studio 网页 + 免费 API 配额） | 付费档 / Paid（开账单后） |
|---|---|---|
| 用于改进/训练 Google 产品 | **是**：「uses the content you submit … and any generated responses to provide, improve, and develop Google products and services」 | **否**：「Google doesn't use your prompts … or responses to improve our products」（含训练） |
| 人工审核 | **是**：「Human reviewers may read, annotate, and process your API input and output」（先与账号解绑再审） | 仅安全命中时：授权员工经内部治理平台评估被 flag 的内容 |
| 敏感信息警告 | **有**：「Do not submit sensitive, confidential, or personal information to the Unpaid Services」 | — |
| 留存 | 滥用检测/合规目的留存 **55 天**（[logs-datasets](https://ai.google.dev/gemini-api/docs/logs-datasets)、[usage-policies](https://ai.google.dev/gemini-api/docs/usage-policies)） | 同样 55 天用于滥用/合规，但不用于改进 |

（EEA/瑞士/英国用户例外：付费档数据条款适用于其全部服务，含免费档。可选 [Zero Data Retention](https://ai.google.dev/gemini-api/docs/zdr) 进一步关留存。）

#### 4.2 对本项目的含义

- 本项目把 3 小时**中文政经直播逐字稿逐块**外传给 Gemini **免费档** = 这批用户精心策展的敏感政治素材被**拿去训练 Google 模型**，且**可能被人工审核员读取**，并撞上官方「勿提交敏感/机密信息」的明文警告。**这是真实的数据治理暴露，须用户明确知情并接受，不是形式条款。**
- **想关掉这条 → 只能开账单转付费档**；但 [billing 文档](https://ai.google.dev/gemini-api/docs/billing) + 多方实测确认：**一旦在项目上开账单，该项目免费额度即整体消失，每次调用从第一 token 计费**（EEA/CH/UK 除外）。即「想要数据保护就得真付钱」——与 #6 的免费额度账直接联动。
- 这把整份报告串起来：付费一旦不可避免，Gemini 付费档 vs §1 的海外开源按量付费就在同一「几美元/月」赛道正面竞争，而后者**顺带**免掉了 §4 的训练/人审暴露（付费第三方托管同样不拿数据训练）。
- **注意轴向别混**：Gemini 的问题是**数据使用/隐私**（Google 不审查中国政治内容），国内托管的问题是**审查硬阻断**——两个不同的坑，别混为一谈。

---

### 5. 本地 14B 约束解码生态现状（为 #14 铺垫）

#### 5.1 三个引擎的成熟度

| 引擎 | 机制 | 成熟度 / 定位 | 复杂嵌套 schema | 一手/来源 |
|---|---|---|---|---|
| **XGrammar** | 下推自动机（CFG） | 2026-03 起为 **vLLM / SGLang / TensorRT-LLM 默认**结构化后端；~40µs/token、近零开销 | 强：Qwen-2.5-32B 在 GitHub-issues schema 上 **97.1%** 准确（Outlines 76.4%）；支持递归/`$ref` | [arXiv:2411.15100](https://arxiv.org/pdf/2411.15100)、[XGrammar-2 arXiv:2601.04426](https://arxiv.org/pdf/2601.04426)、[MLC 博客](https://blog.mlc.ai/2024/11/22/achieving-efficient-flexible-portable-structured-generation-with-xgrammar) |
| **Outlines** | 有限状态机（FSM） | vLLM 可选后端；声明覆盖高但**编译慢**（3.5–12.8s）、实测吞吐低 | 弱：递归会被拒/压平到定深；复杂嵌套 76.4% | [vLLM structured outputs](https://docs.vllm.ai/en/v0.8.4/features/structured_outputs.html) |
| **llama.cpp GBNF** | 显式栈字符级 parser | **5070/12GB 的现实运行时**（GGUF 量化 14B 4-bit）；自带 `json_schema`/`response_format` | 够用：对象/数组/枚举/嵌套/`anyOf`/`oneOf` 支持，但仅「JSON Schema 子集」 | 一手：[grammars/README.md](https://github.com/ggml-org/llama.cpp/blob/master/grammars/README.md) |

> 硬件现实：5070 12GB 上 14B 4-bit 的现实栈是 **llama.cpp（GGUF）**；vLLM+XGrammar 对 12GB 显存偏紧（XGrammar 也可经 MLC-LLM 上消费级 GPU）。所以本项目本地路线的约束解码大概率落在 **llama.cpp GBNF**。

#### 5.2 llama.cpp GBNF 的「支持子集」与坑（一手 README）

- **支持**：string/integer/number/boolean/null/array/object；`minLength/maxLength`、`minItems/maxItems`、`minimum/maximum`（**仅 integer**）；嵌套、`required`、`$ref`/definitions（有坑）、`anyOf/oneOf`（有限）、正则 pattern（须 `^…$`）、`additionalProperties` 控制。
- **不支持/坏掉，且「静默跳过」**：`prefixItems` broken（`items` 可用）；`minimum/maximum` 对 `number` 无效；嵌套 `$ref` broken；远程 `$ref`（C++ 版）；`format: uri/email` 缺失；**无** `patternProperties`/`uniqueItems`/`contains`/`$anchor`/`not`/`if-then-else`。
- **两条运营级坑**：① **schema 不注入 prompt**——「The JSON schema is only used to constrain the model output and is not injected into the prompt. The model has no visibility into the schema.」故 20+ 字段 schema 必须**同时在 prompt 里描述字段**，否则模型吐出合法但空洞/乱填的 JSON；②语法不保证 JSON **完整**（模型可能没写完就耗尽 token）。

**对本项目 schema 的判断**：一条论断 20+ 字段 + 花名册/关系两节 = 扁平字段 + 中等嵌套 + 枚举（论断类型标签），**完全落在 llama.cpp 支持子集内**。用到的高级关键字若涉及 §5.2 不支持项（如 `uniqueItems` 去重、数值 `minimum`），须靠**后置校验**补，不能指望语法层拦。

#### 5.3 约束解码解决什么、不解决什么（#14 的分工线）

- **解决：schema 遵守率 = 语法合规。** JSONSchemaBench（[arXiv:2501.10868](https://arxiv.org/html/2501.10868v1)，1 万真实 schema 基准）测六框架，llama.cpp 声明覆盖 **0.54–0.98**、XGrammar 0.12–1.00、Outlines 0.38–0.99；且**约束解码平均提升下游任务准确率至多 ~4%**（GSM8K 80.1→83.8），并非「戴上枷锁就变笨」。→ **schema 遵守率不必留给 #14 实测，本票判定为「工具链已成熟、可解」。**
- **不解决：幻觉率。** 约束解码只保证输出**长得对**，不保证**内容真**——「failures often due to output degeneration」。更要命：抽取任务里，**强制每个必填字段出值**意味着逐字稿没提供的字段模型也得**编一个**去满足 schema。这与「只提取逐字稿明确出现的内容」非协商项正面冲突，且 schema 越复杂（20+ 字段）逼编越狠。→ **这正是 #14 的胜负手，约束解码帮不上；#14 的 HITL 实测应聚焦幻觉率，而非 schema 遵守率。**
- （关于「约束解码是否伤质量」，学界有分歧：早期有「Let Me Speak Freely?」类工作报告退化，但 JSONSchemaBench 等更严格基准反而测出小幅提升。本项目关心的不是通用推理质量，是**抽取忠实度**这个特定维度，二者都未直接覆盖 → 仍须 #14 在真实政经逐字稿上亲测。）

---

## 对 story-machine 的影响

落到 spec 的具体章节：

1. **spec §6「模型/工具分工与成本策略」表**：给「逐字稿纠错」「分块结构化提取」两行的「Gemini Flash 或本地小模型」补一个**明确的第三选项——海外托管开源模型按量付费**（DeepInfra/Together 上 DeepSeek-V3.x 或 Qwen3-235B），并标注**成本量级 $2–6/月**（§1.2）。该选项同时化解「Flash 免费额度不够」（#6/#11）与「Gemini 免费档数据外传」（§4）两个问题。**国内托管明确标注排除、附审查原因**（§2）。

2. **spec §阶段 0「LLM 修复 pass」/ §阶段 2「Gemini Flash 提取」**：若脱离 Gemini，替代引擎**首选海外托管开源按量付费**；**不要选 opencode Go / GLM Coding Plan**（§3：ToS 不利于非交互批处理 + 对本项目量级更贵）。

3. **合规注记（新增或并入 §7 设计原则 / CONTEXT 非协商项旁）**：Gemini **免费档**会把逐字稿用于训练 + 人工审核（§4）——须由用户**明确知情决策**这批政经素材愿不愿进 Google 池；要免除只能开账单转付费档（且免费额度随之消失）。

4. **交回 #14（本地/开源路线实测）**：
   - **schema 遵守率维度可从 #14 实测清单里降级**——§5 已定「工具链成熟、可解」，5070/12GB 落 llama.cpp GBNF，20+ 字段 schema 在其支持子集内（少数高级关键字走后置校验）。#14 的 HITL 火力**集中到幻觉率**。
   - **新增一条 #14 必测项**：海外托管开源权重对敏感政治实体的**静默漏抽/改写**（§2.3 权重层审查残留）——用含六四/习/新疆的真实逐字稿片段验证 DeepSeek/Qwen 抽取时是否漏实体。这是「幻觉率」的镜像（漏而非增），同属只能实测。

5. **交回 #6（Gemini 额度账）**：§4 的「开账单即失去免费额度」是 #6 算账的硬约束——「免费档不够 → 转付费档」不是平滑升级，而是从第一 token 计费；#6 应把 Gemini 付费档单价与 §1 的海外开源按量单价并排比。

---

## 未决问题

（调研中冒出、超出本票范围者，供开新票；不在本票研究掉）

- **海外托管的数据/隐私条款逐家核查**：本票只证了「海外开源按量付费不拿数据训练」这一общ性结论，未逐家读 DeepInfra/Together/Novita 的 DPA、留存期、是否第三方转售。若要把政经逐字稿常态外传，值得单开一票逐家过条款（与 §4 的 Gemini 同一合规轴）。
- **海外托管的可及性/稳定性**：Tailscale 双机在国内网络环境下访问 DeepInfra/Together 的连通性、限速、支付方式（需外币卡）未评估——属工程可行性，本票只管价格与合规。
- **本地路线的完整可行性**（vLLM+XGrammar vs llama.cpp GBNF 在 5070/12GB 的实机吞吐、与 whisper 串行卸载的调度）：§5 只定了约束解码成熟度，未做实机基准——属 #14 本地路线或单开工程票。
- **`_pairs` 校对数据与第三方 ToS 的潜在冲突**：spec §阶段 3 要留「模型草稿→人工修正」配对做微调；若草稿来自 opencode Go，其 ToS「uses Output to develop AI models that compete」条款可能有摩擦（个人抽取微调是否算 compete 存疑）。选海外按量付费一般无此限，但选订阅制通道时须复核——供选型拍板时留意。
