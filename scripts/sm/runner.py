# -*- coding: utf-8 -*-
"""无头调用的三种实现（SPEC §4.1）。

一个 `run()` 三种后端：真实 `claude -p`、重放 `_pairs/` 里的原始响应、测试用假
货。层的代码不认识这三者的区别，所以「不烧额度跑一遍全流程」和「真跑」走的是
同一条路径。

信封 = `claude -p --output-format json` 的那个对象。层给了 schema 时 CLI 把产物
放在 `structured_output`（已解析），`parse_envelope` 优先取它；没有就退回 `result`
里的 JSON（允许围栏与前言——旧存档与没给 schema 的层走这条）。**找不到存档一律
抛异常**：静默跳过会让一集悄悄少一层产物（红线 9）。
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Protocol

# `--json-schema` 下模型在会话里重试 5 次仍不合 schema 时，CLI 给的信封 subtype
SCHEMA_EXHAUSTED = "error_max_structured_output_retries"


class Runner(Protocol):
    def run(self, scope: str, layer: str, unit: str, prompt_file: Path,
            input_text: str, model: str, effort: str, timeout: int,
            schema: dict | None = None) -> dict:
        ...


class ClaudeRunner:
    """真实调用。禁 `--bare`（计 API credits 而不是订阅额度，SPEC §2）。"""

    replay = False

    def run(self, scope, layer, unit, prompt_file, input_text, model, effort, timeout,
            schema=None) -> dict:
        exe = shutil.which("claude")
        if not exe:
            raise RuntimeError("PATH 里找不到 claude CLI")
        argv = [
            exe, "-p",
            "--system-prompt-file", str(prompt_file),
            "--model", model,
            "--effort", effort,
            "--output-format", "json",
            # 这些层不需要任何工具。`--allowedTools ""` 只禁用、不移除：内置工具、
            # MCP、skills 的定义照样进上下文，每次调用白带约 2.8 万 token（实测
            # 8 行输入一次 $0.077，三个开关关掉后 $0.010）。L2 一集十几次调用，
            # 这笔固定开销按次数乘
            "--tools", "",
            "--strict-mcp-config",
            "--disable-slash-commands",
        ]
        if schema is not None:
            # 产物形状交给 CLI 把关：字段、类型、枚举不对它自己在会话里重来，
            # 不用我们把整份输入重发一趟。代价是多一轮（按缓存价重读一遍输入）
            argv += ["--json-schema", json.dumps(schema, ensure_ascii=False)]
        # cwd 放空目录：躲开 CLAUDE.md 自动发现，别让项目指令混进这一层的上下文
        with tempfile.TemporaryDirectory(prefix="sm-run-") as cwd:
            p = subprocess.run(argv, input=input_text, cwd=cwd, timeout=timeout,
                               capture_output=True, text=True, encoding="utf-8",
                               errors="replace")
        try:
            env = json.loads(p.stdout)
        except json.JSONDecodeError:
            env = None
        # schema 重试用尽（CLI 在会话里自己重来了 5 次还不合）：退出码 1、信封
        # `is_error`——但这是模型答错，不是环境坏了，得走 `_failed/` 那条路留档，
        # 不能当异常抛出去把整集掀翻
        if isinstance(env, dict) and env.get("subtype") == SCHEMA_EXHAUSTED:
            return env
        if p.returncode != 0:
            raise RuntimeError(f"claude 退出码 {p.returncode}: {(p.stderr or '')[:500]}")
        if env is None:
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

    def run(self, scope, layer, unit, prompt_file, input_text, model, effort, timeout,
            schema=None) -> dict:
        p = self.path_for(scope, layer, unit)
        if not p.exists():
            raise FileNotFoundError(f"{type(self).__name__} 找不到存档响应：{p}")
        self.calls.append((scope, layer, unit))
        env = json.loads(p.read_bytes().decode("utf-8"))
        if env.get("is_error") and env.get("subtype") != SCHEMA_EXHAUSTED:
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


MAX_JSON_REPAIRS = 30


def parse_envelope(env: dict) -> dict:
    """信封 → 产物对象。读不出来抛 ValueError（调用方当检查不过处理）。

    给了 schema 的层，CLI 把过了 schema 的对象放在 `structured_output`，直接用；
    `result` 里同一份 JSON 字符串留着给重试时附回去。没有这个键（旧存档、没给
    schema 的层、fixture）就退回去从 `result` 的文字里挖。
    """
    if env.get("subtype") == SCHEMA_EXHAUSTED:
        why = "；".join(str(e) for e in (env.get("errors") or [])) or "CLI 没说原因"
        raise ValueError(f"模型连续几次都交不出合 schema 的产物：{why[:400]}")
    got = env.get("structured_output")
    if isinstance(got, dict):
        return got
    return extract_json(env.get("result") or "")


def extract_json(raw: str) -> dict:
    """从模型回答里挖出那个 JSON 对象。它可能裹在 ``` 里或带前言。

    字符串值里混进一个野引号或野反斜杠时（EP02 上 45 轮出现 1 次：`gist` 里
    冒出 `�">` 三个字符），整份 JSON 就解析不了。那是一个字符的事，不该让整集
    重发一趟：`_loads_repairing` 把那个引号转义掉再读，模型写的字一个不动。
    """
    s = (raw or "").strip()
    fence = re.search(r"```(?:json)?\s*(.+?)```", s, re.S)
    if fence:
        s = fence.group(1).strip()
    start = s.find("{")
    if start < 0:
        raise ValueError("响应里没有 JSON 对象")
    body = _balanced(s, start)
    if body is not None:
        try:
            return json.loads(body)
        except json.JSONDecodeError:
            pass
    # 括号配平失败多半是野引号把字符串的开合搞反了：退回到「最后一个 }」再修
    end = s.rfind("}")
    if end <= start:
        raise ValueError("JSON 对象没有闭合")
    return _loads_repairing(s[start:end + 1])


def _balanced(s: str, start: int) -> str | None:
    """从 `start` 起按括号深度找到那个对象的闭合处；找不到返回 None。"""
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
                return s[start:idx + 1]
    return None


def _loads_repairing(text: str) -> dict:
    """反复读；每次读不过，就把出错点前最近的那个引号转义掉（或把非法反斜杠
    翻倍）再试。修不动（出错点不再前进）就把最后一次的错抛出去。"""
    last_pos = -1
    for _ in range(MAX_JSON_REPAIRS):
        try:
            return json.loads(text)
        except json.JSONDecodeError as e:
            if e.pos <= last_pos:
                raise ValueError(f"JSON 修不好：{e.msg}（第 {e.lineno} 行）") from e
            last_pos = e.pos
            here = text[e.pos] if e.pos < len(text) else ""
            if e.msg.startswith("Invalid \\escape") and here == "\\":
                text = text[:e.pos] + "\\\\" + text[e.pos + 1:]
                continue
            prev = text[:e.pos].rstrip()[-1:]
            if e.msg.startswith("Expecting ',' delimiter") and prev in "}]":
                # 紧跟在 } 或 ] 后面的才算结构位置：对象之间写了全角逗号（haiku
                # 写过 `}，{`）或干脆漏了逗号——都在字符串外面，改它不碰内容。
                # 跟在引号后面的不算：那多半是野引号把字符串提前截断了
                if here == "，":
                    text = text[:e.pos] + "," + text[e.pos + 1:]
                    continue
                if here in "{[":
                    text = text[:e.pos] + "," + text[e.pos:]
                    continue
            q = text.rfind('"', 0, e.pos)
            if q <= 0:
                raise ValueError(f"JSON 修不好：{e.msg}（第 {e.lineno} 行）") from e
            text = text[:q] + '\\"' + text[q + 1:]
    raise ValueError("JSON 修不好：野引号太多")
