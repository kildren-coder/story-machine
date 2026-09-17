# -*- coding: utf-8 -*-
"""L1 骨架：整集 → 话题表（SPEC §4 L1、§5.3）。

一集一次调用，输入是整集的 §5.2 文本。代码这一侧只做机械检查：字段与类型、
`id` 形状、时间范围顺序与边界、覆盖整集不留空洞——**不改模型写的任何一个字**
（红线 2 在代码里的形态）。不过就重试，再不过进 `_failed/`。
"""
from __future__ import annotations

import json
import re

from .pairs import call_layer
from .prov import engine_of, now_iso, provenance
from .text import hms, parse_hms
from .transcript import duration_s, render_lines

LAYER = "L1"
UNIT = "all"
ID_RE = re.compile(r"^[a-z0-9-]+$")
KINDS = ("talk", "aside", "filler")
SEAM_S = 5            # 覆盖检查容忍的缝：模型按行首时间戳取整，差几秒是常态
TOPIC_KEYS = ("id", "title", "kind", "ranges", "who", "gist")


def head_line(ep: str, dur: int, names: list[str]) -> str:
    return (f"episode: {ep} · 时长 {hms(dur)} · "
            f"说话人 {'、'.join(names) if names else '未点名'}")


def build_input(ep: str, segments: list[dict], speakers: dict) -> str:
    """一行头 + 整集 §5.2 文本。头之后一行 `---`，正文就是逐字稿，别的都没有。"""
    order: list[str] = []
    for s in segments:
        tag = s.get("speaker") or ""
        if tag and tag not in order:
            order.append(tag)
    names = [speakers.get(tag, tag) for tag in order]
    body = render_lines(segments, speakers)
    return head_line(ep, duration_s(segments), names) + "\n---\n" + body


def check_topics(obj, dur: int, ep: str | None = None) -> list[str]:
    """§5.3 的字段与类型 + 覆盖整集。返回人话错误列表，空列表算过。"""
    errs: list[str] = []
    if not isinstance(obj, dict):
        return ["顶层不是对象"]
    got_ep = obj.get("ep")
    if not isinstance(got_ep, str) or not got_ep.strip():
        errs.append("顶层 `ep` 缺失或不是字符串")
    elif ep and got_ep.strip() != ep:
        errs.append(f"顶层 `ep` = {got_ep!r}，应该是 {ep!r}")
    topics = obj.get("topics")
    if not isinstance(topics, list) or not topics:
        errs.append("`topics` 不是非空数组")
        return errs

    seen: set[str] = set()
    spans: list[tuple[int, int, str]] = []
    for n, t in enumerate(topics, 1):
        tag = (t or {}).get("id") if isinstance(t, dict) else None
        tag = tag if isinstance(tag, str) and tag else f"第{n}个话题"
        if not isinstance(t, dict):
            errs.append(f"{tag}: 不是对象")
            continue
        for k in TOPIC_KEYS:
            if k not in t:
                errs.append(f"{tag}: 缺字段 `{k}`")
        tid = t.get("id")
        if isinstance(tid, str) and tid:
            if not ID_RE.match(tid):
                errs.append(f"{tag}: `id` = {tid!r} 不匹配 ^[a-z0-9-]+$")
            if tid in seen:
                errs.append(f"{tag}: `id` 重复")
            seen.add(tid)
        elif "id" in t:
            errs.append(f"{tag}: `id` 不是非空字符串")
        if "kind" in t and t.get("kind") not in KINDS:
            errs.append(f"{tag}: `kind` = {t.get('kind')!r} 不在 {KINDS}")
        for k in ("title", "gist"):
            v = t.get(k)
            if k not in t:
                continue
            if not (isinstance(v, str) and v.strip()):
                errs.append(f"{tag}: `{k}` 不是非空字符串")
            # 这两个字段原样落进 EP 笔记的标记块（渲染不许改字，红线 2），所以
            # 换行和 HTML 注释只能在这里拦：它们会把块结构撑破
            elif "\n" in v or "\r" in v or "<!--" in v:
                errs.append(f"{tag}: `{k}` 里有换行或 HTML 注释，渲染进笔记会撑破标记块")
        who = t.get("who")
        if "who" in t and (not isinstance(who, list)
                           or not all(isinstance(w, str) and w.strip() for w in who)):
            errs.append(f"{tag}: `who` 不是字符串数组")

        ranges = t.get("ranges")
        if "ranges" not in t:
            continue
        if not isinstance(ranges, list) or not ranges:
            errs.append(f"{tag}: `ranges` 不是非空数组")
            continue
        for r in ranges:
            if not (isinstance(r, list) and len(r) == 2):
                errs.append(f"{tag}: `ranges` 的元素不是 [起, 止]：{r!r}")
                continue
            a, b = parse_hms(r[0]), parse_hms(r[1])
            if a is None or b is None:
                errs.append(f"{tag}: 时间戳不是 HH:MM:SS：{r!r}")
                continue
            if a >= b:
                errs.append(f"{tag}: 范围起点不早于终点：{r[0]}–{r[1]}")
                continue
            if b > dur:
                errs.append(f"{tag}: 范围终点 {r[1]} 超过时长 {hms(dur)}")
                continue
            spans.append((a, b, tid if isinstance(tid, str) else tag))

    errs += check_coverage(spans, dur)
    return errs


def check_coverage(spans: list[tuple[int, int, str]], dur: int) -> list[str]:
    """排序后从 00:00:00 到时长必须无空洞无重叠（允许 ≤ SEAM_S 秒的缝）。

    空洞的报法带上两头的时间戳：人看到「00:19:00–00:22:00」就知道去听哪一段，
    而「覆盖不全」只能让人重读整集。
    """
    errs: list[str] = []
    if not spans:
        return ["没有一个合法的时间范围，覆盖无从检查"]
    spans = sorted(spans)
    if spans[0][0] > SEAM_S:
        errs.append(f"覆盖从 {hms(spans[0][0])} 才开始，00:00:00 起有空洞")
    for (a0, b0, id0), (a1, b1, id1) in zip(spans, spans[1:]):
        seam = a1 - b0
        if seam > SEAM_S:
            errs.append(f"覆盖有空洞：{hms(b0)}–{hms(a1)}（{seam / 60:.1f} 分钟，"
                        f"在 {id0} 与 {id1} 之间）")
        elif seam < -SEAM_S:
            errs.append(f"覆盖有重叠：{hms(a1)}–{hms(b0)}（{-seam / 60:.1f} 分钟，"
                        f"{id0} 与 {id1}）")
    tail = dur - max(b for _, b, _ in spans)
    if tail > SEAM_S:
        errs.append(f"覆盖到 {hms(dur - tail)} 就断了，到时长 {hms(dur)} 还有空洞")
    return errs


def run_l1(paths, runner, ep: str, segments: list[dict], speakers: dict, prompt: dict,
           *, model: str = "sonnet", effort: str = "low", timeout: int = 1800,
           retries: int = 1, generated_at: str | None = None,
           log=print) -> tuple[dict | None, list[str]]:
    """跑 L1 并落 `_digest/EP{n}/topics.json`（带 provenance）。失败返回 (None, 错误)。"""
    dur = duration_s(segments)
    text = build_input(ep, segments, speakers)
    obj, envelope, errors = call_layer(
        paths, runner, ep, LAYER, UNIT, prompt["path"], text,
        lambda o: check_topics(o, dur, ep),
        retries=retries, model=model, effort=effort, timeout=timeout, log=log,
        generated_at=generated_at)
    if obj is None:
        return None, errors

    obj["provenance"] = provenance(
        derived_from=[f"{ep}.transcript.json"], layer=LAYER, unit=UNIT,
        engine=engine_of(envelope, model), effort=effort,
        prompt_version=prompt["version"], generated_at=generated_at or now_iso())
    out = paths.digest(ep) / "topics.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes((json.dumps(obj, ensure_ascii=False, indent=1) + "\n").encode("utf-8"))
    return obj, []
