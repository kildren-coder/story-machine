# 模型调用一览：哪一步碰模型、提示词怎么拼、实例在哪、改哪儿

2026-11-06 起维护。SPEC v4 重写时 §7 的模型表并进来，这一份是总表。

全系统每一次调模型都是同一个形状（ADR 0004、SPEC §4.1）：`claude -p` 无头调用，**提示词 = 规则文件 + 代码拼的输入 + schema**。

- **规则文件**：一层一份 md，首行 `version:`。流水线走 `--system-prompt-file`，原型进程走 `--append-system-prompt`。改规则就改文件、升版本；版本号进 provenance（流水线）或记录（原型进程），内容 sha8 打在运行日志里，分得清「改了没升版本」。
- **输入**：代码从记录拼，走 stdin。头一行一个键（挤成一行模型会抄错，L1 的教训）；行号是输入里现成的闭集，模型不写时刻；预算数写在头里，规则里不写死数字。
- **schema**：定义在该层代码里，范围跟着输入走（行号上下界），形状不对由 CLI 在会话里让模型重来。
- **没有手写的单次提示词。** 要微调只有三处可改：规则文件（改字、升版本）、拼输入的那段代码（改给模型看什么）、schema 与检查（改产物形状）。

每次调用留三份：原样输入 `.in.md`、原始响应 `.raw.json`、解析后产物。**实例就是 `.in.md`**（流水线）或记录里的 `prompt` 字段（原型进程）。它们含整理稿与逐字稿，只在 vault，不进仓库（红线 10）；本表只记路径。

## 一 · 现在在跑的（代码在仓库）

| # | 调用 | 现状 | 规则文件 | 拼输入的代码 | 模型 / effort / 工具 | 输入 | 输出（schema） | 实例 |
|---|---|---|---|---|---|---|---|---|
| 1 | L1 骨架：整集 → 章节表 | 已实现，EP02 真跑 | `prompts/L1-skeleton.md`（`L1-skeleton@0.9`） | `scripts/sm/l1.py` `head_block` + `build_input` | sonnet / low / 无工具（`--tools ""`） | 头五行（episode、时长、行数、参考章数、说话人）+ `---` + 整集行表 `n [HH:MM:SS] 谁: 文本` | `{chapters:[{id,title,line,gist}]}`，`schema_for` 卡行号 1–行数 | vault `_pairs/EP02/L1-all.in.md` + `.raw.json`；旧版本在 `_history/EP02/L1-skeleton@0.x-…/_pairs/` |
| 2 | L2 逐章节整理：章节切片 → 片段 + 话题表 | 已实现，EP02 真跑 12 章 | `prompts/L2-topic.md`（`L2-topic@0.2`） | `scripts/sm/l2.py` `head_block` + `chapter_map` + `build_input` | sonnet / medium / 无工具，并发 3 | 头八行（含本章字数与整理稿目标）+ 全集章节地图（本章标 →）+ 上文 / 本章 / 下文三段切片（前后各 2 分钟只供理解） | `{topics:[{title,kind,line,gist,paras,quotes,claims,channels,asr}]}`，`schema_for` 卡行号在本章 | `_pairs/EP02/L2-<章节 id>.in.md` × 12 |
| 3 | 重试（不是独立调用） | 已实现 | 无 | `scripts/sm/pairs.py` `retry_input` | 同该层 | 原输入 + `=== 你上一次的输出 ===` + 错误清单（≤ 10 条）+ 「在上一次输出的基础上改」 | 同该层 | `_pairs/` 留的是最后一趟实际发出的 |
| 4 | 行下讨论（深加工页） | 原型 `serve.py`，真跑过 8 次（11-09 0.2 版 2 次；11-11 0.5 版 5 次、0.6 版 1 次） | vault `_lab/thread-proto-20261009/pages-proto/prompts/讨论.md`（`讨论@0.6`） | `serve.py` `context_block` + `talk_prompt`；`prepare_cwd` 往 cwd 放本段整理稿.md、逐字稿切片.md（原话前后 3 分钟；判断行有几处原话就放几处） | sonnet / 默认 effort / WebSearch、WebFetch、Read，`--restricted`，续轮 `--resume` | 首轮：今天 + 本行（命题、判定、依据、实际、现在、来历、原话、来源、关联假设、名词；判断行则是假设、评估、关键假定、论证链、压在的行，各带判定、对这条论点的方向、来历、依据、来源链接）+ 可读文件 + 人问；续轮只有人问，页上这行的材料变了（语境指纹 `ctx_sig` 不同）就重发一遍 | `{answer,claims[{text,affects}],searches,reads,links}` | `pages-proto/records/<问题>/talk.jsonl` AI 轮的 `prompt`，实际搜了几次、打开了哪些网页在 `used`（读 claude -p 会话记录）；页面「看提示词」 |
| 5 | 现在就核（深加工页） | 原型，真跑多次（11-11，都不进用户的记录） | 同目录 `prompts/现在就核.md`（`现在就核@0.3.1`）；挂在论证链必经一步上的行用 `prompts/现在就核.深挖.md`（`现在就核·深挖@0.4`，11-11 用户定） | `serve.py` `verify_material` + `verify_plan`（按 `deep` 选规则、schema、模型）；批量跑用 `verify_batch.py`（同一个 `verify_plan`，可换模型与规则） | sonnet，深挖的行 opus / WebSearch、WebFetch（Read 也给了，cwd 是空的） | 今天、命题、所属问题、原话（逐字）、逐字稿里前后各一行、述段标题、播出日、说话人与 stance、转述自、检索词、候选来源；不给假设（0013 第 3 条） | `{verdict,confidence,why,actual,now,basis,sources,searches,course}`；`why` 是枚举；`course` 是经过：事件类三到五句，每句 `{text,url,quote}`，不是事件留空（0013 补记 11-11）；深挖的行经过四到七句、答五问，另交 `missing[]`（哪一问没查到、为它搜了什么） | `records/<问题>/verify.jsonl` 的 `prompt`；页面「看提示词」；批量跑的在 vault `pages-proto/runs/核实/<运行 id>/<命题 id>.json`（含会话里真用到的搜索与网址）；换模型换规则的对照 `runs/核实/内情对照.md` |
| 5a | 拆步（深加工：列假设之后、核实之前） | 原型 `split_steps.py`，真跑 3 次（11-11：0.1 版 1 次、0.2 版 2 次） | 同目录 `prompts/拆步.md`（`拆步@0.2`） | `split_steps.py` `gather` + `build_input` + `schema_for`；`settle` 抄定原话（0009）并检查 | sonnet / high / 无工具（`--tools ""`），cwd 空目录 | 头四行（问题、述线、论点数、步数上限）+ 论点表（id、持有者、类型、文本、出处）+ 出处述段（整理稿段 + 带行号逐字稿，述段前 1 行后 2 行标邻段）；约 1.5 万字 | `{hyps:[{id,reasoned,why_not,steps:[{text,role,ep,line,quote,do,claim,query,ask}]}]}`；`role` 起点 / 环 / 并列 / 后果，`do` 派生 / 等主播说 / 起点 | vault `pages-proto/runs/拆步/<运行 id>/拆步.in.md` + `.raw.json` + `.out.json` + `对照.md` |
| 5b | 推理（深加工） | 原型 `reason.py`，真跑 2 次（11-11：opus / high、sonnet / high 各一次） | 同目录 `prompts/推理.md`（`推理@0.1`） | `reason.py` `build_input` + `schema`；`settle` 检查、归一、算封顶 | opus / high / 无工具（`--tools ""`），cwd 空目录 | 头几行（今天、问题、述线、上轮一行、本轮新增）+ 假设表（主播 / 嘉宾的带拆步的步：角色、原话、处置、步自己的行、步上开的缺口）+ 证据行（种类、谁说的、时刻、播出日、命题、判定与把握、实际、依据、现在、经过、来源立场、来历或「核的就是第几步」）+ 主播立场 + 预测 + 已有的缺口与指标；约 2.4 万字。不给正文 | `{matrix:[{row,hyp,dir,note,step,says,status,target,open}],evals:[{hyp,likelihood,conf,why,assumptions:[{text,target}],rows,vs,change}],chains:[{hyp,weak,line}],gaps:[{key,hyps,text,kind,where}],doubts,answer}`；`says` 是能说明什么，`status` 推断 / 核过，`target` 对上的缺口或指标 | vault `pages-proto/runs/推理/<运行 id>/推理.in.md` + `.raw.json` + `.out.json` + `对照.md` |

第 4、5 条正式版不这样跑：讨论照 0017 第 4 条，现在就核照 0013（代码检索 + 模型判，模型不带搜索工具）。5a、5b 的输入现在从原型页的数据取（论点是手写的假设表，证据行里旧判定是 10-09 核的、步派生的 13 行是 11-11 真跑核的），正式版从列假设的假设表和台账取。

## 二 · 10-09 原型跑过、v4 要换形状的（代码在 vault `_lab/thread-proto-20261009/`，不进仓库）

| # | 调用 | 规则文件 | 拼输入的代码 | 模型 / effort / 工具 | 输入 | 实例 | v4 换成 |
|---|---|---|---|---|---|---|---|
| 6 | L4′ 挂专题 | `proto/L4-thread.md`（`L4-thread@0.1-proto`） | `proto/thread_step.py` | sonnet / medium / 无工具 | 集号、播出日、UP 主、已有专题清单、本集 talk 话题头 | `vault/_pairs/EP01/L4-thread.in.md`、`EP02/L4-thread.in.md` | 0008 第 3 条：4a 认事 / 4b 对已有 / 4c 拉旧的，步间走本地检索 |
| 7 | L5a 核查说法 | `proto/L5a-check.md`（`L5a-check@0.1-proto`） | `proto/deepen_step.py` | sonnet / high / WebSearch、WebFetch | 一个专题全部可核说法（集号、时刻、说话人、原话） | `vault/_pairs/threads/dsa/L5a.in.md` | 0013 核实：代码检索、模型只判，按诊断力排队 |
| 8 | L5b 四问 | `proto/L5b-deepen.md`（`L5b-deepen@0.1-proto`） | `proto/deepen_step.py` | opus / high / 联网 | 专题全部整理稿正文 + 原话 + 说法 + 核查判定（输入 6.5 万 token） | `vault/_pairs/threads/dsa/L5b.in.md` | 0012：列假设 / 推理 / 反方三次调用，推理不联网不吃正文 |
| 9 | #95 基准挂法（调研，已关） | `retrieval-95/prompt.md`（`baseline-95@0.1`） | `retrieval-95/baseline.py` | opus / high / 无工具 | 两集全部述段一次看全 | `retrieval-95/baseline/in.md` | 一次性，产物是检索基准，不进流程 |

SPEC v3 的 L4 事件、L5a、L5b、L6 导语只有设计没有代码，0007 / 0012 / 0013 已替换，不另列。

## 三 · v4 设计好、提示词还没写的

ADR 定了输入输出与预算，规则文件在骨架票落地时写，写好就补进第一张表。

| # | 调用 | ADR | 模型 / 预算 | 联网 / 正文 | 输入 | 输出 |
|---|---|---|---|---|---|---|
| 10 | 正字 | 0010 第 3、4 条 | 按词，额度走旋钮 | 联网查一次 | 词 + 段内线索 + 词表 | 改字表条目：原字、改成、类别、证据种类、依据与链接、把握 |
| 11 | 挂述线 4a 认事 | 0008 第 3 条 | 模型未定（原型 L4′ 用 sonnet / medium）；一集述段头不到 2 万 | 否 | 这一集全部述段头 | 几件事：名字、一句说明、述段 id |
| 12 | 挂述线 4b 对已有 | 0008 第 3 条 | 模型未定 | 否 | 每件事 + 检索一取的约 5 条候选述线 | 已有哪条 / 新的；每段挂不挂 |
| 13 | 挂述线 4c 拉旧的 | 0008 第 3 条 | 模型未定 | 否 | 新的事 + 检索二取的旧述段候选 | 哪些旧段属于它、够不够开线 |
| 14 | 回顾整体 | 0007 第 9 条 | 模型未定，每周一次 | 否 | 本周碰过的述线、新增没挂述段，每件先本地检索 | 合并、拆分、改挂、改名改说明、整成新线的建议 |
| 15 | 列假设 | 0012 第 2 条 | sonnet / high，约 2 万 | 否；不给正文不给原话 | 问题、述线名与说明、述段头、说法一行头、上轮摘要、关联述线评估 | 假设表、命题表（诊断力）、派生待核事实、先例候选 |
| 15a | 拆步（11-11 加） | 0012 补记 11-11 | sonnet / high，约 1 到 2 万；首轮跑，再跑只对新列的假设和出处有新段的假设 | 否；只读论点出处那几段 | 规则已写、原型已真跑，见第一张表 5a | 同 5a |
| 16 | 核实 | 0013 第 3、5、7 条 | 一批 ≤ 6 万；挂在环上的命题深挖，用 opus（0013 补记 11-11） | 代码检索（AnySearch）抓正文喂进去，模型不带搜索；不看假设 | 命题、原话那句及前后各一句、述段标题、播出日、说话人、stance、转述自、检索结果、台账最像的 5 条 | 判定四态、把握、实际、现在、引文片段、匹配三选一、名词[]、经过（事件类，三到五句各带来源；0013 补记 11-11）；深挖的另交 missing |
| 17 | 推理 | 0012 第 3 条 + 补记 11-11 | opus / high，4 到 5 万 | 否；不吃正文（11-06 定不变） | 问题与假设表（含拆步的步与步上开的缺口）、命题行（含经过）、述段头加每段原话、上轮摘要、反方、缺口与指标 | 矩阵（每格带挂到第几步）、评估、论证链断处、能说明什么（派生与先例行打撑或反时：推断 / 核过，推断的对上缺口或指标）、答案与变了什么、事件脉络、矛盾、质疑、缺口、指标。规则已写、原型已真跑（矩阵、挂步、能说明什么、评估、缺口、质疑、答案这几样），见第一张表 5b；事件脉络、矛盾、指标没进原型的 schema |
| 18 | 反方 | 0012 第 7 条 | sonnet / high，约 2 万，另一个模型 | 否 | 推理产出 + 命题行 | 被攻的假定、薄弱行、替代解释、推翻条件、依据薄弱的判定、总评 |

## 四 · 不是提示词调用的

阶段 0 转写（FireRed，ADR 0006）；本地检索（Qwen3-Embedding-0.6B + 字二元，0008 补记）；L3 闸门、渲染、收勾、改判传播（纯代码）；本地大模型改正本（已否决，0010）。开发用的 AFK 代理和 Claude Code 会话不是系统的调用。

## 五 · 怎么看一次调用、怎么改

- **看流水线的实例**：vault `_pairs/<EP>/<层>-<单元>.in.md` 是原样输入，`.raw.json` 是原始响应；`_failed/` 里是没过检查的那趟。
- **看深加工页的**：起 `serve.py`，核实勾旁或讨论框里点「看提示词」，不跑、零额度；跑过的翻 `records/<问题>/talk.jsonl`、`verify.jsonl` 的 `prompt` 字段（假跑也记）。
- **改规则**：改那份 md，首行版本升一位。L2 跳过的章若是旧版本写的，日志报「prompt_version 落后」，要重跑加 `--force`。
- **改语境**：改拼输入的函数（表里「拼输入的代码」那列）；加一项就要在 `.in.md` 或 `prompt` 字段里看得见。
- **改形状**：改该层的 `schema_for` 与 `check_*`，代码只拦修不了的（SPEC §4.1）。
- **上线前**：3 集 × 3 轮量首发通过率（`scripts/bench_l1.py` 的路子），目标 100%。
