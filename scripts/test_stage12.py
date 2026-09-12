#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""stage12.py 的离线测试：分块、三闸门、schema、渲染。不烧额度，不碰网络。

    python scripts/test_stage12.py

这些是**机械纪律**的测试。抽取质量本身测不了——那是 golden 样例的活儿，
等第一批人审过的草稿攒出来再说（见 SPEC §10）。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import stage12 as S  # noqa: E402

FAIL = 0


def check(name, got, want):
    global FAIL
    if got == want:
        print(f"  PASS  {name}")
    else:
        FAIL += 1
        print(f"  FAIL  {name}\n    got : {got!r}\n    want: {want!r}")


def ok(name, cond, why=""):
    check(name, bool(cond) or why or False, True)


def seg(a, b, text="话", spk="SPEAKER_00"):
    return {"start": a, "end": b, "speaker": spk, "text": text}


# ---------------------------------------------------------------- 分块

print("== 阶段 1 分块 ==")
short = [seg(i * 30, i * 30 + 30) for i in range(54)]          # 27 分钟，EP03 的形状
cs = S.chunk_segments(short, 25 * 60, 30 * 60, 20 * 60, 90)
check("27 分钟切成 1 块", len(cs), 1)
check("单块覆盖全程", (cs[0]["start"], cs[0]["end"]), (0, 1620))
check("块标签从 A 起", cs[0]["label"], "A")

long = [seg(i * 30, i * 30 + 30) for i in range(360)]          # 3 小时
cl = S.chunk_segments(long, 25 * 60, 30 * 60, 20 * 60, 90)
ok("3 小时切成多块", len(cl) >= 6, f"只切了 {len(cl)} 块")
ok("每块不超过 max", all(c["end"] - c["start"] <= 30 * 60 + 30 for c in cl),
   [(S.hms(c["start"]), S.hms(c["end"])) for c in cl])
ok("块间有重叠", all(cl[i + 1]["start"] < cl[i]["end"] for i in range(len(cl) - 1)),
   [(S.hms(c["start"]), S.hms(c["end"])) for c in cl])
ok("重叠在 1–2 分钟量级",
   all(60 <= cl[i]["end"] - cl[i + 1]["start"] <= 150 for i in range(len(cl) - 1)),
   [cl[i]["end"] - cl[i + 1]["start"] for i in range(len(cl) - 1)])
check("覆盖到最后一段", cl[-1]["end"], long[-1]["end"])
check("标签连续", [c["label"] for c in cl], [chr(ord("A") + i) for i in range(len(cl))])

# 25.5 分钟：多出来的半分钟并进上一块，不另起一块
snug = [seg(i * 30, i * 30 + 30) for i in range(51)]
cn = S.chunk_segments(snug, 25 * 60, 30 * 60, 20 * 60, 90)
check("25.5 分钟仍是 1 块", len(cn), 1)
check("并进来后覆盖全程", cn[0]["end"], 1530)

# 32 分钟：并不进去（破 max），于是均分，而不是留个 8 分钟的零头
tail = [seg(i * 30, i * 30 + 30) for i in range(64)]
ct = S.chunk_segments(tail, 25 * 60, 30 * 60, 20 * 60, 90)
check("32 分钟切 2 块", len(ct), 2)
ok("均分而非 25+7", abs((ct[0]["end"] - ct[0]["start"]) - (ct[1]["end"] - ct[1]["start"]))
   < 5 * 60, [(S.hms(c["start"]), S.hms(c["end"])) for c in ct])
check("末块到底", ct[-1]["end"], 1920)
check("空输入", S.chunk_segments([], 1500, 1800, 1200, 90), [])

# ---------------------------------------------------------------- 归一化

print("== 归一化 ==")
check("去时间戳去空白", S.norm("[00:12:03] 好 大家好"), "好大家好")
check("全角空格也去", S.norm("好　大家好"), "好大家好")
check("标点不动（SPEC 只授权去时间戳和空白）", S.norm("好,大家好"), "好,大家好")
check("实体名去分隔符", S.norm_entity("杰西·利维摩尔"), "杰西利维摩尔")

# ---------------------------------------------------------------- 三闸门

print("== 闸门 1–3 ==")
BODY = ("[00:00:03] 奇衡（主播）: 好,大家好我是奇衡我讲股票作手回忆录这本书\n"
        "[00:00:33] 奇衡（主播）: 另外一本叫做证券分析你们可以去看杰西利维摩尔的超盘术\n")
TS = set(S.LINE_TS_RE.findall(BODY))
BODY = S.haystack(BODY)
check("干草堆里没有行首脚手架", "奇衡（主播）" in BODY, False)
check("干草堆里两行接上了", "这本书另外一本" in BODY, True)


def row(**kw):
    r = {k: None for k in S.ROW_KEYS}
    r.update({"id": "A-01", "type": "channel", "正文": "x", "情态": "确定",
              "谁说的": "奇衡", "归因类型": "无外部归因", "录音时间戳": "00:00:33",
              "渠道类型": "书", "名称": "证券分析", "原话口径": "证券分析",
              "实体": [], "主题候选": [], "素材": False,
              "source_quote": ["另外一本叫做证券分析"]})
    r.update(kw)
    return r


check("全过", S.check_gates(row(), BODY, TS), [])
check("引文加了标点就不算命中",
      len(S.check_gates(row(source_quote=["另外一本，叫做证券分析"]), BODY, TS)), 1)
ok("引文跨行拼接算命中（去空白后连续）",
   S.check_gates(row(source_quote=["这本书另外一本叫做证券分析"]), BODY, TS) == [],
   S.check_gates(row(source_quote=["这本书另外一本叫做证券分析"]), BODY, TS))
ok("闸门1 报的是引文", "闸门1" in S.check_gates(row(source_quote=["我知道但他没说"]),
                                                BODY, TS)[0])
check("实体在引文里", S.check_gates(row(实体=["证券分析"]), BODY, TS), [])
ok("实体规整成带点的人名仍算命中",
   S.check_gates(row(实体=["杰西·利维摩尔"],
                     source_quote=["你们可以去看杰西利维摩尔的超盘术"]), BODY, TS) == [])
ok("实体不在引文里 → 闸门2",
   "闸门2" in S.check_gates(row(实体=["美联储"]), BODY, TS)[0])
ok("编造的时间戳 → 闸门3",
   "闸门3" in S.check_gates(row(录音时间戳="09:99:00"), BODY, TS)[0])
check("三条一起挂", len(S.check_gates(
    row(source_quote=["编的"], 实体=["美联储"], 录音时间戳="01:00:00"), BODY, TS)), 3)

# ---------------------------------------------------------------- 闸门 0

print("== 闸门 0 schema ==")
GOOD = {"episode": "EP03", "chunk": "A", "rows": [row()], "归因目击": []}
check("合法", S.check_schema(GOOD), [])
check("rows 可以为空", S.check_schema({"episode": "E", "chunk": "A", "rows": []}), [])

bad = {"episode": "E", "chunk": "A", "rows": [row()]}
del bad["rows"][0]["链接"]
ok("缺键被抓", any("缺字段 `链接`" in e for e in S.check_schema(bad)))
ok("枚举外的情态被抓",
   any("`情态`" in e for e in S.check_schema(
       {"episode": "E", "chunk": "A", "rows": [row(情态="可能")]})))
ok("枚举外的渠道类型被抓",
   any("`渠道类型`" in e for e in S.check_schema(
       {"episode": "E", "chunk": "A", "rows": [row(渠道类型="网站")]})))
ok("空 source_quote 被抓",
   any("source_quote" in e for e in S.check_schema(
       {"episode": "E", "chunk": "A", "rows": [row(source_quote=[])]})))
ok("素材不是布尔被抓",
   any("素材" in e for e in S.check_schema(
       {"episode": "E", "chunk": "A", "rows": [row(素材="是")]})))
ok("时间戳格式被抓",
   any("录音时间戳" in e for e in S.check_schema(
       {"episode": "E", "chunk": "A", "rows": [row(录音时间戳="12:03")]})))
ok("没补全到日的事件时间被抓",
   any("事件时间" in e for e in S.check_schema(
       {"episode": "E", "chunk": "A", "rows": [row(事件时间="2020")]})))
check("事件时间精度允许 null", S.check_schema(
    {"episode": "E", "chunk": "A", "rows": [row(事件时间精度=None)]}), [])

# ---------------------------------------------------------------- 挖 JSON

print("== 从响应里挖 JSON ==")
check("裸 JSON", S.extract_json('{"a": 1}'), {"a": 1})
check("裹在围栏里", S.extract_json('```json\n{"a": 1}\n```'), {"a": 1})
check("带前言", S.extract_json('好的，结果如下：\n{"a": 1}\n'), {"a": 1})
check("字符串里的花括号不算数", S.extract_json('{"a": "}{"}'), {"a": "}{"})
try:
    S.extract_json("什么都没有")
    check("没 JSON 应该抛", False, True)
except ValueError:
    check("没 JSON 应该抛", True, True)

# ---------------------------------------------------------------- 渲染

print("== 渲染（草稿是阅读面，不是容器）==")
check("换行压平", S.flat("上\n下"), "上 下")
check("None 成空串", S.flat(None), "")
check("方括号原样留着（草稿不是行内字段，不用转义）", S.flat("看[图1]"), "看[图1]")

sec = "\n".join(S.render_row(
    row(实体=["证券分析"], 为什么值得看="讲得清楚"), []))
ok("标题是 ### id + 名称", sec.startswith("### A-01　证券分析"), sec[:40])
ok("时间戳露在前面", "00:00:33" in sec.split("\n")[2], sec.split("\n")[2])
ok("时间戳没被反引号包住（包了插件就跳不动）", "`00:00:33`" not in sec)
ok("正文成段", "\n" + row()["正文"] + "\n" in "\n" + sec, sec)
ok("空字段不渲染", "取数地址" not in sec and "链接" not in sec, sec)
ok("有值的字段渲染", "**为什么值得看**　讲得清楚" in sec, sec)
ok("引文进折叠块", "> [!quote]- 逐字引文 1 条" in sec, sec)
ok("引文原样在里面", "> 另外一本叫做证券分析" in sec, sec)
ok("草稿里不打双链（`_review/` 不参与图谱）", "[[" not in sec, sec)
ok("涉及的实体写成人话", "- **涉及**　证券分析" in sec, sec)
ok("没挂闸门就不打 ⛔", "⛔" not in sec)
ok("不再有一行挤满的括号式字段", "[type:: channel]" not in sec)

sec2 = "\n".join(S.render_row(row(), ["闸门1 引文未逐字命中：「x…」"]))
ok("挂了闸门标题打 ⛔", sec2.split("\n")[0].endswith("⛔　证券分析"), sec2.split("\n")[0])
ok("闸门失败单独成块", "[!bug]" in sec2 and "闸门1" in sec2, sec2)
ok("说清没被丢掉", "没有被丢掉" in sec2)

sec3 = "\n".join(S.render_row(row(存疑原因="语气固化"), []))
ok("模型自标可疑也打 ⛔", "⛔" in sec3.split("\n")[0])
ok("存疑理由单独成块", "[!warning]" in sec3 and "语气固化" in sec3, sec3)

multi = "\n".join(S.render_row(row(source_quote=["甲", "乙"]), []))
ok("多条引文都在", "> 甲" in multi and "> 乙" in multi, multi)
ok("引文条数写对", "逐字引文 2 条" in multi, multi)

noname = "\n".join(S.render_row(row(名称=None), []))
ok("没有名称就用正文开头当标题", noname.startswith("### A-01　x…"), noname[:30])

# ---------------------------------------------------------------- 笔记读取

print("== 读 EP 笔记 ==")
NOTE = ("---\ntype: episode\nepisode: EP03\n主播: [\"奇衡\"]\n嘉宾: []\n"
        "播出日期: 2020-03-21\n---\n\n"
        "> - `SPEAKER_00` **奇衡**（主播）说了 00:22:49  [SPEAKER_00:: 奇衡]\n"
        "> - `SPEAKER_01` **未知1** 说了 00:04:00 → 点名 [SPEAKER_01:: ]\n")
fm = S.read_frontmatter(NOTE)
check("frontmatter 列表", fm["主播"], ["奇衡"])
check("空列表", fm["嘉宾"], [])
check("点过名的带上角色", S.read_speakers(NOTE, fm), {"SPEAKER_00": "奇衡（主播）"})
check("没点名的不编名字", "SPEAKER_01" in S.read_speakers(NOTE, fm), False)

ch = {"label": "A", "start": 3, "end": 63,
      "segs": [seg(3, 33, "好大家好"), seg(33, 63, "另外一本")]}
txt = S.render_chunk("EP03", ch, fm, {"SPEAKER_00": "奇衡（主播）"}, [])
ok("块头有播出日期", "播出日期: 2020-03-21" in txt, txt)
ok("块头有时间范围", "时间范围: 00:00:03–00:01:03" in txt, txt)
ok("行首是 [时间] 名字:", "[00:00:03] 奇衡（主播）: 好大家好" in txt, txt)
ok("正文与块头以 --- 分隔", S.chunk_body(txt).startswith("[00:00:03]"), S.chunk_body(txt)[:30])
ok("块头不算原文（闸门只在正文上匹配）", "播出日期" not in S.chunk_body(txt))

print()
print(f"{FAIL} 项失败" if FAIL else "全部通过")
sys.exit(1 if FAIL else 0)
