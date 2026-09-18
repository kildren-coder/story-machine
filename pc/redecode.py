# -*- coding: utf-8 -*-
"""redecode.py — 吞块补解的规则层（SPEC §4 阶段 0「吞块补解」）。部署到 C:\\asr\\redecode.py。

batched 管线把 VAD 语音拼成 ≤30 秒的块，每块只解一遍，没有降温重试；长块会被整块
吞掉，只剩块头或块尾几秒。这个模块负责判断哪些块像是被吞了，并驱动「同一段音频换个
切法再听一遍」的阶梯——**不用 LLM，不改写别的块，一个解码输出以外的字都不引入**
（红线 1：ASR 只听写）。

**只依赖标准库**：判据、阶梯、报告都是纯规则，跟 CUDA 和模型无关，所以在没有
numpy / faster_whisper / opencc 的机器上也 import 得动、测得了。真正的解码由调用方
以回调注入：

    decode(k, start, end, chunk_length) -> (segments, words)

        k              块下标（= 第一遍的段下标）
        start, end     块的原始时间跨度（绝对秒）
        chunk_length   这一级的切块长度
        segments       [{"start": 绝对秒, "end": 绝对秒, "text": 已 t2s 的文本}, ...]
        words          与 segments 平行的词表，words[i] = [[start, end, word], ...]
        抛异常         表示这一级失败（记下来，进下一级）

自带演示（沙箱里能跑，不需要音频和 GPU）：

    python pc/redecode.py --demo tests/fixtures/redecode/EP93.redecode.json
"""

import argparse
import difflib
import json
import re
import sys
from collections import Counter

# ---------------------------------------------------------------- 规则参数（SPEC §4 阶段 0）
MIN_SPEECH_S = 8            # 语音短于这个的块不判疑似：短块 EP02 实测 0/14 出事
MIN_DENSITY = 3             # 汉字 / 语音秒，低于这个算疑似
MAX_GAP_S = 5               # 块内空洞 ≥ 这个算疑似
LADDER = (15, 10, 7)        # 重解阶梯，只改 chunk_length
MIN_GAIN_HAN = 20           # 新版至少比原文多这么多汉字才参选
MIN_KEPT = 0.8              # 原文汉字按序出现在新版里的比例下限
MAX_REP4 = 5                # 同一个 4 字汉字串的出现次数上限，超了算复读
MAX_CHUNK_SPEECH_S = 30     # 合块上限（照抄 faster_whisper.vad.collect_chunks）
GROUP_EPS_S = 1e-6          # 合块判界的浮点容差：远小于一个样点（1/16000 s），见 group_chunks

HAN = re.compile(r"[一-鿿]")            # 字数一律数汉字（SPEC §1.3）
WS = re.compile(r"\s+")


def rule():
    """报告里的 `rule`：本次实际生效的全部参数。"""
    return {
        "min_speech_s": MIN_SPEECH_S,
        "min_density": MIN_DENSITY,
        "max_gap_s": MAX_GAP_S,
        "ladder": list(LADDER),
        "min_gain_han": MIN_GAIN_HAN,
        "min_kept": MIN_KEPT,
        "max_rep4": MAX_REP4,
        "max_chunk_speech_s": MAX_CHUNK_SPEECH_S,
    }


# ---------------------------------------------------------------- 量
def han(text):
    """只留汉字。"""
    return "".join(HAN.findall(text or ""))


def n_han(text):
    return len(HAN.findall(text or ""))


def speech_s(chunk):
    """块的语音秒数（VAD 区间之和，不含区间之间的静音）。"""
    return float(sum(e - s for s, e in chunk["speech"]))


def _speech_between(speech, lo, hi):
    return sum(max(0.0, min(e, hi) - max(s, lo)) for s, e in speech)


def gap_s(chunk, words):
    """块内空洞：相邻两词之间夹着的 VAD 语音秒数，取最大。

    块首到第一个词、最后一个词到块尾也算——被吞掉半个块正是这两种形态。
    一个词都没有时，整块语音就是一个空洞。

    收成内建 float：真机上词的时刻是 numpy 标量（faster-whisper 的 Word），numpy 的
    算术和比较会一路吐 numpy 类型，numpy 的 bool 不是 Python bool，报告一进 json 就炸——
    而那一炸发生在写正本的时候。
    """
    pts = [chunk["start"]]
    for w in words:
        pts.append(w[0])
        pts.append(w[1])
    pts.append(chunk["end"])
    best = 0.0
    for lo, hi in zip(pts[0::2], pts[1::2]):
        best = max(best, _speech_between(chunk["speech"], lo, hi))
    return float(best)


def rep4(text):
    """同一个 4 字汉字串出现的最大次数。复读幻觉的机械判据。"""
    h = han(text)
    c = Counter(h[i:i + 4] for i in range(len(h) - 3))
    return max(c.values()) if c else 0


def kept_ratio(old, new):
    """原文汉字按顺序出现在新版里的比例。

    两边都只取汉字，用 difflib 的 matching blocks 总长 ÷ 原文汉字数。原文一个汉字
    都没有时是 1.0（「全都在」是空集上的真命题）——整块被吞光恰恰是最该补的情形，
    不能因为除零把它挡在门外。
    """
    o, n = han(old), han(new)
    if not o:
        return 1.0
    m = difflib.SequenceMatcher(None, o, n, autojunk=False).get_matching_blocks()
    return sum(b.size for b in m) / len(o)


# ---------------------------------------------------------------- 判据
def is_suspect(chunk, text, words):
    """疑似吞块：语音够长，且字太少或块内空着一大段。"""
    sp = speech_s(chunk)
    if sp < MIN_SPEECH_S:
        return False
    # bool()：这个值直接进报告的 residual，见 gap_s 的说明
    return bool(n_han(text) / sp < MIN_DENSITY or gap_s(chunk, words) >= MAX_GAP_S)


def acceptable(old, new):
    """新版够不够格参选。返回 (参选, 不参选的原因)；参选时原因是 None。"""
    why = []
    gain = n_han(new) - n_han(old)
    if gain < MIN_GAIN_HAN:
        why.append("gain=%d<%d" % (gain, MIN_GAIN_HAN))
    k = kept_ratio(old, new)
    if k < MIN_KEPT:
        why.append("kept=%.2f<%.2f" % (k, MIN_KEPT))
    r = rep4(new)
    if r > MAX_REP4:
        why.append("rep4=%d>%d" % (r, MAX_REP4))
    return (not why), (" ".join(why) if why else None)


# ---------------------------------------------------------------- 块
def group_chunks(speech, max_speech_s=MAX_CHUNK_SPEECH_S):
    """把 VAD 语音区间合成块——合块条件照抄 `faster_whisper.vad.collect_chunks`：
    累计语音超过上限就另起一块。

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


# ---------------------------------------------------------------- 阶梯
def _err(e):
    return ("%s: %s" % (type(e).__name__, e))[:200]


def _report(segments, chunks=0):
    h = sum(n_han(s["text"]) for s in segments)
    return {"rule": rule(), "chunks": chunks, "suspects": 0, "replaced": 0,
            "residual": 0, "errors": 0, "skipped": None, "elapsed_s": None,
            "han_before": h, "han_after": h, "blocks": []}


def skipped(reason, segments, chunks=0):
    """整步没跑成时的报告：不静默，原因照记（红线 9），正本照常写盘。"""
    rep = _report(segments, chunks)
    rep["skipped"] = reason
    return rep


def run(chunks, segments, words, decode, progress=None):
    """疑似吞块逐级切短重解，直到不再疑似。

    chunks    group_chunks 的产物，块 k 对应第一遍的第 k 段
    segments  第一遍的段 [{start, end, speaker, text}, ...]
    words     与 segments 平行的词表，words[k] = [[start, end, word], ...]
    decode    解码回调，见模块头
    progress  可选 progress(已完成疑似块数, 疑似块总数, 这一块)

    返回 (segments, words, report)。入参不被改动：没换过的块原样（同一个对象）
    带回，换过的块是新对象。段数与块数对不上时整步跳过，报告标 `skipped`。
    """
    rep = _report(segments, len(chunks))

    # 块 k 必须对应段 k。对不上就整步跳过：宁可不补，也不能错位改到别的块（红线 1）。
    if len(segments) != len(chunks):
        return list(segments), list(words), skipped(
            "segments != chunks (%d vs %d)" % (len(segments), len(chunks)),
            segments, len(chunks))
    if len(words) != len(segments):
        return list(segments), list(words), skipped(
            "words != segments (%d vs %d)" % (len(words), len(segments)),
            segments, len(chunks))

    marks = [is_suspect(c, segments[k]["text"], words[k]) for k, c in enumerate(chunks)]
    rep["suspects"] = sum(1 for m in marks if m)

    out_segs, out_words, done = list(segments), list(words), 0
    for k, ch in enumerate(chunks):
        if not marks[k]:
            continue
        seg, ws = segments[k], words[k]
        entry = {
            "k": k,
            "start": ch["start"],
            "end": ch["end"],
            "speech_s": round(speech_s(ch), 2),
            "before": {"han": n_han(seg["text"]), "gap": round(gap_s(ch, ws), 2)},
            "tries": [],
            "picked": None,
            "after": None,
            "residual": True,
        }
        best_text, best_words, best_segs, best_l = seg["text"], ws, None, None

        for length in LADDER:
            try:
                d_segs, d_words = decode(k, ch["start"], ch["end"], length)
            except Exception as e:               # 一级失败不拖累别的级、别的块
                entry["tries"].append({"chunk_length": length, "han": None, "gap": None,
                                       "rep4": None, "acceptable": False, "reason": None,
                                       "error": _err(e)})
                rep["errors"] += 1
                continue

            text = "".join(s["text"] for s in d_segs)
            flat = [w for sw in d_words for w in sw]
            try_ = {"chunk_length": length, "han": n_han(text),
                    "gap": round(gap_s(ch, flat), 2), "rep4": rep4(text),
                    "acceptable": False, "reason": None, "error": None}
            # 说话人分离按词重建段且不许改文本，所以词拼起来必须就是段文本。空白
            # 不计（check_diar.py 的 norm 是同一把尺子），字一个都不能差。对不上的
            # 版本是解码器坏了，当这一级失败处理，不静默、更不去「修」。
            if WS.sub("", "".join(w[2] for w in flat)) != WS.sub("", text):
                try_["error"] = "words != text"
                rep["errors"] += 1
                entry["tries"].append(try_)
                continue
            ok, why = acceptable(seg["text"], text)
            try_["acceptable"], try_["reason"] = ok, why
            entry["tries"].append(try_)

            if ok and n_han(text) > n_han(best_text):
                best_text, best_words, best_segs, best_l = text, flat, d_segs, length
            if not is_suspect(ch, best_text, best_words):
                break                            # 取中的版本不再疑似就收手

        entry["picked"] = best_l
        entry["after"] = {"han": n_han(best_text),
                          "gap": round(gap_s(ch, best_words), 2)}
        entry["residual"] = is_suspect(ch, best_text, best_words)
        if best_l is not None:
            new = dict(seg)
            new["text"] = best_text
            new["start"] = best_segs[0]["start"]   # 时刻也来自取中那一级，别留旧跨度
            new["end"] = best_segs[-1]["end"]
            out_segs[k] = new
            out_words[k] = best_words
            rep["replaced"] += 1
        if entry["residual"]:
            rep["residual"] += 1
        rep["blocks"].append(entry)

        done += 1
        if progress:
            progress(done, rep["suspects"], ch)

    rep["han_after"] = sum(n_han(s["text"]) for s in out_segs)
    return out_segs, out_words, rep


# ---------------------------------------------------------------- 演示
def demo_decoder(doc):
    """用样例里的假解码表 decodes[k][L] 当解码器。返回 (decode, calls)。"""
    calls = []

    def decode(k, start, end, length):
        calls.append((k, length))
        d = (doc.get("decodes") or {}).get(str(k), {}).get(str(length))
        if d is None:
            raise RuntimeError("no decode for k=%d chunk_length=%d" % (k, length))
        if "error" in d:
            raise RuntimeError(d["error"])
        return d["segments"], d["words"]

    return decode, calls


def _fmt_tries(entry):
    for t in entry["tries"]:
        if t["error"]:
            # 解码抛异常 vs 解出来了但词和文本对不上：两种失败，别混着说
            yield "     %2d 秒: %s %s" % (t["chunk_length"],
                                          "解码失败" if t["han"] is None else "输出弃用",
                                          t["error"])
        else:
            mark = "参选" if t["acceptable"] else ("不参选 " + (t["reason"] or ""))
            yield "     %2d 秒: %d 汉字  空洞 %.1fs  复读 %d  %s%s" % (
                t["chunk_length"], t["han"], t["gap"], t["rep4"], mark,
                "  ← 取中" if t["chunk_length"] == entry["picked"] else "")


def cmd_demo(path, dump_json=False):
    doc = json.loads(open(path, encoding="utf-8").read())
    chunks = doc["chunks"]
    segments = doc["transcript"]["segments"]
    words = doc["words"]["segments"]
    decode, calls = demo_decoder(doc)

    segs2, words2, rep = run(chunks, segments, words, decode)

    print("样例 %s（%s，合成，内容虚构）" % (path, doc.get("ep", "?")))
    print("块 %d  段 %d  阶梯 %s 秒" % (len(chunks), len(segments),
                                        "→".join(str(x) for x in LADDER)))
    print("规则  语音 ≥%ds  密度 <%d 字/秒  空洞 ≥%ds  增益 ≥%d 字  保留 ≥%.0f%%  复读 ≤%d"
          % (MIN_SPEECH_S, MIN_DENSITY, MAX_GAP_S, MIN_GAIN_HAN, MIN_KEPT * 100, MAX_REP4))
    print("")

    by_k = {e["k"]: e for e in rep["blocks"]}
    bad = 0
    for k, ch in enumerate(chunks):
        exp = (doc.get("expect") or {}).get(str(k))
        e = by_k.get(k)
        if e is None:
            print("块 %d  %.1f-%.1fs  语音 %.1fs  %d 汉字  → 不疑似，原样"
                  % (k, ch["start"], ch["end"], speech_s(ch), n_han(segments[k]["text"])))
            got = {"suspect": False}
        else:
            print("块 %d  %.1f-%.1fs  语音 %.1fs  %d 汉字 / 空洞 %.1fs  → 疑似"
                  % (k, e["start"], e["end"], e["speech_s"], e["before"]["han"],
                     e["before"]["gap"]))
            for line in _fmt_tries(e):
                print(line)
            if e["picked"] is None:
                print("     结局: 残留，保留原文（%d 汉字）" % e["after"]["han"])
            else:
                print("     结局: %d 秒补全，%d → %d 汉字，空洞 %.1f → %.1fs%s"
                      % (e["picked"], e["before"]["han"], e["after"]["han"],
                         e["before"]["gap"], e["after"]["gap"],
                         "，仍残留" if e["residual"] else ""))
            got = {"suspect": True, "picked": e["picked"], "residual": e["residual"]}
        if exp is not None and got != exp:
            bad += 1
            print("     ✗ 与样例 expect 不符：期望 %s，实得 %s" % (exp, got))

    print("")
    print("解码调用 %d 次：%s" % (len(calls), " ".join("%d@%d" % c for c in calls)))
    print("INFO redecode: suspects=%d replaced=%d residual=%d errors=%d han=%d->%d"
          % (rep["suspects"], rep["replaced"], rep["residual"], rep["errors"],
             rep["han_before"], rep["han_after"]))
    head = dict((k, v) for k, v in rep.items() if k != "blocks")
    print("transcript.json 顶层 redecode（略去 blocks 的 %d 条明细）:" % len(rep["blocks"]))
    print(json.dumps(head, ensure_ascii=False, indent=1))
    if dump_json:
        print(json.dumps(rep, ensure_ascii=False, indent=1))

    if bad:
        print("与样例 expect 不符的块：%d" % bad)
        return 1
    print("与样例 expect 逐块一致。")
    return 0


def main(argv=None):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(prog="redecode.py", description="吞块补解的规则层")
    ap.add_argument("--demo", metavar="FIXTURE",
                    help="拿样例里的假解码表跑一遍规则层，打印每块结局与报告")
    ap.add_argument("--json", action="store_true", help="连 blocks 明细一起打印")
    a = ap.parse_args(argv)
    if not a.demo:
        ap.error("这个模块是给 smpc.py import 的；单独跑只有 --demo")
    return cmd_demo(a.demo, a.json)


if __name__ == "__main__":
    sys.exit(main())
