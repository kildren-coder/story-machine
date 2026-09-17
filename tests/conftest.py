# -*- coding: utf-8 -*-
"""pytest 共用件：让 `scripts/` 可 import，把 fixture vault 拷进临时目录。

**不许写回 `tests/fixtures/`**：每个用例先 copytree 到 tmp_path，跑完随 tmp 一起
扔掉。沙箱里没有真 vault，所有用例的 `--vault` 都显式指向这份副本。
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
FIX = REPO / "tests" / "fixtures"
RAW = FIX / "raw"
RAW_BAD = FIX / "raw-bad"
NOW = "2026-03-12T23:10:00+08:00"          # 固定时钟：重跑要逐字节一致

sys.path.insert(0, str(REPO / "scripts"))

from sm.prov import read_prompt                                    # noqa: E402

# 打磨期 prompt 版本一天能升几次（#57），钉死在这里只会逼人跟着改测试
VERSION = read_prompt(REPO / "prompts" / "L1-skeleton.md")["version"]


@pytest.fixture
def vault(tmp_path) -> Path:
    dst = tmp_path / "vault"
    shutil.copytree(FIX / "vault", dst)
    return dst


def note_path(vault: Path, ep: str) -> Path:
    return sorted((vault / "10-Episodes").glob(f"{ep} *.md"))[0]


def note_text(vault: Path, ep: str) -> str:
    return note_path(vault, ep).read_bytes().decode("utf-8")


def fixture_note_text(ep: str) -> str:
    return sorted((FIX / "vault" / "10-Episodes").glob(f"{ep} *.md"))[0] \
        .read_bytes().decode("utf-8")


def run_ep(vault: Path, ep: str, runner, *extra: str, now: str = NOW) -> int:
    """进程内跑 `digest.py ep`，runner 换成调用方给的那个（`runner.calls` 可数）。"""
    import digest

    real = digest.make_runner
    digest.make_runner = lambda spec: runner
    try:
        return digest.main(["ep", ep, "--vault", str(vault), "--now", now,
                            "--runner", f"fake:{runner.root}", *extra])
    finally:
        digest.make_runner = real
