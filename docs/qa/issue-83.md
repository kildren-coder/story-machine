# QA — issue #83 闸门 1 近似命中归一：少抄或错抄一两个字的引文换成逐字稿原句留下

分支 `agent/issue-83`。沙箱内 `bash scripts/test.sh` 全绿（202 个 pytest 用例，比
开工时的 189 个多 13 个），没有调用过 `claude -p`，没有碰过 vault，所有用例跑在
`tests/fixtures/vault/` 的临时副本上。

#53 的闸门 1 只有「逐字命中 / 删」两档。EP02 实跑 171 条引文删 1 条，删的那条是
模型把「基本上可以认为」抄成「基本可以认为」——逐字稿原句就在旁边，删掉不如换成
原句留下。本票在中间插一档**归一**：`ts` 前后 2 分钟内的段上对齐，差得不超过预算
就把 `text` 换成那一段原文里的连续一截，`from` / `to` 记进 `gates.json`（红线 9：
不静默），丢掉的限定词随原句一起回来（红线 2）。2026-09-22 拍板**代码归一、不引入
模型仲裁**，所以这一票纯代码、零调用。

---

## 1. 改动摘要

| 文件 | 做了什么 |
|---|---|
| `scripts/sm/text.py` | 新增 `norm_map(s) -> (nstr, idx)`：`norm()` 的带索引版，`idx[i]` 是 `nstr[i]` 在原文里的下标，用来把归一化文本上的跨度映射回原文（原文里的空格、英文、时间戳原样带回来）。`norm()` 本身一个字没动 |
| `scripts/sm/l3.py` | 闸门 1 改成三档：逐字命中 → 近似命中归一 → 删。新增 `align_span()`（半全局编辑距离，插 / 删 / 换各 1，同距离取最短跨度、再同取最靠前）、`snap_segment()`（候选段 = 与 `[ts ± 120s]` 有交集的段，取距离最小的跨度，换成该跨度在原文里的那一截）、`near()`；模块常量 `SNAP_MIN_LEN = 6`、`SNAP_EDITS_PER_10 = 1`。`gate_frag` 每话题多记 `quotes_snapped` 与 `snapped: [{ts, from, to}]`，`COUNTERS` 跟着加一个键（`GateReport.totals` 自动带上） |
| `scripts/sm/render_ep.py` | 块首行改成「闸门：归一引文 j 条、删引文 n 条、越界 m 条、删 ASR 条目 k 条」，全 0 也写 |
| `scripts/digest.py` | `L3 闸门：` 那行同样多一个「归一引文 n 条」 |
| `SPEC.md` | §4 L3 第 1 条写成三档（含两个阈值与 tie-break 顺序）；「只删、只警、只补 `ctx`」改成「只删、只警、只补 `ctx`、只把近似命中的 `quotes[].text` 换成逐字稿原文」；`gates.json` 字段加两个键；§5.4 注明 `text` 可能被 L3 换成逐字稿原文；§5.7 块首行四个数 |
| `tests/fixtures/mkfixtures.py` | 把出票时手写进仓库的 `l3/frag-market-01.snap.json` 接回生成脚本（脚本每次跑都先 `rmtree` 掉 `l3/`，不接回去的话谁重生成一次这份片段就没了）；速查表里 `.bad.json` 那行改准 |
| `tests/` | `test_sm_l3.py` +10、`test_s3_gates.py` +3；`test_sm_render_ep.py` 的 `ZERO` 与两条块首行断言跟着改 |

**没动的**：`prompts/*.md`（票面明确不动）、L1 / L2 / L4 以后的层、闸门 2 / 3 / 5
的判法、`quotes[].ctx` 的语义（照旧是所在段全文）。

现有用例跟着改档的两处，评审时值得对一眼：

1. `tests/fixtures/l3/frag-market-01.bad.json` 里「摊位不到一百个摊」那条从「删」
   变成「归一」：`quotes_dropped` 1 → 0、`quotes_snapped` 0 → 1，笔记上那一节的
   锚点从 3 行变成 4 行（越界那条与编出来的 ASR 条目照删）。
2. `test_sm_l3.py::test_a_quote_that_is_not_verbatim_is_dropped_and_counted` 原来用
   「改造预算是一千三百万」当「不逐字」的样本——它现在差一个字，正好归一。换成差
   3 处的改写（23 字容许 2 处）才是这一档要的样本。

---

## 2. 「可见变化」演示（fixture 副本，合成内容）

照票面那条跑：把 fixture 的 `_digest/EP91/` 铺进副本，再用
`tests/fixtures/l3/frag-market-01.snap.json` 顶替 `frag-market-01.json`。L1 与 L2
的产物就此齐全，这一趟一次调用都不会发，只跑闸门与渲染。

```
$ rm -rf /tmp/demo83 && mkdir -p /tmp/demo83 && cp -r tests/fixtures/vault /tmp/demo83/vault
$ mkdir -p /tmp/demo83/vault/_digest && cp -r tests/fixtures/digest/EP91 /tmp/demo83/vault/_digest/EP91
$ cp tests/fixtures/l3/frag-market-01.snap.json /tmp/demo83/vault/_digest/EP91/frag-market-01.json
$ python scripts/digest.py ep EP91 --vault /tmp/demo83/vault --runner fake:tests/fixtures/raw
[07:46:16] EP91：76 段 / 00:42:40，说话人 阿桥（主播）、老周（嘉宾），prompt L1-skeleton@0.9@ecefac87
[07:46:16] L1 产物已在（_digest/EP91/chapters.json），跳过调用——要重跑加 --force
[07:46:16] L2 逐章节整理：2 章，一章一次调用（sonnet / effort medium，并发 3，超时 1800s/章，prompt L2-topic@0.2@963e68d7）
[07:46:16]     L2：2 章已完成，跳过不调用——要重跑加 --force
[07:46:16]     L2：2 章的 prompt_version 落后于当前 prompt（L2@0.1、未记 → L2-topic@0.2），要重跑加 --force
[07:46:16] L2 通过：5 个话题（talk 3、aside 1、filler 1）；正文合计 1438 字 / 逐字稿 1857 字，压缩比 0.77 → _digest/EP91/topics.json
[07:46:16]     L3：5 个话题过了闸门，写回 3 份片段（越界的段只记不删，红线 2）
[07:46:16] L3 闸门：归一引文 2 条、删引文 2 条、越界 0 条、删 ASR 条目 0 条，越界段 0 处 → _digest/EP91/gates.json
[07:46:16] 整理稿已写进 10-Episodes/EP91 河口夜话 2026年3月12日 北港大桥与夜市.md（整理: done，整理版本 L2@0.1）
退出码 0
```

`_digest/EP91/gates.json`（贴出 `market-01` 与一条全 0 的对照）：

```json
{
 "ep": "EP91",
 "generated_at": "2026-09-22T07:46:16+00:00",
 "topics": {
  "market-01": {
   "quotes_snapped": 2,
   "quotes_dropped": 2,
   "quotes_out_of_range": 0,
   "paras_out_of_range": [],
   "asr_dropped": 0,
   "snapped": [
    {
     "ts": "00:20:13",
     "from": "我上个月去数过，摊位不到一百个摊",
     "to": "我上个月去数过，摊位不到一百个"
    },
    {
     "ts": "00:22:39",
     "from": "六月底是赶在暑假前，暑假是夜市生意最好的时候",
     "to": "六月底应该是赶在暑假前，暑假是夜市生意最好的时候"
    }
   ],
   "schema": "ok"
  },
  "market-02": {
   "quotes_snapped": 0,
   "quotes_dropped": 0,
   "quotes_out_of_range": 0,
   "paras_out_of_range": [],
   "asr_dropped": 0,
   "snapped": [],
   "schema": "ok"
  }
 }
}
```

笔记里那一块的**块首行**（`L2@0.1` 是 fixture 里那份片段自己记的版本）：

```markdown
> [!info] 本块由 L3 渲染（整理版本 L2@0.1，生成于 2026-03-12T23:10:00+08:00）；闸门：归一引文 2 条、删引文 2 条、越界 0 条、删 ASR 条目 0 条；重跑会覆盖，批注请写在块外。另有 1 段杂项未渲染（合计 00:03:30）。
```

「河口夜市搬迁」那一节的**原话锚点**——五条里 1 条逐字命中、2 条归一、2 条删：

```markdown
**原话锚点**

- [00:19:00] 阿桥：「河口晚报今天早上发了报道，说夜市要整体搬到滨江路」
- [00:20:13] 老周：「我上个月去数过，摊位不到一百个」
- [00:22:39] 老周：「六月底应该是赶在暑假前，暑假是夜市生意最好的时候」
```

第二条模型多抄了一个「摊」（「……不到一百个摊」），第三条丢了限定词「应该」
（「六月底是赶在暑假前」）——#53 的两档会把这两条整条删掉，现在它们以逐字稿原句
的样子留在笔记上，**丢掉的「应该」跟着原句回来了**（红线 2）。删掉的那两条是
「便宜两百一年两千四，人流少根本补不回来」（逐字稿是「便宜两百块，一年两千四，但
人流少的话根本补不回来」，改写超出预算）与「夜市搬走以后老街的房租肯定要跌」
（逐字稿里根本没有这句）。

写回的 `frag-market-01.json` 里，归一过的那条 `text` 换成了原句、`ctx` 照旧是所在段
全文：

```json
{
 "ts": "00:20:13",
 "who": "老周",
 "text": "我上个月去数过，摊位不到一百个",
 "ctx": "一百二十户这个数我有点怀疑，我上个月去数过，摊位不到一百个。"
}
```

同一条命令**再跑一遍**（幂等）：换进去的就是逐字稿原句，第二趟它已是逐字命中，

```
[07:46:26]     L3：5 个话题过了闸门，写回 0 份片段（越界的段只记不删，红线 2）
[07:46:26] L3 闸门：归一引文 0 条、删引文 0 条、越界 0 条、删 ASR 条目 0 条，越界段 0 处 → _digest/EP91/gates.json
```

---

## 3. 沙箱内已验证清单（验收标准 → 用例）

| 验收 | 用例 |
|---|---|
| 1 端到端（`snap` 片段）：`quotes_snapped` 2 / `quotes_dropped` 2 / 越界 0 / ASR 0；写回 3 条引文、`text` 依次是那三句、每条带 `ctx`；`snapped` 两项且 `from` 是模型写的、`to` 等于写回的 `text`；笔记锚点 3 行、含「应该」那句、不含「摊位不到一百个摊」「便宜两百」「房租」；块首行「归一引文 2 条、删引文 2 条、越界 0 条、删 ASR 条目 0 条；」；`paras` / `claims` / `channels` 逐项与输入相等 | `test_s3_gates.py::test_quotes_that_miss_by_a_character_come_back_as_the_transcript_said_it` |
| 2 bad fixture 改档：`quotes_snapped` 1 / `quotes_dropped` 0 / 越界 1 / ASR 1；锚点 4 行，含「摊位不到一百个」、不含「摊位不到一百个摊」、不含 `[00:10:00]` 那行 | `test_s3_gates.py::test_a_violating_fragment_loses_two_entries_and_gets_one_snapped` |
| 3 逐字不变量：每条留下的引文 `norm(text)` 是 `norm(ctx)` 的子串且 `ctx` 是逐字稿的一整段；`text` 与 `ctx` 之外每个字符串值都能在输入里原样找到（递归） | `test_s3_gates.py::test_the_gates_can_only_write_the_transcripts_own_words`（bad，剩 4 条）、`::test_the_gates_can_only_write_the_transcripts_own_words_after_snapping`（snap，剩 3 条） |
| 4 单测（合成 SEGS）：多一字 / 少一字 / 换一字 → 归一且 `to` 是段原文里的连续子串、`from` 是模型原文 | `test_sm_l3.py::test_one_character_too_many_too_few_or_wrong_snaps_to_the_transcript` |
| 4 阈值：20 字差 2 处 → 归一；15 字差 2 处 → 删；5 字差 1 处 → 删 | `::test_the_budget_is_one_edit_per_ten_characters_and_six_characters_minimum` |
| 4 末尾多一字、逐字稿该处紧跟标点：`to` 不含那个标点 | `::test_a_quote_one_character_past_a_full_stop_does_not_swallow_it`（另有 `::test_the_alignment_takes_the_shortest_span_with_the_fewest_edits` 直接钉住 `align_span` 的 tie-break） |
| 4 `ts` 读不出来 → 不归一、删 | `::test_a_quote_whose_timestamp_is_unreadable_is_not_snapped` |
| 4 同一句在 ±2 分钟内外各有一段 → 归一到窗内那段；窗里没有候选段 → 删 | `::test_only_segments_within_two_minutes_of_the_timestamp_are_candidates` |
| 4 段原文含空格或英文：`to` 取自原文、保留空格，且 `norm(to)` 是 `norm(段)` 的子串 | `::test_the_replacement_keeps_the_spaces_and_latin_letters_of_the_transcript`（段是「这个名字变成 middle name 就是外国人的叫法。」） |
| 4 有逐字命中时不归一（`quotes_snapped` 为 0） | `::test_a_verbatim_quote_is_never_snapped` |
| 4 归一后 `ts` 越界 → 只计 `quotes_out_of_range`、不计 `quotes_snapped`、不写回 | `::test_a_snapped_quote_that_is_out_of_range_is_only_counted_as_out_of_range` |
| 5 `gates.json` 每话题有 `quotes_snapped` 与 `snapped`，0 条时 `snapped == []`；块首行与日志行的四个数和 `gates.json` 合计一致 | `test_s3_gates.py::test_a_clean_episode_passes_every_gate`（整份 entry 逐键比）、`test_sm_render_ep.py::test_the_block_head_reports_what_the_gates_dropped_and_snapped`、上面验收 1 / 2 两条（块首行与 `gates.json` 同一趟比） |
| 6 幂等：归一过一轮再跑，`quotes_snapped == 0`、`snapped == []`、片段逐字节不变、块首行「归一引文 0 条」 | `test_s3_gates.py::test_a_snapped_episode_run_twice_snaps_nothing_the_second_time`（整条 `ep` 链路）、`test_sm_l3.py::test_running_twice_changes_nothing`（连 mtime 都不动） |

票面之外顺手钉住的：`norm_map` 与 `norm` 归的是同一个文本、下标表指得回原文
（`test_sm_l3.py::test_norm_map_says_where_every_character_came_from`）；改写超出预算
的照删且入参没被就地改掉（`::test_a_quote_that_is_not_verbatim_is_dropped_and_counted`）。

---

## 4. 我认为风险最高的两个点

**① 归一是「换成逐字稿的原话」，不是「改对模型的意思」——换错句时笔记上看不出来。**
代码只认字面距离：模型把「不会通过」写成「会通过」（或反过来）这种一字之差，如果
逐字稿里正好有对应的一句，归一会把它换成逐字稿那句、**意思跟着翻过来**，而笔记上
只是一条正常的锚点。防线有三道：阈值卡在 `max(1, 字数 // 10)`、引文 ≥ 6 字、候选段
限 `ts` ±2 分钟；再就是每条归一都把 `from` / `to` 写进 `gates.json`（红线 9）。
**第 5 节的 5.3 就是让人把 EP02 上每条 `from` / `to` 过一遍眼**——真出现「`to` 与
`from` 讲的不是一回事」，记进 #57 把阈值往严调（两个常量在 `sm/l3.py` 顶部，不在
prompt 里）。EP02 预计只有 1 条走到这一档，人工过一遍不费事。

**② 归一同样是覆盖写回，而且 #53 已经删掉的引文本票救不回来。** 片段里没有的东西
闸门变不出来：vault 上如果已经跑过 #53，`_digest\EP02\frag-*.json` 里那条「基本可以
认为」早被删了，这一趟只会报「归一 0 条」。所以 5.0 那一步（确认没跑过 #53，或先把
`_lab\` 的备份拷回去）不能省，否则看到的是一个假的 0。`--replay`（#55）还没有。

次一级的两点，评审顺带看一眼就好：候选段限在 ±2 分钟，意味着模型把 `ts` 写偏两分钟
开外的引文既不归一也没法定位，只能照删（跟 #53 的口径一致）；跨段抄的引文本票不管
（对齐只在单段内做，EP02 上 0 例），它仍旧是 `quotes_dropped`。

---

## 5. 合并后跑真实样例（人，在笔记本的交互式会话里）

vault 里 EP02 的 L1 / L2 产物都在，这一票只跑闸门与渲染，**一次模型调用都不发、
不烧额度**，可以放心重跑。`--replay` 还没有（#55），下面用不到它。

### 5.0 先确认起点（一步，别省）

```powershell
Test-Path "D:\obsidian-task\任务栏\story-machine\_digest\EP02\gates.json"
```

- **`False`**（`_digest\EP02\` 还是 #53 合并前的样子）→ 直接跑 5.1。
- **`True`**（已经跑过 #53，那条少一个「上」的引文已经被删掉了）→ 先把备份拷回去，
  不然这一趟只会报「归一 0 条」，看到的是个假的 0：

```powershell
Remove-Item -Recurse "D:\obsidian-task\任务栏\story-machine\_digest\EP02"
Copy-Item -Recurse "D:\obsidian-task\任务栏\story-machine\_lab\EP02-digest-before-gates" `
                   "D:\obsidian-task\任务栏\story-machine\_digest\EP02"
```

（`_lab\EP02-digest-before-gates\` 是 #53 的 QA 文档 5.0 那步留下的备份。备份也没有
的话，这一票在 EP02 上就只能看个「归一 0 条、删 0 条」，没别的办法——只能等 #55 的
`--replay` 从 `_pairs\` 重放。）

### 5.1 跑

```powershell
python scripts\digest.py ep EP02 --vault "D:\obsidian-task\任务栏\story-machine"
```

（等价于 `worker.ps1 -Extract EP02`。**不要**加 `-Redo` / `--force`——那会把 L1 L2
一起重烧。model / effort 这一票用不上：L1 L2 都会跳过，日志里会各报一句「跳过
不调用」。）

期望日志（`a` = 归一、`b` = 删、后两个数是越界与 ASR）：

```
    L3：N 个话题过了闸门，写回 M 份片段（越界的段只记不删，红线 2）
L3 闸门：归一引文 a 条、删引文 b 条、越界 c 条、删 ASR 条目 d 条，越界段 e 处 → _digest\EP02\gates.json
整理稿已写进 10-Episodes\EP02 ….md（整理: done，整理版本 L2-topic@0.2）
```

**2026-09-18 那趟的基线是 171 条引文删 1 条**，所以这一趟期望是
**`归一引文 1 条、删引文 0 条、越界 0 条、删 ASR 条目 0 条`**；`N` 等于
`topics.json` 的话题条数（那趟是 12 章 58 个话题）。

### 5.2 看什么

**`_digest\EP02\gates.json`**：每个话题一行，键是 `quotes_snapped` /
`quotes_dropped` / `quotes_out_of_range` / `paras_out_of_range` / `asr_dropped` /
`snapped` / `schema`。本票起，#50 判据里的**闸门 1 通过率 =（逐字命中 + 归一）÷
引文总数 = 1 − `quotes_dropped` ÷ 引文总数**。

下面这段**在仓库根目录**存成 `check-gates.py`（UTF-8，跑完删掉、别提交），
`python check-gates.py` 跑（PowerShell 没有 heredoc，管道进 `python -` 还会撞编码，
所以走文件）：

```python
# -*- coding: utf-8 -*-
import json, pathlib, sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

d = pathlib.Path(r"D:\obsidian-task\任务栏\story-machine\_digest\EP02")
g = json.loads((d / "gates.json").read_bytes().decode("utf-8"))["topics"]
kept = sum(len(json.loads(p.read_bytes().decode("utf-8")).get("quotes") or [])
           for p in d.glob("frag-*.json"))
snapped = sum(t["quotes_snapped"] for t in g.values())
dropped = sum(t["quotes_dropped"] for t in g.values())
oor = sum(t["quotes_out_of_range"] for t in g.values())
total = kept + dropped + oor
print(f"话题 {len(g)} 个；引文 {total} 条：留 {kept}（其中归一 {snapped}）、"
      f"闸门 1 删 {dropped}、闸门 2 删 {oor}")
print(f"闸门 1 通过率 {1 - dropped / total:.1%}（逐字命中 {kept - snapped} + 归一 {snapped}）"
      if total else "没有引文")
print("形状不过的话题：", [k for k, v in g.items() if v["schema"] != "ok"])
```

**期望的形状**：58 个话题上下、引文总数 171 条量级、`归一 1`、`闸门 1 删 0`、
通过率 100%、`schema` 全是 `"ok"`。EP 笔记块首行的四个数应当与 `gates.json` 各自
求和相等。

**具体到那一条**：`gates.json` 里 `dsa-history-and-mamdani-03` 应当有一项
`snapped`，`to` 比 `from` 多一个「上」（「基本可以认为」→「基本上可以认为」），
EP02 笔记 DSA 那一节的 `[01:26:42]` 锚点回来了。

**什么现象说明坏了**

| 看到 | 说明 | 去哪 |
|---|---|---|
| `归一引文 0 条、删引文 0 条` 且 `_digest` 是 #53 跑过的那份 | 那条引文早被 #53 删掉了，这一趟无事可做（假的 0） | 回 5.0 把 `_lab\` 备份拷回去重跑 |
| 归一条数远多于 1（十几条起） | 阈值太松，或 L2 换了 prompt 之后引文质量掉了 | 逐条看 5.3 的 `from` / `to`，记进 #57 调 `SNAP_MIN_LEN` / `SNAP_EDITS_PER_10` |
| 某条 `to` 与 `from` 讲的不是一回事 | **换错句**（第 4 节 ①） | 把这条贴进 #57，阈值往严调；那条锚点先手工从笔记里删掉 |
| 还有 `quotes_dropped` > 0 | 剩下的是真对不上的（改写太多 / 跨段抄 / 逐字稿里没有） | 按 #53 QA 文档 5.3 那段脚本区分「跨段」还是「瞎编」，再去 #57 |
| 块首行只有三个数、没有「归一引文」 | 渲染没走新代码（装错分支） | 检查分支 |
| 退出码 2、日志「L3 闸门读不下去」 | `_digest\EP02\` 里的产物缺了或坏了 | 按提示看一眼再删，或删 `topics.json` 重跑 L2 |

**第二次跑计数会归零**（归一过的已是逐字命中、写回 0 份片段），这是对的、不是坏了；
这一趟到底换了什么以第一次的 `gates.json` 为准（它每趟重写，`generated_at` 就是这趟
的时间）。

### 5.3 逐条看归一（**每次跑完都做**，这一票的判据就在这儿）

同样存成仓库根目录下的 `check-snapped.py`（UTF-8）再 `python check-snapped.py`：

```python
# -*- coding: utf-8 -*-
import json, pathlib, sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

d = pathlib.Path(r"D:\obsidian-task\任务栏\story-machine\_digest\EP02")
g = json.loads((d / "gates.json").read_bytes().decode("utf-8"))["topics"]
for tid, t in g.items():
    for s in t["snapped"]:
        print(f"{tid} | {s['ts']}\n  模型写的：{s['from']}\n  换成的　：{s['to']}\n")
```

一条一条读「模型写的」与「换成的」：**只差一两个字、意思一样** → 对了，这正是本票
要救的那一档；**讲的不是一回事**（人名、数字、否定词变了，或者换成了邻近的另一句）
→ 把这一条贴进 #57，并把那条锚点从笔记里手工删掉（块内的改动重跑会被覆盖，所以
顺手把 issue 开了）。

### 5.4 坏了怎么回退

1. **只回退这一集的产物**：把 `_lab\EP02-digest-before-gates\` 拷回 `_digest\EP02\`
   （5.0 那两条命令），盘上就回到了任何闸门跑之前那一份。笔记那一块要一起回退的话，
   `git checkout` 到合并前的代码再跑一次 `ep EP02`（照样不烧额度）。
2. **整张 PR**：`git revert`。片段里被换过的 `text` 不会自己变回去——它现在是逐字稿
   原句，revert 后的闸门 1 会把它当逐字命中放行（不删、不报），所以盘上留着也无害；
   要彻底回到模型写的那一版，从 `_lab\` 备份拷回片段。
3. **连 L2 一起重来**：`del _digest\EP02\topics.json` 后跑 `ep EP02`（12 章重跑、
   L1 跳过、烧一趟 L2 额度）。

派生文件里删得起的：`_digest\EP02\gates.json`（下一趟重写）、`_digest\EP02\frag-*.json`
与 `topics.json`（删了就重跑 L2）。**不能删** `_pairs\`（永久正本）和逐字稿。
