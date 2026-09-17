# -*- coding: utf-8 -*-
"""L1 的机械检查与 prompt（issue #51 验收 7、12）。

`check_topics` 是红线 9 的入口：它判不过的单元会被拦进 `_failed/`，所以它宁可
啰嗦也不能放水；但它**只判形状**，一个字都不许改（红线 2）。

时间这一侧只剩两条检查——起点读得出、不超过时长。倒置、空洞、重叠、越界
这几类曾经最常见的错误已经**在结构上不可能发生**：模型不再写终点，终点由
`with_ends` 接上。格式松紧由 `read_start` 兜住，顺序由 `with_ends` 排好，首个
起点归零，两个话题起点相同也算过，都不打回重跑。
"""
from __future__ import annotations

import re

from conftest import REPO
from sm.l1 import build_input, check_topics, out_of_order, read_start, tidy, with_ends
from sm.prov import read_prompt

PROMPT = REPO / "prompts" / "L1-skeleton.md"
DUR = 600                                              # 10:00 的一集


def topics(*starts) -> dict:
    out = []
    for n, st in enumerate(starts, 1):
        out.append({"id": f"t{n}", "title": f"话题{n}", "kind": "talk" if n % 2 else "aside",
                    "start": st, "who": ["阿桥"], "gist": f"概要{n}"})
    return {"topics": out}


def errs(obj) -> str:
    return "\n".join(check_topics(obj, DUR))


def test_ordered_starts_pass():
    assert check_topics(topics("00:00:00", "00:05:00"), DUR) == []


def test_a_start_between_two_lines_is_fine():
    """行首每 30 秒才有一个（ASR 段长中位 29.9 秒），模型想切的地方常在两行
    之间。**逼它照抄行首只会逼出编造的时间戳**——EP03 上两轮都写了输入里
    根本没有的 00:18:13。差几秒无所谓：链条照样由 `with_ends` 闭合。"""
    assert check_topics(topics("00:00:00", "00:03:07"), DUR) == []


def test_a_timestamp_missing_its_hour_is_read_not_rejected():
    """EP03 实测写过 ['03:34', '05:09']。这种能读懂，就别打回整集重跑。"""
    assert read_start("05:09") == 309 and read_start("00:05:09") == 309
    assert check_topics(topics("00:00:00", "05:09"), DUR) == []
    assert read_start("胡写") is None
    assert "读不出时刻" in errs(topics("00:00:00", "胡写"))


def test_a_start_past_the_duration_is_rejected():
    """EP01 实测把另一集的时长 03:10:43 写了进来（本集只有 02:21:26）。
    这个必须拦：它不是精度问题，是时间戳根本不来自这一集。"""
    assert "超过整集时长" in errs(topics("00:00:00", "00:11:00"))


def test_out_of_order_topics_are_sorted_not_rejected():
    """EP01 上模型把 00:49:35 那个回头再谈的话题按主题挪到了 00:36:29 那个旁边，
    中间三个话题排到了它后面。时间戳全对（628 个起点里没有一个离谱手误），
    只是列表顺序错了——顺序是代码能归一的，打回只会白烧一趟。"""
    obj = topics("00:00:00", "00:05:00", "00:02:00", "00:08:00")
    assert check_topics(obj, DUR) == []
    assert out_of_order(obj["topics"]) == 2
    ts = with_ends(obj["topics"], DUR)
    assert [t["id"] for t in ts] == ["t1", "t3", "t2", "t4"]
    assert [t["end"] for t in ts] == ["00:02:00", "00:05:00", "00:08:00", "00:10:00"]
    assert ts[1]["title"] == "话题3"                    # 只挪位置，一个字不改
    assert out_of_order(topics("00:00:00", "00:05:00")["topics"]) == 0


def test_two_topics_on_one_line_may_share_a_start():
    """起点制以来 8 轮里 3 轮写了两个一样的起点（EP01 的 00:32:41、EP03 的
    00:00:33）：两件事挤在同一行里，行首每 30 秒才一个，它没有别的时刻可写。
    这不是它写错，打回只会白烧一趟。前一个话题长度为 0，链条照样闭合。"""
    obj = topics("00:00:00", "00:05:00", "00:05:00", "00:08:00")
    assert check_topics(obj, DUR) == []
    ts = with_ends(obj["topics"], DUR)
    assert (ts[1]["start"], ts[1]["end"]) == ("00:05:00", "00:05:00")
    assert (ts[2]["start"], ts[2]["end"]) == ("00:05:00", "00:08:00")
    for a, b in zip(ts, ts[1:]):
        assert a["end"] == b["start"]


def test_ends_are_derived_so_the_chain_can_never_break():
    """`with_ends` 接出来的链：首尾相接、无缝、无重叠、无零长度。

    这一条是整套改造的理由——从前模型要手写 2N 个时间戳、其中 N-1 对必须两两
    相等，三集九次实测挂了三次；现在它只写 N 个，而且写偏了也不要紧。
    """
    ts = with_ends(topics("00:00:00", "00:05:00", "00:07:30")["topics"], DUR)
    assert [t["end"] for t in ts] == ["00:05:00", "00:07:30", "00:10:00"]
    for a, b in zip(ts, ts[1:]):
        assert a["end"] == b["start"]                  # 缝永远是 0
    assert all(t["start"] < t["end"] for t in ts)      # 起点各不相同时没有零长度


def test_with_ends_normalises_the_head_and_the_format():
    """首个起点归零、MM:SS 补成 HH:MM:SS——产物里的时间戳形状是一致的。"""
    ts = with_ends(topics("00:00:20", "05:09")["topics"], DUR)
    assert ts[0]["start"] == "00:00:00"                # 开头那 20 秒并进第一个话题
    assert ts[1]["start"] == "00:05:09" and ts[0]["end"] == "00:05:09"


def test_field_and_type_errors():
    obj = topics("00:00:00")
    t = obj["topics"][0]
    t["id"] = "Bridge Toll"
    t["kind"] = "talking"
    t["who"] = "阿桥"
    del t["gist"]
    e = errs(obj)
    assert "^[a-z0-9-]+$" in e and "`kind`" in e and "`who` 不是字符串数组" in e
    assert "缺字段 `gist`" in e


def test_an_id_with_a_capital_letter_is_lowercased_not_rejected():
    """haiku 写过 `eric-Adams-mandela`。`id` 是机器键不是人读的字，一个大写字母
    不该让整集重发一趟；归一完还不合规的（中文、标点）照样拦。"""
    obj = topics("00:00:00", "00:05:00")
    obj["topics"][0]["id"] = "eric-Adams mandela"
    obj["topics"][1]["id"] = "Bridge_Toll"
    tidied = tidy(obj)
    assert [t["id"] for t in tidied["topics"]] == ["eric-adams-mandela", "bridge-toll"]
    assert check_topics(tidied, DUR) == []
    assert obj["topics"][0]["id"] == "eric-Adams mandela"          # 不改原对象
    obj["topics"][0]["id"] = "大桥"
    assert "不匹配" in "\n".join(check_topics(tidy(obj), DUR))


def test_duplicate_id():
    obj = topics("00:00:00", "00:05:00")
    obj["topics"][1]["id"] = obj["topics"][0]["id"]
    assert "`id` 重复" in errs(obj)


def test_shape_errors():
    assert check_topics([], DUR) == ["顶层不是对象"]
    assert "`topics` 不是非空数组" in "\n".join(check_topics({}, DUR))


def test_prompt_version_and_schema_in_body():
    """验收 12：首行版本号形状 + 正文写清六个键与三档 kind。"""
    text = PROMPT.read_bytes().decode("utf-8")
    first = text.splitlines()[0]
    assert re.match(r"^version: L1-skeleton@\d+\.\d+$", first)
    for key in ("id", "title", "kind", "start", "who", "gist",
                "talk", "aside", "filler"):
        assert key in text, key
    # 版本号不钉死：打磨期它每改一版就升一次（#57），钉死只会逼人改测试
    assert read_prompt(PROMPT)["version"] == first.split(": ", 1)[1]
    assert len(read_prompt(PROMPT)["sha8"]) == 8


def test_prompt_does_not_ask_for_what_the_code_already_knows():
    """终点与集号由程序填。prompt 里再提，模型就又会去写，又多一处会错的地方。"""
    text = PROMPT.read_bytes().decode("utf-8")
    assert "只写起点，不写终点" in text
    assert "ranges" not in text
    # 「不能写同一个时刻」这条禁令模型照样违反，只会让它二选一丢掉一个话题
    assert "不能写同一个时刻" not in text


def test_title_that_would_break_the_marker_block():
    """标题 / gist 原样进标记块，所以换行与 HTML 注释在检查时就得拦下。"""
    obj = topics("00:00:00")
    obj["topics"][0]["title"] = "两行\n标题"
    assert "撑破标记块" in errs(obj)

    obj = topics("00:00:00")
    obj["topics"][0]["gist"] = "收尾 <!-- /digest -->"
    assert "撑破标记块" in errs(obj)


def test_head_puts_only_the_ep_id_on_the_episode_line():
    """头一行一个键：`episode:` 那行只有集号。

    挤成一行（`episode: EP02 · 时长 … · 说话人 …`）的时候，模型把整行抄进了
    `ep`，EP02 上连挂两次、两次都重发了整集逐字稿。歧义要消在输入里，不是靠
    prompt 多写一句话求它别抄错。
    """
    segs = [{"start": 0.0, "end": 61.0, "speaker": "SPEAKER_00", "text": "开场"}]
    lines = build_input("EP02", segs, {"SPEAKER_00": "瓜哥"}).splitlines()
    assert lines[0] == "episode: EP02"
    assert lines[1].startswith("时长: ")
    assert lines[2].startswith("说话人: ")
    # 集号那行不许挂别的东西——挂了就又有歧义了
    assert "·" not in lines[0] and "时长" not in lines[0]
