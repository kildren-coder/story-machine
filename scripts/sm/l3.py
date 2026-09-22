# -*- coding: utf-8 -*-
"""L3 闸门（纯代码）：片段 → 过滤后的片段 + `gates.json`（SPEC §4 L3、§5.4）。

**只删、只警、只补 `ctx`、只把近似命中的 `quotes[].text` 换成逐字稿原文**（红线
2、5）。本层跑三道：

- 闸门 1 引文逐字命中，三档，顺序固定：`norm(quotes[].text)` 是逐字稿**某一段**
  `norm(text)` 的子串（不跨段）→ 留，补 `ctx`（该段全文）；逐字对不上但跟 `ts`
  前后 2 分钟内某一段的某个跨度只差一两个字（半全局编辑距离 ≤
  `max(1, 字数 // 10)`、引文 ≥ `SNAP_MIN_LEN` 字）→ 把 `text` 换成该跨度在原文里
  的那一截、补 `ctx`、计 `quotes_snapped` 并把 `from` / `to` 记进 `snapped`（红线
  9：不静默）；还对不上 → 整条删掉并计数。
  归一只会把引文换成逐字稿里的原话，模型少抄或错抄一两个字不至于整条丢掉，丢掉
  的限定词随原句一起回来（红线 2）。
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
from .text import norm, norm_map, parse_hms
from .transcript import build_lines, read_transcript, slice_chapter

PAD_S = 120            # 话题范围的余量、章节切片的余量（§4 L3 第 2 条、§5.2）
SNAP_MIN_LEN = 6       # 短于这个字数（归一化后）的引文不归一：一字之差可能就是另一句话
SNAP_EDITS_PER_10 = 1  # 每 10 字容许差几处，下限 1：超出一两个字就分不清模型指的是哪句
PARA_TS_RE = re.compile(r"^\[(\d{1,2}:[0-5]\d:[0-5]\d)\]")
COUNTERS = ("quotes_snapped", "quotes_dropped", "quotes_out_of_range", "asr_dropped")


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


def read_doc(path: str | Path) -> dict:
    """读一份 `_digest/` 的 JSON 产物，**不吞异常**：产物坏了当场炸。

    吞掉的话，读不出来的片段会被当成「这个话题没有引文」放行，人在笔记上看到的
    是一节空话题，`gates.json` 还写着全 0（红线 9）。不是对象也算坏——照着它往下
    跑只会在别处炸出一句看不懂的 AttributeError。
    """
    obj = json.loads(Path(path).read_bytes().decode("utf-8"))
    if not isinstance(obj, dict):
        raise ValueError(f"{Path(path).name} 顶层不是对象")
    return obj


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


def align_span(nquote: str, nseg: str) -> tuple[int, int, int]:
    """引文整体对齐进段内某个跨度：(编辑距离, 起, 止)，下标落在 `nseg` 上。

    半全局编辑距离——插 / 删 / 换各记 1，跨度**两端不要钱**（引文本来就只是段里
    的一截）。同距离取最短跨度、再同取最靠前的跨度：模型末尾多抄一个字而逐字稿
    那处紧跟标点时，两种对法距离都是 1，取短的那个才不会把标点也算成他说的话。

    逐格 DP：候选段 `norm` 后几百字、引文几十字，一条引文几万格，够快。
    """
    m, n = len(nquote), len(nseg)
    # 行 0：从哪个位置起对齐都不要钱，所以距离全 0、起点就是当前位置
    dist, start = [0] * (n + 1), list(range(n + 1))
    for k in range(1, m + 1):
        # 第 k 行的第 0 列：引文的前 k 个字对空跨度，只能全删
        cur_d, cur_s = [k], [0]
        qc = nquote[k - 1]
        for j in range(1, n + 1):
            # 每格取 (距离, 起点靠后)最优的一条路：距离一样时起点越靠后跨度越短，
            # 而往后的代价跟起点无关，所以这么挑不会错过全局最优
            best = (dist[j] + 1, -start[j])                              # 删引文里这个字
            ins = (cur_d[j - 1] + 1, -cur_s[j - 1])                      # 插段里这个字
            sub = (dist[j - 1] + (qc != nseg[j - 1]), -start[j - 1])     # 换 / 对上
            if ins < best:
                best = ins
            if sub < best:
                best = sub
            cur_d.append(best[0])
            cur_s.append(-best[1])
        dist, start = cur_d, cur_s
    d, _, i, j = min((dist[j], j - start[j], start[j], j) for j in range(n + 1))
    return d, i, j


def snap_segment(nquote: str, ts: int | None, nsegs: list[tuple[str, dict]],
                 ) -> tuple[str, dict] | None:
    """近似命中（闸门 1 第二档）：(该跨度在**原文**里的那一截, 那一段)。对不上返回
    None——归一不产生失败态，对不上就交回去走「删」那一档。

    候选段只取与 `[ts - 2 分钟, ts + 2 分钟]` 有交集的那些：`ts` 读不出来就没有尺子
    定位，整集找「最像的一句」换错句比删更糟。
    """
    if ts is None or len(nquote) < SNAP_MIN_LEN:
        return None
    budget = max(1, len(nquote) * SNAP_EDITS_PER_10 // 10)
    best = None
    for nseg, seg in nsegs:
        if not nseg or not near(seg, ts):
            continue
        # 引文比整段还长出预算之外：对齐进段内任何一个跨度都至少要差这么多刀，
        # 不必逐格算。模型偶尔会把一整节抄成「引文」，没这一刀 DP 会按它的长度
        # 乘段长空转一遍（2 万字的「引文」能让一集卡好几秒）
        if len(nquote) - len(nseg) > budget:
            continue
        d, i, j = align_span(nquote, nseg)
        if d > budget or j <= i:
            continue
        # 先距离、再跨度长短，最后才是离 `ts` 的远近：同一句话在窗里出现两遍时，
        # `ctx` 要的是他说这一句的那一处（跟逐字命中那一档一个规矩）
        key = (d, j - i, abs(float(seg.get("start") or 0) - ts))
        if best is None or key < best[0]:
            best = (key, seg, i, j)
    if best is None:
        return None
    _, seg, i, j = best
    raw = str(seg.get("text") or "")
    _, idx = norm_map(raw)
    # 跨度两端都落在留下来的字上，中间原文有的空格 / 英文 / 时间戳原样带回来
    return raw[idx[i]:idx[j - 1] + 1], seg


def near(seg: dict, ts: int) -> bool:
    """这一段跟 `[ts - 2 分钟, ts + 2 分钟]` 有没有交集（归一档的候选段）。"""
    s0 = float(seg.get("start") or 0)
    s1 = float(seg.get("end") or 0)
    return s0 <= ts + PAD_S and max(s0, s1) >= ts - PAD_S


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

    片段是新对象：**只删条目、只补 `ctx`、只把近似命中的 `text` 换成逐字稿原文**，
    留下来的字符串值除这一处外一个字节都不动，换成的也是逐字稿里的连续一截。
    """
    entry = {"quotes_snapped": 0, "quotes_dropped": 0, "quotes_out_of_range": 0,
             "paras_out_of_range": [], "asr_dropped": 0, "snapped": [],
             "schema": check_shape(frag) or "ok"}
    out = dict(frag)
    t0, t1 = parse_hms(frag.get("start")), parse_hms(frag.get("end"))
    c0, c1 = parse_hms(chapter.get("start")), parse_hms(chapter.get("end"))

    if isinstance(frag.get("quotes"), list):
        kept = []
        for q in frag["quotes"]:
            # 形状不对的（不是对象、`text` 不是字符串）照删：它不可能是逐字稿里的
            # 一句话，而且 schema 那一栏已经把它报出来了
            if not isinstance(q, dict) or not isinstance(q.get("text"), str):
                entry["quotes_dropped"] += 1
                continue
            ts = parse_hms(q.get("ts"))
            nquote = norm(q["text"])
            snapped, seg = None, hit_segment(nquote, ts, nsegs)
            if seg is None:                       # 逐字对不上，才试归一那一档
                hit = snap_segment(nquote, ts, nsegs)
                if hit is None:
                    entry["quotes_dropped"] += 1
                    continue
                snapped, seg = hit
            # 话题的起止读不出来就不跑闸门 2：宁可不删（红线 2），schema 那一栏
            # 已经把这个片段报出来了
            if t0 is not None and t1 is not None and not in_topic(ts, t0, t1):
                # 归一完照样越界的只计越界：`quotes_snapped` 只数真正留下来的
                entry["quotes_out_of_range"] += 1
                continue
            if snapped is None:
                kept.append(dict(q, ctx=str(seg.get("text") or "")))
                continue
            entry["quotes_snapped"] += 1
            entry["snapped"].append({"ts": str(q.get("ts") or ""), "from": q["text"],
                                     "to": snapped})
            kept.append(dict(q, text=snapped, ctx=str(seg.get("text") or "")))
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
            heard = norm(a["heard"]) if isinstance(a, dict) \
                and isinstance(a.get("heard"), str) else ""
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
    chapters = {c["id"]: c for c in (read_doc(d / "chapters.json").get("chapters") or [])
                if isinstance(c, dict) and c.get("id")}
    heads = read_doc(d / "topics.json").get("topics") or []
    segments, _ = read_transcript(paths.transcript(ep))
    nsegs = [(norm(s.get("text")), s) for s in segments]
    lines = build_lines(segments)
    nslices: dict[str, list[str]] = {}

    report = GateReport(ep=ep, generated_at=generated_at or now_iso())
    pending: list[tuple[Path, dict]] = []
    for head in heads:
        tid = str((head or {}).get("id") or "").strip()
        if not tid:
            raise ValueError(f"{paths.rel(d / 'topics.json')} 里有话题没有 `id`")
        frag = read_doc(d / f"frag-{tid}.json")
        ch_id = frag.get("chapter")
        if ch_id not in chapters:
            # 孤儿片段（L1 重切过而 L2 没重跑）。这里判不了它该归哪一章，闸门 2
            # 与闸门 5 就没有尺子可用——不许当成「全都通过」放行
            raise ValueError(f"frag-{tid}.json 的 `chapter` = {ch_id!r} "
                             f"不在 {paths.rel(d / 'chapters.json')} 里")
        if ch_id not in nslices:
            ch = chapters[ch_id]
            c0, c1 = parse_hms(ch.get("start")), parse_hms(ch.get("end"))
            if c0 is None or c1 is None:
                # 章节表的时刻是 L1 的代码填的，读不出来就是产物坏了。**不许退成 0**
                # ——那会算出一段错的切片，然后照着它删掉本来该留的 ASR 条目，
                # 盘上还看不出是 chapters.json 的问题（片段那边有 `schema` 一栏可以
                # 记，章节表这边没有，所以只能抛）
                raise ValueError(f"{paths.rel(d / 'chapters.json')} 里章 {ch_id} 的 "
                                 f"start / end 读不出时刻（{ch.get('start')!r}、"
                                 f"{ch.get('end')!r}）")
            groups = slice_chapter(lines, c0, c1, PAD_S)
            nslices[ch_id] = [norm(ln["text"]) for g in groups for ln in g]

        out, entry = gate_frag(frag, chapters[ch_id], nsegs, nslices[ch_id])
        pending.append((d / f"frag-{tid}.json", out))
        report.topics[tid] = entry
        report.frags[tid] = out

    # **全集都过完了才落盘**：中途抛出去的那一趟，盘上不该留下「删了一半」的片段
    # ——`gates.json` 还没写出来，那些删除就再也没有记录了，下一趟看到的是已经被
    # 删过的片段、计数却是 0（红线 9：绝不静默丢单元）
    changed = 0
    for path, out in pending:
        if json_bytes(out) != path.read_bytes():
            write_json(path, out)
            changed += 1
    write_json(d / "gates.json", report.doc())
    log(f"    L3：{len(report.topics)} 个话题过了闸门，写回 {changed} 份片段"
        f"（越界的段只记不删，红线 2）")
    bad = [tid for tid, e in report.topics.items() if e.get("schema") != "ok"]
    if bad:
        # 本票不产生失败态（#54 才判），但不报的话人只能自己去翻 gates.json
        log(f"    ⚠ {len(bad)} 个话题的片段形状不合 §5.4（见 "
            f"{paths.rel(d / 'gates.json')} 的 `schema`）")
    return report
