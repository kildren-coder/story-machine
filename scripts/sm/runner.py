# -*- coding: utf-8 -*-
"""无头调用的三种实现（SPEC §4.1）。

一个 `run()` 三种后端：真实 `claude -p`、重放 `_pairs/` 里的原始响应、测试用假
货。层的代码不认识这三者的区别，所以「不烧额度跑一遍全流程」和「真跑」走的是
同一条路径。

信封 = `claude -p --output-format json` 的那个对象；解析产物是它 `result` 里的
JSON（允许围栏与前言）。**找不到存档一律抛异常**：静默跳过会让一集悄悄少一层
产物（红线 9）。
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Protocol


class Runner(Protocol):
    def run(self, scope: str, layer: str, unit: str, prompt_file: Path,
            input_text: str, model: str, effort: str, timeout: int) -> dict:
        ...


class ClaudeRunner:
    """真实调用。禁 `--bare`（计 API credits 而不是订阅额度，SPEC §2）。"""

    replay = False

    def run(self, scope, layer, unit, prompt_file, input_text, model, effort, timeout) -> dict:
        exe = shutil.which("claude")
        if not exe:
            raise RuntimeError("PATH 里找不到 claude CLI")
        argv = [
            exe, "-p",
            "--system-prompt-file", str(prompt_file),
            "--model", model,
            "--effort", effort,
            "--output-format", "json",
            # 这些层不需要任何工具。禁掉可消掉「agent 跑去读文件」整类失败模式
            "--allowedTools", "",
        ]
        # cwd 放空目录：躲开 CLAUDE.md 自动发现，别让项目指令混进这一层的上下文
        with tempfile.TemporaryDirectory(prefix="sm-run-") as cwd:
            p = subprocess.run(argv, input=input_text, cwd=cwd, timeout=timeout,
                               capture_output=True, text=True, encoding="utf-8",
                               errors="replace")
        if p.returncode != 0:
            raise RuntimeError(f"claude 退出码 {p.returncode}: {(p.stderr or '')[:500]}")
        try:
            env = json.loads(p.stdout)
        except json.JSONDecodeError:
            raise RuntimeError(f"claude 的 --output-format json 没给出 JSON: {p.stdout[:300]}")
        if env.get("is_error"):
            raise RuntimeError(f"claude 报错: {str(env.get('result'))[:500]}")
        return env


class _ArchiveRunner:
    """从 `<root>/<scope>/<层>-<单元>.raw.json` 取信封。"""

    replay = False

    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.calls: list[tuple[str, str, str]] = []

    def path_for(self, scope: str, layer: str, unit: str) -> Path:
        return self.root / scope / f"{layer}-{unit}.raw.json"

    def run(self, scope, layer, unit, prompt_file, input_text, model, effort, timeout) -> dict:
        p = self.path_for(scope, layer, unit)
        if not p.exists():
            raise FileNotFoundError(f"{type(self).__name__} 找不到存档响应：{p}")
        self.calls.append((scope, layer, unit))
        env = json.loads(p.read_bytes().decode("utf-8"))
        if env.get("is_error"):
            raise RuntimeError(f"存档响应本身是错误信封：{str(env.get('result'))[:200]}")
        return env


class ReplayRunner(_ArchiveRunner):
    """`--replay`：读 vault 的 `_pairs/`，免额度重跑闸门与渲染。

    `replay = True` 让 pairs.call_layer 别把 `.in.md` / `.raw.json` 重写一遍——
    那两份是永久正本（SPEC §9）。
    """

    replay = True

    def __init__(self, pairs_dir: str | Path):
        super().__init__(pairs_dir)


class FakeRunner(_ArchiveRunner):
    """测试用：读 `tests/fixtures/raw/<scope>/<层>-<单元>.raw.json`。"""


def extract_json(raw: str) -> dict:
    """从模型回答里挖出那个 JSON 对象。它可能裹在 ``` 里或带前言。"""
    s = (raw or "").strip()
    fence = re.search(r"```(?:json)?\s*(.+?)```", s, re.S)
    if fence:
        s = fence.group(1).strip()
    start = s.find("{")
    if start < 0:
        raise ValueError("响应里没有 JSON 对象")
    depth, in_str, esc = 0, False, False
    for idx in range(start, len(s)):
        ch = s[idx]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return json.loads(s[start:idx + 1])
    raise ValueError("JSON 对象没有闭合")
