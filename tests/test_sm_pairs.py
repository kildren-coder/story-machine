# -*- coding: utf-8 -*-
"""留档 / 重试 / `_failed/` 与 provenance（issue #51 验收 8、9）。

红线 9 的两半：不过的单元必须留下可复盘的 `_failed/`（含信封），派生文件必须带
§9 那七个键。
"""
from __future__ import annotations

import json

import pytest
from conftest import RAW, RAW_BAD
from sm.pairs import MAX_PREV_CHARS, call_layer, retry_input
from sm.paths import VaultPaths
from sm.prov import PROV_KEYS, engine_of, provenance
from sm.runner import SCHEMA_EXHAUSTED, FakeRunner, ReplayRunner, extract_json, parse_envelope

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
    assert errors == [] and obj["chapters"][0]["id"] == "bridge"
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
    assert errors == [] and obj["chapters"][0]["id"] == "bridge"
    assert (pairs / "L1-all.raw.json").read_bytes() == before
    assert not (pairs / "L1-all.in.md").exists()


def test_extract_json_shapes():
    """验收 8 后半：围栏、带前言都能取；纯散文抛 ValueError。"""
    fenced = json.loads((RAW_BAD / "EP91" / "L1-all.raw.json").read_bytes().decode("utf-8"))
    assert fenced["result"].startswith("```json")
    assert extract_json(fenced["result"])["chapters"][0]["id"] == "bridge"

    prose = json.loads((RAW_BAD / "EP91" / "L2-bridge.raw.json").read_bytes().decode("utf-8"))
    with pytest.raises(ValueError):
        extract_json(prose["result"])

    assert extract_json('这一集我切成两个话题：\n{"ep": "EP91", "topics": []}\n就这些。'
                        )["topics"] == []
    assert extract_json('{"a": "带 } 的字符串", "b": {"c": 1}}')["b"]["c"] == 1
    with pytest.raises(ValueError):
        extract_json('{"ep": "EP91"')


def test_a_stray_quote_in_a_value_is_escaped_not_rejected():
    """EP02 上 45 轮出现 1 次：`gist` 里冒出 `�">` 三个字符（模型侧的字符毛刺，
    另一轮的标题里也出现过 `阿巴拉契�亚`），整份 JSON 就读不了。那是一个字符
    的事，不该让整集重发一趟——把那个引号转义掉再读，模型写的字一个不动。"""
    raw = ('```json\n{"topics": [\n'
           '  {"id": "a", "title": "第一段", "kind": "talk", "start": "00:00:00",\n'
           '   "who": ["瓜哥"], "gist": "瓜哥讲一位年�">支持民主党的候选人。"},\n'
           '  {"id": "b", "title": "第二段", "kind": "talk", "start": "00:05:00",\n'
           '   "who": ["瓜哥"], "gist": "正常的一条。"}\n'
           ']}\n```')
    obj = extract_json(raw)
    assert [t["id"] for t in obj["topics"]] == ["a", "b"]
    assert obj["topics"][0]["gist"] == '瓜哥讲一位年�">支持民主党的候选人。'   # 原样

    # 野反斜杠（非法转义）翻倍成字面反斜杠
    obj = extract_json('{"gist": "路径 C:\\x 那种"}')
    assert obj["gist"] == "路径 C:\\x 那种"

    # 两个野引号也修得动；纯散文、没闭合的照样拒
    obj = extract_json('{"gist": "他说"好"，然后走了"}')
    assert obj["gist"] == '他说"好"，然后走了'
    with pytest.raises(ValueError):
        extract_json("这里一个 JSON 都没有")
    with pytest.raises(ValueError):
        extract_json('{"gist": "开了引号没关')


def test_a_fullwidth_or_missing_comma_between_objects_is_mended():
    """haiku/high 在 EP01 上把两个话题之间的逗号写成了全角 `}，{`。这个字符在
    字符串外面，换成半角不碰任何内容；漏写逗号同理补上。"""
    obj = extract_json('{"topics": [{"id": "a", "gist": "一，二"}，{"id": "b", "gist": "三"}]}')
    assert [t["id"] for t in obj["topics"]] == ["a", "b"]
    assert obj["topics"][0]["gist"] == "一，二"                    # 字符串里的全角逗号不动
    obj = extract_json('{"topics": [{"id": "a"}\n  {"id": "b"}]}')
    assert [t["id"] for t in obj["topics"]] == ["a", "b"]


def test_structured_output_is_preferred_over_the_result_text():
    """给了 schema 的层，CLI 把过了 schema 的对象放在 `structured_output`。直接用
    它：不必从文字里挖，野引号、围栏、前言这几类解析失败在这条路上不存在。
    没有这个键（旧存档、没给 schema 的层）才退回 `result`。"""
    real = json.loads((RAW / "EP91" / "L1-all.raw.json").read_bytes().decode("utf-8"))
    assert parse_envelope(real)["chapters"][0]["id"] == "bridge"
    assert parse_envelope({"structured_output": {"a": 1}, "result": "这里不是 JSON"}) == {"a": 1}
    assert parse_envelope({"result": '前言\n```json\n{"a": 2}\n```'}) == {"a": 2}
    assert parse_envelope({"structured_output": None, "result": '{"a": 3}'}) == {"a": 3}
    with pytest.raises(ValueError):
        parse_envelope({"result": None})


def test_schema_retries_exhausted_goes_to_failed_not_up_the_stack(tmp_path):
    """模型在会话里连续几次交不出合 schema 的产物时，CLI 退出码 1、信封
    `is_error`。这是模型答错，不是环境坏了：得走 `_failed/` 留档（红线 9），不能
    当异常把整集掀翻。"""
    env = {"type": "result", "is_error": True, "subtype": SCHEMA_EXHAUSTED, "result": None,
           "errors": ["Failed to provide valid structured output after 5 attempts"]}
    with pytest.raises(ValueError, match="after 5 attempts"):
        parse_envelope(env)

    class Exhausted(ScriptedRunner):
        def run(self, *a, schema=None, **kw):
            self.inputs.append(a[4])
            return env

    paths = VaultPaths(tmp_path)
    runner = Exhausted([])
    obj, _, errors = call_layer(paths, runner, "EP91", "L1", "all", "p.md", "正文",
                                lambda o: [], retries=1, log=lambda m: None, schema={"type": "object"})
    assert obj is None and len(runner.inputs) == 2
    assert "交不出合 schema 的产物" in errors[0]
    assert (paths.failed("EP91") / "L1-all.failed.json").exists()
    assert "=== 你上一次的输出 ===" not in runner.inputs[1]       # 没有上一次的输出可附


def test_the_schema_reaches_the_runner(tmp_path):
    paths = VaultPaths(tmp_path)
    runner = ScriptedRunner(['{"ok": true}'])
    schema = {"type": "object", "properties": {"ok": {"type": "boolean"}}}
    call_layer(paths, runner, "EP91", "L1", "all", "p.md", "正文", lambda o: [],
               log=lambda m: None, schema=schema)
    call_layer(paths, runner, "EP91", "L1", "all", "p.md", "正文", lambda o: [],
               log=lambda m: None)
    assert runner.schemas == [schema, None]


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
        self.schemas: list = []

    def run(self, scope, layer, unit, prompt_file, input_text, model, effort, timeout,
            schema=None):
        self.inputs.append(input_text)
        self.schemas.append(schema)
        return {"type": "result", "is_error": False,
                "result": self.results[min(len(self.inputs) - 1, len(self.results) - 1)]}


def test_retry_carries_the_previous_errors(tmp_path):
    """重试要把上一次错在哪带上，不是把同一份输入再掷一次骰子。

    EP02 上 `@0.3` 两次挂在同一个错（整行头被抄进了 `ep`），因为两趟发的输入
    一模一样。而每掷一次要把三小时逐字稿重发一遍，约 2% 的 5h 额度。
    """
    paths = VaultPaths(tmp_path)
    runner = ScriptedRunner(['{"ok": false}', '{"ok": true}'])

    def check(obj):
        if obj.get("ok"):
            return []
        return ["t3: `start` = '00:22:07' 不是逐字稿里出现过的行首时间戳",
                "t7: `id` 重复"]

    obj, _, errors = call_layer(paths, runner, "EP91", "L1", "all", "p.md",
                                "逐字稿正文", check, log=lambda m: None)
    assert errors == [] and obj["ok"] is True
    assert len(runner.inputs) == 2

    first, second = runner.inputs
    assert first == "逐字稿正文"                       # 第一趟一个字不多
    assert second.startswith("逐字稿正文")              # 原材料照旧在最前面
    assert "上面这份输出没通过检查" in second
    assert "不是逐字稿里出现过的行首时间戳" in second
    assert "t7: `id` 重复" in second


def test_retry_carries_the_previous_output_too(tmp_path):
    """光说「错了」不够，要把它自己那份答卷附上。

    不附的话「其余照常」是空话——模型手上只有原材料，只能从头重写，改对这条
    碰坏那条。合成集活体实测：四条错误它改对三条、剩一条原样，进了 `_failed/`。
    """
    paths = VaultPaths(tmp_path)
    runner = ScriptedRunner(['{"ep": "坏的", "topics": ["原样留着的那部分"]}',
                             '{"ep": "EP91"}'])
    call_layer(paths, runner, "EP91", "L1", "all", "p.md", "逐字稿正文",
               lambda o: [] if o.get("ep") == "EP91" else ["不过"], log=lambda m: None)

    second = runner.inputs[1]
    assert "=== 你上一次的输出 ===" in second
    assert '"原样留着的那部分"' in second               # 一字不改地附上
    assert second.index("原样留着的那部分") < second.index("不过")   # 先答卷后批注
    assert "没被点到的地方原样保留" in second


def test_in_md_is_the_input_that_actually_produced_the_archived_response(tmp_path):
    """`.in.md` 与 `.raw.json` 是一对：重试过的话，留下的是最后那一趟。"""
    paths = VaultPaths(tmp_path)
    runner = ScriptedRunner(['{"ep": "坏的"}', '{"ep": "EP91"}'])
    call_layer(paths, runner, "EP91", "L1", "all", "p.md", "逐字稿正文",
               lambda o: [] if o.get("ep") == "EP91" else ["不过"], log=lambda m: None)

    in_md = (paths.pairs("EP91") / "L1-all.in.md").read_bytes().decode("utf-8")
    assert in_md == runner.inputs[-1]
    assert "上面这份输出没通过检查" in in_md


def test_retry_block_truncates_a_flood_of_errors(tmp_path):
    """一百条错误不必全附上：附一屏比附一沓管用。"""
    errs = [f"第{n}条错误" for n in range(1, 101)]
    text = retry_input("正文", errs)
    assert "第1条错误" in text and "第10条错误" in text
    assert "第11条错误" not in text
    assert "还有 90 条同类问题" in text
    assert text.startswith("正文")


def test_an_absurdly_long_previous_output_is_dropped(tmp_path):
    """上一次的输出长到离谱就不带——错误照带，别把这一趟也撑爆。"""
    huge = "x" * (MAX_PREV_CHARS + 1)
    text = retry_input("正文", ["不过"], huge)
    assert "=== 你上一次的输出 ===" not in text
    assert "不过" in text and text.startswith("正文")

    ok = "y" * MAX_PREV_CHARS
    assert "=== 你上一次的输出 ===" in retry_input("正文", ["不过"], ok)
