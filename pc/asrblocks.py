# -*- coding: utf-8 -*-
"""asrblocks.py — 阶段 0 转写的规则层（SPEC §4 阶段 0「转写」「标点」，ADR 0006）。部署到 C:\\asr\\asrblocks.py。

FireRedASR2-AED 一块一段：VAD 语音合成 ≤30 秒语音的块，每块取原始时间跨度整段解码。
这个模块管块怎么切、怎么分批、缺了结果怎么补、词怎么挂回段文本、标点怎么只插不改、
计数怎么报——**不用 LLM，一个解码输出以外的字都不引入**（红线 1：ASR 只听写）。

**只依赖标准库**：规则跟 CUDA 和模型无关，所以在没有 torch / numpy / opencc 的机器上也
import 得动、测得了。真正的解码和加标点由调用方（`fired_engine.py`）以回调注入：

    decode(blocks) -> {k: {"text": 解码文本, "tokens": [[token, start, end], ...]}}

        blocks   同一批的块 [{"k", "start", "end", ...}, ...]
        k        块下标；返回里缺了某个 k = 这一块没有结果（FireRed 在内部吞掉异常，
                 返回空 hyps，所以缺结果只能按块号对账）
        tokens   CTC 强制对齐的词时刻，块内秒
        抛异常    整批失败（同样按缺结果处理）

    punc(texts) -> [加了标点的文本, ...]       与 texts 一一对应；抛异常 = 标点这一步失败

自带演示（沙箱里能跑，不需要音频和 GPU）：

    python pc/asrblocks.py --demo tests/fixtures/asrblocks/EP95.asrblocks.json
"""

import argparse
import json
import re
import sys
import unicodedata

# ---------------------------------------------------------------- 冻结配置（SPEC §4 阶段 0，ADR 0006）
ENGINE = "FireRedASR2-AED"
SR = 16000                  # 引擎与 VAD 的工作采样率
MAX_CHUNK_SPEECH_S = 30     # 合块上限（照抄 faster_whisper.vad.collect_chunks）；也是 VAD 的 max_speech_duration_s
VAD_MIN_SILENCE_MS = 160
GROUP_EPS_S = 1e-6          # 合块判界的浮点容差：远小于一个样点（1/16000 s），见 group_chunks
BATCH = 4                   # 块按时长排序后分批
MEM_FRACTION = 0.8          # torch.cuda.set_per_process_memory_fraction
DECODE = {                  # FireRedAsr2Config 的解码参数；fp32（use_half=False）另由引擎接线写死
    "beam_size": 3,
    "nbest": 1,
    "softmax_smoothing": 1.25,
    "aed_length_penalty": 0.6,
    "eos_penalty": 1.0,
    "decode_max_len": 0,
    "return_timestamp": True,
}
CONFIG = "fp32 beam%d bs%d xkv memfrac%g vad%d ctc_ts" % (
    DECODE["beam_size"], BATCH, MEM_FRACTION, MAX_CHUNK_SPEECH_S)
PUNC_MODEL = "FireRedPunc"
PUNC_BATCH = 32


def _err(e):
    return ("%s: %s" % (type(e).__name__, e))[:200]


# ---------------------------------------------------------------- 块
def group_chunks(speech, max_speech_s=MAX_CHUNK_SPEECH_S):
    """把 VAD 语音区间合成块——合块条件照抄 `faster_whisper.vad.collect_chunks`：
    累计语音超过上限就另起一块。

    （搬自 pc/redecode.py（#80 吞块补解），原样保留；补解随换引擎撤掉，合块留下。）

    只抄条件，不抄它返回的 segments 元数据：那份元数据每开一个新块都会漏记该块的
    第一段，拿来跟第一遍的段对位会整体错位。

    判界带 GROUP_EPS_S 容差：collect_chunks 在整数样点上比「> 30 s」，这里是浮点秒。
    累计恰好等于 30.000 s 的块每集都会出现（VAD 强切 + 两侧补齐正好 480000 样点），
    浮点累加会算成 30.000000000000004，不加容差就会在这里多切一刀，后面的块整体错位，
    整步被判「段数 ≠ 块数」跳过。
    """
    out, cur, acc = [], [], 0.0
    for s, e in speech:
        s, e = float(s), float(e)
        if cur and acc + (e - s) > max_speech_s + GROUP_EPS_S:
            out.append(cur)
            cur, acc = [], 0.0
        cur.append([s, e])
        acc += e - s
    if cur:
        out.append(cur)
    return [{"k": k, "start": c[0][0], "end": c[-1][1], "speech": c}
            for k, c in enumerate(out)]


def make_blocks(speech):
    """VAD 语音区间（秒）→ 解码块 [{k, start, end, speech_s}]。

    跨度 `[首段 start, 末段 end)` 含块内静音，取到毫秒：EP02 对照实验（ADR 0006 的
    449/449 基线）就是这么切的，切法一变，块的音频差几个样点，解码就未必逐字相同。
    """
    return [{"k": c["k"], "start": round(c["start"], 3), "end": round(c["end"], 3),
             "speech_s": round(sum(e - s for s, e in c["speech"]), 3)}
            for c in group_chunks(speech)]


def span(block):
    return block["end"] - block["start"]


def batches(blocks, size=BATCH):
    """按时长排序后分批（稳定排序：等长的块保持块号顺序，与实验同序）。"""
    order = sorted(blocks, key=span)
    return [order[i:i + size] for i in range(0, len(order), size)]


# ---------------------------------------------------------------- 词
_PLACEHOLDER = re.compile(r"<blank>|<sil>")


def _keep(ch):
    """对齐时认的字：字母、数字、撇号。空白和标点不进 token，跟着前一个单元走。"""
    return ch == "'" or unicodedata.category(ch)[0] in "LN"


def words_for_text(text, tokens, offset):
    """把 CTC 的 `[token, s, e]`（块内秒）按顺序挂回段文本。

    每个单元是 `[绝对 start, 绝对 end, 文本片段]`，片段带上紧随其后的空格（第一个单元
    还带上前导空白），所以 `"".join(片段) == text`——说话人分离按词重建段、不许改文本，
    靠的就是这一条。

    token 里的字必须按序逐个对上文本里的字（不分大小写），token 用完时文本也必须用完。
    对不上返回 None，由调用方整块均分兜底并计数——不去「修」文本。

    `<sil>` / `<blank>` 是 FireRed 的占位 token，上游拼文本时就删掉了，这里同样不认。
    """
    toks = [(_PLACEHOLDER.sub("", t), s, e) for t, s, e in tokens]
    toks = [(t, s, e) for t, s, e in toks if any(_keep(c) for c in t)]
    if not toks:
        return None
    units, pos = [], 0
    for tok, s, e in toks:
        need = [c for c in tok.lower() if _keep(c)]
        start, got = pos, 0
        while pos < len(text) and got < len(need):
            c = text[pos]
            if _keep(c):
                if c.lower() != need[got]:
                    return None
                got += 1
            pos += 1
        if got < len(need):
            return None
        while pos < len(text) and not _keep(text[pos]):
            pos += 1
        units.append([round(offset + float(s), 3), round(offset + float(e), 3), text[start:pos]])
    if pos != len(text):            # 文本里还剩 token 没覆盖到的字
        return None
    return units


def linear_words(text, start, end):
    """整块按字均分时刻：每个非空白字一个单元，带上紧随其后的空白。"""
    units, lead = [], ""
    for ch in text:
        if ch.isspace():
            if units:
                units[-1] += ch
            else:
                lead += ch
        else:
            units.append(lead + ch)
            lead = ""
    n = len(units)
    return [[round(start + (end - start) * j / n, 3), round(start + (end - start) * (j + 1) / n, 3), u]
            for j, u in enumerate(units)]


# ---------------------------------------------------------------- 解码驱动
def run(blocks, decode, t2s=None, progress=None, log=None, size=BATCH):
    """按批解码、对账、出段与词。

    blocks    make_blocks 的产物
    decode    解码回调，见模块头
    t2s       逐字繁→简（smpc.to_simplified）；段文本和词片段都过它
    progress  可选 progress(已解块的音频秒数, 全部块的音频秒数)，每批之后报一次
    log       可选 log(文本)，整批失败时报一行

    返回 (segments, words, asr)。segments 按块号排，一块一段；words 与 segments 平行。
    """
    t2s = t2s or (lambda s: s)
    got, retried, errors = {}, [], []
    total = sum(span(b) for b in blocks)
    done = 0.0
    for group in batches(blocks, size):
        try:
            res = decode(group) or {}
        except Exception as e:
            res = {}
            if log:
                log("batch %s failed: %s" % (",".join(str(b["k"]) for b in group), _err(e)))
        for b in group:
            r = res.get(b["k"])
            if r is None:                   # 缺结果：单独重解一次
                retried.append(b["k"])
                try:
                    r = (decode([b]) or {}).get(b["k"])
                except Exception as e:
                    r = None
                    if log:
                        log("block %d failed alone: %s" % (b["k"], _err(e)))
            if r is None:
                errors.append(b["k"])
            else:
                got[b["k"]] = r
        done += sum(span(b) for b in group)
        if progress:
            progress(done, total)

    segments, words, empty, linear, t2s_chars = [], [], [], [], 0
    for b in blocks:
        r = got.get(b["k"])
        if r is None:
            continue
        raw = r.get("text") or ""
        if not raw.strip():
            empty.append(b["k"])
            continue
        text = t2s(raw)
        t2s_chars += sum(1 for x, y in zip(raw, text) if x != y)
        units = words_for_text(raw, r.get("tokens") or [], b["start"])
        if units is not None:
            units = [[s, e, t2s(p)] for s, e, p in units]
            if "".join(u[2] for u in units) != text:
                units = None
        if units is None:
            linear.append(b["k"])
            units = linear_words(text, b["start"], b["end"])
        segments.append({"start": b["start"], "end": b["end"], "speaker": None, "text": text})
        words.append(units)

    asr = {"blocks": len(blocks), "segments": len(segments),
           "empty": len(empty), "errors": len(errors), "words_linear": len(linear),
           "retried": len(retried), "t2s_chars": t2s_chars,
           "empty_blocks": empty, "error_blocks": errors, "linear_blocks": linear,
           "retried_blocks": retried}
    return segments, words, asr


def asr_line(asr):
    """worker 日志里的那一行（ASCII）。"""
    return ("asr: blocks=%d segments=%d empty=%d errors=%d words_linear=%d"
            % (asr["blocks"], asr["segments"], asr["empty"], asr["errors"], asr["words_linear"]))


# ---------------------------------------------------------------- 标点
def _is_punc(ch):
    return unicodedata.category(ch).startswith("P")


def strip_punc(text):
    return "".join(c for c in text if not _is_punc(c))


def punc_overlay(text, punc_text):
    """只把 punc_text 里的标点按位置插回 text。字和大小写一律以 text 为准，空白也以
    text 为准（标点版多出的空白丢掉）。对不上返回 None。

    结果去掉插进去的标点就是 text 本身：标点版只是读着方便的另一份，正本不动（红线 1）。
    """
    out, i, j = [], 0, 0
    n, m = len(text), len(punc_text)
    while i < n or j < m:
        if i < n and j < m and text[i].lower() == punc_text[j].lower():
            out.append(text[i])
            i += 1
            j += 1
        elif j < m and _is_punc(punc_text[j]):
            out.append(punc_text[j])
            j += 1
        elif i < n and text[i].isspace():
            out.append(text[i])
            i += 1
        elif j < m and punc_text[j].isspace():
            j += 1
        else:
            return None
    return "".join(out)


def punc_pass(segments, punc, size=PUNC_BATCH):
    """给每段加标点，结果另存（transcript.json 顶层 `punc`），与段一一对应。

    对不上的段原样不带标点，计入 `unmatched`。这一步失败不让转写失败：
    `skipped` 记原因，`segments` 为空。
    """
    try:
        outs = []
        for i in range(0, len(segments), size):
            texts = [s["text"] for s in segments[i:i + size]]
            res = list(punc(texts))
            if len(res) != len(texts):
                raise RuntimeError("punc returned %d texts for %d" % (len(res), len(texts)))
            outs += res
    except Exception as e:
        return {"model": PUNC_MODEL, "skipped": _err(e), "unmatched": 0,
                "unmatched_segments": [], "segments": []}
    segs, unmatched = [], []
    for k, (s, p) in enumerate(zip(segments, outs)):
        t = punc_overlay(s["text"], p) if isinstance(p, str) else None
        if t is None:
            unmatched.append(k)
            t = s["text"]
        segs.append({"start": s["start"], "end": s["end"], "text": t})
    return {"model": PUNC_MODEL, "skipped": None, "unmatched": len(unmatched),
            "unmatched_segments": unmatched, "segments": segs}


# ---------------------------------------------------------------- 演示
def demo_decoder(doc):
    """用样例里的假解码表当解码器。`batch_missing` 里的块在整批里缺结果，单独解才有。
    返回 (decode, calls)，calls 记每次调用的块号。"""
    calls = []
    table = doc.get("decodes") or {}
    missing = set(doc.get("batch_missing") or [])

    def decode(group):
        ks = [b["k"] for b in group]
        calls.append(ks)
        out = {}
        for k in ks:
            if len(ks) > 1 and k in missing:
                continue
            d = table.get(str(k))
            if d is not None:
                out[k] = {"text": d["text"], "tokens": d["tokens"]}
        return out

    return decode, calls


def demo_punc(doc):
    table = doc.get("punc") or {}

    def punc(texts):
        return [table.get(t, t) for t in texts]

    return punc


def cmd_demo(path):
    doc = json.loads(open(path, encoding="utf-8").read())
    blocks = make_blocks(doc["speech"])
    decode, calls = demo_decoder(doc)
    segments, words, asr = run(blocks, decode)
    punc = punc_pass(segments, demo_punc(doc))
    expect = doc.get("expect") or {}

    print("样例 %s（%s，合成，内容虚构）" % (path, doc.get("ep", "?")))
    print("配置 %s %s，块 %d" % (ENGINE, CONFIG, len(blocks)))
    print("分批 %s" % " | ".join(",".join(str(k) for k in ks) for ks in calls))
    print("")

    seg_of = {}
    for s, w in zip(segments, words):
        seg_of[s["start"]] = (s, w)
    fate = {}
    bad = 0
    pi = 0
    for b in blocks:
        k = b["k"]
        head = "块 %d  %.1f-%.1fs" % (k, b["start"], b["end"])
        if k in asr["error_blocks"]:
            fate[k] = "error"
            print(head + "  → 无结果，不出段（计入 errors）")
            continue
        if k in asr["empty_blocks"]:
            fate[k] = "empty"
            print(head + "  → 空，不出段（计入 empty）")
            continue
        s, w = seg_of[b["start"]]
        fate[k] = "linear" if k in asr["linear_blocks"] else "ok"
        note = "  （整批缺结果，单独重解）" if k in asr["retried_blocks"] else ""
        print(head + "  → 段%s" % note)
        print("     文本  %s" % s["text"])
        print("     词    %s" % " | ".join("%s@%.2f" % (u[2], u[0]) for u in w))
        if fate[k] == "linear":
            print("     词挂不上 CTC token，整块按字均分（计入 words_linear）")
        ok_join = "".join(u[2] for u in w) == s["text"]
        p = punc["segments"][pi]["text"] if not punc["skipped"] else None
        pi += 1
        ok_punc = p is not None and strip_punc(p) == strip_punc(s["text"])
        print("     标点  %s" % p)
        print("     词拼回 == 文本：%s；标点版去标点 == 原文：%s"
              % ("是" if ok_join else "否", "是" if ok_punc else "否"))
        if not (ok_join and ok_punc):
            bad += 1
    print("")
    want = expect.get("blocks") or {}
    for k, f in sorted(fate.items()):
        if str(k) in want and want[str(k)] != f:
            bad += 1
            print("✗ 块 %d 与样例 expect 不符：期望 %s，实得 %s" % (k, want[str(k)], f))
    for key, v in (expect.get("asr") or {}).items():
        if asr.get(key) != v:
            bad += 1
            print("✗ asr.%s 与样例 expect 不符：期望 %s，实得 %s" % (key, v, asr.get(key)))
    print("解码调用 %d 次；标点 %s，对不上 %d 段" % (len(calls), punc["model"], punc["unmatched"]))
    print("与样例 expect %s。" % ("不符 %d 处" % bad if bad else "逐块一致"))
    print(asr_line(asr))
    return 1 if bad else 0


def main(argv=None):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(prog="asrblocks.py", description="阶段 0 转写的规则层")
    ap.add_argument("--demo", metavar="FIXTURE",
                    help="拿样例里的假解码结果跑一遍规则层，打印段、词、标点和计数")
    a = ap.parse_args(argv)
    if not a.demo:
        ap.error("这个模块是给 smpc.py import 的；单独跑只有 --demo")
    return cmd_demo(a.demo)


if __name__ == "__main__":
    sys.exit(main())
