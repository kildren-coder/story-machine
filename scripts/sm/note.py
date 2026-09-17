# -*- coding: utf-8 -*-
"""EP 笔记：读 frontmatter 与点名，只改 frontmatter 的指定键。

笔记是人的地盘（红线 7 类比）：读进来、写回去必须逐字节保真。所以这里一律走
bytes，不用 `Path.read_text()`——它的 universal newlines 会把 Windows 上 Obsidian
写的 CRLF 悄悄换成 LF，等于把整张笔记改了一遍。
"""
from __future__ import annotations

import re
from pathlib import Path

FM_RE = re.compile(r"\A﻿?---\r?\n(.*?)\r?\n---\r?\n", re.S)
SPK_LINE_RE = re.compile(r"\[(SPEAKER_\d+)::\s*([^\]]*)\]")
ROLE_SUFFIX_RE = re.compile(r"（(?:主播|嘉宾)）$")


def read_note(path: str | Path) -> str:
    """原样读（不做行尾转换，BOM 留着）。"""
    return Path(path).read_bytes().decode("utf-8")


def write_note(path: str | Path, text: str) -> None:
    Path(path).write_bytes(text.encode("utf-8"))


def read_frontmatter(text: str) -> dict:
    """够用就行的 YAML 子集：单行 key: value，值支持 [..] 列表和引号。"""
    m = FM_RE.match(text)
    if not m:
        return {}
    out = {}
    for line in m.group(1).splitlines():
        kv = re.match(r"^([^:#\s][^:]*):\s*(.*)$", line)
        if not kv:
            continue
        k, v = kv.group(1).strip(), kv.group(2).strip()
        if v.startswith("[") and v.endswith("]"):
            inner = v[1:-1].strip()
            v = [x.strip().strip('"').strip("'") for x in inner.split(",")] if inner else []
        else:
            v = v.strip('"').strip("'")
        out[k] = v
    return out


def read_speakers(note_text: str, fm: dict) -> dict:
    """SPEAKER_XX → 「名字（角色）」。名字取自笔记里人点过的方括号，角色取自
    frontmatter 的 主播/嘉宾。点不出来的不进这张表——不许编（SPEC 阶段 0）。"""
    hosts = set(fm.get("主播") or [])
    guests = set(fm.get("嘉宾") or [])
    out = {}
    for tag, raw in SPK_LINE_RE.findall(note_text):
        name = (raw or "").strip()
        if not name:
            continue
        # 首次登记允许写「老周 嘉宾」，取第一段当名字
        name = name.split()[0]
        role = "主播" if name in hosts else "嘉宾" if name in guests else None
        out[tag] = f"{name}（{role}）" if role else name
    return out


def bare_name(name: str) -> str:
    """「阿桥（主播）」→「阿桥」。角色只在块头里报一次，逐字稿行首只用名字。"""
    return ROLE_SUFFIX_RE.sub("", str(name or ""))


def set_frontmatter(text: str, updates: dict) -> tuple[str, list[str]]:
    """只改 `updates` 里这几个键，其余键、顺序、正文一个字节不动。

    值为 None 的键跳过（本层没有可写的值时别留半截字段）。键不存在就新增在
    frontmatter 末尾。返回 (新文本, 没写成的键)——没有 frontmatter 时不硬造一个，
    把键退回给调用方去报警（绝不静默）。
    """
    todo = {k: v for k, v in updates.items() if v is not None}
    if not todo:
        return text, []
    m = FM_RE.match(text)
    if not m:
        return text, list(todo)

    block = m.group(1)
    nl = "\r\n" if "\r\n" in m.group(0) else "\n"
    lines = block.split("\n")
    for key, value in list(todo.items()):
        for i, line in enumerate(lines):
            if re.match(rf"^{re.escape(key)}\s*:", line.rstrip("\r")):
                cr = "\r" if line.endswith("\r") else ""
                lines[i] = f"{key}: {value}{cr}"
                del todo[key]
                break
    for key, value in todo.items():
        tail = "\r" if nl == "\r\n" else ""
        lines.append(f"{key}: {value}{tail}")
    new_block = "\n".join(lines)
    return text[:m.start(1)] + new_block + text[m.end(1):], []
