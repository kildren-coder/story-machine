# -*- coding: utf-8 -*-
"""真实 runner 拼出来的命令行（SPEC §4.1）。不发真实调用：`subprocess.run` 换成假的。

两件事各省一类额度：
- `--tools "" --strict-mcp-config --disable-slash-commands`：`--allowedTools ""`
  只禁用不移除，内置工具、MCP、skills 的定义照样进上下文，每次调用白带约
  2.8 万 token（实测 8 行输入一次 $0.077，关掉后 $0.010）。
- `--json-schema`：形状不对由 CLI 在会话里让模型重来，不用把整份输入重发一趟。
"""
from __future__ import annotations

import json
import subprocess

import pytest
from sm import runner as R
from sm.runner import SCHEMA_EXHAUSTED, ClaudeRunner


class FakeProc:
    def __init__(self, stdout: str, returncode: int = 0, stderr: str = ""):
        self.stdout, self.returncode, self.stderr = stdout, returncode, stderr


@pytest.fixture
def argv_of(monkeypatch):
    """跑一次 ClaudeRunner，返回 (argv, 送进 stdin 的文本, 信封)。"""
    def go(stdout: str, returncode: int = 0, schema=None):
        seen = {}

        def fake_run(argv, **kw):
            seen["argv"], seen["input"], seen["cwd"] = argv, kw.get("input"), kw.get("cwd")
            return FakeProc(stdout, returncode)

        monkeypatch.setattr(R.shutil, "which", lambda name: "claude")
        monkeypatch.setattr(subprocess, "run", fake_run)
        env = ClaudeRunner().run("EP91", "L1", "all", "prompts/L1-skeleton.md", "输入正文",
                                 "sonnet", "low", 60, schema=schema)
        return seen["argv"], seen["input"], env
    return go


OK = json.dumps({"type": "result", "is_error": False, "result": "{}"})


def test_no_tool_definitions_ride_along(argv_of):
    argv, stdin, env = argv_of(OK)
    assert argv[:2] == ["claude", "-p"]
    i = argv.index("--tools")
    assert argv[i + 1] == ""                              # 移除全部内置工具，不只是禁用
    assert "--strict-mcp-config" in argv and "--disable-slash-commands" in argv
    assert "--allowedTools" not in argv
    assert "--bare" not in argv                           # 计 API credits 而不是订阅额度
    assert "--json-schema" not in argv                    # 这一层没给 schema 就不带
    assert stdin == "输入正文" and env["result"] == "{}"


def test_schema_is_passed_as_one_json_argument(argv_of):
    schema = {"type": "object", "properties": {"标题": {"type": "string", "pattern": "^[a-z0-9-]+$"}}}
    argv, _, _ = argv_of(OK, schema=schema)
    assert json.loads(argv[argv.index("--json-schema") + 1]) == schema


def test_schema_exhaustion_is_returned_not_raised(argv_of):
    """CLI 这时退出码是 1、信封 `is_error`——照常返回，由 call_layer 走 `_failed/`。"""
    out = json.dumps({"type": "result", "is_error": True, "subtype": SCHEMA_EXHAUSTED,
                      "result": None, "errors": ["after 5 attempts"]})
    _, _, env = argv_of(out, returncode=1, schema={"type": "object"})
    assert env["subtype"] == SCHEMA_EXHAUSTED


def test_other_failures_still_raise(argv_of):
    """环境坏了（退出码非 0、信封不是 JSON、别的 is_error）不是模型答错，照抛。"""
    with pytest.raises(RuntimeError, match="退出码 1"):
        argv_of("", returncode=1)
    with pytest.raises(RuntimeError, match="没给出 JSON"):
        argv_of("这不是 JSON")
    with pytest.raises(RuntimeError, match="claude 报错"):
        argv_of(json.dumps({"is_error": True, "subtype": "error_during_execution", "result": "额度用完"}))
