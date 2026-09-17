# -*- coding: utf-8 -*-
"""L1 的机械检查与 prompt（issue #51 验收 7、12）。

`check_topics` 是红线 9 的入口：它判不过的单元会被拦进 `_failed/`，所以它宁可
啰嗦也不能放水；但它**只判形状**，一个字都不许改（红线 2）。
"""
from __future__ import annotations

import re

from conftest import REPO
from sm.l1 import check_topics
from sm.prov import read_prompt

PROMPT = REPO / "prompts" / "L1-skeleton.md"
DUR = 600          # 10:00 的一集，够摆开空洞 / 重叠 / 越界几种坏法


def topics(*ranges: list) -> dict:
    out = []
    for n, rs in enumerate(ranges, 1):
        out.append({"id": f"t{n}", "title": f"话题{n}", "kind": "talk" if n % 2 else "aside",
                    "ranges": rs, "who": ["阿桥"], "gist": f"概要{n}"})
    return {"ep": "EP91", "topics": out}


def errs(obj, dur: int = DUR) -> str:
    return "\n".join(check_topics(obj, dur, "EP91"))


def test_full_coverage_passes():
    assert check_topics(topics([["00:00:00", "00:05:00"]],
                               [["00:05:00", "00:10:00"]]), DUR, "EP91") == []


def test_three_minute_hole():
    e = errs(topics([["00:00:00", "00:05:00"]], [["00:08:00", "00:10:00"]]))
    assert "空洞" in e and "00:05:00" in e and "00:08:00" in e


def test_one_minute_overlap():
    e = errs(topics([["00:00:00", "00:06:00"]], [["00:05:00", "00:10:00"]]))
    assert "重叠" in e


def test_start_after_end():
    assert "起点不早于终点" in errs(topics([["00:05:00", "00:05:00"]],
                                           [["00:00:00", "00:10:00"]]))


def test_end_past_duration():
    assert "超过时长" in errs(topics([["00:00:00", "00:10:00"]],
                                     [["00:10:00", "00:11:00"]]))


def test_three_second_seam_passes():
    assert check_topics(topics([["00:00:00", "00:04:57"]],
                               [["00:05:00", "00:10:00"]]), DUR, "EP91") == []


def test_hole_at_the_head_and_tail():
    assert "00:00:00 起有空洞" in errs(topics([["00:01:00", "00:10:00"]]))
    assert "还有空洞" in errs(topics([["00:00:00", "00:08:00"]]))


def test_field_and_type_errors():
    obj = topics([["00:00:00", "00:10:00"]])
    t = obj["topics"][0]
    t["id"] = "Bridge Toll"
    t["kind"] = "talking"
    t["who"] = "阿桥"
    del t["gist"]
    e = errs(obj)
    assert "^[a-z0-9-]+$" in e and "`kind`" in e and "`who` 不是字符串数组" in e
    assert "缺字段 `gist`" in e


def test_duplicate_id():
    obj = topics([["00:00:00", "00:05:00"]], [["00:05:00", "00:10:00"]])
    obj["topics"][1]["id"] = obj["topics"][0]["id"]
    assert "`id` 重复" in errs(obj)


def test_wrong_ep_and_shape():
    obj = topics([["00:00:00", "00:10:00"]])
    obj["ep"] = "EP02"
    assert "应该是 'EP91'" in errs(obj)
    assert check_topics([], DUR) == ["顶层不是对象"]
    assert "`topics` 不是非空数组" in "\n".join(check_topics({"ep": "EP91"}, DUR))


def test_prompt_version_and_schema_in_body():
    """验收 12：首行版本号形状 + 正文写清六个键与两种 kind。"""
    text = PROMPT.read_bytes().decode("utf-8")
    first = text.splitlines()[0]
    assert re.match(r"^version: L1-skeleton@\d+\.\d+$", first)
    for key in ("id", "title", "kind", "ranges", "who", "gist", "talk", "aside"):
        assert key in text, key
    assert read_prompt(PROMPT)["version"] == "L1-skeleton@0.1"
    assert len(read_prompt(PROMPT)["sha8"]) == 8
