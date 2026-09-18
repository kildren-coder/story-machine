# -*- coding: utf-8 -*-
"""吞块补解（SPEC §4 阶段 0、issue #80）。

样例 `tests/fixtures/redecode/EP93.redecode.json` 是**合成**的（红线 10），由
`mk_redecode.py` 生成并自断言；这里不重复它的算术，只钉住规则层的行为。

`pc/` 不在 conftest 的 sys.path 里（那份只管 `scripts/`），本文件自己加。
"""
from __future__ import annotations

import ast
import copy
import io
import json
import subprocess
import sys
import types
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "pc"))

import redecode                                            # noqa: E402

FIX = REPO / "tests" / "fixtures" / "redecode" / "EP93.redecode.json"
SUSPECTS = {1, 2, 3, 4, 6, 7, 8}            # 验收 1
UNTOUCHED = {0, 5, 9, 4, 8}                 # 不疑似的 + 残留的：一个字节都不许动


def load() -> dict:
    return json.loads(FIX.read_bytes().decode("utf-8"))


def run_fixture(doc=None):
    """跑一遍规则层。返回 (doc, 原样输入的深拷贝, segs, words, rep, calls)。"""
    doc = doc or load()
    pristine = copy.deepcopy((doc["transcript"]["segments"], doc["words"]["segments"]))
    decode, calls = redecode.demo_decoder(doc)
    segs, words, rep = redecode.run(doc["chunks"], doc["transcript"]["segments"],
                                    doc["words"]["segments"], decode)
    return doc, pristine, segs, words, rep, calls


def blocks(rep) -> dict:
    return {b["k"]: b for b in rep["blocks"]}


def picked_decode(doc, k, length):
    return doc["decodes"][str(k)][str(length)]


# ---------------------------------------------------------------- 验收 1：判疑似
def test_the_seven_suspect_blocks_are_the_ones_the_fixture_names():
    _, _, _, _, rep, _ = run_fixture()
    assert set(blocks(rep)) == SUSPECTS
    assert rep["suspects"] == 7
    assert rep["chunks"] == 10


def test_a_short_block_is_never_suspect_however_few_words_it_has():
    """块 5：语音只有 6 秒 < 8——短块 EP02 实测 0/14 出事，不值得重解。"""
    doc = load()
    ch, seg, ws = doc["chunks"][5], doc["transcript"]["segments"][5], doc["words"]["segments"][5]
    assert redecode.speech_s(ch) < redecode.MIN_SPEECH_S
    assert redecode.n_han(seg["text"]) / redecode.speech_s(ch) < redecode.MIN_DENSITY
    assert not redecode.is_suspect(ch, seg["text"], ws)


def test_block_six_is_caught_by_the_hole_not_by_the_density():
    """块 6：字够密（4 字/秒），但最后 10 秒语音一个词都没有。"""
    doc = load()
    ch, seg, ws = doc["chunks"][6], doc["transcript"]["segments"][6], doc["words"]["segments"][6]
    assert redecode.n_han(seg["text"]) / redecode.speech_s(ch) >= redecode.MIN_DENSITY
    assert redecode.gap_s(ch, ws) >= redecode.MAX_GAP_S
    assert redecode.is_suspect(ch, seg["text"], ws)


def test_normal_blocks_are_neither_thin_nor_holey():
    doc = load()
    for k in (0, 9):
        ch, seg, ws = doc["chunks"][k], doc["transcript"]["segments"][k], doc["words"]["segments"][k]
        assert redecode.n_han(seg["text"]) / redecode.speech_s(ch) >= redecode.MIN_DENSITY
        assert redecode.gap_s(ch, ws) < redecode.MAX_GAP_S


def test_a_hole_at_the_head_or_the_tail_counts_too():
    ch = {"start": 0.0, "end": 20.0, "speech": [[0.0, 20.0]]}
    assert redecode.gap_s(ch, [[18.0, 20.0, "收尾"]]) == pytest.approx(18.0)   # 块首到第一个词
    assert redecode.gap_s(ch, [[0.0, 2.0, "开头"]]) == pytest.approx(18.0)     # 最后一个词到块尾
    assert redecode.gap_s(ch, []) == pytest.approx(20.0)                       # 一个词都没有
    # 空洞数的是 VAD 语音秒，不是墙上时间：中间那段静音不算
    quiet = {"start": 0.0, "end": 20.0, "speech": [[0.0, 2.0], [18.0, 20.0]]}
    assert redecode.gap_s(quiet, [[0.0, 2.0, "开头"], [18.0, 20.0, "收尾"]]) == pytest.approx(0.0)


# ---------------------------------------------------------------- 验收 2：每块的结局
def test_every_block_ends_exactly_where_the_fixture_expects():
    doc, _, _, _, rep, _ = run_fixture()
    by_k = blocks(rep)
    for k_str, exp in doc["expect"].items():
        k = int(k_str)
        if not exp["suspect"]:
            assert k not in by_k
            continue
        got = by_k[k]
        assert (got["picked"], got["residual"]) == (exp["picked"], exp["residual"]), k
    assert (rep["replaced"], rep["residual"]) == (5, 2)


# ---------------------------------------------------------------- 验收 3：没动过的块逐字节不变
def test_untouched_and_residual_blocks_are_byte_identical():
    _, (segs0, words0), segs, words, _, _ = run_fixture()
    for k in sorted(UNTOUCHED):
        assert json.dumps(segs[k], ensure_ascii=False, sort_keys=True) == \
               json.dumps(segs0[k], ensure_ascii=False, sort_keys=True), k
        assert json.dumps(words[k], ensure_ascii=False) == \
               json.dumps(words0[k], ensure_ascii=False), k


def test_the_inputs_are_not_mutated():
    """正本还在调用方手里：补解只能返回新的，不能就地改。"""
    doc, (segs0, words0), segs, words, _, _ = run_fixture()
    assert doc["transcript"]["segments"] == segs0
    assert doc["words"]["segments"] == words0
    assert segs is not doc["transcript"]["segments"]
    for k in sorted(UNTOUCHED):                      # 没换的块原样带回，同一个对象
        assert segs[k] is doc["transcript"]["segments"][k]


def test_the_segment_count_never_changes():
    doc, _, segs, words, _, _ = run_fixture()
    assert len(segs) == len(words) == len(doc["chunks"]) == 10


# ---------------------------------------------------------------- 验收 4：不引入解码输出以外的字
def test_replaced_segments_contain_nothing_the_decoder_did_not_write():
    """红线 1：补解是重听，不是改写。每个字都必须逐字来自取中那一级的输出。"""
    doc, (segs0, _), segs, words, rep, _ = run_fixture()
    replaced = [b for b in rep["blocks"] if b["picked"] is not None]
    assert [b["k"] for b in replaced] == [1, 2, 3, 6, 7]
    for b in replaced:
        k, d = b["k"], picked_decode(doc, b["k"], b["picked"])
        assert segs[k]["text"] == "".join(s["text"] for s in d["segments"])
        assert words[k] == [w for sw in d["words"] for w in sw]
        assert "".join(w[2] for w in words[k]) == segs[k]["text"]
        # 时刻也来自那一级，不留第一遍被吞剩的旧跨度
        assert segs[k]["start"] == d["segments"][0]["start"]
        assert segs[k]["end"] == d["segments"][-1]["end"]
        # 补回来的内容让跨度变宽了（丢头的往前长，丢尾的往后长）
        assert segs[k]["end"] - segs[k]["start"] > segs0[k]["end"] - segs0[k]["start"]
        assert segs[k]["speaker"] is None and list(segs[k]) == list(segs0[k])
        assert all(len(w) == 3 for w in words[k])    # 词表照旧是平的 [[s, e, 词], ...]


def test_the_whole_transcript_only_grows_by_what_was_recovered():
    doc, _, segs, _, rep, _ = run_fixture()
    assert rep["han_before"] == sum(redecode.n_han(s["text"])
                                    for s in doc["transcript"]["segments"])
    assert rep["han_after"] == sum(redecode.n_han(s["text"]) for s in segs)
    gained = sum(b["after"]["han"] - b["before"]["han"] for b in rep["blocks"])
    assert rep["han_after"] - rep["han_before"] == gained > 0


# ---------------------------------------------------------------- 验收 5：阶梯按规则走
def test_the_ladder_stops_as_soon_as_the_block_is_no_longer_suspect():
    _, _, _, _, rep, calls = run_fixture()
    per_k = {}
    for k, length in calls:
        per_k.setdefault(k, []).append(length)
    assert per_k == {1: [15], 6: [15],            # 15 秒就补全了，不再解 10、7
                     2: [15, 10], 3: [15, 10], 7: [15, 10],
                     4: [15, 10, 7], 8: [15, 10, 7]}
    assert len(calls) == 14                        # 每个疑似块至多 3 次
    assert all(b["k"] in SUSPECTS for b in rep["blocks"])


def test_block_two_takes_the_fifteen_second_version_and_still_goes_on():
    """15 秒版可参选、字也最多，但块内还空着 10 秒——仍疑似，所以继续解 10 秒。"""
    doc, _, segs, _, rep, _ = run_fixture()
    ch, seg = doc["chunks"][2], doc["transcript"]["segments"][2]
    d15 = picked_decode(doc, 2, 15)
    t15 = "".join(s["text"] for s in d15["segments"])
    w15 = [w for sw in d15["words"] for w in sw]
    assert redecode.acceptable(seg["text"], t15)[0]
    assert redecode.n_han(t15) > redecode.n_han(seg["text"])
    assert redecode.is_suspect(ch, t15, w15)               # 仍疑似 → 进下一级
    entry = blocks(rep)[2]
    assert entry["tries"][0] == {"chunk_length": 15, "han": redecode.n_han(t15),
                                 "gap": round(redecode.gap_s(ch, w15), 2),
                                 "rep4": redecode.rep4(t15), "acceptable": True,
                                 "reason": None, "error": None}
    assert entry["picked"] == 10 and not entry["residual"]
    assert not redecode.is_suspect(ch, segs[2]["text"], _w(doc, 2, 10))
    assert entry["after"]["gap"] < redecode.MAX_GAP_S


def _w(doc, k, length):
    return [w for sw in picked_decode(doc, k, length)["words"] for w in sw]


def test_a_later_rung_only_wins_if_it_has_more_han():
    """取中的是「原文和已解各版里汉字最多的可参选版」，不是「最后一个可参选版」。"""
    long_text = ("河口夜市搬迁以后生意变差了不少老周说货车的费率明年还要再涨一点"
                 "阿桥在弹幕里问大桥什么时候通车我觉得这件事情还要再等一等看看")
    ch = {"start": 0.0, "end": 20.0, "speech": [[0.0, 20.0]]}
    seg = {"start": 0.0, "end": 1.0, "speaker": None, "text": long_text[:4]}
    words = [[0.0, 1.0, long_text[:4]]]
    # 15 秒版字最多，但块内还空着 10 秒 → 仍疑似，阶梯继续；10、7 两级也可参选，
    # 只是字更少，不许把它顶掉。
    table = {15: (long_text, 0.0, 10.0),
             10: (long_text[:40], 0.0, 20.0),
             7: (long_text[:45], 0.0, 20.0)}

    def decode(k, start, end, length):
        text, s, e = table[length]
        return [{"start": s, "end": e, "text": text}], [[[s, e, text]]]

    segs, _, rep = redecode.run([ch], [seg], [words], decode)
    entry = rep["blocks"][0]
    assert [t["acceptable"] for t in entry["tries"]] == [True, True, True]
    assert [t["han"] for t in entry["tries"]] == [61, 40, 45]
    assert entry["picked"] == 15 and entry["after"]["han"] == 61
    assert segs[0]["text"] == long_text
    assert entry["residual"] is True and rep["residual"] == rep["replaced"] == 1


# ---------------------------------------------------------------- 验收 6：不参选的原因进报告
def test_a_looping_version_is_rejected_and_the_report_says_so():
    """块 3 的 15 秒版字最多，但同一个 4 字串复读了几十次——幻觉，不参选。"""
    doc, _, segs, _, rep, _ = run_fixture()
    try15 = blocks(rep)[3]["tries"][0]
    assert try15["chunk_length"] == 15 and try15["acceptable"] is False
    assert "rep4" in try15["reason"] and try15["error"] is None
    assert try15["rep4"] > redecode.MAX_REP4
    assert try15["han"] > blocks(rep)[3]["tries"][1]["han"]     # 字确实最多
    loop = "".join(s["text"] for s in picked_decode(doc, 3, 15)["segments"])
    assert loop not in segs[3]["text"] and segs[3]["text"] != loop


def test_a_version_that_lost_the_original_text_is_rejected_and_the_report_says_so():
    """块 7 的 15 秒版字也多，但原文只有 10% 按序出现在里面——听的不是这一段。"""
    _, _, _, _, rep, _ = run_fixture()
    try15 = blocks(rep)[7]["tries"][0]
    assert try15["acceptable"] is False and "kept" in try15["reason"]
    assert try15["han"] >= redecode.MIN_GAIN_HAN and try15["rep4"] <= redecode.MAX_REP4


def test_a_version_that_barely_adds_anything_is_rejected():
    """块 4：三级都只多几个字，一级都不参选 → 保留原文。"""
    _, _, _, _, rep, _ = run_fixture()
    entry = blocks(rep)[4]
    assert [t["chunk_length"] for t in entry["tries"]] == [15, 10, 7]
    assert all(t["acceptable"] is False and "gain" in t["reason"] for t in entry["tries"])
    assert entry["picked"] is None and entry["residual"] is True


def test_acceptable_reports_every_reason_it_failed_on():
    ok, why = redecode.acceptable("河口夜市", "河口夜市")
    assert (ok, why) == (False, "gain=0<20")
    ok, why = redecode.acceptable("河口夜市搬迁以后", "好的好的" * 30)
    assert ok is False and "gain" not in why and "kept=" in why and "rep4=" in why


def test_kept_ratio_is_vacuously_true_when_the_block_was_swallowed_whole():
    """整块被吞光（原文 0 汉字）正是最该补的情形，不能因为除零把它挡在门外。"""
    assert redecode.kept_ratio("", "河口夜市搬迁") == 1.0
    assert redecode.kept_ratio("河口夜市", "河口夜市搬迁以后") == 1.0
    assert redecode.kept_ratio("河口夜市", "春天雨水多的时候") < redecode.MIN_KEPT


# ---------------------------------------------------------------- 验收 7：三级都报错
def test_three_failed_decodes_leave_the_block_alone_and_are_all_reported():
    doc, (segs0, words0), segs, words, rep, _ = run_fixture()
    entry = blocks(rep)[8]
    assert [t["chunk_length"] for t in entry["tries"]] == [15, 10, 7]
    assert all(t["error"] and "CUDA out of memory" in t["error"] for t in entry["tries"])
    assert all(t["han"] is None and t["acceptable"] is False for t in entry["tries"])
    assert entry["picked"] is None and entry["residual"] is True
    assert rep["errors"] == 3
    assert segs[8] == segs0[8] and words[8] == words0[8]
    # 别的块照常处理：报错的块不能拖垮整步
    assert rep["replaced"] == 5 and set(blocks(rep)) == SUSPECTS


def test_one_broken_rung_does_not_stop_the_next_one():
    doc = load()
    doc["decodes"]["1"]["15"] = {"error": "boom"}
    doc["decodes"]["1"]["10"] = load()["decodes"]["1"]["15"]
    _, _, _, _, rep, calls = run_fixture(doc)
    entry = blocks(rep)[1]
    assert entry["tries"][0]["error"] == "RuntimeError: boom"
    assert entry["picked"] == 10 and not entry["residual"]
    assert (1, 15) in calls and (1, 10) in calls and (1, 7) not in calls


def test_a_decoder_whose_words_do_not_spell_the_text_is_treated_as_a_failure():
    """smdiar 按词重建段且不许改文本——词和文本对不上的版本不能进正本。"""
    ch = {"start": 0.0, "end": 20.0, "speech": [[0.0, 20.0]]}
    seg = {"start": 0.0, "end": 2.0, "speaker": None, "text": "开头两句"}
    text = "河口夜市搬迁以后生意变差了不少老周说货车的费率明年还要再涨一点"

    def decode(k, start, end, length):
        return ([{"start": 0.0, "end": 20.0, "text": text}],
                [[[0.0, 20.0, text[:10]]]])        # 词少了一截

    segs, words, rep = redecode.run([ch], [seg], [[[0.0, 2.0, "开头两句"]]], decode)
    assert [t["error"] for t in rep["blocks"][0]["tries"]] == ["words != text"] * 3
    assert rep["errors"] == 3 and rep["replaced"] == 0
    assert segs[0] == seg and words[0] == [[0.0, 2.0, "开头两句"]]


def test_whitespace_alone_does_not_count_as_a_mismatch():
    """faster-whisper 的词带前导空格，段文本不一定；check_diar.py 也是这把尺子。"""
    ch = {"start": 0.0, "end": 20.0, "speech": [[0.0, 20.0]]}
    seg = {"start": 0.0, "end": 2.0, "speaker": None, "text": "河口夜市"}
    text = " 河口夜市搬迁以后生意变差了不少老周说货车的费率明年还要再涨一点"

    def decode(k, start, end, length):
        return ([{"start": 0.0, "end": 20.0, "text": text}],
                [[[0.0, 20.0, text.strip()]]])

    segs, _, rep = redecode.run([ch], [seg], [[[0.0, 2.0, "河口夜市"]]], decode)
    assert rep["errors"] == 0 and rep["replaced"] == 1
    assert segs[0]["text"] == text                 # 文本照旧逐字来自解码输出


# ---------------------------------------------------------------- 验收 8：段数 ≠ 块数
def test_a_segment_count_mismatch_skips_the_whole_step():
    """块 k 对不上段 k 时，补解会改错块——宁可整步不跑（红线 1）。"""
    doc = load()
    del doc["transcript"]["segments"][5]
    del doc["words"]["segments"][5]
    _, (segs0, words0), segs, words, rep, calls = run_fixture(doc)
    assert rep["skipped"] == "segments != chunks (9 vs 10)"
    assert calls == [] and rep["suspects"] == rep["replaced"] == rep["errors"] == 0
    assert rep["chunks"] == 10          # 跳过了也要照实说复算出几块，好对着查
    assert segs == segs0 and words == words0
    assert rep["han_before"] == rep["han_after"] == sum(
        redecode.n_han(s["text"]) for s in segs0)


def test_a_words_count_mismatch_skips_the_whole_step_too():
    doc = load()
    del doc["words"]["segments"][5]
    _, _, segs, words, rep, calls = run_fixture(doc)
    assert rep["skipped"] == "words != segments (9 vs 10)"
    assert calls == [] and len(segs) == 10 and len(words) == 9
    assert rep["chunks"] == 10


# ---------------------------------------------------------------- 验收 9：报告的字段
def test_the_report_has_exactly_the_agreed_fields():
    _, _, _, _, rep, _ = run_fixture()
    assert set(rep) == {"rule", "chunks", "suspects", "replaced", "residual", "errors",
                        "skipped", "elapsed_s", "han_before", "han_after", "blocks"}
    assert rep["rule"] == {"min_speech_s": 8, "min_density": 3, "max_gap_s": 5,
                           "ladder": [15, 10, 7], "min_gain_han": 20, "min_kept": 0.8,
                           "max_rep4": 5, "max_chunk_speech_s": 30}
    for b in rep["blocks"]:
        assert set(b) == {"k", "start", "end", "speech_s", "before", "tries",
                          "picked", "after", "residual"}
        assert set(b["before"]) == set(b["after"]) == {"han", "gap"}
        for t in b["tries"]:
            assert set(t) == {"chunk_length", "han", "gap", "rep4", "acceptable",
                              "reason", "error"}
            assert t["chunk_length"] in redecode.LADDER
        assert b["picked"] in (None,) + redecode.LADDER
        assert b["k"] in SUSPECTS and b["speech_s"] >= redecode.MIN_SPEECH_S


def test_the_report_is_json_serialisable_as_is():
    """它要原样进 transcript.json 的顶层。"""
    _, _, _, _, rep, _ = run_fixture()
    assert json.loads(json.dumps(rep, ensure_ascii=False)) == rep


def test_the_rule_block_records_the_constants_actually_in_force():
    assert redecode.rule() == {
        "min_speech_s": redecode.MIN_SPEECH_S, "min_density": redecode.MIN_DENSITY,
        "max_gap_s": redecode.MAX_GAP_S, "ladder": list(redecode.LADDER),
        "min_gain_han": redecode.MIN_GAIN_HAN, "min_kept": redecode.MIN_KEPT,
        "max_rep4": redecode.MAX_REP4,
        "max_chunk_speech_s": redecode.MAX_CHUNK_SPEECH_S}


# ---------------------------------------------------------------- 验收 10：只有标准库
def test_redecode_imports_nothing_outside_the_standard_library():
    tree = ast.parse((REPO / "pc" / "redecode.py").read_bytes().decode("utf-8"))
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.level == 0:
            names.add((node.module or "").split(".")[0])
    assert names and names <= set(sys.stdlib_module_names), sorted(names)


def test_redecode_imports_on_a_machine_without_numpy_or_faster_whisper():
    """沙箱镜像就是这样的机器；规则层必须在那里也能 import、能跑。"""
    src = (
        "import sys\n"
        "for m in ('numpy', 'faster_whisper', 'opencc', 'torch'): sys.modules[m] = None\n"
        "sys.path.insert(0, %r)\n"
        "import redecode\n"
        "print(redecode.LADDER, redecode.n_han('河口夜市 abc 123'))\n" % str(REPO / "pc")
    )
    p = subprocess.run([sys.executable, "-c", src], capture_output=True, text=True)
    assert p.returncode == 0, p.stderr
    assert p.stdout.strip() == "(15, 10, 7) 4"


# ---------------------------------------------------------------- 演示（issue 的「可见变化」）
def test_the_demo_command_runs_and_agrees_with_the_fixture():
    p = subprocess.run([sys.executable, str(REPO / "pc" / "redecode.py"),
                        "--demo", str(FIX)], capture_output=True, text=True,
                       encoding="utf-8")
    assert p.returncode == 0, p.stdout + p.stderr
    assert "与样例 expect 逐块一致。" in p.stdout
    assert ("INFO redecode: suspects=7 replaced=5 residual=2 errors=3 han=414->872"
            in p.stdout)
    for k in sorted(SUSPECTS):
        assert "块 %d" % k in p.stdout


def test_the_demo_fails_loudly_when_the_rules_stop_matching_the_fixture(tmp_path):
    doc = load()
    doc["expect"]["1"]["picked"] = 7
    tmp = tmp_path / "EP93.redecode.json"          # 不许写回 tests/fixtures/
    tmp.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    p = subprocess.run([sys.executable, str(REPO / "pc" / "redecode.py"),
                        "--demo", str(tmp)], capture_output=True, text=True,
                       encoding="utf-8")
    assert p.returncode == 1
    assert "与样例 expect 不符" in p.stdout


# ---------------------------------------------------------------- 合块（照抄 collect_chunks）
def test_speech_is_grouped_until_thirty_seconds_of_it_pile_up():
    speech = [[0.0, 10.0], [12.0, 22.0], [24.0, 34.0],      # 30 秒整，还塞得下
              [40.0, 41.0],                                  # 第 31 秒 → 另起一块
              [50.0, 80.0]]                                  # 满一块
    got = redecode.group_chunks(speech)
    assert [c["k"] for c in got] == [0, 1, 2]
    assert [(c["start"], c["end"]) for c in got] == [(0.0, 34.0), (40.0, 41.0), (50.0, 80.0)]
    assert got[0]["speech"] == [[0.0, 10.0], [12.0, 22.0], [24.0, 34.0]]
    assert all(redecode.speech_s(c) <= redecode.MAX_CHUNK_SPEECH_S for c in got)


def test_grouping_edge_cases():
    assert redecode.group_chunks([]) == []
    one = redecode.group_chunks([[1.0, 2.0]])
    assert one == [{"k": 0, "start": 1.0, "end": 2.0, "speech": [[1.0, 2.0]]}]
    # 单段就超上限（VAD 的 max_speech_duration_s 之外的意外）也要自成一块，不丢
    assert len(redecode.group_chunks([[0.0, 45.0], [46.0, 47.0]])) == 2


# 六段语音，样点数加起来恰好 480000 = 30.000 s（VAD 强切加两侧补齐就会凑出这种块；
# EP01 有 2 处、EP02 有 1 处）。collect_chunks 在整数样点上比「> 480000」判成不超；
# 换成浮点秒累加得 30.000000000000004，没有容差就会多切一刀，后面全部错位。
EXACT_30S_SAMPLES = [(3552, 34756), (65161, 214182), (221760, 294041),
                     (312813, 338642), (347586, 386116), (425229, 588364)]
SR = 16000


def test_grouping_judges_an_exact_thirty_second_sum_like_collect_chunks_does():
    assert sum(b - a for a, b in EXACT_30S_SAMPLES) == 30 * SR
    speech = [[a / SR, b / SR] for a, b in EXACT_30S_SAMPLES]
    acc = 0.0
    for s, e in speech:
        acc += e - s
    assert acc > 30.0                       # 浮点累加确实越界了——这就是要防的那一下
    assert len(redecode.group_chunks(speech)) == 1
    # 真多一个样点就该切：容差不能大到把 480001 也放过
    over = EXACT_30S_SAMPLES[:-1] + [(425229, 588365)]
    assert len(redecode.group_chunks([[a / SR, b / SR] for a, b in over])) == 2


def test_grouping_keeps_every_speech_interval_exactly_once():
    doc = load()
    speech = [iv for c in doc["chunks"] for iv in c["speech"]]
    assert [iv for c in redecode.group_chunks(speech) for iv in c["speech"]] == speech


# ---------------------------------------------------------------- smpc.py 的接线
@pytest.fixture(scope="module")
def smpc():
    """import 时要 reconfigure stdout；给它一个真 TextIOWrapper，别赌 pytest 的捕获对象。"""
    real = sys.stdout
    sys.stdout = io.TextIOWrapper(io.BytesIO(), encoding="utf-8")
    try:
        import smpc as mod
    finally:
        sys.stdout = real
    return mod


class FakeWord:
    def __init__(self, start, end, word):
        self.start, self.end, self.word = start, end, word


class FakeSeg:
    def __init__(self, start, end, text, words):
        self.start, self.end, self.text, self.words = start, end, text, words


# 一个繁体字（遷）：用来证明重解出来的文本和词都过了同一张 t2s 字表
HEARD = "河口夜市搬遷以后生意变差了不少老周说货车的费率明年还要再涨一点"


class FakePipe:
    """只记下自己被怎么调的；不解码。"""
    def __init__(self):
        self.last_speech_timestamp = 7.5       # 上一次调用留下的脏值
        self.calls = []

    def transcribe(self, audio, **kw):
        self.calls.append({"n": len(audio), "head": audio[0], "kw": dict(kw),
                           "last_speech_timestamp": self.last_speech_timestamp})
        self.last_speech_timestamp = 99.0      # 不清零就会拖进下一块
        words = [FakeWord(0.5, 10.5, HEARD[:10]), FakeWord(10.5, 20.5, HEARD[10:20]),
                 FakeWord(20.5, 24.5, HEARD[20:])]
        return [FakeSeg(0.5, 24.5, HEARD, words)], object()


def fake_faster_whisper(monkeypatch, pcm, speech_samples):
    audio_mod = types.ModuleType("faster_whisper.audio")
    audio_mod.decode_audio = lambda path, sampling_rate=16000: pcm
    vad_mod = types.ModuleType("faster_whisper.vad")
    seen = {}

    class VadOptions:
        def __init__(self, **kw):
            seen.update(kw)

    vad_mod.VadOptions = VadOptions
    vad_mod.get_speech_timestamps = lambda a, opts: [{"start": s, "end": e}
                                                     for s, e in speech_samples]
    pkg = types.ModuleType("faster_whisper")
    pkg.audio, pkg.vad = audio_mod, vad_mod
    for name, mod in (("faster_whisper", pkg), ("faster_whisper.audio", audio_mod),
                      ("faster_whisper.vad", vad_mod)):
        monkeypatch.setitem(sys.modules, name, mod)
    return seen


def test_smpc_recomputes_the_blocks_and_redecodes_the_swallowed_one(smpc, monkeypatch):
    sr = smpc.SR
    pcm = list(range(100 * sr))                       # 100 秒「音频」，切片看得出边界
    speech = [(0 * sr, 25 * sr), (30 * sr, 55 * sr)]  # 两块，各 25 秒语音
    seen = fake_faster_whisper(monkeypatch, pcm, speech)
    monkeypatch.setattr(smpc, "to_simplified", lambda t: t.replace("遷", "迁"))

    intact = ("河口夜市搬迁以后生意变差了不少老周说货车的费率明年还要再涨一点"
              "阿桥在弹幕里问大桥什么时候通车我觉得这件事情还要再等一等看看"
              "河口市上个礼拜刚刚发了一个新通知")   # 密度够、无空洞 → 不疑似
    segments = [{"start": 0.0, "end": 24.5, "speaker": None, "text": intact},
                {"start": 30.0, "end": 31.0, "speaker": None, "text": "河口夜市"}]
    words = [[[0.0, 24.5, intact]], [[30.0, 31.0, "河口夜市"]]]
    pipe = FakePipe()
    kw = {"language": "zh", "vad_filter": True, "word_timestamps": True, "batch_size": 16}

    segs, ws, rep = smpc.redecode_pass(pipe, "EP93.m4a", kw, segments, words, 100.0)

    assert seen == {"max_speech_duration_s": 30, "min_silence_duration_ms": 160}
    assert rep["skipped"] is None and rep["chunks"] == 2
    assert (rep["suspects"], rep["replaced"], rep["errors"]) == (1, 1, 0)
    assert kw == {"language": "zh", "vad_filter": True, "word_timestamps": True,
                  "batch_size": 16}, "第一遍的 kw 不许被就地改"

    # 只加 chunk_length，逐级走；每一级调用前 last_speech_timestamp 都清零
    assert [c["kw"] for c in pipe.calls] == [dict(kw, chunk_length=x) for x in (15, 10, 7)]
    assert [c["last_speech_timestamp"] for c in pipe.calls] == [0, 0, 0]
    assert [(c["n"], c["head"]) for c in pipe.calls] == [(25 * sr, 30 * sr)] * 3
    # 时间加块起点；文本和词都过同一个 t2s（遷 → 迁）
    assert segs[1]["text"] == HEARD.replace("遷", "迁")
    assert (segs[1]["start"], segs[1]["end"]) == (30.5, 54.5)
    assert ws[1] == [[30.5, 40.5, "河口夜市搬迁以后生意"], [40.5, 50.5, "变差了不少老周说货车"],
                     [50.5, 54.5, "的费率明年还要再涨一点"]]
    assert "".join(w[2] for w in ws[1]) == segs[1]["text"]
    assert segs[0] is segments[0] and ws[0] is words[0]      # 另一块一个字节没动
    assert rep["elapsed_s"] is not None
    # 31 字 / 25 秒还是不到 3 字/秒：补回来了但仍疑似，记残留，不再重试
    assert rep["residual"] == 1 and rep["blocks"][0]["picked"] == 15


def test_smpc_skips_the_step_when_the_vad_recompute_blows_up(smpc, monkeypatch):
    fake_faster_whisper(monkeypatch, [], [])
    monkeypatch.setattr(sys.modules["faster_whisper.audio"], "decode_audio",
                        lambda *a, **k: (_ for _ in ()).throw(OSError("ffmpeg not found")))
    segments = [{"start": 0.0, "end": 1.0, "speaker": None, "text": "河口夜市"}]
    pipe = FakePipe()
    segs, ws, rep = smpc.redecode_pass(pipe, "EP93.m4a", {}, segments, [[]], 10.0)
    assert "vad recompute failed" in rep["skipped"] and "ffmpeg not found" in rep["skipped"]
    assert (segs, ws) == (segments, [[]]) and pipe.calls == []
    assert rep["replaced"] == 0 and rep["blocks"] == []
    assert smpc.ascii_only(rep["skipped"]).isascii()


def test_smpc_never_lets_the_redecode_step_take_the_transcript_down(smpc, monkeypatch):
    """补解跑在写盘之前：从这里漏出去的异常会让几小时的转写一个字都落不了盘。"""
    sr = smpc.SR
    fake_faster_whisper(monkeypatch, list(range(30 * sr)), [(0, 25 * sr)])
    segments = [{"start": 0.0, "end": 1.0, "speaker": None, "text": "河口夜市"}]
    words = [[[0.0]]]                       # 词表坏了：规则层算空洞时会炸
    pipe = FakePipe()
    with pytest.raises(IndexError):         # 规则层自己不兜，兜在 smpc 这一层
        redecode.run([{"k": 0, "start": 0.0, "end": 25.0, "speech": [[0.0, 25.0]]}],
                     segments, words, lambda *a: ([], []))

    segs, ws, rep = smpc.redecode_pass(pipe, "EP93.m4a", {}, segments, words, 30.0)
    assert rep["skipped"].startswith("redecode failed: IndexError")
    assert (segs, ws) == (segments, words) and rep["replaced"] == 0
    assert rep["elapsed_s"] is not None and smpc.ascii_only(rep["skipped"]).isascii()


def test_smpc_writes_the_report_and_marks_the_config(smpc):
    """`config` 只在补解真跑了的时候才追加 ` redecode`；跳过了不许冒充跑过。"""
    src = (REPO / "pc" / "smpc.py").read_bytes().decode("utf-8")
    assert '"redecode": red,' in src
    assert '("" if red["skipped"] else " redecode")' in src
    # 补解在写盘之前：正本一旦落地就不可变，不回补
    assert src.index("redecode_pass(pipe") < src.index("dest.write_text")
    assert src.index("redecode_pass(pipe") < src.index('ep + ".words.json"')


def test_the_worker_log_line_is_plain_ascii(smpc):
    line = ("redecode: suspects=%d replaced=%d residual=%d errors=%d han=%d->%d in %.0fs"
            % (33, 30, 3, 1, 39535, 42985, 121.4))
    assert line.isascii()
    assert smpc.ascii_only("补解 failed: 找不到 ffmpeg").isascii()


def test_setup_pipeline_ships_redecode_next_to_smpc():
    """smpc.py import redecode——少传一个，PC 上连 download 都起不来。"""
    ps1 = (REPO / "scripts" / "setup-pipeline.ps1").read_bytes().decode("utf-8")
    assert "'smpc.py', 'redecode.py'" in ps1
    assert 'Join-Path $Repo "pc\\$f"' in ps1


# ---------------------------------------------------------------- 真机逮到的：numpy 标量进了报告
# 沙箱没有 numpy，用两个替身仿它的两条性质：float64 是 float 的子类，但算术和比较吐的
# 仍是 numpy 类型；numpy 的 bool 不是 Python bool（json 不认）。
class NpBool:
    def __init__(self, v):
        self.v = bool(v)

    def __bool__(self):
        return self.v


class NpFloat(float):
    def __add__(self, o):
        return NpFloat(float(self) + float(o))

    __radd__ = __add__

    def __sub__(self, o):
        return NpFloat(float(self) - float(o))

    def __rsub__(self, o):
        return NpFloat(float(o) - float(self))

    def __lt__(self, o):
        return NpBool(float(self) < float(o))

    def __le__(self, o):
        return NpBool(float(self) <= float(o))

    def __gt__(self, o):
        return NpBool(float(self) > float(o))

    def __ge__(self, o):
        return NpBool(float(self) >= float(o))


def test_the_report_is_json_serialisable_when_word_times_are_numpy_scalars():
    """EP02 音频真跑逮到的：词时刻是 numpy 标量 → 空洞是 numpy float → `residual` 是
    numpy bool → 写正本时 `TypeError: Object of type bool is not JSON serializable`，
    几分钟 GPU 白跑、一个字都没落盘。规则层的量一律收成内建类型。"""
    doc = load()
    words = [[[NpFloat(w[0]), NpFloat(w[1]), w[2]] for w in ws] for ws in doc["words"]["segments"]]
    assert not isinstance(NpFloat(1.0) >= 0.5, bool)           # 替身确实仿到了那条性质
    decode, _ = redecode.demo_decoder(doc)
    _, _, rep = redecode.run(doc["chunks"], doc["transcript"]["segments"], words, decode)
    json.dumps(rep)
    for b in rep["blocks"]:
        assert type(b["residual"]) is bool, b["k"]
        assert type(b["before"]["gap"]) is float and type(b["speech_s"]) is float, b["k"]
    ch = doc["chunks"][4]
    assert type(redecode.gap_s(ch, words[4])) is float
    assert type(redecode.is_suspect(ch, doc["transcript"]["segments"][4]["text"], words[4])) is bool


def test_smpc_drops_what_it_cannot_serialise_instead_of_crashing_at_write_time(smpc, monkeypatch):
    """兜底的兜底：规则层再漏出什么 json 不认的东西，也要在补解这一步失败，不能拖到写盘。"""
    segments = [{"start": 0.0, "end": 1.0, "speaker": None, "text": "河口夜市"}]
    words = [[[0.0, 1.0, "河口夜市"]]]
    poisoned = ([dict(segments[0], text="河口夜市搬迁")], words,
                dict(redecode.skipped(None, segments), blocks=[{"residual": NpBool(True)}]))
    monkeypatch.setattr(smpc, "_redecode", lambda *a: poisoned)
    segs, ws, rep = smpc.redecode_pass(FakePipe(), "EP93.m4a", {}, segments, words, 10.0)
    assert rep["skipped"].startswith("redecode failed: TypeError")
    assert segs is segments and ws is words and segs[0]["text"] == "河口夜市"
    json.dumps([segs, ws, rep])
