# -*- coding: utf-8 -*-
"""留档 / 重试 / `_failed/` 与 provenance（issue #51 验收 8、9）。

红线 9 的两半：不过的单元必须留下可复盘的 `_failed/`（含信封），派生文件必须带
§9 那七个键。
"""
from __future__ import annotations

import json

import pytest
from conftest import RAW, RAW_BAD
from sm.pairs import call_layer, retry_input
from sm.paths import VaultPaths
from sm.prov import PROV_KEYS, engine_of, provenance
from sm.runner import FakeRunner, ReplayRunner, extract_json

SPEC_9_KEYS = {"derived_from", "layer", "unit", "engine", "effort",
               "prompt_version", "generated_at"}


def test_retries_then_failed(tmp_path):
    """验收 8：check 恒错 → 调用 retries+1 次 → 写 `_failed/` → 返回 None。"""
    paths = VaultPaths(tmp_path)
    runner = FakeRunner(RAW)
    obj, envelope, errors = call_layer(
        paths, runner, "EP91", "L1", "all", "prompts/L1-skeleton.md", "输入正文",
        lambda o: ["就是不过"], retries=2, log=lambda m: None)

    assert obj is None
    assert len(runner.calls) == 3
    assert errors == ["就是不过"]
    assert envelope["type"] == "result"
    in_md = (paths.pairs("EP91") / "L1-all.in.md").read_bytes().decode("utf-8")
    assert in_md.startswith("输入正文")
    assert "就是不过" in in_md          # 留下的是最后一趟——带着上一趟的错误
    assert (paths.pairs("EP91") / "L1-all.raw.json").exists()
    rec = json.loads((paths.failed("EP91") / "L1-all.failed.json").read_bytes().decode("utf-8"))
    assert rec["attempts"] == 3 and rec["errors"] == ["就是不过"]
    assert rec["envelope"]["session_id"] == envelope["session_id"]   # 信封留着好复盘


def test_passing_check_returns_object(tmp_path):
    paths = VaultPaths(tmp_path)
    runner = FakeRunner(RAW)
    obj, _, errors = call_layer(paths, runner, "EP91", "L1", "all", "p.md", "x",
                                lambda o: [], log=lambda m: None)
    assert errors == [] and obj["ep"] == "EP91"
    assert len(runner.calls) == 1
    assert not (paths.failed("EP91") / "L1-all.failed.json").exists()


def test_runner_errors_are_not_swallowed(tmp_path):
    """信封缺档是环境坏了，不是模型答错——重试没有意义，直接抛。"""
    paths = VaultPaths(tmp_path)
    with pytest.raises(FileNotFoundError):
        call_layer(paths, FakeRunner(RAW), "EP93", "L1", "all", "p.md", "x",
                   lambda o: [], log=lambda m: None)


def test_replay_runner_reads_pairs_and_keeps_the_archive(tmp_path):
    """`_pairs/` 是永久正本：ReplayRunner 跑一遍不许把它重写一遍。"""
    paths = VaultPaths(tmp_path)
    pairs = paths.pairs("EP91")
    pairs.mkdir(parents=True)
    (pairs / "L1-all.raw.json").write_bytes(
        (RAW / "EP91" / "L1-all.raw.json").read_bytes())
    before = (pairs / "L1-all.raw.json").read_bytes()

    obj, _, errors = call_layer(paths, ReplayRunner(tmp_path / "_pairs"), "EP91", "L1",
                               "all", "p.md", "别写进去", lambda o: [], log=lambda m: None)
    assert errors == [] and obj["ep"] == "EP91"
    assert (pairs / "L1-all.raw.json").read_bytes() == before
    assert not (pairs / "L1-all.in.md").exists()


def test_extract_json_shapes():
    """验收 8 后半：围栏、带前言都能取；纯散文抛 ValueError。"""
    fenced = json.loads((RAW / "EP91" / "L1-all.raw.json").read_bytes().decode("utf-8"))
    assert extract_json(fenced["result"])["ep"] == "EP91"

    prose = json.loads((RAW_BAD / "EP91" / "L2-qa.raw.json").read_bytes().decode("utf-8"))
    with pytest.raises(ValueError):
        extract_json(prose["result"])

    assert extract_json('这一集我切成两个话题：\n{"ep": "EP91", "topics": []}\n就这些。'
                        )["topics"] == []
    assert extract_json('{"a": "带 } 的字符串", "b": {"c": 1}}')["b"]["c"] == 1
    with pytest.raises(ValueError):
        extract_json('{"ep": "EP91"')


def test_provenance_keys_are_spec_9():
    """验收 9：字段集合 == §9。"""
    p = provenance(["EP91.transcript.json"], "L1", "all", "claude-sonnet-5", "low",
                   "L1-skeleton@0.1", "2026-03-12T23:10:00+08:00")
    assert set(p) == SPEC_9_KEYS == set(PROV_KEYS)


def test_engine_takes_the_costliest_model():
    """CLI 会顺手起小调用（会话标题之类），按 costUSD 取最大那个才是干活的。"""
    envelope = {"modelUsage": {
        "claude-haiku-4-5": {"costUSD": 0.0004},
        "claude-sonnet-5": {"costUSD": 0.027},
    }}
    assert engine_of(envelope, "sonnet") == "claude-sonnet-5"
    assert engine_of({}, "sonnet") == "sonnet"

    real = json.loads((RAW / "EP91" / "L1-all.raw.json").read_bytes().decode("utf-8"))
    assert engine_of(real, "sonnet") == "claude-sonnet-5"


class ScriptedRunner:
    """按剧本一趟给一个响应，并记下每一趟实际收到的输入。"""

    replay = False

    def __init__(self, results):
        self.results = list(results)
        self.inputs: list[str] = []

    def run(self, scope, layer, unit, prompt_file, input_text, model, effort, timeout):
        self.inputs.append(input_text)
        return {"type": "result", "is_error": False,
                "result": self.results[min(len(self.inputs) - 1, len(self.results) - 1)]}


def test_retry_carries_the_previous_errors(tmp_path):
    """重试要把上一次错在哪带上，不是把同一份输入再掷一次骰子。

    EP02 上 `@0.3` 两次挂在同一个错（整行头被抄进了 `ep`），因为两趟发的输入
    一模一样。而每掷一次要把三小时逐字稿重发一遍，约 2% 的 5h 额度。
    """
    paths = VaultPaths(tmp_path)
    runner = ScriptedRunner(['{"ep": "坏的"}', '{"ep": "EP91"}'])

    def check(obj):
        if obj.get("ep") == "EP91":
            return []
        return ["顶层 `ep` = '坏的'，应该是 'EP91'", "范围起点不早于终点：03:09:00-03:09:00"]

    obj, _, errors = call_layer(paths, runner, "EP91", "L1", "all", "p.md",
                                "逐字稿正文", check, log=lambda m: None)
    assert errors == [] and obj["ep"] == "EP91"
    assert len(runner.inputs) == 2

    first, second = runner.inputs
    assert first == "逐字稿正文"                       # 第一趟一个字不多
    assert second.startswith("逐字稿正文")              # 原材料照旧在最前面
    assert "上一次的输出没通过检查" in second
    assert "顶层 `ep` = '坏的'，应该是 'EP91'" in second
    assert "范围起点不早于终点：03:09:00-03:09:00" in second


def test_in_md_is_the_input_that_actually_produced_the_archived_response(tmp_path):
    """`.in.md` 与 `.raw.json` 是一对：重试过的话，留下的是最后那一趟。"""
    paths = VaultPaths(tmp_path)
    runner = ScriptedRunner(['{"ep": "坏的"}', '{"ep": "EP91"}'])
    call_layer(paths, runner, "EP91", "L1", "all", "p.md", "逐字稿正文",
               lambda o: [] if o.get("ep") == "EP91" else ["不过"], log=lambda m: None)

    in_md = (paths.pairs("EP91") / "L1-all.in.md").read_bytes().decode("utf-8")
    assert in_md == runner.inputs[-1]
    assert "上一次的输出没通过检查" in in_md


def test_retry_block_truncates_a_flood_of_errors(tmp_path):
    """一百条错误不必全附上：附一屏比附一沓管用。"""
    errs = [f"第{n}条错误" for n in range(1, 101)]
    text = retry_input("正文", errs)
    assert "第1条错误" in text and "第10条错误" in text
    assert "第11条错误" not in text
    assert "还有 90 条同类问题" in text
    assert text.startswith("正文")
