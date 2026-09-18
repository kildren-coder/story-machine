# QA — issue #53 闸门 1 / 2 / 5：不逐字的引文与越界时间戳从整理稿里消失

分支 `agent/issue-53`。沙箱内 `bash scripts/test.sh` 全绿（189 个 pytest 用例，
比开工时的 162 个多 27 个），没有调用过 `claude -p`，没有碰过 vault，所有用例跑在
`tests/fixtures/vault/` 的临时副本上。

这一票让 L3 从「只渲染」变成「先过闸门再渲染」：不逐字的原话锚点、落在话题范围外
的锚点、逐字稿里根本没出现过的 ASR 条目，在写进笔记之前就从片段里删掉；删了多少
写在块首行和 `_digest/EP{n}/gates.json` 里。越界的**段落只记不删**（红线 2）。

---

## 1. 改动摘要

| 文件 | 做了什么 |
|---|---|
| `scripts/sm/l3.py`（新，约 230 行） | `run_gates(paths, ep) -> GateReport`：读 `chapters.json` / `topics.json` / 全部 `frag-*.json` / 逐字稿，每个片段跑闸门 1（引文逐字命中，命中补 `ctx`）、闸门 2（时间戳范围）、闸门 5 的 ASR 条款，写回过滤后的片段并写 `gates.json`。纯函数 `gate_frag` / `hit_segment` / `in_topic` / `in_chapter` / `check_shape` 各自可单测 |
| `scripts/sm/l2.py` | `_write_json` / `_check_paras` / `_check_items` 去掉下划线（§5.4 的形状检查与 `_digest/` 的字节形状两层共用一份）；新增 `json_bytes`，L3 拿它比「写回前后有没有真变」 |
| `scripts/sm/render_ep.py` | `render_digest` 多一个必填参数 `gates`：块首行加「闸门：删引文 n 条、越界 m 条、删 ASR 条目 k 条」，全 0 也写 |
| `scripts/sm/text.py` | `norm()` 收 `str()`：逐字稿正本里混进一个非字符串不该把整集掀翻在一句 TypeError 上（`parse_hms` 同样的路子）|
| `scripts/digest.py` | `ep` 子命令在 L2 之后、渲染之前跑闸门，渲染读过滤后的片段；闸门读不动产物（缺文件 / JSON 坏 / 片段指着章节表里没有的章）时报一句、退 2、不碰笔记 |
| `SPEC.md` | §4 L3 第 1、2、5 条写明比的是哪一层单位、`ctx` 怎么取、越界的段只记不删、`gates.json` 的实际字段、读不动时抛异常；§5.7 块首行多了三个计数 |
| `docs/agents/domain.md` | 目录树补上 `sm/l3.py` |
| `tests/` | 新增 `test_sm_l3.py`（21）、`test_s3_gates.py`（5）；`test_sm_render_ep.py` 加 1 并跟着改签名；`test_s2_topics.py` 三条跟着改（见下） |

`test_s2_topics.py` 那三条为什么要改：#52 的两条端到端用例比的是「片段逐个等于
fixture」，现在片段多了闸门补的 `ctx`，改成比「L2 写出来那一份」（去掉 `ctx`）；
闸门违规那一条原来断言越界的引文**留在**片段里（当时 L3 还没有），现在断言 L2
照写不误、L3 删掉、`_pairs/` 的原始响应里照旧留着——**代码任何一处都没改模型的字**
这件事没变，变的是它在哪一层被删。

实现完成后又派了一个 sonnet 子代理做对抗式复查，逮到三个真缺陷，都已修、各配了
用例，列在最前面：

1. **中途炸掉会在盘上留下「删了一半」的片段。** 原来是过一个话题写回一个：前几份
   写回去了，后面一份抛出去（孤儿片段），`gates.json` 还没写——那些删除就再也没有
   记录了，下一趟看到的是已经删过的片段、计数却是 0（红线 9；#50 的「闸门 1 通过
   率」也就此失真）。现在全集过完才落盘，要么整趟都写，要么盘上一个字节都没动
   （用例 `test_a_run_that_blows_up_halfway_leaves_nothing_on_disk`）。
2. **`quotes[].text` / `asr[].heard` 不是字符串时炸 `TypeError`**（手改坏一份片段
   就够了），而 `digest.py` 只收 `OSError` 与 `ValueError`，人看到的是一整页
   traceback。现在照删并计数——不是字符串的引文本来也不可能是逐字稿里的一句话，
   `schema` 那一栏同时把它报出来（`test_a_quote_whose_text_is_not_a_string_is_dropped_not_crashed`）。
3. **章节表的时刻读不出来时退成 `0`**，会算出一段错的切片，再照着它删掉本该留下的
   ASR 条目，而盘上完全看不出问题出在 `chapters.json`。片段那边有 `schema` 一栏可
   记，章节表这边没有，所以改成抛（`test_a_chapter_with_an_unreadable_time_raises`）。

三处判断题面没写死或与别处有张力，我按红线选了并记在这里（评审重点看这几处）：

1. **`ts` 落在话题 `end` 之后正好 2 分钟算在范围内**（两端都算）。删是不可逆的，
   宽容一格错的代价小；`start - 120` 那头同理。
2. **闸门 1 判到「段」，闸门 5 判到「章节切片的行」**，两把尺子不一样是故意的：
   `ctx` 要的是「他说这一句的那一段全文」，跨段拼起来的句子逐字稿里并没有这么
   一句；而 ASR 条款问的是「模型的输入里出现过这个写法没有」，那就该拿模型看到的
   那份文本（§5.2 的切片，含前后各 2 分钟）去比。**风险在第 4 节。**
3. **`gates.json` 没带 §9 的 `provenance` 块**，只有票面写的 `ep` + `generated_at`。
   红线 9 说「每个派生文件带 provenance」，但 L3 是纯代码层，`engine` / `effort` /
   `prompt_version` 三个键没有值可填，而票面把这个文件的形状写死了（#54 还要往里
   加 `passed` / `coverage_missing` / hedge 字段）。我照票面实现。要补的话是
   `sm/l3.py` 里 `GateReport.doc()` 一处，那三个键填什么请一并定。

---

## 2. 「可见变化」演示（fixture 副本，合成内容）

照票面那条跑：先把 fixture 的 `_digest/EP91/` 铺进副本，再用
`tests/fixtures/l3/frag-market-01.bad.json` 顶替 `frag-market-01.json`。L1 与 L2
的产物就此齐全，这一趟一次调用都不会发，只跑闸门与渲染。

```
$ rm -rf /tmp/demo53 && mkdir -p /tmp/demo53 && cp -r tests/fixtures/vault /tmp/demo53/vault
$ mkdir -p /tmp/demo53/vault/_digest && cp -r tests/fixtures/digest/EP91 /tmp/demo53/vault/_digest/EP91
$ cp tests/fixtures/l3/frag-market-01.bad.json /tmp/demo53/vault/_digest/EP91/frag-market-01.json
$ python scripts/digest.py ep EP91 --vault /tmp/demo53/vault --runner fake:tests/fixtures/raw
[19:21:06] EP91：76 段 / 00:42:40，说话人 阿桥（主播）、老周（嘉宾），prompt L1-skeleton@0.9@ecefac87
[19:21:06] L1 产物已在（_digest/EP91/chapters.json），跳过调用——要重跑加 --force
[19:21:06] L2 逐章节整理：2 章，一章一次调用（sonnet / effort medium，并发 3，超时 1800s/章，prompt L2-topic@0.2@963e68d7）
[19:21:06]     L2：2 章已完成，跳过不调用——要重跑加 --force
[19:21:06]     L2：2 章的 prompt_version 落后于当前 prompt（L2@0.1、未记 → L2-topic@0.2），要重跑加 --force
[19:21:06] L2 通过：5 个话题（talk 3、aside 1、filler 1）；正文合计 1438 字 / 逐字稿 1857 字，压缩比 0.77 → _digest/EP91/topics.json
[19:21:06]     L3：5 个话题过了闸门，写回 3 份片段（越界的段只记不删，红线 2）
[19:21:06] L3 闸门：删引文 1 条、越界 1 条、删 ASR 条目 1 条，越界段 0 处 → _digest/EP91/gates.json
[19:21:06] 整理稿已写进 10-Episodes/EP91 河口夜话 2026年3月12日 北港大桥与夜市.md（整理: done，整理版本 L2@0.1）
退出码 0
```

`_digest/EP91/gates.json`（贴出出事的 `market-01` 与一条全 0 的对照）：

```json
{
 "ep": "EP91",
 "generated_at": "2026-09-18T19:21:06+00:00",
 "topics": {
  "market-01": {
   "quotes_dropped": 1,
   "quotes_out_of_range": 1,
   "paras_out_of_range": [],
   "asr_dropped": 1,
   "schema": "ok"
  },
  "market-02": {
   "quotes_dropped": 0,
   "quotes_out_of_range": 0,
   "paras_out_of_range": [],
   "asr_dropped": 0,
   "schema": "ok"
  }
 }
}
```

笔记里那一块的**块首行**（`L2@0.1` 是 fixture 里那份片段自己记的版本）：

```markdown
> [!info] 本块由 L3 渲染（整理版本 L2@0.1，生成于 2026-03-12T23:10:00+08:00）；闸门：删引文 1 条、越界 1 条、删 ASR 条目 1 条；重跑会覆盖，批注请写在块外。另有 1 段杂项未渲染（合计 00:03:30）。
```

「河口夜市搬迁」那一节的**原话锚点从五条变成三条**——「摊位不到一百个摊」（逐字稿
里是「摊位不到一百个」，多了一个字）和 `ts` 写成 `00:10:00` 的那条都不见了：

```markdown
**原话锚点**

- [00:19:00] 阿桥：「河口晚报今天早上发了报道，说夜市要整体搬到滨江路」
- [00:27:30] 阿桥：「商户其实是在停业整改和搬迁之间选，不是搬和不搬之间选」
- [00:28:06] 老周：「老码头市场也是因为消防搬的，搬完之后头一年生意掉了一半」
```

写回的 `frag-market-01.json` 里，留下来的锚点各多了一个 `ctx`（逐字来自逐字稿的
那一段全文，人和后面的核查层要核对时不用再去翻逐字稿）：

```json
{
 "ts": "00:19:00",
 "who": "阿桥",
 "text": "河口晚报今天早上发了报道，说夜市要整体搬到滨江路",
 "ctx": "河口夜市搬迁这个事，河口晚报今天早上发了报道，说夜市要整体搬到滨江路。"
}
```

`asr` 从 `[{"heard": "冰江路", ...}]` 变成 `[]`（逐字稿里没有「冰江路」这个写法），
`paras` 五段一段没少、一个字没改。

**好样例的对照**（不顶替坏片段，直接 `ep EP91`）：五个话题的计数全 0，每条锚点都
补上了 `ctx`，块首行是

```markdown
> [!info] 本块由 L3 渲染（整理版本 L2-topic@0.2，生成于 2026-03-12T23:10:00+08:00）；闸门：删引文 0 条、越界 0 条、删 ASR 条目 0 条；重跑会覆盖，批注请写在块外。另有 1 段杂项未渲染（合计 00:03:30）。
```

---

## 3. 沙箱内已验证清单（验收标准 → 用例）

| 验收 | 用例 |
|---|---|
| 1 端到端好 fixture：计数全 0、每条引文有 `ctx` 且等于逐字稿对应段、除 `ctx` 外与输入等价、块首行「删引文 0 条」 | `test_s3_gates.py::test_a_clean_episode_passes_every_gate`（13 条锚点逐条比 `ctx`） |
| 2 坏片段：删引文 1 / 越界 1 / 删 ASR 1，被删的两条不在写回文件里也不在笔记的锚点里，`paras` 逐段与输入相等，块首行与 `gates.json` 一致 | `test_s3_gates.py::test_a_violating_fragment_loses_exactly_three_entries` |
| 3 闸门 1：多余空格 / 全角空格 / 时间戳仍命中；标点不同不命中；跨两段不命中 | `test_sm_l3.py::test_extra_whitespace_and_timestamps_still_hit`、`::test_different_punctuation_misses`、`::test_a_quote_stitched_from_two_segments_misses`（另有 `::test_ctx_is_the_whole_segment_nearest_to_the_timestamp` 钉住同一句话说两遍时 `ctx` 取哪一段） |
| 4 闸门 2：`end` 之后 2 分钟内算在范围、2 分钟外越界；para 落在章节 `start` 之前算越界（哪怕离话题 `start` 不到 2 分钟）；越界 para 不删只记；`start == end` 的话题按 ±2 分钟判 | `test_sm_l3.py::test_a_quote_two_minutes_past_the_topic_end_is_still_in_range`、`::test_a_paragraph_inside_the_chapter_padding_is_out_of_range_but_kept`、`::test_a_paragraph_past_the_topic_margin_is_also_flagged`、`::test_a_zero_length_topic_still_judges_by_the_two_minute_margin` |
| 5 「只删不改」总断言：写回文件里每个字符串值都能在输入里原样找到（递归遍历），`ctx` 除外 | `test_s3_gates.py::test_the_gates_only_delete_and_only_add_ctx`（另有 `test_sm_l3.py::test_a_quote_that_is_not_verbatim_is_dropped_and_counted` 钉住入参没被就地改掉） |
| 6 幂等：同一输入跑两次，第二次计数全 0 且片段不变 | `test_sm_l3.py::test_running_twice_changes_nothing`（连 mtime 都不动）、`test_s3_gates.py::test_a_second_run_drops_nothing_and_leaves_the_fragment_alone`（整条 `ep` 链路） |
| 7 `gates.json` 带 `generated_at`；闸门遇到坏 JSON 抛异常、不静默 | `test_sm_l3.py::test_gates_json_and_write_back`、`::test_a_broken_fragment_raises_instead_of_passing_quietly`、`::test_a_missing_fragment_raises`、`::test_an_orphan_fragment_raises` |

票面之外顺手钉住的：闸门 5 的切片含前后 2 分钟余量
（`test_sm_l3.py::test_the_asr_slice_includes_the_two_minute_context`）、形状不合
§5.4 只记在 `schema` 那一栏不抛不删（`::test_a_fragment_that_breaks_the_shape_is_recorded_not_raised`）、
块首行非 0 计数的渲染（`test_sm_render_ep.py::test_the_block_head_reports_what_the_gates_dropped`）、
读不出来的片段在 L2 那一步就被重跑补上了
（`test_s3_gates.py::test_a_broken_fragment_is_refilled_by_l2_before_the_gates_see_it`），
以及自审那三条各自的用例（见第 1 节）。

评审补的两条（`review:` commit）：`ts` 缺了或读不出时刻的引文按 `quotes_out_of_range`
删、而话题自己的 `start` / `end` 读不出来时闸门 2 整个不跑（这对反着的口径原先没有
用例钉住，`test_sm_l3.py::test_a_quote_whose_ts_cannot_be_read_is_dropped_as_out_of_range`）；
验收 5 那条总断言补一句「还剩 3 条锚点、段数没变」的前置断言——引文要是被全删光，
底下两个遍历都成空转，那条断言会变成永真。

---

## 4. 我认为风险最高的两个点

**① 闸门 1 判到「段」，而模型看到的是「行」。** §5.1 的一段是 ASR 切出来的一段，
§5.2 的一行是**同一个人 30 秒窗内的若干段连起来**的。fixture 里两者一一对应（每段
都超过 30 秒），EP02 上不是——一行常常是好几段。模型被要求「逐字照抄逐字稿里某一段
连续的文本」，但它眼前只有行；它照抄了一行里横跨两段的一句话，闸门会当成不逐字
**删掉**，而这句话在逐字稿里确实一字不差地存在。

题面写的是 `norm(seg.text)`、「不跨段」、`ctx` 是「该段全文」，SPEC §4 L3 第 1 条与
§5.4 也都是「段」，所以我按段实现，并把它写死在用例里（`test_a_quote_stitched_from_two_segments_misses`
特意挑同一行内的两段，拿行当尺子的实现会在这条上翻车）。**但这是 EP02 上「闸门 1
通过率」掉下来的头号嫌疑**，而且它跟「模型瞎编引文」的表现一模一样：都是
`quotes_dropped` 加一。第 5 节给了区分这两者的现成命令——**先跑它再决定要不要去
改 prompt（#57）**，不然会对着一个代码口径问题改 prompt。

**② 闸门的删除在 `#55 --replay` 到位之前是不可逆的。** 写回是覆盖；被删的条目只在
`_pairs/EP{n}/L2-<章>.raw.json` 里还留着原样（那是永久正本，闸门不碰）。所以第一次
在 EP02 上跑之前**先把 `_digest\EP02\` 整个拷一份到 `_lab\`**，不然要恢复只能重跑
L2、烧一趟额度。

---

## 5. 合并后跑真实样例（人，在笔记本的交互式会话里）

vault 里 EP02 的 L1 / L2 产物都在，这一票只跑闸门与渲染，**一次模型调用都不发、
不烧额度**，所以可以放心重跑。`--replay` 还没有（#55），下面不需要它。

### 5.0 先备份（一步，别省）

```powershell
Copy-Item -Recurse "D:\obsidian-task\任务栏\story-machine\_digest\EP02" `
                   "D:\obsidian-task\任务栏\story-machine\_lab\EP02-digest-before-gates"
```

闸门写回是覆盖，删掉的锚点只在 `_pairs\` 的原始响应里还有。

### 5.1 跑

```powershell
python scripts\digest.py ep EP02 --vault "D:\obsidian-task\任务栏\story-machine"
```

（等价于 `worker.ps1 -Extract EP02`。不要加 `-Redo` / `--force`——那会把 L1 L2 一起
重烧。model / effort 这一票用不上：L1 L2 都会跳过。）

日志里该出现这三行，L1 与 L2 都报「跳过不调用」：

```
    L3：N 个话题过了闸门，写回 M 份片段（越界的段只记不删，红线 2）
L3 闸门：删引文 a 条、越界 b 条、删 ASR 条目 c 条，越界段 d 处 → _digest\EP02\gates.json
整理稿已写进 10-Episodes\EP02 ….md（整理: done，整理版本 L2-topic@0.2）
```

`N` 应当等于 `topics.json` 里的话题条数（2026-09-18 那趟是 12 章 58 个话题）；
`M` 是这一趟真被改写的片段数，第一次跑通常等于「有引文的话题数」（补 `ctx`）。

### 5.2 看什么

**`_digest\EP02\gates.json`**：一个话题一行，键就是 `quotes_dropped` /
`quotes_out_of_range` / `paras_out_of_range` / `asr_dropped` / `schema`。#50 判据里的
**闸门 1 通过率** = 1 − `quotes_dropped` 之和 ÷ 引文总数；引文总数 = 写回后各片段
`quotes` 的条数之和 + `quotes_dropped` + `quotes_out_of_range`。

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
dropped = sum(t["quotes_dropped"] for t in g.values())
oor = sum(t["quotes_out_of_range"] for t in g.values())
total = kept + dropped + oor
print(f"话题 {len(g)} 个；引文 {total} 条：留 {kept}、闸门 1 删 {dropped}、闸门 2 删 {oor}")
print(f"闸门 1 通过率 {1 - dropped / total:.1%}" if total else "没有引文")
print("越界的段：", {k: v["paras_out_of_range"] for k, v in g.items() if v["paras_out_of_range"]})
print("形状不过的话题：", [k for k, v in g.items() if v["schema"] != "ok"])
```

**期望的形状**：58 个话题上下（跟 `topics.json` 的条数一致）、引文总数两三百条量级
（每个 `talk` 话题 ≤ 6 条）、`schema` 全是 `"ok"`。EP 笔记块首行的三个数应当与
`gates.json` 各自求和相等。

**什么现象说明坏了**

| 看到 | 说明 | 去哪 |
|---|---|---|
| 闸门 1 通过率 < 100% | 有引文不是逐字抄的，**或者**是跨段抄的（第 4 节 ①） | 先跑 5.3 的区分命令 |
| 通过率 < 90% 且 5.3 判定「逐字稿里没有」占多数 | prompt 的「逐字」规则没压住 | #57 改 `prompts\L2-topic.md`，升 `version:` |
| `quotes_out_of_range` 成片出现（不是零星一两条） | L2 把相邻章的内容写进本章了，或 `ts` 在瞎写 | 翻那几个话题的 `_pairs\EP02\L2-<章>.in.md` 看切片边界，再去 #57 |
| `paras_out_of_range` 很多 | 同上，而且是段落级的串章——**段一条都没删**，笔记内容还是全的，先别慌 | 同上 |
| `asr_dropped` 很多 | 模型在 `asr.heard` 里写的是它规范化之后的词，不是逐字稿里的原写法 | #57 |
| `schema` 不是 `"ok"` | 片段形状不合 §5.4 | 本票只记不判；失败态是 #54 |
| 退出码 2、日志「L3 闸门读不下去」 | `_digest\EP02\` 里的产物缺了或坏了 | 按提示看一眼再删，或删 `topics.json` 重跑 L2 |
| 块首行没有「闸门：」那一段 | 渲染没走新路径（装错分支） | 检查分支 |

**第二次跑计数会归零**——删过的东西不会再删第二遍，块首行跟着变成全 0。这是对的，
不是坏了；这一趟到底删了什么以第一次的 `gates.json` 为准（它每次都重写，`generated_at`
就是这一趟的时间）。

### 5.3 区分「模型瞎编」还是「跨段抄」（通过率不到 100% 时跑）

不调模型、只读 `_pairs\` 的原始响应和逐字稿正本。同样存成仓库根目录下的
`check-gate1.py`（UTF-8）再 `python check-gate1.py`——`sys.path` 那行按相对路径找
`scripts\sm\`，所以**必须在仓库根目录跑**：

```python
# -*- coding: utf-8 -*-
import json, pathlib, sys
sys.path.insert(0, "scripts")
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from sm.runner import parse_envelope
from sm.text import norm
from sm.transcript import build_lines, read_transcript

VAULT, EP = pathlib.Path(r"D:\obsidian-task\任务栏\story-machine"), "EP02"
segs, _ = read_transcript(VAULT / "_assets" / f"{EP}.transcript.json")
nsegs = [norm(s["text"]) for s in segs]
nlines = [norm(ln["text"]) for ln in build_lines(segs)]
raws = sorted((VAULT / "_pairs" / EP).glob("L2-*.raw.json"))
print(f"{len(raws)} 份响应")                      # 0 份说明路径写错了
for raw in raws:
    for t in parse_envelope(json.loads(raw.read_bytes().decode("utf-8")))["topics"]:
        for q in t.get("quotes") or []:
            n = norm(q["text"])
            if any(n in s for s in nsegs):
                continue
            why = "跨段（同一行内）" if any(n in ln for ln in nlines) else "逐字稿里没有"
            print(f"{raw.name} | {q['ts']} | {why} | {q['text'][:30]}")
```

（这段在沙箱里拿 fixture 试过：好响应一条都不打，换成 `raw-bad` 那份 `L2-market`
就打出「`逐字稿里没有` | 我上个月去数过，摊位不到一百个摊」。）

- 打出来的多数是**「逐字稿里没有」** → 真的是模型没照抄，去 #57 改 prompt。
- 打出来的多数是**「跨段（同一行内）」** → 是代码这一侧的口径问题：模型照着它看到的
  行抄了，闸门按段判。去 issue #53 留一句（把这条命令的输出贴上），把闸门 1 的匹配
  单位从段改成行、`ctx` 相应取整行——**别改 prompt**。
- 一条都没打出来却有 `quotes_dropped` → 片段与 `_pairs\` 对不上（`_digest` 是更早
  一轮留下的），拿 5.0 的备份对一下。

### 5.4 坏了怎么回退

1. **只回退这一集的产物**：把 5.0 备份的 `_digest\EP02\` 拷回去。盘上就回到了闸门
   跑之前那一份（没有 `ctx`、被删的条目都在）。**注意再跑一次 `ep EP02` 会照样删
   一遍**——要连笔记一起回到没有闸门的样子，得先 `git checkout` 到合并前的代码
   再跑（照样不烧额度）。
2. **没备份**：`_pairs\EP02\L2-*.raw.json` 是永久正本、闸门不碰，但本票之前没有
   `--replay`（#55），所以只能重跑 L2 ——
   `del _digest\EP02\topics.json` 后跑 `ep EP02`（12 章重跑、L1 跳过、烧一趟 L2 额度），
   或 `worker.ps1 -Extract EP02 -Redo`（连 L1 一起重跑，更贵）。
3. **整张 PR**：`git revert`。片段里已经补上的 `ctx` 会留在盘上——它不进笔记，
   L2 重跑时会连同片段一起被覆盖，不用手工清。

派生文件里删得起的：`_digest\EP02\gates.json`（下一趟重写）、`_digest\EP02\frag-*.json`
与 `topics.json`（删了就重跑 L2）。**不能删** `_pairs\`（永久正本）和逐字稿。
