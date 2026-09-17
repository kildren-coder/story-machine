# -*- coding: utf-8 -*-
"""§5.1 → §5.2 的渲染与点名（issue #51 验收 6、10）。

红线 1 / 2 在代码里的形态：行首那截 `行号 [HH:MM:SS] 名字: ` 是代码加的，段文本必须
一个字不改地落进行里。下面的 walk 把每一行拆回段文本来证明这件事。
"""
from __future__ import annotations

import re

from conftest import FIX, fixture_note_text
from sm.note import read_frontmatter, read_speakers
from sm.text import hms
from sm.transcript import (build_lines, duration_s, line_t, read_transcript, render_lines,
                           slice_chapter)

LINE_RE = re.compile(r"^(\d+) \[(\d\d:\d\d:\d\d)\] (?:([^:]{1,20}): )?(.*)$")


def load(ep: str):
    segs, _ = read_transcript(FIX / "vault" / "_assets" / f"{ep}.transcript.json")
    text = fixture_note_text(ep)
    return segs, read_speakers(text, read_frontmatter(text))


def walk(lines: list[str], segs: list[dict]):
    """逐行把段文本消掉。返回 [(时间戳, 名字或 None, 该行的段下标)]。"""
    out, si = [], 0
    for line in lines:
        m = LINE_RE.match(line)
        assert m, f"行首形状不对：{line!r}"
        no, ts, who, body = int(m.group(1)), m.group(2), m.group(3), m.group(4)
        assert no == len(out) + 1, "整集渲染时行号从 1 起、一行加一"
        first = si
        while body:
            t = str(segs[si]["text"]).strip()
            assert body.startswith(t), f"第 {si} 段的文本被改过：{body[:20]!r}"
            body = body[len(t):]
            si += 1
            if body:
                assert body.startswith(" "), "同一行的段之间只能有一个空格"
                body = body[1:]
        assert ts == hms(float(segs[first]["start"])), "行首时间戳不是该行第一段的 start"
        out.append((ts, who, first))
    assert si == len(segs), "有段没被渲染进去（红线 1：不许丢）"
    return out


def test_read_speakers_takes_name_and_role():
    """验收 10：点过名的带上角色，render_lines 行首只用名字。"""
    _, spk = load("EP91")
    assert spk == {"SPEAKER_00": "阿桥（主播）", "SPEAKER_01": "老周（嘉宾）"}


def test_ep91_lines_are_verbatim():
    """验收 6：行首时间戳、段间一个空格、一个字不改。"""
    segs, spk = load("EP91")
    lines = render_lines(segs, spk).splitlines()
    rows = walk(lines, segs)
    assert lines[0] == f"1 [00:00:00] 阿桥: {segs[0]['text']}"
    # 说话人变化才写名字：第二行同一个人，不重复写
    assert rows[1][1] is None and lines[1].startswith("2 [00:00:35] 弹幕")
    assert rows[2][1] == "老周"
    assert rows[3][1] == "阿桥"


def test_speaker_change_inside_one_window_breaks_the_line():
    """结尾两个 30 秒窗里两人各说一句 → 四行，各自带名字。"""
    segs, spk = load("EP91")
    tail = render_lines(segs, spk, start=2490).splitlines()
    assert [LINE_RE.match(x).group(1, 2, 3) for x in tail] == [
        ("73", "00:41:30", "阿桥"), ("74", "00:41:48", "老周"),
        ("75", "00:42:05", "阿桥"), ("76", "00:42:22", "老周")]


def test_same_window_same_speaker_joins_with_one_space():
    """同窗同人连成一行，段间一个空格（fixture 的段都比 30 秒长，这里现造）。"""
    segs = [{"start": 0.0, "end": 9.5, "speaker": "SPEAKER_00", "text": "第一句合成文本"},
            {"start": 10.0, "end": 19.5, "speaker": "SPEAKER_00", "text": "第二句合成文本"},
            {"start": 31.0, "end": 40.0, "speaker": "SPEAKER_00", "text": "跨窗那句"}]
    out = render_lines(segs, {"SPEAKER_00": "阿桥（主播）"})
    assert out == ("1 [00:00:00] 阿桥: 第一句合成文本 第二句合成文本\n"
                   "2 [00:00:31] 跨窗那句\n")


def test_unnamed_speaker_keeps_the_tag():
    """验收 10 后半：EP92 去掉点名 → 行首是 SPEAKER_00（不许编名字）。"""
    segs, _ = load("EP92")
    lines = render_lines(segs, {}).splitlines()
    assert lines[0].startswith("1 [00:00:00] SPEAKER_00: ")
    walk(lines, segs)


def test_slice_takes_lines_whose_start_falls_inside_and_keeps_their_numbers():
    """L2 用的切片：只取起点落在范围内的行，行不切开；**行号照旧是全集的**——
    L1 看到的第 35 行和 L2 在切片里看到的第 35 行是同一行。切片的第一行总是
    写名字（哪怕整集渲染时它跟上一行同一个人）。"""
    segs, spk = load("EP91")
    lines = render_lines(segs, spk, start=1140, end=2160).splitlines()
    assert lines[0].startswith("35 [00:19:00] 阿桥: ")
    assert lines[-1].startswith("62 [00:35:24] ")
    starts = [float(s["start"]) for s in segs if 1140 <= float(s["start"]) < 2160]
    assert len(lines) == len(starts)
    assert render_lines(segs, spk).splitlines()[34].startswith("35 [00:19:00] ")


def test_line_numbers_map_back_to_the_timestamp_printed_on_that_line():
    """模型用行号指位置，代码用同一张行表把它换回时刻：换回来的就是那一行行首
    印着的 `[HH:MM:SS]`，所以「某行属于哪一章」两头用的是同一把尺。"""
    segs, spk = load("EP91")
    table = build_lines(segs)
    for raw in render_lines(segs, spk).splitlines():
        m = LINE_RE.match(raw)
        assert hms(line_t(table, int(m.group(1)))) == m.group(2)
    assert line_t(table, 0) is None and line_t(table, len(table) + 1) is None
    assert line_t(table, "7") is None and line_t(table, 7) == 210


def test_slice_chapter_pads_two_minutes_and_truncates_at_the_episode_edges():
    """L2 的切片：本章 + 前后各 2 分钟，越过首尾的那一段是空的（issue #52 验收 3）。"""
    segs, _ = load("EP91")
    lines = build_lines(segs)

    before, market, after = slice_chapter(lines, 1140, 2560)        # market 章
    assert [ln["n"] for ln in before] == [32, 33, 34]               # 00:17:00 起
    assert market[0]["n"] == 35 and market[-1]["n"] == 76
    assert after == []                                              # 章尾就是整集末尾

    before, body, after = slice_chapter(lines, 0, 1140)             # bridge 章
    assert before == []                                             # 章首就是整集开头
    assert body[0]["n"] == 1 and body[-1]["n"] == 34
    assert [ln["n"] for ln in after] == [35, 36, 37, 38]            # 00:21:00 前

    # 余量可调，行不切开：改 pad 只改两侧带几行，本章那一段一个字不变
    narrow = slice_chapter(lines, 1140, 2560, pad=60)
    assert [ln["n"] for ln in narrow[0]] == [34]                    # 00:18:00 起
    assert narrow[1] == market


def test_duration_comes_from_the_last_segment():
    for ep, want in (("EP91", "00:42:40"), ("EP92", "00:14:00")):
        segs, _ = load(ep)
        assert hms(duration_s(segs)) == want
        # 笔记的 `时长:` 是人看的那份，值该对得上（不参与检查，只做一致性提醒）
        assert read_frontmatter(fixture_note_text(ep))["时长"] == want
