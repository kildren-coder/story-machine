# -*- coding: utf-8 -*-
"""大纲渲染：`filler` 不进阅读面，但不许悄悄消失（SPEC §5.7）。

答谢礼物、设备测试这种零信息的段落渲染出来只会稀释正题，所以不给 `###`；
可模型也会误判——把正题标成 `filler` 的那一次，人在笔记上就再也看不见它。
所以段数与合计时长必须报在块首行（红线 2 的形态：只让位，不删事）。
"""
from __future__ import annotations

import conftest                                          # noqa: F401  （挂 sys.path）
from sm.render_ep import render_outline

VER = "L1-skeleton@9.9"
NOW = "2026-03-12T23:10:00+08:00"


def topic(tid, kind, a, b, title=None):
    return {"id": tid, "kind": kind, "title": title or tid,
            "start": a, "end": b, "who": ["阿桥"], "gist": f"{tid} 的交接说明"}


def test_filler_is_not_rendered_but_is_counted():
    out = render_outline([
        topic("opening", "filler", "00:00:00", "00:03:10", "开场问好与感谢礼物"),
        topic("bridge", "talk", "00:03:10", "00:20:00", "北港大桥收费方案"),
        topic("danmu", "aside", "00:20:00", "00:24:00", "回应弹幕：房价"),
        topic("outro", "filler", "00:24:00", "00:26:30", "结尾预告"),
    ], VER, NOW)

    assert "### [00:03:10] 北港大桥收费方案" in out
    assert "### [00:20:00] 回应弹幕：房价 · 旁白" in out
    # 两段 filler 的标题、gist 一个字都不出现
    for gone in ("开场问好与感谢礼物", "结尾预告", "opening 的交接说明", "outro 的交接说明"):
        assert gone not in out, gone
    assert out.count("### ") == 2
    # 但人看得见「这里少了 2 段、共 5 分 40 秒」
    assert "另有 2 段杂项未渲染（合计 00:05:40）" in out


def test_no_filler_means_no_tail():
    out = render_outline([topic("bridge", "talk", "00:00:00", "00:20:00")], VER, NOW)
    assert "杂项未渲染" not in out
    assert "批注请写在块外。" in out
