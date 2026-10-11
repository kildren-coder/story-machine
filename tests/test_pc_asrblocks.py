# -*- coding: utf-8 -*-
"""阶段 0 转写换 FireRedASR2-AED（SPEC §4 阶段 0、ADR 0006、issue #85）。

样例 `tests/fixtures/asrblocks/EP95.asrblocks.json` 是**合成**的（红线 10），由
`mk_asrblocks.py` 生成并自断言。引擎本身（torch / FireRedASR2S）沙箱里没有，真跑归 5070；
这里钉住规则层、smpc 的接线（假引擎）和 PC 侧脚本的静态契约。

`pc/` 不在 conftest 的 sys.path 里（那份只管 `scripts/`），本文件自己加。
"""
from __future__ import annotations

import ast
import io
import json
import re
import subprocess
import sys
import types
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "pc"))

import asrblocks                                           # noqa: E402

FIX = REPO / "tests" / "fixtures" / "asrblocks" / "EP95.asrblocks.json"
SR = 16000


def load() -> dict:
    return json.loads(FIX.read_bytes().decode("utf-8"))


def run_fixture(doc=None, **kw):
    doc = doc or load()
    blocks = asrblocks.make_blocks(doc["speech"])
    decode, calls = asrblocks.demo_decoder(doc)
    segs, words, asr = asrblocks.run(blocks, decode, **kw)
    return doc, blocks, segs, words, asr, calls


def seg_at(segs, words, start):
    for s, w in zip(segs, words):
        if s["start"] == start:
            return s, w
    raise KeyError(start)


# ---------------------------------------------------------------- 验收 1：合块（搬自 redecode.py，行为不变）
def test_speech_is_grouped_until_thirty_seconds_of_it_pile_up():
    speech = [[0.0, 10.0], [12.0, 22.0], [24.0, 34.0],      # 30 秒整，还塞得下
              [40.0, 41.0],                                  # 第 31 秒 → 另起一块
              [50.0, 80.0]]                                  # 满一块
    got = asrblocks.group_chunks(speech)
    assert [c["k"] for c in got] == [0, 1, 2]
    assert [(c["start"], c["end"]) for c in got] == [(0.0, 34.0), (40.0, 41.0), (50.0, 80.0)]
    assert got[0]["speech"] == [[0.0, 10.0], [12.0, 22.0], [24.0, 34.0]]


def test_grouping_edge_cases():
    assert asrblocks.group_chunks([]) == []
    one = asrblocks.group_chunks([[1.0, 2.0]])
    assert one == [{"k": 0, "start": 1.0, "end": 2.0, "speech": [[1.0, 2.0]]}]
    # 单段就超上限（VAD 的 max_speech_duration_s 之外的意外）也要自成一块，不丢
    assert len(asrblocks.group_chunks([[0.0, 45.0], [46.0, 47.0]])) == 2


# 六段语音，样点数加起来恰好 480000 = 30.000 s（VAD 强切加两侧补齐就会凑出这种块；
# EP01 有 2 处、EP02 有 1 处）。collect_chunks 在整数样点上比「> 480000」判成不超；
# 换成浮点秒累加得 30.000000000000004，没有容差就会多切一刀，后面全部错位。
EXACT_30S_SAMPLES = [(3552, 34756), (65161, 214182), (221760, 294041),
                     (312813, 338642), (347586, 386116), (425229, 588364)]


def test_grouping_judges_an_exact_thirty_second_sum_like_collect_chunks_does():
    assert sum(b - a for a, b in EXACT_30S_SAMPLES) == 30 * SR
    speech = [[a / SR, b / SR] for a, b in EXACT_30S_SAMPLES]
    acc = 0.0
    for s, e in speech:
        acc += e - s
    assert acc > 30.0                       # 浮点累加确实越界了——这就是要防的那一下
    assert len(asrblocks.group_chunks(speech)) == 1
    # 真多一个样点就该切：容差不能大到把 480001 也放过
    over = EXACT_30S_SAMPLES[:-1] + [(425229, 588365)]
    assert len(asrblocks.group_chunks([[a / SR, b / SR] for a, b in over])) == 2


def test_grouping_keeps_every_speech_interval_exactly_once():
    speech = load()["speech"]
    assert [iv for c in asrblocks.group_chunks(speech) for iv in c["speech"]] == speech


def test_a_block_spans_its_first_to_last_speech_including_the_silence_between():
    blocks = asrblocks.make_blocks(load()["speech"])
    assert len(blocks) == 6
    assert (blocks[0]["start"], blocks[0]["end"], blocks[0]["speech_s"]) == (12.0, 39.5, 26.5)
    # 跨度取到毫秒（实验的切法）；不是浮点秒原样
    b = asrblocks.make_blocks([[3552 / SR, 34756 / SR]])[0]
    assert (b["start"], b["end"]) == (0.222, 2.172)


def test_blocks_are_sorted_by_span_and_batched_by_four():
    blocks = asrblocks.make_blocks(load()["speech"])
    got = [[b["k"] for b in g] for g in asrblocks.batches(blocks)]
    assert got == [[4, 1, 2, 3], [0, 5]]          # 0 和 5 一样长：保持块号顺序
    assert asrblocks.BATCH == 4


# ---------------------------------------------------------------- 验收 2：段与词
def test_one_block_one_segment_in_block_order_and_every_segment_spells_its_words():
    _, blocks, segs, words, asr, _ = run_fixture()
    assert [s["start"] for s in segs] == [b["start"] for b in blocks if b["k"] != 2]
    assert [(s["start"], s["end"]) for s in segs] == [(b["start"], b["end"])
                                                      for b in blocks if b["k"] != 2]
    assert all(s["speaker"] is None for s in segs)
    assert len(words) == len(segs)
    for s, w in zip(segs, words):
        assert "".join(u[2] for u in w) == s["text"]


def test_english_tokens_attach_with_the_space_that_follows_them():
    doc, blocks, segs, words, _, _ = run_fixture()
    s, w = seg_at(segs, words, blocks[1]["start"])
    assert s["text"] == "老周说 northbridge toll明年还要再涨一点"
    assert [u[2] for u in w][:5] == ["老", "周", "说 ", "northbridge ", "toll"]


def test_word_times_are_the_block_start_plus_the_in_block_time():
    doc, blocks, segs, words, _, _ = run_fixture()
    toks = doc["decodes"]["1"]["tokens"]
    _, w = seg_at(segs, words, blocks[1]["start"])
    assert [(u[0], u[1]) for u in w] == [(round(41.0 + t[1], 3), round(41.0 + t[2], 3))
                                         for t in toks]


def test_tokens_that_do_not_spell_the_text_fall_back_to_an_even_split_and_are_counted():
    _, blocks, segs, words, asr, _ = run_fixture()
    b = blocks[3]
    s, w = seg_at(segs, words, b["start"])
    assert asr["words_linear"] == 1 and asr["linear_blocks"] == [3]
    assert "".join(u[2] for u in w) == s["text"] == "阿桥在弹幕里问夜市什么时候搬回来"
    n = len(s["text"])
    assert w[0][0] == b["start"] and w[-1][1] == b["end"]
    assert all(abs((u[1] - u[0]) - (b["end"] - b["start"]) / n) < 0.002 for u in w)


@pytest.mark.parametrize("text,tokens,ok", [
    ("河口夜市", [["河", 0, 1], ["口", 1, 2], ["夜", 2, 3], ["市", 3, 4]], True),
    ("河口夜市", [["河", 0, 1], ["口", 1, 2], ["夜", 2, 3]], False),       # 文本里还剩字
    ("河口夜", [["河", 0, 1], ["口", 1, 2], ["夜", 2, 3], ["市", 3, 4]], False),  # token 多
    ("河口 trump说", [["河", 0, 1], ["口", 1, 2], ["TRUMP", 2, 3], ["说", 3, 4]], True),  # 不分大小写
    ("他说 what's up", [["他", 0, 1], ["说", 1, 2], ["what's", 2, 3], ["up", 3, 4]], True),
    ("河口", [["<sil>", 0, 0.5], ["河", 0.5, 1], ["口", 1, 2], ["<blank>", 2, 3]], True),
    ("河口", [], False),
])
def test_words_for_text(text, tokens, ok):
    got = asrblocks.words_for_text(text, tokens, 100.0)
    if ok:
        assert got is not None and "".join(u[2] for u in got) == text
        assert all(100.0 <= u[0] <= u[1] for u in got)
    else:
        assert got is None


def test_a_leading_space_rides_on_the_first_word():
    got = asrblocks.words_for_text(" ok河口", [["ok", 0, 1], ["河", 1, 2], ["口", 2, 3]], 0.0)
    assert [u[2] for u in got] == [" ok", "河", "口"]
    assert [u[2] for u in asrblocks.linear_words(" a b 河", 0.0, 3.0)] == [" a ", "b ", "河"]


def test_segment_text_and_word_pieces_go_through_the_same_t2s():
    doc = load()
    doc["decodes"]["0"]["text"] = doc["decodes"]["0"]["text"].replace("迁", "遷")
    doc["decodes"]["0"]["tokens"] = [[t.replace("迁", "遷"), s, e]
                                     for t, s, e in doc["decodes"]["0"]["tokens"]]
    _, blocks, segs, words, asr, _ = run_fixture(doc, t2s=lambda t: t.replace("遷", "迁"))
    s, w = seg_at(segs, words, blocks[0]["start"])
    assert "迁" in s["text"] and "遷" not in "".join(u[2] for u in w)
    assert "".join(u[2] for u in w) == s["text"]
    assert asr["t2s_chars"] == 1 and asr["words_linear"] == 1


# ---------------------------------------------------------------- 验收 3：空块、缺结果、错误
def test_an_empty_block_gives_no_segment_and_is_counted():
    _, blocks, segs, _, asr, _ = run_fixture()
    assert blocks[2]["start"] not in [s["start"] for s in segs]
    assert asr["empty"] == 1 and asr["empty_blocks"] == [2]
    assert (asr["blocks"], asr["segments"], asr["errors"]) == (6, 5, 0)


def test_a_block_missing_from_its_batch_is_decoded_once_more_on_its_own():
    _, blocks, segs, _, asr, calls = run_fixture()
    assert calls == [[4, 1, 2, 3], [4], [0, 5]]
    assert asr["retried"] == 1 and asr["retried_blocks"] == [4]
    assert blocks[4]["start"] in [s["start"] for s in segs]


def test_a_block_still_missing_after_the_retry_is_an_error_and_the_rest_carry_on():
    doc = load()
    del doc["decodes"]["4"]                       # 单独解也没结果
    logs = []
    _, blocks, segs, _, asr, calls = run_fixture(doc, log=logs.append)
    assert calls == [[4, 1, 2, 3], [4], [0, 5]]   # 只重解一次
    assert asr["errors"] == 1 and asr["error_blocks"] == [4]
    assert asr["segments"] == 4 and blocks[4]["start"] not in [s["start"] for s in segs]


def test_a_batch_that_raises_is_redecoded_block_by_block():
    doc = load()
    decode0, calls = asrblocks.demo_decoder(doc)

    def decode(group):
        if len(group) > 1 and group[0]["k"] == 4:
            calls.append("boom")
            raise RuntimeError("CUDA out of memory")
        return decode0(group)

    logs = []
    segs, _, asr = asrblocks.run(asrblocks.make_blocks(doc["speech"]), decode, log=logs.append)
    assert calls == ["boom", [4], [1], [2], [3], [0, 5]]
    assert (asr["retried"], asr["errors"], asr["segments"]) == (4, 0, 5)
    assert logs == ["batch 4,1,2,3 failed: RuntimeError: CUDA out of memory"]


def test_progress_is_reported_in_audio_seconds_after_every_batch():
    seen = []
    _, blocks, _, _, _, _ = run_fixture(progress=lambda d, t: seen.append((d, t)))
    total = sum(b["end"] - b["start"] for b in blocks)
    assert len(seen) == 2 and seen[-1] == (pytest.approx(total), pytest.approx(total))
    assert seen[0][0] == pytest.approx(sum(blocks[k]["end"] - blocks[k]["start"] for k in (4, 1, 2, 3)))


def test_the_asr_report_is_json_and_the_log_line_is_ascii():
    _, _, _, _, asr, _ = run_fixture()
    json.dumps(asr)
    line = asrblocks.asr_line(asr)
    assert line == "asr: blocks=6 segments=5 empty=1 errors=0 words_linear=1" and line.isascii()


# ---------------------------------------------------------------- 验收 4：标点只插不改
def test_punctuation_is_only_inserted():
    doc = load()
    _, _, segs, _, _, _ = run_fixture(doc)
    punc = asrblocks.punc_pass(segs, asrblocks.demo_punc(doc))
    assert punc["skipped"] is None and punc["unmatched"] == 0 and punc["model"] == "FireRedPunc"
    assert len(punc["segments"]) == len(segs)
    for s, p in zip(segs, punc["segments"]):
        assert (p["start"], p["end"]) == (s["start"], s["end"])
        assert asrblocks.strip_punc(p["text"]) == asrblocks.strip_punc(s["text"])
        assert p["text"] != s["text"]


def test_case_and_spaces_come_from_the_original():
    assert asrblocks.punc_overlay("老周说 trump toll明年", "老周说 Trump toll，明年。") \
        == "老周说 trump toll，明年。"
    assert asrblocks.punc_overlay("我说trump", "我说 Trump。") == "我说trump。"   # 多出的空白丢掉
    assert asrblocks.punc_overlay("a b", "a,b") == "a, b"                          # 少了的空白照原文补
    assert asrblocks.punc_overlay("don't", "Don't.") == "don't."              # 原文里的撇号不算插入


def test_a_segment_whose_punctuated_version_does_not_line_up_stays_bare_and_is_counted():
    segs = [{"start": 0.0, "end": 1.0, "text": "河口夜市"},
            {"start": 1.0, "end": 2.0, "text": "北港大桥"}]
    punc = asrblocks.punc_pass(segs, lambda texts: ["河口夜市。", "北港大轿。"])  # 改了字
    assert punc["unmatched"] == 1 and punc["unmatched_segments"] == [1]
    assert [p["text"] for p in punc["segments"]] == ["河口夜市。", "北港大桥"]
    assert asrblocks.punc_overlay("北港大桥", "北港大轿。") is None


def test_a_failing_punctuation_step_is_recorded_as_skipped():
    segs = [{"start": 0.0, "end": 1.0, "text": "河口夜市"}]

    def boom(texts):
        raise OSError("weights missing")

    punc = asrblocks.punc_pass(segs, boom)
    assert punc["skipped"] == "OSError: weights missing" and punc["segments"] == []
    short = asrblocks.punc_pass(segs, lambda texts: [])
    assert short["skipped"].startswith("RuntimeError: punc returned 0 texts for 1")


def test_punctuation_runs_in_batches_of_thirty_two():
    segs = [{"start": float(i), "end": i + 1.0, "text": "河口%d" % i} for i in range(40)]
    sizes = []
    asrblocks.punc_pass(segs, lambda texts: (sizes.append(len(texts)), texts)[1])
    assert sizes == [32, 8]


# ---------------------------------------------------------------- 冻结配置
def test_the_frozen_config_is_the_one_in_the_spec():
    spec = (REPO / "SPEC.md").read_bytes().decode("utf-8")
    assert asrblocks.CONFIG == "fp32 beam3 bs4 xkv memfrac0.8 vad30 ctc_ts"
    assert '`config: "%s"`' % asrblocks.CONFIG in spec
    assert '`engine: "%s"`' % asrblocks.ENGINE in spec
    for key, val in asrblocks.DECODE.items():
        assert "`%s=%s`" % (key, val) in spec, key
    assert "max_speech_duration_s=%d" % asrblocks.MAX_CHUNK_SPEECH_S in spec
    assert "min_silence_duration_ms=%d" % asrblocks.VAD_MIN_SILENCE_MS in spec
    assert "set_per_process_memory_fraction(%g)" % asrblocks.MEM_FRACTION in spec


# ---------------------------------------------------------------- 验收 5：规则层只有标准库
def _imports(path):
    tree = ast.parse(path.read_bytes().decode("utf-8"))
    top = set()
    for node in tree.body:                       # 只看顶层：函数里的 import 是故意推迟的
        if isinstance(node, ast.Import):
            top |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.level == 0:
            top.add((node.module or "").split(".")[0])
    return top


def test_asrblocks_imports_nothing_outside_the_standard_library():
    names = set()
    for node in ast.walk(ast.parse((REPO / "pc" / "asrblocks.py").read_bytes().decode("utf-8"))):
        if isinstance(node, ast.Import):
            names |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.level == 0:
            names.add((node.module or "").split(".")[0])
    assert names and names <= set(sys.stdlib_module_names), sorted(names)


def test_smpc_and_fired_engine_import_nothing_heavy_at_the_top():
    """download 跑在没有 torch 的 C:\\asr\\venv：顶层只许标准库和 asrblocks。"""
    allowed = set(sys.stdlib_module_names) | {"asrblocks"}
    for f in ("smpc.py", "fired_engine.py"):
        top = _imports(REPO / "pc" / f)
        assert top <= allowed, (f, sorted(top - allowed))


def test_the_pc_modules_import_on_a_machine_without_torch_numpy_or_opencc():
    src = (
        "import io, sys\n"
        "for m in ('numpy', 'faster_whisper', 'opencc', 'torch', 'torchaudio'): sys.modules[m] = None\n"
        "sys.path.insert(0, %r)\n"
        "import asrblocks, fired_engine\n"
        "sys.stdout = io.TextIOWrapper(io.BytesIO(), encoding='utf-8')\n"
        "import smpc\n"
        "sys.stdout = sys.__stdout__\n"
        "print(asrblocks.CONFIG)\n" % str(REPO / "pc")
    )
    p = subprocess.run([sys.executable, "-c", src], capture_output=True, text=True)
    assert p.returncode == 0, p.stderr
    assert p.stdout.strip() == "fp32 beam3 bs4 xkv memfrac0.8 vad30 ctc_ts"


# ---------------------------------------------------------------- 验收 6：smpc 不再有 whisper 那一套
def test_smpc_has_no_whisper_leftovers():
    src = (REPO / "pc" / "smpc.py").read_bytes().decode("utf-8")
    for word in ("redecode", "hotwords", "BatchedInferencePipeline", "setup_cuda_dlls",
                 "WhisperModel"):
        assert word.lower() not in src.lower(), word
    assert not (REPO / "pc" / "redecode.py").exists()
    assert not (REPO / "tests" / "fixtures" / "redecode").exists()


# ---------------------------------------------------------------- 演示（issue 的「可见变化」）
def test_the_demo_command_ends_with_the_agreed_counts():
    p = subprocess.run([sys.executable, str(REPO / "pc" / "asrblocks.py"), "--demo", str(FIX)],
                       capture_output=True, text=True, encoding="utf-8")
    assert p.returncode == 0, p.stdout + p.stderr
    lines = p.stdout.strip().splitlines()
    assert lines[-1] == "asr: blocks=6 segments=5 empty=1 errors=0 words_linear=1"
    assert "与样例 expect 逐块一致。" in p.stdout
    assert p.stdout.count("词拼回 == 文本：是；标点版去标点 == 原文：是") == 5
    assert "空，不出段" in p.stdout and "整块按字均分" in p.stdout and "单独重解" in p.stdout


def test_the_demo_fails_loudly_when_the_rules_stop_matching_the_fixture(tmp_path):
    doc = load()
    doc["expect"]["blocks"]["3"] = "ok"
    tmp = tmp_path / "EP95.asrblocks.json"          # 不许写回 tests/fixtures/
    tmp.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    p = subprocess.run([sys.executable, str(REPO / "pc" / "asrblocks.py"), "--demo", str(tmp)],
                       capture_output=True, text=True, encoding="utf-8")
    assert p.returncode == 1
    assert "与样例 expect 不符" in p.stdout


# ---------------------------------------------------------------- fired_engine：按 uttid 对账
class FakeCuda:
    def __init__(self):
        self.emptied = 0

    def empty_cache(self):
        self.emptied += 1


class FakeAttn:
    _xkv = ("stale",)


def bare_engine(transcribe):
    import fired_engine
    eng = object.__new__(fired_engine.Engine)
    eng.model = types.SimpleNamespace(transcribe=transcribe)
    eng.torch = types.SimpleNamespace(cuda=FakeCuda())
    eng.cross = [FakeAttn(), FakeAttn()]
    return eng


def test_the_engine_reconciles_results_by_uttid_and_resets_its_caches():
    seen = []

    def transcribe(ids, paths):
        seen.append((ids, paths))
        return [  # 顺序打乱、缺一块、一块是特征出错时上游填的空壳（没有 confidence）
            {"uttid": "k007", "text": "北港", "confidence": 0.9,
             "timestamp": [("北", 0.1, 0.2), ("港", 0.2, 0.3)]},
            {"uttid": "k003", "text": ""},
            {"uttid": "k012", "text": "", "confidence": 0.7, "timestamp": [("<sil>", 0.0, 1.0)]},
        ]

    eng = bare_engine(transcribe)
    group = [{"k": 3}, {"k": 7}, {"k": 12}, {"k": 5}]
    got = eng.decoder({3: "a.wav", 7: "b.wav", 12: "c.wav", 5: "d.wav"})(group)
    assert seen == [(["k003", "k007", "k012", "k005"], ["a.wav", "b.wav", "c.wav", "d.wav"])]
    assert got == {7: {"text": "北港", "tokens": [["北", 0.1, 0.2], ["港", 0.2, 0.3]]},
                   12: {"text": "", "tokens": [["<sil>", 0.0, 1.0]]}}
    assert eng.torch.cuda.emptied == 1 and all(a._xkv is None for a in eng.cross)


def test_the_engine_resets_its_caches_even_when_the_batch_raises():
    def transcribe(ids, paths):
        raise RuntimeError("boom")

    eng = bare_engine(transcribe)
    with pytest.raises(RuntimeError):
        eng.decoder({1: "a.wav"})([{"k": 1}])
    assert eng.torch.cuda.emptied == 1 and all(a._xkv is None for a in eng.cross)


# ---------------------------------------------------------------- smpc transcribe 的接线（假引擎）
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


def fake_engine_module(doc, *, load_error=None, vad_error=None, punc_error=None):
    blocks = asrblocks.make_blocks(doc["speech"])
    decode, calls = asrblocks.demo_decoder(doc)
    mod = types.ModuleType("fired_engine")
    state = {"wav_dirs": []}

    class Engine:
        versions = "torch fake"

        def __init__(self):
            if load_error:
                raise load_error

        def decoder(self, wavs):
            assert set(wavs) == {b["k"] for b in blocks}
            return decode

        def memory(self):
            return {"peak_gpu_gb": 6.86, "reserved_gpu_gb": 7.29, "align_errors": 0}

        def punc(self, texts):
            if punc_error:
                raise punc_error
            return asrblocks.demo_punc(doc)(texts)

    def vad_blocks(audio):
        if vad_error:
            raise vad_error
        return [0.0] * int(200 * SR), blocks

    def write_block_wavs(pcm, blks, out_dir):
        Path(out_dir).mkdir(parents=True, exist_ok=True)
        state["wav_dirs"].append(Path(out_dir))
        paths = {}
        for b in blks:
            p = Path(out_dir) / ("k%04d.wav" % b["k"])
            p.write_bytes(b"RIFF")
            paths[b["k"]] = str(p)
        return paths

    mod.Engine, mod.vad_blocks, mod.write_block_wavs = Engine, vad_blocks, write_block_wavs
    return mod, state


def transcribe(smpc, monkeypatch, tmp_path, capsys, **kw):
    mod, state = fake_engine_module(load(), **kw)
    monkeypatch.setitem(sys.modules, "fired_engine", mod)
    monkeypatch.setattr(smpc, "STAGE_DIR", tmp_path)
    monkeypatch.setattr(smpc, "load_t2s", lambda: None)
    monkeypatch.setattr(smpc, "to_simplified", lambda t: t)
    (tmp_path / "EP95.m4a").write_bytes(b"fake audio")
    code = 0
    try:
        smpc.cmd_transcribe("EP95")
    except SystemExit as e:
        code = e.code
    return code, capsys.readouterr().out, state


def test_smpc_writes_the_transcript_with_the_agreed_fields(smpc, monkeypatch, tmp_path, capsys):
    code, out, state = transcribe(smpc, monkeypatch, tmp_path, capsys)
    assert code == 0, out
    doc = json.loads((tmp_path / "EP95.transcript.json").read_text(encoding="utf-8"))
    assert doc["engine"] == "FireRedASR2-AED"
    assert doc["config"] == "fp32 beam3 bs4 xkv memfrac0.8 vad30 ctc_ts"
    assert "redecode" not in doc
    assert doc["orthography"] == "opencc t2s 逐字" and doc["orthography_chars"] == 0
    assert doc["diarization"] == "pending" and doc["duration_s"] == 200.0
    a = doc["asr"]
    assert (a["blocks"], a["segments"], a["empty"], a["errors"], a["words_linear"]) == (6, 5, 1, 0, 1)
    assert (a["peak_gpu_gb"], a["reserved_gpu_gb"]) == (6.86, 7.29) and "t2s_chars" not in a
    assert len(doc["segments"]) == 5 and all("speaker" in s for s in doc["segments"])
    assert len(doc["punc"]["segments"]) == 5 and doc["punc"]["skipped"] is None
    for s, p in zip(doc["segments"], doc["punc"]["segments"]):
        assert asrblocks.strip_punc(p["text"]) == s["text"]
        assert not any(asrblocks._is_punc(c) for c in s["text"])      # 正本不带标点
    words = json.loads((tmp_path / "EP95.words.json").read_text(encoding="utf-8"))
    assert words["ep"] == "EP95" and len(words["segments"]) == 5
    for s, w in zip(doc["segments"], words["segments"]):
        assert "".join(u[2] for u in w) == s["text"]
    # 块音频是临时文件：转完删掉
    assert state["wav_dirs"] == [tmp_path / "EP95.blocks"] and not (tmp_path / "EP95.blocks").exists()


def test_the_worker_sees_only_ascii_protocol_lines(smpc, monkeypatch, tmp_path, capsys):
    code, out, _ = transcribe(smpc, monkeypatch, tmp_path, capsys)
    lines = out.strip().splitlines()
    assert lines and all(re.match(r"^(PROGRESS|INFO|ERROR) ", l) for l in lines), lines
    assert all(l.isascii() for l in lines)
    assert any(l.startswith("INFO asr: blocks=6 segments=5 empty=1 errors=0 words_linear=1 ")
               for l in lines)
    assert "INFO asr: linear_blocks k=3" in lines
    assert "INFO punc: segments=5 unmatched=0" in " ".join(lines)
    prog = [l for l in lines if l.startswith("PROGRESS")]
    assert len(prog) == 3 and prog[-1] == "PROGRESS 200.0 200.0"


def test_smpc_fails_loudly_when_the_model_does_not_load(smpc, monkeypatch, tmp_path, capsys):
    code, out, _ = transcribe(smpc, monkeypatch, tmp_path, capsys,
                              load_error=RuntimeError("CUDA driver too old"))
    assert code == 1
    assert "ERROR model load failed: RuntimeError('CUDA driver too old')" in out
    assert not (tmp_path / "EP95.transcript.json").exists()


def test_smpc_fails_loudly_when_vad_fails_and_leaves_no_block_audio(smpc, monkeypatch, tmp_path, capsys):
    code, out, _ = transcribe(smpc, monkeypatch, tmp_path, capsys, vad_error=OSError("bad m4a"))
    assert code == 1 and "ERROR vad failed: OSError('bad m4a')" in out
    assert not (tmp_path / "EP95.blocks").exists()
    assert not (tmp_path / "EP95.transcript.json").exists()


def test_a_punctuation_failure_does_not_fail_the_transcription(smpc, monkeypatch, tmp_path, capsys):
    code, out, _ = transcribe(smpc, monkeypatch, tmp_path, capsys,
                              punc_error=MemoryError("CUDA OOM"))
    assert code == 0
    doc = json.loads((tmp_path / "EP95.transcript.json").read_text(encoding="utf-8"))
    assert doc["punc"]["skipped"].startswith("MemoryError") and doc["punc"]["segments"] == []
    assert len(doc["segments"]) == 5
    assert "INFO punc: skipped (MemoryError: CUDA OOM)" in out


def test_numpy_scalars_that_slip_through_are_written_as_plain_numbers(smpc):
    class Np64:
        def __init__(self, v):
            self.v = v

        def item(self):
            return self.v

    assert json.dumps({"x": Np64(1.5)}, default=smpc._plain) == '{"x": 1.5}'
    with pytest.raises(TypeError):
        json.dumps({"x": object()}, default=smpc._plain)


# ---------------------------------------------------------------- worker / 部署 / PC 环境的静态契约
def test_the_worker_transcribes_in_the_fired_venv_and_downloads_in_the_old_one():
    ps1 = (REPO / "scripts" / "worker.ps1").read_bytes()
    assert ps1.startswith(b"\xef\xbb\xbf")                      # PowerShell 5.1 要 BOM
    src = ps1.decode("utf-8-sig")
    assert '$RemoteAsrPy = "E:\\asr\\venv-fired\\Scripts\\python.exe"' in src
    assert '$RemotePy = "C:\\asr\\venv\\Scripts\\python.exe"' in src
    body = re.search(r"function Step-Transcribe \{(.*?)\n\}", src, re.S).group(1)
    assert "-Py $RemoteAsrPy" in body
    dl = re.search(r"function Step-Download \{(.*?)\n\}", src, re.S).group(1)
    assert "-Py" not in dl
    assert "转写 venv 必须保持无 torch" not in src


def test_setup_pipeline_ships_the_three_pc_files_and_drops_redecode():
    ps1 = (REPO / "scripts" / "setup-pipeline.ps1").read_bytes()
    assert ps1.startswith(b"\xef\xbb\xbf")
    src = ps1.decode("utf-8-sig")
    assert "foreach ($f in 'smpc.py', 'asrblocks.py', 'fired_engine.py')" in src
    assert "C:\\asr\\redecode.py" in src and "Remove-Item" in src
    assert "'redecode.py'" not in src


def test_setup_fired_matches_the_paths_the_engine_reads():
    raw = (REPO / "pc" / "setup_fired.ps1").read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf")
    src = raw.decode("utf-8-sig")
    import fired_engine
    assert "$Src = '%s'" % fired_engine.SRC in src
    assert "$Models = 'E:\\asr\\models'" in src
    assert fired_engine.AED_DIR.parent == fired_engine.PUNC_DIR.parent == Path(r"E:\asr\models")
    assert "$Venv = 'E:\\asr\\venv-fired'" in src
    for pin in ("torch==2.11.0+cu128", "torchaudio==2.11.0+cu128", "transformers==4.51.3",
                "numpy==1.26.4", "faster-whisper==1.2.1", "opencc-python-reimplemented"):
        assert pin in src, pin
    spec = (REPO / "SPEC.md").read_bytes().decode("utf-8")
    assert "venv `E:\\asr\\venv-fired`" in spec
    assert "`E:\\asr\\models\\FireRedASR2-AED`" in spec and "`E:\\asr\\models\\FireRedPunc`" in spec
