# QA — issue #51 骨架（曳光弹）：Extract EP → L1 话题表 → EP 笔记出现可跳播的话题大纲

分支 `agent/issue-51`。沙箱内 `bash scripts/test.sh` 全绿（39 个 pytest 用例），
没有调用过 `claude -p`，没有碰过 vault，所有用例跑在 `tests/fixtures/vault/` 的
临时副本上。

---

## 1. 改动摘要

| 文件 | 做了什么 |
|---|---|
| `scripts/sm/`（新，10 个文件） | 各层共用的机械件：`text`（时间戳与归一）、`note`（EP 笔记读写、frontmatter、点名）、`paths`（vault 路径、找 EP 笔记）、`transcript`（§5.1 → §5.2）、`runner`（真实 / 重放 / 假 runner + `extract_json`）、`pairs`（三份留档、重试、`_failed/`）、`prov`（§9 + prompt 版本）、`l1`（L1 调用与 `check_topics`）、`render_ep`（标记块渲染与写回） |
| `prompts/L1-skeleton.md`（新） | L1 骨架 prompt，首行 `version: L1-skeleton@0.1` |
| `scripts/digest.py`（新） | 单集入口 `ep EP{n} --vault <dir> [--force] [--runner fake:<root>] [--model] [--effort] [--timeout] [--retries] [--now]` |
| `scripts/worker.ps1` | `-Extract` 从 `stage12.py --ep` 改成 `digest.py ep`，`-Redo` → `--force`，完成提示改成「话题大纲已写进 EP 笔记」（静态改，沙箱跑不了 PowerShell） |
| `scripts/stage12.py`、`scripts/test_stage12.py` | 删。取回：`git show 1d82498:scripts/stage12.py` |
| `SPEC.md` | §4.1 补 `scripts/sm/`；§4 L1 补输入头、时长取法、prompt 文件名、五条代码检查；§4.2 补 `-Redo` → `--force` 与退出码 0/1/2、找笔记的规则；§5.7 补块首行说明、`整理版本:` 取法、L2 上线前整理稿的形状 |
| `docs/agents/domain.md` | 目录树补 `prompts/`、`scripts/digest.py`、`scripts/sm/`、`tests/` |
| `docs/agents/afk-sandcastle.md` | 「沙箱已知坑」两处指针换成 `digest.py` / `conftest.py` 的 `vault` fixture（原来指 `stage12.py` / `test_stage12.py`） |
| `tests/`（新，5 个文件 + `conftest.py`） | 37 个用例，逐条对应验收标准 |

契约层面值得单独看的三处决定：

1. **时长取逐字稿最后一段的 `end` 取整秒**，不读 EP 笔记的 `时长:`。正本不可变，
   笔记那行是人看的、可能被改过；覆盖检查必须跟模型看到的那份文本对得上。
   （EP91 2559.6s → `00:42:40`，与笔记一致，`test_duration_comes_from_the_last_segment`
   把两者钉在一起。）
2. **`整理版本:` 取 `topics.json` 的 `provenance.prompt_version`**，产物缺
   provenance 时退回当前 prompt 的版本。跳过 L1 重渲染时写的是当初生成它的那个
   版本——不是现在磁盘上的 prompt 版本。
3. **`_pairs/` 是永久正本**：`ReplayRunner` 带 `replay = True`，`call_layer` 见到它
   就不重写 `.in.md` / `.raw.json`。（`--replay` 开关本票不接，归 #55；类已就位。）

---

## 2. 「可见变化」演示（fixture 副本，合成内容）

```
$ rm -rf /tmp/demo && cp -r tests/fixtures/vault /tmp/demo
$ python scripts/digest.py ep EP91 --vault /tmp/demo --runner fake:tests/fixtures/raw
[04:07:54] EP91：76 段 / 00:42:40，说话人 阿桥（主播）、老周（嘉宾），prompt L1-skeleton@0.1@5905fddf
[04:07:54] L1 骨架：整集一次调用（sonnet / effort low，超时 1800s）
[04:07:54]     L1-all 第 1 次调用（sonnet / effort low）…
[04:07:54] L1 通过：4 个话题 → _digest/EP91/topics.json
[04:07:54] 话题大纲已写进 10-Episodes/EP91 河口夜话 2026年3月12日 北港大桥与夜市.md（整理: done，整理版本 L1-skeleton@0.1）
退出码 0
```

`10-Episodes/EP91 河口夜话 2026年3月12日 北港大桥与夜市.md` 里 `<!-- /speakers -->`
之后长出来的那一块（原样贴，合成内容）：

```markdown
<!-- /speakers -->

<!-- digest:auto -->
## 整理稿

> [!info] 本块由 L3 渲染（整理版本 L1-skeleton@0.1，生成于 2026-09-17T04:07:54+00:00）；重跑会覆盖，批注请写在块外。

### [00:00:00] 开场与设备测试 · 旁白

问好、换麦、预告两个话题

### [00:03:30] 北港大桥收费方案：十五块还是十二块
范围 [00:03:30]–[00:19:00]、[00:36:00]–[00:41:30]

通报按车型收费、听证会建议价、贷款与 2019 隧道先例、货车与浮桥

### [00:19:00] 河口夜市搬迁：消防倒逼下的选择

晚报报道搬滨江路、商户反对、消防隐患、老码头先例

### [00:41:30] 结尾弹幕与下周预告 · 旁白

下周聊老照片
<!-- /digest -->

## 断言
```

四个 `###`（开场 / 北港大桥 / 夜市 / 结尾），大桥那条列出两段范围；`## 断言`
和 `## 待办` 两节在块后原样保留。frontmatter 尾部：

```yaml
人物: ["阿桥", "老周"]
整理: done
整理版本: L1-skeleton@0.1
```

再跑一次（秒回，不调 runner）：

```
[04:08:05] EP91：76 段 / 00:42:40，说话人 阿桥（主播）、老周（嘉宾），prompt L1-skeleton@0.1@5905fddf
[04:08:05] L1 产物已在（_digest/EP91/topics.json），跳过调用——要重跑加 --force
[04:08:05] 话题大纲已写进 10-Episodes/EP91 河口夜话 2026年3月12日 北港大桥与夜市.md（整理: done，整理版本 L1-skeleton@0.1）
退出码 0
```

坏响应（覆盖空洞 + 缺 `kind`）的样子——这是红线 9 在终端上的形态：

```
$ python scripts/digest.py ep EP91 --vault /tmp/demobad --runner fake:tests/fixtures/raw-bad
[04:08:05]     L1-all 第 1 次调用（sonnet / effort low）…
[04:08:05]     L1-all 检查不过（2 项）：qa: 缺字段 `kind`
[04:08:05]     L1-all 第 2 次调用（sonnet / effort low）…
[04:08:05]     L1-all 检查不过（2 项）：qa: 缺字段 `kind`
[04:08:05]     ⚠ L1-all 重试 1 次仍不过 → /tmp/demobad/_failed/EP91/L1-all.failed.json（不静默丢单元）
[04:08:05] ✖ L1 检查不过（2 项），已落 _failed/EP91，笔记打 整理: failed
[04:08:05]     · qa: 缺字段 `kind`
[04:08:05]     · 覆盖有空洞：00:19:00–00:22:00（3.0 分钟，在 bridge-toll 与 night-market 之间）
退出码 1
```

笔记上只多了 `整理: failed` 一行，没有标记块。

---

## 3. 沙箱内已验证清单（验收标准 → 测试）

| # | 验收标准 | 测试 |
|---|---|---|
| 1 | 端到端：退出码 0、三份留档、`topics.json` 去 provenance 等于 fixture、块紧跟 `<!-- /speakers -->`、四个 `###` 与时间戳、大桥两段范围、`整理: done` / `整理版本`、去块与两行后逐字节相等 | `test_s1_skeleton.py::test_ep91_end_to_end` |
| 2 | EP92 的 `整理: pending` 原位变 `done`，其他行不变 | `::test_ep92_pending_flips_in_place`（去掉块与新增行、把 done 换回 pending 后与原文逐字节相等） |
| 3 | 再跑 runner 调用 0 次、笔记逐字节不变；`--force` 调用 1 次 | `::test_rerun_skips_l1_and_force_recalls` |
| 4 | `raw-bad`：`_failed/` 存在、错误同时提到 `00:19:00` 的空洞与缺字段、无 `topics.json`、笔记无块且 `整理: failed`、退出码 1 | `::test_bad_l1_goes_to_failed` |
| 5 | 逐字稿不存在 → 退出码 2，笔记不动 | `::test_missing_transcript_exits_2` |
| 6 | §5.2：行首时间戳 = 该行第一段 start；同窗同人一行、段间一个空格；说话人变化另起一行带名字；行内容去掉行首等于原段文本拼接；未点名保留 `SPEAKER_00: ` | `test_sm_transcript.py::test_ep91_lines_are_verbatim`（`walk()` 把每行拆回段文本，最后断言 76 段一段不少）、`::test_same_window_same_speaker_joins_with_one_space`、`::test_speaker_change_inside_one_window_breaks_the_line`、`::test_unnamed_speaker_keeps_the_tag` |
| 7 | `check_topics`：3 分钟空洞 / 重叠 1 分钟 / 起点晚于终点 / 终点超时长报错，缝 3 秒通过 | `test_sm_l1.py::test_three_minute_hole`、`::test_one_minute_overlap`、`::test_start_after_end`、`::test_end_past_duration`、`::test_three_second_seam_passes`（另有头尾空洞、字段类型、id 重复、ep 不符） |
| 8 | `call_layer` 重试 `retries+1` 次后写 `_failed/` 返回 None；`extract_json` 对散文抛 `ValueError`，对围栏 / 带前言 JSON 都能取出 | `test_sm_pairs.py::test_retries_then_failed`、`::test_extract_json_shapes` |
| 9 | provenance 字段集合 == §9；`engine` 取 `modelUsage` 中 costUSD 最大者 | `::test_provenance_keys_are_spec_9`、`::test_engine_takes_the_costliest_model`，端到端里也断言了产物的 provenance 键集合 |
| 10 | `read_speakers` 得 `阿桥（主播）` / `老周（嘉宾）`；`render_lines` 行首只用名字 | `test_sm_transcript.py::test_read_speakers_takes_name_and_role`、`::test_ep91_lines_are_verbatim` |
| 11 | 没有 `<!-- /speakers -->` 也没有 `<!-- /ep -->` → 块追加文末 | `test_s1_skeleton.py::test_block_appended_when_no_anchor` |
| 12 | prompt 首行 `^version: L1-skeleton@\d+\.\d+$`，正文含六个键与 `talk` / `aside` | `test_sm_l1.py::test_prompt_version_and_schema_in_body` |
| 13 | `worker.ps1` 不含 `stage12`、`-Extract` 调 `digest.py` 且参数含 `ep`、`-Redo` → `--force`；两个 stage12 文件不存在；`scripts` `docs/agents` `SPEC.md` `CLAUDE.md` `CONTEXT.md` `.sandcastle/prompts` 里搜不到 `stage12` | `test_worker_static.py`（4 个用例；grep 那条在 python 里遍历，`docs/adr/` 不在搜索面内——stage12 曾经存在这件事是历史，不该抹） |

红线映射：红线 1（不改一个字）验收 6 的 `walk()`；红线 6（人只读日报）
`::test_stdout_says_each_step_and_no_content` + 块首行；红线 7 类比验收 1、2 的
字节相等；红线 9 验收 4、8、9；红线 10 只用 `tests/fixtures/` 的合成样例。

另外四条不在票面但顺手钉住的：

- `_pairs/` 不被 `ReplayRunner` 重写（`test_replay_runner_reads_pairs_and_keeps_the_archive`）。
- 已有 `topics.json` 被写坏时停下报错而不是悄悄覆盖
  （`test_broken_topics_json_stops_instead_of_overwriting`）。
- **CRLF 笔记往返**（`test_crlf_note_keeps_crlf`）：fixture 是 LF，宿主机上
  Obsidian 写的是 CRLF。第一版在 CRLF 笔记里追加 `整理版本:` 时会留下一个裸 LF
  （frontmatter 正则把末行行尾吃进了分隔符），真机第一次跑就会踩到——已修，并用
  这条用例钉住。
- 标题 / `gist` 里的换行与 `<!--` 在 `check_topics` 就拦下
  （`test_title_that_would_break_the_marker_block`）：这两个字段原样进标记块，
  换行会把 `### …` 撑成两行，`<!-- /digest -->` 会让下一次整块替换只替换掉半块。

---

## 4. 我认为风险最高的两个点

**（一）§5.2 的分行在真实逐字稿上还没见过面。** fixture 的段都是 17–35 秒的
长段，落进 30 秒窗时几乎一段一行，所以「同窗同人连成一行、段间一个空格」这条
只有一个现造的三段样例在测。faster-whisper 的真实段是几秒一段，EP02 上每行会
由 5–10 段拼起来——拼错的表现是：行首时间戳不再是 30 秒一跳（而是跳几秒），或
者一行装了一两分钟的话。合并后先看 `_pairs/EP02/L1-all.in.md` 的前 30 行，确认
行首时间戳基本每 30 秒一跳、说话人只在变化时出现。

**（二）覆盖检查对 3 小时一集是全有或全无。** 模型在整集任何位置留下 > 5 秒的
缝，都会重试一次后整集进 `_failed/`，`整理:` 打成 `failed`，没有部分产物。这是
票面定的失败语义（红线 9），但 EP02 第一次真跑很可能就栽在这条上。栽了先读
`_failed/EP91/…` 里的错误行——它带着空洞两头的时间戳；如果是模型系统性地在话题
之间留缝，**改 prompt 升 `version:` 重跑**，不要去放宽 `SEAM_S`（那等于让后面
每一层都在漏了几分钟的切片上干活）。

---

## 5. 合并后跑真实样例的验证指引（人，笔记本交互式会话）

> 下面整节可以直接当提示词用。vault = `D:\obsidian-task\任务栏\story-machine`。

### 5.1 跑

```powershell
.\scripts\worker.ps1 -Extract EP02
```

worker 只做三件事：查 `_assets\EP02.transcript.json` 在不在、起
`python scripts\digest.py ep EP02 --vault <vault>`、把 stdout 原样喷出来。想直接
调 python（比如要换 model / effort）：

```powershell
python scripts\digest.py ep EP02 --vault "D:\obsidian-task\任务栏\story-machine" --model sonnet --effort low
```

- `--model` / `--effort` 默认 `sonnet` / `low`（SPEC §7 的 L1 起手值），`--timeout`
  默认 1800 秒，`--retries` 默认 1（检查不过再调一次）。
- **`--replay` 本票没有**（归 #55）。想不烧额度重渲染，只能先把
  `_digest\EP02\topics.json` 留着重跑（它在就跳过 L1，只重渲染笔记）。
- `--runner fake:<root>` 只在测试里用，别拿它跑真实集。
- 一集一次调用，整集约 5.5 万字进 prompt；3 小时一集预计几十秒到两三分钟。

### 5.2 看什么

1. **`_digest\EP02\topics.json`**
   - 话题数 **8–15**；`talk` 的时间跨度 **10–25 分钟**；`aside` 只盖开场 / 口播 /
     问答 / 结尾预告。
   - `ranges` 排序后从 `00:00:00` 接到 `时长`，首尾相接（代码已判过一遍，这里是
     看它判得对不对）。
   - `id` 全小写短横线、看得出是哪件事（不是 `topic1`）。
   - `gist` 是导航用的一句话，不是结论——**它替主播下了判断就是 prompt 的问题**。
   - 顶层 `provenance` 七个键齐（`derived_from` / `layer` / `unit` / `engine` /
     `effort` / `prompt_version` / `generated_at`），`engine` 应当是
     `claude-sonnet-5` 这种真实模型名，不是 `sonnet`。
2. **`_pairs\EP02\L1-all.in.md`**（喂进去的原样输入）
   - 第一行是 `episode: EP02 · 时长 HH:MM:SS · 说话人 …`，第二行 `---`。
   - 之后每行 `[HH:MM:SS] 名字: …`，时间戳基本每 30 秒一跳，说话人只在变化时写；
     没点名的应当是 `SPEAKER_00` 原样（那说明该去笔记里点名了）。
3. **`_pairs\EP02\L1-all.raw.json`**
   - `duration_ms`（这一层花了多久）、`total_cost_usd`（额度折算）、
     `modelUsage` 里那个 costUSD 最大的模型名。记下来回填 SPEC §7。
4. **EP02 笔记**（Obsidian 打开）
   - `<!-- /speakers -->` 之后一块 `<!-- digest:auto -->` … `<!-- /digest -->`，
     里面每话题一行 `### [HH:MM:SS] 标题`。
   - **点两个时间戳看跳播**（ADR 0001 的插件认裸 `[HH:MM:SS]`）：一个开场附近的，
     一个一小时以后的。
   - frontmatter 多了 `整理: done`、`整理版本: L1-skeleton@0.1`；人写的段落、旧的
     节、`主播:` / `嘉宾:` / `人物:` 一个字节都没动。
   - 再跑一次 `-Extract EP02`：应当秒回「L1 产物已在…跳过调用」，笔记内容不变。

### 5.3 什么现象说明坏了

| 现象 | 说明 | 怎么办 |
|---|---|---|
| 退出码 1、`整理: failed`、`_failed\EP02\L1-all.failed.json` 出现 | L1 两次都没过代码检查，错误行在那个文件的 `errors` 里（空洞带两头时间戳、缺字段带话题 id）。上一次成功渲染的块留着不动——块首行的生成时间就是上一次那次 | 空洞 / 重叠 / 粒度问题 → 改 `prompts\L1-skeleton.md` 升 `version:`，`-Extract EP02 -Redo`。字段缺失反复出现 → 把 §5.3 的例子在 prompt 第三节写得更死 |
| 退出码 2、说找不到逐字稿 / 笔记 / prompt | 阶段 0 没跑完，或笔记文件名与 frontmatter 的 `episode` 都不是 `EP02` | 先补阶段 0；笔记按「文件名以 `EP02 ` 开头」或 frontmatter `episode: EP02` 找 |
| 抛 Python 栈、提到 `claude` | 环境问题（CLI 不在 PATH、退出码非 0、信封不是 JSON、`is_error`）。这时笔记已经打成 `整理: failed` 了 | 修环境重跑；`_pairs\` 里那次的 `.raw.json` 可以直接看模型到底回了什么 |
| 话题只有 3–4 个、每个 40 分钟 | 粒度崩了，不是代码问题 | 改 prompt 升版本重跑；别改代码里的检查 |
| 笔记里时间戳点不动 | 块里的时间戳被包进了反引号或链接 | 看块内那行是不是裸 `[HH:MM:SS]`；frontmatter 的 `音频:` 不能省（ADR 0001） |
| 块内人写的批注消失了 | 正常：块每次重跑整块替换（块首行写着这句） | 批注写在 `<!-- /digest -->` 之后 |

### 5.4 回退

- 整张 PR：`git revert`。
- vault 里：删 `_digest\EP02\`（派生的，`derived_from` 齐全，随时重生成）、
  手删 EP02 笔记里的 `<!-- digest:auto -->` … `<!-- /digest -->` 整块、把
  `整理: done` 改回 `pending`。`_pairs\EP02\` 建议留着（永久正本，#55 的 `--replay`
  要用它免额度重渲染）；真要清就连 `_failed\EP02\` 一起删。
- 只想换 prompt 重跑：`-Extract EP02 -Redo` 会覆盖 `.in.md` / `.raw.json` /
  `topics.json` 与笔记里那一块，不碰块外。
