# -*- coding: utf-8 -*-
"""L2 上线前的整理稿：章节大纲（SPEC §5.7）。

章是容器，不分档：每章一行可跳播的标题，下面是 L1 写的 `gist`，全部照列。哪些
是过场（`filler`）要等 L2 在章内细分话题时才知道——「`filler` 不渲染、段数与合计
时长报在块首行」那条规矩跟着话题走，属于 L2 的渲染（#52）。
"""
from __future__ import annotations

import conftest                                          # noqa: F401  （挂 sys.path）
from sm.render_ep import render_outline

VER = "L1-skeleton@9.9"
NOW = "2026-03-12T23:10:00+08:00"


def chapter(cid, a, b, title=None):
    return {"id": cid, "title": title or cid, "start": a, "end": b,
            "who": ["阿桥"], "gist": f"{cid} 的交接说明"}


def test_every_chapter_gets_a_seekable_heading_and_its_gist():
    out = render_outline([
        chapter("bridge", "00:00:00", "00:19:00", "开场、北港大桥收费方案"),
        chapter("market", "00:19:00", "00:36:00", "河口夜市搬迁滨江路"),
    ], VER, NOW)

    # 时间戳写成裸 [HH:MM:SS]，跳播插件才认（ADR 0001）
    assert "### [00:00:00] 开场、北港大桥收费方案\n\nbridge 的交接说明\n" in out
    assert "### [00:19:00] 河口夜市搬迁滨江路\n\nmarket 的交接说明\n" in out
    assert out.count("### ") == 2
    assert out.startswith("## 整理稿\n\n> [!info] 本块由 L3 渲染（整理版本 L1-skeleton@9.9，"
                          f"生成于 {NOW}）；重跑会覆盖，批注请写在块外。\n")
    assert "旁白" not in out and "杂项未渲染" not in out
