# -*- coding: utf-8 -*-
"""L3 闸门（纯代码）：片段 → 过滤后的片段 + `gates.json`（SPEC §4 L3、§5.4）。

**只删、只警、只补 `quotes[].ctx`，一个字都不改**（红线 2、5）。本层跑三道：

- 闸门 1 引文逐字命中：`norm(quotes[].text)` 是逐字稿**某一段** `norm(text)` 的
  子串（不跨段）。命中的补 `ctx`（该段全文），不命中的整条删掉并计数。
- 闸门 2 时间戳在范围内：`quotes[].ts` 与 `paras` 行首的时刻落在话题
  `[start, end)` 前后各 2 分钟内；`paras` 的另须落在**所属章节**的 `[start, end)`
  内、不含余量——L2 的切片带前后各 2 分钟上下文，那里的内容归相邻章写（ADR 0005）。
  越界的引文删掉并计数，越界的段**只记不删**（红线 2：不删事）。
- 闸门 5 的 ASR 条款：`asr[].heard` 不在所属章节的切片里（本章的行前后各 2 分钟）
  的整条删掉并计数。

闸门 3（限定词）与覆盖失败态（哪一章没整理出来、`passed`）在 #54。

**两把尺子不一样，是故意的**：引文比到**段**（§5.1 正本的 `segments`）——`ctx` 要
的就是「他说这句话的那一段全文」，跨段拼起来的句子逐字稿里并没有这么一句；ASR
条目比的是**章节切片**（§5.2 喂给 L2 的那些行），问的是「模型输入里到底有没有出现
过这个写法」，那就该拿模型看到的那份文本去比。

产物坏了要炸出来：`_digest/` 少文件、JSON 读不出来、片段指着章节表里没有的章，
一律抛异常向上（红线 9：绝不静默丢单元）。片段形状不合 §5.4 不算异常，记在
`gates.json` 的 `schema` 一栏里（失败态归 #54）。
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from .l2 import FRAG_KEYS, KINDS, check_items, check_paras, json_bytes, write_json
from .prov import now_iso
from .text import norm, parse_hms
from .transcript import build_lines, read_transcript, slice_chapter

PAD_S = 120            # 话题范围的余量、章节切片的余量（§4 L3 第 2 条、§5.2）
PARA_TS_RE = re.compile(r"^\[(\d{1,2}:[0-5]\d:[0-5]\d)\]")
COUNTERS = ("quotes_dropped", "quotes_out_of_range", "asr_dropped")


@dataclass
class GateReport:
    """一集的闸门结果。`topics` 就是 `gates.json` 里那张表，`frags` 是过滤后的
    片段（渲染读这一份，省得再读一遍盘）。"""

    ep: str
    generated_at: str
    topics: dict[str, dict] = field(default_factory=dict)
    frags: dict[str, dict] = field(default_factory=dict)

    @property
    def totals(self) -> dict[str, int]:
        """整集合计。块首行与日志只报这几个数（红线 6：不打印产物内容）。"""
        out = {k: sum(int(t.get(k) or 0) for t in self.topics.values()) for k in COUNTERS}
        out["paras_out_of_range"] = sum(len(t.get("paras_out_of_range") or [])
                                        for t in self.topics.values())
        return out

    def doc(self) -> dict:
        return {"ep": self.ep, "generated_at": self.generated_at, "topics": self.topics}


def read_json(path: str | Path):
    """闸门这一侧读 JSON **不吞异常**：产物坏了当场炸。

    吞掉的话，读不出来的片段会被当成「这个话题没有引文」放行，人在笔记上看到的
    是一节空话题，`gates.json` 还写着全 0（红线 9）。
    """
    return json.loads(Path(path).read_bytes().decode("utf-8"))


# ---------------------------------------------------------------- 闸门 4：形状

def check_shape(frag) -> list[str]:
    """片段合不合 §5.4。空列表算过；`provenance` 不查（§4.1：schema 检查忽略该键）。

    本票只记不判——schema 不过算失败态是 #54 的事。
    """
    tag = "片段"
    if not isinstance(frag, dict):
        return [f"{tag}: 顶层不是对象"]
    errs: list[str] = []
    for k in FRAG_KEYS:
        if k not in frag:
            errs.append(f"{tag}: 缺字段 `{k}`")
    for k in ("id", "chapter", "title", "gist"):
        if k in frag and not (isinstance(frag[k], str) and frag[k].strip()):
            errs.append(f"{tag}: `{k}` 不是非空字符串")
    for k in ("start", "end"):
        if k in frag and parse_hms(frag[k]) is None:
            errs.append(f"{tag}: `{k}` = {frag[k]!r} 读不出时刻")
    if "kind" in frag and frag["kind"] not in KINDS:
        errs.append(f"{tag}: `kind` = {frag['kind']!r} 不是 talk / aside / filler 之一")
    if "who" in frag and not (isinstance(frag["who"], list)
                              and all(isinstance(x, str) for x in frag["who"])):
        errs.append(f"{tag}: `who` 不是字符串数组")
    return errs + check_paras(frag, tag) + check_items(frag, tag)


# ---------------------------------------------------------------- 闸门 1、2、5

def hit_segment(ntext: str, ts: int | None, nsegs: list[tuple[str, dict]]) -> dict | None:
    """引文命中的那一段（闸门 1）：`norm` 后的子串匹配，不跨段。没命中返回 None。

    同一句话整集里说过好几遍时取离 `ts` 最近的那一段——`ctx` 要的是他说这一句的
    那一处，不是字面上第一处。
    """
    if not ntext:
        return None                     # 空引文不是任何一段的子串，别让它白捡一个命中
    hits = [s for n, s in nsegs if n and ntext in n]
    if not hits:
        return None
    if ts is None:
        return hits[0]
    return min(hits, key=lambda s: abs(float(s.get("start") or 0) - ts))


def in_topic(ts: int | None, start: int, end: int) -> bool:
    """话题范围前后各 2 分钟，两端都算在范围内（闸门 2）。

    宽容一点是有意的：判错要删条目，而人说着说着回头补一句是常事（§4 L3 第 2 条）。
    """
    return ts is not None and start - PAD_S <= ts <= end + PAD_S


def in_chapter(ts: int | None, start: int, end: int) -> bool:
    """章节范围，**不含余量**（闸门 2 对 `paras` 的那一条）。

    切片里前后各 2 分钟的行只供理解，那段时间里的内容归相邻章写（ADR 0005）：
    段落的时间戳落在余量里，说明这一章把邻章的内容也写进来了。
    """
    return ts is not None and start <= ts < end


def gate_frag(frag: dict, chapter: dict, nsegs: list[tuple[str, dict]],
              nslice: list[str]) -> tuple[dict, dict]:
    """跑完三道闸门的 (片段, 这个话题在 `gates.json` 里的一行)。

    片段是新对象：**只删条目、只补 `ctx`**，留下来的字符串值一个字节都不动。
    """
    entry = {"quotes_dropped": 0, "quotes_out_of_range": 0, "paras_out_of_range": [],
             "asr_dropped": 0, "schema": check_shape(frag) or "ok"}
    out = dict(frag)
    t0, t1 = parse_hms(frag.get("start")), parse_hms(frag.get("end"))
    c0, c1 = parse_hms(chapter.get("start")), parse_hms(chapter.get("end"))

    if isinstance(frag.get("quotes"), list):
        kept = []
        for q in frag["quotes"]:
            if not isinstance(q, dict):
                entry["quotes_dropped"] += 1        # 形状已经报在 schema 那一栏
                continue
            ts = parse_hms(q.get("ts"))
            seg = hit_segment(norm(q.get("text")), ts, nsegs)
            if seg is None:
                entry["quotes_dropped"] += 1
                continue
            # 话题的起止读不出来就不跑闸门 2：宁可不删（红线 2），schema 那一栏
            # 已经把这个片段报出来了
            if t0 is not None and t1 is not None and not in_topic(ts, t0, t1):
                entry["quotes_out_of_range"] += 1
                continue
            kept.append(dict(q, ctx=str(seg.get("text") or "")))
        out["quotes"] = kept

    if isinstance(frag.get("paras"), list) and None not in (t0, t1, c0, c1):
        for p in frag["paras"]:
            m = PARA_TS_RE.match(str(p or "").strip())
            if not m:                               # 没有行首时间戳，schema 那一栏报
                continue
            ts = parse_hms(m.group(1))
            if not (in_topic(ts, t0, t1) and in_chapter(ts, c0, c1)):
                entry["paras_out_of_range"].append(m.group(1))

    if isinstance(frag.get("asr"), list):
        kept_asr = []
        for a in frag["asr"]:
            heard = norm(a.get("heard")) if isinstance(a, dict) else ""
            if heard and any(heard in n for n in nslice):
                kept_asr.append(a)
            else:
                entry["asr_dropped"] += 1
        out["asr"] = kept_asr

    return out, entry


# ---------------------------------------------------------------- 跑一集

def run_gates(paths, ep: str, *, generated_at: str | None = None, log=print) -> GateReport:
    """跑完一集的闸门：写回过滤后的片段，写 `_digest/EP{n}/gates.json`。

    片段按 `topics.json` 的顺序过，所属章节按片段自己的 `chapter` 认（不按文件名）。
    写回**只在内容真变了时候落盘**：闸门跑两遍不该把一整个 `_digest/` 的 mtime
    翻新一遍，人对着盘上的时间找「这一趟到底改了什么」才找得准。
    """
    d = paths.digest(ep)
    chapters = {c["id"]: c for c in (read_json(d / "chapters.json").get("chapters") or [])
                if isinstance(c, dict) and c.get("id")}
    heads = read_json(d / "topics.json").get("topics") or []
    segments, _ = read_transcript(paths.transcript(ep))
    nsegs = [(norm(s.get("text")), s) for s in segments]
    lines = build_lines(segments)
    nslices: dict[str, list[str]] = {}

    report = GateReport(ep=ep, generated_at=generated_at or now_iso())
    changed = 0
    for head in heads:
        tid = str((head or {}).get("id") or "").strip()
        if not tid:
            raise ValueError(f"{paths.rel(d / 'topics.json')} 里有话题没有 `id`")
        frag = read_json(d / f"frag-{tid}.json")
        ch_id = frag.get("chapter") if isinstance(frag, dict) else None
        if ch_id not in chapters:
            # 孤儿片段（L1 重切过而 L2 没重跑）。这里判不了它该归哪一章，闸门 2
            # 与闸门 5 就没有尺子可用——不许当成「全都通过」放行
            raise ValueError(f"frag-{tid}.json 的 `chapter` = {ch_id!r} "
                             f"不在 {paths.rel(d / 'chapters.json')} 里")
        if ch_id not in nslices:
            ch = chapters[ch_id]
            groups = slice_chapter(lines, parse_hms(ch.get("start")) or 0,
                                   parse_hms(ch.get("end")) or 0, PAD_S)
            nslices[ch_id] = [norm(ln["text"]) for g in groups for ln in g]

        out, entry = gate_frag(frag, chapters[ch_id], nsegs, nslices[ch_id])
        path = d / f"frag-{tid}.json"
        if json_bytes(out) != path.read_bytes():
            write_json(path, out)
            changed += 1
        report.topics[tid] = entry
        report.frags[tid] = out

    write_json(d / "gates.json", report.doc())
    log(f"    L3：{len(report.topics)} 个话题过了闸门，写回 {changed} 份片段"
        f"（越界的段只记不删，红线 2）")
    bad = [tid for tid, e in report.topics.items() if e.get("schema") != "ok"]
    if bad:
        # 本票不产生失败态（#54 才判），但不报的话人只能自己去翻 gates.json
        log(f"    ⚠ {len(bad)} 个话题的片段形状不合 §5.4（见 "
            f"{paths.rel(d / 'gates.json')} 的 `schema`）")
    return report
