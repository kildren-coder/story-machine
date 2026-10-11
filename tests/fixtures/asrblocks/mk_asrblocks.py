# -*- coding: utf-8 -*-
"""生成阶段 0 转写规则层（SPEC §4 阶段 0「转写」「标点」，ADR 0006）的合成样例 EP95.asrblocks.json。

**全部内容虚构**（红线 10）：句子沿用 tests/fixtures 的「河口夜话」设定，不是任何真实直播的
转写或改写。改样例请改本脚本重生成，不要手改 JSON：

    python tests/fixtures/asrblocks/mk_asrblocks.py

样例的形状：
- speech         VAD 语音区间（秒），合块后是 6 块
- decodes        假解码表 decodes[k] = {"text": 解码文本, "tokens": [[token, 块内 start, 块内 end], ...]}
- batch_missing  这些块在整批里缺结果（FireRed 内部吞掉异常），单独解才有
- punc           假标点表：段文本 → 加了标点的文本
- expect         预期：各块结局与 asr 计数（本脚本自己算一遍并断言，测试可以直接用）
"""
from __future__ import annotations

import json
import unicodedata
from pathlib import Path

OUT = Path(__file__).resolve().parent / "EP95.asrblocks.json"
MAX_SPEECH_S = 30

# 每块的 VAD 语音区间：块内累计 ≤30 秒，下一块的第一段加进来就超 30 秒
SPEECH = [
    [[12.0, 26.0], [27.0, 39.5]],       # 0  26.5 s
    [[41.0, 49.0], [50.0, 66.0]],       # 1  24 s
    [[70.0, 77.0], [78.0, 96.0]],       # 2  25 s
    [[98.0, 104.0], [105.0, 125.0]],    # 3  26 s
    [[127.0, 132.0], [133.5, 151.0]],   # 4  22.5 s
    [[153.0, 161.0], [162.0, 180.5]],   # 5  26.5 s
]

# (块, 情形, 解码文本, token 要拼成的文本（None = 与解码文本相同）, 标点版)
CASES = [
    (0, "ok", "今天我们接着聊北港大桥收费的事情河口夜市搬迁以后生意变差了不少", None,
     "今天我们接着聊北港大桥收费的事情。河口夜市搬迁以后，生意变差了不少。"),
    # 英文 token 不带空格；文本里英文词前有空格、词与词之间有空格、词后紧接汉字（FireRed 的写法）
    (1, "ok", "老周说 northbridge toll明年还要再涨一点", None,
     "老周说 Northbridge toll，明年还要再涨一点。"),
    (2, "empty", "", None, None),
    # token 与文本对不上（「夜事」≠「夜市」）：整块均分
    (3, "linear", "阿桥在弹幕里问夜市什么时候搬回来", "阿桥在弹幕里问夜事什么时候搬回来",
     "阿桥在弹幕里问，夜市什么时候搬回来？"),
    # 整批里缺结果，单独重解一次拿回来
    (4, "ok", "河口市上个礼拜刚刚发了一个新通知", None,
     "河口市上个礼拜刚刚发了一个新通知。"),
    (5, "ok", "通勤的人每天过桥要多花二十分钟北港那一头的路口一到晚上就堵车", None,
     "通勤的人每天过桥要多花二十分钟，北港那一头的路口一到晚上就堵车。"),
]
BATCH_MISSING = [4]


def keep(ch):
    return ch == "'" or unicodedata.category(ch)[0] in "LN"


def is_punc(ch):
    return unicodedata.category(ch).startswith("P")


def tokens_of(text, speech, block_start):
    """汉字一字一个 token，英文一词一个 token；时刻均摊在块的语音区间上（块内秒）。"""
    toks, word = [], ""
    for ch in text:
        if ch.isascii() and keep(ch):
            word += ch
            continue
        if word:
            toks.append(word)
            word = ""
        if keep(ch):
            toks.append(ch)
    if word:
        toks.append(word)
    total = sum(e - s for s, e in speech)
    per = total / len(toks)
    out, si, t = [], 0, speech[0][0]
    for tok in toks:
        if t + per > speech[si][1] + 1e-9 and si + 1 < len(speech):
            si += 1
            t = speech[si][0]
        out.append([tok, round(t - block_start, 3), round(t + per * 0.9 - block_start, 3)])
        t += per
    return out


def group(speech):
    """合块（与 asrblocks.group_chunks 同一条件，独立再写一遍）。"""
    out, cur, acc = [], [], 0.0
    for s, e in speech:
        if cur and acc + (e - s) > MAX_SPEECH_S:
            out.append(cur)
            cur, acc = [], 0.0
        cur.append([s, e])
        acc += e - s
    if cur:
        out.append(cur)
    return out


def main():
    flat = [iv for blk in SPEECH for iv in blk]
    assert group(flat) == SPEECH, "VAD 区间合出来不是预定的 6 块"

    decodes, punc, fates = {}, {}, {}
    for k, fate, text, tok_text, punc_text in CASES:
        blk = SPEECH[k]
        toks = tokens_of(tok_text or text, blk, blk[0][0]) if text else []
        decodes[str(k)] = {"text": text, "tokens": toks}
        spelled = "".join(c for t in toks for c in t[0] if keep(c))
        wanted = "".join(c for c in text if keep(c))
        assert (spelled == wanted) == (fate in ("ok", "empty")), k
        if punc_text:
            assert "".join(c for c in punc_text if not is_punc(c)).lower().replace(" ", "") \
                == text.lower().replace(" ", ""), k
            punc[text] = punc_text
        fates[str(k)] = fate

    n = len(SPEECH)
    empty = sum(1 for f in fates.values() if f == "empty")
    linear = sum(1 for f in fates.values() if f == "linear")
    doc = {
        "ep": "EP95",
        "note": "合成样例，内容虚构（红线 10）。由 mk_asrblocks.py 生成，不要手改。",
        "speech": flat,
        "decodes": decodes,
        "batch_missing": BATCH_MISSING,
        "punc": punc,
        "expect": {
            "blocks": fates,
            "asr": {"blocks": n, "segments": n - empty, "empty": empty, "errors": 0,
                    "words_linear": linear, "retried": len(BATCH_MISSING)},
        },
    }
    OUT.write_bytes((json.dumps(doc, ensure_ascii=False, indent=1) + "\n").encode("utf-8"))  # LF
    print("wrote", OUT.name, "blocks", n, "segments", n - empty, "empty", empty, "linear", linear)


if __name__ == "__main__":
    main()
