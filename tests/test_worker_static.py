# -*- coding: utf-8 -*-
"""worker.ps1 的静态检查（issue #51 验收 13）。

沙箱里没有 PowerShell，`-Extract` 只能这样验：读源码确认它转交的是
`digest.py ep`，`-Redo` 映射到 `--force`，仓库里再没有 stage12 的残留。
真跑归人（见 docs/qa/issue-51.md 的「真实样例验证指引」）。
"""
from __future__ import annotations

import re

from conftest import REPO

WORKER = (REPO / "scripts" / "worker.ps1").read_bytes().decode("utf-8")
# 验收 13 点名的搜索面：ADR 是历史记录，不在其中（stage12 曾经存在这件事不许抹）
GREP_PATHS = ("scripts", "docs/agents", "SPEC.md", "CLAUDE.md", "CONTEXT.md",
              ".sandcastle/prompts")


def extract_body() -> str:
    m = re.search(r"function Invoke-Extract \{(.*?)\n\}", WORKER, re.S)
    assert m, "worker.ps1 里找不到 Invoke-Extract"
    return m.group(1)


def test_extract_hands_off_to_digest_py():
    body = extract_body()
    assert "$DigestScript" in body
    assert re.search(r"\$DigestScript\s*=\s*Join-Path \$PSScriptRoot \"digest\.py\"", WORKER)
    argv = re.search(r"\$argv = @\((.*?)\)", body).group(1)
    assert "$DigestScript" in argv and "'ep'" in argv and "$Ep" in argv
    assert "'--vault', $Vault" in argv


def test_redo_maps_to_force():
    body = extract_body()
    assert re.search(r"if \(\$Again\) \{ \$argv \+= '--force' \}", body)
    assert "Invoke-Extract -Ep $Extract -Again:$Redo" in WORKER


def test_done_message_mentions_the_visible_change():
    """L2 上线后笔记里那块是整理稿，不再是大纲——完成提示得说人真能看到的东西。"""
    assert "整理稿已写进 EP 笔记" in extract_body()


def test_stage12_is_gone():
    assert not (REPO / "scripts" / "stage12.py").exists()
    assert not (REPO / "scripts" / "test_stage12.py").exists()
    hits = []
    for rel in GREP_PATHS:
        p = REPO / rel
        files = [p] if p.is_file() else sorted(x for x in p.rglob("*") if x.is_file())
        for f in files:
            try:
                text = f.read_bytes().decode("utf-8")
            except UnicodeDecodeError:
                continue
            hits += [f"{f.relative_to(REPO)}:{n}" for n, line in enumerate(text.splitlines(), 1)
                     if "stage12" in line]
    assert hits == []
