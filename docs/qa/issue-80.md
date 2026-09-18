# QA — issue #80 阶段 0 转写：吞块补解（疑似吞块逐级切短重解 15→10→7 秒）

分支 `agent/issue-80`。沙箱内 `bash scripts/test.sh` 全绿（160 个 pytest 用例：
原有 118 + 本票 42），没有调用过 `claude -p`，没有碰过 vault，没有 GPU / 音频参与。
合并前评审在本机与 PC 上另做的实证见第 6 节。
样例是 `tests/fixtures/redecode/EP93.redecode.json`（合成，内容虚构，红线 10；它与
生成脚本在 #80 落 SPEC 那一笔里已经进仓库，本票只消费它）。

背景一句话：batched 管线把 VAD 语音拼成 ≤30 秒的块，每块只解一遍、没有降温重试，
长块会被整块吞掉——EP02 正本因此少了约 6% 的汉字。补解就是把疑似被吞的那几块单独
拿出来、只改 `chunk_length` 再听一遍，不用 LLM，不碰别的块。

---

## 1. 改动摘要

| 文件 | 做了什么 |
|---|---|
| `pc/redecode.py`（新，约 390 行） | 规则层，**纯标准库**。汉字计数 / 语音秒 / 块内空洞 / 复读 / 保留比例 / 判疑似 / 判参选 / 合块 / 阶梯驱动 / `redecode` 报告；解码器以回调注入（`decode(k, start, end, chunk_length)`）。`--demo <样例>` 拿样例里的假解码表跑一遍规则层 |
| `pc/smpc.py` | `transcribe` 在第一遍收完段之后、写盘之前接上补解：复算 VAD 块 → 真解码器（同一个 `pipe`、同一份 kw，只加 `chunk_length`）→ 替换段与词 → 报告写进 `transcript.json` 顶层、`config` 追加 ` redecode`、日志一行 ASCII。新增 `redecode_pass` / `_redecode` / `ascii_only`，常量 `SR` / `VAD_MIN_SILENCE_MS` |
| `scripts/setup-pipeline.ps1` | PC 侧上传从只传 `smpc.py` 改成 `smpc.py` + `redecode.py`（静态改，沙箱跑不了 PowerShell） |
| `SPEC.md` §4 阶段 0 | 补规则层文件名与 `--demo`、合块条件（照抄 `collect_chunks`）、复算失败也跳过且不让转写失败、替换**连起止时刻一起换**、报告字段写全、真跑过才标 `config` |
| `tests/test_pc_redecode.py`（新，42 个用例） | 验收 1–10 逐条 + 合块（含恰好 30 s 的判界）+ smpc 接线（假 `faster_whisper` / 假 `pipe`） |

`pc/` 不在 `tests/conftest.py` 的 `sys.path` 里（那份只管 `scripts/`），测试文件自己加。

### 自审逮到的两个真缺陷（已修，各配用例，commit `d313ed9`）

1. **补解整步没有兜底 `except`，而它跑在写盘之前。** 原来只有 VAD 复算和单级解码兜了
   异常，`redecode.run` 本身裸奔；规则层算空洞、判疑似都在 try 之外。复现：词表里有个
   只有两个元素的词，`gap_s` 抛 `IndexError`，异常一路穿出 `cmd_transcribe`——**几个
   小时的转写一个字都落不了盘**，比不补严重得多。现在整步兜底：跳过、报原因、正本照写
   （`test_smpc_never_lets_the_redecode_step_take_the_transcript_down`）。
2. **段数 / 词数对不上而跳过时，报告里的 `chunks` 记成 0**，明明刚复算出来。人拿这个
   数对着查「复算出几块 vs 第一遍几段」，记成 0 就白瞎了。

---

## 2. 沙箱内已验证：验收标准 → 用例

| 验收 | 用例（`tests/test_pc_redecode.py`） |
|---|---|
| 1 疑似块 = {1,2,3,4,6,7,8}；5 因语音 <8 秒不算，6 靠空洞判出 | `test_the_seven_suspect_blocks_are_the_ones_the_fixture_names`、`test_a_short_block_is_never_suspect_however_few_words_it_has`、`test_block_six_is_caught_by_the_hole_not_by_the_density`、`test_normal_blocks_are_neither_thin_nor_holey`、`test_a_hole_at_the_head_or_the_tail_counts_too` |
| 2 每块结局与样例 `expect` 一致（1、6→15；2、3、7→10；4、8 残留） | `test_every_block_ends_exactly_where_the_fixture_expects` |
| 3 非疑似块与残留块逐字节不变 | `test_untouched_and_residual_blocks_are_byte_identical`、`test_the_inputs_are_not_mutated`、`test_the_segment_count_never_changes` |
| 4 不引入解码输出以外的字（文本 = 各段文本按序拼、词 = 各段词按序拼、`"".join(词) == 文本`） | `test_replaced_segments_contain_nothing_the_decoder_did_not_write`、`test_the_whole_transcript_only_grows_by_what_was_recovered` |
| 5 阶梯按规则走（块 2 取中 15 秒但仍疑似→继续；块 1 通过后不再调 10、7；会计数的假解码器） | `test_the_ladder_stops_as_soon_as_the_block_is_no_longer_suspect`、`test_block_two_takes_the_fifteen_second_version_and_still_goes_on`、`test_a_later_rung_only_wins_if_it_has_more_han` |
| 6 不参选的原因进报告（块 3 复读、块 7 保留 <80%） | `test_a_looping_version_is_rejected_and_the_report_says_so`、`test_a_version_that_lost_the_original_text_is_rejected_and_the_report_says_so`、`test_a_version_that_barely_adds_anything_is_rejected`、`test_acceptable_reports_every_reason_it_failed_on` |
| 7 块 8 三级都抛异常：不中断、记三条错误、残留保留原文 | `test_three_failed_decodes_leave_the_block_alone_and_are_all_reported`、`test_one_broken_rung_does_not_stop_the_next_one` |
| 8 段数 ≠ 块数：整步跳过，段与词原样返回，报告标 `skipped` 和原因 | `test_a_segment_count_mismatch_skips_the_whole_step`、`test_a_words_count_mismatch_skips_the_whole_step_too` |
| 9 报告字段（顶层 `rule` / 四个计数 / `skipped`；每块 `k`…`residual`；`tries` 七个键） | `test_the_report_has_exactly_the_agreed_fields`、`test_the_report_is_json_serialisable_as_is`、`test_the_rule_block_records_the_constants_actually_in_force` |
| 10 只有标准库的环境里能 import | `test_redecode_imports_nothing_outside_the_standard_library`（AST 扫 import）、`test_redecode_imports_on_a_machine_without_numpy_or_faster_whisper`（子进程里把 numpy / faster_whisper / opencc / torch 钉成 `None` 再 import） |
| 可见变化（演示命令） | `test_the_demo_command_runs_and_agrees_with_the_fixture`、`test_the_demo_fails_loudly_when_the_rules_stop_matching_the_fixture` |

验收之外另外钉住的（都是沙箱里能验、真机上验不起的）：`group_chunks` 的合块条件三个
用例；`redecode_pass` 的接线——VAD 样点 → 秒、`audio[块起点:块终点]` 的切片边界、
每级调用前 `pipe.last_speech_timestamp` 清零、kw 只多一个 `chunk_length` 且第一遍的
kw 不被就地改、时间加块起点、文本与词都过同一张 t2s 字表、跳过时 `config` 不冒充跑过、
日志行纯 ASCII、`setup-pipeline.ps1` 确实把 `redecode.py` 一起传上去。

**两处 SPEC 没写死、按字面意思裁的边**（写在代码注释里，评审请重点看这两条）：

- `kept_ratio`：原文 0 汉字时返回 1.0（空集上「全都在」为真）。生成脚本里那个参考
  实现写的是 `sum / max(1, len(o))` = 0.0，样例里没有这种块所以两边都自洽；但整块被
  吞光恰恰是最该补的情形，除零把它挡在门外说不过去。
- 「词拼起来 = 段文本」这条**空白不计**（`check_diar.py` 的 `norm` 是同一把尺子）：
  faster-whisper 的词带前导空格、段文本不一定。字一个都不能差；对不上的版本按这一级
  失败处理、记进 `errors`，不静默也不去「修」。

---

## 3. 风险最高的两点

1. **复算出来的块对不上第一遍的段，补解就整步空转。** 这是本票唯一真正的门槛，而且
   **沙箱里验不了**（没有 faster-whisper、没有音频）。管线内部不把块交出来，只能拿
   同一套 VAD 参数（`max_speech_duration_s=30`、`min_silence_duration_ms=160`）复算
   一遍再照抄合块条件；只要 faster-whisper 的 VAD 默认值（`speech_pad_ms` 之类）和
   我们复算时的不一样，块数就会差一两个，于是 `segments != chunks` → 整步跳过。
   失败是安全且吵的（日志明写 `redecode: skipped (segments != chunks (449 vs 452))`，
   正本逐字节照旧），但功能等于没上。**第一次真跑必须先看这一行**，见下面第 5 节。
2. **7 秒这一级在真实音频上一次都没跑过。** EP02 的实验里 15、10 两级就把残留清零了，
   合成样例里 7 秒那一级也只有「三级都不参选」和「三级都报错」两块走到过。真机上遇到
   `picked == 7` 的块要抽听，确认补回来的不是幻觉（复读判据只拦同一个 4 字串 >5 次，
   拦不住「听起来通顺但不是他说的」）。

次要的两条，记在这里免得下次重新踩：`orthography_chars` 仍只数第一遍的转换字数
（补解的文本过的是同一张逐字表，字形保证不变，只是这个计数器不含补解那部分）；
`VAD_MIN_SILENCE_MS = 160` 是手抄 faster-whisper 的内部默认值，升级 faster-whisper
时要回来对一眼——对不上的后果就是风险 1。

---

## 4. 「可见变化」演示（沙箱内实跑，stdout 原样）

```
$ python pc/redecode.py --demo tests/fixtures/redecode/EP93.redecode.json
样例 tests/fixtures/redecode/EP93.redecode.json（EP93，合成，内容虚构）
块 10  段 10  阶梯 15→10→7 秒
规则  语音 ≥8s  密度 <3 字/秒  空洞 ≥5s  增益 ≥20 字  保留 ≥80%  复读 ≤5

块 0  0.0-20.0s  语音 19.4s  97 汉字  → 不疑似，原样
块 1  21.0-46.0s  语音 25.0s  12 汉字 / 空洞 22.1s  → 疑似
     15 秒: 120 汉字  空洞 0.1s  复读 1  参选  ← 取中
     结局: 15 秒补全，12 → 120 汉字，空洞 22.1 → 0.1s
块 2  47.0-75.0s  语音 27.5s  15 汉字 / 空洞 24.5s  → 疑似
     15 秒: 85 汉字  空洞 9.5s  复读 1  参选
     10 秒: 130 汉字  空洞 0.0s  复读 1  参选  ← 取中
     结局: 10 秒补全，15 → 130 汉字，空洞 24.5 → 0.0s
块 3  76.0-100.0s  语音 24.0s  10 汉字 / 空洞 22.0s  → 疑似
     15 秒: 150 汉字  空洞 0.0s  复读 59  不参选 rep4=59>5
     10 秒: 110 汉字  空洞 0.1s  复读 1  参选  ← 取中
     结局: 10 秒补全，10 → 110 汉字，空洞 22.0 → 0.1s
块 4  101.0-121.0s  语音 20.0s  20 汉字 / 空洞 16.0s  → 疑似
     15 秒: 26 汉字  空洞 15.0s  复读 1  不参选 gain=6<20
     10 秒: 24 汉字  空洞 15.0s  复读 1  不参选 gain=4<20
      7 秒: 28 汉字  空洞 14.0s  复读 1  不参选 gain=8<20
     结局: 残留，保留原文（20 汉字）
块 5  122.0-128.0s  语音 6.0s  5 汉字  → 不疑似，原样
块 6  129.0-154.0s  语音 25.0s  100 汉字 / 空洞 10.0s  → 疑似
     15 秒: 140 汉字  空洞 0.0s  复读 1  参选  ← 取中
     结局: 15 秒补全，100 → 140 汉字，空洞 10.0 → 0.0s
块 7  155.0-180.0s  语音 25.0s  30 汉字 / 空洞 22.0s  → 疑似
     15 秒: 100 汉字  空洞 0.1s  复读 2  不参选 kept=0.10<0.80
     10 秒: 125 汉字  空洞 0.0s  复读 1  参选  ← 取中
     结局: 10 秒补全，30 → 125 汉字，空洞 22.0 → 0.0s
块 8  181.0-206.0s  语音 25.0s  10 汉字 / 空洞 23.0s  → 疑似
     15 秒: 解码失败 RuntimeError: CUDA out of memory (fake)
     10 秒: 解码失败 RuntimeError: CUDA out of memory (fake)
      7 秒: 解码失败 RuntimeError: CUDA out of memory (fake)
     结局: 残留，保留原文（10 汉字）
块 9  207.0-230.0s  语音 23.0s  115 汉字  → 不疑似，原样

解码调用 14 次：1@15 2@15 2@10 3@15 3@10 4@15 4@10 4@7 6@15 7@15 7@10 8@15 8@10 8@7
INFO redecode: suspects=7 replaced=5 residual=2 errors=3 han=414->872
transcript.json 顶层 redecode（略去 blocks 的 7 条明细）:
{
 "rule": {
  "min_speech_s": 8,
  "min_density": 3,
  "max_gap_s": 5,
  "ladder": [
   15,
   10,
   7
  ],
  "min_gain_han": 20,
  "min_kept": 0.8,
  "max_rep4": 5,
  "max_chunk_speech_s": 30
 },
 "chunks": 10,
 "suspects": 7,
 "replaced": 5,
 "residual": 2,
 "errors": 3,
 "skipped": null,
 "elapsed_s": null,
 "han_before": 414,
 "han_after": 872
}
与样例 expect 逐块一致。
```

（`elapsed_s` 在演示里是 `null`：那是 `smpc.py` 给整步计的时，规则层自己不看表。
`--json` 连 `blocks` 的明细一起打印。）

`blocks` 里每个疑似块长这样（仍是上面这条演示命令的输出，合成样例的块 3；真机上
的形状一样，只是数不同）：

```json
{
 "k": 3, "start": 76.0, "end": 100.0, "speech_s": 24.0,
 "before": {"han": 10, "gap": 22.04},
 "tries": [
  {"chunk_length": 15, "han": 150, "gap": 0.03, "rep4": 59,
   "acceptable": false, "reason": "rep4=59>5", "error": null},
  {"chunk_length": 10, "han": 110, "gap": 0.05, "rep4": 1,
   "acceptable": true, "reason": null, "error": null}
 ],
 "picked": 10, "after": {"han": 110, "gap": 0.05}, "residual": false
}
```

---

## 5. 合并后跑真实样例的验证指引（笔记本，vault 里有 EP02）

> 下面整段可以直接当提示词用。**先做第 0 步**，不然 PC 上连 `download` 都起不来。

### 0. 部署（必做，一次）

`pc/smpc.py` 现在 `import redecode`，而旧的 `setup-pipeline.ps1` 只传 `smpc.py`。

```powershell
.\scripts\setup-pipeline.ps1 -SkipPlugins
```

看它打出 `C:\asr\smpc.py 已更新` 和 `C:\asr\redecode.py 已更新` 两行。只想手动传：

```powershell
scp .\pc\smpc.py .\pc\redecode.py 5070:C:/asr/
ssh 5070 "C:\asr\venv\Scripts\python.exe -c ""import sys; sys.path.insert(0,'C:/asr'); import redecode; print(redecode.LADDER)"""
```

第二条应当打印 `(15, 10, 7)`。**漏了这一步的症状**：worker 跑任何一步都立刻
`ModuleNotFoundError: No module named 'redecode'`（import 在文件顶上，不是转写才炸）。

### 1. 转写下一集，盯三行日志

照常跑队列（粘链接 → `.\scripts\worker.ps1`，或 `-Watch`）。转写那一步的终端里，
按顺序应当出现：

```
    redecode: chunks=449 segments=449
    redecode: suspects=33 replaced=30 residual=3 errors=0 han=54007->57232 in 121s
    segments=449  191.0min in 251s (45.7x realtime)  t2s=1234 chars
```

逐项对照（数量级取自 EP02 的实验与第 6 节的干跑）：

- **`chunks=N segments=M` 两个数必须相等。** 不等就会在下一行看到
  `redecode: skipped (segments != chunks (449 vs 452))`，补解整步没跑，正本与旧流程
  逐字节相同（不是坏事，只是功能没上）。**这时把这两个数贴回 issue #80**：差多少、
  差在哪个方向，决定要不要调复算时的 VAD 参数。别自己改 `VAD_MIN_SILENCE_MS` 试，
  先看差值。
- `suspects` 的数量级：EP02 是 449 段里 33 块（约 7%）。**超过 20% 说明判据在这一集
  上过敏**（音乐、长笑声、纯环境音都会让密度变低），这时重点看 `replaced` —— 误判块
  应该只空跑、不替换。
- `residual`：走完三级仍疑似的块，个位数正常。残留块**保留原文**，不是空的。
- `errors=0` 是预期。非 0 去 `redecode` 块里看 `tries[].error`：`CUDA out of memory`
  说明块太长 / 显存被占（补解与主转写同为 bs16、块更短，正常不该发生）；
  `words != text` 说明解码器吐的词和文本对不上，那是 faster-whisper 版本问题，
  要报回 issue。
- `han=前->后`：只增不减。EP02 的实验里补回约 3450 字（约 6%）。**如果后 < 前，
  立刻停下报 bug**——规则上不可能发生（参选要求至少多 20 个汉字）。
- `in Ts`：EP02 的实验里 15、10 两级共约 120 秒，主转写 251 秒。数量级差一个数
  （比如 1000 秒）说明疑似块判多了。
- 进度条在补解期间会**退回去再爬一遍音频**，这是故意的：单位跟第一遍一样是秒，
  它确实在重走那几块。不是卡住、不是重新转写。

### 2. 看正本里的 `redecode` 块

取回之后（`_assets\EP{n}.transcript.json`，顶层）：

```powershell
$t = Get-Content "D:\obsidian-task\任务栏\story-machine\_assets\EP03.transcript.json" -Raw -Encoding utf8 | ConvertFrom-Json
$t.config                       # 应当以 " redecode" 结尾；跳过了就没有这个词
$t.redecode.rule                # 8 / 3 / 5 / [15,10,7] / 20 / 0.8 / 5 / 30
$t.redecode | Select-Object chunks, suspects, replaced, residual, errors, skipped, elapsed_s, han_before, han_after
$t.redecode.blocks | Where-Object { $_.picked -eq 7 }        # 7 秒那一级，抽听用
$t.redecode.blocks | Where-Object { $_.residual } | Select-Object k, start, end, before, after
```

- **`picked == 7` 的块：每块抽听一两段**（EP 笔记里点时间戳跳播，`start`/`end` 就是
  块的时间跨度）。听到的话要能和 `segments[k].text` 对上；对不上就是幻觉，把块号、
  时间、文本贴回 issue #80——7 秒这一级还没有真实样例背书。
- **残留块**（`residual: true`）：拿 `start`/`end` 跳播听一下，确认那里本来就是音乐 /
  笑声 / 环境音（该残留），还是真的有人说话却没补回来（判据或阶梯不够）。
- 找一集**音乐或长笑声多的**再跑一遍，专看误判：`suspects` 会偏高，但 `replaced`
  应当接近 0——重解出来的东西补不出 20 个汉字，参选这一关就过不去。

### 3. 分离之后再验一次一致性

说话人分离按词重建段，而补解换过一批段的词，所以这一关要过：

```powershell
python .\pc\check_diar.py EP03
```

必须看到 `✓ words.json 原序拼接与分离前逐字稿一致`。**出现 ✗ 就是本票的 bug**
（替换段的「词拼起来 = 段文本」没守住），把它打印的那一段贴回 issue。
`smdiar.py` 只覆盖 `segments` 和分离相关的键，所以 `redecode` 块在分离后仍在正本里。

### 4. 坏了怎么回退

- **先用应急杠杆，别急着 revert**：把 PC 上 `C:\asr\redecode.py` 的 `LADDER` 改成
  `()`，转写完再改回来。沙箱里实测过：一次解码都不发，`replaced=0`，段与词逐字节
  等于旧流程，报告里 `rule.ladder` 写着 `[]`（所以事后看得出这一集是这么跑的），
  疑似块全部计入 `residual`。这是「这一集先别补解」最小、最可逆的做法。
- **补解的结果不可信**（幻觉、字变少、听不对）：revert 接线那两笔——先
  `fix(pc): 补解整步兜一个 except`，再 `feat(pc): smpc transcribe 写盘前接上补解`
  （合并后用 `git log --oneline -- pc/smpc.py` 找哈希；顺序反了会冲突）。然后重跑
  第 0 步部署再重转。规则层 `pc/redecode.py` 可以留着，没人调用它。
- **重转会覆盖正本**（`EP{n}.transcript.json` 与 `.nodiar.json`），下游派生文件
  必须跟着重来：删 `_digest\EP{n}\`、`_pairs\EP{n}\`、`_failed\EP{n}\`，再按 L1 → L2
  重跑；EP 笔记里的整理稿块会被重新渲染。**EP02 要不要用新流程重转由人决定**——它是
  各层的 golden 样例，重转等于把 L1–L3 的基线一起换掉。
- 中途中断不会留下半份产物：补解在写盘之前，什么都没落盘，整步重来即可
  （`.\scripts\worker.ps1 -Retry EP03`）。

---

## 6. 合并前评审补验（2026-09-19，本机 + PC；不在沙箱范围）

沙箱验不了的两条，合并前用真机数据补验过。脚本与产物只在本机 / PC，不进仓库。

### 6.1 复算的块数 = 第一遍的段数（第 3 节风险 1）

PC 上只跑 VAD（CPU，不解码、不写正本），拿本 PR 的 `redecode.group_chunks` 复算，
与已有正本的段数对照：

| 集 | VAD 语音区间 | 复算块数 | 正本段数 | 累计恰好 30.000 s 的块 |
|---|---|---|---|---|
| EP01 | 1,492 | 321 | 321 | 2 |
| EP02 | 2,139 | 449 | 449 | 1 |
| EP03 | 806 | 52 | 52 | 0 |

三集全部对上。最后一列是评审逮到的边：`collect_chunks` 在整数样点上比「> 480000」，
`group_chunks` 在浮点秒上比「> 30」——累计恰好 480000 样点的块（VAD 强切加两侧补齐
正好凑出）浮点累加得 `30.000000000000004`，会多切一刀，后面的块整体错位，整步被判
「段数 ≠ 块数」跳过。这三集是运气好没撞上（同一批样点换个顺序累加就会撞）。已修：判界
加 `GROUP_EPS_S = 1e-6`（远小于一个样点），配用例
`test_grouping_judges_an_exact_thirty_second_sum_like_collect_chunks_does`（未修版多切一刀，
480001 样点仍会切）。

### 6.2 把规则层套在 EP02 真实数据上干跑

`redecode.run` 不改，解码器换成查表：09-18 实验里已经解好的 15 s / 10 s 版本
（`D:\asr-exp\rechunk-a.json` / `rechunk-a10.json`，31 块）；7 s 与实验没解过的块一律
抛异常。段与词用 `pass1-rerun`（与生产正本逐字相同）。

```
chunks=449 segments=449 words=449   skipped: None
suspects=33 replaced=30 residual=3 errors=7 han=54007->57232 (+3225)
picked: 15 s × 24，10 s × 6，残留 × 3
```

- 疑似 33 块 = 实验按密度判出的 31 块 + 靠空洞判出的 2 块（73、389；实验没解过它们，
  三级都报「无数据」，所以 `errors=7` 全是查表缺项，不是规则层的错）。
- 残留 3 块：47 两级增益只有 16 / 15 汉字（< 20），真机上会走到 7 s；73、389 无数据。
- 未替换的 419 块是同一对象带回（逐字节不变）；30 个替换块「词拼起来 = 段文本」
  全部成立，起止时刻都落在块内。
- 补回 +3,225 汉字，与 #80 正文的「约 3450」同一量级（差的是 47 那一块的 15/10 s 版
  被本 PR 更严的参选条件拦下了）。

### 6.3 顺手对齐的一处

生成脚本 `mk_redecode.py` 的 `kept()` 原来是 `sum / max(1, len(o))`（原文 0 汉字 → 0.0），
与 `pc/redecode.kept_ratio` 的 1.0 不同口径（第 2 节末尾那条）。改成同口径；重生成样例
逐字节不变。
