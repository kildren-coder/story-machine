# -*- coding: utf-8 -*-
"""里程碑 1 行走骨架的端到端用例：逐字稿 → L1 → 话题表 → EP 笔记大纲。

对应 issue #51 验收 1–5、11。全部在 fixture vault 的临时副本上跑，假 runner 读
`tests/fixtures/raw/`，一次真实调用都不发。
"""
from __future__ import annotations

import json
import re

from conftest import FIX, NOW, RAW, RAW_BAD, VERSION, fixture_note_text, note_path, note_text, run_ep
from sm.note import read_frontmatter
from sm.prov import PROV_KEYS
from sm.runner import FakeRunner

BLOCK_RE = re.compile(r"\n<!-- digest:auto -->.*?<!-- /digest -->\n", re.S)
HEAD_RE = re.compile(r"^### \[(\d\d:\d\d:\d\d)\] (.+)$", re.M)


def block_of(text: str) -> str:
    m = re.search(r"<!-- digest:auto -->(.*?)<!-- /digest -->", text, re.S)
    assert m, "笔记里没有标记块"
    return m.group(1)


def without_block(text: str) -> str:
    """去掉整个标记块（连插入时补的那个空行），剩下的应当与原笔记逐字节相同。"""
    return BLOCK_RE.sub("", text, count=1)


def drop_prov(obj: dict) -> dict:
    return {k: v for k, v in obj.items() if k != "provenance"}


def test_ep91_end_to_end(vault):
    """验收 1：三份留档 + 产物 + 笔记块 + frontmatter + 块外字节不动。"""
    runner = FakeRunner(RAW)
    assert run_ep(vault, "EP91", runner) == 0

    assert (vault / "_pairs" / "EP91" / "L1-all.in.md").exists()
    assert (vault / "_pairs" / "EP91" / "L1-all.raw.json").exists()
    got = json.loads((vault / "_digest" / "EP91" / "topics.json").read_bytes().decode("utf-8"))
    want = json.loads((FIX / "digest" / "EP91" / "topics.json").read_bytes().decode("utf-8"))
    assert drop_prov(got) == drop_prov(want)
    assert set(got["provenance"]) == set(PROV_KEYS)

    text = note_text(vault, "EP91")
    # 块紧跟 <!-- /speakers -->：两者之间除了空白什么都没有
    assert re.search(r"<!-- /speakers -->\s*<!-- digest:auto -->", text)
    block = block_of(text)
    heads = HEAD_RE.findall(block)
    assert len(heads) == 4
    assert [h[0] for h in heads] == [t["ranges"][0][0] for t in want["topics"]]
    assert [h[1] for h in heads] == ["开场与设备测试 · 旁白",
                                     "北港大桥收费方案：十五块还是十二块",
                                     "河口夜市搬迁：消防倒逼下的选择",
                                     "结尾弹幕与下周预告 · 旁白"]
    # 大桥那条两段范围都列出来
    assert "范围 [00:03:30]–[00:19:00]、[00:36:00]–[00:41:30]" in block
    assert block.count("范围 ") == 1

    fm = read_frontmatter(text)
    assert fm["整理"] == "done"
    assert fm["整理版本"] == VERSION
    # 红线 7 类比：把块和这两行去掉，人写的每一节逐字节回到原样
    stripped = without_block(text) \
        .replace(f"整理: done\n", "", 1).replace(f"整理版本: {VERSION}\n", "", 1)
    assert stripped == fixture_note_text("EP91")


def test_ep92_pending_flips_in_place(vault):
    """验收 2：已有 `整理: pending` 的那一行原位变 done，其他行不动。"""
    before = note_text(vault, "EP92")
    assert "整理: pending\n" in before
    assert run_ep(vault, "EP92", FakeRunner(RAW)) == 0

    after = note_text(vault, "EP92")
    lines_before, lines_after = before.splitlines(), after.splitlines()
    i = lines_before.index("整理: pending")
    assert lines_after[i] == "整理: done"
    restored = without_block(after) \
        .replace(f"整理版本: {VERSION}\n", "", 1).replace("整理: done\n", "整理: pending\n", 1)
    assert restored == before


def test_rerun_skips_l1_and_force_recalls(vault):
    """验收 3：产物在就不调 runner，笔记逐字节不变；--force 再调一次。"""
    runner = FakeRunner(RAW)
    assert run_ep(vault, "EP91", runner) == 0
    assert len(runner.calls) == 1
    first = note_text(vault, "EP91")

    assert run_ep(vault, "EP91", runner) == 0
    assert len(runner.calls) == 1                      # 第二趟一次都没调
    assert note_text(vault, "EP91") == first

    assert run_ep(vault, "EP91", runner, "--force") == 0
    assert len(runner.calls) == 2
    assert note_text(vault, "EP91") == first           # 同一份响应 + 固定时钟


def test_bad_l1_goes_to_failed(vault):
    """验收 4：覆盖空洞 + 缺 kind → `_failed/`、整理: failed、无块、退出码 1。"""
    runner = FakeRunner(RAW_BAD)
    assert run_ep(vault, "EP91", runner) == 1
    assert len(runner.calls) == 2                      # 默认 retries=1

    failed = vault / "_failed" / "EP91" / "L1-all.failed.json"
    assert failed.exists()
    errs = "\n".join(json.loads(failed.read_bytes().decode("utf-8"))["errors"])
    assert "00:19:00" in errs and "空洞" in errs        # 夜市话题晚开始 3 分钟
    assert "缺字段" in errs and "kind" in errs          # qa 话题没有 kind
    assert not (vault / "_digest" / "EP91" / "topics.json").exists()

    text = note_text(vault, "EP91")
    assert "<!-- digest:auto -->" not in text
    assert read_frontmatter(text)["整理"] == "failed"


def test_missing_transcript_exits_2(vault):
    """验收 5：逐字稿不在就退出码 2，笔记一个字节都不动。"""
    before = note_text(vault, "EP91")
    (vault / "_assets" / "EP91.transcript.json").unlink()
    assert run_ep(vault, "EP91", FakeRunner(RAW)) == 2
    assert note_text(vault, "EP91") == before


def test_block_appended_when_no_anchor(vault):
    """验收 11：既没有 `<!-- /speakers -->` 也没有 `<!-- /ep -->` → 块追加文末。"""
    note_path(vault, "EP91").unlink()
    minimal = ("---\ntype: episode\nepisode: EP91\n主播: [\"阿桥\"]\n---\n\n"
               "# EP91\n\n这一行是人写的，机器不许碰。\n")
    p = vault / "10-Episodes" / "EP91 极简笔记.md"
    p.write_bytes(minimal.encode("utf-8"))

    assert run_ep(vault, "EP91", FakeRunner(RAW)) == 0
    text = p.read_bytes().decode("utf-8")
    assert text.rstrip("\n").endswith("<!-- /digest -->")
    assert "这一行是人写的，机器不许碰。" in text
    stripped = without_block(text) \
        .replace("整理: done\n", "", 1).replace(f"整理版本: {VERSION}\n", "", 1)
    assert stripped == minimal


def test_stdout_says_each_step_and_no_content(vault, capsys):
    """红线 6：日志只报步骤与计数，不把话题标题 / gist 打到终端。"""
    assert run_ep(vault, "EP91", FakeRunner(RAW)) == 0
    out = capsys.readouterr().out
    assert "L1 骨架" in out and "L1 通过：4 个话题" in out
    assert "整理: done" in out
    assert "北港大桥收费方案" not in out
    assert "晚报报道搬滨江路" not in out
    assert NOW in note_text(vault, "EP91")              # 块首行写明生成时间
