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


def sha8(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()[:8]
