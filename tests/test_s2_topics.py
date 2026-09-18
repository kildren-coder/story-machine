# -*- coding: utf-8 -*-
"""L2 的端到端用例：逐字稿 → L1 章节表 → 逐章节整理 → EP 笔记里的整理稿。

对应 issue #52 验收 1、2、3、4、5、6、9、10、11。全部在 fixture vault 的临时副本
上跑，假 runner 读 `tests/fixtures/raw/`，一次真实调用都不发。
"""
from __future__ import annotations

import json
import re
import shutil

from conftest import FIX, L2_VERSION, NOW, RAW, RAW_BAD, fixture_note_text, note_path, note_text, run_ep
from sm.note import read_frontmatter
from sm.prov import PROV_KEYS
from sm.runner import FakeRunner

BLOCK_RE = re.compile(r"\n<!-- digest:auto -->.*?<!-- /digest -->\n", re.S)
HEAD_RE = re.compile(r"^### \[(\d\d:\d\d:\d\d)\] (.+)$", re.M)
PARA_RE = re.compile(r"^\[\d\d:\d\d:\d\d\] ", re.M)


def block_of(text: str) -> str:
    m = re.search(r"<!-- digest:auto -->(.*?)<!-- /digest -->", text, re.S)
    assert m, "笔记里没有标记块"
    return m.group(1)


def without_block(text: str) -> str:
    return BLOCK_RE.sub("", text, count=1)


def drop_prov(obj: dict) -> dict:
    return {k: v for k, v in obj.items() if k != "provenance"}


def digest(vault, ep: str, name: str) -> dict:
    return json.loads((vault / "_digest" / ep / name).read_bytes().decode("utf-8"))


def sections(block: str) -> dict:
    """`### [HH:MM:SS] 标题` → 标题下面那一节的正文（不含标题行本身）。"""
    out = {}
    for part in re.split(r"^### ", block, flags=re.M)[1:]:
        head, _, body = part.partition("\n")
        out[HEAD_RE.match("### " + head).group(2)] = body
    return out


def rows_under(section: str, title: str) -> list[str]:
    m = re.search(rf"\*\*{title}\*\*\n\n(.*?)(?:\n\n|\Z)", section, re.S)
    return m.group(1).splitlines() if m else []


def raw_with(tmp_path, ep: str, unit: str):
    """`raw/` 的副本，其中一章的响应换成 `raw-bad/` 的那一份。"""
    root = tmp_path / f"raw-{ep}-{unit}"
    shutil.copytree(RAW, root)
    shutil.copy(RAW_BAD / ep / f"L2-{unit}.raw.json", root / ep / f"L2-{unit}.raw.json")
    return FakeRunner(root)


# ---------------------------------------------------------------- 验收 1

def test_ep91_end_to_end(vault):
    """L1 一次 + L2 每章一次；片段与话题表逐个等于 fixture；笔记里四节整理稿。"""
    runner = FakeRunner(RAW)
    assert run_ep(vault, "EP91", runner) == 0
    # L2 的两章并发跑，完成顺序不定；调用集合是定的
    assert runner.calls[0] == ("EP91", "L1", "all")
    assert sorted(runner.calls) == [("EP91", "L1", "all"), ("EP91", "L2", "bridge"),
                                    ("EP91", "L2", "market")]

    for name in ("frag-bridge-01.json", "frag-bridge-02.json", "frag-market-01.json",
                 "frag-market-02.json", "frag-market-03.json", "topics.json"):
        got = digest(vault, "EP91", name)
        want = json.loads((FIX / "digest" / "EP91" / name).read_bytes().decode("utf-8"))
        assert drop_prov(got) == drop_prov(want), name
        assert set(got["provenance"]) == set(PROV_KEYS), name
    assert digest(vault, "EP91", "frag-market-01.json")["provenance"]["unit"] == "market"
    assert digest(vault, "EP91", "topics.json")["provenance"]["unit"] == "all"
    assert sorted((vault / "_digest" / "EP91").glob("frag-*.json")).__len__() == 5

    block = block_of(note_text(vault, "EP91"))
    heads = HEAD_RE.findall(block)
    # bridge-01 是 filler，不渲染；其余四个话题各一节
    assert len(heads) == 4
    assert [h[0] for h in heads] == ["00:03:30", "00:19:00", "00:36:00", "00:41:30"]
    assert [h[1] for h in heads] == ["北港大桥收费方案：十五块还是十二块",
                                     "河口夜市搬迁：消防倒逼下的选择",
                                     "回到大桥：货车费率与浮桥",
                                     "结尾弹幕与下周预告 · 旁白"]

    sec = sections(block)["北港大桥收费方案：十五块还是十二块"]
    assert len(PARA_RE.findall(sec)) == 5
    assert len(rows_under(sec, "原话锚点")) == 6
    assert len(rows_under(sec, "可核查的说法")) == 10
    assert len(rows_under(sec, "提到的信源")) == 2 + 3          # 表头两行 + 三行信源
    assert len(rows_under(sec, "疑似 ASR 生音")) == 1

    fm = read_frontmatter(note_text(vault, "EP91"))
    assert fm["整理"] == "done" and fm["整理版本"] == L2_VERSION == "L2-topic@0.2"
    stripped = without_block(note_text(vault, "EP91")) \
        .replace("整理: done\n", "", 1).replace(f"整理版本: {L2_VERSION}\n", "", 1)
    assert stripped == fixture_note_text("EP91")


def test_ep92_end_to_end(vault):
    """一章三个话题，其中一个 filler：块内两节。"""
    runner = FakeRunner(RAW)
    assert run_ep(vault, "EP92", runner) == 0
    assert len(runner.calls) == 2                       # L1 + 一章 L2

    for name in ("frag-followup-01.json", "frag-followup-02.json",
                 "frag-followup-03.json", "topics.json"):
        got = digest(vault, "EP92", name)
        want = json.loads((FIX / "digest" / "EP92" / name).read_bytes().decode("utf-8"))
        assert drop_prov(got) == drop_prov(want), name

    block = block_of(note_text(vault, "EP92"))
    heads = HEAD_RE.findall(block)
    assert [h[1] for h in heads] == ["加更说明 · 旁白",
                                     "北港大桥货车费率：一张征求意见函的照片"]
    assert "另有 1 段杂项未渲染（合计 00:01:00）。" in block.splitlines()[3]


# ---------------------------------------------------------------- 验收 2

def test_paragraphs_land_in_the_note_verbatim(vault):
    """红线 5：除三种标记外一个字节不动；块内时间戳全是裸 `[HH:MM:SS]`。"""
    assert run_ep(vault, "EP91", FakeRunner(RAW)) == 0
    block = block_of(note_text(vault, "EP91"))
    seen = 0
    for t in digest(vault, "EP91", "topics.json")["topics"]:
        if t["kind"] == "filler":
            continue
        for para in digest(vault, "EP91", f"frag-{t['id']}.json")["paras"]:
            shown = re.sub(r"<who>(.*?)</who>", r"**\1**", para)
            shown = re.sub(r"<hedge>(.*?)</hedge>", r"<u>\1</u>", shown)
            assert shown in block
            back = re.sub(r"\*\*(.*?)\*\*", r"<who>\1</who>", shown) \
                     .replace("<u>", "<hedge>").replace("</u>", "</hedge>")
            assert back == para                          # 还原回去逐字相等
            seen += 1
    assert seen == 13                                    # 四个话题的段落全在
    assert "<who>" not in block and "<hedge>" not in block
    assert PARA_RE.search(block) and not re.search(r"EP\d+@\d\d:\d\d:\d\d", block)


# ---------------------------------------------------------------- 验收 3

def test_the_chapter_slice_input_is_labelled(vault):
    """切片三段、头里的行号与范围、章节地图上标出本章；空的那一段连分隔行一起
    省掉——空标题下面跟着本章的内容，模型会以为那也是上文。"""
    assert run_ep(vault, "EP91", FakeRunner(RAW)) == 0
    market = (vault / "_pairs" / "EP91" / "L2-market.in.md").read_bytes().decode("utf-8")
    head, rest = market.split("\n---\n", 1)
    assert "行号: 35–76" in head and "范围: 00:19:00–00:42:40" in head
    chart, body = rest.split("\n---\n", 1)
    assert len(chart.splitlines()) == 2 and chart.splitlines()[1].startswith("→ ")

    before = body.split("=== 上文（只供理解，不写） ===\n", 1)[1].split("=== 本章 ===")[0]
    assert [ln.split(" ", 1)[0] for ln in before.strip().splitlines()] == ["32", "33", "34"]
    mine = body.split("=== 本章 ===\n", 1)[1].strip().splitlines()
    assert mine[0].startswith("35 [00:19:00] 阿桥: ") and mine[-1].startswith("76 ")
    assert "下文" not in market                          # 本章收在整集末尾

    bridge = (vault / "_pairs" / "EP91" / "L2-bridge.in.md").read_bytes().decode("utf-8")
    assert "上文" not in bridge                          # 本章从整集开头起
    after = bridge.split("=== 下文（只供理解，不写） ===\n", 1)[1]
    assert [ln.split(" ", 1)[0] for ln in after.strip().splitlines()] == ["35", "36", "37", "38"]


# ---------------------------------------------------------------- 验收 4

def test_the_code_fills_ids_times_and_speakers(vault):
    """模型只写 `line`，其余是代码填的；`line` 不进产物。"""
    assert run_ep(vault, "EP91", FakeRunner(RAW)) == 0
    topics = digest(vault, "EP91", "topics.json")["topics"]
    assert [t["id"] for t in topics] == ["bridge-01", "bridge-02",
                                         "market-01", "market-02", "market-03"]
    assert topics[0]["start"] == "00:00:00"              # 章内第一个话题归到章首
    assert topics[-1]["end"] == "00:42:40"               # 最后一个收在章尾
    for a, b in zip(topics, topics[1:]):                 # 章内首尾相接
        if a["chapter"] == b["chapter"]:
            assert a["end"] == b["start"]
    assert topics[-1]["who"] == ["阿桥", "老周"]         # 行表里现成的
    for t in topics:
        frag = digest(vault, "EP91", f"frag-{t['id']}.json")
        assert "line" not in frag and frag["chapter"] in ("bridge", "market")


# ---------------------------------------------------------------- 验收 5

def test_one_bad_chapter_is_isolated_and_the_rest_still_land(vault, tmp_path):
    """散文响应（没有 JSON）：那一章进 `_failed/`，另一章照样写出来；整集不渲染、
    `整理: failed`、退出码 1。补跑时只调没完成的那一章（红线 9）。"""
    runner = raw_with(tmp_path, "EP91", "bridge")
    assert run_ep(vault, "EP91", runner) == 1
    assert len(runner.calls) == 1 + 1 + 2                # L1 + market + bridge 两趟（retries=1）

    failed = vault / "_failed" / "EP91" / "L2-bridge.failed.json"
    assert failed.exists()
    assert "响应不是合法 JSON" in json.loads(failed.read_bytes().decode("utf-8"))["errors"][0]

    frags = sorted(p.name for p in (vault / "_digest" / "EP91").glob("frag-*.json"))
    assert frags == ["frag-market-01.json", "frag-market-02.json", "frag-market-03.json"]
    topics = digest(vault, "EP91", "topics.json")["topics"]
    assert [t["id"] for t in topics] == ["market-01", "market-02", "market-03"]

    text = note_text(vault, "EP91")
    assert "<!-- digest:auto -->" not in text
    assert read_frontmatter(text)["整理"] == "failed"

    # 换回好的响应再跑：只补 bridge 那一章
    good = FakeRunner(RAW)
    assert run_ep(vault, "EP91", good) == 0
    assert good.calls == [("EP91", "L2", "bridge")]
    assert HEAD_RE.findall(block_of(note_text(vault, "EP91"))).__len__() == 4


def test_a_stale_topic_table_cannot_stand_in_for_the_chapter_that_just_failed(vault, tmp_path):
    """上一趟的话题表还在盘上，这一趟这一章又挂了：不许拿旧表当「完成」的凭据。

    「片段写了一半被杀」（frag 没了、话题表还记着它）之后重跑，那一章没过——盘上
    的 `topics.json` 还停在上一趟，里面有它的旧话题，可它的片段这一趟一份都没装
    进来。照着旧表渲染的话，笔记上那一节是个**空标题**（正题整段消失），
    frontmatter 还写着 `整理: done`、退出码 0：`_failed/` 里躺着记录，人唯一会读
    的那一面上却什么都看不出来（红线 9）。
    """
    assert run_ep(vault, "EP91", FakeRunner(RAW)) == 0
    before = note_text(vault, "EP91")
    (vault / "_digest" / "EP91" / "frag-bridge-02.json").unlink()

    runner = raw_with(tmp_path, "EP91", "bridge")
    assert run_ep(vault, "EP91", runner) == 1
    assert runner.calls == [("EP91", "L2", "bridge")] * 2     # market 已完成，只补 bridge
    assert (vault / "_failed" / "EP91" / "L2-bridge.failed.json").exists()

    text = note_text(vault, "EP91")
    assert read_frontmatter(text)["整理"] == "failed"
    # 上一趟那块好的原样留着（`block_text=None` 只动 frontmatter），绝不许被换成
    # 一块只剩标题的壳
    assert block_of(text) == block_of(before)
    assert without_block(text).replace("整理: failed", "整理: done") == without_block(before)


# ---------------------------------------------------------------- 验收 6

def test_a_gate_violating_chapter_still_passes_l2(vault, tmp_path):
    """闸门违规（引文改写、时间戳越界、丢 hedge）不是 L2 检查的事（#53）：
    schema 合法就写出来，L3 上线后才由闸门去删、去警。"""
    runner = raw_with(tmp_path, "EP91", "market")
    assert run_ep(vault, "EP91", runner) == 0
    assert len(runner.calls) == 3                        # 一趟就过，没有重试
    assert not (vault / "_failed" / "EP91").exists()
    frag = digest(vault, "EP91", "frag-market-01.json")
    assert frag["kind"] == "talk" and frag["paras"]
    # 越界的时间戳原样留着，不许代码替模型改（红线 2）
    assert any(q["ts"] == "00:10:00" for q in frag["quotes"])


# ---------------------------------------------------------------- 验收 9

def test_rerun_is_byte_identical_and_only_missing_chapters_are_refilled(vault):
    """幂等与增量：跑两次笔记逐字节不变、第二次一次都不调；删掉一个片段只重跑
    它那一章，重跑前把这一章的旧片段清干净。"""
    runner = FakeRunner(RAW)
    assert run_ep(vault, "EP91", runner) == 0
    first = note_text(vault, "EP91")
    topics_before = (vault / "_digest" / "EP91" / "topics.json").read_bytes()

    assert run_ep(vault, "EP91", runner, now="2026-03-13T11:30:00+08:00") == 0
    assert len(runner.calls) == 3                        # 第二趟一次都没调
    assert note_text(vault, "EP91") == first
    assert (vault / "_digest" / "EP91" / "topics.json").read_bytes() == topics_before

    # 片段写了一半被杀：话题表里有它、文件不在 → 这一章重跑
    (vault / "_digest" / "EP91" / "frag-market-02.json").unlink()
    stray = vault / "_digest" / "EP91" / "frag-market-09.json"
    stray.write_bytes(json.dumps({"id": "market-09", "chapter": "market"}).encode("utf-8"))
    # 文件名撞上但章节不同的，不许误伤（`frag-market-*.json` 会连它一起扫进来）
    other = vault / "_digest" / "EP91" / "frag-market-2-01.json"
    other.write_bytes(json.dumps({"id": "market-2-01", "chapter": "market-2"}).encode("utf-8"))

    again = FakeRunner(RAW)
    assert run_ep(vault, "EP91", again) == 0
    assert again.calls == [("EP91", "L2", "market")]
    assert not stray.exists() and other.exists()
    assert note_text(vault, "EP91") == first             # 固定时钟 + 同一份响应

    other.unlink()
    # 人手改了一个片段：重渲染只动块内，产物一个字节不动
    frag_path = vault / "_digest" / "EP91" / "frag-bridge-02.json"
    frag = json.loads(frag_path.read_bytes().decode("utf-8"))
    frag["paras"][0] = "[00:03:30] 人手改过的一段"
    frag_path.write_bytes(json.dumps(frag, ensure_ascii=False, indent=1).encode("utf-8"))
    quiet = FakeRunner(RAW)
    assert run_ep(vault, "EP91", quiet) == 0
    assert quiet.calls == []
    after = note_text(vault, "EP91")
    assert "[00:03:30] 人手改过的一段" in block_of(after)
    assert without_block(after) == without_block(first)


def test_force_reruns_every_chapter(vault):
    runner = FakeRunner(RAW)
    assert run_ep(vault, "EP91", runner) == 0
    first = note_text(vault, "EP91")
    assert run_ep(vault, "EP91", runner, "--force") == 0
    assert len(runner.calls) == 6                        # L1 + 两章，再来一遍
    assert note_text(vault, "EP91") == first


def test_a_chapter_whose_boundaries_moved_is_not_reused(vault):
    """L1 重切之后章还叫 `market`、起止时刻却变了：只认 `id` 的话这一章会被当成
    已完成跳过，笔记上留着按旧边界整理的话题，和章节表对不上——那是静默的不一致。"""
    assert run_ep(vault, "EP91", FakeRunner(RAW)) == 0
    chapters = digest(vault, "EP91", "chapters.json")
    chapters["chapters"][0]["end"] = "00:14:00"          # 假装 L1 重切，边界挪了
    chapters["chapters"][1]["start"] = "00:14:00"
    (vault / "_digest" / "EP91" / "chapters.json").write_bytes(
        json.dumps(chapters, ensure_ascii=False, indent=1).encode("utf-8"))

    runner = FakeRunner(RAW)
    assert run_ep(vault, "EP91", runner) == 0
    assert sorted(runner.calls) == [("EP91", "L2", "bridge"), ("EP91", "L2", "market")]
    topics = digest(vault, "EP91", "topics.json")["topics"]
    assert topics[1]["end"] == "00:14:00" and topics[2]["start"] == "00:14:00"


def test_orphan_topics_from_a_rerun_l1_are_swept(vault):
    """L1 重跑过、章节表变了：话题表里 `chapter` 对不上的话题连片段一起清掉。"""
    assert run_ep(vault, "EP91", FakeRunner(RAW)) == 0
    orphan = vault / "_digest" / "EP91" / "frag-gone-01.json"
    orphan.write_bytes(json.dumps({"id": "gone-01", "chapter": "gone"},
                                  ensure_ascii=False).encode("utf-8"))
    topics = digest(vault, "EP91", "topics.json")
    topics["topics"].append({"id": "gone-01", "chapter": "gone", "title": "上一版的章",
                             "kind": "talk", "start": "00:05:00", "end": "00:06:00",
                             "who": [], "gist": "上一版章节表留下的"})
    (vault / "_digest" / "EP91" / "topics.json").write_bytes(
        json.dumps(topics, ensure_ascii=False, indent=1).encode("utf-8"))

    runner = FakeRunner(RAW)
    assert run_ep(vault, "EP91", runner) == 0
    assert runner.calls == []                            # 五个话题都还在，不用重跑
    assert not orphan.exists()
    assert "gone-01" not in [t["id"] for t in digest(vault, "EP91", "topics.json")["topics"]]


# ---------------------------------------------------------------- 验收 10、11

def test_filler_is_invisible_but_counted(vault):
    """`filler` 一个字都不出现，但段数与合计时长报在块首行；片段照样落盘。"""
    assert run_ep(vault, "EP91", FakeRunner(RAW)) == 0
    block = block_of(note_text(vault, "EP91"))
    assert "开场与设备测试" not in block and "换了新麦克风" not in block
    assert "另有 1 段杂项未渲染（合计 00:03:30）。" in block.splitlines()[3]

    frag = digest(vault, "EP91", "frag-bridge-01.json")
    assert frag["kind"] == "filler" and frag["title"] == "开场与设备测试"
    assert all(frag[k] == [] for k in ("paras", "quotes", "claims", "channels", "asr"))


def test_an_aside_topic_renders_only_its_paragraphs(vault):
    """验收 11：`market-03` 那一节没有锚点 / 说法 / 信源小标题。"""
    assert run_ep(vault, "EP91", FakeRunner(RAW)) == 0
    sec = sections(block_of(note_text(vault, "EP91")))["结尾弹幕与下周预告 · 旁白"]
    assert len(PARA_RE.findall(sec)) == 1
    for title in ("原话锚点", "可核查的说法", "提到的信源", "疑似 ASR 生音"):
        assert title not in sec


# ---------------------------------------------------------------- 红线 6

def test_stdout_reports_steps_and_counts_only(vault, capsys):
    """日志一步一行、只报步骤与计数，不把整理稿的内容打到终端。"""
    assert run_ep(vault, "EP91", FakeRunner(RAW)) == 0
    out = capsys.readouterr().out
    assert "L2 逐章节整理：2 章" in out
    assert "L2 通过：5 个话题（talk 3、aside 1、filler 1）" in out
    assert "整理稿已写进" in out and f"整理版本 {L2_VERSION}" in out
    assert "北港大桥收费方案" not in out and "河口晚报" not in out
    assert "十五块" not in out
