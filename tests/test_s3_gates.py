# -*- coding: utf-8 -*-
"""L3 闸门的端到端用例：跑完一集之后，`gates.json`、写回的片段、笔记三处对得上。

对应 issue #53 验收 1、2、5 与 #83 验收 1、2、3、6。全部在 fixture vault 的临时
副本上跑，假 runner 读 `tests/fixtures/raw/`，一次真实调用都不发。

块解析那几个小工具跟 #52 的用例共用一份（`test_s2_topics`），免得两边漂。
"""
from __future__ import annotations

import json
import shutil

from conftest import FIX, RAW, note_text, run_ep
from sm.runner import FakeRunner
from sm.text import norm
from test_s2_topics import block_of, digest, rows_under, sections


def transcript_segments(vault) -> list[dict]:
    data = json.loads((vault / "_assets" / "EP91.transcript.json").read_bytes().decode("utf-8"))
    return data["segments"]


def strings(obj, skip: tuple = ()) -> list[str]:
    """递归捞出所有字符串**值**（键不算），`skip` 里的键跳过。"""
    if isinstance(obj, str):
        return [obj]
    if isinstance(obj, dict):
        return [s for k, v in obj.items() if k not in skip for s in strings(v, skip)]
    if isinstance(obj, list):
        return [s for v in obj for s in strings(v, skip)]
    return []


def fixture_frag(name: str) -> dict:
    return json.loads((FIX / "digest" / "EP91" / name).read_bytes().decode("utf-8"))


def with_market_01(vault, which: str = "bad"):
    """把 fixture 的 `_digest/EP91/` 铺进 vault 副本，`frag-market-01.json` 换成
    `tests/fixtures/l3/frag-market-01.<which>.json`（`bad` 违规、`snap` 差一两个字）。

    L1 与 L2 的产物就此齐全，跑 `ep EP91` 一次调用都不会发——这一趟只跑闸门与渲染。
    """
    dst = vault / "_digest" / "EP91"
    shutil.copytree(FIX / "digest" / "EP91", dst)
    shutil.copy(FIX / "l3" / f"frag-market-01.{which}.json", dst / "frag-market-01.json")
    return json.loads((dst / "frag-market-01.json").read_bytes().decode("utf-8"))


def market_rows(vault):
    """笔记「夜市」那一节的原话锚点。"""
    block = block_of(note_text(vault, "EP91"))
    return rows_under(sections(block)["河口夜市搬迁：消防倒逼下的选择"], "原话锚点")


# ---------------------------------------------------------------- 验收 1

def test_a_clean_episode_passes_every_gate(vault):
    """好 fixture 跑完：计数全 0，每条引文补上 `ctx`（等于逐字稿对应那一段），
    除 `ctx` 外片段与 L2 写出来的那一份等价，块首行报「删引文 0 条」。"""
    assert run_ep(vault, "EP91", FakeRunner(RAW)) == 0

    gates = digest(vault, "EP91", "gates.json")
    assert gates["ep"] == "EP91" and gates["generated_at"]
    assert set(gates["topics"]) == {"bridge-01", "bridge-02", "market-01",
                                    "market-02", "market-03"}
    for tid, entry in gates["topics"].items():
        assert entry == {"quotes_snapped": 0, "quotes_dropped": 0, "quotes_out_of_range": 0,
                         "paras_out_of_range": [], "asr_dropped": 0, "snapped": [],
                         "schema": "ok"}, tid

    seg_texts = {s["text"] for s in transcript_segments(vault)}
    seen = 0
    for tid in gates["topics"]:
        got = digest(vault, "EP91", f"frag-{tid}.json")
        want = fixture_frag(f"frag-{tid}.json")
        for q, w in zip(got["quotes"], want["quotes"]):
            assert q["ctx"] in seg_texts                  # `ctx` 是逐字稿里的一整段
            assert q["text"] in q["ctx"]                  # 而且是这条引文所在那一段
            assert {k: v for k, v in q.items() if k != "ctx"} == w
            seen += 1
        assert {k: v for k, v in got.items() if k not in ("quotes", "provenance")} == \
               {k: v for k, v in want.items() if k not in ("quotes", "provenance")}
    assert seen == 13                                     # 三个话题的锚点全带上了 ctx

    head = block_of(note_text(vault, "EP91")).splitlines()[3]
    assert "闸门：归一引文 0 条、删引文 0 条、越界 0 条、删 ASR 条目 0 条；" in head


# ---------------------------------------------------------------- #83 验收 1

def test_quotes_that_miss_by_a_character_come_back_as_the_transcript_said_it(vault):
    """`snap` 片段跑完：五条引文里 1 条逐字命中、2 条归一、2 条删。

    归一的那两条在笔记上是逐字稿的原句——模型多抄的「摊」没了，丢掉的「应该」
    回来了（红线 2：限定词原样保留）。
    """
    before = with_market_01(vault, "snap")
    runner = FakeRunner(RAW)
    assert run_ep(vault, "EP91", runner) == 0
    assert runner.calls == []                             # L1 / L2 产物齐全，只跑闸门与渲染

    entry = digest(vault, "EP91", "gates.json")["topics"]["market-01"]
    assert entry["quotes_snapped"] == 2                   # 多一个「摊」、少一个「应该」
    assert entry["quotes_dropped"] == 2                   # 改写太多的、逐字稿里没有的
    assert entry["quotes_out_of_range"] == 0 and entry["asr_dropped"] == 0

    said = ["河口晚报今天早上发了报道，说夜市要整体搬到滨江路",
            "我上个月去数过，摊位不到一百个",
            "六月底应该是赶在暑假前，暑假是夜市生意最好的时候"]
    after = digest(vault, "EP91", "frag-market-01.json")
    assert [q["text"] for q in after["quotes"]] == said
    assert all(q.get("ctx") for q in after["quotes"])
    assert entry["snapped"] == [
        {"ts": "00:20:13", "from": before["quotes"][1]["text"], "to": said[1]},
        {"ts": "00:22:39", "from": before["quotes"][2]["text"], "to": said[2]}]
    # 闸门只动 `quotes`：整理稿的段落、说法、信源逐项与 L2 写出来的那份相等
    for k in ("paras", "claims", "channels"):
        assert after[k] == before[k]

    rows = market_rows(vault)
    assert len(rows) == 3
    assert all(any(t in r for r in rows) for t in said)
    assert "六月底应该是赶在暑假前" in "\n".join(rows)      # 丢掉的限定词随原句回来
    for gone in ("摊位不到一百个摊", "便宜两百", "房租"):
        assert not any(gone in r for r in rows)
    head = block_of(note_text(vault, "EP91")).splitlines()[3]
    assert "闸门：归一引文 2 条、删引文 2 条、越界 0 条、删 ASR 条目 0 条；" in head


def test_a_snapped_episode_run_twice_snaps_nothing_the_second_time(vault):
    """#83 验收 6：归一过一轮再跑，计数归 0、片段逐字节不变、块首行「归一引文 0 条」
    ——换进去的就是逐字稿原句，第二趟它已经是逐字命中的了。"""
    with_market_01(vault, "snap")
    assert run_ep(vault, "EP91", FakeRunner(RAW)) == 0
    first = (vault / "_digest" / "EP91" / "frag-market-01.json").read_bytes()

    assert run_ep(vault, "EP91", FakeRunner(RAW), now="2026-03-13T09:00:00+08:00") == 0
    entry = digest(vault, "EP91", "gates.json")["topics"]["market-01"]
    assert entry["quotes_snapped"] == 0 and entry["snapped"] == []
    assert entry["quotes_dropped"] == 0
    assert (vault / "_digest" / "EP91" / "frag-market-01.json").read_bytes() == first
    head = block_of(note_text(vault, "EP91")).splitlines()[3]
    assert "闸门：归一引文 0 条、删引文 0 条、越界 0 条、删 ASR 条目 0 条；" in head


# ---------------------------------------------------------------- 验收 2、#83 验收 2

def test_a_violating_fragment_loses_two_entries_and_gets_one_snapped(vault):
    """坏片段跑完：归一 1、删引文 0、越界 1、删 ASR 1；多抄一个「摊」的那条换成
    逐字稿原句留下，越界与编出来的 ASR 条目照删；`paras` 逐段与输入相等；块首行的
    计数与 gates.json 一致。"""
    before = with_market_01(vault)
    runner = FakeRunner(RAW)
    assert run_ep(vault, "EP91", runner) == 0
    assert runner.calls == []                             # L1 / L2 产物齐全，只跑闸门与渲染

    entry = digest(vault, "EP91", "gates.json")["topics"]["market-01"]
    assert entry["quotes_snapped"] == 1                   # 「摊位不到一百个摊」多了个字
    assert entry["quotes_dropped"] == 0
    assert entry["quotes_out_of_range"] == 1              # ts 00:10:00 离话题 2 分钟开外
    assert entry["asr_dropped"] == 1                      # 「冰江路」逐字稿里没有
    assert entry["paras_out_of_range"] == [] and entry["schema"] == "ok"

    after = digest(vault, "EP91", "frag-market-01.json")
    assert [q["text"] for q in after["quotes"]] == [
        "河口晚报今天早上发了报道，说夜市要整体搬到滨江路",
        "我上个月去数过，摊位不到一百个",                   # 归一：多抄的「摊」没了
        "商户其实是在停业整改和搬迁之间选，不是搬和不搬之间选",
        "老码头市场也是因为消防搬的，搬完之后头一年生意掉了一半"]
    assert after["asr"] == []
    assert after["paras"] == before["paras"]              # 段一段没删、一个字没改

    block = block_of(note_text(vault, "EP91"))
    rows = market_rows(vault)
    assert len(rows) == 4
    assert any("摊位不到一百个" in r for r in rows)
    assert not any("摊位不到一百个摊" in r for r in rows)
    assert not any(r.startswith("- [00:10:00]") for r in rows)
    # 被删的只是锚点：同一句话在「可核查的说法」「提到的信源」里是 L2 另写的条目，
    # 闸门 1 / 2 不碰它们（那是 #54 的 schema 与 #53 之外的事），笔记上照旧在
    assert "四十多处这个数字是消防部门的通报" in block
    assert "闸门：归一引文 1 条、删引文 0 条、越界 1 条、删 ASR 条目 1 条；" \
        in block.splitlines()[3]


# ---------------------------------------------------------------- 验收 5、#83 验收 3

def test_the_gates_can_only_write_the_transcripts_own_words(vault):
    """闸门能写进片段的字只有两种：逐字稿的一整段（`ctx`），和逐字稿一段里的连续
    一截（归一过的 `text`）。除这两处之外，每个留下来的字符串值都能在输入里原样
    找到。

    闸门不许有「修正」逻辑（红线 2、5）：它只会让条目变少，或者把引文换回逐字稿
    原句，不会自己写出一个字来。
    """
    before = with_market_01(vault, "bad")
    assert run_ep(vault, "EP91", FakeRunner(RAW)) == 0
    only_the_transcripts_words(vault, before, kept=4)


def test_the_gates_can_only_write_the_transcripts_own_words_after_snapping(vault):
    """同一条总断言，换成归一那份片段跑：归一写回的 `text` 也逃不出「逐字稿一段里
    的连续一截」。"""
    before = with_market_01(vault, "snap")
    assert run_ep(vault, "EP91", FakeRunner(RAW)) == 0
    only_the_transcripts_words(vault, before, kept=3)


def only_the_transcripts_words(vault, before: dict, kept: int) -> None:
    after = digest(vault, "EP91", "frag-market-01.json")
    # 先钉住「还剩东西」：全删光的话下面几条遍历都成了空转，总断言会变成永真
    assert len(after["quotes"]) == kept and len(after["paras"]) == len(before["paras"])
    seg_texts = {s["text"] for s in transcript_segments(vault)}
    for q in after["quotes"]:
        assert q["ctx"] in seg_texts                      # `ctx` 是逐字稿里的一整段
        assert norm(q["text"]) in norm(q["ctx"])          # `text` 是那一段里的连续一截
    source = set(strings(before))
    for s in strings(after, skip=("text", "ctx", "provenance")):
        assert s in source, s


def test_a_broken_fragment_is_refilled_by_l2_before_the_gates_see_it(vault):
    """读不出来的片段在 L2 那一步就被认出来了（#52 的 `read_done`）：它那一章重跑，
    闸门拿到的是重跑出来的新片段。

    所以闸门自己那道「读不出来就抛」（`test_sm_l3` 里单测的那条）是最后一道防线，
    不是常走的路——`ep` 这条路上走到闸门的产物，都是这一趟刚写出来的。
    """
    with_market_01(vault)
    (vault / "_digest" / "EP91" / "frag-market-02.json").write_bytes(b'{"id": "market-02",')

    runner = FakeRunner(RAW)
    assert run_ep(vault, "EP91", runner) == 0
    assert runner.calls == [("EP91", "L2", "market")]      # 只补这一章，L1 与 bridge 不动
    # 重跑把坏片段连同那一章的其他片段一起覆盖了，market-01 也回到了 L2 的原样：
    # 闸门这一趟无事可删、也无事可归一
    entry = digest(vault, "EP91", "gates.json")["topics"]["market-01"]
    assert (entry["quotes_snapped"], entry["quotes_dropped"],
            entry["quotes_out_of_range"], entry["asr_dropped"]) == (0, 0, 0, 0)


def test_a_second_run_drops_nothing_and_leaves_the_fragment_alone(vault):
    """验收 6 的端到端那一半：删过一轮之后重跑，计数全 0、片段逐字节不变。"""
    with_market_01(vault)
    assert run_ep(vault, "EP91", FakeRunner(RAW)) == 0
    first = (vault / "_digest" / "EP91" / "frag-market-01.json").read_bytes()

    assert run_ep(vault, "EP91", FakeRunner(RAW), now="2026-03-13T09:00:00+08:00") == 0
    entry = digest(vault, "EP91", "gates.json")["topics"]["market-01"]
    assert (entry["quotes_snapped"], entry["quotes_dropped"],
            entry["quotes_out_of_range"], entry["asr_dropped"]) == (0, 0, 0, 0)
    assert (vault / "_digest" / "EP91" / "frag-market-01.json").read_bytes() == first
    head = block_of(note_text(vault, "EP91")).splitlines()[3]
    assert "闸门：归一引文 0 条、删引文 0 条、越界 0 条、删 ASR 条目 0 条；" in head
