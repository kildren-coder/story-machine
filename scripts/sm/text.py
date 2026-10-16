# -*- coding: utf-8 -*-
"""时间戳与文本归一。整个包里只有这里允许改写文本形状。"""
from __future__ import annotations

import hashlib
import re

TS_RE = re.compile(r"\[\d{1,2}:\d{2}:\d{2}\]")
TS_EXACT = re.compile(r"^(\d{1,2}):([0-5]\d):([0-5]\d)$")
WS_RE = re.compile(r"\s+", re.UNICODE)
# 全角空格 / 零宽 不在 \s 里，单列
EXTRA_WS = "　​‌‍﻿"


def hms(sec: float) -> str:
    sec = int(round(sec))
    return f"{sec // 3600:02d}:{sec % 3600 // 60:02d}:{sec % 60:02d}"


def parse_hms(s: str) -> int | None:
    """`HH:MM:SS` → 秒。形状不对返回 None（调用方负责报错，这里不抛）。"""
    m = TS_EXACT.match(str(s or "").strip())
    if not m:
        return None
    h, mi, se = (int(x) for x in m.groups())
    return h * 3600 + mi * 60 + se


def norm(s: str) -> str:
    """闸门用的归一化：去时间戳、去空白。只授权这两样，不动标点（红线 2）。

    非字符串照 `str()` 收（`parse_hms` 同样的路子）：闸门拿它比的是逐字稿正本里的
    段文本，正本里混进一个数字不该把整集掀翻在一句 TypeError 上。
    """
    s = TS_RE.sub("", str(s or ""))
    s = s.translate({ord(c): None for c in EXTRA_WS})
    return WS_RE.sub("", s)


def norm_map(s: str) -> tuple[str, list[int]]:
    """`norm()` 的带索引版：返回 (归一化文本, 下标表)，`idx[i]` 是归一化文本第 i 个
    字在原文里的下标。恒有 `norm_map(s)[0] == norm(s)`。

    闸门 1 的归一档要把归一化文本上的一个跨度换回**原文**里的那一截（原文里的
    空格、英文、时间戳原样带着，红线 2），所以得知道每个字是从哪儿来的。`norm()`
    自己不动：它只回答「一不一样」，多数调用方用不上这张表。
    """
    s = str(s or "")
    cut = {i for m in TS_RE.finditer(s) for i in range(*m.span())}
    idx = [i for i, ch in enumerate(s)
           if i not in cut and ch not in EXTRA_WS and not WS_RE.fullmatch(ch)]
    return "".join(s[i] for i in idx), idx


def sha8(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()[:8]
