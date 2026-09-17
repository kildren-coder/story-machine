# -*- coding: utf-8 -*-
"""整理稿的渲染：话题表 + 片段 → EP 笔记里那一块（SPEC §5.7、§5.9；issue #52 验收 10、11）。

按**话题**出节，不按章——章只是 L2 的调用单位，人读的是话题。渲染不生成一个字：
三种标记换成 Obsidian 认的写法，其余逐字照搬（红线 5）。
"""
from __future__ import annotations

import re

import conftest                                          # noqa: F401  （挂 sys.path）
from sm.render_ep import render_digest, render_para

VER = "L2-topic@9.9"
NOW = "2026-03-12T23:10:00+08:00"


def topic(tid, kind, a, b, title=None) -> dict:
    return {"id": tid, "chapter": "ch", "title": title or tid, "kind": kind,
            "start": a, "end": b, "who": ["阿桥"], "gist": f"{tid} 的一句话"}


def frag(tid, **over) -> dict:
    f = {"paras": [f"[00:00:00] <who>阿桥</who>讲了 {tid}"],
         "quotes": [], "claims": [], "channels": [], "asr": []}
    f.update(over)
    return f


def test_every_topic_gets_a_seekable_heading_and_its_paragraphs():
    topics = [topic("t1", "talk", "00:03:30", "00:19:00", "北港大桥收费方案"),
              topic("t2", "talk", "00:19:00", "00:36:00", "河口夜市搬迁")]
    out = render_digest(topics, {"t1": frag("t1"), "t2": frag("t2")}, VER, NOW)

    # 时间戳写成裸 [HH:MM:SS]，跳播插件才认（ADR 0001）
    assert "### [00:03:30] 北港大桥收费方案\n\n[00:00:00] **阿桥**讲了 t1\n" in out
    assert out.count("### ") == 2
    assert out.startswith("## 整理稿\n\n> [!info] 本块由 L3 渲染（整理版本 L2-topic@9.9，"
                          f"生成于 {NOW}）；重跑会覆盖，批注请写在块外。\n")
    assert "杂项未渲染" not in out and "旁白" not in out


def test_five_kinds_of_content_each_get_their_own_subsection():
    f = frag("t1",
             quotes=[{"ts": "00:04:36", "who": "老周", "text": "十五块是听证会的建议价"}],
             claims=[{"ts": "00:04:36", "who": "老周", "claim": "听证会建议价 15 元",
                      "quote": "十五块是听证会的建议价"}],
             channels=[{"ts": "00:03:30", "who": "阿桥", "name": "市交通局通报",
                        "kind": "政府通报", "quote": "市交通局上周发了一个通报"}],
             asr=[{"heard": "北岗大桥", "means": "北港大桥"}])
    out = render_digest([topic("t1", "talk", "00:03:30", "00:19:00")], {"t1": f}, VER, NOW)

    assert "**原话锚点**\n\n- [00:04:36] 老周：「十五块是听证会的建议价」\n" in out
    assert "**可核查的说法**\n\n- [00:04:36] 老周：听证会建议价 15 元\n" in out
    assert ("**提到的信源**\n\n| 信源 | 类型 | 谁 | 时间戳 | 原话 |\n"
            "| --- | --- | --- | --- | --- |\n"
            "| 市交通局通报 | 政府通报 | 阿桥 | [00:03:30] | 市交通局上周发了一个通报 |\n") in out
    assert "**疑似 ASR 生音**\n\n- 听成「北岗大桥」→ 应为「北港大桥」\n" in out


def test_an_empty_subsection_keeps_quiet():
    """`talk` 话题里没有信源是常事，留个空标题只是噪音。"""
    out = render_digest([topic("t1", "talk", "00:00:00", "00:10:00")], {"t1": frag("t1")},
                        VER, NOW)
    for title in ("原话锚点", "可核查的说法", "提到的信源", "疑似 ASR 生音"):
        assert title not in out


def test_an_aside_only_shows_its_paragraphs():
    """验收 11：`aside` 的标题后加「· 旁白」，多写的锚点留在片段里、不渲染。"""
    f = frag("t2", quotes=[{"ts": "00:41:30", "who": "阿桥", "text": "多写的一条"}],
             claims=[{"ts": "00:41:30", "who": "阿桥", "claim": "多写的", "quote": "多写的一条"}])
    out = render_digest([topic("t2", "aside", "00:41:30", "00:42:40", "结尾弹幕")],
                        {"t2": f}, VER, NOW)
    assert "### [00:41:30] 结尾弹幕 · 旁白" in out
    assert "原话锚点" not in out and "可核查的说法" not in out
    assert "多写的一条" not in out
    assert "[00:00:00] **阿桥**讲了 t2" in out


def test_filler_is_not_rendered_but_its_minutes_are_reported():
    """验收 10：`filler` 一个字都不出现，但段数与合计时长报在块首行——不报的话，
    模型把正题误判成 `filler` 时人在笔记上再也看不见它。"""
    topics = [topic("t0", "filler", "00:00:00", "00:03:30", "开场与设备测试"),
              topic("t1", "talk", "00:03:30", "00:19:00", "北港大桥收费方案"),
              topic("t9", "filler", "00:19:00", "00:20:30", "念打赏名单")]
    out = render_digest(topics, {"t1": frag("t1")}, VER, NOW)
    assert "另有 2 段杂项未渲染（合计 00:05:00）。" in out.splitlines()[2]
    assert "开场与设备测试" not in out and "念打赏名单" not in out
    assert out.count("### ") == 1


def test_markers_become_obsidian_writing_and_nothing_else_moves():
    """红线 5：除三种标记外一个字节不动。还原回去要逐字等于片段里那一段。"""
    para = ("[00:05:43] <who>阿桥</who>说十五块<hedge>应该</hedge>不准，"
            "<hedge>听说</hedge>会压到十二块（十二块这个数他没法验证）")
    out = render_para(para)
    assert out == ("[00:05:43] **阿桥**说十五块<u>应该</u>不准，"
                   "<u>听说</u>会压到十二块（十二块这个数他没法验证）")
    back = re.sub(r"\*\*(.*?)\*\*", r"<who>\1</who>", out) \
             .replace("<u>", "<hedge>").replace("</u>", "</hedge>")
    assert back == para
