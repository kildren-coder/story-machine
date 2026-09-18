# QA — issue #52 逐章节整理：L2 按章切片、章内切话题 → EP 笔记里出现整理稿

分支 `agent/issue-52`。沙箱内 `bash scripts/test.sh` 全绿（108 个 pytest 用例，
本票新增 43 个，含评审补的 1 个），没有调用过 `claude -p`，没有碰过 vault，所有
用例跑在 `tests/fixtures/vault/` 的临时副本上。

---

## 1. 改动摘要

| 文件 | 做了什么 |
|---|---|
| `prompts/L2-topic.md`（新） | L2 的 prompt，首行 `version: L2-topic@0.1`。输入长什么样（头 / 章节地图 / 切片三段 / 行号）、章内怎么切话题、`kind` 三档、九个键与五类内容、三条铁律、一个三话题（`filler` / `talk` / `aside`）的合成例子 |
| `scripts/sm/l2.py`（新，约 480 行） | `build_input`（头 + 章节地图 + 三段切片）、`schema_for`（`--json-schema` 的形状，行号上下界按本章）、`tidy`（机械归一）、`check_frag`（只拦代码修不了的）、`finish`（代码填 `id` / `chapter` / `start` / `end` / `who`）、`topics_doc`、`run_l2`（并发 3、跳过已完成的章、孤儿清理、单章失败隔离） |
| `scripts/sm/transcript.py` | 加 `slice_chapter(lines, start, end, pad=120)`：(上文, 本章, 下文)，行不切开、行号照旧是全集的 |
| `scripts/sm/render_ep.py` | `render_outline` → `render_digest`：**按话题**出节，段落里 `<who>` → `**名**`、`<hedge>` → `<u>…</u>`，四个小节（锚点 / 说法 / 信源表 / ASR 生音），`aside` 只出段落且标题加「 · 旁白」，`filler` 不渲染但段数与合计时长报在块首行 |
| `scripts/digest.py` | `ep` 子命令从「L1 → 渲染」变成「L1 → L2 → 渲染」；新增 `--l2-prompt` / `--l2-model`（sonnet）/ `--l2-effort`（medium）/ `--workers`（3）；每一章都完成才渲染，否则 `整理: failed`、不写块、退出码 1 |
| `scripts/worker.ps1` | 两句提示改成事实：跑的是「整集一次 + 每章一次」，完成提示改成「整理稿已写进 EP 笔记」（静态改，沙箱跑不了 PowerShell） |
| `SPEC.md` | §4 L2 补 prompt 文件名、空段省掉分隔行、schema 不卡 `ts`、五类内容不含 HTML 注释、完成判据加「边界对得上」、孤儿片段、失败就不渲染、`_digest/` 只主线程写且原子替换；§5.3 补话题表 provenance 的取法；§5.7 整理稿形状写全，删掉「L2 上线前是章节大纲」那一段 |
| `tests/` | 新增 `test_sm_l2.py`（20）、`test_s2_topics.py`（13）；`test_sm_render_ep.py` 重写（6）；`test_sm_transcript.py` 加 1；`test_s1_skeleton.py`、`test_worker_static.py`、`conftest.py` 跟着改（#51 留下的章节大纲断言） |

自审（实现完成后又派了一个 sonnet 子代理做对抗式复查）逮到三个真缺陷，都已修、
各配了用例，列在最前面：

1. **锚点 / 说法 / 信源 / 生音里的 HTML 注释会撑破标记块。** 这四类字段原样进
   `<!-- digest:auto -->` … `<!-- /digest -->`；内容里混进一个 `<!-- /digest -->`
   之后，**下一次**整块替换会在那里收尾，后半块被永久甩到块外（实测复现，违反
   「块外一个字节不动」）。`title` / `gist` 早就拦了这一条，`paras` 由「只认两种
   标记」挡着，漏的就是这四类。删注释等于改字（红线 5），所以只能打回，不能改。
2. **一章算完成只认 `id` 不够。** L1 重切之后章还叫 `market`、起止时刻却变了，
   这一章会被当成已完成跳过，笔记上留着按旧边界整理的话题，和章节表对不上——
   静默的不一致，比重跑一章贵得多。现在还要求「首尾正好铺满这一章」。
3. **`topics.json` 不是原子写。** 它每完成一章重写一次，同时又是「这一章跑没跑
   过」的判据；直接 `write_bytes` 中间那一小段文件是截断的。并发用例里 worker
   就在那一刻读到过半份 JSON（对照实验：300 次重写，直接写法下读到半份 1023 次，
   `os.replace` 之后 0 次）。跑到一半被杀再重跑会踩到同一个坑。

评审阶段又逮到第四个（已修、配了用例
`test_s2_topics.py::test_a_stale_topic_table_cannot_stand_in_for_the_chapter_that_just_failed`）：

4. **这一趟一章都没写成时，`run_l2` 会拿盘上那份旧话题表当完成的凭据。**
   「片段写了一半被杀」（frag 没了、话题表还记着它）之后重跑，那一章又没过：
   `done` 里没有它，可 `doc` 回退去读了上一趟的 `topics.json`，里面有它的旧话题。
   `digest.py` 照着算「每一章都完成」→ 渲染。实测复现：正题那一节在笔记上变成一个
   **空标题**（15 分钟的内容整段消失），frontmatter 照旧写 `整理: done`、退出码 0，
   `_failed/EP91/L2-bridge.failed.json` 躺在那儿但人唯一会读的那一面上看不出来
   （红线 9；`--force` 下两章全挂时整块四节全空）。现在这条回退路径只认这一趟真
   拿到片段的章，全跳过的那种情况一个都不会滤掉、`topics.json` 也不重写，笔记照旧
   逐字节不变。

契约层面值得单独看的四处决定：

1. **schema 不卡 `ts` 的样子**（SPEC 原文写的是「各 `ts` 形如 `HH:MM:SS`」）。
   `MM:SS` / `H:MM:SS` 代码补得回来（`tidy`），卡了只会让 CLI 在会话里白多一轮
   ——SPEC §4.1「闸门只拦代码修不了的」。已按 issue 改了 SPEC 那一条。
2. **`_digest/` 只由主线程写。** 线程里只拼输入、调 runner、跑检查；片段与
   `topics.json` 由主线程在 `as_completed` 里写。`topics.json` 是全集一份，让
   worker 去写，两支笔会互相盖掉对方刚写完的那一份。`_pairs/` 与 `_failed/` 是
   每单元一份、互不相干，留在 `call_layer` 里（线程内）。
3. **重跑一章前按片段里的 `chapter` 键清旧片段，不按文件名。**
   `frag-market-*.json` 会把 `market-2` 章的片段一起扫进来（`test_rerun_…` 里放了
   一个 `frag-market-2-01.json` 的诱饵钉住这条）。
4. **话题表的 provenance 取各片段里 `generated_at` 最晚的那一份**（`engine` /
   `effort` / `prompt_version` 跟着同一份走）。于是没有片段重生成时，`topics.json`
   重写出来逐字节不变，笔记也就不会每跑一次 `-Extract` 变一次。

---

## 2. 「可见变化」演示（fixture 副本，合成内容）

```
$ rm -rf /tmp/demo && mkdir -p /tmp/demo && cp -r tests/fixtures/vault /tmp/demo/vault
$ python scripts/digest.py ep EP91 --vault /tmp/demo/vault --runner fake:tests/fixtures/raw
[19:22:04] EP91：76 段 / 00:42:40，说话人 阿桥（主播）、老周（嘉宾），prompt L1-skeleton@0.9@ecefac87
[19:22:04] L1 骨架：整集一次调用（sonnet / effort low，超时 1800s）
[19:22:04]     L1-all 第 1 次调用（sonnet / effort low）…
[19:22:04]     L1：模型切了 3 章，其中 1 章不到 8 分钟，并进了相邻的章（标题与 gist 顺序接上，字没动）
[19:22:04] L1 通过：2 章 → _digest/EP91/chapters.json
[19:22:04] L2 逐章节整理：2 章，一章一次调用（sonnet / effort medium，并发 3，超时 1800s/章，prompt L2-topic@0.1@42451229）
[19:22:04]     L2-bridge 第 1 次调用（sonnet / effort medium）…
[19:22:04]     L2-market 第 1 次调用（sonnet / effort medium）…
[19:22:04]     L2 market：3 个话题（talk 2、aside 1、filler 0）
[19:22:04]     L2 bridge：2 个话题（talk 1、aside 0、filler 1）
[19:22:04] L2 通过：5 个话题（talk 3、aside 1、filler 1）→ _digest/EP91/topics.json
[19:22:04] 整理稿已写进 10-Episodes/EP91 河口夜话 2026年3月12日 北港大桥与夜市.md（整理: done，整理版本 L2-topic@0.1）
退出码 0
```

L2 只调了 2 次（`bridge`、`market` 两章），`_digest/EP91/` 下多出五份
`frag-*.json` 与 `topics.json`。笔记里 `<!-- /speakers -->` 之后那一块从十来行的
章节大纲变成了 112 行的整理稿，块首行与「北港大桥收费方案」那一节原样贴在下面
（fixture 是合成内容）：

```markdown
<!-- digest:auto -->
## 整理稿

> [!info] 本块由 L3 渲染（整理版本 L2-topic@0.1，生成于 2026-09-17T19:22:04+00:00）；重跑会覆盖，批注请写在块外。另有 1 段杂项未渲染（合计 00:03:30）。

### [00:03:30] 北港大桥收费方案：十五块还是十二块

[00:03:30] **阿桥**说北港大桥的收费方案来自市交通局上周的一份通报，从 2027 年 1 月开始按车型收费；通报里小客车一次十五块，货车按吨位另算，具体的表他没找到。**老周**补充那份通报他也看了，十五块是听证会的建议价，不是最后定的价；听证会三月三号开的，二十一个代表里十四个赞成按车型收费。

[00:05:43] **阿桥**承认自己说的十五块<u>应该</u>是不准确的，<u>听说</u>最后<u>可能</u>会压到十二块；这个十二块是他在一个叫桥梁观察的公众号上看到的，对方说是内部消息，他没法验证。**老周**说桥梁观察去年说大桥要延期通车、后来确实延期了，所以他觉得这个号的消息有一定可信度；**阿桥**说有一定可信度不等于对，让大家自己判断。

（中间还有三段，00:07:56 / 00:11:15 / 00:14:34，略）

**原话锚点**

- [00:03:30] 阿桥：「市交通局上周发了一个通报，说从2027年1月开始要按车型收费」
- [00:04:36] 老周：「十五块是听证会的建议价，不是最后定的价」
- [00:05:43] 阿桥：「听说最后可能会压到十二块」
- [00:10:09] 阿桥：「光靠过桥费还本金要二十年往上，大概率还要财政补一部分」
- [00:11:48] 老周：「2019年河口有过一个先例，滨江隧道也想收费，听证会开了两次，最后没收成」
- [00:15:08] 老周：「可能是你记混了，我记得是每月前十次」

**可核查的说法**

- [00:03:30] 阿桥：市交通局通报：北港大桥 2027 年 1 月起按车型收费
- [00:04:03] 阿桥：通报：小客车一次 15 元，货车按吨位另算
（共 10 条，略去 8 条）

**提到的信源**

| 信源 | 类型 | 谁 | 时间戳 | 原话 |
| --- | --- | --- | --- | --- |
| 市交通局通报 | 政府通报 | 阿桥 | [00:03:30] | 市交通局上周发了一个通报 |
| 桥梁观察 | 公众号 | 阿桥 | [00:06:16] | 一个叫桥梁观察的公众号 |
| 招标公告 | 政府公告 | 老周 | [00:09:35] | 我在当年的招标公告里看到过 |

**疑似 ASR 生音**

- 听成「北岗大桥」→ 应为「北港大桥」
```

期望的五项（验收里逐条断言过）：这一节 **5 段段落、6 条锚点、10 条说法、
3 行信源、1 条 ASR 生音**。

`aside` 那一节只有段落，标题后面挂「 · 旁白」：

```markdown
### [00:41:30] 结尾弹幕与下周预告 · 旁白

[00:41:30] 结尾回了几条与今天话题无关的弹幕：下周聊河口老照片，**老周**准备了一九八几年的照片。
<!-- /digest -->
```

`filler` 话题「开场与设备测试」一个字都没出现，只在块首行剩下一句「另有 1 段
杂项未渲染（合计 00:03:30）」；它的片段 `frag-bridge-01.json` 照样落了盘（五类
内容为空），人想追可以去 `_digest/` 里翻。块外的 `## 断言`、`## 待办` 两节与
frontmatter 其他键一个字节没动。

---

## 3. 沙箱内已验证清单（验收标准 → 测试）

| # | 验收标准 | 测试 |
|---|---|---|
| 1 | 端到端：runner 共调 3 次（L1 + 两章）；五份 `frag-*.json` 与 `topics.json` 去 provenance 后逐个等于 fixture；块内 4 个 `###`；大桥那节 5 段 / 6 锚点 / 10 说法 / 3 行信源 / 1 ASR；`整理版本: L2-topic@0.1`。EP92 同理（1 章、3 话题、2 个 `###`） | `test_s2_topics.py::test_ep91_end_to_end`、`::test_ep92_end_to_end` |
| 2 | 红线 5：块内每段还原 `**名**` / `<u>` 后与片段的 `paras` 逐字相等（13 段全查）；块内时间戳全是裸 `[HH:MM:SS]` | `::test_paragraphs_land_in_the_note_verbatim`、`test_sm_render_ep.py::test_markers_become_obsidian_writing_and_nothing_else_moves` |
| 3 | 切片输入：`L2-market.in.md` 头里 `行号: 35–76`、`范围: 00:19:00–00:42:40`；地图两行、第二行行首 `→`；上文恰好 32–34 行、本章首行 `35 [00:19:00] 阿桥: `、末行 76、没有「下文」分隔行；`L2-bridge.in.md` 没有「上文」、下文恰好 35–38 行 | `::test_the_chapter_slice_input_is_labelled`、`test_sm_l2.py::test_head_is_one_key_per_line_and_the_map_marks_this_chapter`、`::test_an_empty_side_drops_its_separator_line`、`test_sm_transcript.py::test_slice_chapter_pads_two_minutes_and_truncates_at_the_episode_edges` |
| 4 | 代码填的键：`bridge-01` 的 `start` 是 `00:00:00`、`market-03` 的 `end` 是 `00:42:40`、章内首尾相接、`who` 来自行表、产物里没有 `line`；schema 的 `line` 上下界 = 本章首末行号（35 / 76） | `::test_the_code_fills_ids_times_and_speakers`、`test_sm_l2.py::test_finish_fills_id_chapter_times_and_who`、`::test_the_first_topic_starts_at_the_chapter_start_and_the_last_ends_at_its_end`、`::test_two_topics_on_one_line_give_a_zero_length_topic`、`::test_the_schema_carries_this_chapters_line_range` |
| 5 | 坏响应隔离：`bridge` 换成散文 → `_failed/EP91/L2-bridge.failed.json` 存在、`market` 三个片段照样写出、`topics.json` 里只有这三个话题、笔记无块、`整理: failed`、退出码 1；换回好响应重跑只调 1 次（`L2` / `bridge`），块出现 | `::test_one_bad_chapter_is_isolated_and_the_rest_still_land`、`::test_a_stale_topic_table_cannot_stand_in_for_the_chapter_that_just_failed`（评审补：上一趟的话题表不许替这一趟失败的章顶包）（另有 `test_sm_l2.py::test_a_runner_that_throws_takes_down_one_chapter_not_the_episode`：runner 抛异常时也落 `_failed/`） |
| 6 | `market` 换成闸门违规的响应（schema 合法）：检查通过、片段写出，越界的 `ts` 原样留着 | `::test_a_gate_violating_chapter_still_passes_l2` |
| 7 | **拦**：`<b>` 标记、`talk` 的空 `paras`、段不以 `[HH:MM:SS]` 开头、`line` 越界、空 `title`、缺 `channels` 键、`ts` 写成「胡写」、五类内容里的 HTML 注释（自审补）。**不拦、归一**：`1:05` → `00:01:05`、7 条 `quotes` 留前 6、`heard == means` 删掉、`line` 写成 `"36"`、乱序按 `line` 排、`aside` 多写的 `quotes` 留在片段里 | `test_sm_l2.py::test_a_third_kind_of_tag_in_paras_is_rejected`、`::test_empty_paras_on_a_talk_or_aside_is_rejected`、`::test_a_paragraph_without_a_timestamp_is_rejected`、`::test_a_line_outside_this_chapter_is_rejected`、`::test_empty_title_missing_key_and_unreadable_ts_are_rejected`、`::test_tidy_normalises_what_the_code_can_fix`、`::test_tidy_flattens_newlines_in_title_and_gist`、`::test_an_aside_that_wrote_quotes_keeps_them_in_the_fragment`、`::test_an_html_comment_anywhere_in_the_rendered_text_is_rejected` |
| 8 | 并发：拖慢的假 runner 断言同时在跑 ≤ 3（且 > 1）；5 章合成输入全部完成；每一次 `_digest/` 写盘都发生在主线程；worker 中途读到的 `topics.json` 每一份都是合法 JSON | `test_sm_l2.py::test_three_chapters_at_a_time_and_every_write_lands_on_the_main_thread`、`::test_the_topic_table_is_replaced_in_one_step`（原子替换） |
| 9 | 幂等与增量：跑两次笔记逐字节不变、第二次 0 次调用；删掉 `frag-market-02.json` 再跑只调 1 次（`market`），`chapter == "market"` 的旧片段被清掉（`market-2` 章的诱饵不许误伤）；手改一个片段后重渲染只有块内变化；`--force` 全部重跑 | `::test_rerun_is_byte_identical_and_only_missing_chapters_are_refilled`、`::test_force_reruns_every_chapter`、`::test_orphan_topics_from_a_rerun_l1_are_swept`（L1 重跑后的孤儿片段）、`::test_a_chapter_whose_boundaries_moved_is_not_reused`（L1 重切后边界变了） |
| 10 | `filler`：「开场与设备测试」一个字不出现、块首行有「另有 1 段杂项未渲染（合计 00:03:30）」、`frag-bridge-01.json` 在且五类内容为空；没有 `filler` 的集不出那一句 | `::test_filler_is_invisible_but_counted`、`test_sm_render_ep.py::test_filler_is_not_rendered_but_its_minutes_are_reported`、`::test_every_topic_gets_a_seekable_heading_and_its_paragraphs`（构造的无 `filler` 集） |
| 11 | `aside` 只出 `paras`：`market-03` 那一节没有锚点 / 说法 / 信源小标题 | `::test_an_aside_topic_renders_only_its_paragraphs`、`test_sm_render_ep.py::test_an_aside_only_shows_its_paragraphs` |
| 12 | prompt：首行匹配 `^version: L2-topic@\d+\.\d+$`；含两种标记、九个键名、三档 `kind`、「上文」「下文」「行号」；不含 `"id"` / `"start"` / `"end"`；例子里每个话题的键集合恰好是 schema 的九个键 | `test_sm_l2.py::test_prompt_version_and_body`、`::test_prompt_does_not_ask_for_what_the_code_already_knows`、`::test_the_example_in_the_prompt_passes_the_code_checks` |

> 验收 12 的「不含 `"who"`」按字面做不到：`quotes` / `claims` / `channels` 的
> **条目**里有 `who` 键，是模型写的（§5.4），prompt 的例子必须出现
> `"who": "瓜哥"`。改成钉住真正的意思——**话题级**没有 `who`：
> `test_the_example_in_the_prompt_passes_the_code_checks` 断言例子里每个话题的键
> 集合恰好等于 schema 的九个键，`test_prompt_does_not_ask_…` 另外断言 prompt 里
> 不出现 `"who": [` 这种话题级说话人名单。

红线映射：红线 2、3 在 prompt 的「三 · 铁律」（机械部分归 #53、#54）；红线 5 验收
2；红线 6 `::test_stdout_reports_steps_and_counts_only`（日志里查不到「北港大桥
收费方案」「十五块」这些字）；红线 9 验收 5；红线 10 全部样例来自
`tests/fixtures/` 的合成内容。

---

## 4. 我认为风险最高的两个点

**（一）整理稿的质量这一票一个字都没验到。** 沙箱里跑的是存档响应，证明的只是
机械件：切片、schema、归一、填键、渲染、幂等。真正决定这张票值不值的是 prompt
——`paras` 会不会写成摘要（阅读预算 §1.3 要的是 0.2 压缩比，不是 0.05）、`aside`
会不会被压成一行、`kind` 会不会把正题判成 `filler`（那样它整个从笔记上消失，只
在块首行留下一句「另有 N 段杂项未渲染」）。**合并后第一件事就是拿 EP02 跑一遍读
出来**（下面第 5 节），粒度与字数的打磨归 #57。`filler` 误判是这里唯一会「丢东西」
的路径，块首行那句话就是为它留的告警。

**（二）并发 3 在真机上是第一次跑。** 沙箱里的并发用例是拖慢的假 runner，没有
真的起过三个 `claude -p` 子进程。EP02 有 11–13 章，三个子进程同时在同一个订阅
额度池里跑（还要跟 agent-alert 共享），可能出现的新现象：某一章超时（单章
1800 秒）、CLI 并发限流、日志交错读不出哪一行属于哪一章。失败语义已经按单章
隔离写好了（一章挂了其他章继续，整集不渲染、下次只补那一章），但**第一次跑建议
用 `--workers 1` 看一遍**，确认单章的耗时与费用，再放回 3。

另外一条不算风险、但评审值得看一眼的：**信源表的单元格不转义 `|`、也不管换行**。
渲染不许改模型写的字（红线 5），所以 `name` / `quote` 里真出现竖线或换行时，那一行
表格会散。合成样例里没有，真实样例里大概率也没有（中文全角居多）；散掉也只是块内
的排版，下一次重跑整块替换就恢复（会撑破块的那一类——HTML 注释——已经在
`check_frag` 里拦下了）。真撞上了再决定是转义还是换渲染形式，不要悄悄替模型改字。

---

## 5. 合并后跑真实样例的验证指引（人，笔记本交互式会话）

> 下面整节可以直接当提示词用。vault = `D:\obsidian-task\任务栏\story-machine`。

### 5.1 跑

```powershell
.\scripts\worker.ps1 -Extract EP02
```

L1 的 `chapters.json` 已经在的话这一步会跳过（日志里是「L1 产物已在…跳过调用」），
直接进 L2。想换参数就直接调 python：

```powershell
python scripts\digest.py ep EP02 --vault "D:\obsidian-task\任务栏\story-machine" --workers 1
```

- `--l2-model` / `--l2-effort` 默认 `sonnet` / `medium`（SPEC §7 的 L2 起手值），
  `--l2-prompt` 默认 `prompts\L2-topic.md`；`--model` / `--effort` 那两个是 L1 的。
- `--workers` 默认 3；**第一次跑建议 `--workers 1`**，日志不交错，好读单章耗时。
- `--timeout` 默认 1800 秒，是**每次调用**的上限（L1 一次、L2 每章一次）；
  `--retries` 默认 1（检查不过再调一次，带上一次的答卷和错误）。
- **`--replay` / `--only` 本票没有**（归 #55）。想不烧额度重渲染笔记：把
  `_digest\EP02\topics.json` 与 `frag-*.json` 留着重跑一次 `-Extract EP02`，
  L1 L2 都会跳过，只重渲染那一块。
- 预计：EP02（3 小时 10 分）11–13 章，每章一次调用，`--workers 3` 下大约十几分钟。

### 5.2 看什么

1. **`_digest\EP02\topics.json`**
   - 话题数应当是章数的 2–4 倍（EP02 约 25–45 个）；每个话题的 `start` / `end`
     首尾相接铺满它所在的章；`id` 形如 `<章节 id>-01`。
   - `kind` 分布：`filler` 只该盖开场寒暄、答谢礼物、口播、结尾预告。
     **`filler` 超过四五个就是判太松了**，去片段里翻一眼它们的 `title`。
   - provenance 七个键齐，`unit` 是 `all`，`engine` 应当是 `claude-sonnet-5` 这种
     真实模型名（不是 `sonnet`）。
2. **随便挑一章的 `_digest\EP02\frag-<章节>-0N.json`**（挑一个 15 分钟的章）
   - 这一章各话题的 `paras` 加起来，比着**本章逐字稿字数 × 0.2**（SPEC §1.3 的
     压缩比，主口径）。少一大截是在写摘要，多一大截是在誊逐字稿——两种都是
     prompt 的问题（#52 后续把目标字数算进输入、#57 打磨），不是代码的问题。
     *2026-09-18 EP02 实跑：正文 40,679 字、压缩比 0.73，超预算 3.4 倍。这一条
     原先写的「1500–3000 字」是凭空定的绝对值，已作废。*
   - 每个话题 `quotes` ≤ 6 条，`text` 里没有标点（真实逐字稿是无标点的 ASR 文本，
     加了标点说明模型在改字，L3 的闸门 1 会把它整条删掉）。
   - `talk` 话题的 `claims` 一般 5–15 条；`asr` 多半 0–2 条。
   - `paras` 里只有 `[HH:MM:SS]`、`<who>`、`<hedge>` 三种标记；**限定词该标的都标了**
     （挑一段他说「应该」「听说」的，看有没有 `<hedge>`）。
3. **`_pairs\EP02\L2-<章节>.in.md`**（喂进去的原样输入，随便挑一章）
   - 头六行：`episode:` / `章节:` / `标题:` / `范围:` / `行号:` / `说话人:`；
     `行号:` 的两个数就是「本章」那一段第一行和最后一行行首的整数。
   - 章节地图一章一行、本章那一行行首是 `→`。
   - 三段分隔行 `=== 上文（只供理解，不写） ===` / `=== 本章 ===` /
     `=== 下文（只供理解，不写） ===`；第一章没有「上文」，最后一章没有「下文」。
4. **`_pairs\EP02\L2-*.raw.json`**（十几份）
   - 每份的 `num_turns`、`duration_ms`、`total_cost_usd`；把 `total_cost_usd`
     **求和**，那就是 L2 跑一集的额度成本。记下来回填 SPEC §7 与 ADR 0005。
5. **EP02 笔记**（Obsidian 打开，这是这张票真正的交付物）
   - 一个话题一节 `### [HH:MM:SS] 标题`，`aside` 的标题后面挂「 · 旁白」。
   - **点三个时间戳看跳播**：段首的、锚点行里的、信源表格里的各一个（插件认裸
     `[HH:MM:SS]`，ADR 0001）。
   - 块首行那句「另有 N 段杂项未渲染（合计 HH:MM:SS）」：**N 与时长都要合理**
     （3 小时的集里合计超过 15 分钟就去翻那几个 `filler` 片段，多半误判了）。
   - **计时读一遍**（#50 的判据是 30 分钟内读完）。读的时候留意：有没有一段读着
     像摘要、有没有一件事只讲了一半（章界接缝，见下）。
   - frontmatter：`整理: done`、`整理版本: L2-topic@0.1`；块外人写的东西一个字节
     没动。
6. **章界上的接缝**
   - 在 `topics.json` 里数一数 `start` 落在某一章 `start` 后 1 分钟内的话题、以及
     `gist` 里写了「接上一章」「下一章继续」的话题；挑两个在笔记里读一遍，看
     前后两半接不接得上。接不上说明章节地图那段上下文没起作用，归 #57。

### 5.3 什么现象说明坏了

| 现象 | 说明 | 怎么办 |
|---|---|---|
| 退出码 1、`整理: failed`、`_failed\EP02\L2-<章节>.failed.json` 出现 | 那一章两次都没过代码检查（`errors` 里带着位置：第几个话题、行号多少）。其他章的片段已经写好了，`topics.json` 里也有，只是整集不渲染 | 直接再跑一次 `-Extract EP02`：完成的章会跳过，只补这一章。反复挂在同一类错（段没有时间戳、多余标记）→ 改 `prompts\L2-topic.md` 升 `version:` 重跑 |
| 日志里某章「重试 1 次仍不过」，错误是「响应不是合法 JSON」 | 模型没按 schema 交货（`--json-schema` 会在会话里先自己重来 5 次），或者信封是 `error_max_structured_output_retries` | 看 `_pairs\EP02\L2-<章节>.raw.json` 里模型到底回了什么；单章现象就重跑，每章都这样就是 prompt 或 schema 的问题 |
| 某章调用超过 1800 秒被杀 | 章太长（L1 偶尔切出 30 分钟以上的章）或 CLI 卡住 | `--timeout 3600` 重跑那一集；连着出现就去看 L1 把章切多长了 |
| 整理稿读着像摘要、3 小时一集只有五六千字 | prompt 的问题，不是代码的问题 | 改 `prompts\L2-topic.md`（「全长、按叙述顺序、不压成条目」那几条），升 `version:`，`-Extract EP02 -Redo`。**不要**去代码里加字数检查 |
| 笔记里少了一整段你记得他讲过的内容，块首行的「杂项未渲染」时长很大 | 模型把正题判成了 `filler` | 去 `_digest\EP02\` 里找那个 `kind: filler` 的片段确认，然后改 prompt 的 `kind` 判据（「整段删掉会不会丢东西」）升版本重跑 |
| 笔记里出现 `<who>` / `<hedge>` 字样，或表格散掉 | 渲染没把标记换掉（不可能，有用例）；表格散掉多半是 `name` / `quote` 里有 `\|` 或换行 | 前者报 bug；后者见第 4 节最后一段 |
| 某章反复挂在「里有 HTML 注释，渲染进笔记会撑破标记块」 | 模型在 `title` / `gist` / 锚点 / 说法 / 信源里写了 `<!-- … -->`（逐字稿里几乎不可能有，多半是它自己加的排版） | 重跑一次；反复出现就在 prompt 里补一句「不要写 HTML 注释」并升 `version:`。**不要**改成渲染时删注释——那是替模型改字 |
| 抛 Python 栈、提到 `claude` | 环境问题（CLI 不在 PATH、退出码非 0、信封不是 JSON）。单章抛异常不会掀翻整集：那一章记进 `_failed/`，其他章照跑 | 修环境重跑，完成的章会跳过 |

### 5.4 回退

- 整张 PR：`git revert`。回到章节大纲态**必须**连 `render_digest` 一起回退（`-Extract`
  只会重跑，不会把笔记里的整理稿变回大纲）。
- 只想重跑 L2：删 `_digest\EP02\frag-*.json` 与 `_digest\EP02\topics.json`
  （`chapters.json` 留着，L1 就不用重跑），再 `-Extract EP02`。
- 想连 L1 一起重来：`-Extract EP02 -Redo`（= `--force`）。L1 重切之后旧片段的
  `chapter` 可能对不上新章节，代码会把这些孤儿片段连同话题表里的条目一起清掉并
  记一行日志。
- vault 里彻底清干净：删 `_digest\EP02\`、手删 EP02 笔记里
  `<!-- digest:auto -->` … `<!-- /digest -->` 整块、把 `整理: done` 改回 `pending`。
  `_pairs\EP02\` 建议留着（永久正本，§9；#55 的 `--replay` 要用它免额度重渲染）。
