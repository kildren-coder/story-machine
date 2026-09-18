# -*- coding: utf-8 -*-
"""L3 闸门的单测（SPEC §4 L3 第 1、2、5 条；issue #53 验收 3、4、6、7）。

用例里的逐字稿、章节、片段全是这里现编的合成文本（红线 10），跟 `tests/fixtures/`
那一套「河口夜话」无关——这里要的是刚好卡在边界上的那几段，编起来比改 fixture 快。

**段与行的区别在这一层很要紧**：§5.1 的一段是 ASR 的一段，§5.2 的一行是同一个人
30 秒窗内的几段连起来的。闸门 1 比到段（不跨段），闸门 5 比的是章节切片的行。
下面 `SEGS` 的前两段就是同人同窗的一对——它们在 §5.2 里是同一行，在这里是两段。
"""
from __future__ import annotations

import json

import pytest

import conftest                                          # noqa: F401  （挂 sys.path）
from sm.l3 import gate_frag, hit_segment, run_gates
from sm.paths import VaultPaths
from sm.text import norm

A = "SPEAKER_00"

# (start, end, text)。第 1、2 段同人同窗：§5.2 里是一行，§5.1 里是两段
SEGS = [
    (0.0, 20.0, "各位晚上好，今天聊城西菜场的改造。"),
    (21.0, 29.0, "先说结论，工期要拖到年底。"),
    (60.0, 100.0, "改造预算是一千二百万，这个数是区里通报里写的。"),
    (600.0, 640.0, "摊位现在是八十个，改造以后是一百个。"),
    (880.0, 900.0, "这句话我在下半场还会再说一遍。"),
    (960.0, 990.0, "西城菜场这个写法我看到过两次。"),
    (1080.0, 1100.0, "这句话我在下半场还会再说一遍。"),
    (1400.0, 1430.0, "今天就到这里，下周接着说菜场。"),
]
CHAPTERS = {"ep": "EP99", "chapters": [
    {"id": "ch1", "title": "菜场改造", "start": "00:00:00", "end": "00:15:00",
     "who": ["阿桥"], "gist": "改造的工期与预算"},
    {"id": "ch2", "title": "收尾", "start": "00:15:00", "end": "00:23:50",
     "who": ["阿桥"], "gist": "摊位数与预告"},
]}


def segments() -> list[dict]:
    return [{"start": a, "end": b, "text": t, "speaker": A} for a, b, t in SEGS]


def nsegs() -> list[tuple[str, dict]]:
    return [(norm(s["text"]), s) for s in segments()]


def frag(tid="ch1-01", chapter="ch1", start="00:00:00", end="00:10:00", **over) -> dict:
    f = {"id": tid, "chapter": chapter, "title": "菜场改造：工期与预算", "kind": "talk",
         "start": start, "end": end, "who": ["阿桥"], "gist": "工期拖到年底，预算一千二百万",
         "paras": ["[00:00:00] <who>阿桥</who>说工期要拖到年底，预算一千二百万。"],
         "quotes": [], "claims": [], "channels": [], "asr": []}
    f.update(over)
    return f


def quote(text: str, ts: str = "00:00:00") -> dict:
    return {"ts": ts, "who": "阿桥", "text": text}


def gate(f: dict, chapter: str = "ch1", nslice: list[str] | None = None):
    ch = next(c for c in CHAPTERS["chapters"] if c["id"] == chapter)
    if nslice is None:
        nslice = [norm(t) for _, _, t in SEGS]
    return gate_frag(f, ch, nsegs(), nslice)


def build_vault(tmp_path, frags: list[dict], chapters=None) -> VaultPaths:
    """合成的迷你 vault：逐字稿 + 章节表 + 话题表 + 片段。不碰 `tests/fixtures/`。"""
    paths = VaultPaths(tmp_path / "vault")
    (paths.vault / "_assets").mkdir(parents=True)
    write(paths.transcript("EP99"), {"meta": {"episode": "EP99"}, "segments": segments()})
    d = paths.digest("EP99")
    d.mkdir(parents=True)
    write(d / "chapters.json", chapters or CHAPTERS)
    write(d / "topics.json", {"ep": "EP99", "topics": [
        {k: f[k] for k in ("id", "chapter", "title", "kind", "start", "end", "who", "gist")
         if k in f} for f in frags]})
    for f in frags:
        write(d / f"frag-{f['id']}.json", f)
    return paths


def write(path, obj) -> None:
    path.write_bytes((json.dumps(obj, ensure_ascii=False, indent=1) + "\n").encode("utf-8"))


def read(path) -> dict:
    return json.loads(path.read_bytes().decode("utf-8"))


# ---------------------------------------------------------------- 验收 3：闸门 1

def test_extra_whitespace_and_timestamps_still_hit():
    """归一只授权两样：去时间戳、去空白（全角空格与零宽也算）。模型把行首那截
    脚手架抄进引文、或者在词之间多敲了空格，都还算逐字命中。"""
    seg = hit_segment(norm(" 改造预算是一千二百万，　这个数是 区里通报里写的。"),
                      60, nsegs())
    assert seg and seg["text"] == "改造预算是一千二百万，这个数是区里通报里写的。"
    assert hit_segment(norm("[00:01:00] 改造预算是一千二百万"), 60, nsegs()) is not None


def test_different_punctuation_misses():
    """标点不动（红线 2）：他没说的逗号是模型加的，加了就不是逐字照抄。"""
    assert hit_segment(norm("改造预算是一千二百万这个数是区里通报里写的"), 60, nsegs()) is None
    assert hit_segment(norm("改造预算是一千二百万。这个数是区里通报里写的。"), 60, nsegs()) is None


def test_a_quote_stitched_from_two_segments_misses():
    """跨两段不命中——哪怕这两段在 §5.2 里同属一行（同人、同 30 秒窗）。

    逐字稿里并没有「……菜场的改造。先说结论……」这么一句连着说下来的话，`ctx`
    也就无从取；要引两段就分两条写。
    """
    stitched = "今天聊城西菜场的改造。先说结论，工期要拖到年底。"
    assert hit_segment(norm(stitched), 0, nsegs()) is None
    # 各自那一半照样命中，证明不是文本本身有问题
    assert hit_segment(norm("今天聊城西菜场的改造。"), 0, nsegs()) is not None
    assert hit_segment(norm("先说结论，工期要拖到年底。"), 21, nsegs()) is not None


def test_ctx_is_the_whole_segment_nearest_to_the_timestamp():
    """同一句话说过两遍时取离 `ts` 最近的那一段：`ctx` 要的是他说这一句的那一处。"""
    repeated = "这句话我在下半场还会再说一遍。"
    assert hit_segment(norm(repeated), 1080, nsegs())["start"] == 1080.0
    assert hit_segment(norm(repeated), 880, nsegs())["start"] == 880.0


def test_a_quote_that_is_not_verbatim_is_dropped_and_counted():
    f = frag(quotes=[quote("改造预算是一千二百万，这个数是区里通报里写的。", "00:01:00"),
                     quote("改造预算是一千三百万", "00:01:00")])
    out, entry = gate(f)
    assert entry["quotes_dropped"] == 1 and entry["quotes_out_of_range"] == 0
    assert [q["text"] for q in out["quotes"]] == ["改造预算是一千二百万，这个数是区里通报里写的。"]
    assert out["quotes"][0]["ctx"] == "改造预算是一千二百万，这个数是区里通报里写的。"
    assert f["quotes"][1]["text"] == "改造预算是一千三百万"        # 入参没被就地改掉


# ---------------------------------------------------------------- 验收 4：闸门 2

def test_a_quote_two_minutes_past_the_topic_end_is_still_in_range():
    """话题范围前后各 2 分钟：人说着说着回头补一句是常事，卡太死要删掉真引文。"""
    text = "摊位现在是八十个，改造以后是一百个。"          # 段在 00:10:00
    out, entry = gate(frag(end="00:08:00", quotes=[quote(text, "00:10:00")]))
    assert entry["quotes_out_of_range"] == 0 and len(out["quotes"]) == 1

    out, entry = gate(frag(end="00:07:59", quotes=[quote(text, "00:10:00")]))
    assert entry["quotes_out_of_range"] == 1 and out["quotes"] == []
    assert entry["quotes_dropped"] == 0                    # 逐字是命中的，越界才是它的问题


def test_a_zero_length_topic_still_judges_by_the_two_minute_margin():
    """章内两个话题写了同一行时前一个长度为 0（§5.3），照样按 ±2 分钟判。"""
    text = "摊位现在是八十个，改造以后是一百个。"
    f = frag(start="00:09:00", end="00:09:00", quotes=[quote(text, "00:10:00")],
             paras=["[00:09:00] <who>阿桥</who>说摊位八十个。"])
    out, entry = gate(f)
    assert entry["quotes_out_of_range"] == 0 and entry["paras_out_of_range"] == []
    assert len(out["quotes"]) == 1


def test_a_paragraph_inside_the_chapter_padding_is_out_of_range_but_kept():
    """段落的时间戳落在章节 `start` 之前（上文余量里）算越界，哪怕它离话题 `start`
    不到 2 分钟——余量里的内容归相邻章写（ADR 0005）。

    **越界的段只记不删**（红线 2：不删事）：删掉的话人在笔记上再也看不见这段内容。
    """
    paras = ["[00:14:30] <who>阿桥</who>说这段其实是上一章的事。",
             "[00:15:30] <who>阿桥</who>说摊位数改造以后是一百个。"]
    f = frag(tid="ch2-01", chapter="ch2", start="00:15:00", end="00:20:00", paras=paras)
    out, entry = gate(f, chapter="ch2")
    assert entry["paras_out_of_range"] == ["00:14:30"]
    assert out["paras"] == paras                          # 一段都没删，一个字都没改


def test_a_paragraph_past_the_topic_margin_is_also_flagged():
    """两个条件是「且」：落在本章里、也落在话题 ±2 分钟里。"""
    f = frag(paras=["[00:00:00] <who>阿桥</who>说工期。",
                    "[00:12:30] <who>阿桥</who>说这段跑到别的话题去了。"])
    _, entry = gate(f)
    assert entry["paras_out_of_range"] == ["00:12:30"]


# ---------------------------------------------------------------- 闸门 5 的 ASR 条款

def test_an_asr_entry_not_in_the_chapter_slice_is_dropped():
    """`heard` 是逐字稿里的原写法，切片里找不到就不是这一章听出来的。"""
    nslice = [norm(t) for a, _, t in SEGS if a < 900 + 120]
    out, entry = gate(frag(asr=[{"heard": "西城菜场", "means": "城西菜场"},
                                {"heard": "城东菜场", "means": "城西菜场"}]),
                      nslice=nslice)
    assert entry["asr_dropped"] == 1
    assert out["asr"] == [{"heard": "西城菜场", "means": "城西菜场"}]


def test_the_asr_slice_includes_the_two_minute_context(tmp_path):
    """切片带前后各 2 分钟：`heard` 出现在余量那几行里也算数——L2 看到的就是这份
    文本（§5.2），闸门就该拿模型看到的那份去比。"""
    paths = build_vault(tmp_path, [frag(asr=[{"heard": "西城菜场", "means": "城西菜场"}])])
    report = run_gates(paths, "EP99", log=lambda _: None)
    # 「西城菜场」在 00:16:00 那一段，章 ch1 收在 00:15:00，靠 2 分钟余量捞回来
    assert report.topics["ch1-01"]["asr_dropped"] == 0
    assert read(paths.digest("EP99") / "frag-ch1-01.json")["asr"] == [
        {"heard": "西城菜场", "means": "城西菜场"}]


# ---------------------------------------------------------------- 验收 6、7：跑一集

def test_gates_json_and_write_back(tmp_path):
    paths = build_vault(tmp_path, [frag(quotes=[
        quote("先说结论，工期要拖到年底。", "00:00:00"),
        quote("工期要拖到明年年底", "00:00:00")])])
    report = run_gates(paths, "EP99", generated_at="2026-03-12T23:10:00+08:00",
                       log=lambda _: None)

    doc = read(paths.digest("EP99") / "gates.json")
    assert doc["ep"] == "EP99" and doc["generated_at"] == "2026-03-12T23:10:00+08:00"
    assert doc["topics"]["ch1-01"] == {"quotes_dropped": 1, "quotes_out_of_range": 0,
                                       "paras_out_of_range": [], "asr_dropped": 0,
                                       "schema": "ok"}
    written = read(paths.digest("EP99") / "frag-ch1-01.json")
    assert len(written["quotes"]) == 1
    assert written["quotes"][0]["ctx"] == "先说结论，工期要拖到年底。"
    assert report.totals == {"quotes_dropped": 1, "quotes_out_of_range": 0,
                             "asr_dropped": 0, "paras_out_of_range": 0}


def test_running_twice_changes_nothing(tmp_path):
    """验收 6：同一输入跑两次，第二次计数全 0、片段逐字节不变（`ctx` 也不重写）。"""
    paths = build_vault(tmp_path, [frag(quotes=[
        quote("先说结论，工期要拖到年底。", "00:00:00"),
        quote("工期要拖到明年年底", "00:00:00")])])
    run_gates(paths, "EP99", log=lambda _: None)
    first = (paths.digest("EP99") / "frag-ch1-01.json").read_bytes()
    stamp = (paths.digest("EP99") / "frag-ch1-01.json").stat().st_mtime_ns

    report = run_gates(paths, "EP99", log=lambda _: None)
    assert report.totals == {"quotes_dropped": 0, "quotes_out_of_range": 0,
                             "asr_dropped": 0, "paras_out_of_range": 0}
    assert (paths.digest("EP99") / "frag-ch1-01.json").read_bytes() == first
    # 没变就不落盘：盘上的时间是人找「这一趟到底改了什么」的线索
    assert (paths.digest("EP99") / "frag-ch1-01.json").stat().st_mtime_ns == stamp


def test_a_broken_fragment_raises_instead_of_passing_quietly(tmp_path):
    """验收 7 / 红线 9：JSON 坏了当场炸。吞掉的话它会被当成「没有引文」放行，
    笔记上是一节空话题，gates.json 还写着全 0。"""
    paths = build_vault(tmp_path, [frag()])
    (paths.digest("EP99") / "frag-ch1-01.json").write_bytes(b'{"id": "ch1-01",')
    with pytest.raises(ValueError):
        run_gates(paths, "EP99", log=lambda _: None)


def test_a_missing_fragment_raises(tmp_path):
    paths = build_vault(tmp_path, [frag()])
    (paths.digest("EP99") / "frag-ch1-01.json").unlink()
    with pytest.raises(OSError):
        run_gates(paths, "EP99", log=lambda _: None)


def test_an_orphan_fragment_raises(tmp_path):
    """片段指着章节表里没有的章（L1 重切过而 L2 没重跑）：闸门 2 与闸门 5 没有尺子
    可用，不许当成「全都通过」放行。"""
    paths = build_vault(tmp_path, [frag(chapter="ch9")])
    with pytest.raises(ValueError, match="ch9"):
        run_gates(paths, "EP99", log=lambda _: None)


def test_a_fragment_that_breaks_the_shape_is_recorded_not_raised(tmp_path):
    """形状不合 §5.4 记在 `schema` 那一栏，不抛也不删（失败态是 #54 的事）。"""
    bad = frag(kind="chat", paras=["没有行首时间戳的一段"])
    del bad["gist"]
    paths = build_vault(tmp_path, [bad])
    report = run_gates(paths, "EP99", log=lambda _: None)
    errs = report.topics["ch1-01"]["schema"]
    assert isinstance(errs, list)
    assert any("缺字段 `gist`" in e for e in errs)
    assert any("kind" in e for e in errs)
    assert any("不以 `[HH:MM:SS]` 开头" in e for e in errs)
    assert read(paths.digest("EP99") / "frag-ch1-01.json")["paras"] == bad["paras"]
