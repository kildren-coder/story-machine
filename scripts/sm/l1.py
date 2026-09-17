# -*- coding: utf-8 -*-
"""L1 骨架：整集 → 话题表（SPEC §4 L1、§5.3）。

一集一次调用，输入是整集的 §5.2 文本。代码这一侧只做机械检查：字段与类型、
`id` 形状、起点读得出且落在集内——**不改模型写的任何一个字**（红线 2 在
代码里的形态）。不过就重试，再不过进 `_failed/`。

**模型只写起点，终点由代码接**（`with_ends`）。从前要它写 `[起, 止]` 并铺满
整集：52 个话题 104 个时间戳、51 对必须两两相等，三集九次实测挂了三次，全是
空洞、越界、格式。现在链条由构造闭合，那几类错误不存在了。
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
TOPIC_KEYS = ("id", "title", "kind", "start", "who", "gist")


def read_start(value) -> int | None:
    """把模型写的起点读成秒。读不出来返回 None。

    宽容到底：`HH:MM:SS` 照读，`MM:SS` 按分秒读，`H:MM:SS` 也认。逐字稿的行首
    时间戳每 30 秒才有一个（ASR 段长中位 29.9 秒），模型想切的位置往往在两行
    之间——**逼它照抄行首只会逼出编造的时间戳**：EP03 上两轮都写了输入里根本
    不存在的 00:18:13，因为它要切的地方在 00:18:02 那一行的中间。

    起点差几秒无所谓：`end` 由下一个起点推出，链条照样严丝合缝，差的只是边界
    落在哪句话上——而边界本来就只有 30 秒精度。
    """
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return int(value) if value >= 0 else None
    if not isinstance(value, str):
        return None
    got = parse_hms(value.strip())
    if got is not None:
        return got
    m = re.fullmatch(r"(\d{1,3}):([0-5]\d)", value.strip())
    return int(m.group(1)) * 60 + int(m.group(2)) if m else None


def with_ends(topics: list[dict], dur: int) -> list[dict]:
    """按起点排好、归一起点、接上终点。检查过了才调。

    先按起点**稳定**排序：模型偶尔把回头再谈的话题按主题挪到前一次旁边（EP01
    上 20 轮出现 1 次，4 个话题错位），时间戳本身全对——628 个起点里 608 个正好
    是行首、其余都落在相邻两行之间，没有一个离谱的手误。顺序是代码能归一的，
    打回只会白烧一趟。起点相同的保持模型给的先后。

    `end` 取下一个话题的 `start`，最后一个收在时长——推出来的链天然首尾相接，
    倒置、空洞、重叠在结构上不可能发生，不必再靠闸门事后抓。两个话题起点相同
    时前一个长度为 0：它确实只占那一行的一部分，切片由下一层的 pad 兜住。

    起点统一写成 `HH:MM:SS`（模型可能写成 `MM:SS`）；第一个一律归零——整集从头
    算起，开头那几十秒并进第一个话题就是了，不为一个边界把整集打回重跑。
    """
    ordered = sorted(topics, key=lambda t: read_start(t.get("start")) or 0)
    secs = [read_start(t.get("start")) or 0 for t in ordered]
    secs[0] = 0
    out = []
    for i, t in enumerate(ordered):
        end = secs[i + 1] if i + 1 < len(ordered) else dur
        out.append({**t, "start": hms(secs[i]), "end": hms(end)})
    return out


def out_of_order(topics: list[dict]) -> int:
    """模型给的顺序里，有几个话题的位置和按起点排完不一样。只用来报日志。"""
    ids = [t.get("id") for t in topics]
    ordered = [t.get("id") for t in sorted(topics, key=lambda t: read_start(t.get("start")) or 0)]
    return sum(1 for a, b in zip(ids, ordered) if a != b)


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


def tidy(obj):
    """机械归一，不碰内容：`id` 转小写、下划线与空格换成短横线。

    `id` 是机器键，不是人读的字（红线 2 管的是标题、gist、原话）。haiku 写过
    `eric-Adams-mandela`，一个大写字母就让整集重发一趟，不值。归一完还不合规
    的照样由 check_topics 拦。检查前与落盘前都过一遍，两头看到的是同一份。
    """
    if not isinstance(obj, dict) or not isinstance(obj.get("topics"), list):
        return obj
    out = []
    for t in obj["topics"]:
        if isinstance(t, dict) and isinstance(t.get("id"), str):
            tid = re.sub(r"[\s_]+", "-", t["id"].strip().lower())
            t = {**t, "id": tid}
        out.append(t)
    return {**obj, "topics": out}


def check_topics(obj, dur: int) -> list[str]:
    """§5.3 的字段与类型 + 起点能读出来、落在集内。空列表算过。

    时间这一侧只剩两条真检查：起点读得出、不超过时长。空洞、重叠、倒置、
    越界都由构造排除（`end` 由下一个起点推出），格式松紧由 `read_start` 兜住，
    顺序由 `with_ends` 排好，第一个起点归零，起点相同算过——都不必打回重跑。
    """
    errs: list[str] = []
    if not isinstance(obj, dict):
        return ["顶层不是对象"]
    topics = obj.get("topics")
    if not isinstance(topics, list) or not topics:
        errs.append("`topics` 不是非空数组")
        return errs

    seen: set[str] = set()
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
        cur = read_start(st)
        if cur is None:
            errs.append(f"{tag}: `start` = {st!r} 读不出时刻，要写成 HH:MM:SS")
            continue
        if cur > dur:
            errs.append(f"{tag}: `start` = {st} 超过整集时长 {hms(dur)}"
                        f"——时间戳只能来自这一集")
        # 顺序不查：相同的算过（两件事挤在同一行里，行首每 30 秒才一个，它没有
        # 别的时刻可写——起点制以来 8 轮里出现 3 次），乱了的由 with_ends 排好

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
        lambda o: check_topics(tidy(o), dur),
        retries=retries, model=model, effort=effort, timeout=timeout, log=log,
        generated_at=generated_at)
    if obj is None:
        return None, errors
    obj = tidy(obj)

    # `ep` 与 `end` 由代码填：模型只写它真正看得出来的东西（起点与内容），
    # 凡是代码已经知道的一律不问——问了就是白白多一处会错的地方
    moved = out_of_order(obj["topics"])
    if moved:
        log(f"    L1：{moved} 个话题按起点重排了（模型按主题挪过位置，时间戳没动）")
    obj = {"ep": ep, "topics": with_ends(obj["topics"], dur)}
    obj["provenance"] = provenance(
        derived_from=[f"{ep}.transcript.json"], layer=LAYER, unit=UNIT,
        engine=engine_of(envelope, model), effort=effort,
        prompt_version=prompt["version"], generated_at=generated_at or now_iso())
    out = paths.digest(ep) / "topics.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes((json.dumps(obj, ensure_ascii=False, indent=1) + "\n").encode("utf-8"))
    return obj, []
