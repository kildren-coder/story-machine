# -*- coding: utf-8 -*-
"""一层一个单元的调用：三份留档 + 重试 + `_failed/`（SPEC §4.1，红线 9）。

三份留档里这里负责前两份：原样输入 `.in.md`、原始响应 `.raw.json`（都在
`_pairs/<scope>/`，永久）。第三份是解析后产物，形状归层自己（`_digest/`）。

**绝不静默**：检查不过就重试，重试到上限还不过就把错误和信封一起落
`_failed/<scope>/<层>-<单元>.failed.json` 并返回 None，由调用方决定怎么报警。

**重试要把上一次的错误带上**。发一模一样的输入不叫重试，叫重掷骰子：EP02 上
`@0.3` 两次挂在同一个错（把整行头抄进了 `ep`），而每掷一次要把三小时逐字稿
重发一遍。实测五次跑里四次第一发不过，全是机械格式错——范围倒置、引号没转义、
字段抄错、零长度范围——这类错误附上原话几乎必然一次改对。

带错误还不够，**上一次的输出也要带上**，否则模型是在空白纸上重写，改对这条碰坏
那条。见 `retry_input`。
"""
from __future__ import annotations

import json
from pathlib import Path

from .prov import now_iso
from .runner import extract_json


MAX_RETRY_ERRORS = 10        # 错误太多时只带前几条：附一屏比附一沓管用

MAX_PREV_CHARS = 120_000     # 上一次的输出长到离谱就不带，只带错误

RETRY_PREV = """

=== 你上一次的输出 ===

"""

RETRY_HEAD = """

=== 上面这份输出没通过检查 ===

原材料一个字没变。上一次的输出有下面这些问题：

"""

RETRY_TAIL_WITH_PREV = """

在上一次输出的基础上改掉这些问题，没被点到的地方原样保留。
重新输出完整结果，不要解释你改了什么。
"""

RETRY_TAIL = """

重新输出完整结果，不要解释你改了什么。
"""


def retry_input(input_text: str, errors: list[str], prev: str | None = None) -> str:
    """原输入 + 上一次的输出 + 一段「错在哪」。每次都从原输入拼，错误不累积。

    **上一次的输出必须带上**。不带的话「其余照常」是句空话——模型手上只有原材料
    和一句「你错了」，只能从头重写一遍，改对这条往往碰坏那条：合成集实测，四条
    错误里它改对三条、剩一条原样，直接进了 `_failed/`。带上之后是在自己的答卷上
    改，没被点到的地方留得住。JSON 崩了的那类更是只有带上才修得了——「line 67
    column 104」离开原文毫无意义。
    """
    shown = errors[:MAX_RETRY_ERRORS]
    lines = [f"- {e}" for e in shown]
    if len(errors) > len(shown):
        lines.append(f"- （还有 {len(errors) - len(shown)} 条同类问题，一并改掉）")
    body = input_text.rstrip()
    tail = RETRY_TAIL
    if prev and len(prev) <= MAX_PREV_CHARS:
        body += RETRY_PREV + prev.strip()
        tail = RETRY_TAIL_WITH_PREV
    return body + RETRY_HEAD + "\n".join(lines) + tail


def _write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes((json.dumps(obj, ensure_ascii=False, indent=1) + "\n").encode("utf-8"))


def call_layer(paths, runner, scope: str, layer: str, unit: str, prompt_file: Path,
               input_text: str, check, *, retries: int = 1, model: str = "sonnet",
               effort: str = "low", timeout: int = 1800, log=print,
               generated_at: str | None = None) -> tuple[dict | None, dict, list[str]]:
    """`.in.md` → runner → `.raw.json` → extract_json → check。

    `check(obj) -> [错误…]`；空列表算过。返回 (产物 | None, 最后一个信封, 错误)。
    runner 自己抛的异常（CLI 不在、退出码非 0、信封不是 JSON、is_error）**不吞**
    ——那是环境坏了，不是模型答错，重试没有意义。
    """
    pairs = paths.pairs(scope)
    pairs.mkdir(parents=True, exist_ok=True)
    in_path = pairs / f"{layer}-{unit}.in.md"
    raw_path = pairs / f"{layer}-{unit}.raw.json"
    archived = getattr(runner, "replay", False)      # 重放时那两份就是正本，别重写

    obj: dict | None = None
    envelope: dict = {}
    errors: list[str] = []
    text = input_text
    for attempt in range(1, retries + 2):
        # 每一趟都把这一趟实际发出去的输入落盘：`.in.md` 与 `.raw.json` 是一对，
        # 两端必须对得上（重试过的话，留下的就是最后那一趟）
        if not archived:
            in_path.write_bytes(text.encode("utf-8"))
        log(f"    {layer}-{unit} 第 {attempt} 次调用（{model} / effort {effort}）…")
        envelope = runner.run(scope, layer, unit, prompt_file, text,
                              model, effort, timeout)
        if not archived:
            _write_json(raw_path, envelope)
        try:
            obj = extract_json(envelope.get("result", ""))
            errors = list(check(obj))
        except (ValueError, json.JSONDecodeError) as e:
            obj, errors = None, [f"响应不是合法 JSON：{e}"]
        if not errors:
            return obj, envelope, []
        log(f"    {layer}-{unit} 检查不过（{len(errors)} 项）：{errors[0]}")
        obj = None
        text = retry_input(input_text, errors, envelope.get("result", ""))

    failed = paths.failed(scope) / f"{layer}-{unit}.failed.json"
    _write_json(failed, {
        "scope": scope, "layer": layer, "unit": unit,
        "attempts": retries + 1,
        "failed_at": generated_at or now_iso(),
        "errors": errors,
        "envelope": envelope,
    })
    log(f"    ⚠ {layer}-{unit} 重试 {retries} 次仍不过 → {failed}（不静默丢单元）")
    return None, envelope, errors
