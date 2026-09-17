# -*- coding: utf-8 -*-
"""留档 / 重试 / `_failed/` 与 provenance（issue #51 验收 8、9）。

红线 9 的两半：不过的单元必须留下可复盘的 `_failed/`（含信封），派生文件必须带
§9 那七个键。
"""
from __future__ import annotations

import json

import pytest
from conftest import RAW, RAW_BAD
from sm.pairs import call_layer
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
    assert (paths.pairs("EP91") / "L1-all.in.md").read_bytes().decode("utf-8") == "输入正文"
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
