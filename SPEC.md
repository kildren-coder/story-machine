# Story Machine — 项目规格（SPEC）v3

> 本文是本项目**唯一可信的需求来源**，只记「做什么」；「为什么」在 `docs/adr/`。与用户临时口头描述冲突时，以本文为准，除非用户明确要求变更。
> 2026-09-12 重写，替代 2026-07-27 的 v2。v2 原档：`git log --oneline -- SPEC.BACKUP.md` 找到备份 commit，`git show <sha>:SPEC.BACKUP.md`。

---

## 1. 目的与边界

### 1.1 一句话

把关注的 UP 主每天发布的**直播录播和视频**，自动整理成一份**日报**，回答六个问题：讲了什么（不简略）、重大事实偏差、支持的证据、不支持的情况、历史先例与当时 vs 现在、有见地的分析。末尾附他们提到的信源。

**AI 做信息初筛与整理，知识与事实的构建归人。**

### 1.2 人与软件的分工

| 谁 | 每天 | 周末 |
|---|---|---|
| 软件 | 发现新录播 → 转写 → 整理 → 核查 → 出日报 | 无 |
| 人 | **只读日报** | 确认核查判定（改标签）、在事件笔记的「我的判断」里写自己的东西；把日报标出的 ASR 生音补进热词库 |

人**永不通读逐字稿，永不审中间产物**。没有每日人工审核。

### 1.3 阅读预算

| 指标 | 数值 |
|---|---|
| 一场 3 小时直播的整理稿 | ≤ 30 分钟读完（正文约 12,000 字） |
| 一张六问卡 | ≤ 3 分钟 |
| 日报导语 | ≤ 300 字 |
| 压缩比（整理稿字数 / 逐字稿字数） | 约 0.2 |

超出预算时调话题切分和事件聚类，**不允许为了短而删内容**（红线 2）。

### 1.4 不做

- B 站动态（暂缓）
- 自动知识图谱、实体笔记、脉络笔记的自动生成
- 信源信用打分（「他们提到的信源」只列不评）
- 多用户 / 产品化（单用户单机；选型留升级路径即可）
- 每日人工审核
- 模型自校验（机械可判的事全在代码里判）
- LLM 逐字稿修复 pass

---

## 2. 硬件与账号

- **笔记本**：开发、Obsidian 库、Claude Code。
- **房间 PC**：RTX 5070 12GB，跑转写与说话人分离。`ssh pc-5070` 免密（Tailscale + OpenSSH）。
- **Claude 订阅**：Max。全流程 LLM 走 Claude Code 订阅，无头 `claude -p`，**不走 API credits**（禁 `--bare`）。与 agent-alert 项目共享额度池。
- **子代理**（交互会话里做原型 / 调研）：必须显式 `model`（sonnet；论证类 opus），一次并发 ≤ 3。生产流水线不用子代理。

---

## 3. 总体架构

```
关注列表 ──► _pipeline/队列.md ──► [PC: 下载 → 转写 → 分离] ──► _assets/EP{n}.*      阶段 0（ADR 0002）
                                                                    │
                                                                    ▼
                     [笔记本: 无头 Claude Code，一层一个调用，代码切片与拼装]        L1–L7（ADR 0004）
                                                                    │
                    ┌───────────────────────────────────────────────┤
                    ▼                        ▼                      ▼
          10-Episodes/EP{n}.md        20-Daily/{date}.md      30-Events/{事件}.md
          整理稿                        日报（人每天读）          跨天事件（人周末写）
```

- 阶段 0 在 PC 上跑，产物 scp 取回；此后全部在笔记本本地。
- 状态落在文件里：阶段 0 的状态是队列笔记；L1 到 L7 每层的产物就是它的状态，缺哪个文件就从哪层重跑。
- 时间戳跳播靠自研插件（ADR 0001）：EP 笔记内用裸 `[HH:MM:SS]`，日报和事件笔记用 `EP02@HH:MM:SS`。

---

## 4. 处理流程

```
阶段 0  音频 ──► 逐字稿 JSON（正本）+ 说话人 + 声纹点名
L1      骨架      整集 ──► 话题表 topics.json
L2      逐话题    话题切片 ──► 片段 frag-<topic>.json
L3      闸门      纯代码 ──► 整理稿落 EP 笔记
L4      事件      各 EP 的话题表 + 可核查的说法 ──► events.json
L5a     事实核查  每事件 ──► check-<event>.json（deviations）        联网
L5b     证据·先例·分析  每事件 ──► check-<event>.json（其余字段）     联网
L6      导语      ──► ≤ 300 字
L7      渲染      纯代码 ──► 日报 + 事件笔记 + 跨 UP 对照
```

### 阶段 0：转写（PC）

**转写**：`faster-whisper` `large-v3`，`float16` / `batch_size=16` / VAD 开 / `word_timestamps=True` / `language="zh"`；`multilingual` 不开；`initial_prompt` 不用。此配置冻结。环境：CUDA 12.8+，CTranslate2 ≥ 4.7.0。

**说话人分离**（`pc/smdiar.py`，venv `C:\asr\venv-diar`，torch CPU）：
- 模型 3D-Speaker `iic/speech_campplus_sv_zh_en_16k-common_advanced`，权重缓存 `E:\asr\ms-cache`。禁用 `pyannote.audio` 4.x。
- 按词边界切 3 秒窗做 embedding；按录音去均值再归一化，Ward linkage 聚类。
- K 自动估计，上限 4，`--speakers N` 可锁死。每簇 ≥ 60 秒，轮廓系数 ≥ 0.10，否则该 K 作废；全作废即单人。
- 段按标注好的词重建；**重建不许改文本、不许用时间戳筛词或排序**。改分离逻辑必跑 `pc/check_diar.py`。
- 改聚类逻辑必须用 `pc/mkfixture.py` 造的已知答案素材验收；素材的音色差异要用同文本时长确认，不能只回读 `Voice.Name`。三人以上未验收。
- 产物：`EP{n}.transcript.json`（分离后正本）、`EP{n}.transcript.nodiar.json`（分离前正本）、`EP{n}.words.json`、`EP{n}.diar.json`（每簇质心，原始空间）。

**字形归一**：写盘时按 opencc `t2s` 逐字表繁转简，`transcript.json` / `words.json` 同步，`orthography` 字段记录。禁用 `tw2sp` 等词汇转换表。存量用 `pc/t2s_backfill.py`。

**输出**：JSON 正本 `{start, end, speaker, text}`，浮点秒，永久不可变；`EP{n}.txt` 派生渲染。中英混杂保留原文。

**声纹库与点名**（`pc/speakers.py`，`_assets/speakers.json`）：
- 每集质心与库比对，门槛 0.65；库存每集样本，每人 ≤ 20 集按时长取长的，质心随取随算。
- **点名唯一入口是人在 EP 笔记里填**：认出的写名字，认不出的显示「未知N」+ 首次出现时间戳 + `[SPEAKER_XX:: ]` 空位；填完 worker 入库。不做自动入库。改名先把该集从旧名下摘掉。
- 一人一集只占一个簇；两簇同人时标「⚠ 声纹跟 X 是同一个人」，不挑赢家。
- 撞脸报警：库内两两相似度 > `LIB_WARN = 0.50` 报出；worker 日志每对只报一次，EP 笔记只报与本集有关的对，库健康时不写。
- 字段：`人物:` 机器独占（含「未知N」）；`主播:` / `嘉宾:` 只在空着时替人填一次。

**热词库**（`hotwords.json`）：走 faster-whisper `hotwords` 参数；只收多字词；入口只有人工回流（周末）；223 token 上限，注入前计 token、超限告警。

### 4.1 各层通用约定

- 一层一个无头调用：`claude -p --model <m> --effort <e> --system-prompt-file prompts/<层>.md --allowedTools ""`，输入走文件。
- 每层每单元留三份：原样输入 `_pairs/EP{n}/<层>-<单元>.in.md`、原始响应 `.raw.json`、解析后产物（`_digest/`）。`--replay` 从原始响应免额度重渲染。
- 失败只重跑该层该单元；schema 不过进 `_failed/` 报警，绝不静默丢。
- prompt 带版本号（文件首行 `version:`），产物 provenance 记 `prompt_version`。每层以 EP02 为 golden 样例。
- 不联网的层（L1、L2、L4、L6）不得引入逐字稿以外的事实；联网的层（L5a、L5b）每条判断必带链接。

### L1 骨架：整集 → 话题表

- 输入：整集逐字稿，§5.2 格式。
- 输出：`topics.json`（§5.3）。
- 规则：话题以「一个标题能概括、10 到 25 分钟」为粒度；开场白、观众问答、口播照列，标 `aside`；时间范围覆盖整集不留空洞（代码检查）。
- sonnet / low。

### L2 逐话题整理：切片 → 片段

- 输入：该话题的逐字稿切片（时间范围前后各留 2 分钟）。
- 输出：`frag-<topic>.json`（§5.4）：
  - `paras` 讲了什么：全长、按叙述顺序、不压成条目；每段开头一个时间戳；说话人 `<who>`；不确定语气 `<hedge>`。
  - `quotes` 原话锚点：每话题 ≤ 6 条，逐字照抄逐字稿某一段的连续文本。
  - `claims` 可核查的说法：数字、日期、归属、引述，带时间戳与原话；主播自标推测的不列。
  - `channels` 提到的信源：带时间戳与原话，只列不评。
  - `asr` 疑似 ASR 生音：原文写法 → 规范名。
- 规则：只用切片内容；不引入外部知识纠正主播；只删口水不删内容；`aside` 话题只写 ≤ 100 字概述。
- sonnet / medium，并发 ≤ 3。

### L3 闸门（纯代码）

1. **引文逐字命中**：每条 `quotes[].text` 是逐字稿某一段的连续子串；不命中的删除并计数。
2. **时间戳在范围内**：`paras` 与 `quotes` 的时间戳落在话题范围（含前后 2 分钟）内。
3. **限定词保留**：`claims[].quote` 含「应该 / 大概率 / 可能 / 我猜 / 听说 / 好像」时，`paras` 中对应句必须含 `<hedge>`；缺则标 `hedge_missing` 报警，不改。
4. **schema** 合 §5.4。
5. **覆盖**：所有 `talk` 话题有片段；`asr` 的规范名不出现在 `quotes` 里。

通过后渲染整理稿进 EP 笔记正文（§5.7），EP 笔记 `整理:` 置 `done`。

### L4 事件：各 EP → 当天事件清单

- 输入：当天所有 EP 的 `topics.json` + 各片段的 `claims`；附最近 30 天的事件 `id` 与标题列表。
- 输出：`events.json`（§5.5）。
- 规则：事件是「一件正在发生或被讨论的事」；只从 `talk` 话题聚，`aside` 不成事件；跨 EP 同一事件合并，同一 EP 内被打断的同一事件合并；已有 `id` 的事件沿用 `id`。**每个事件都进六问卡，不设每日上限。**
- sonnet / medium。要有自己的 golden 样例。

### L5a 事实核查：每事件 → 判定

- 输入：一个事件的全部 `claims` + 事件标题。联网。
- 输出：`check-<event>.json` 的 `deviations`（§5.6）。
- 规则：每条 `ok / warn / bad / none`，`basis` 一句话，`links` ≥ 1。没有链接不得判 `bad`；找不到依据判 `none`。**有多少条核多少条**；事件没有 `claims` 时 `deviations` 为空、`note` 写明。
- sonnet / high。

### L5b 证据 · 先例 · 分析：每事件 → 四问

- 输入：该事件各 EP 的 `paras` + L5a 结果。联网。
- 输出：同一文件的 `support`、`against`、`history.precedent`、`history.thenNow`、`history.readings`、`overall`。
- 规则：每条带链接；`readings` 写明作者与立场，不许「有人认为」；找不到先例写「没找到」；不改写、不转述 `paras`。
- opus / high。

### L6 导语与对照

- 导语：输入事件清单 + 各事件 `overall`，输出 ≤ 300 字。sonnet / low。
- 跨 UP 对照表：纯代码从 `events.json` 的 `refs` 拼；行是事件，列是 UP，格里 `gist` + 主时间戳；未谈写「未谈」。

### L7 渲染（纯代码）

- 写 `20-Daily/{date}.md`（§5.7）。
- 更新 `30-Events/{id}.md`：只追加「时间线」、只改 `last_seen` / `days`（§5.8）。
- 时间戳写成 `EP{n}@HH:MM:SS`。
- 写 provenance（§9）。

### 4.2 触发与调度

- 关注列表 `_pipeline/关注.md`：一行一个 UP 主空间链接；worker 每天扫新投稿与录播入队（里程碑 5 前手动粘链接）。
- 日报日期 = 内容发布日；当天无新内容不出日报。
- v1 用 `worker.ps1 -Digest <date>` 一条命令跑 L1 到 L7。

---

## 5. 数据契约

### 5.1 逐字稿 JSON

`_assets/EP{n}.transcript.json`：`{meta, segments: [{start, end, speaker, text}]}`，浮点秒，`speaker` 为人名或 `SPEAKER_XX`。永久不可变。

### 5.2 喂给模型的逐字稿文本

```
[00:05:00] 瓜哥: 休达这个事情呢我看到的消息是……
[00:05:30] ……
[00:06:00] 历史哥: 我补充一下……
```

时间戳每 30 秒一个（该窗第一段的 start）；说话人只在变化时写。由代码从 §5.1 生成，L1 喂整集，L2 喂切片。

### 5.3 话题表 `topics.json`

```json
{"ep": "EP02", "topics": [
  {"id": "midterm", "title": "2026 年中期选举：川普的三个动作", "kind": "talk",
   "ranges": [["01:04:32", "01:17:56"], ["02:15:00", "02:18:40"]],
   "who": ["瓜哥", "历史哥"], "gist": "访华、重划选区、SAVE Act 三招保两院"}
]}
```

`kind`：`talk` / `aside`。

### 5.4 话题片段 `frag-<topic>.json`

```json
{"id": "midterm", "title": "…", "ranges": [...], "who": [...],
 "paras": ["[01:04:32] <who>瓜哥</who>说川普为中期选举做了三个动作……<hedge>应该</hedge>能稳住 210 席……"],
 "quotes": [{"ts": "01:05:18", "who": "瓜哥", "text": "好棒棒的共和党选民52%但认为川普好棒棒的民主党选民只有12%差距40%"}],
 "claims": [{"ts": "01:05:18", "who": "瓜哥", "claim": "盖洛普：认为川普好的共和党选民 52%、民主党选民 12%", "quote": "…"}],
 "channels": [{"ts": "01:06:02", "who": "瓜哥", "name": "盖洛普", "kind": "民调机构", "quote": "…"}],
 "asr": [{"heard": "超盘术", "means": "操盘术"}]}
```

`paras` 只认 `[HH:MM:SS]`、`<who>`、`<hedge>` 三种标记。`quotes[].ctx`（所在段全文）由 L3 补。

### 5.5 事件清单 `events.json`

```json
{"date": "2026-08-02", "events": [
  {"id": "2026-us-midterm", "title": "2026 年中期选举：川普的三个动作，以及他会不会输", "tag": "美国政治 · 选举",
   "refs": [{"ep": "EP02", "topic": "midterm", "ts": "01:04:32", "gist": "三招保两院，稳赢约 210 席但摇摆区不利"},
            {"ep": "EP02", "topic": "dem-midterm", "ts": "00:20:26", "gist": "连线前独白：民主党占上风但很废物"}]}
]}
```

`refs[0]` 是主引用。`id` 跨天稳定。

### 5.6 核查 `check-<event>.json`

```json
{"event": "2026-us-midterm", "overall": "warn",
 "deviations": [{"ts": "01:05:18", "claim": "盖洛普 52% / 12%", "verdict": "bad",
                 "basis": "盖洛普 2026-07 该题为共和党 89%、民主党 3%", "links": ["https://…"]}],
 "support": [{"point": "…", "links": ["…"]}],
 "against": [{"point": "…", "links": ["…"]}],
 "history": {"precedent": "…", "thenNow": "…",
             "readings": [{"who": "…", "stance": "…", "point": "…", "link": "…"}]},
 "sources": ["…"], "note": "只核了 11 条，跳过的 3 条是主播自标推测"}
```

`overall`：`ok` 无重大偏差 / `warn` 有偏差不影响主线 / `bad` 主线建立在错事实上 / `none` 没核。

### 5.7 日报笔记 `20-Daily/{date}.md`

```markdown
---
type: daily
date: 2026-08-02
sources: [EP02]
events: [2026-us-midterm, …]
generated_at: 2026-08-03T06:12:00
pipeline_version: v3.0
---
# 2026-08-02 日报

（导语）

## 今天的事件
1. [[30-Events/2026-us-midterm|2026 年中期选举…]] · 美国政治 · 选举 · 瓜哥 EP02@01:04:32 · ⚠ 有偏差

## 事件卡
### 2026 年中期选举：川普的三个动作，以及他会不会输
**讲了什么** —— 主引用的 paras 全长；次引用另起小段
**重大事实偏差** —— verdict ≠ ok 的条目：时间戳 · 说法 · 判定 · 依据 · 链接
**支持的证据** / **不支持的情况**
**历史先例 · 当时 vs 现在**
**有见地的分析** —— 每条：作者（立场）· 观点 · 链接
> [!note]- 核查台账（全部 N 条）

## 其余话题
（`aside` 话题，只放概述）

## 跨 UP 对照
| 事件 | 瓜哥 | … |

## 他们提到的信源
| 信源 | 类型 | 谁提到 | 时间戳 | 原话 |
```

**单集整理稿**渲染在 EP 笔记 `## 整理稿` 下：按话题顺序放 `paras`、原话锚点、可核查的说法、提到的信源、疑似 ASR 生音；时间戳用裸 `[HH:MM:SS]`。

### 5.8 事件笔记 `30-Events/{id}.md`

```markdown
---
type: event
id: 2026-us-midterm
title: 2026 年中期选举
first_seen: 2026-08-02
last_seen: 2026-08-02
days: [2026-08-02]
---
## 我的判断
（人写。软件永不碰这一节，空着也留着。）

## 时间线
### 2026-08-02
- 瓜哥 EP02@01:04:32：三招保两院…（overall: warn）→ [[20-Daily/2026-08-02#事件卡]]
```

L7 只在「时间线」下追加，只改 `last_seen` / `days`，其余字节不动。

### 5.9 标记

| 标记 | 含义 | 谁写 | 谁认 |
|---|---|---|---|
| `[HH:MM:SS]` | 本集时间戳，EP 笔记内 | L2 | 跳播插件 |
| `EP02@HH:MM:SS` | 指定集时间戳，日报 / 事件笔记内 | L7 | 跳播插件 |
| `<who>名字</who>` | 说话人 | L2 | 渲染为小标 |
| `<hedge>应该</hedge>` | 不确定语气 | L2 | 渲染为虚线下划线；闸门 3 |
| `ok / warn / bad / none` | 核查判定 | L5a / L5b | 渲染为徽标；人周末可改 |

---

## 6. Obsidian Vault 结构

```
Vault/story-machine/
├── 10-Episodes/       EP 笔记：frontmatter + 说话人小表 + 状态条 + 整理稿
├── 20-Daily/          日报
├── 30-Events/         事件笔记（「我的判断」人写，「时间线」机器追加）
├── _assets/           EP{n}.m4a / .transcript.json / .txt / .meta.json / .words.json / .diar.json / .transcript.nodiar.json / speakers.json
├── _pipeline/         控制台.md / 队列.md / 关注.md
├── _pairs/            每层每单元的原样输入 + 原始响应（永久）
├── _digest/           每层的解析后产物，按 EP 与日期分目录（人不看）
├── _failed/           不过 schema 的单元
└── _lab/              实验与原型留档（不进公开仓库）
```

`15-Materials/`、`_review/`、`_queries/`、`_index/` 退役：现存内容搬进 `_lab/v2/`，目录删除。

`EP{n}.transcript.json` 是正本，永久不可变；`EP{n}.m4a` 必须在 vault 内。

### 6.1 EP 笔记 frontmatter

```yaml
---
type: episode
episode: EP02
title: 一起聊聊吧
音频: EP02.m4a               # 不能省（ADR 0001）
播出日期: 2026-08-02        # 日报按它归档
up: 迷宫干饭人               # 机器抄 meta.json 的 uploader
主播: ["瓜哥"]              # 人的字段；worker 只在空着时填一次
嘉宾: ["历史哥"]
人物: ["瓜哥", "历史哥"]     # 机器独占；认不出的写「未知1」
transcript: ../_assets/EP02.transcript.json
逐字稿渲染: ../_assets/EP02.txt
时长: 03:10:43
来源: https://www.bilibili.com/video/BV1TcM96DEPB
转写引擎: faster-whisper large-v3
说话人分离: 3dspeaker-campp   # pending | 3dspeaker-campp
整理: done                    # pending | running | done | failed
整理版本: L2@0.1
---
```

---

## 7. 模型与思考深度

| 层 | 模型 | effort | 联网 |
|---|---|---|---|
| 阶段 0 | 本地 faster-whisper / CAM++ | — | 否 |
| L1 骨架 | sonnet | low | 否 |
| L2 逐话题整理 | sonnet | medium | 否 |
| L3 闸门 | 纯代码 | — | — |
| L4 事件 | sonnet | medium | 否 |
| L5a 事实核查 | sonnet | high | 是 |
| L5b 证据·先例·分析 | opus | high | 是 |
| L6 导语 | sonnet | low | 否 |
| L7 渲染 | 纯代码 | — | — |

起手值，实跑一天后填真实 token 数回来调。额度大头在 L5。

---

## 8. 红线（不可协商）

1. **ASR 只听写**，不总结不脑补；分离与字形归一不改一个字。
2. **整理不脑补、不删事**：「讲了什么」只来自该话题切片；不引入外部知识纠正主播；只删口水。原话锚点逐字来自逐字稿，时间戳真实。
3. **限定词与不确定语气原样保留**并用 `<hedge>` 标出。「应该是」不能写成「是」。
4. **核查判定是 AI 初判，每条必带来源链接**；没有链接不得判 `bad`；找不到依据判 `none`。
5. **核查不改整理**：L5 只加批注，不改写、删减、转述 L2 的文字。
6. **人每天只读日报**，永不通读逐字稿、永不审中间产物；阅读预算见 §1.3。
7. **综合归人**：「我的判断」软件永不碰；不自动生成脉络、实体笔记、知识图谱。
8. **不猜年份、不补日期**：主播没说的时间不写；核出的正确日期写在判定里。
9. **每个派生文件带 provenance**；缺哪层从哪层重跑，绝不静默丢单元。
10. **逐字稿片段不进公开仓库**：仓库只放代码、prompt、schema、合成或脱敏样例。

---

## 9. 资产与 provenance

全部留下。每个派生文件带：

```yaml
---
derived_from: [EP02.transcript.json, topics.json]
layer: L2
unit: midterm
engine: claude-sonnet-5
effort: medium
prompt_version: L2-topic@0.1
generated_at: 2026-08-03T05:40:12
---
```

`derived_from` 齐全 + 输入还在 = 可重生成 = 可删。

**永久正本**：逐字稿 JSON、`EP{n}.meta.json`、`_pairs/`、`speakers.json`、事件笔记的「我的判断」、人改过的核查判定（人改标签时在该条后追加 `[人改:: 日期]`，渲染不覆盖）。

---

## 10. 开发优先级（= issue #50）

1. **L1 到 L3 单集整理稿**：EP02 当 golden；落 EP 笔记正文；状态条加「整理」按钮。判据：整理稿 30 分钟内读完，闸门 1 通过率 100%。
2. **L4 + L7 单 UP 日报**：六问卡先只有「讲了什么」。
3. **L5a 事实核查**。
4. **L5b 证据 · 先例 · 分析**。
5. **多 UP**：`关注.md` + 自动入队 + 跨 UP 对照。
6. **事件笔记跨天**。
7. **参数打磨**：话题粒度、锚点数、每层 model / effort。

---

## 11. 未定

- 时间戳跳播：限定符走本地音频（现行），还是加 B 站 `?t=` 链接作第二按钮。
- 队列状态机是否延伸到 L1 到 L7。
- 事件 `id` 跨天匹配：30 天回看够不够；换角度谈同一件事算不算同一事件。
- 闸门 3 的限定词清单会漏什么。
- L5a 是否需要升 opus。
- 动态何时纳入。
