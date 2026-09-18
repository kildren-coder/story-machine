# -*- coding: utf-8 -*-
"""生成吞块补解（SPEC §4 阶段 0「吞块补解」）的合成样例 EP93.redecode.json。

**全部内容虚构**（红线 10）：句子来自下面的 SENT 表，沿用本目录上级 README 的「河口夜话」设定，
不是任何真实直播的转写或改写。改样例请改本脚本重生成，不要手改 JSON：

    python tests/fixtures/redecode/mk_redecode.py

样例的形状：
- chunks      生产 VAD 块：k、原始时间跨度 start/end、VAD 语音区间 speech（秒）
- transcript  第一遍的正本（§5.1 形状，分离前），段 k ↔ 块 k
- words       第一遍的词级时间戳，`[[start, end, word], ...]`，段 k ↔ 块 k；"".join(词) == 段文本
- decodes     假解码表：decodes[k][chunk_length] = {"segments": [...], "words": [...]}（绝对时间）
              或 {"error": "..."}（这一级解码抛异常）
- expect      各块的预期结局（本脚本按 SPEC 规则自己算一遍并断言，测试可以直接用）
"""
from __future__ import annotations

import difflib
import json
import re
from collections import Counter
from pathlib import Path

OUT = Path(__file__).resolve().parent / "EP93.redecode.json"

SENT = [
    "今天我们接着聊北港大桥收费的事情",
    "河口夜市搬迁以后生意变差了不少",
    "老周说货车的费率明年还要再涨一点",
    "阿桥在弹幕里问大桥什么时候通车",
    "我觉得这件事情还要再等一等看看",
    "河口市上个礼拜刚刚发了一个新通知",
    "夜市那边的摊主大多数都不太愿意搬",
    "通勤的人每天过桥要多花二十分钟",
    "北港那一头的路口一到晚上就堵车",
    "这个方案讨论了差不多有一年多了",
]
OTHER = [  # 与 SENT 不重合的句子：用来造「新版里找不到原文」的块
    "隔壁县的渡轮码头去年就已经停运",
    "春天雨水多的时候江面会涨得很高",
    "码头边上那家面馆开了三十多年了",
    "渡轮停了以后老人进城只能坐大巴",
]
HAN = re.compile(r"[一-鿿]")


def text_of(n, pool=SENT, offset=0):
    """从句子表里按顺序截出 n 个汉字的文本。"""
    s, i = "", offset
    while len(s) < n:
        s += pool[i % len(pool)]
        i += 1
    return s[:n]


def words_of(text, spans):
    """两字一词，均匀摊在若干时间区间上。返回 (words, start, end)。"""
    toks = [text[i:i + 2] for i in range(0, len(text), 2)]
    total = sum(e - s for s, e in spans)
    per = total / max(1, len(toks))
    out, si, t = [], 0, spans[0][0]
    for tok in toks:
        s, e = spans[si]
        if t + per > e + 1e-9 and si + 1 < len(spans):
            si += 1
            t = spans[si][0]
        out.append([round(t, 2), round(t + per * 0.9, 2), tok])
        t += per
    return out


def seg(text, spans):
    w = words_of(text, spans)
    assert "".join(x[2] for x in w) == text
    return {"start": w[0][0], "end": w[-1][1], "speaker": None, "text": text}, w


def dec(*parts):
    """parts = [(text, spans), ...] → 一级解码的输出（可能多段：块内 VAD 重新切出的子块）。"""
    segs, words = [], []
    for text, spans in parts:
        s, w = seg(text, spans)
        segs.append({"start": s["start"], "end": s["end"], "text": text})
        words.append(w)
    return {"segments": segs, "words": words}


# ---------------------------------------------------------------- 各块
C = []          # (chunk, (text, spans) 第一遍, {L: decode}, expect)


def chunk(k, speech):
    return {"k": k, "start": speech[0][0], "end": speech[-1][1], "speech": speech}


# 0 正常块：密度 5 字/秒，无空洞 → 不是疑似块
C.append((chunk(0, [[0.0, 9.6], [10.2, 20.0]]), (text_of(97), [[0.0, 9.6], [10.2, 20.0]]), {},
          {"suspect": False}))
# 1 丢尾：只剩开头 3 秒 → 15 s 一级补全
t1 = text_of(120, offset=1)
C.append((chunk(1, [[21.0, 46.0]]), (t1[:12], [[21.0, 24.0]]),
          {15: dec((t1, [[21.0, 46.0]]))},
          {"suspect": True, "picked": 15, "residual": False}))
# 2 丢头；15 s 版块内还空着 10 秒（仍疑似）→ 继续 10 s，10 s 版补全
t2 = text_of(130, offset=2)
C.append((chunk(2, [[47.0, 61.0], [61.5, 75.0]]), (t2[-15:], [[72.0, 75.0]]),
          {15: dec((t2[:55], [[47.0, 58.0]]), (t2[-30:], [[68.0, 75.0]])),
           10: dec((t2[:70], [[47.0, 61.0]]), (t2[70:], [[61.5, 75.0]]))},
          {"suspect": True, "picked": 10, "residual": False}))
# 3 复读：15 s 版字最多但同一 4 字串出现 >5 次 → 不参选；10 s 版补全
t3 = text_of(110, offset=3)
loop = t3[:20] + "好的好的" * 30 + t3[20:30]
C.append((chunk(3, [[76.0, 100.0]]), (t3[:10], [[76.0, 78.0]]),
          {15: dec((loop, [[76.0, 100.0]])), 10: dec((t3, [[76.0, 100.0]]))},
          {"suspect": True, "picked": 10, "residual": False}))
# 4 补不回：三级都只多几个字（< 20）→ 保留原文，残留
t4 = text_of(40, offset=4)
C.append((chunk(4, [[101.0, 121.0]]), (t4[:20], [[101.0, 105.0]]),
          {15: dec((t4[:26], [[101.0, 106.0]])), 10: dec((t4[:24], [[101.0, 106.0]])),
           7: dec((t4[:28], [[101.0, 107.0]]))},
          {"suspect": True, "picked": None, "residual": True}))
# 5 短块：语音 6 秒 < 8 → 不是疑似块（哪怕只有 5 个字）
C.append((chunk(5, [[122.0, 128.0]]), (text_of(5, offset=5), [[122.0, 124.0]]), {},
          {"suspect": False}))
# 6 只有空洞：密度 4 字/秒（够），但后 10 秒语音一个词都没有 → 疑似；15 s 一级补全
t6 = text_of(140, offset=6)
C.append((chunk(6, [[129.0, 154.0]]), (t6[:100], [[129.0, 144.0]]),
          {15: dec((t6, [[129.0, 154.0]]))},
          {"suspect": True, "picked": 15, "residual": False}))
# 7 新版里找不到原文：15 s 版字多但原文汉字只有 <80% 按序出现 → 不参选；10 s 版含原文、补全
t7 = text_of(125, offset=7)
C.append((chunk(7, [[155.0, 180.0]]), (t7[-30:], [[177.0, 180.0]]),
          {15: dec((text_of(100, pool=OTHER), [[155.0, 180.0]])), 10: dec((t7, [[155.0, 180.0]]))},
          {"suspect": True, "picked": 10, "residual": False}))
# 8 解码报错：三级都抛异常 → 保留原文，记错误，残留；不影响其他块
C.append((chunk(8, [[181.0, 206.0]]), (text_of(10, offset=8), [[181.0, 183.0]]),
          {15: {"error": "CUDA out of memory (fake)"}, 10: {"error": "CUDA out of memory (fake)"},
           7: {"error": "CUDA out of memory (fake)"}},
          {"suspect": True, "picked": None, "residual": True}))
# 9 正常块收尾
C.append((chunk(9, [[207.0, 230.0]]), (text_of(115, offset=9), [[207.0, 230.0]]), {},
          {"suspect": False}))


# ---------------------------------------------------------------- 按 SPEC 规则自算一遍，断言与 expect 一致
MIN_SPEECH, MIN_DENS, MAX_GAP, LADDER, MIN_GAIN, MIN_KEPT, MAX_REP4 = 8, 3, 5, (15, 10, 7), 20, 0.8, 5


def han(s):
    return "".join(HAN.findall(s))


def gap(ch, words):
    pts = [ch["start"]] + [x for w in words for x in (w[0], w[1])] + [ch["end"]]
    best = 0.0
    for lo, hi in zip(pts[0::2], pts[1::2]):
        best = max(best, sum(max(0.0, min(e, hi) - max(s, lo)) for s, e in ch["speech"]))
    return best


def suspect(ch, text, words):
    sp = sum(e - s for s, e in ch["speech"])
    return sp >= MIN_SPEECH and (len(han(text)) / sp < MIN_DENS or gap(ch, words) >= MAX_GAP)


def rep4(text):
    h = han(text)
    c = Counter(h[i:i + 4] for i in range(len(h) - 3))
    return max(c.values()) if c else 0


def kept(old, new):
    o, n = han(old), han(new)
    m = difflib.SequenceMatcher(None, o, n, autojunk=False).get_matching_blocks()
    return sum(b.size for b in m) / max(1, len(o))


def simulate(ch, text, words, decodes):
    if not suspect(ch, text, words):
        return {"suspect": False}
    best = (text, words, None)
    for L in LADDER:
        d = decodes.get(L)
        if d is None or "error" in d:
            continue
        t = "".join(s["text"] for s in d["segments"])
        w = [x for ws in d["words"] for x in ws]
        ok = (rep4(t) <= MAX_REP4 and len(han(t)) - len(han(text)) >= MIN_GAIN and kept(text, t) >= MIN_KEPT)
        if ok and len(han(t)) > len(han(best[0])):
            best = (t, w, L)
        if not suspect(ch, best[0], best[1]):
            break
    return {"suspect": True, "picked": best[2], "residual": suspect(ch, best[0], best[1])}


chunks, segments, words, decodes, expect = [], [], [], {}, {}
for ch, (text, spans), dmap, exp in C:
    s, w = seg(text, spans)
    got = simulate(ch, text, w, dmap)
    assert got == exp, (ch["k"], got, exp)
    chunks.append(ch)
    segments.append(s)
    words.append(w)
    if dmap:
        decodes[str(ch["k"])] = {str(L): v for L, v in dmap.items()}
    expect[str(ch["k"])] = exp

doc = {
    "note": "合成样例，内容虚构（红线 10）；由 mk_redecode.py 生成，勿手改。",
    "ep": "EP93",
    "chunks": chunks,
    "transcript": {"ep": "EP93", "diarization": "pending", "segments": segments},
    "words": {"ep": "EP93", "segments": words},
    "decodes": decodes,
    "expect": expect,
}
OUT.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
print("wrote", OUT.name, "chunks", len(chunks), "suspects",
      sum(1 for e in expect.values() if e["suspect"]))
