# -*- coding: utf-8 -*-
"""L1 的机械检查、归一与 prompt（issue #51 验收 7、12；章节契约）。

`check_chapters` 是红线 9 的入口：它判不过的单元会被拦进 `_failed/`。但它**只拦
代码修不了的**（SPEC §4.1）：行号不在这一集里、标题或 gist 是空的。`id` 不合规、
行号写成字符串、顺序乱了、首章没从第 1 行起、两章写了同一行，全部由 `tidy` 与
`with_ends` 归一——这几类从前各自让整集重发过一趟。

时间这一侧已经没有可错的东西：模型不写时刻，只写行号（输入里现成的闭集），
时刻由代码拿同一张行表换回来，终点由下一章的起点推出。
"""
from __future__ import annotations

import re

from conftest import REPO
from sm.l1 import (build_input, chapter_budget, check_chapters, out_of_order, schema_for,
                   tidy, with_ends)
from sm.prov import read_prompt
from sm.transcript import build_lines

PROMPT = REPO / "prompts" / "L1-skeleton.md"
DUR = 3600                                             # 一小时的一集，120 行，一行 30 秒


def make_segs(n: int, first: float = 0.0) -> list[dict]:
    segs = [{"start": first + i * 30.0, "end": first + i * 30.0 + 29.0,
             "speaker": "SPEAKER_00" if i < n // 2 else "SPEAKER_01", "text": f"第{i + 1}行"}
            for i in range(n)]
    segs[-1]["end"] = first + n * 30.0
    return segs


SEGS = make_segs(120)
LINES = build_lines(SEGS)
NAMES = {"SPEAKER_00": "阿桥（主播）", "SPEAKER_01": "老周（嘉宾）"}


def chapters(*line_nos) -> dict:
    return {"chapters": [{"id": f"c{n}", "title": f"第{n}章", "line": ln, "gist": f"交接{n}"}
                         for n, ln in enumerate(line_nos, 1)]}


def errs(obj) -> str:
    return "\n".join(check_chapters(obj, len(LINES)))


def test_the_fixture_episode_is_120_lines():
    assert len(LINES) == 120 and LINES[40]["t"] == 1200


def test_ordered_lines_pass():
    assert check_chapters(chapters(1, 41), len(LINES)) == []


def test_a_line_outside_the_episode_is_rejected():
    """行号只能取自输入每行行首的那个数。表外的行号代码换不回时刻，这条必须拦
    ——给了 schema 时 CLI 已经用 `maximum` 拦过一遍，这里兜的是旧存档与假 runner。"""
    assert "不在这一集的行号里（1–120）" in errs(chapters(1, 121))
    assert "不在这一集的行号里" in errs(chapters(0, 5))
    assert "不是行号" in errs(chapters(1, "00:05:00"))
    assert "不是行号" in errs(chapters(1, True))


def test_the_schema_carries_this_episodes_line_count():
    line = schema_for(len(LINES))["properties"]["chapters"]["items"]["properties"]["line"]
    assert line == {"type": "integer", "minimum": 1, "maximum": 120}
    items = schema_for(430)["properties"]["chapters"]["items"]
    assert items["required"] == ["id", "title", "line", "gist"]
    assert items["additionalProperties"] is False
    assert "pattern" not in items["properties"]["id"]          # id 的样子由 tidy 归一，不卡


def test_out_of_order_chapters_are_sorted_not_rejected():
    """模型偶尔把回头再谈的内容按主题挪到前一次旁边（话题制时 EP01 上 20 轮
    出现 1 次）。位置本身没错，只是列表顺序错了——顺序是代码能归一的。"""
    obj = chapters(1, 81, 41, 101)
    assert check_chapters(obj, len(LINES)) == []
    assert out_of_order(obj["chapters"]) == 2
    cs = with_ends(obj["chapters"], LINES, DUR, NAMES)
    assert [c["id"] for c in cs] == ["c1", "c3", "c2", "c4"]
    assert [c["start"] for c in cs] == ["00:00:00", "00:20:00", "00:40:00", "00:50:00"]
    assert [c["end"] for c in cs] == ["00:20:00", "00:40:00", "00:50:00", "01:00:00"]
    assert cs[1]["title"] == "第3章"                    # 只挪位置，一个字不改
    assert out_of_order(chapters(1, 41)["chapters"]) == 0


def test_the_chain_is_closed_by_construction():
    """`with_ends` 接出来的链：首尾相接、无缝、无重叠，最后一章收在时长。"""
    cs = with_ends(chapters(1, 41, 81)["chapters"], LINES, DUR, NAMES)
    assert cs[0]["start"] == "00:00:00" and cs[-1]["end"] == "01:00:00"
    for a, b in zip(cs, cs[1:]):
        assert a["end"] == b["start"]
    assert all(c["start"] < c["end"] for c in cs)


def test_the_first_chapter_always_starts_at_zero():
    """首章写成了第 3 行，或者逐字稿第一行不是从 0 秒开始：第一章一律从
    00:00:00 起，开头那一截并进第一章。"""
    cs = with_ends(chapters(3, 41)["chapters"], LINES, DUR, NAMES)
    assert cs[0]["start"] == "00:00:00" and cs[0]["end"] == "00:20:00"


def test_a_short_chapter_is_merged_into_its_shorter_neighbour():
    """prompt 写了「不到 8 分钟的不单独成章」，模型照样切（EP01 一轮 14 章里 8 章
    不到 8 分钟）。章是容器，并起来一个字都不丢：标题用顿号接、gist 按先后接。
    L2 一章一次调用，调用次数不能跟着模型的手感摆。"""
    cs = with_ends(chapters(1, 41, 47, 81)["chapters"], LINES, DUR, NAMES)   # 第 2 章只有 3 分钟
    assert [c["id"] for c in cs] == ["c1", "c3", "c4"]      # 并进较短的邻居（第 3 章），id 留吸收方
    assert cs[1]["title"] == "第2章、第3章" and cs[1]["gist"] == "交接2 交接3"
    assert (cs[1]["start"], cs[1]["end"]) == ("00:20:00", "00:40:00")

    tail = with_ends(chapters(1, 41, 115)["chapters"], LINES, DUR, NAMES)    # 末章只有 3 分钟
    assert [c["id"] for c in tail] == ["c1", "c2"]
    assert tail[1]["title"] == "第2章、第3章" and tail[1]["end"] == "01:00:00"

    chain = with_ends(chapters(1, 5, 9, 13, 81)["chapters"], LINES, DUR, NAMES)  # 连着四个 2 分钟
    assert [(c["start"], c["end"]) for c in chain] == [("00:00:00", "00:40:00"), ("00:40:00", "01:00:00")]
    assert chain[0]["title"] == "第1章、第2章、第3章、第4章"
    assert chain[0]["gist"] == "交接1 交接2 交接3 交接4"          # 先后不乱


def test_two_chapters_on_one_line_become_one():
    """两章写了同一行：前一章长度为 0，它的内容就在后一章开头那一行里——并进
    后一章，不打回，也不替模型删东西。"""
    obj = chapters(1, 41, 41, 81)
    assert check_chapters(obj, len(LINES)) == []
    cs = with_ends(obj["chapters"], LINES, DUR, NAMES)
    assert [c["id"] for c in cs] == ["c1", "c3", "c4"]
    assert cs[1]["title"] == "第2章、第3章" and cs[1]["start"] == "00:20:00"


def test_the_first_chapters_length_is_counted_from_the_first_line():
    """真库 EP01 第一行是 00:07:47，前面是静音。第一章从 00:00:00 起，但它有
    多长得从第一行算——不然 8 分钟静音加 3 分钟话就混过了「不到 8 分钟」。"""
    segs = make_segs(100, first=480.0)                   # 第一行 00:08:00
    lines = build_lines(segs)
    cs = with_ends(chapters(1, 7, 51)["chapters"], lines, 3480, NAMES)   # 第 1 章只有 3 分钟话
    assert [c["id"] for c in cs] == ["c2", "c3"]
    assert (cs[0]["start"], cs[0]["end"]) == ("00:00:00", "00:33:00")


def test_a_short_episode_ends_up_as_one_chapter():
    segs = make_segs(12)                                 # 6 分钟
    cs = with_ends(chapters(1, 7)["chapters"], build_lines(segs), 360, NAMES)
    assert len(cs) == 1 and (cs[0]["start"], cs[0]["end"]) == ("00:00:00", "00:06:00")


def test_who_is_filled_by_code_from_the_lines_each_chapter_owns():
    """说话人行表里本来就有，不让模型再写一遍。按出场先后，用点名后的名字
    （去掉角色后缀）；没点名的保留 SPEAKER_XX。"""
    cs = with_ends(chapters(1, 41, 81)["chapters"], LINES, DUR, NAMES)
    assert [c["who"] for c in cs] == [["阿桥"], ["阿桥", "老周"], ["老周"]]
    bare = with_ends(chapters(1)["chapters"], LINES, DUR, {})
    assert bare[0]["who"] == ["SPEAKER_00", "SPEAKER_01"]
    # 产物里的键：模型写的 `line` 换成了 `start` / `end`
    assert list(cs[0]) == ["id", "title", "start", "end", "who", "gist"]


def test_ids_are_normalised_never_rejected():
    """`id` 是机器键不是人读的字：大小写、空格、下划线归一（haiku 写过
    `eric-Adams-mandela`），写了中文或漏写的按位置补 `chNN`，重复的加后缀。"""
    obj = chapters(1, 5, 9, 13, 17)
    for c, raw in zip(obj["chapters"], ["eric-Adams mandela", "Bridge_Toll", "大桥", "bridge-toll", None]):
        c["id"] = raw
    del obj["chapters"][4]["id"]
    tidied = tidy(obj)
    assert [c["id"] for c in tidied["chapters"]] == [
        "eric-adams-mandela", "bridge-toll", "ch03", "bridge-toll-2", "ch05"]
    assert check_chapters(tidied, len(LINES)) == []
    assert obj["chapters"][0]["id"] == "eric-Adams mandela"        # 不改原对象


def test_a_line_number_written_as_a_string_is_read():
    obj = chapters(1, "11", 15.0)
    assert [c["line"] for c in tidy(obj)["chapters"]] == [1, 11, 15]
    assert check_chapters(tidy(obj), len(LINES)) == []


def test_a_newline_in_a_title_is_flattened_but_a_comment_marker_is_rejected():
    """标题 / gist 原样进标记块。换行换成空格只动了空白，由代码归一；HTML 注释
    会把块结构撑破，而删它等于改字——拦下。"""
    obj = chapters(1)
    obj["chapters"][0]["title"] = "两行\n  标题"
    assert tidy(obj)["chapters"][0]["title"] == "两行 标题"
    assert check_chapters(tidy(obj), len(LINES)) == []
    assert "撑破标记块" in errs(obj)                     # 没过 tidy 的照样拦得住

    obj = chapters(1)
    obj["chapters"][0]["gist"] = "收尾 <!-- /digest -->"
    assert "撑破标记块" in "\n".join(check_chapters(tidy(obj), len(LINES)))


def test_field_and_shape_errors():
    obj = chapters(1)
    del obj["chapters"][0]["gist"]
    obj["chapters"][0]["title"] = "  "
    e = errs(obj)
    assert "缺字段 `gist`" in e and "`title` 不是非空字符串" in e
    assert check_chapters([], len(LINES)) == ["顶层不是对象"]
    assert check_chapters({}, len(LINES)) == ["`chapters` 不是非空数组"]
    assert check_chapters({"chapters": []}, len(LINES)) == ["`chapters` 不是非空数组"]


def test_chapter_budget_follows_the_duration():
    """参考章数 = 时长 ÷ 15 分钟，至少 1。L2 的调用次数跟着它，不跟着模型的手感。"""
    assert [chapter_budget(s) for s in (300, 840, 1623, 2560, 8486, 11443)] == [1, 1, 2, 3, 9, 13]


def test_head_is_one_key_per_line():
    """头一行一个键：`episode:` 那行只有集号。

    挤成一行（`episode: EP02 · 时长 … · 说话人 …`）的时候，模型把整行抄进了
    `ep`，EP02 上连挂两次、两次都重发了整集逐字稿。歧义要消在输入里，不是靠
    prompt 多写一句话求它别抄错。
    """
    text = build_input("EP02", SEGS, NAMES)
    head, body = text.split("\n---\n", 1)
    assert head.splitlines() == ["episode: EP02", "时长: 01:00:00", "行数: 120",
                                 "参考章数: 4", "说话人: 阿桥（主播）、老周（嘉宾）"]
    rows = body.splitlines()
    assert rows[0] == "1 [00:00:00] 阿桥: 第1行" and rows[60] == "61 [00:30:00] 老周: 第61行"
    assert len(rows) == 120


def test_prompt_version_and_keys_in_body():
    """验收 12：首行版本号形状 + 正文写清四个键、行号与参考章数。"""
    text = PROMPT.read_bytes().decode("utf-8")
    first = text.splitlines()[0]
    assert re.match(r"^version: L1-skeleton@\d+\.\d+$", first)
    for key in ("`id`", "`title`", "`line`", "`gist`", "行号", "参考章数", '"chapters"'):
        assert key in text, key
    # 版本号不钉死：打磨期它每改一版就升一次（#57），钉死只会逼人改测试
    assert read_prompt(PROMPT)["version"] == first.split(": ", 1)[1]
    assert len(read_prompt(PROMPT)["sha8"]) == 8


def test_prompt_does_not_ask_for_what_the_code_already_knows():
    """时刻、终点、集号、说话人、话题分档都不归 L1 的模型写。prompt 里再提，它就
    又会去写，又多一处会错的地方。"""
    text = PROMPT.read_bytes().decode("utf-8")
    for gone in ('"start"', '"end"', '"ep"', '"who"', '"kind"', "ranges", "filler"):
        assert gone not in text, gone
    assert "只写行号，不写时刻" in text
