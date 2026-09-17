# -*- coding: utf-8 -*-
"""provenance（SPEC §9）与 prompt 版本。

红线 9：每个派生文件都带这七个键。`derived_from` 齐全 + 输入还在 = 可重生成
= 可删，所以这七个键不是装饰，是「删得起」的凭据。
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from .text import sha8

PROV_KEYS = ("derived_from", "layer", "unit", "engine", "effort",
             "prompt_version", "generated_at")


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def provenance(derived_from: list[str], layer: str, unit: str, engine: str,
               effort: str, prompt_version: str, generated_at: str) -> dict:
    return {
        "derived_from": list(derived_from),
        "layer": layer,
        "unit": unit,
        "engine": engine,
        "effort": effort,
        "prompt_version": prompt_version,
        "generated_at": generated_at,
    }


def engine_of(envelope: dict, fallback: str = "") -> str:
    """真正干活的模型名。

    `modelUsage` 里除了干活的模型，还挂着 CLI 自己顺手起的小调用（会话标题
    之类）。按花费取最大那个，才是跑这一层的引擎。
    """
    usage = (envelope or {}).get("modelUsage") or {}
    if not usage:
        return fallback
    return max(usage, key=lambda m: (usage[m] or {}).get("costUSD", 0))


def read_prompt(path: str | Path) -> dict:
    """prompt 首行 `version: <名>@<x.y>`，外加内容 sha8——版本号是人写的，sha8
    是机器算的；两者都进 provenance 才能分清「改了没升版本」。"""
    p = Path(path)
    raw = p.read_bytes()
    first = raw.decode("utf-8").splitlines()[0].strip() if raw else ""
    version = first.split(":", 1)[1].strip() if first.startswith("version:") else "?"
    return {"path": p, "version": version, "sha8": sha8(raw)}
