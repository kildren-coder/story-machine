# -*- coding: utf-8 -*-
"""生成 tests/fixtures/ 下的全部合成样例（红线 10：内容全部虚构，不含任何真实转写）。

单一事实来源：下面的对白表 → 逐字稿 JSON、EP 笔记、topics/frag/events、假 claude 原始响应。
所有引文由本脚本断言为某一段的连续子串；时间戳由本脚本按段计算。
"""
from __future__ import annotations
import io, json, sys, pathlib, copy, shutil

sys.stdout.reconfigure(encoding="utf-8")
ROOT = pathlib.Path(__file__).resolve().parent
GEN_AT = "2026-03-12T23:10:00+08:00"


def hms(sec: float) -> str:
    sec = int(round(sec))
    return f"{sec // 3600:02d}:{sec % 3600 // 60:02d}:{sec % 60:02d}"


def wjson(p: pathlib.Path, obj):
    p.parent.mkdir(parents=True, exist_ok=True)
    io.open(p, "w", encoding="utf-8", newline="\n").write(
        json.dumps(obj, ensure_ascii=False, indent=1) + "\n")


def wtext(p: pathlib.Path, s: str):
    p.parent.mkdir(parents=True, exist_ok=True)
    io.open(p, "w", encoding="utf-8", newline="\n").write(s)


# ------------------------------------------------------------------ 对白（全部虚构）
A, Z = "SPEAKER_00", "SPEAKER_01"   # 阿桥（主播）、老周（嘉宾）

EP91_BLOCKS = [
    # (start_s, end_s, [(speaker, text), ...])
    (0, 210, [
        (A, "各位晚上好，河口夜话又开播了，今天麦克风换了个新的，你们听听有没有回音。"),
        (A, "弹幕说没回音那就好，今天老周也在，老周跟大家打个招呼。"),
        (Z, "大家好，我是老周，上周说好的大桥那个话题今天补上。"),
        (A, "对，今天主要聊两件事，一个是北港大桥的收费方案，一个是河口夜市要搬的事。"),
        (A, "先看一眼今天的直播间人数，两百多，比上周多一点，谢谢大家。"),
        (A, "那我们直接进正题吧，先说大桥。"),
    ]),
    (210, 1140, [
        (A, "北港大桥这个事情呢，我看到的消息是市交通局上周发了一个通报，说从2027年1月开始要按车型收费。"),
        (A, "通报里写的是小客车一次十五块，货车按吨位另算，但是具体的表我没找到。"),
        (Z, "我补充一下，那个通报我也看了，十五块是听证会的建议价，不是最后定的价。"),
        (Z, "听证会是三月三号开的，二十一个代表里有十四个赞成按车型收费。"),
        (A, "哦，那我说的十五块应该是不准确的，听说最后可能会压到十二块。"),
        (A, "这个十二块是我在一个叫桥梁观察的公众号上看到的，他们说是内部消息，我没法验证。"),
        (Z, "桥梁观察那个号我也关注，他们去年说大桥要延期通车，后来确实延期了，所以我觉得他们的消息有一定可信度。"),
        (A, "但有一定可信度不等于对，大家自己判断。"),
        (Z, "说回收费本身，大桥现在的日均车流量是四万辆左右，这是通报里的数字。"),
        (Z, "四万辆按十五块算，一天就是六十万，一年两亿多，这个数够还贷款利息了。"),
        (A, "贷款总额我记得是三十八个亿，工期五年，2024年年底通的车。"),
        (Z, "三十八亿这个数应该是对的，我在当年的招标公告里看到过。"),
        (A, "那这么算的话，光靠过桥费还本金要二十年往上，大概率还要财政补一部分。"),
        (Z, "这就是争议的地方，反对的人说大桥本来就是财政修的，凭什么再收一次钱。"),
        (A, "我看弹幕有人问北岗大桥是不是就是北港大桥，是的，我口音的问题，就是北港。"),
        (Z, "2019年河口有过一个先例，滨江隧道也想收费，听证会开了两次，最后没收成。"),
        (Z, "那次是因为隧道是市政债修的，收费的话等于市民付两次钱，舆论压力太大就搁置了。"),
        (A, "那这次大桥会不会也搁置？我猜有一半可能。"),
        (Z, "我倒觉得这次不一样，大桥有一部分是银行贷款，不收费的话利息是实打实的。"),
        (A, "好，我们先记着这个分歧，等一下看看弹幕怎么说。"),
        (A, "还有一个细节，通报说本地牌照的车可能有优惠，好像是每月前二十次免费。"),
        (Z, "每月前二十次这个我没看到，可能是你记混了，我记得是每月前十次。"),
        (A, "那这个我不确定，大家去看原文，通报在市交通局官网上能搜到。"),
        (Z, "对，原文标题是关于北港大桥收费方案征求意见的通告，三月五号发的。"),
        (A, "这个话题我们等会儿再回来，先说夜市。"),
        (A, "夜市那边的消息更新一点，是今天早上刚出的。"),
        (Z, "好，先喝口水。"),
        (A, "那说夜市。"),
    ]),
    (1140, 2160, [
        (A, "河口夜市搬迁这个事，河口晚报今天早上发了报道，说夜市要整体搬到滨江路。"),
        (A, "报道里说现在夜市有一百二十户商户，搬迁之后新地方能容纳一百五十户。"),
        (Z, "一百二十户这个数我有点怀疑，我上个月去数过，摊位不到一百个。"),
        (A, "可能报道算的是登记的户数，不是实际出摊的。"),
        (Z, "有可能，登记和出摊差二三十户也正常。"),
        (A, "搬迁的时间报道说是六月底之前完成，但没说具体哪一天。"),
        (Z, "六月底应该是赶在暑假前，暑假是夜市生意最好的时候。"),
        (A, "商户那边的反应，报道采访了三个摊主，两个反对一个中立。"),
        (A, "反对的理由主要是滨江路那边人流没有现在的老街多。"),
        (Z, "这个担心有道理，滨江路晚上确实没什么人，公交也少。"),
        (A, "但市里的说法是老街消防不达标，去年检查出了四十多处隐患。"),
        (Z, "四十多处这个数字是消防部门的通报，我看过，好像是四十三处。"),
        (A, "好像是四十三处，这个我没记那么细。"),
        (Z, "那这个搬迁其实是消防倒逼的，不搬也得整改，整改的话夜市要停业。"),
        (A, "对，所以商户其实是在停业整改和搬迁之间选，不是搬和不搬之间选。"),
        (Z, "2016年河口有过类似的事，老码头市场也是因为消防搬的，搬完之后头一年生意掉了一半。"),
        (Z, "第二年才慢慢回来，所以这次商户担心不是没道理。"),
        (A, "老码头那次我记得后来市里给了一年免租，这次报道里没提免租的事。"),
        (Z, "没提不代表没有，可能还在谈。"),
        (A, "弹幕有人说自己就是夜市的摊主，说通知是上周五收到的，跟报道对得上。"),
        (A, "这位朋友说租金每月两千，新地方说是一千八，比现在便宜一点。"),
        (Z, "便宜两百块，一年两千四，但人流少的话根本补不回来。"),
        (A, "对，商户算的是总账不是租金。"),
        (Z, "还有一个信息，河口晚报的报道最后提到新夜市会有统一的排污和用电改造。"),
        (A, "这个是好事，老街那边电线确实乱。"),
        (A, "好，夜市这个事我们就说到这，有新消息再更新。"),
        (Z, "那回到大桥，刚才有几个弹幕的问题没回。"),
        (A, "对，回大桥。"),
    ]),
    (2160, 2490, [
        (A, "弹幕问收费之后有没有替代路线，有的，老的北港浮桥还在，但只能走小车。"),
        (Z, "浮桥限重两吨，货车走不了，货车绕行要多跑二十几公里。"),
        (A, "所以货运公司应该是最反对收费的，他们的成本直接涨。"),
        (Z, "通报里货车的费率没公布，只说按吨位另算，这个另算是什么意思不清楚。"),
        (A, "还有人问听证会的记录哪里能看，市交通局官网有，但我没找到下载链接。"),
        (Z, "我这边有一份，是从一个货运行业群里传出来的，我不确定是不是完整版。"),
        (A, "那这个我们就不引用了，等官方版本出来再说。"),
        (Z, "最后再说一句，收费方案的意见征集到三月三十一号截止，大家有意见可以去提。"),
        (A, "对，三月三十一号截止，这个日期是通报里写的。"),
        (A, "大桥的事就先到这。"),
    ]),
    (2490, 2560, [
        (A, "最后回几个跟今天话题无关的弹幕，有人问下周播什么，下周聊河口的老照片。"),
        (Z, "老照片那期我准备了一些一九八几年的，到时候给大家看。"),
        (A, "好，那今天就到这，感谢大家，点个关注，下周见。"),
        (Z, "下周见。"),
    ]),
]

EP92_BLOCKS = [
    (0, 60, [
        (A, "各位，加更一小段，刚才下播之后有朋友发了我一份东西，跟大桥收费有关。"),
        (A, "不长，十几分钟，说完就走。"),
    ]),
    (60, 780, [
        (A, "是这样，一位在货运公司上班的朋友把公司收到的征求意见函拍给我了。"),
        (A, "函上写的货车费率是按轴计算，两轴四十块，三轴六十块，四轴以上八十块。"),
        (A, "我先说明，这个是征求意见的版本，不是最后定的，而且我只看到了照片。"),
        (A, "按这个算，一辆四轴货车一天来回两趟就是三百二十块。"),
        (A, "朋友说他们公司一天大概有三十辆车过桥，一个月下来接近三十万。"),
        (A, "三十万这个数是他口头说的，我没有看到账。"),
        (A, "所以货运这边的反对应该会比我直播里估计的还要大。"),
        (A, "函里还有一条，说本地注册的货运企业可能有百分之三十的折扣。"),
        (A, "可能有，注意是可能，函上用的词是拟给予。"),
        (A, "另外照片里能看到函是三月十号发的，比通报晚了五天。"),
        (A, "我猜这是分批征求意见，先公众后企业。"),
        (A, "有朋友问要不要把照片发出来，我觉得不合适，那是朋友公司的内部文件。"),
        (A, "等官方版本出来我再对照着讲。"),
        (A, "还有一个更正，直播里我说本地牌照每月前二十次免费，老周说是前十次。"),
        (A, "我下播之后查了通报原文，是前十次，老周是对的，我记错了。"),
        (A, "好，大桥的补充就这些。"),
        (A, "以后有这种下播之后来的消息，我都用加更的方式说，不等下一周。"),
        (A, "那就这样。"),
    ]),
    (780, 840, [
        (A, "对了，下周的老照片那期时间不变，还是周四晚上八点。"),
        (A, "走了，拜拜。"),
    ]),
]


def build_segments(blocks):
    segs = []
    for start, end, lines in blocks:
        n = len(lines)
        step = (end - start) / n
        for i, (spk, text) in enumerate(lines):
            s = round(start + i * step, 2)
            e = round(start + (i + 1) * step - 0.4, 2)
            segs.append({"start": s, "end": e, "speaker": spk, "text": text})
    return segs


EP91 = build_segments(EP91_BLOCKS)
EP92 = build_segments(EP92_BLOCKS)
assert len(EP91) == 76 and len(EP92) == 22


def seg(segs, n):            # 1-based，对应上面对白的顺序
    return segs[n - 1]


def ts(segs, n):
    return hms(seg(segs, n)["start"])


def q(segs, n, who, text):
    """原话锚点：断言 text 是第 n 段的连续子串。"""
    assert text in seg(segs, n)["text"], (n, text)
    return {"ts": ts(segs, n), "who": who, "text": text}


# ------------------------------------------------------------------ 逐字稿 JSON（§5.1）
def transcript(ep, segs, note):
    return {"meta": {"ep": ep, "synthetic": True, "note": note,
                     "orthography": "zh-Hans", "engine": "synthetic-fixture"},
            "segments": segs}


wjson(ROOT / "vault/_assets/EP91.transcript.json", transcript(
    "EP91", EP91, "合成样例：虚构 UP 主「河口夜话」，虚构城市河口市。不是任何真实直播的转写。"))
wjson(ROOT / "vault/_assets/EP92.transcript.json", transcript(
    "EP92", EP92, "合成样例：同一虚构 UP 主同日加更，单说话人。不是任何真实直播的转写。"))

# ------------------------------------------------------------------ EP 笔记（§6.1；仿 worker 建笔记的形状）
EP91_NOTE = """---
type: episode
episode: EP91
title: 河口夜话 2026年3月12日 北港大桥与夜市
音频: EP91.m4a
播出日期: 2026-03-12
up: 河口夜话
主播: ["阿桥"]
嘉宾: ["老周"]
transcript: ../_assets/EP91.transcript.json
逐字稿渲染: ../_assets/EP91.txt
时长: 00:42:40
来源: https://example.invalid/video/EP91
转写引擎: synthetic-fixture
说话人分离: 3dspeaker-campp
转写时间: 2026-03-12T22:00:00
人物: ["阿桥", "老周"]
---

# EP91 河口夜话 2026年3月12日 北港大桥与夜市

<!-- ep:auto -->
```sm-ep
ep: EP91
worker: D:\\code\\story-machine\\scripts\\worker.ps1
```
<!-- /ep -->

> [!warning] 本笔记是容器，不是阅读面。
> 逐字稿正本在 `_assets/`，永不要求通读。

<!-- speakers:auto -->
> [!question]- 这集都有谁
> 「未知N」是声纹库认不出来的人：点它的时间戳听两句，把名字填进行尾方括号里保存。
> - `SPEAKER_00` **阿桥**（主播 · 声纹库 0.91）说了 00:24:10（57%），首次出现 00:00:00  [SPEAKER_00:: 阿桥]
> - `SPEAKER_01` **老周**（嘉宾 · 声纹库 0.88）说了 00:18:30（43%），首次出现 00:01:10  [SPEAKER_01:: 老周]
<!-- /speakers -->

## 断言

（旧版结构留下的空节：渲染整理稿时这一节必须原样保留，字节不动。）

## 待办

- [ ] 人写的待办，机器不许碰
"""

EP92_NOTE = """---
type: episode
episode: EP92
title: 河口夜话 2026年3月12日 加更 大桥补充
音频: EP92.m4a
播出日期: 2026-03-12
up: 河口夜话
主播: ["阿桥"]
嘉宾: []
transcript: ../_assets/EP92.transcript.json
逐字稿渲染: ../_assets/EP92.txt
时长: 00:14:00
来源: https://example.invalid/video/EP92
转写引擎: synthetic-fixture
说话人分离: 3dspeaker-campp
转写时间: 2026-03-12T23:00:00
人物: ["阿桥"]
整理: pending
---

# EP92 河口夜话 2026年3月12日 加更 大桥补充

<!-- ep:auto -->
```sm-ep
ep: EP92
worker: D:\\code\\story-machine\\scripts\\worker.ps1
```
<!-- /ep -->

<!-- speakers:auto -->
> [!question]- 这集都有谁
> - `SPEAKER_00` **阿桥**（主播 · 声纹库 0.93）说了 00:13:20（100%），首次出现 00:00:00  [SPEAKER_00:: 阿桥]
<!-- /speakers -->
"""

wtext(ROOT / "vault/10-Episodes/EP91 河口夜话 2026年3月12日 北港大桥与夜市.md", EP91_NOTE)
wtext(ROOT / "vault/10-Episodes/EP92 河口夜话 2026年3月12日 加更 大桥补充.md", EP92_NOTE)

# 一张已存在的事件笔记（§5.8）：L4 要沿用它的 id，L7 只能追加时间线、只能改 last_seen/days
EVENT_NOTE = """---
type: event
id: 2026-northbridge-toll
title: 北港大桥收费方案
first_seen: 2026-03-05
last_seen: 2026-03-05
days: [2026-03-05]
---
## 我的判断

我觉得收费方案大概率会拖到 2027 年下半年。这一段是人写的，软件永远不许改这里的任何一个字节。

## 时间线

### 2026-03-05
- 阿桥 EP90@00:12:00：通报刚出，先念了一遍收费方案的要点（overall: none）→ [[20-Daily/2026-03-05#事件卡]]
"""
wtext(ROOT / "vault/30-Events/2026-northbridge-toll.md", EVENT_NOTE)

# ------------------------------------------------------------------ 章节表（§5.3，L1）
# L1 只切十几分钟一章的容器；模型写每章从第几行开始（`line`），`start` / `end` /
# `who` / `ep` 由程序填。两集的段都比 30 秒长，所以第 n 行就是对白表的第 n 段
# （下面用 build_lines 断言过）。
sys.path.insert(0, str(ROOT.parent.parent / "scripts"))
from sm.transcript import build_lines          # noqa: E402

for _segs in (EP91, EP92):
    _lines = build_lines(_segs)
    assert len(_lines) == len(_segs)
    assert [ln["t"] for ln in _lines] == [int(round(s["start"])) for s in _segs]

# 每章：模型写 id / title / line / gist；时长 42:40 ÷ 15 分钟 → 参考章数 3
EP91_CHAPTERS_MODEL = {"chapters": [
    {"id": "bridge", "title": "开场、北港大桥收费方案", "line": 1,
     "gist": "开头几分钟换麦问好、预告今天聊两件事。随后进正题：北港大桥按车型收费的通报，十五块是听证会建议价、听说可能压到十二块，贷款三十八亿怎么还，2019 年滨江隧道没收成的先例，本地牌照每月前几次免费两人说法不一。章尾说大桥等会儿再回来，先说夜市。"},
    {"id": "market", "title": "河口夜市搬迁滨江路", "line": 35,
     "gist": "河口晚报今早报道夜市要整体搬到滨江路：商户数两人有出入，六月底前搬完，摊主多数反对；市里说老街消防不达标，老周说其实是在停业整改和搬迁之间选；2016 年老码头市场搬迁的先例；弹幕里有摊主报了租金。章尾回到大桥。"},
    {"id": "bridge-again", "title": "回到大桥：货车与浮桥、结尾弹幕", "line": 63,
     "gist": "接着上上章的大桥收费：回弹幕问的替代路线，浮桥限重货车走不了，货车费率通报没公布，听证会记录不引用流出版，意见征集三月三十一号截止。最后回几条无关弹幕、预告下周聊老照片，收尾。"},
]}
EP92_CHAPTERS_MODEL = {"chapters": [
    {"id": "followup", "title": "加更：北港大桥货车费率的征求意见函", "line": 1,
     "gist": "下播后朋友发来货运公司收到的征求意见函照片：货车按轴计费的费率、公司的过桥账、本地企业拟给折扣、函比通报晚五天；更正直播里说的每月前二十次免费，应为前十次。最后一句下周预告。"},
]}


def chapters_product(ep, model, segs, names, groups=None):
    """模型交的 → `chapters.json` 的样子：行号换成时刻、并掉不到 8 分钟的章、接终点、
    填说话人。`groups` 是期望的并法（手写，不调被测代码）：`[(留下的 id, [并在一起的
    各章 id]), …]`；并起来的标题用顿号接、gist 按先后用空格接，模型写的字原样。"""
    dur = int(round(segs[-1]["end"]))
    by_id = {c["id"]: c for c in model["chapters"]}
    cs = [{"id": keep, "line": by_id[ids[0]]["line"],
           "title": "、".join(by_id[i]["title"] for i in ids),
           "gist": " ".join(by_id[i]["gist"] for i in ids)}
          for keep, ids in (groups or [(c["id"], [c["id"]]) for c in model["chapters"]])]
    out = []
    for i, c in enumerate(cs):
        start = 0 if i == 0 else int(round(seg(segs, c["line"])["start"]))
        end = int(round(seg(segs, cs[i + 1]["line"])["start"])) if i + 1 < len(cs) else dur
        who = []
        for s in segs:
            if start <= int(round(s["start"])) < end and names[s["speaker"]] not in who:
                who.append(names[s["speaker"]])
        out.append({"id": c["id"], "title": c["title"], "start": hms(start), "end": hms(end),
                    "who": who, "gist": c["gist"]})
    return {"ep": ep, "chapters": out}


NAMES = {A: "阿桥", Z: "老周"}
# 模型把 EP91 切成了三章，第三章只有 6 分 40 秒（不到 8 分钟）——程序把它并进
# 相邻两章里较短的那个（`market`，17 分钟；另一边没有邻居）。章节表里剩两章
EP91_CHAPTERS = chapters_product("EP91", EP91_CHAPTERS_MODEL, EP91, NAMES,
                                 groups=[("bridge", ["bridge"]), ("market", ["market", "bridge-again"])])
EP92_CHAPTERS = chapters_product("EP92", EP92_CHAPTERS_MODEL, EP92, NAMES)
assert [(c["id"], c["start"], c["end"]) for c in EP91_CHAPTERS["chapters"]] == [
    ("bridge", "00:00:00", "00:19:00"), ("market", "00:19:00", "00:42:40")]

# L1 的坏输出：一章的行号不在这一集里（本集只有 76 行）、一章缺 title。
# 行号顺序乱、id 大写、首章没写 1 都不算坏（代码归一），写到表外才是坏。
EP91_CHAPTERS_BAD = copy.deepcopy(EP91_CHAPTERS_MODEL)
EP91_CHAPTERS_BAD["chapters"][1]["line"] = 99
del EP91_CHAPTERS_BAD["chapters"][2]["title"]

# ------------------------------------------------------------------ 话题（§5.3 话题表、§5.4 片段，L2）
# L2 一章一次调用，在章内细分话题。模型每个话题写 title / kind / line / gist 与五类
# 内容；`id`（`<章节 id>-NN`）、`chapter`、`start` / `end` / `who` 由程序填。
# 大桥那件事被夜市打断后又回来，成了两个话题——后面 L4 会把它们归回同一件事。
S = EP91


def para(n, text):
    return f"[{ts(S, n)}] {text}"


FRAG_OPENING = {
    "title": "开场与设备测试", "kind": "filler", "line": 1,
    "gist": "换了新麦克风、老周问好、预告今天聊大桥收费和夜市搬迁、报了直播间人数。",
    "paras": [], "quotes": [], "claims": [], "channels": [], "asr": [],
}

FRAG_BRIDGE = {
    "title": "北港大桥收费方案：十五块还是十二块", "kind": "talk", "line": 7,
    "gist": "通报按车型收费，十五块是听证会建议价、听说可能压到十二块；贷款三十八亿靠过桥费还不完；2019 年滨江隧道收费没收成的先例；本地牌照每月前几次免费两人说法不一。",
    "paras": [
        para(7, "<who>阿桥</who>说北港大桥的收费方案来自市交通局上周的一份通报，从 2027 年 1 月开始按车型收费；通报里小客车一次十五块，货车按吨位另算，具体的表他没找到。<who>老周</who>补充那份通报他也看了，十五块是听证会的建议价，不是最后定的价；听证会三月三号开的，二十一个代表里十四个赞成按车型收费。"),
        para(11, "<who>阿桥</who>承认自己说的十五块<hedge>应该</hedge>是不准确的，<hedge>听说</hedge>最后<hedge>可能</hedge>会压到十二块；这个十二块是他在一个叫桥梁观察的公众号上看到的，对方说是内部消息，他没法验证。<who>老周</who>说桥梁观察去年说大桥要延期通车、后来确实延期了，所以他觉得这个号的消息有一定可信度；<who>阿桥</who>说有一定可信度不等于对，让大家自己判断。"),
        para(15, "<who>老周</who>说回收费本身：通报里大桥日均车流量四万辆左右，按十五块算一天六十万、一年两亿多，够还贷款利息。<who>阿桥</who>记得贷款总额三十八个亿，工期五年，2024 年年底通的车；<who>老周</who>说三十八亿<hedge>应该</hedge>是对的，他在当年的招标公告里看到过。<who>阿桥</who>算下来光靠过桥费还本金要二十年往上，<hedge>大概率</hedge>还要财政补一部分；<who>老周</who>说这正是争议所在，反对的人说大桥本来就是财政修的，凭什么再收一次钱。"),
        para(21, "<who>阿桥</who>顺带回弹幕：北岗大桥就是北港大桥，是他的口音问题。<who>老周</who>举了 2019 年的先例：滨江隧道也想收费，听证会开了两次最后没收成，因为隧道是市政债修的，收费等于市民付两次钱，舆论压力太大就搁置了。<who>阿桥</who>问这次大桥会不会也搁置，<hedge>我猜</hedge>有一半<hedge>可能</hedge>；<who>老周</who>倒觉得这次不一样，大桥有一部分是银行贷款，不收费的话利息是实打实的。两人先记着这个分歧。"),
        para(27, "<who>阿桥</who>提到通报说本地牌照的车<hedge>可能</hedge>有优惠，<hedge>好像</hedge>是每月前二十次免费；<who>老周</who>说每月前二十次他没看到，<hedge>可能</hedge>是记混了，他记得是每月前十次。<who>阿桥</who>说这个他不确定，让大家去市交通局官网看原文；<who>老周</who>说原文标题是关于北港大桥收费方案征求意见的通告，三月五号发的。"),
    ],
    "quotes": [
        q(S, 7, "阿桥", "市交通局上周发了一个通报，说从2027年1月开始要按车型收费"),
        q(S, 9, "老周", "十五块是听证会的建议价，不是最后定的价"),
        q(S, 11, "阿桥", "听说最后可能会压到十二块"),
        q(S, 19, "阿桥", "光靠过桥费还本金要二十年往上，大概率还要财政补一部分"),
        q(S, 22, "老周", "2019年河口有过一个先例，滨江隧道也想收费，听证会开了两次，最后没收成"),
        q(S, 28, "老周", "可能是你记混了，我记得是每月前十次"),
    ],
    "claims": [
        {"ts": ts(S, 7), "who": "阿桥", "claim": "市交通局通报：北港大桥 2027 年 1 月起按车型收费",
         "quote": "市交通局上周发了一个通报，说从2027年1月开始要按车型收费"},
        {"ts": ts(S, 8), "who": "阿桥", "claim": "通报：小客车一次 15 元，货车按吨位另算",
         "quote": "通报里写的是小客车一次十五块，货车按吨位另算"},
        {"ts": ts(S, 10), "who": "老周", "claim": "听证会 3 月 3 日召开，21 名代表 14 人赞成按车型收费",
         "quote": "听证会是三月三号开的，二十一个代表里有十四个赞成按车型收费"},
        {"ts": ts(S, 11), "who": "阿桥", "claim": "最终价可能压到 12 元（来源：公众号「桥梁观察」）",
         "quote": "听说最后可能会压到十二块"},
        {"ts": ts(S, 15), "who": "老周", "claim": "通报：大桥日均车流量约 4 万辆",
         "quote": "大桥现在的日均车流量是四万辆左右，这是通报里的数字"},
        {"ts": ts(S, 17), "who": "阿桥", "claim": "贷款总额 38 亿，工期 5 年，2024 年底通车",
         "quote": "贷款总额我记得是三十八个亿，工期五年，2024年年底通的车"},
        {"ts": ts(S, 18), "who": "老周", "claim": "38 亿见于当年招标公告",
         "quote": "三十八亿这个数应该是对的，我在当年的招标公告里看到过"},
        {"ts": ts(S, 22), "who": "老周", "claim": "2019 年滨江隧道收费听证两次，最终未收费",
         "quote": "2019年河口有过一个先例，滨江隧道也想收费，听证会开了两次，最后没收成"},
        {"ts": ts(S, 28), "who": "老周", "claim": "本地牌照优惠为每月前 10 次免费（阿桥说 20 次）",
         "quote": "可能是你记混了，我记得是每月前十次"},
        {"ts": ts(S, 30), "who": "老周", "claim": "通告标题《关于北港大桥收费方案征求意见的通告》，3 月 5 日发布",
         "quote": "原文标题是关于北港大桥收费方案征求意见的通告，三月五号发的"},
    ],
    "channels": [
        {"ts": ts(S, 7), "who": "阿桥", "name": "市交通局通报", "kind": "政府通报",
         "quote": "市交通局上周发了一个通报"},
        {"ts": ts(S, 12), "who": "阿桥", "name": "桥梁观察", "kind": "公众号",
         "quote": "一个叫桥梁观察的公众号"},
        {"ts": ts(S, 18), "who": "老周", "name": "招标公告", "kind": "政府公告",
         "quote": "我在当年的招标公告里看到过"},
    ],
    "asr": [{"heard": "北岗大桥", "means": "北港大桥"}],
}

FRAG_MARKET = {
    "title": "河口夜市搬迁：消防倒逼下的选择", "kind": "talk", "line": 35,
    "gist": "晚报报道夜市六月底前搬到滨江路，商户多数反对；市里说老街消防隐患四十多处，其实是在停业整改和搬迁之间选；2016 年老码头市场搬迁头一年生意掉一半；摊主报的租金账。",
    "paras": [
        para(35, "<who>阿桥</who>说河口晚报今天早上报道夜市要整体搬到滨江路：现在一百二十户商户，新地方能容纳一百五十户。<who>老周</who>对一百二十户有点怀疑，他上个月去数过摊位不到一百个；<who>阿桥</who>说<hedge>可能</hedge>报道算的是登记户数不是实际出摊的，<who>老周</who>觉得有可能，差二三十户也正常。"),
        para(40, "搬迁时间报道说六月底之前完成，没说具体哪天；<who>老周</who>说六月底<hedge>应该</hedge>是赶在暑假前，暑假是夜市生意最好的时候。报道采访了三个摊主，两个反对一个中立，反对的理由是滨江路人流没有老街多；<who>老周</who>认为这个担心有道理，滨江路晚上确实没什么人，公交也少。"),
        para(45, "<who>阿桥</who>说市里的说法是老街消防不达标，去年检查出四十多处隐患；<who>老周</who>说这个数字来自消防部门的通报，<hedge>好像</hedge>是四十三处，<who>阿桥</who>说<hedge>好像</hedge>是四十三处、他没记那么细。<who>老周</who>由此说搬迁其实是消防倒逼的，不搬也得整改、整改就要停业；<who>阿桥</who>接着说商户其实是在停业整改和搬迁之间选，不是搬和不搬之间选。"),
        para(50, "<who>老周</who>举 2016 年的先例：老码头市场也是因为消防搬的，搬完头一年生意掉了一半，第二年才慢慢回来。<who>阿桥</who>记得老码头那次市里后来给了一年免租，这次报道里没提；<who>老周</who>说没提不代表没有，<hedge>可能</hedge>还在谈。"),
        para(54, "弹幕里一位自称夜市摊主的观众说通知是上周五收到的，跟报道对得上；租金每月两千，新地方说是一千八。<who>老周</who>算便宜两百一年两千四，但人流少的话根本补不回来；<who>阿桥</who>说商户算的是总账不是租金。<who>老周</who>补充晚报报道最后提到新夜市会有统一的排污和用电改造，<who>阿桥</who>说这是好事，老街电线确实乱。"),
    ],
    "quotes": [
        q(S, 35, "阿桥", "河口晚报今天早上发了报道，说夜市要整体搬到滨江路"),
        q(S, 37, "老周", "我上个月去数过，摊位不到一百个"),
        q(S, 46, "老周", "四十多处这个数字是消防部门的通报，我看过，好像是四十三处"),
        q(S, 49, "阿桥", "商户其实是在停业整改和搬迁之间选，不是搬和不搬之间选"),
        q(S, 50, "老周", "老码头市场也是因为消防搬的，搬完之后头一年生意掉了一半"),
    ],
    "claims": [
        {"ts": ts(S, 35), "who": "阿桥", "claim": "河口晚报报道：夜市整体搬迁至滨江路",
         "quote": "河口晚报今天早上发了报道，说夜市要整体搬到滨江路"},
        {"ts": ts(S, 36), "who": "阿桥", "claim": "现有商户 120 户，新址容纳 150 户",
         "quote": "现在夜市有一百二十户商户，搬迁之后新地方能容纳一百五十户"},
        {"ts": ts(S, 40), "who": "阿桥", "claim": "搬迁 6 月底前完成",
         "quote": "搬迁的时间报道说是六月底之前完成"},
        {"ts": ts(S, 46), "who": "老周", "claim": "消防部门通报：老街隐患 43 处",
         "quote": "四十多处这个数字是消防部门的通报，我看过，好像是四十三处"},
        {"ts": ts(S, 50), "who": "老周", "claim": "2016 年老码头市场因消防搬迁，次年生意减半",
         "quote": "2016年河口有过类似的事，老码头市场也是因为消防搬的，搬完之后头一年生意掉了一半"},
        {"ts": ts(S, 52), "who": "阿桥", "claim": "老码头搬迁后市里给过一年免租",
         "quote": "老码头那次我记得后来市里给了一年免租"},
    ],
    "channels": [
        {"ts": ts(S, 35), "who": "阿桥", "name": "河口晚报", "kind": "报纸",
         "quote": "河口晚报今天早上发了报道"},
        {"ts": ts(S, 46), "who": "老周", "name": "消防部门通报", "kind": "政府通报",
         "quote": "四十多处这个数字是消防部门的通报"},
    ],
    "asr": [],
}

FRAG_FREIGHT = {
    "title": "回到大桥：货车费率与浮桥", "kind": "talk", "line": 63,
    "gist": "接着前面的大桥收费：替代路线只有限重两吨的浮桥，货车得绕行；货车费率通报没公布；听证会记录只有流出版，不引用；意见征集三月三十一号截止。",
    "paras": [
        para(63, "回到大桥后<who>阿桥</who>回答替代路线：老的北港浮桥还在，但只能走小车；<who>老周</who>说浮桥限重两吨，货车走不了，绕行要多跑二十几公里。<who>阿桥</who>说货运公司<hedge>应该</hedge>是最反对收费的，成本直接涨；<who>老周</who>说通报里货车费率没公布，只说按吨位另算，这个另算是什么意思不清楚。"),
        para(67, "有人问听证会记录哪里能看，<who>阿桥</who>说市交通局官网有但他没找到下载链接；<who>老周</who>手里有一份从货运行业群里传出来的，不确定是不是完整版，<who>阿桥</who>决定不引用，等官方版本。最后<who>老周</who>提醒收费方案的意见征集到三月三十一号截止；<who>阿桥</who>确认这个日期是通报里写的。"),
    ],
    "quotes": [
        q(S, 64, "老周", "浮桥限重两吨，货车走不了，货车绕行要多跑二十几公里"),
        q(S, 70, "老周", "收费方案的意见征集到三月三十一号截止"),
    ],
    "claims": [
        {"ts": ts(S, 64), "who": "老周", "claim": "北港浮桥限重 2 吨，货车绕行多 20 余公里",
         "quote": "浮桥限重两吨，货车走不了，货车绕行要多跑二十几公里"},
        {"ts": ts(S, 70), "who": "老周", "claim": "意见征集截止 3 月 31 日",
         "quote": "收费方案的意见征集到三月三十一号截止"},
    ],
    "channels": [
        {"ts": ts(S, 68), "who": "老周", "name": "货运行业群流出的听证会记录", "kind": "群聊流出文件",
         "quote": "是从一个货运行业群里传出来的，我不确定是不是完整版"},
    ],
    "asr": [],
}
# `aside` 只出 paras：把是什么事讲清楚，不出锚点 / 说法 / 信源
FRAG_QA = {
    "title": "结尾弹幕与下周预告", "kind": "aside", "line": 73,
    "gist": "回了几条与今天无关的弹幕，下周聊河口老照片。",
    "paras": [para(73, "结尾回了几条与今天话题无关的弹幕：下周聊河口老照片，<who>老周</who>准备了一九八几年的照片。")],
    "quotes": [], "claims": [], "channels": [], "asr": [],
}

# L2 的坏输出（schema 合法、闸门不过）：四处故意违规，见 README
FRAG_MARKET_BAD = copy.deepcopy(FRAG_MARKET)
# 闸门 1：引文被改写（不是逐字）
FRAG_MARKET_BAD["quotes"][1] = {"ts": ts(S, 37), "who": "老周", "text": "我上个月去数过，摊位不到一百个摊"}
# 闸门 2：时间戳跑到话题范围（含前后 2 分钟）之外
FRAG_MARKET_BAD["quotes"][2] = {"ts": "00:10:00", "who": "老周", "text": "四十多处这个数字是消防部门的通报"}
# 闸门 3：claim.quote 带「好像」，对应段落却没有 <hedge>
FRAG_MARKET_BAD["paras"][2] = FRAG_MARKET_BAD["paras"][2].replace("<hedge>好像</hedge>", "好像")
# 闸门 5：asr.heard 在切片里根本不存在（模型编的）
FRAG_MARKET_BAD["asr"] = [{"heard": "冰江路", "means": "滨江路"}]

T = EP92


def para92(n, text):
    return f"[{hms(seg(T, n)['start'])}] {text}"


FRAG_FOLLOWUP = {
    "title": "北港大桥货车费率：一张征求意见函的照片", "kind": "talk", "line": 3,
    "gist": "货运公司收到的征求意见函：货车按轴计费、公司一个月过桥接近三十万、本地企业拟给三成折扣、函比通报晚五天；更正每月前十次免费。",
    "paras": [
        para92(3, "<who>阿桥</who>说一位在货运公司上班的朋友把公司收到的征求意见函拍给了他：货车费率按轴计算，两轴四十块、三轴六十块、四轴以上八十块。他先说明这是征求意见的版本，不是最后定的，而且他只看到了照片。按这个算，一辆四轴货车一天来回两趟三百二十块；朋友说公司一天大概三十辆车过桥，一个月接近三十万，这个数是朋友口头说的，他没看到账。他因此认为货运这边的反对<hedge>应该</hedge>会比直播里估计的还大。"),
        para92(10, "函里还有一条，本地注册的货运企业<hedge>可能</hedge>有百分之三十的折扣，<who>阿桥</who>强调函上用的词是「拟给予」。照片里能看到函是三月十号发的，比通报晚五天，他<hedge>我猜</hedge>是分批征求意见，先公众后企业。有人问要不要把照片发出来，他觉得不合适，那是朋友公司的内部文件，等官方版本出来再对照着讲。"),
        para92(16, "<who>阿桥</who>更正直播里的说法：他说过本地牌照每月前二十次免费，老周说是前十次；下播后查了通报原文，是前十次，老周是对的。以后下播之后来的消息都用加更的方式说，不等下一周。"),
    ],
    "quotes": [
        q(T, 4, "阿桥", "函上写的货车费率是按轴计算，两轴四十块，三轴六十块，四轴以上八十块"),
        q(T, 5, "阿桥", "这个是征求意见的版本，不是最后定的，而且我只看到了照片"),
        q(T, 17, "阿桥", "我下播之后查了通报原文，是前十次，老周是对的，我记错了"),
    ],
    "claims": [
        {"ts": hms(seg(T, 4)["start"]), "who": "阿桥", "claim": "征求意见函：货车按轴计费，2 轴 40 元、3 轴 60 元、4 轴以上 80 元",
         "quote": "函上写的货车费率是按轴计算，两轴四十块，三轴六十块，四轴以上八十块"},
        {"ts": hms(seg(T, 10)["start"]), "who": "阿桥", "claim": "本地注册货运企业拟给予 30% 折扣",
         "quote": "本地注册的货运企业可能有百分之三十的折扣"},
        {"ts": hms(seg(T, 12)["start"]), "who": "阿桥", "claim": "函件日期 3 月 10 日，晚于通报 5 天",
         "quote": "函是三月十号发的，比通报晚了五天"},
        {"ts": hms(seg(T, 17)["start"]), "who": "阿桥", "claim": "通报原文：本地牌照每月前 10 次免费",
         "quote": "我下播之后查了通报原文，是前十次"},
    ],
    "channels": [
        {"ts": hms(seg(T, 3)["start"]), "who": "阿桥", "name": "货运公司收到的征求意见函（照片）", "kind": "企业收到的公函",
         "quote": "把公司收到的征求意见函拍给我了"},
    ],
    "asr": [],
}
FRAG_OPENING92 = {"title": "加更说明", "kind": "aside", "line": 1,
                  "gist": "下播后收到跟大桥收费有关的材料，加更十几分钟。",
                  "paras": [para92(1, "<who>阿桥</who>说下播后有朋友发来跟大桥收费有关的材料，加更十几分钟。")],
                  "quotes": [], "claims": [], "channels": [], "asr": []}
# `filler`：零信息的过场（结尾预告）。模型只交标题与一句 gist，五类内容全空
FRAG_OUTRO92 = {"title": "下周预告与道别", "kind": "filler", "line": 21,
                "gist": "下周老照片那期时间不变，道别。",
                "paras": [], "quotes": [], "claims": [], "channels": [], "asr": []}

# 每章模型交出来的样子：`{"topics": [...]}`，话题按行号先后
L2_MODEL = {
    "EP91": {"bridge": [FRAG_OPENING, FRAG_BRIDGE],
             "market": [FRAG_MARKET, FRAG_FREIGHT, FRAG_QA]},
    "EP92": {"followup": [FRAG_OPENING92, FRAG_FOLLOWUP, FRAG_OUTRO92]},
}

# 字数预算远远不达标的一章：话题、kind、锚点都照旧，只把 paras 砍到目标的十分之一。
# L2 **不为字数设闸门**——为了短而删内容比超预算糟得多，而代码判不了「短是因为写法
# 好还是因为把事删了」，所以这份响应必须照常通过、照常写出片段（长短归 #57 拿真实
# 样例对基线判）。段首那个时间戳照旧，不然会被「每段以 [HH:MM:SS] 开头」拦下
L2_MARKET_SHORT = []
for _t, _short in zip(L2_MODEL["EP91"]["market"],
                      ("夜市要搬。", "货车费率有争议。", "回了弹幕。")):
    _t = copy.deepcopy(_t)
    _t["paras"] = [_t["paras"][0].split("] ", 1)[0] + "] " + _short]
    L2_MARKET_SHORT.append(_t)


# 断言：claims / channels 的 quote 也必须逐字来自某一段（同一话题范围内）
def assert_verbatim(frag, segs):
    texts = [s["text"] for s in segs]
    for c in frag["claims"] + frag["channels"]:
        assert any(c["quote"] in t for t in texts), c["quote"]


for f in (FRAG_BRIDGE, FRAG_MARKET, FRAG_OPENING, FRAG_FREIGHT, FRAG_QA):
    assert_verbatim(f, EP91)
for f in (FRAG_FOLLOWUP, FRAG_OPENING92, FRAG_OUTRO92):
    assert_verbatim(f, EP92)


def topics_product(ep, chapters, by_chapter, segs, names):
    """模型按章交的话题 → 每话题一份 `frag-<id>.json` 的样子（§5.4）。

    程序填的键：`id` = `<章节 id>-NN`（章内按行号先后编号）、`chapter`、`start` /
    `end`（行号换时刻；章内第一个话题从章的 `start` 起，最后一个收在章的 `end`）、
    `who`（话题自己的行里出现过的说话人）。模型写的 `line` 不进产物。
    """
    out = []
    for ch in chapters["chapters"]:
        ts_ = sorted(by_chapter[ch["id"]], key=lambda t: t["line"])
        c0, c1 = (int(x[0:2]) * 3600 + int(x[3:5]) * 60 + int(x[6:8]) for x in (ch["start"], ch["end"]))
        starts = [int(round(seg(segs, t["line"])["start"])) for t in ts_]
        starts[0] = c0
        for i, t in enumerate(ts_):
            end = starts[i + 1] if i + 1 < len(ts_) else c1
            who = []
            for s in segs:
                if starts[i] <= int(round(s["start"])) < end and names[s["speaker"]] not in who:
                    who.append(names[s["speaker"]])
            out.append({"id": f"{ch['id']}-{i + 1:02d}", "chapter": ch["id"],
                        "title": t["title"], "kind": t["kind"],
                        "start": hms(starts[i]), "end": hms(end), "who": who, "gist": t["gist"],
                        **{k: t[k] for k in CONTENT_KEYS}})
    return out


CONTENT_KEYS = ("paras", "quotes", "claims", "channels", "asr")
EP91_FRAGS = topics_product("EP91", EP91_CHAPTERS, L2_MODEL["EP91"], EP91, NAMES)
EP92_FRAGS = topics_product("EP92", EP92_CHAPTERS, L2_MODEL["EP92"], EP92, NAMES)
assert [f["id"] for f in EP91_FRAGS] == ["bridge-01", "bridge-02",
                                         "market-01", "market-02", "market-03"]
assert [f["id"] for f in EP92_FRAGS] == ["followup-01", "followup-02", "followup-03"]


def topics_index(ep, frags):
    """话题表 `topics.json`（§5.3）：各片段去掉五类内容剩下的头，全集按时间排。"""
    return {"ep": ep, "topics": [{k: v for k, v in f.items() if k not in CONTENT_KEYS}
                                 for f in frags]}


EP91_TOPICS = topics_index("EP91", EP91_FRAGS)
EP92_TOPICS = topics_index("EP92", EP92_FRAGS)

# ------------------------------------------------------------------ 事件清单（§5.5）
# 大桥那件事在 EP91 里被夜市打断、成了两个话题：L4 把它们归回同一个事件
EVENTS = {"date": "2026-03-12", "events": [
    {"id": "2026-northbridge-toll", "title": "北港大桥收费方案：定价、货车费率与 2019 年隧道先例",
     "tag": "地方市政 · 交通",
     "refs": [
         {"ep": "EP91", "topic": "bridge-02", "ts": "00:03:30",
          "gist": "通报按车型收费、建议价十五块可能压到十二、贷款三十八亿、2019 隧道先例"},
         {"ep": "EP91", "topic": "market-02", "ts": "00:36:00",
          "gist": "回到大桥：浮桥限重货车绕行、货车费率没公布、意见征集三月三十一号截止"},
         {"ep": "EP92", "topic": "followup-02", "ts": "00:01:00",
          "gist": "货车按轴计费的征求意见函照片、货运公司的账、更正每月前十次"},
     ]},
    {"id": "2026-hekou-night-market", "title": "河口夜市搬迁滨江路：消防倒逼与商户的总账",
     "tag": "地方市政 · 民生",
     "refs": [
         {"ep": "EP91", "topic": "market-01", "ts": "00:19:00",
          "gist": "晚报报道六月底前搬迁、一百二十户之争、四十三处隐患、2016 老码头先例、租金账"},
     ]},
]}
# L4 的坏输出：引用不存在的话题、把 aside 话题聚成事件
EVENTS_BAD = copy.deepcopy(EVENTS)
EVENTS_BAD["events"][1]["refs"].append({"ep": "EP91", "topic": "parking-01", "ts": "00:30:00", "gist": "不存在的话题"})
EVENTS_BAD["events"].append({"id": "2026-hekou-old-photos", "title": "下周老照片", "tag": "预告",
                             "refs": [{"ep": "EP91", "topic": "market-03", "ts": "00:41:30", "gist": "aside 不该成事件"}]})
_known = {(ep, f["id"]) for ep, fs in (("EP91", EP91_FRAGS), ("EP92", EP92_FRAGS)) for f in fs}
assert all((r["ep"], r["topic"]) in _known for e in EVENTS["events"] for r in e["refs"])

# ------------------------------------------------------------------ 落盘：_digest 形状（带 provenance）
# 旧样例按话题 id 起文件名，换了契约之后文件名全变；先清掉，别留孤儿
for _d in ("digest", "raw", "raw-bad", "l3"):
    shutil.rmtree(ROOT / _d, ignore_errors=True)


def prov(layer, unit, derived, engine="claude-sonnet-5", effort="medium", pv="0.1"):
    return {"derived_from": derived, "layer": layer, "unit": unit, "engine": engine,
            "effort": effort, "prompt_version": f"{layer}@{pv}", "generated_at": GEN_AT}


def with_prov(obj, p):
    o = dict(obj)
    o["provenance"] = p
    return o


for ep, chapters, frags, topics in (("EP91", EP91_CHAPTERS, EP91_FRAGS, EP91_TOPICS),
                                    ("EP92", EP92_CHAPTERS, EP92_FRAGS, EP92_TOPICS)):
    wjson(ROOT / f"digest/{ep}/chapters.json",
          with_prov(chapters, prov("L1", "all", [f"{ep}.transcript.json"], effort="low")))
    for f in frags:
        # 一章一次调用，`unit` 是章节 id；同一章的几个片段 provenance 相同
        wjson(ROOT / f"digest/{ep}/frag-{f['id']}.json",
              with_prov(f, prov("L2", f["chapter"], [f"{ep}.transcript.json", "chapters.json"])))
    # 话题表是 L2 收尾时代码拼的索引，不是哪一次调用的产物
    wjson(ROOT / f"digest/{ep}/topics.json",
          with_prov(topics, prov("L2", "all", ["chapters.json", "frag-*.json"])))
wjson(ROOT / "digest/2026-03-12/events.json", with_prov(EVENTS, prov("L4", "all", ["EP91/topics.json", "EP91/frag-*.json", "EP92/topics.json", "EP92/frag-*.json", "30-Events/*.md"])))

# 闸门用的坏片段：解析后产物的形状（顶替 `_digest/EP91/frag-market-01.json`）
_market = next(f for f in EP91_FRAGS if f["id"] == "market-01")
wjson(ROOT / "l3/frag-market-01.bad.json",
      {**_market, **{k: FRAG_MARKET_BAD[k] for k in CONTENT_KEYS}})


# ------------------------------------------------------------------ 假 claude 原始响应（--output-format json 的信封）
def envelope(obj_or_text, model="claude-sonnet-5", in_tok=9000, out_tok=1800, bad_text=None,
             structured=True):
    """好响应按 `--json-schema` 的真实形状：`structured_output` 是已解析的对象，
    `result` 是同一份 JSON 的字符串。坏响应只有 `result`（围栏里的 JSON 或散文）
    ——真实 CLI 不会放一份不合 schema 的 `structured_output` 出来，坏输出只可能
    来自没给 schema 的旧存档，走的是从文字里挖 JSON 那条路。
    """
    if bad_text is not None:
        result, structured = bad_text, False
    elif structured:
        result = json.dumps(obj_or_text, ensure_ascii=False)
    else:
        result = "```json\n" + json.dumps(obj_or_text, ensure_ascii=False, indent=2) + "\n```"
    cost = round(in_tok * 3e-6 + out_tok * 1.5e-5, 4)
    env = {
        "type": "result", "subtype": "success", "is_error": False,
        "duration_ms": 41000, "duration_api_ms": 39000, "num_turns": 2 if structured else 1,
        "stop_reason": "end_turn",
        "result": result, "session_id": "synthetic-fixture-session",
        "total_cost_usd": cost,
        "usage": {"input_tokens": in_tok, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0,
                  "output_tokens": out_tok},
        "modelUsage": {model: {"inputTokens": in_tok, "outputTokens": out_tok, "cacheReadInputTokens": 0,
                               "cacheCreationInputTokens": 0, "webSearchRequests": 0, "costUSD": cost,
                               "contextWindow": 200000, "maxOutputTokens": 64000}},
        "permission_denials": [], "uuid": "00000000-0000-4000-8000-000000000091",
    }
    if structured:
        env["structured_output"] = obj_or_text
    return env


wjson(ROOT / "raw/EP91/L1-all.raw.json", envelope(EP91_CHAPTERS_MODEL, in_tok=6000, out_tok=600))
wjson(ROOT / "raw/EP92/L1-all.raw.json", envelope(EP92_CHAPTERS_MODEL, in_tok=1500, out_tok=300))
for ep, by_chapter in L2_MODEL.items():
    for cid, ts_ in by_chapter.items():
        wjson(ROOT / f"raw/{ep}/L2-{cid}.raw.json", envelope({"topics": ts_}))
wjson(ROOT / "raw/2026-03-12/L4-all.raw.json", envelope(EVENTS, in_tok=4000, out_tok=500, structured=False))

wjson(ROOT / "raw-bad/EP91/L1-all.raw.json",
      envelope(EP91_CHAPTERS_BAD, in_tok=6000, out_tok=600, structured=False))
wjson(ROOT / "raw-bad/EP91/L2-market.raw.json", envelope({"topics": [FRAG_MARKET_BAD]}, structured=False))
wjson(ROOT / "raw-bad/EP91/L2-bridge.raw.json", envelope(None, bad_text="这一章开头全是寒暄，我没法按要求整理，建议合并到后一章。"))
# 这一份 schema 合法、结构也合法，坏的只是字数——所以带 structured_output，跟好响应一样
wjson(ROOT / "raw-bad/EP91/L2-market-short.raw.json", envelope({"topics": L2_MARKET_SHORT}, out_tok=300))
wjson(ROOT / "raw-bad/2026-03-12/L4-all.raw.json", envelope(EVENTS_BAD, in_tok=4000, out_tok=500, structured=False))

# ------------------------------------------------------------------ README
README = f"""# tests/fixtures — 合成样例

**全部内容虚构**（红线 10）：UP 主「河口夜话」、河口市、北港大桥、河口夜市、阿桥、老周都是编的，
不是任何真实直播的转写或改写。生成脚本的对白表是唯一事实来源；引文已由生成脚本断言为
某一段的连续子串，时间戳由段起点计算。改样例请改脚本重生成，不要手改 JSON。

## 布局

| 路径 | 是什么 | 对应 SPEC |
|---|---|---|
| `vault/` | 迷你 vault：两集逐字稿、两张 EP 笔记、一张已存在的事件笔记 | §5.1、§6.1、§5.8 |
| `vault/_assets/EP91.transcript.json` | 42:40，两位说话人，76 段；含一处 ASR 生音「北岗大桥」 | §5.1 |
| `vault/_assets/EP92.transcript.json` | 14:00，单说话人，22 段；同日加更，谈同一事件 | §5.1 |
| `vault/10-Episodes/EP91 ….md` | 没有 `整理:` 字段（仿现网旧笔记），带 `## 断言` `## 待办` 旧节 | §6.1 |
| `vault/10-Episodes/EP92 ….md` | 有 `整理: pending` | §6.1 |
| `vault/30-Events/2026-northbridge-toll.md` | first_seen 2026-03-05，「我的判断」有人写的内容 | §5.8 |
| `digest/EP91/`、`digest/EP92/` | L1 章节表 `chapters.json`、L2 片段 `frag-<话题>.json` 与话题表 `topics.json` 的**解析后产物**形状（带 `provenance`） | §5.3、§5.4、§9 |
| `digest/2026-03-12/events.json` | L4 事件清单：跨 EP 合并、同一 EP 内被打断的同一事件合并、沿用已有事件 id | §5.5 |
| `l3/frag-market-01.bad.json` | 故意违规的片段：闸门 1（引文改写）、2（时间戳越界）、3（丢 hedge）、5（asr.heard 不存在） | §4 L3 |
| `raw/<EP 或日期>/<层>-<单元>.raw.json` | 假 `claude -p --output-format json` 信封；L1 / L2 带 `structured_output`（`--json-schema` 的形状），L4 的 `result` 是围栏 JSON | §4.1 |
| `raw-bad/…` | 坏响应（多数只有 `result`）：L1 行号不在这一集里 + 缺 title；L2 闸门违规；L2 纯散文无 JSON；L2 正文只有字数预算的十分之一（`L2-market-short`，schema 合法故带 `structured_output`，L2 不为字数设闸门）；L4 引用不存在话题 + aside 成事件 | §4.1 |

`raw/` 的键与 `_pairs/` 的文件名一致：`_pairs/EP91/L2-bridge.in.md` ↔ `raw/EP91/L2-bridge.raw.json`。
L2 的单元是**章节**：一章一次调用，响应里是这一章的全部话题。假 runner 按这个键取响应，缺键即报错（不是静默跳过）。

## 章节与话题速查

| 集 | 章节（L1） | 章内话题（L2，`id` 由程序按 `<章节>-NN` 编） |
|---|---|---|
| EP91 | `bridge` 00:00:00–00:19:00 | `bridge-01` 开场（`filler`）、`bridge-02` 大桥收费（`talk`） |
| EP91 | `market` 00:19:00–00:42:40 | `market-01` 夜市搬迁（`talk`）、`market-02` 回到大桥（`talk`）、`market-03` 结尾弹幕（`aside`） |
| EP92 | `followup` 00:00:00–00:14:00 | `followup-01` 加更说明（`aside`）、`followup-02` 货车费率（`talk`）、`followup-03` 下周预告（`filler`） |

EP91 的 L1 响应里模型切了三章（`bridge` / `market` / `bridge-again`），第三章只有 6 分 40 秒，
程序把它并进 `market`（标题用顿号接、gist 顺序接），所以章节表里是两章、L2 调两次。
大桥那件事在 EP91 里被夜市打断，落在 `bridge-02` 与 `market-02` 两个话题里，L4 把它们归回同一个事件。

## 行号速查（EP91）

两集的段都比 30 秒长，所以 §5.2 文本的第 n 行就是对白表的第 n 段。行号 → 时间戳：第 7 行 {ts(EP91, 7)}，
第 11 行 {ts(EP91, 11)}，第 21 行 {ts(EP91, 21)}（ASR 生音所在行），第 35 行 {ts(EP91, 35)}，第 63 行 {ts(EP91, 63)}，第 73 行 {ts(EP91, 73)}。
"""
wtext(ROOT / "README.md", README)
print("FIXTURES OK", ROOT)
