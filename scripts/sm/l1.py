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
LINE_RE = re.compile(r"^\[(\d\d:\d\d:\d\d)\]", re.M)
KINDS = ("talk", "aside", "filler")
TOPIC_KEYS = ("id", "title", "kind", "start", "who", "gist")


def line_starts(input_text: str) -> list[str]:
    """输入里所有行首时间戳，按出现顺序。话题的 `start` 只能从这里面取。

    从**实际发出去的那份文本**里数，不另算一遍：另算会跟 render_lines 的分行
    规则悄悄走岔，把模型老实照抄来的时间戳判成非法。
    """
    return LINE_RE.findall(input_text)


def nearest_start(value, starts: list[str]) -> str | None:
    """离 `value` 最近的那个行首时间戳；`value` 连时刻都算不出来就返回 None。"""
    got = parse_hms(value) if isinstance(value, str) else None
    if got is None or not starts:
        return None
    return min(starts, key=lambda s: abs((parse_hms(s) or 0) - got))


def with_ends(topics: list[dict], dur: int) -> list[dict]:
    """给每个话题补 `end`：下一个话题的 `start`，最后一个收在时长。

    模型只写 `start`，`end` 由代码推——推出来的链天然首尾相接，零长度、倒置、
    空洞、重叠这几类错误在结构上就不可能发生，不必再靠闸门事后抓。
    """
    out = []
    for i, t in enumerate(topics):
        end = topics[i + 1].get("start") if i + 1 < len(topics) else hms(dur)
        out.append({**t, "end": end})
    return out


def head_block(ep: str, dur: int, names: list[str]) -> str:
    """三行头，一行一个键。

    挤成一行（`episode: EP02 · 时长 … · 说话人 …`）时「照抄 episode」有歧义，
    模型会把整行抄进 `ep`，整集打回重跑——EP02 上连挂两次。
    """
    return (f"episode: {ep}\n"
            f"时长: {hms(dur)}\n"
            f"说话人: {'、'.join(names) if names else '未点名'}")


def build_input(ep: str, segments: list[dict], speakers: dict) -> str:
    """三行头 + 整集 §5.2 文本。头之后一行 `---`，正文就是逐字稿，别的都没有。"""
    order: list[str] = []
    for s in segments:
        tag = s.get("speaker") or ""
        if tag and tag not in order:
            order.append(tag)
    names = [speakers.get(tag, tag) for tag in order]
    body = render_lines(segments, speakers)
    return head_block(ep, duration_s(segments), names) + "\n---\n" + body


def check_topics(obj, dur: int, starts: list[str]) -> list[str]:
    """§5.3 的字段与类型 + 起点照抄行首且递增。返回人话错误列表，空列表算过。

    时间这一侧只剩三条：起点在行首集合里、第一个是第一行、严格递增。三条都由
    「在换论点那一行把行首时间戳复制下来」一个动作同时满足——模型不用算数，
    所以算错不了。
    """
    errs: list[str] = []
    if not isinstance(obj, dict):
        return ["顶层不是对象"]
    topics = obj.get("topics")
    if not isinstance(topics, list) or not topics:
        errs.append("`topics` 不是非空数组")
        return errs

    allowed = set(starts)
    seen: set[str] = set()
    prev: int | None = None
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

        if "start" not in t:
            continue
        st = t.get("start")
        if not isinstance(st, str) or st not in allowed:
            # 把最近的那个行首一并报出去：差一秒、或者写成 MM:SS 的，看见正确
            # 答案就能一次改对，不必再赌下一趟
            near = nearest_start(st, starts)
            errs.append(f"{tag}: `start` = {st!r} 不是逐字稿里出现过的行首时间戳"
                        + (f"，最近的一个是 {near}" if near else "")
                        + "——只能把换论点那一行的 [HH:MM:SS] 照抄下来，不要自己算")
            continue
        if n == 1 and st != starts[0]:
            errs.append(f"第一个话题的 `start` 必须是第一行的 {starts[0]}，"
                        f"现在是 {st}——整集从头讲起，开头不能漏")
        cur = parse_hms(st)
        if prev is not None and cur <= prev:
            errs.append(f"{tag}: `start` = {st} 不晚于上一个话题的起点 {hms(prev)}"
                        f"——话题要按时间先后排，一个话题一个起点")
            continue
        prev = cur

    return errs


def run_l1(paths, runner, ep: str, segments: list[dict], speakers: dict, prompt: dict,
           *, model: str = "sonnet", effort: str = "low", timeout: int = 1800,
           retries: int = 1, generated_at: str | None = None,
           log=print) -> tuple[dict | None, list[str]]:
    """跑 L1 并落 `_digest/EP{n}/topics.json`（带 provenance）。失败返回 (None, 错误)。"""
    dur = duration_s(segments)
    text = build_input(ep, segments, speakers)
    starts = line_starts(text)
    obj, envelope, errors = call_layer(
        paths, runner, ep, LAYER, UNIT, prompt["path"], text,
        lambda o: check_topics(o, dur, starts),
        retries=retries, model=model, effort=effort, timeout=timeout, log=log,
        generated_at=generated_at)
    if obj is None:
        return None, errors

    # `ep` 与 `end` 由代码填：模型只写它真正看得出来的东西（起点与内容），
    # 凡是代码已经知道的一律不问——问了就是白白多一处会错的地方
    obj = {"ep": ep, "topics": with_ends(obj["topics"], dur)}
    obj["provenance"] = provenance(
        derived_from=[f"{ep}.transcript.json"], layer=LAYER, unit=UNIT,
        engine=engine_of(envelope, model), effort=effort,
        prompt_version=prompt["version"], generated_at=generated_at or now_iso())
    out = paths.digest(ep) / "topics.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes((json.dumps(obj, ensure_ascii=False, indent=1) + "\n").encode("utf-8"))
    return obj, []
