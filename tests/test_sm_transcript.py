# -*- coding: utf-8 -*-
"""§5.1 → §5.2 的渲染与点名（issue #51 验收 6、10）。

红线 1 / 2 在代码里的形态：行首那截 `[HH:MM:SS] 名字: ` 是代码加的，段文本必须
一个字不改地落进行里。下面的 walk 把每一行拆回段文本来证明这件事。
"""
from __future__ import annotations

import re

from conftest import FIX, fixture_note_text
from sm.note import read_frontmatter, read_speakers
from sm.text import hms
from sm.transcript import duration_s, read_transcript, render_lines

LINE_RE = re.compile(r"^\[(\d\d:\d\d:\d\d)\] (?:([^:]{1,20}): )?(.*)$")


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
        ts, who, body = m.group(1), m.group(2), m.group(3)
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
    assert lines[0] == f"[00:00:00] 阿桥: {segs[0]['text']}"
    # 说话人变化才写名字：第二行同一个人，不重复写
    assert rows[1][1] is None and lines[1].startswith("[00:00:35] 弹幕")
    assert rows[2][1] == "老周"
    assert rows[3][1] == "阿桥"


def test_speaker_change_inside_one_window_breaks_the_line():
    """结尾两个 30 秒窗里两人各说一句 → 四行，各自带名字。"""
    segs, spk = load("EP91")
    tail = render_lines(segs, spk, start=2490).splitlines()
    assert [LINE_RE.match(x).group(1, 2) for x in tail] == [
        ("00:41:30", "阿桥"), ("00:41:48", "老周"),
        ("00:42:05", "阿桥"), ("00:42:22", "老周")]


def test_same_window_same_speaker_joins_with_one_space():
    """同窗同人连成一行，段间一个空格（fixture 的段都比 30 秒长，这里现造）。"""
    segs = [{"start": 0.0, "end": 9.5, "speaker": "SPEAKER_00", "text": "第一句合成文本"},
            {"start": 10.0, "end": 19.5, "speaker": "SPEAKER_00", "text": "第二句合成文本"},
            {"start": 31.0, "end": 40.0, "speaker": "SPEAKER_00", "text": "跨窗那句"}]
    out = render_lines(segs, {"SPEAKER_00": "阿桥（主播）"})
    assert out == ("[00:00:00] 阿桥: 第一句合成文本 第二句合成文本\n"
                   "[00:00:31] 跨窗那句\n")


def test_unnamed_speaker_keeps_the_tag():
    """验收 10 后半：EP92 去掉点名 → 行首是 SPEAKER_00（不许编名字）。"""
    segs, _ = load("EP92")
    lines = render_lines(segs, {}).splitlines()
    assert lines[0].startswith("[00:00:00] SPEAKER_00: ")
    walk(lines, segs)


def test_slice_takes_segments_whose_start_falls_inside():
    """L2 用的切片：只取起点落在范围内的段，段不切开。"""
    segs, spk = load("EP91")
    lines = render_lines(segs, spk, start=1140, end=2160).splitlines()
    assert lines[0].startswith("[00:19:00] ")
    assert lines[-1].startswith("[00:35:24] ")
    starts = [float(s["start"]) for s in segs if 1140 <= float(s["start"]) < 2160]
    assert len(lines) == len(starts)


def test_duration_comes_from_the_last_segment():
    for ep, want in (("EP91", "00:42:40"), ("EP92", "00:14:00")):
        segs, _ = load(ep)
        assert hms(duration_s(segs)) == want
        # 笔记的 `时长:` 是人看的那份，值该对得上（不参与检查，只做一致性提醒）
        assert read_frontmatter(fixture_note_text(ep))["时长"] == want
