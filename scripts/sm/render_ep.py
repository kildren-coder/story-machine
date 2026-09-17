# -*- coding: utf-8 -*-
"""L3 渲染的最简形态：话题表 → EP 笔记里的可跳播大纲（SPEC §5.7）。

这一层不生成文字：标题和 `gist` 是 L1 写的，原样搬。渲染只负责排版和时间戳
（红线 2：渲染不改写整理层的文字）。

标记块规则（§5.7）：`## 整理稿` 连同正文写在 `<!-- digest:auto -->` …
`<!-- /digest -->` 之间，首次插在 `<!-- /speakers -->` 后（没有则 `<!-- /ep -->`
后，再没有则文末），已存在整块替换，**块外一个字节不动**。
"""
from __future__ import annotations

import re
from pathlib import Path

from .note import read_note, set_frontmatter, write_note
from .text import hms, parse_hms

BLOCK_START = "<!-- digest:auto -->"
BLOCK_END = "<!-- /digest -->"
BLOCK_RE = re.compile(re.escape(BLOCK_START) + r".*?" + re.escape(BLOCK_END), re.S)
ANCHORS = ("<!-- /speakers -->", "<!-- /ep -->")


def _span_s(t: dict) -> int:
    """一个话题的秒数；算不出来的当 0。`end` 是 L1 用下一个话题的起点推出来的。"""
    a, b = parse_hms(t.get("start")), parse_hms(t.get("end"))
    return b - a if a is not None and b is not None and b > a else 0


def render_outline(topics: list[dict], version: str, now: str) -> str:
    """`## 整理稿` 那一块的正文（不含标记行，标记由 write_into_note 加）。

    `filler`（答谢礼物、设备测试、纯口播）不渲染：它们没有信息量，占着阅读面
    只会稀释正题。但**段数与合计时长要报出来**——不报的话模型把正题误判成
    `filler`，人在笔记上永远看不见（红线 2 不删事）。
    """
    shown = [t for t in topics if t.get("kind") != "filler"]
    dropped = [t for t in topics if t.get("kind") == "filler"]
    tail = (f"；另有 {len(dropped)} 段杂项未渲染（合计 {hms(sum(_span_s(t) for t in dropped))}）"
            if dropped else "")
    out = [
        "## 整理稿",
        "",
        f"> [!info] 本块由 L3 渲染（整理版本 {version}，生成于 {now}）；"
        f"重跑会覆盖，批注请写在块外{tail}。",
        "",
    ]
    for t in shown:
        # 时间戳写成裸 [HH:MM:SS]，跳播插件才认（ADR 0001）
        aside = " · 旁白" if t.get("kind") == "aside" else ""
        out.append(f"### [{t.get('start', '00:00:00')}] {t.get('title', '')}{aside}")
        out += ["", str(t.get("gist") or ""), ""]
    return "\n".join(out).rstrip("\n") + "\n"


def write_into_note(note_path: str | Path, block_text: str | None, status: str,
                    version: str | None = None) -> list[str]:
    """把块写进笔记并只改 `整理:` / `整理版本:`。返回没写成的 frontmatter 键。

    `block_text` 为 None 时只动 frontmatter（L1 挂了要置 `failed`，但不能留一块
    半成品在人的阅读面上）。
    """
    path = Path(note_path)
    text = read_note(path)

    if block_text is not None:
        # 行尾跟着笔记走：Windows 上 Obsidian 写的是 CRLF，块内混进 LF 等于把
        # 整张笔记的行尾弄花
        nl = "\r\n" if "\r\n" in text else "\n"
        body = block_text.replace("\r\n", "\n").rstrip("\n").replace("\n", nl)
        block = BLOCK_START + nl + body + nl + BLOCK_END
        if BLOCK_RE.search(text):
            text = BLOCK_RE.sub(lambda _: block, text, count=1)
        else:
            text = _insert_block(text, block, nl)

    text, missed = set_frontmatter(text, {"整理": status, "整理版本": version})
    write_note(path, text)
    return missed


def _insert_block(text: str, block: str, nl: str) -> str:
    for anchor in ANCHORS:
        i = text.find(anchor)
        if i < 0:
            continue
        cut = i + len(anchor)
        for eol in ("\r\n", "\n"):                 # 锚点那一行的行尾归锚点
            if text[cut:cut + len(eol)] == eol:
                cut += len(eol)
                break
        return text[:cut] + nl + block + nl + text[cut:]
    # 没有锚点：追加文末。块前补足一个空行，块外的字节照旧
    pad = "" if text.endswith(nl + nl) else (nl if text.endswith(nl) else nl + nl)
    return text + pad + block + nl
