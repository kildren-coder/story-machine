# -*- coding: utf-8 -*-
"""一层一个单元的调用：三份留档 + 重试 + `_failed/`（SPEC §4.1，红线 9）。

三份留档里这里负责前两份：原样输入 `.in.md`、原始响应 `.raw.json`（都在
`_pairs/<scope>/`，永久）。第三份是解析后产物，形状归层自己（`_digest/`）。

**绝不静默**：检查不过就重试，重试到上限还不过就把错误和信封一起落
`_failed/<scope>/<层>-<单元>.failed.json` 并返回 None，由调用方决定怎么报警。
"""
from __future__ import annotations

import json
from pathlib import Path

from .prov import now_iso
from .runner import extract_json


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

    if not archived:
        in_path.write_bytes(input_text.encode("utf-8"))

    obj: dict | None = None
    envelope: dict = {}
    errors: list[str] = []
    for attempt in range(1, retries + 2):
        log(f"    {layer}-{unit} 第 {attempt} 次调用（{model} / effort {effort}）…")
        envelope = runner.run(scope, layer, unit, prompt_file, input_text,
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
