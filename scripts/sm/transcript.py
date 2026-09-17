# -*- coding: utf-8 -*-
"""逐字稿正本（SPEC §5.1）→ 喂给模型的文本（SPEC §5.2）。

红线 1 / 2 的形态：这里只**拼**，不改一个字。段文本原样进行，行首那截
`12 [HH:MM:SS] 名字: ` 是代码加的脚手架，闸门匹配原文时要先去掉（见 text.norm）。

**行号是全集统一的**：行表只看整集的段怎么落进 30 秒窗、说话人在哪换，跟切片
从哪开始无关。L1 看到的第 57 行和 L2 在切片里看到的第 57 行是同一行——模型
用行号指位置，代码用同一张表把行号换回时刻（`line_t`）。
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


def build_lines(segments: list[dict]) -> list[dict]:
    """整集的行表：`[{"n", "t", "tag", "text"}]`，`n` 从 1 起。

    窗内同人连成一行（段间一个空格），说话人变化另起一行。`t` 是该行第一段的
    start 取整秒——和行首印出来的 `[HH:MM:SS]` 是同一个数，所以「行号 → 时刻」
    与「时刻落在哪个范围」两头用的是同一把尺，不会出现某行被自己的章节漏掉。
    """
    lines: list[dict] = []
    cur: list[dict] = []

    def flush() -> None:
        nonlocal cur
        if not cur:
            return
        lines.append({"n": len(lines) + 1,
                      "t": int(round(float(cur[0]["start"]))),
                      "tag": cur[0].get("speaker") or "",
                      "text": " ".join(str(s.get("text") or "").strip() for s in cur)})
        cur = []

    for s in segments:
        if cur:
            same_win = int(float(cur[0]["start"]) // WINDOW_S) == int(float(s["start"]) // WINDOW_S)
            same_who = (cur[-1].get("speaker") or "") == (s.get("speaker") or "")
            if not (same_win and same_who):
                flush()
        cur.append(s)
    flush()
    return lines


def line_t(lines: list[dict], n: int) -> int | None:
    """第 `n` 行的起点（秒）。行号不在表里返回 None。"""
    return lines[n - 1]["t"] if isinstance(n, int) and 1 <= n <= len(lines) else None


def pick_lines(lines: list[dict], start: float | None = None,
               end: float | None = None) -> list[dict]:
    """起点落在 `[start, end)` 里的行。行不切开。"""
    return [ln for ln in lines
            if (start is None or ln["t"] >= start) and (end is None or ln["t"] < end)]


def format_lines(lines: list[dict], names: dict) -> str:
    """一组行 → §5.2 文本：`行号 [HH:MM:SS] 名字: 文本`，名字只在变化时写
    （这一组的第一行总是写）。"""
    out: list[str] = []
    last_who = None
    for ln in lines:
        who = bare_name(names.get(ln["tag"], ln["tag"]))
        head = f"{ln['n']} [{hms(ln['t'])}] "
        if who and who != last_who:
            head += f"{who}: "
            last_who = who
        out.append(head + ln["text"])
    return "\n".join(out) + ("\n" if out else "")


def render_lines(segments: list[dict], names: dict, start: float | None = None,
                 end: float | None = None) -> str:
    """§5.2 文本。给了 `start` / `end` 就只出起点落在范围里的行，行号照旧是全集的。"""
    return format_lines(pick_lines(build_lines(segments), start, end), names)
