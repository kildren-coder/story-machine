# -*- coding: utf-8 -*-
"""L2 的输入、形状、机械检查与归一、代码填的键、并发（issue #52 验收 3、4、7、8、12）。

`check_frag` 是红线 9 的入口：它判不过的章会被拦进 `_failed/`，其他章照跑。但它
**只拦代码修不了的**（SPEC §4.1）：行号不在本章、标题空、段没有时间戳、段里冒出
第三种尖括号标记、`ts` 读不出时刻。`ts` 写成 `MM:SS`、`quotes` 写了七条、`asr` 里
两边一样的条目、话题顺序乱了，全部由 `tidy` 归一，不打回。

时间这一侧没有可错的东西：模型只写行号（切片里现成的闭集），时刻、终点、话题
`id`、说话人全由代码填。
"""
from __future__ import annotations

import json
import re
import threading
import time
from pathlib import Path

from conftest import REPO
from sm.l2 import (build_input, check_frag, finish, run_l2, schema_for, tidy)
from sm.paths import VaultPaths
from sm.prov import read_prompt
from sm.text import hms
from sm.transcript import build_lines

PROMPT = REPO / "prompts" / "L2-topic.md"
NAMES = {"SPEAKER_00": "阿桥（主播）", "SPEAKER_01": "老周（嘉宾）"}


def make_segs(n: int) -> list[dict]:
    """一行 30 秒的合成逐字稿：第 n 行的行号就是 n，起点 (n-1)×30 秒。"""
    segs = [{"start": i * 30.0, "end": i * 30.0 + 29.0,
             "speaker": "SPEAKER_00" if i % 2 == 0 else "SPEAKER_01", "text": f"第{i + 1}行"}
            for i in range(n)]
    segs[-1]["end"] = n * 30.0
    return segs


SEGS = make_segs(120)                                    # 一小时，120 行
LINES = build_lines(SEGS)
CHAPTERS = [{"id": "one", "title": "第一章", "start": "00:00:00", "end": "00:20:00",
             "who": ["阿桥"], "gist": "第一章的交接说明"},
            {"id": "two", "title": "第二章", "start": "00:20:00", "end": "01:00:00",
             "who": ["阿桥"], "gist": "第二章的交接说明"}]


def topic(at: int, kind: str = "talk", **over) -> dict:
    t = {"title": f"第 {at} 行起的话题", "kind": kind, "line": at, "gist": "合成的一句话",
         "paras": [f"[00:{at // 2:02d}:00] <who>阿桥</who>说了点什么"],
         "quotes": [{"ts": "00:01:00", "who": "阿桥", "text": "原话"}],
         "claims": [{"ts": "00:01:00", "who": "阿桥", "claim": "说法", "quote": "原话"}],
         "channels": [{"ts": "00:01:00", "who": "阿桥", "name": "某通报", "kind": "政府通报",
                       "quote": "原话"}],
         "asr": [{"heard": "北岗", "means": "北港"}]}
    t.update(over)
    return t


def errs(obj, first: int = 1, last: int = 40) -> str:
    return "\n".join(check_frag(obj, first, last))


# ---------------------------------------------------------------- 输入

def test_head_is_one_key_per_line_and_the_map_marks_this_chapter():
    """头一行一个键；章节地图一章一行，本章那一行行首标 `→`（验收 3）。"""
    text = build_input("EP02", CHAPTERS[1], CHAPTERS, LINES, NAMES)
    head, rest = text.split("\n---\n", 1)
    assert head.splitlines() == ["episode: EP02", "章节: two", "标题: 第二章",
                                 "范围: 00:20:00–01:00:00", "行号: 41–120",
                                 "说话人: 阿桥（主播）、老周（嘉宾）"]
    chart, body = rest.split("\n---\n", 1)
    rows = chart.splitlines()
    assert len(rows) == 2 and rows[0].startswith("  1. 00:00:00–00:20:00 第一章 —— ")
    assert rows[1].startswith("→ 2. 00:20:00–01:00:00 第二章 —— ")
    assert body.startswith("=== 上文（只供理解，不写） ===\n37 [00:18:00] ")


def test_an_empty_side_drops_its_separator_line():
    """本章在整集开头（或结尾）：那一段连分隔行一起不出现——空标题下面跟着
    「本章」的内容，模型会以为那也是上文。"""
    first = build_input("EP02", CHAPTERS[0], CHAPTERS, LINES, NAMES)
    assert "上文" not in first
    assert "=== 本章 ===\n1 [00:00:00] 阿桥: 第1行" in first
    assert first.rstrip().endswith("44 [00:21:30] 老周: 第44行")   # 下文带到 00:22:00 前
    assert "=== 下文（只供理解，不写） ===\n41 [00:20:00] " in first

    last = build_input("EP02", CHAPTERS[1], CHAPTERS, LINES, NAMES)
    assert "下文" not in last and "=== 上文" in last


# ---------------------------------------------------------------- 形状

def test_the_schema_carries_this_chapters_line_range():
    """验收 4：行号上下界就是本章的首末行号——写出本章之外的行号，CLI 在会话里
    就让它重来了，不用我们把这一章重发一趟。"""
    items = schema_for(35, 76)["properties"]["topics"]["items"]
    assert items["properties"]["line"] == {"type": "integer", "minimum": 35, "maximum": 76}
    assert items["properties"]["kind"]["enum"] == ["talk", "aside", "filler"]
    assert items["properties"]["quotes"]["maxItems"] == 6
    assert items["required"] == ["title", "kind", "line", "gist",
                                 "paras", "quotes", "claims", "channels", "asr"]
    assert items["additionalProperties"] is False
    # `id` / `start` / `end` / `who` 是代码填的，模型不写，schema 里也就没有
    assert "id" not in items["properties"] and "start" not in items["properties"]
    ch = items["properties"]["channels"]["items"]
    assert ch["required"] == ["ts", "who", "name", "kind", "quote"]
    assert ch["additionalProperties"] is False
    assert "pattern" not in ch["properties"]["ts"]        # ts 的样子由 tidy 归一，不卡


# ---------------------------------------------------------------- 检查（拦）

def test_a_line_outside_this_chapter_is_rejected():
    """代码不知道它想指哪一行，也就换不回时刻——这条只能打回。"""
    assert "不在本章的行号里（35–76）" in errs({"topics": [topic(34)]}, 35, 76)
    assert "不在本章的行号里" in errs({"topics": [topic(77)]}, 35, 76)
    assert "不是行号" in errs({"topics": [topic(1, line="00:05:00")]})
    assert check_frag({"topics": [topic(35)]}, 35, 76) == []


def test_empty_paras_on_a_talk_or_aside_is_rejected():
    """`paras` 是整理稿本身，空着等于这一段没整理——代码补不出来。"""
    assert "`paras` 不能为空" in errs({"topics": [topic(3, paras=[])]})
    assert "`paras` 不能为空" in errs({"topics": [topic(3, "aside", paras=[])]})
    # filler 的五类内容本来就该是空的
    assert check_frag({"topics": [topic(3, "filler", paras=[], quotes=[], claims=[],
                                        channels=[], asr=[])]}, 1, 40) == []


def test_a_paragraph_without_a_timestamp_is_rejected():
    """每段开头那个时刻是跳播用的（ADR 0001），代码不知道这段对应哪一行。"""
    assert "不以 `[HH:MM:SS]` 开头" in errs({"topics": [topic(3, paras=["说了点什么"])]})
    assert "不以 `[HH:MM:SS]` 开头" in errs({"topics": [topic(3, paras=["[03:00] 说了点什么"])]})


def test_a_third_kind_of_tag_in_paras_is_rejected():
    """段文本逐字进笔记（红线 5），删掉那个标记等于改字。只认 `<who>` 与 `<hedge>`。"""
    bad = topic(3, paras=["[00:01:00] <b>加粗</b>不在三种标记里"])
    assert "只认 `<who>` 与 `<hedge>`" in errs({"topics": [bad]})
    ok = topic(3, paras=["[00:01:00] <who>阿桥</who>说<hedge>应该</hedge>是这样"])
    assert check_frag({"topics": [ok]}, 1, 40) == []


def test_empty_title_missing_key_and_unreadable_ts_are_rejected():
    obj = {"topics": [topic(3, title="  ")]}
    del obj["topics"][0]["channels"]
    e = errs(obj)
    assert "`title` 不是非空字符串" in e and "缺字段 `channels`" in e

    weird = topic(3, quotes=[{"ts": "胡写", "who": "阿桥", "text": "原话"}])
    assert "读不出时刻" in errs({"topics": [weird]})
    assert "撑破标记块" in errs({"topics": [topic(3, gist="收尾 <!-- /digest -->")]})
    assert check_frag([], 1, 40) == ["顶层不是对象"]
    assert check_frag({"topics": []}, 1, 40) == ["`topics` 不是非空数组"]


# ---------------------------------------------------------------- 归一（不拦）

def test_tidy_normalises_what_the_code_can_fix():
    """验收 7 后半：这几类从前各自能让一整章重发一趟。"""
    obj = {"topics": [
        topic(9, line="9", quotes=[{"ts": f"{i}:05", "who": "阿桥", "text": f"原话{i}"}
                                   for i in range(1, 8)],
              asr=[{"heard": "北岗", "means": "北岗"}, {"heard": "北岗", "means": "北港"}]),
        topic(3, claims=[{"ts": "1:02:03", "who": "阿桥", "claim": "说法", "quote": "原话"}]),
    ]}
    out = tidy(obj)
    assert [t["line"] for t in out["topics"]] == [3, 9]           # 顺序乱了 → 按行号排
    late = out["topics"][1]
    assert len(late["quotes"]) == 6                               # 7 条 → 留前 6 条
    assert late["quotes"][0]["ts"] == "00:01:05"                  # `1:05` → `00:01:05`
    assert late["asr"] == [{"heard": "北岗", "means": "北港"}]     # 两边一样的删掉
    assert out["topics"][0]["claims"][0]["ts"] == "01:02:03"      # `H:MM:SS` → `HH:MM:SS`
    assert check_frag(out, 1, 40) == []
    assert obj["topics"][0]["line"] == "9"                        # 不改原对象


def test_tidy_flattens_newlines_in_title_and_gist():
    """标题与 gist 原样进标记块，换行会把块撑破；换掉的只是空白。"""
    out = tidy({"topics": [topic(3, title="两行\n  标题", gist="两行\ngist")]})
    assert out["topics"][0]["title"] == "两行 标题" and out["topics"][0]["gist"] == "两行 gist"
    assert check_frag(out, 1, 40) == []


def test_an_aside_that_wrote_quotes_keeps_them_in_the_fragment():
    """`aside` 只该写 `paras`，多写的留在片段里（渲染不出、不进 L4），不打回
    ——删它等于替模型丢东西。"""
    obj = {"topics": [topic(3, "aside")]}
    assert check_frag(tidy(obj), 1, 40) == []
    frag = finish(tidy(obj)["topics"], CHAPTERS[0], LINES, NAMES)[0]
    assert frag["kind"] == "aside" and len(frag["quotes"]) == 1


# ---------------------------------------------------------------- 代码填的键

def test_finish_fills_id_chapter_times_and_who():
    """验收 4：模型只写 `line`，其余由代码填；`line` 不进产物。"""
    topics = tidy({"topics": [topic(1), topic(11, "filler"), topic(21, "aside")]})["topics"]
    frags = finish(topics, CHAPTERS[0], LINES, NAMES)
    assert [f["id"] for f in frags] == ["one-01", "one-02", "one-03"]
    assert all(f["chapter"] == "one" and "line" not in f for f in frags)
    assert [f["start"] for f in frags] == ["00:00:00", "00:05:00", "00:10:00"]
    assert [f["end"] for f in frags] == ["00:05:00", "00:10:00", "00:20:00"]
    for a, b in zip(frags, frags[1:]):                   # 章内首尾相接
        assert a["end"] == b["start"]
    assert frags[0]["who"] == ["阿桥", "老周"]           # 行表里现成的，按出场先后
    assert list(frags[0]) == ["id", "chapter", "title", "kind", "start", "end", "who",
                              "gist", "paras", "quotes", "claims", "channels", "asr"]


def test_the_first_topic_starts_at_the_chapter_start_and_the_last_ends_at_its_end():
    """章内第一个话题归位到章的 `start`（章首那几行不许掉出去），最后一个收在
    章的 `end`——章与章之间由构造闭合。"""
    topics = tidy({"topics": [topic(7), topic(21)]})["topics"]
    frags = finish(topics, CHAPTERS[0], LINES, NAMES)
    assert frags[0]["start"] == "00:00:00" and frags[-1]["end"] == "00:20:00"


def test_two_topics_on_one_line_give_a_zero_length_topic():
    """行首每 30 秒才一个，两个话题挤在同一行是合法的：前一个长度为 0，照常渲染
    （§5.3）。它自己的行里没有人说话，`who` 就是空的。"""
    topics = tidy({"topics": [topic(1), topic(11), topic(11)]})["topics"]
    frags = finish(topics, CHAPTERS[0], LINES, NAMES)
    assert (frags[1]["start"], frags[1]["end"]) == ("00:05:00", "00:05:00")
    assert frags[1]["who"] == [] and frags[2]["start"] == "00:05:00"


# ---------------------------------------------------------------- 并发

class SlowRunner:
    """记录并发数的假 runner：人为拖慢，好让几章真的同时在跑。"""

    replay = False

    def __init__(self, digest_dir: Path, delay: float = 0.05):
        self.digest_dir = Path(digest_dir)
        self.delay = delay
        self.lock = threading.Lock()
        self.calls: list[str] = []
        self.live = 0
        self.peak = 0
        self.topics_seen: list[int] = []

    def run(self, scope, layer, unit, prompt_file, input_text, model, effort, timeout,
            schema=None) -> dict:
        with self.lock:
            self.live += 1
            self.peak = max(self.peak, self.live)
            self.calls.append(unit)
            # 主线程正在重写话题表：worker 每次抬头看到的都得是完整的一份
            p = self.digest_dir / "topics.json"
            if p.exists():
                self.topics_seen.append(len(json.loads(p.read_bytes().decode("utf-8"))["topics"]))
        try:
            time.sleep(self.delay)
            first = int(re.search(r"行号: (\d+)–", input_text).group(1))
            return {"structured_output": {"topics": [
                {"title": f"{unit} 的话题", "kind": "talk", "line": first,
                 "gist": "合成的交接说明",
                 "paras": ["[00:00:00] <who>阿桥</who>说了点什么"],
                 "quotes": [], "claims": [], "channels": [], "asr": []}]}}
        finally:
            with self.lock:
                self.live -= 1


def test_three_chapters_at_a_time_and_every_write_lands_on_the_main_thread(tmp_path, monkeypatch):
    """验收 8：并发 ≤ 3；五章都完成；`_digest/` 只有主线程这一支笔。

    线程里起子进程（真跑时是 `claude -p`）没有共享状态，但话题表是全集一份：让
    worker 去写，重跑一章时两支笔会互相盖掉对方刚写完的那一份。
    """
    paths = VaultPaths(tmp_path)
    segs = make_segs(300)                                # 两个半小时，一章 30 分钟
    chapters = [{"id": f"ch{i}", "title": f"第{i}章", "gist": "合成的交接说明",
                 "start": hms(i * 1800), "end": hms((i + 1) * 1800),
                 "who": ["阿桥"]} for i in range(5)]
    prompt = {"path": PROMPT, "version": "L2-topic@9.9"}

    import sm.l2 as l2
    writes: list[str] = []
    real = l2._write_json
    monkeypatch.setattr(l2, "_write_json",
                        lambda p, o: (writes.append(threading.current_thread().name), real(p, o))[1])

    runner = SlowRunner(paths.digest("EP99"))
    doc, frags, failed = run_l2(paths, runner, "EP99", chapters, segs, NAMES, prompt,
                                workers=3, generated_at="2026-03-12T23:10:00+08:00",
                                log=lambda m: None)

    assert failed == [] and len(runner.calls) == 5
    assert runner.peak <= 3, f"同时在跑 {runner.peak} 章，超过并发上限"
    assert runner.peak > 1, "五章全串行跑了，并发没起作用"
    assert len(doc["topics"]) == 5 and len(frags) == 5
    assert [t["chapter"] for t in doc["topics"]] == [f"ch{i}" for i in range(5)]
    assert set(writes) == {threading.main_thread().name}
    # worker 中途读到的话题表每一份都是完整 JSON（上面已经 json.loads 过）
    assert runner.topics_seen == sorted(runner.topics_seen)


# ---------------------------------------------------------------- prompt

def test_prompt_version_and_body():
    """验收 12：首行版本号形状 + 正文写清九个键、三档、两种标记、切片三段。"""
    text = PROMPT.read_bytes().decode("utf-8")
    first = text.splitlines()[0]
    assert re.match(r"^version: L2-topic@\d+\.\d+$", first)
    for key in ("`title`", "`kind`", "`line`", "`gist`", "`paras`", "`quotes`",
                "`claims`", "`channels`", "`asr`", "`talk`", "`aside`", "`filler`",
                "<who>", "<hedge>", "上文", "下文", "行号", '"topics"'):
        assert key in text, key
    assert read_prompt(PROMPT)["version"] == first.split(": ", 1)[1]


def test_prompt_does_not_ask_for_what_the_code_already_knows():
    """话题 `id`、起止时刻、说话人名单都是代码填的。prompt 里再提，模型就会去写，
    又多一处会错的地方（L1 上的教训）。"""
    text = PROMPT.read_bytes().decode("utf-8")
    for gone in ('"id"', '"start"', '"end"', '"ep"', '"chapter"'):
        assert gone not in text, gone
    # `who` 只作为原话锚点 / 说法 / 信源条目里的键出现；话题自己的说话人名单是
    # 代码从行表里填的（例子里九个键一个不多，见下一条）
    assert not re.search(r'"who":\s*\[', text)
    assert "只写行号，不写时刻" in text


def test_the_example_in_the_prompt_passes_the_code_checks():
    """例子是模型唯一会照着抄的东西：它自己得过得了 `check_frag`，键也得跟
    schema 对得上，否则第一发就是打回。"""
    text = PROMPT.read_bytes().decode("utf-8")
    body = re.findall(r"```json\s*(.+?)```", text, re.S)[-1]
    obj = json.loads(body)
    keys = set(schema_for(1, 999)["properties"]["topics"]["items"]["properties"])
    assert [t["kind"] for t in obj["topics"]] == ["filler", "talk", "aside"]
    for t in obj["topics"]:
        assert set(t) == keys
    assert check_frag(tidy(obj), 1, 999) == []
