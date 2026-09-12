#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""stage12.py — SPEC §4 阶段 1（分块）+ 阶段 2（channel 抽取）

    python scripts/stage12.py --vault <vault> --ep EP03

一集逐字稿进来，`_review/EP{n}-{块}.draft.md` 出去。中间四件事：

  1. 分块      20–30 分钟一块、1–2 分钟重叠，切在 segment 边界（ASR 无标点，
               这是能拿到的最接近「句子边界」的东西）
  2. 无头调用  claude -p --system-prompt-file prompts/stage2-extract.md
               --model opus --effort high --allowedTools ""
  3. 出口闸门  schema + 三闸门（SPEC §4 阶段2）。schema 挂了重跑整块；
               闸门 1–3 挂了**标记后照进草稿**，绝不静默丢条目
  4. 落草稿    括号式 [key:: value] 断言行（约定 B，只在草稿里用）

红线：本脚本一个字都不生成。它只搬运、切分、机械校验。语义判断全在人那边。

调试用的两个开关（都不烧额度）：
  --chunk-only  只切块，把块文件写出来看看切得对不对
  --replay      用 _pairs/ 里存着的上次原始响应重跑闸门 + 重渲染草稿
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


# ---------------------------------------------------------------- 小工具

def log(msg: str) -> None:
    print(f"[{datetime.now():%H:%M:%S}] {msg}", flush=True)


def hms(sec: float) -> str:
    sec = int(round(sec))
    return f"{sec // 3600:02d}:{sec % 3600 // 60:02d}:{sec % 60:02d}"


TS_RE = re.compile(r"\[\d{1,2}:\d{2}:\d{2}\]")
WS_RE = re.compile(r"\s+", re.UNICODE)
# 全角空格 / 零宽 不在 \s 里，单列
EXTRA_WS = "\u3000\u200b\u200c\u200d\ufeff"


def norm(s: str) -> str:
    """闸门 1 的归一化：去时间戳、去空白。SPEC 只授权这两样，不动标点。"""
    s = TS_RE.sub("", s or "")
    s = s.translate({ord(c): None for c in EXTRA_WS})
    return WS_RE.sub("", s)


# 闸门 2 额外去掉人名分隔符：模型把「杰西利维摩尔」规整成「杰西·利维摩尔」是
# prompt 允许的（§三 名称），但引文里没有那个点。这属于机械归一，不是放水。
SEP_CHARS = "·・‧∙•.．-–—_ "


def norm_entity(s: str) -> str:
    s = norm(s)
    return s.translate({ord(c): None for c in SEP_CHARS})


def sha8(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()[:8]


# ---------------------------------------------------------------- 读 vault

FM_RE = re.compile(r"\A\ufeff?---\r?\n(.*?)\r?\n---\r?\n", re.S)


def read_frontmatter(text: str) -> dict:
    """够用就行的 YAML 子集：单行 key: value，值支持 [..] 列表和引号。"""
    m = FM_RE.match(text)
    if not m:
        return {}
    out = {}
    for line in m.group(1).splitlines():
        kv = re.match(r"^([^:#\s][^:]*):\s*(.*)$", line)
        if not kv:
            continue
        k, v = kv.group(1).strip(), kv.group(2).strip()
        if v.startswith("[") and v.endswith("]"):
            inner = v[1:-1].strip()
            v = [x.strip().strip('"').strip("'") for x in inner.split(",")] if inner else []
        else:
            v = v.strip('"').strip("'")
        out[k] = v
    return out


SPK_LINE_RE = re.compile(r"\[(SPEAKER_\d+)::\s*([^\]]*)\]")


def read_speakers(note_text: str, fm: dict) -> dict:
    """SPEAKER_XX → 「名字（角色）」。名字取自笔记里人点过的方括号，角色取自
    frontmatter 的 主播/嘉宾。点不出来的保持 SPEAKER_XX 原样——不许编。"""
    hosts = set(fm.get("主播") or [])
    guests = set(fm.get("嘉宾") or [])
    out = {}
    for tag, raw in SPK_LINE_RE.findall(note_text):
        name = (raw or "").strip()
        if not name:
            continue
        # 首次登记允许写「历史哥 嘉宾」，取第一段当名字
        name = name.split()[0]
        role = "主播" if name in hosts else "嘉宾" if name in guests else None
        out[tag] = f"{name}（{role}）" if role else name
    return out


# ---------------------------------------------------------------- 阶段 1 分块

def _rewind(segs: list, lo: int, boundary: int, overlap_s: float) -> int:
    """下一块从哪个 segment 起：从 boundary 往回退 overlap_s。"""
    back_to = segs[boundary]["end"] - overlap_s
    k = boundary + 1
    while k > lo + 1 and segs[k - 1]["start"] >= back_to:
        k -= 1
    return k


def chunk_segments(segs: list, target_s: float, max_s: float, min_s: float,
                   overlap_s: float) -> list:
    """按时长切块，边界永远落在 segment 之间。返回 [{label,segs,start,end}]。

    重叠的实现：下一块的起点往回退 overlap_s，取第一个 start >= 那个时刻的
    segment。因此重叠段的文本在两块里各出现一次——这是 SPEC 要的（跨块的话
    别被切断），代价是同一条渠道可能被抽两遍，留给阶段 3 的人去重。
    """
    if not segs:
        return []
    n = len(segs)
    bounds = []                                   # [(首段下标, 末段下标)]
    i = 0
    while i < n:
        start = segs[i]["start"]
        j = i
        while j < n - 1 and segs[j]["end"] - start < target_s:
            j += 1
        # 收尾：剩下的不够 min 就并进本块（别留一个两分钟的碎块），但不许破 max
        rest_end = segs[-1]["end"]
        if rest_end - segs[j]["end"] < min_s and rest_end - start <= max_s:
            j = n - 1
        bounds.append((i, j))
        if j >= n - 1:
            break
        i = _rewind(segs, i, j, overlap_s)

    # 并不进来（会破 max）又实在太短的尾巴：把倒数第二块的边界往回挪，两块均分。
    # 32 分钟一集本来切成 25+8.5，均分后是 16+17.5——都在 min 以下，但比留个
    # 八分钟的零头强：块数一样多，注意力分布还更均匀。
    if len(bounds) >= 2:
        (a0, _), (b0, b1) = bounds[-2], bounds[-1]
        if segs[b1]["end"] - segs[b0]["start"] < min_s / 2:
            mid = (segs[a0]["start"] + segs[b1]["end"]) / 2
            m = a0
            while m < b1 - 1 and segs[m]["end"] < mid:
                m += 1
            bounds[-2] = (a0, m)
            bounds[-1] = (_rewind(segs, a0, m, overlap_s), b1)

    chunks = []
    for idx, (a, b) in enumerate(bounds):
        cur = segs[a:b + 1]
        chunks.append({"label": chr(ord("A") + idx) if idx < 26 else f"Z{idx}",
                       "segs": cur, "start": cur[0]["start"], "end": cur[-1]["end"]})
    return chunks


def render_chunk(ep: str, chunk: dict, fm: dict, spk: dict, entities: list) -> str:
    """块文件＝喂给模型的**全部**输入。格式对齐 prompt 第零节。"""
    head = [
        f"episode: {ep}",
        f"chunk: {chunk['label']}",
        f"播出日期: {fm.get('播出日期', '未知')}",
        f"时间范围: {hms(chunk['start'])}–{hms(chunk['end'])}",
        f"说话人: {'、'.join(dict.fromkeys(spk.values())) or '未点名'}",
        f"已知实体名单: {'、'.join(entities) if entities else '（空）'}",
        "---",
    ]
    body = []
    for s in chunk["segs"]:
        who = spk.get(s.get("speaker") or "", s.get("speaker") or "未知")
        body.append(f"[{hms(s['start'])}] {who}: {s.get('text', '').strip()}")
    return "\n".join(head) + "\n" + "\n".join(body) + "\n"


def chunk_body(chunk_text: str) -> str:
    """块文件里 `---` 之后的逐字稿正文——闸门只在这上面匹配，块头不算原文。"""
    _, _, body = chunk_text.partition("\n---\n")
    return body


# ---------------------------------------------------------------- 阶段 2 调用

def run_claude(prompt_file: Path, chunk_text: str, model: str, effort: str,
               timeout: int) -> dict:
    exe = shutil.which("claude")
    if not exe:
        raise RuntimeError("PATH 里找不到 claude CLI")
    argv = [
        exe, "-p",
        "--system-prompt-file", str(prompt_file),
        "--model", model,
        "--effort", effort,
        "--output-format", "json",
        # 提取不需要任何工具。禁掉可消掉「agent 跑去读文件」整类失败模式（SPEC §4）
        "--allowedTools", "",
    ]
    # cwd 放空目录：躲开 CLAUDE.md 自动发现，别让项目指令混进抽取上下文
    with tempfile.TemporaryDirectory(prefix="sm-stage2-") as cwd:
        p = subprocess.run(argv, input=chunk_text, cwd=cwd, timeout=timeout,
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace")
    if p.returncode != 0:
        raise RuntimeError(f"claude 退出码 {p.returncode}: {(p.stderr or '')[:500]}")
    try:
        env = json.loads(p.stdout)
    except json.JSONDecodeError:
        raise RuntimeError(f"claude 的 --output-format json 没给出 JSON: {p.stdout[:300]}")
    if env.get("is_error"):
        raise RuntimeError(f"claude 报错: {str(env.get('result'))[:500]}")
    return env


def extract_json(raw: str) -> dict:
    """从模型回答里挖出那个 JSON 对象。它可能裹在 ``` 里或带前言。"""
    s = raw.strip()
    fence = re.search(r"```(?:json)?\s*(.+?)```", s, re.S)
    if fence:
        s = fence.group(1).strip()
    start = s.find("{")
    if start < 0:
        raise ValueError("响应里没有 JSON 对象")
    depth, in_str, esc = 0, False, False
    for idx in range(start, len(s)):
        ch = s[idx]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return json.loads(s[start:idx + 1])
    raise ValueError("JSON 对象没有闭合")


# ---------------------------------------------------------------- 闸门 0 schema

ROW_KEYS = ["id", "type", "正文", "情态", "谁说的", "归因类型", "录音时间戳",
            "渠道类型", "名称", "作者或机构", "取数地址", "链接", "原话口径",
            "为什么值得看", "事件时间原文", "事件时间", "事件时间止", "事件时间精度",
            "实体", "主题候选", "素材", "source_quote", "存疑原因"]

ENUM = {
    "type": {"channel"},
    "情态": {"确定", "推测", "传闻"},
    "归因类型": {"无外部归因", "具名信源", "模糊信源", "匿名私人信源", "转述他人"},
    "渠道类型": {"数据源", "书", "报道", "专栏", "访谈", "播客", "报告", "机构文件", "人"},
    "事件时间精度": {"day", "month", "year", "decade", "era", "未知"},
}
TS_EXACT = re.compile(r"^\d{1,2}:\d{2}:\d{2}$")
DATE_EXACT = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def check_schema(obj: dict) -> list:
    """闸门 0。返回错误列表；非空即整块重跑（SPEC：不合法直接重跑该块）。"""
    errs = []
    if not isinstance(obj, dict):
        return ["顶层不是对象"]
    for k in ("episode", "chunk", "rows"):
        if k not in obj:
            errs.append(f"顶层缺 `{k}`")
    if not isinstance(obj.get("rows"), list):
        errs.append("`rows` 不是数组")
        return errs
    if "归因目击" in obj and not isinstance(obj["归因目击"], list):
        errs.append("`归因目击` 不是数组")
    for n, row in enumerate(obj["rows"], 1):
        tag = (row or {}).get("id") or f"第{n}条"
        if not isinstance(row, dict):
            errs.append(f"{tag}: 不是对象")
            continue
        for k in ROW_KEYS:
            if k not in row:
                errs.append(f"{tag}: 缺字段 `{k}`")
        for k, allowed in ENUM.items():
            v = row.get(k)
            if k == "事件时间精度" and v in (None, ""):
                continue
            if v not in allowed:
                errs.append(f"{tag}: `{k}` = {v!r} 不在枚举内")
        if not isinstance(row.get("source_quote"), list) or not row.get("source_quote"):
            errs.append(f"{tag}: `source_quote` 必须是非空数组")
        for k in ("实体", "主题候选"):
            if not isinstance(row.get(k), list):
                errs.append(f"{tag}: `{k}` 不是数组")
        if not isinstance(row.get("素材"), bool):
            errs.append(f"{tag}: `素材` 不是布尔")
        if not TS_EXACT.match(str(row.get("录音时间戳") or "")):
            errs.append(f"{tag}: `录音时间戳` 不是 HH:MM:SS")
        if not str(row.get("正文") or "").strip():
            errs.append(f"{tag}: `正文` 为空")
        et = row.get("事件时间")
        if et not in (None, "") and not DATE_EXACT.match(str(et)):
            errs.append(f"{tag}: `事件时间` 不是补全到日的 ISO")
    return errs


# ---------------------------------------------------------------- 闸门 1–3

LINE_TS_RE = re.compile(r"^\[(\d{1,2}:\d{2}:\d{2})\]", re.M)
# 非贪婪：说话人名里不会有冒号，正文里可能有——贪婪会一路吃到句中那个冒号
LINE_HEAD_RE = re.compile(r"^\[\d{1,2}:\d{2}:\d{2}\]\s*[^:：\n]{0,40}?[:：]\s?", re.M)


def haystack(body: str) -> str:
    """闸门 1 的干草堆：块正文去掉每行的「[时间] 说话人: 」行首，再归一化。

    行首是渲染出来的脚手架，不是主播说的话。留着它，**任何跨行引文都会假失败**
    ——而 prompt 恰恰要求引文取语义自足的完整句、宁可多带一句相邻上下文，
    一行才 30 秒，跨行是常态。
    """
    return norm(LINE_HEAD_RE.sub("", body))


def check_gates(row: dict, nbody: str, ts_set: set) -> list:
    """闸门 1/2/3。只判机械纪律，不判语义。返回人话的失败说明列表。

    `nbody` 是 haystack() 的产物（已归一化）。
    失败**不丢条目**（SPEC §4 阶段2），调用方负责把它标进草稿。
    """
    fails = []
    quotes = [q for q in (row.get("source_quote") or []) if str(q or "").strip()]

    miss = [q for q in quotes if norm(str(q)) not in nbody]
    if miss:
        fails.append("闸门1 引文未逐字命中：" + "；".join(f"「{str(q)[:24]}…」" for q in miss))

    joined = norm_entity("".join(str(q) for q in quotes))
    off = [e for e in (row.get("实体") or []) if norm_entity(str(e)) not in joined]
    if off:
        fails.append("闸门2 实体名不在自己引文里：" + "、".join(str(e) for e in off))

    if str(row.get("录音时间戳") or "") not in ts_set:
        fails.append(f"闸门3 时间戳 {row.get('录音时间戳')} 在本块不存在")
    return fails


# ---------------------------------------------------------------- 渲染草稿

def flat(v) -> str:
    """压成一行。草稿是给人读的散文体，不是 [key:: value] 容器，所以除了换行
    没有别的东西要转义——引文得以一个字不差地原样落进去。"""
    s = "" if v is None else str(v)
    return WS_RE.sub(" ", s.replace("\r", " ").replace("\n", " ")).strip()


# 「显示名 → 字段名」。空的一律不渲染：A-01 二十个字段里八个是空的，
# 全打出来只会把真正有内容的那三行埋掉。
DETAIL_FIELDS = [
    ("为什么值得看", "为什么值得看"),
    ("他的原话口径", "原话口径"),
    ("去哪取", "取数地址"),
    ("链接", "链接"),
    ("作者/机构", "作者或机构"),
]


def render_row(row: dict, fails: list) -> list:
    """一条 channel 渲染成给人看的一小节。

    **不用 §5.1 那种一行挤二十个 `[key:: value]` 的写法**——那是 EP 笔记（容器）
    的格式，为的是 Dataview 跨集行级查询必须同行。草稿是人**唯一**要看的界面，
    套容器格式等于把唯一的阅读面也变成不可读。转成行内字段是阶段 4 落库的事。
    """
    flag = " ⛔" if (fails or row.get("存疑原因")) else ""
    title = flat(row.get("名称")) or flat(row.get("正文"))[:24] + "…"
    out = [f"### {flat(row.get('id'))}{flag}　{title}", ""]

    # 时间戳放最前面且不加反引号：时间戳插件跳过 code 元素，包起来就点不动了
    meta = [flat(row.get("录音时间戳")), flat(row.get("渠道类型")), flat(row.get("情态")),
            flat(row.get("谁说的"))]
    att = flat(row.get("归因类型"))
    if att and att != "无外部归因":
        meta.append(att)
    if row.get("素材"):
        meta.append("**素材**")
    out += ["　·　".join(x for x in meta if x), ""]
    out += [flat(row.get("正文")), ""]

    if fails:
        out += ["> [!bug] 闸门没过（机械校验，不是语义判断）",
                "> " + "；".join(flat(f) for f in fails),
                "> 条目**没有被丢掉**——留在这儿由你处置。", ""]
    if row.get("存疑原因"):
        out += ["> [!warning] ⛔ 模型自己觉得这条可疑",
                "> " + flat(row["存疑原因"]), ""]

    for label, key in DETAIL_FIELDS:
        v = flat(row.get(key))
        if v:
            out.append(f"- **{label}**　{v}")
    when = flat(row.get("事件时间原文"))
    if when:
        span = " → ".join(x for x in (flat(row.get("事件时间")),
                                      flat(row.get("事件时间止"))) if x)
        out.append(f"- **说的是什么时候**　{when}"
                   + (f"（{span}，精度 {flat(row.get('事件时间精度'))}）" if span else ""))
    ents = [flat(e) for e in (row.get("实体") or []) if flat(e)]
    if ents:
        # 草稿里不打 [[双链]]：`_review/` 不参与图谱，落库时才建链
        out.append("- **涉及**　" + "、".join(ents))
    if out[-1] != "":
        out.append("")

    quotes = [flat(q) for q in (row.get("source_quote") or []) if flat(q)]
    out.append(f"> [!quote]- 逐字引文 {len(quotes)} 条（点开核对；一个字都不该改过）")
    for q in quotes:
        out += ["> " + q, ">"]
    if out[-1] == ">":
        out.pop()
    out.append("")
    return out


HEADER_NOTE = """> [!info] 怎么用这一页
> 一节一条，都是这一块里**他让你去查、去看、去关注**的东西（本版只抽这一类）。
> **⛔ 的先看**——那是模型自己标了可疑，或者机械校验没过的。其余的扫一眼就行。
> 时间戳可以直接点，跳到录音那一秒听两句。**不需要通读逐字稿。**
> 动作只有几种：改错的、删废的、拿不准的打个 `?`。审完把本文件**挪出 `_review/`** 就算通过。"""


def render_draft(ep: str, chunk: dict, obj: dict, gate_map: dict, meta: dict) -> str:
    rows = obj.get("rows") or []
    flagged = sum(1 for r in rows if gate_map.get(id(r)) or r.get("存疑原因"))
    gate_bad = sum(1 for r in rows if gate_map.get(id(r)))
    fm = {
        "type": "review-draft",
        "stage": "2-extract",
        "scope": "channel-only",
        "episode": ep,
        # 时间戳插件按这一行绑音频——有了它，草稿里每个时间戳都能点着跳播，
        # 「听两句再判断」才是一次点击而不是一次寻宝
        "音频": meta.get("audio", f"{ep}.m4a"),
        "chunk": chunk["label"],
        "chunk_span": f"{hms(chunk['start'])}-{hms(chunk['end'])}",
        "engine": meta.get("engine", ""),
        "prompt_version": meta.get("prompt_version", ""),
        "prompt_sha8": meta.get("prompt_sha8", ""),
        "generated_at": meta.get("generated_at", ""),
        "cost_usd": meta.get("cost_usd", ""),
        "duration_s": meta.get("duration_s", ""),
        "gates": "passed" if not gate_bad else "failed-with-flags",
        "rows": len(rows),
        "flagged": flagged,
    }
    out = ["---"]
    out += [f"{k}: {v}" for k, v in fm.items()]
    out += ["---", "", f"# {ep} 块{chunk['label']} 待审"
            f"（录音 {hms(chunk['start'])}–{hms(chunk['end'])}）", "", HEADER_NOTE, ""]
    if rows:
        out += [f"**{len(rows)} 条，其中 ⛔ {flagged} 条要你重点看。**", ""]
    out += ["---", ""]
    if rows:
        for r in rows:
            out += render_row(r, gate_map.get(id(r), []))
    else:
        out += ["## 本块没有渠道提及", "",
                "这是正常结果，不是失败——**没有就是没有，硬凑才是失败**。", ""]

    out += ["---", "", "## 机械校验记录", "",
            "> 只判纪律不判语义：引文是不是真的逐字抄的、实体名在不在自己引文里、"
            "时间戳在不在这一块。三条全过也可能是废条目，那是你的判断。", ""]
    if rows:
        out.append(f"- schema：✅ {len(rows)} 条字段齐全、取值在枚举内")
        for n, label in ((1, "引文逐字存在"), (2, "实体名在自己引文里"), (3, "时间戳真实")):
            bad = [r.get("id") for r in rows
                   if any(f.startswith(f"闸门{n}") for f in gate_map.get(id(r), []))]
            out.append(f"- 闸门{n} {label}：" + ("✅" if not bad else "❌ " + "、".join(map(str, bad))))
    else:
        out.append("- 无条目可校验")
    out.append("")

    topics = []
    for r in rows:
        for t in (r.get("主题候选") or []):
            if isinstance(t, dict) and str(t.get("词") or "").strip():
                topics.append((r.get("id"), t.get("词"), t.get("理由") or ""))
    if topics:
        out += ["## 主题候选", "",
                "> 主题词表现在是空的（种子期）。下面是模型的**提议**，你勾选了才算数。", "",
                "| 来自 | 词 | 它的理由 |", "|---|---|---|"]
        out += [f"| {a} | {b} | {flat(c)} |" for a, b, c in topics]
        out.append("")

    seen = obj.get("归因目击") or []
    out += ["## 他从哪听来的（侧录）", "",
            "> 上面抽的是**他让你去看什么**。这里记的是反方向的——**他这话从哪听来的**，"
            "本版不抽成条，先记个数。", ""]
    if seen:
        out += ["| 时间戳 | 信源 | 原话 |", "|---|---|---|"]
        for s in seen:
            if not isinstance(s, dict):
                continue
            out.append(f"| {flat(s.get('录音时间戳'))} | {flat(s.get('信源表述'))} "
                       f"| {flat(s.get('原话'))} |")
    else:
        out.append("（本块没有）")
    out.append("")
    return "\n".join(out)


# ---------------------------------------------------------------- 主流程

def process_chunk(args, paths, ep, chunk, fm, spk, prompt_meta) -> dict:
    label = chunk["label"]
    chunk_path = paths["pairs"] / f"{label}.chunk.md"
    raw_path = paths["pairs"] / f"{label}.raw.json"
    draft_path = paths["review"] / f"{ep}-{label}.draft.md"

    text = render_chunk(ep, chunk, fm, spk, args.entities)
    chunk_path.write_text(text, encoding="utf-8")
    body = chunk_body(text)
    ts_set = set(LINE_TS_RE.findall(body))
    log(f"  块{label} {hms(chunk['start'])}–{hms(chunk['end'])}"
        f"（{len(chunk['segs'])} 段 / {len(body)} 字）→ {chunk_path.name}")

    if args.chunk_only:
        return {"label": label, "state": "chunked"}

    obj, envelope = None, {}
    if args.replay:
        if not raw_path.exists():
            log(f"  块{label} 没有存档的原始响应，跳过（--replay）")
            return {"label": label, "state": "skipped"}
        envelope = json.loads(raw_path.read_text(encoding="utf-8"))
        obj = extract_json(envelope.get("result", ""))
        errs = check_schema(obj)
        if errs:
            log(f"  块{label} 存档响应 schema 就不合法：{errs[:3]}")
            return {"label": label, "state": "schema-failed", "errors": errs}
    else:
        errs = []
        for attempt in range(1, args.retries + 2):
            log(f"  块{label} 调用 claude（{args.model} / effort {args.effort}）"
                f"，第 {attempt} 次…")
            envelope = run_claude(paths["prompt"], text, args.model, args.effort,
                                  args.timeout)
            raw_path.write_text(json.dumps(envelope, ensure_ascii=False, indent=1),
                                encoding="utf-8")
            try:
                obj = extract_json(envelope.get("result", ""))
                errs = check_schema(obj)
            except (ValueError, json.JSONDecodeError) as e:
                obj, errs = None, [f"响应不是合法 JSON：{e}"]
            if not errs:
                break
            log(f"  块{label} 闸门0 不过（{len(errs)} 项）：{errs[:3]}")
            obj = None
        if obj is None:
            paths["failed"].mkdir(parents=True, exist_ok=True)
            fp = paths["failed"] / f"{ep}-{label}.failed.json"
            fp.write_text(json.dumps({"errors": errs, "envelope": envelope},
                                     ensure_ascii=False, indent=1), encoding="utf-8")
            log(f"  ⚠ 块{label} 重试 {args.retries} 次仍不过闸门0 → {fp}（不静默丢块）")
            return {"label": label, "state": "failed", "errors": errs}

    rows = obj.get("rows") or []
    nbody = haystack(body)
    gate_map = {}
    for r in rows:
        f = check_gates(r, nbody, ts_set)
        if f:
            gate_map[id(r)] = f
    # modelUsage 里除了干活的模型，还挂着 CLI 自己顺手起的小调用（会话标题之类）。
    # 按花费取最大那个，才是真正抽这一块的引擎。
    usage = envelope.get("modelUsage") or {}
    engine = max(usage, key=lambda m: usage[m].get("costUSD", 0)) if usage else args.model
    meta = {
        "engine": engine,
        "prompt_version": prompt_meta["version"],
        "prompt_sha8": prompt_meta["sha8"],
        "generated_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "cost_usd": round(envelope.get("total_cost_usd") or 0, 4),
        "duration_s": round((envelope.get("duration_ms") or 0) / 1000),
        "audio": fm.get("音频") or f"{ep}.m4a",
    }
    draft_path.parent.mkdir(parents=True, exist_ok=True)
    draft_path.write_text(render_draft(ep, chunk, obj, gate_map, meta), encoding="utf-8")
    bad = len(gate_map)
    flag = sum(1 for r in rows if gate_map.get(id(r)) or r.get("存疑原因"))
    log(f"  块{label} → {draft_path.name}：{len(rows)} 条 channel，"
        f"⛔ {flag} 条待看（闸门未过 {bad} 条），归因目击 {len(obj.get('归因目击') or [])} 处")
    if meta["duration_s"]:
        log(f"  块{label} 用时 {meta['duration_s']}s，额度折算 ${meta['cost_usd']}"
            f"（{meta['engine']}）")
    return {"label": label, "state": "ok", "rows": len(rows), "flagged": flag,
            "gate_failed": bad, "draft": str(draft_path)}


def main() -> int:
    repo = Path(__file__).resolve().parent.parent
    ap = argparse.ArgumentParser(description="阶段 1 分块 + 阶段 2 channel 抽取")
    ap.add_argument("--vault", default=r"D:\obsidian-task\任务栏\story-machine",
                    help="story-machine 根目录（不是 Obsidian 库根）")
    ap.add_argument("--ep", required=True, help="EP03")
    ap.add_argument("--prompt", default=str(repo / "prompts" / "stage2-extract.md"))
    ap.add_argument("--model", default="opus")
    ap.add_argument("--effort", default="high")
    ap.add_argument("--target", type=float, default=25.0, help="目标块长（分钟）")
    ap.add_argument("--max", dest="max_min", type=float, default=30.0)
    ap.add_argument("--min", dest="min_min", type=float, default=20.0)
    ap.add_argument("--overlap", type=float, default=1.5, help="块间重叠（分钟）")
    ap.add_argument("--retries", type=int, default=2, help="闸门0 不过时重跑几次")
    ap.add_argument("--timeout", type=int, default=1800)
    ap.add_argument("--only", default="", help="只跑某几块，如 A 或 A,C")
    ap.add_argument("--chunk-only", action="store_true", help="只切块，不调模型")
    ap.add_argument("--replay", action="store_true", help="用存档响应重跑闸门+重渲染")
    ap.add_argument("--force", action="store_true", help="草稿已存在也覆盖")
    args = ap.parse_args()
    args.entities = []  # 已知实体名单注入（#30）——entities.json 还没有，先留空

    vault = Path(args.vault)
    ep = args.ep.strip()
    paths = {
        "assets": vault / "_assets",
        "review": vault / "_review",
        "pairs": vault / "_pairs" / ep,
        "failed": vault / "_failed",
        "prompt": Path(args.prompt),
    }
    tr = paths["assets"] / f"{ep}.transcript.json"
    if not tr.exists():
        log(f"✖ 找不到逐字稿 {tr}——这一集跑完阶段 0 了吗？")
        return 2
    if not paths["prompt"].exists():
        log(f"✖ 找不到 prompt {paths['prompt']}")
        return 2

    notes = sorted((vault / "10-Episodes").glob(f"{ep} *.md")) or \
        sorted((vault / "10-Episodes").glob(f"{ep}.md"))
    if not notes:
        log(f"✖ 找不到 {ep} 的笔记")
        return 2
    note_text = notes[0].read_text(encoding="utf-8")
    fm = read_frontmatter(note_text)
    spk = read_speakers(note_text, fm)

    prompt_bytes = paths["prompt"].read_bytes()
    pfm = read_frontmatter(prompt_bytes.decode("utf-8"))
    prompt_meta = {"version": pfm.get("version", "?"), "sha8": sha8(prompt_bytes)}

    data = json.loads(tr.read_text(encoding="utf-8"))
    segs = [s for s in data.get("segments", []) if str(s.get("text", "")).strip()]
    log(f"{ep}『{fm.get('title', '')}』：{len(segs)} 段 / {hms(data.get('duration_s', 0))}"
        f"，prompt {prompt_meta['version']}@{prompt_meta['sha8']}")
    unnamed = sorted({s.get("speaker") for s in segs if s.get("speaker") not in spk})
    if unnamed:
        log(f"⚠ 还有没点名的说话人 {unnamed}——块头和行首会保留 SPEAKER_XX 原样。"
            f"先去笔记里点名，抽出来的『谁说的』才是人名。")

    chunks = chunk_segments(segs, args.target * 60, args.max_min * 60,
                            args.min_min * 60, args.overlap * 60)
    only = {x.strip().upper() for x in args.only.split(",") if x.strip()}
    if only:
        chunks = [c for c in chunks if c["label"] in only]
    log(f"阶段 1：切成 {len(chunks)} 块"
        + ("" if not only else f"（--only 过滤后剩 {len(chunks)} 块）"))
    paths["pairs"].mkdir(parents=True, exist_ok=True)
    paths["review"].mkdir(parents=True, exist_ok=True)

    results = []
    for c in chunks:
        draft = paths["review"] / f"{ep}-{c['label']}.draft.md"
        if draft.exists() and not (args.force or args.chunk_only or args.replay):
            log(f"  块{c['label']} 草稿已存在，跳过（要重跑加 --force）")
            results.append({"label": c["label"], "state": "exists"})
            continue
        results.append(process_chunk(args, paths, ep, c, fm, spk, prompt_meta))

    ok = [r for r in results if r.get("state") == "ok"]
    bad = [r for r in results if r.get("state") in ("failed", "schema-failed")]
    if ok:
        log(f"阶段 2 完成：{len(ok)} 块，共 {sum(r['rows'] for r in ok)} 条 channel，"
            f"⛔ {sum(r['flagged'] for r in ok)} 条待你审 → {paths['review']}")
    if bad:
        log(f"✖ {len(bad)} 块没过闸门0，已落 {paths['failed']}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
