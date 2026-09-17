# -*- coding: utf-8 -*-
"""逐字稿正本（SPEC §5.1）→ 喂给模型的文本（SPEC §5.2）。

红线 1 / 2 的形态：这里只**拼**，不改一个字。段文本原样进行，行首那截
`[HH:MM:SS] 名字: ` 是代码加的脚手架，闸门匹配原文时要先去掉（见 text.norm）。
"""
from __future__ import annotations

import json
from pathlib import Path

from .note import bare_name
from .text import hms

WINDOW_S = 30.0          # §5.2：时间戳每 30 秒一个，窗起点为整 30 秒


def read_transcript(path: str | Path) -> tuple[list[dict], dict]:
    """返回 (有字的段, meta)。段按 start 排序——正本本来就是有序的，但排序是
    白来的保险，而且**不许**为了排序改文本或丢段（红线 1）。"""
    data = json.loads(Path(path).read_bytes().decode("utf-8"))
    segs = [s for s in data.get("segments", []) if str(s.get("text") or "").strip()]
    segs.sort(key=lambda s: (float(s.get("start") or 0), float(s.get("end") or 0)))
    return segs, data.get("meta") or {}


def duration_s(segments: list[dict]) -> int:
    """整集时长 = 最后一段的 end（取整秒）。

    正本里没有 duration 字段，而 EP 笔记的 `时长:` 是给人看的、可能被改过；覆盖
    检查要跟模型看到的那份文本对得上，所以只认正本。
    """
    return int(round(max((float(s.get("end") or 0) for s in segments), default=0)))


def render_lines(segments: list[dict], names: dict, start: float | None = None,
                 end: float | None = None) -> str:
    """§5.2 文本。窗内同人连成一行（段间一个空格），说话人变化另起一行并写名字，
    行首时间戳 = 该行第一段的 start。

    切片（L2 用）：`start` / `end` 给出范围时只取**起点**落在范围内的段，段不切开。
    """
    picked = [s for s in segments
              if (start is None or float(s["start"]) >= start)
              and (end is None or float(s["start"]) < end)]

    lines: list[str] = []
    cur: list[dict] = []           # 正在攒的一行
    last_who = None                # 上一行写的是谁——名字只在变化时写

    def flush() -> None:
        nonlocal cur, last_who
        if not cur:
            return
        tag = cur[0].get("speaker") or ""
        who = bare_name(names.get(tag, tag))
        head = f"[{hms(float(cur[0]['start']))}] "
        if who and who != last_who:
            head += f"{who}: "
            last_who = who
        lines.append(head + " ".join(str(s.get("text") or "").strip() for s in cur))
        cur = []

    for s in picked:
        if cur:
            same_win = int(float(cur[0]["start"]) // WINDOW_S) == int(float(s["start"]) // WINDOW_S)
            same_who = (cur[-1].get("speaker") or "") == (s.get("speaker") or "")
            if not (same_win and same_who):
                flush()
        cur.append(s)
    flush()
    return "\n".join(lines) + ("\n" if lines else "")
