# -*- coding: utf-8 -*-
"""L3 渲染：话题表 + 片段 → EP 笔记里的整理稿（SPEC §5.7）。

这一层不生成文字：段落、锚点、说法、信源都是 L2 写的，原样搬。渲染只负责排版、
把 §5.9 的三种标记换成 Obsidian 认的写法（红线 5：核查与渲染不改整理层的字）。

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
WHO_RE = re.compile(r"<who>(.*?)</who>", re.S)
HEDGE_RE = re.compile(r"<hedge>(.*?)</hedge>", re.S)
CHANNEL_HEAD = ("| 信源 | 类型 | 谁 | 时间戳 | 原话 |", "| --- | --- | --- | --- | --- |")


def render_para(text: str) -> str:
    """§5.9 的标记 → 笔记里的写法：`<who>` 变粗体小标，`<hedge>` 变下划线。

    除这两样之外一个字节不动——时间戳照旧是裸 `[HH:MM:SS]`（跳播插件才认，
    ADR 0001），段文本逐字进笔记（红线 5）。
    """
    return HEDGE_RE.sub(lambda m: f"<u>{m.group(1)}</u>",
                        WHO_RE.sub(lambda m: f"**{m.group(1)}**", str(text or "")))


def render_digest(topics: list[dict], frags: dict, version: str, now: str) -> str:
    """`## 整理稿` 那一块的正文（不含标记行，标记由 write_into_note 加）。

    **按话题出节**，不按章：章只是 L2 的调用单位，人读的是话题。`talk` 出五类
    内容，`aside` 只出 `paras`（多写的锚点留在片段里，不渲染），`filler` 整个
    不渲染——但**段数与合计时长报在块首行**：不报的话，模型把正题误判成 `filler`
    时人在笔记上再也看不见它（红线 9 的阅读面形态）。
    """
    shown = [t for t in topics if t.get("kind") != "filler"]
    hidden = [t for t in topics if t.get("kind") == "filler"]
    head = (f"> [!info] 本块由 L3 渲染（整理版本 {version}，生成于 {now}）；"
            f"重跑会覆盖，批注请写在块外。")
    if hidden:
        total = sum(max(0, (parse_hms(t.get("end")) or 0) - (parse_hms(t.get("start")) or 0))
                    for t in hidden)
        head += f"另有 {len(hidden)} 段杂项未渲染（合计 {hms(total)}）。"

    out = ["## 整理稿", "", head, ""]
    for t in shown:
        frag = frags.get(t.get("id")) or {}
        title = str(t.get("title") or "")
        if t.get("kind") == "aside":
            title += " · 旁白"
        out.append(f"### [{t.get('start', '00:00:00')}] {title}")
        out.append("")
        for para in frag.get("paras") or []:
            out += [render_para(para), ""]
        if t.get("kind") == "aside":
            continue
        out += _section("原话锚点", frag.get("quotes"),
                        lambda q: f"- [{q.get('ts', '')}] {q.get('who', '')}："
                                  f"「{q.get('text', '')}」")
        out += _section("可核查的说法", frag.get("claims"),
                        lambda c: f"- [{c.get('ts', '')}] {c.get('who', '')}：{c.get('claim', '')}")
        out += _section("提到的信源", frag.get("channels"),
                        lambda c: f"| {c.get('name', '')} | {c.get('kind', '')} | "
                                  f"{c.get('who', '')} | [{c.get('ts', '')}] | "
                                  f"{c.get('quote', '')} |",
                        head=CHANNEL_HEAD)
        out += _section("疑似 ASR 生音", frag.get("asr"),
                        lambda a: f"- 听成「{a.get('heard', '')}」→ 应为「{a.get('means', '')}」")
    return "\n".join(out).rstrip("\n") + "\n"


def _section(title: str, rows, line, head: tuple = ()) -> list[str]:
    """一个小节。空的不出标题——`talk` 话题里没有信源是常事，留个空标题只是噪音。"""
    if not rows:
        return []
    return [f"**{title}**", "", *head, *(line(r) for r in rows), ""]


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
