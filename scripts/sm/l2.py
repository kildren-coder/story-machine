# -*- coding: utf-8 -*-
"""L2 逐章节整理：章节切片 → 片段 + 话题表（SPEC §4 L2、§5.3、§5.4）。

一章一次调用。L1 只切出十几分钟一章的**容器**；在章内切话题、分 `kind`、写五类
内容，是这一层的事——上下文只有十几分钟，判断稳得多（ADR 0005）。

**模型只写它真看得出来的东西**：话题从第几行开始、叫什么、是正题还是过场、讲了
什么。话题 `id`、时刻、终点、说话人全由代码填；模型写的 `line` 不进产物。代码
这一侧只拦修不了的（行号不在本章、标题空、段没有时间戳、多出来的尖括号标记），
其余一律归一不打回（SPEC §4.1）。

**并发与写盘**：一集十几章，并发 3 跑（§7）。线程里只做「拼输入 → 调 runner →
检查」，`_pairs/` 与 `_failed/` 是每单元一份、互不相干；**共享的 `_digest/`（片段
与话题表）只在主线程写**——每完成一章，先清这一章的旧片段，再写新片段，再重写
`topics.json`。中途被杀最多丢一章，重跑时它自己会补上。
"""
from __future__ import annotations

import json
import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from .note import bare_name
from .pairs import call_layer
from .prov import engine_of, now_iso, provenance
from .text import hms, parse_hms
from .transcript import build_lines, format_lines, line_t, pick_lines, slice_chapter

LAYER = "L2"
KINDS = ("talk", "aside", "filler")
# 模型写的九个键（`id` / `start` / `end` / `who` 由代码填，不让模型写）
TOPIC_KEYS = ("title", "kind", "line", "gist", "paras", "quotes", "claims", "channels", "asr")
BODY_KEYS = ("paras", "quotes", "claims", "channels", "asr")
ITEM_KEYS = {
    "quotes": ("ts", "who", "text"),
    "claims": ("ts", "who", "claim", "quote"),
    "channels": ("ts", "who", "name", "kind", "quote"),
    "asr": ("heard", "means"),
}
FRAG_KEYS = ("id", "chapter", "title", "kind", "start", "end", "who", "gist") + BODY_KEYS
HEAD_KEYS = ("id", "chapter", "title", "kind", "start", "end", "who", "gist")
MAX_QUOTES = 6           # 每话题的原话锚点上限（prompt 里是同一个数）
PAD_S = 120              # 切片前后各带 2 分钟，只供理解（§5.2）
PARA_HEAD_RE = re.compile(r"^\[\d{1,2}:[0-5]\d:[0-5]\d\]")
TAG_RE = re.compile(r"<[^<>]*>")
OK_TAGS = ("<who>", "</who>", "<hedge>", "</hedge>")


# ---------------------------------------------------------------- 输入

def head_block(ep: str, chapter: dict, first_line: int, last_line: int,
               names: list[str]) -> str:
    """头，一行一个键。挤成一行会让「照抄 episode」有歧义（L1 上的教训）。"""
    return "\n".join([
        f"episode: {ep}",
        f"章节: {chapter.get('id', '')}",
        f"标题: {chapter.get('title', '')}",
        f"范围: {chapter.get('start', '')}–{chapter.get('end', '')}",
        f"行号: {first_line}–{last_line}",
        f"说话人: {'、'.join(names) if names else '未点名'}",
    ])


def chapter_map(chapters: list[dict], cur_id: str) -> str:
    """全集章节地图，一章一行；本章那一行行首标 `→`。

    L2 每章各跑各的（不让后一章读前一章的输出，否则只能串行），所以「前一章讲到
    哪、后一章要接什么」只能靠 L1 写的 `gist` 当地图。
    """
    rows = []
    for i, c in enumerate(chapters, 1):
        mark = "→" if c.get("id") == cur_id else " "
        rows.append(f"{mark} {i}. {c.get('start', '')}–{c.get('end', '')} "
                    f"{c.get('title', '')} —— {c.get('gist', '')}")
    return "\n".join(rows)


def build_input(ep: str, chapter: dict, chapters: list[dict], lines: list[dict],
                speakers: dict) -> str:
    """头 + 章节地图 + 切片三段。空的那一段连分隔行一起省掉。"""
    before, body, after = _slice(chapter, lines)
    first = body[0]["n"] if body else 0
    last = body[-1]["n"] if body else 0
    out = [head_block(ep, chapter, first, last, _names(body, speakers)),
           "---",
           chapter_map(chapters, chapter.get("id")),
           "---"]
    for title, group in (("上文（只供理解，不写）", before),
                         ("本章", body),
                         ("下文（只供理解，不写）", after)):
        if not group:
            continue
        out.append(f"=== {title} ===")
        out.append(format_lines(group, speakers).rstrip("\n"))
    return "\n".join(out) + "\n"


def _slice(chapter: dict, lines: list[dict]):
    return slice_chapter(lines, parse_hms(chapter.get("start")) or 0,
                         parse_hms(chapter.get("end")) or 0, PAD_S)


def _names(group: list[dict], speakers: dict) -> list[str]:
    """本章出现过的说话人，按出场先后，带角色（头里报一次）。"""
    out: list[str] = []
    for ln in group:
        name = speakers.get(ln["tag"], ln["tag"])
        if name and name not in out:
            out.append(name)
    return out


# ---------------------------------------------------------------- 形状

def schema_for(first_line: int, last_line: int) -> dict:
    """交给 `--json-schema` 的形状（§5.4）。行号上下界跟着本章走：写出本章之外的
    行号，CLI 在会话里就让它重来了，不用我们把整章重发一趟。

    `id` 不在这里——那是代码按 `<章节 id>-NN` 编的，模型不写。`ts` 不卡格式：
    `MM:SS` 这类代码补得回来（`tidy`），卡了只会白白多一轮。
    """
    def items(keys: tuple, **extra) -> dict:
        return {"type": "array",
                "items": {"type": "object",
                          "properties": {k: {"type": "string"} for k in keys},
                          "required": list(keys),
                          "additionalProperties": False},
                **extra}

    return {
        "type": "object",
        "properties": {"topics": {
            "type": "array", "minItems": 1,
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "minLength": 1},
                    "kind": {"type": "string", "enum": list(KINDS)},
                    "line": {"type": "integer",
                             "minimum": max(1, first_line), "maximum": max(1, last_line)},
                    "gist": {"type": "string", "minLength": 1},
                    "paras": {"type": "array", "items": {"type": "string"}},
                    "quotes": items(ITEM_KEYS["quotes"], maxItems=MAX_QUOTES),
                    "claims": items(ITEM_KEYS["claims"]),
                    "channels": items(ITEM_KEYS["channels"]),
                    "asr": items(ITEM_KEYS["asr"]),
                },
                "required": list(TOPIC_KEYS),
                "additionalProperties": False,
            }}},
        "required": ["topics"],
        "additionalProperties": False,
    }


def _fix_ts(v):
    """`5:43` / `1:05:43` → `00:05:43` / `01:05:43`。读不出来的原样留着（交给检查）。"""
    if not isinstance(v, str):
        return v
    parts = v.strip().split(":")
    if 2 <= len(parts) <= 3 and all(p.isdigit() for p in parts):
        nums = [int(p) for p in parts]
        if len(nums) == 2:
            nums = [0] + nums
        return "{:02d}:{:02d}:{:02d}".format(*nums)
    return v


def _line_key(t) -> int:
    ln = t.get("line") if isinstance(t, dict) else None
    return ln if isinstance(ln, int) and not isinstance(ln, bool) else 0


def tidy(obj):
    """机械归一，不碰内容。检查前与落盘前各过一遍，两头看到的是同一份。

    - `line` 写成 `"36"` 或 `36.0` 的读成 36。
    - `title` / `gist` 里的换行换成一个空格（它们原样进笔记的标记块，换行会把块
      撑破；换掉的只是空白）。
    - `ts` 写成 `MM:SS` 或 `H:MM:SS` 的补成 `HH:MM:SS`。
    - `quotes` 超过 6 条的留前 6 条；`asr` 里 `heard` 等于 `means` 的条目删掉
      （那种条目下游没法用，删它不碰任何字）。
    - 话题按 `line` 稳定排序：模型偶尔把回头再谈的内容按主题挪到一起，位置本身
      没错，排序是代码能做的事，打回只会白烧一趟。
    """
    if not isinstance(obj, dict) or not isinstance(obj.get("topics"), list):
        return obj
    out = []
    for t in obj["topics"]:
        if not isinstance(t, dict):
            out.append(t)
            continue
        t = dict(t)
        ln = t.get("line")
        if isinstance(ln, str) and ln.strip().isdigit():
            t["line"] = int(ln.strip())
        elif isinstance(ln, float) and ln.is_integer():
            t["line"] = int(ln)
        for key in ("title", "gist"):
            if isinstance(t.get(key), str):
                t[key] = re.sub(r"\s*[\r\n]+\s*", " ", t[key]).strip()
        for key in ("quotes", "claims", "channels"):
            v = t.get(key)
            if isinstance(v, list):
                t[key] = [{**it, "ts": _fix_ts(it["ts"])}
                          if isinstance(it, dict) and "ts" in it else it for it in v]
        if isinstance(t.get("quotes"), list) and len(t["quotes"]) > MAX_QUOTES:
            t["quotes"] = t["quotes"][:MAX_QUOTES]
        if isinstance(t.get("asr"), list):
            t["asr"] = [a for a in t["asr"]
                        if not (isinstance(a, dict) and a.get("heard") == a.get("means"))]
        out.append(t)
    out.sort(key=_line_key)
    return {**obj, "topics": out}


def check_frag(obj, first_line: int, last_line: int) -> list[str]:
    """只拦代码修不了的（SPEC §4.1）。空列表算过。

    逐字命中与时间戳范围不在这里——那是 L3 的事（#53）。`filler` 多写的内容、
    `aside` 多写的锚点也不拦：留在片段里，渲染不出，不丢。
    """
    if not isinstance(obj, dict):
        return ["顶层不是对象"]
    topics = obj.get("topics")
    if not isinstance(topics, list) or not topics:
        return ["`topics` 不是非空数组"]

    errs: list[str] = []
    for n, t in enumerate(topics, 1):
        # 报错不带标题、不带正文（红线 6：日志与留档只报位置与计数）
        tag = f"第{n}个话题"
        if not isinstance(t, dict):
            errs.append(f"{tag}: 不是对象")
            continue
        if isinstance(t.get("line"), int) and not isinstance(t.get("line"), bool):
            tag = f"第{n}个话题（行 {t['line']}）"
        for k in TOPIC_KEYS:
            if k not in t:
                errs.append(f"{tag}: 缺字段 `{k}`")
        for k in ("title", "gist"):
            if k not in t:
                continue
            v = t[k]
            if not (isinstance(v, str) and v.strip()):
                errs.append(f"{tag}: `{k}` 不是非空字符串")
            # 这两个字段原样落进 EP 笔记的标记块（渲染不许改字，红线 2）
            elif "\n" in v or "\r" in v or "<!--" in v:
                errs.append(f"{tag}: `{k}` 里有换行或 HTML 注释，渲染进笔记会撑破标记块")
        if "kind" in t and t["kind"] not in KINDS:
            errs.append(f"{tag}: `kind` = {t['kind']!r} 不是 talk / aside / filler 之一")
        if "line" in t:
            ln = t["line"]
            if isinstance(ln, bool) or not isinstance(ln, int):
                errs.append(f"{tag}: `line` = {ln!r} 不是行号，要写这个话题开头那一行行首的整数")
            elif not first_line <= ln <= last_line:
                errs.append(f"{tag}: `line` = {ln} 不在本章的行号里（{first_line}–{last_line}）"
                            f"——行号只能取自「本章」那一段每行行首的那个数")
        errs += _check_paras(t, tag)
        errs += _check_items(t, tag)
    return errs


def _check_paras(t: dict, tag: str) -> list[str]:
    if "paras" not in t:
        return []
    paras = t["paras"]
    if not isinstance(paras, list):
        return [f"{tag}: `paras` 不是数组"]
    errs: list[str] = []
    if t.get("kind") in ("talk", "aside") and not [p for p in paras if str(p or "").strip()]:
        errs.append(f"{tag}: `kind` 是 {t.get('kind')}，`paras` 不能为空"
                    f"——把这一段讲了什么按叙述顺序写出来")
    for i, p in enumerate(paras, 1):
        if not isinstance(p, str) or not p.strip():
            errs.append(f"{tag}: 第 {i} 段不是非空字符串")
            continue
        if not PARA_HEAD_RE.match(p.strip()):
            errs.append(f"{tag}: 第 {i} 段不以 `[HH:MM:SS]` 开头"
                        f"——每段开头照抄这一段头一句话所在那一行行首的时间戳")
        bad = [m for m in TAG_RE.findall(p) if m not in OK_TAGS]
        if bad:
            errs.append(f"{tag}: 第 {i} 段里有 `{bad[0]}`，只认 `<who>` 与 `<hedge>` 两种标记")
    return errs


def _check_items(t: dict, tag: str) -> list[str]:
    errs: list[str] = []
    for key, keys in ITEM_KEYS.items():
        if key not in t:
            continue
        v = t[key]
        if not isinstance(v, list):
            errs.append(f"{tag}: `{key}` 不是数组")
            continue
        for i, it in enumerate(v, 1):
            if not isinstance(it, dict):
                errs.append(f"{tag}: `{key}` 第 {i} 条不是对象")
                continue
            for k in keys:
                if k not in it:
                    errs.append(f"{tag}: `{key}` 第 {i} 条缺 `{k}`")
                elif not isinstance(it[k], str):
                    errs.append(f"{tag}: `{key}` 第 {i} 条的 `{k}` 不是字符串")
                # 这些字段原样落进 EP 笔记的标记块：里面混进 `<!-- /digest -->`，
                # 下一次整块替换就在那里收尾，后半块被甩到块外、再也清不掉
                # （红线 5：块外一个字节不动）。删注释等于改字，只能打回
                elif "<!--" in it[k]:
                    errs.append(f"{tag}: `{key}` 第 {i} 条的 `{k}` 里有 HTML 注释，"
                                f"渲染进笔记会撑破标记块")
            if "ts" in keys and isinstance(it.get("ts"), str) and parse_hms(it["ts"]) is None:
                errs.append(f"{tag}: `{key}` 第 {i} 条的 `ts` = {it['ts']!r} 读不出时刻，"
                            f"要写成 HH:MM:SS")
    return errs


# ---------------------------------------------------------------- 产物

def finish(topics: list[dict], chapter: dict, lines: list[dict],
           speakers: dict) -> list[dict]:
    """模型写的九个键 → §5.4 的片段。检查过了才调。

    代码填的：`id` = `<章节 id>-NN`（章内按先后从 01 编）、`chapter`、`start`（该行
    行首的时刻，章内第一个话题归到章的 `start`）、`end`（下一个话题的 `start`，
    最后一个收在章的 `end`）、`who`（话题自己的行里出现过的说话人）。模型写的
    `line` 不进产物——它是指位置用的脚手架。
    """
    ch_start = parse_hms(chapter.get("start")) or 0
    ch_end = parse_hms(chapter.get("end")) or 0
    starts = []
    for i, t in enumerate(topics):
        t0 = line_t(lines, t.get("line")) if i else None
        starts.append(ch_start if i == 0 or t0 is None else t0)

    out = []
    for i, t in enumerate(topics):
        start, end = starts[i], (starts[i + 1] if i + 1 < len(starts) else ch_end)
        frag = {"id": f"{chapter['id']}-{i + 1:02d}", "chapter": chapter["id"],
                "title": t.get("title"), "kind": t.get("kind"),
                "start": hms(start), "end": hms(max(start, end)),
                "who": _who(lines, start, end, speakers), "gist": t.get("gist")}
        for k in BODY_KEYS:
            frag[k] = t[k] if isinstance(t.get(k), list) else []
        out.append(frag)
    return out


def _who(lines: list[dict], start: int, end: int, speakers: dict) -> list[str]:
    """这个话题自己的行里出现过的说话人，按出场先后，用点名后的名字。"""
    out: list[str] = []
    for ln in pick_lines(lines, start, end):
        name = bare_name(speakers.get(ln["tag"], ln["tag"]))
        if name and name not in out:
            out.append(name)
    return out


def head_of(frag: dict) -> dict:
    """片段去掉五类内容剩下的头——话题表就是这些头的索引（§5.3）。"""
    return {k: frag.get(k) for k in HEAD_KEYS}


def topics_doc(ep: str, chapters: list[dict], done: dict, *, model: str, effort: str,
               prompt_version: str, generated_at: str | None) -> dict:
    """已完成章节的话题头，按 `start` 排（§5.3）。

    provenance 取片段自己的（`generated_at` 取各片段里最晚的那个）：没有片段重生成
    时重写出来逐字节不变，笔记也就不会每跑一次 `-Extract` 变一次。
    """
    heads, provs = [], []
    for c in chapters:
        for frag in done.get(c.get("id"), []):
            heads.append(head_of(frag))
            provs.append(frag.get("provenance") or {})
    heads.sort(key=lambda t: parse_hms(t.get("start")) or 0)
    last = max(provs, key=lambda p: str(p.get("generated_at") or ""), default={})
    return {"ep": ep, "topics": heads,
            "provenance": provenance(
                derived_from=["chapters.json", "frag-*.json"], layer=LAYER, unit="all",
                engine=last.get("engine") or model, effort=last.get("effort") or effort,
                prompt_version=last.get("prompt_version") or prompt_version,
                generated_at=last.get("generated_at") or generated_at or now_iso())}


# ---------------------------------------------------------------- 跑一集

def _write_json(path: Path, obj) -> None:
    """先写临时文件再 `os.replace`——落盘要么是旧的一整份，要么是新的一整份。

    `topics.json` 每完成一章就重写一次，而它同时是「这一章跑没跑过」的判据：
    直接 `write_bytes` 的话，这中间有一小段时间文件是截断的，谁在那一刻读它
    （下一趟的 `read_done`、跑到一半被杀之后的下一次 `-Extract`）都会读到半份
    JSON，整集的已完成状态凭空蒸发。`os.replace` 在 POSIX 与 Windows 上都是原子的。
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes((json.dumps(obj, ensure_ascii=False, indent=1) + "\n").encode("utf-8"))
    os.replace(tmp, path)


def _read_json(path: Path):
    try:
        return json.loads(Path(path).read_bytes().decode("utf-8"))
    except (OSError, ValueError, UnicodeDecodeError):
        return None


def read_done(paths, ep: str, chapters: list[dict], log=print) -> tuple[dict, list[str]]:
    """已完成的章 → 它的片段；外加孤儿话题的 `id`。

    **一章算完成** = 话题表里有 `chapter` 等于它的话题、这些话题的片段文件都在、
    而且它们首尾正好铺满这一章（片段写了一半被杀的那种，话题表还没更新，这里就
    当它没完成，重跑补上）。
    话题表里 `chapter` 不在当前章节表里的是孤儿（L1 重跑过，章节没了）。

    **边界也要对上**：L1 重跑后 `id` 可能照旧（`market` 还叫 `market`）而起止时刻
    换了。只认 `id` 的话这一章会被当成已完成跳过，笔记上留着按旧边界整理的话题，
    与章节表对不上——那是静默的不一致，比重跑一章贵得多。
    """
    d = paths.digest(ep)
    doc = _read_json(d / "topics.json") if (d / "topics.json").exists() else None
    if (d / "topics.json").exists() and not isinstance(doc, dict):
        log(f"    ⚠ {paths.rel(d / 'topics.json')} 读不出来，当作没整理过——各章会重跑")
        doc = None
    spans = {c.get("id"): (c.get("start"), c.get("end")) for c in chapters}
    want: dict[str, list[str]] = {}
    orphans: list[str] = []
    for t in (doc or {}).get("topics") or []:
        if not isinstance(t, dict) or not t.get("id"):
            continue
        if t.get("chapter") in spans:
            want.setdefault(t["chapter"], []).append(t["id"])
        else:
            orphans.append(t["id"])

    done: dict[str, list[dict]] = {}
    for ch, tids in want.items():
        frags = [_read_json(d / f"frag-{tid}.json") for tid in tids]
        if not all(isinstance(f, dict) for f in frags):
            continue
        if (frags[0].get("start"), frags[-1].get("end")) != spans[ch]:
            log(f"    L2：章 {ch} 的起止时刻跟章节表对不上（L1 重切过？），这一章重跑")
            continue
        done[ch] = frags
    return done, orphans


def drop_chapter_frags(digest_dir: Path, chapter_id: str) -> int:
    """删掉 `chapter` 等于它的片段。**按片段里的 `chapter` 键认，不按文件名猜**
    ——`frag-market-*.json` 会误伤 `market-2` 章的片段。"""
    n = 0
    for p in sorted(Path(digest_dir).glob("frag-*.json")):
        obj = _read_json(p)
        if isinstance(obj, dict) and obj.get("chapter") == chapter_id:
            p.unlink()
            n += 1
    return n


def _one_chapter(paths, runner, ep: str, chapter: dict, chapters: list[dict],
                 lines: list[dict], speakers: dict, prompt: dict, *, model: str,
                 effort: str, timeout: int, retries: int, generated_at: str | None,
                 log) -> tuple[dict | None, dict, list[str], bool]:
    """线程里跑的那一段：拼输入 → runner → 检查。**不碰 `_digest/`。**

    runner 自己抛的（CLI 不在、退出码非 0、存档缺键）在这里收住：一章挂了不该把
    其他章掀翻，但也绝不静默——调用方按失败记账，照样落 `_failed/`（红线 9）。
    """
    body = _slice(chapter, lines)[1]
    if not body:
        return None, {}, [f"章 {chapter.get('id')} 的时间范围里一行都没有"], True
    first, last = body[0]["n"], body[-1]["n"]
    text = build_input(ep, chapter, chapters, lines, speakers)
    try:
        obj, envelope, errors = call_layer(
            paths, runner, ep, LAYER, chapter["id"], prompt["path"], text,
            lambda o: check_frag(tidy(o), first, last),
            retries=retries, model=model, effort=effort, timeout=timeout, log=log,
            generated_at=generated_at, schema=schema_for(first, last))
    except Exception as e:                                   # noqa: BLE001
        return None, {}, [f"{type(e).__name__}: {e}"], True
    if obj is None:
        return None, envelope, errors, False
    return tidy(obj), envelope, errors, False


def run_l2(paths, runner, ep: str, chapters: list[dict], segments: list[dict],
           speakers: dict, prompt: dict, *, workers: int = 3, force: bool = False,
           only=None, model: str = "sonnet", effort: str = "medium", timeout: int = 1800,
           retries: int = 1, generated_at: str | None = None,
           log=print) -> tuple[dict | None, dict, list[str]]:
    """跑 L2 并落 `_digest/EP{n}/frag-*.json` 与 `topics.json`。

    返回 (话题表 | None, {话题 id: 片段}, 没整理出来的章节 id)。完成的章跳过、
    不调 runner；`force` 全部重跑；单章失败其他章照跑。
    """
    lines = build_lines(segments)
    chs = [c for c in (chapters or []) if isinstance(c, dict) and c.get("id")]
    digest_dir = paths.digest(ep)
    done, orphans = read_done(paths, ep, chs, log)

    doc, dirty = None, False
    if orphans:
        gone = 0
        for tid in orphans:
            p = digest_dir / f"frag-{tid}.json"
            if p.exists():
                p.unlink()
                gone += 1
        log(f"    L2：{len(orphans)} 个话题的章节已不在章节表里（L1 重跑过？），"
            f"连片段一起清掉（{gone} 份）")
        dirty = True

    todo = [c for c in chs if force or c["id"] not in done]
    if only:
        want = {only} if isinstance(only, str) else set(only)
        todo = [c for c in todo if c["id"] in want]
    for c in todo:
        done.pop(c["id"], None)
    if len(todo) < len(chs):
        log(f"    L2：{len(chs) - len(todo)} 章已完成，跳过不调用——要重跑加 --force")

    failed: list[str] = []
    if todo:
        with ThreadPoolExecutor(max_workers=max(1, int(workers))) as pool:
            futures = {pool.submit(
                _one_chapter, paths, runner, ep, c, chs, lines, speakers, prompt,
                model=model, effort=effort, timeout=timeout, retries=retries,
                generated_at=generated_at, log=log): c for c in todo}
            # 写盘全在主线程：各章的完成顺序不定，但 `topics.json` 只有这一支笔
            for fut in as_completed(futures):
                c = futures[fut]
                obj, envelope, errors, crashed = fut.result()
                if obj is None:
                    failed.append(c["id"])
                    if crashed:                       # call_layer 没来得及留档，补一份
                        _write_json(paths.failed(ep) / f"{LAYER}-{c['id']}.failed.json",
                                    {"scope": ep, "layer": LAYER, "unit": c["id"],
                                     "failed_at": generated_at or now_iso(),
                                     "errors": errors, "envelope": envelope})
                    log(f"    ⚠ 章 {c['id']} 没整理出来（{len(errors)} 项）→ "
                        f"{paths.rel(paths.failed(ep))}，其他章继续")
                    continue
                frags = finish(obj["topics"], c, lines, speakers)
                prov = provenance(
                    derived_from=[f"{ep}.transcript.json", "chapters.json"],
                    layer=LAYER, unit=c["id"], engine=engine_of(envelope, model),
                    effort=effort, prompt_version=prompt["version"],
                    generated_at=generated_at or now_iso())
                dropped = drop_chapter_frags(digest_dir, c["id"])
                for frag in frags:
                    frag["provenance"] = prov
                    _write_json(digest_dir / f"frag-{frag['id']}.json", frag)
                done[c["id"]] = frags
                dirty = True
                doc = topics_doc(ep, chs, done, model=model, effort=effort,
                                 prompt_version=prompt["version"],
                                 generated_at=generated_at)
                _write_json(digest_dir / "topics.json", doc)
                kinds = "、".join(f"{k} {sum(1 for f in frags if f['kind'] == k)}"
                                 for k in KINDS)
                log(f"    L2 {c['id']}：{len(frags)} 个话题（{kinds}）"
                    f"{f'，清掉旧片段 {dropped} 份' if dropped else ''}")

    if dirty and doc is None:                         # 只清了孤儿、没有章跑过
        doc = topics_doc(ep, chs, done, model=model, effort=effort,
                         prompt_version=prompt["version"], generated_at=generated_at)
        _write_json(digest_dir / "topics.json", doc)
    if doc is None:
        # 这一趟没有一章写成（全都跳过了，或者跑过的全挂了）：盘上那份话题表还停在
        # 上一趟。**只认这一趟真拿到片段的章**——失败的那些章，旧表里有它们的话题、
        # 片段却没装进 `done`，照着旧表渲染出来就是一串空标题，frontmatter 还写着
        # `整理: done`，失败在人唯一会读的那一面上彻底消失（红线 9）。全跳过的那种
        # 情况这里一个都不会滤掉，`topics.json` 也不重写，笔记照旧逐字节不变
        doc = _read_json(digest_dir / "topics.json")
        if isinstance(doc, dict):
            doc = {**doc, "topics": [t for t in (doc.get("topics") or [])
                                     if isinstance(t, dict) and t.get("chapter") in done]}
    return doc, {f["id"]: f for fs in done.values() for f in fs}, failed
