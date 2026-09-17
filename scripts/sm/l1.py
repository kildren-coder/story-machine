# -*- coding: utf-8 -*-
"""L1 骨架：整集 → 章节表（SPEC §4 L1、§5.3）。

一集一次调用，输入是整集的 §5.2 文本。L1 只把整集切成十几分钟一章的**容器**，
章内有几个话题、哪些值得深加工，是 L2 拿着十几分钟的上下文去判断的事——整集
三小时一口气切到话题粒度，同一集跑几遍话题数能差一倍多（EP02：29–75），而
L2 的调用次数跟着它摆。章数由时长决定，摆不起来。

**模型只写它真看得出来的东西**：每章从第几行开始、叫什么、讲了什么。行号是
输入里现成的闭集，它不必写时刻，也就没有格式、编造、越界这几类错；时刻由代码
拿行号查行表换回来（`with_ends`）。终点、集号、说话人都由代码填。

代码这一侧只拦修不了的：行号不在表里、标题或 gist 是空的。`id` 不合规、行号
写成了字符串、顺序乱了、首章没从第 1 行起、章切得太短或两章写了同一行，全部
归一，不打回（SPEC §4.1）。
"""
from __future__ import annotations

import json
import re

from .note import bare_name
from .pairs import call_layer
from .prov import engine_of, now_iso, provenance
from .text import hms
from .transcript import build_lines, duration_s, format_lines, line_t, pick_lines

LAYER = "L1"
UNIT = "all"
ID_RE = re.compile(r"^[a-z0-9-]+$")
CHAPTER_KEYS = ("id", "title", "line", "gist")
CHAPTER_S = 900              # 一章 15 分钟上下：L2 一次调用吃得下、写得细的量
MIN_CHAPTER_S = 480          # 不到 8 分钟的章并进相邻的章（prompt 里是同一个数）


def chapter_budget(dur: int) -> int:
    """按时长估的章数，写进输入头给模型当参考（不是闸门）。"""
    return max(1, round(dur / CHAPTER_S))


def schema_for(n_lines: int) -> dict:
    """交给 `--json-schema` 的形状。行号上限跟着这一集走：写出表外的行号，CLI
    在会话里就让它重来了，不用我们把整集重发一趟。

    `id` 的样子不在这里卡——大小写、下划线之类代码能归一，卡了只会白白多一轮。
    """
    return {
        "type": "object",
        "properties": {"chapters": {
            "type": "array", "minItems": 1,
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "title": {"type": "string", "minLength": 1},
                    "line": {"type": "integer", "minimum": 1, "maximum": max(1, n_lines)},
                    "gist": {"type": "string", "minLength": 1},
                },
                "required": list(CHAPTER_KEYS),
                "additionalProperties": False,
            }}},
        "required": ["chapters"],
        "additionalProperties": False,
    }


def head_block(ep: str, dur: int, names: list[str], n_lines: int) -> str:
    """头，一行一个键。

    挤成一行（`episode: EP02 · 时长 … · 说话人 …`）时「照抄 episode」有歧义，
    模型会把整行抄进 `ep`，整集打回重跑——EP02 上连挂两次。
    """
    return (f"episode: {ep}\n"
            f"时长: {hms(dur)}\n"
            f"行数: {n_lines}\n"
            f"参考章数: {chapter_budget(dur)}\n"
            f"说话人: {'、'.join(names) if names else '未点名'}")


def build_input(ep: str, segments: list[dict], speakers: dict) -> str:
    """头 + 整集 §5.2 文本。头之后一行 `---`，正文就是逐字稿，别的都没有。"""
    order: list[str] = []
    for s in segments:
        tag = s.get("speaker") or ""
        if tag and tag not in order:
            order.append(tag)
    names = [speakers.get(tag, tag) for tag in order]
    lines = build_lines(segments)
    return (head_block(ep, duration_s(segments), names, len(lines))
            + "\n---\n" + format_lines(lines, speakers))


def tidy(obj):
    """机械归一，不碰内容。检查前与落盘前都过一遍，两头看到的是同一份。

    - `id` 是机器键，不是人读的字（红线 2 管的是标题、gist、原话）：转小写，
      `a-z0-9` 以外的连成一个短横线；归一完是空的（写了中文、漏写）就按位置补
      `chNN`；重复的加 `-2`、`-3`。haiku 写过 `eric-Adams-mandela`，一个大写字母
      不值得让整集重发一趟。
    - `line` 写成 `"57"` 或 `57.0` 的读成 57。
    - `title` / `gist` 里的换行换成一个空格（它们原样进笔记的标记块，换行会把块
      撑破；换掉的只是空白）。
    """
    if not isinstance(obj, dict) or not isinstance(obj.get("chapters"), list):
        return obj
    seen: set[str] = set()
    out = []
    for n, c in enumerate(obj["chapters"], 1):
        if not isinstance(c, dict):
            out.append(c)
            continue
        c = dict(c)
        raw = c.get("id") if isinstance(c.get("id"), str) else ""
        base = re.sub(r"[^a-z0-9]+", "-", raw.strip().lower()).strip("-") or f"ch{n:02d}"
        cid, k = base, 2
        while cid in seen:
            cid, k = f"{base}-{k}", k + 1
        seen.add(cid)
        c["id"] = cid
        ln = c.get("line")
        if isinstance(ln, str) and ln.strip().isdigit():
            c["line"] = int(ln.strip())
        elif isinstance(ln, float) and ln.is_integer():
            c["line"] = int(ln)
        for key in ("title", "gist"):
            if isinstance(c.get(key), str):
                c[key] = re.sub(r"\s*[\r\n]+\s*", " ", c[key]).strip()
        out.append(c)
    return {**obj, "chapters": out}


def check_chapters(obj, n_lines: int) -> list[str]:
    """§5.3 模型那一半的字段与类型 + 行号在表里。空列表算过。

    给了 schema 时这些 CLI 已经把过一遍；这里留着，是因为重放旧存档、假 runner、
    CLI 没给 `structured_output` 时产物是从文字里挖出来的，没人替它把关。
    顺序不查（`with_ends` 会排），首章行号不查（一律从 0 秒起），两章同一行、
    章太短也算过（`merge_short` 会并）。
    """
    if not isinstance(obj, dict):
        return ["顶层不是对象"]
    chapters = obj.get("chapters")
    if not isinstance(chapters, list) or not chapters:
        return ["`chapters` 不是非空数组"]

    errs: list[str] = []
    for n, c in enumerate(chapters, 1):
        tag = c.get("id") if isinstance(c, dict) and isinstance(c.get("id"), str) and c.get("id") \
            else f"第{n}章"
        if not isinstance(c, dict):
            errs.append(f"{tag}: 不是对象")
            continue
        for k in CHAPTER_KEYS:
            if k not in c:
                errs.append(f"{tag}: 缺字段 `{k}`")
        if "id" in c and not (isinstance(c["id"], str) and ID_RE.match(c["id"])):
            errs.append(f"{tag}: `id` = {c['id']!r} 不匹配 ^[a-z0-9-]+$")
        for k in ("title", "gist"):
            if k not in c:
                continue
            v = c[k]
            if not (isinstance(v, str) and v.strip()):
                errs.append(f"{tag}: `{k}` 不是非空字符串")
            # 这两个字段原样落进 EP 笔记的标记块（渲染不许改字，红线 2）
            elif "\n" in v or "\r" in v or "<!--" in v:
                errs.append(f"{tag}: `{k}` 里有换行或 HTML 注释，渲染进笔记会撑破标记块")
        if "line" in c:
            ln = c["line"]
            if isinstance(ln, bool) or not isinstance(ln, int):
                errs.append(f"{tag}: `line` = {ln!r} 不是行号，要写这一章开头那一行行首的整数")
            elif not 1 <= ln <= n_lines:
                errs.append(f"{tag}: `line` = {ln} 不在这一集的行号里（1–{n_lines}）"
                            f"——行号只能取自输入每行行首的那个数")
    return errs


def out_of_order(chapters: list[dict]) -> int:
    """模型给的顺序里，有几章的位置和按行号排完不一样。只用来报日志。"""
    ids = [c.get("id") for c in chapters]
    ordered = [c.get("id") for c in sorted(chapters, key=lambda c: c.get("line") or 0)]
    return sum(1 for a, b in zip(ids, ordered) if a != b)


def merge_short(items: list[dict], dur: int, first_t: int) -> list[dict]:
    """不到 `MIN_CHAPTER_S` 的章并进相邻的章，直到没有为止。`items` 已按 `t` 排好。

    prompt 写了「不到 8 分钟的不单独成章」，模型照样切：EP01 三轮里一轮切出 14 章、
    其中 8 章不到 8 分钟（最短 2 分钟）。章是容器，并起来一个字都不丢——标题用
    顿号接、`gist` 按先后接，模型写的字原样；而 L2 每章一次调用，每次都要带前后
    各 2 分钟的上下文，3 分钟的章一多半额度花在重读上。

    每次挑最短的那一章，并进它两边较短的那个邻居（长度为 0 的并进后一章——它
    的内容就在后一章开头那一行里）。`id` 留吸收方的。第一章的长度从逐字稿第一
    行算起，不从 0 秒算（真库 EP01 第一行是 00:07:47，前面是静音）。
    """
    items = [dict(i) for i in items]
    while len(items) > 1:
        ends = [b["t"] for b in items[1:]] + [dur]
        spans = [e - (max(i["t"], first_t) if k == 0 else i["t"])
                 for k, (i, e) in enumerate(zip(items, ends))]
        k = min(range(len(items)), key=lambda n: (spans[n], n))
        if spans[k] >= MIN_CHAPTER_S:
            break
        if k == 0:
            j = 1
        elif k == len(items) - 1:
            j = k - 1
        elif spans[k] <= 0:
            j = k + 1
        else:
            j = k - 1 if spans[k - 1] <= spans[k + 1] else k + 1
        a, b = min(k, j), max(k, j)
        items[a:b + 1] = [{"id": items[j]["id"],
                           "title": items[a]["title"] + "、" + items[b]["title"],
                           "gist": items[a]["gist"] + " " + items[b]["gist"],
                           "t": items[a]["t"]}]
    return items


def with_ends(chapters: list[dict], lines: list[dict], dur: int, speakers: dict) -> list[dict]:
    """按行号排好，行号换成时刻，并掉太短的章，接上终点，填说话人。检查过了才调。

    - 先按行号**稳定**排序：模型偶尔把回头再谈的内容按主题挪到前一次旁边，位置
      本身没错。顺序是代码能归一的，打回只会白烧一趟。
    - `start` = 那一行行首的时刻；第一章一律从 `00:00:00` 起（逐字稿第一行未必
      从 0 秒开始，开头那一截并进第一章）。`end` 取下一章的 `start`，最后一章
      收在时长——链由构造闭合，空洞、重叠、倒置、越界都不可能出现。
    - 太短的章由 `merge_short` 并掉；两章写了同一行（前一章长度为 0）也在这一步
      并掉，所以产物里没有长度为 0 的章。
    - `who` = 这一章自己的行里出现过的说话人，按出场先后。行表里本来就有，不
      必让模型再写一遍。
    """
    ordered = sorted(chapters, key=lambda c: c["line"])
    items = [{"id": c["id"], "title": c["title"], "gist": c["gist"],
              "t": line_t(lines, c["line"]) or 0} for c in ordered]
    items[0]["t"] = 0
    items = merge_short(items, dur, lines[0]["t"] if lines else 0)
    out = []
    for i, c in enumerate(items):
        end = items[i + 1]["t"] if i + 1 < len(items) else dur
        who: list[str] = []
        for ln in pick_lines(lines, c["t"], end):
            name = bare_name(speakers.get(ln["tag"], ln["tag"]))
            if name and name not in who:
                who.append(name)
        out.append({"id": c["id"], "title": c["title"],
                    "start": hms(c["t"]), "end": hms(end),
                    "who": who, "gist": c["gist"]})
    return out


def run_l1(paths, runner, ep: str, segments: list[dict], speakers: dict, prompt: dict,
           *, model: str = "sonnet", effort: str = "low", timeout: int = 1800,
           retries: int = 1, generated_at: str | None = None,
           log=print) -> tuple[dict | None, list[str]]:
    """跑 L1 并落 `_digest/EP{n}/chapters.json`（带 provenance）。失败返回 (None, 错误)。"""
    dur = duration_s(segments)
    lines = build_lines(segments)
    text = build_input(ep, segments, speakers)
    obj, envelope, errors = call_layer(
        paths, runner, ep, LAYER, UNIT, prompt["path"], text,
        lambda o: check_chapters(tidy(o), len(lines)),
        retries=retries, model=model, effort=effort, timeout=timeout, log=log,
        generated_at=generated_at, schema=schema_for(len(lines)))
    if obj is None:
        return None, errors
    obj = tidy(obj)

    moved = out_of_order(obj["chapters"])
    if moved:
        log(f"    L1：{moved} 章按行号重排了（模型按主题挪过位置，行号没动）")
    wrote = len(obj["chapters"])
    obj = {"ep": ep, "chapters": with_ends(obj["chapters"], lines, dur, speakers)}
    if len(obj["chapters"]) < wrote:
        log(f"    L1：模型切了 {wrote} 章，其中 {wrote - len(obj['chapters'])} 章不到 "
            f"{MIN_CHAPTER_S // 60} 分钟，并进了相邻的章（标题与 gist 顺序接上，字没动）")
    obj["provenance"] = provenance(
        derived_from=[f"{ep}.transcript.json"], layer=LAYER, unit=UNIT,
        engine=engine_of(envelope, model), effort=effort,
        prompt_version=prompt["version"], generated_at=generated_at or now_iso())
    out = paths.digest(ep) / "chapters.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes((json.dumps(obj, ensure_ascii=False, indent=1) + "\n").encode("utf-8"))
    return obj, []
