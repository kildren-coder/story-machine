# -*- coding: utf-8 -*-
"""L1 的机械检查与 prompt（issue #51 验收 7、12）。

`check_topics` 是红线 9 的入口：它判不过的单元会被拦进 `_failed/`，所以它宁可
啰嗦也不能放水；但它**只判形状**，一个字都不许改（红线 2）。

时间这一侧只剩三条检查——起点照抄自行首、第一个是第一行、严格递增。零长度、
倒置、空洞、重叠、越界这五类曾经最常见的错误已经**在结构上不可能发生**：模型
不再写终点，终点由 `with_ends` 接上。
"""
from __future__ import annotations

import re

from conftest import REPO
from sm.l1 import build_input, check_topics, line_starts, with_ends
from sm.prov import read_prompt

PROMPT = REPO / "prompts" / "L1-skeleton.md"
DUR = 600                                              # 10:00 的一集
# 逐字稿每 30 秒一行，所以行首时间戳就是这些；`start` 只能从里面挑
STARTS = [f"00:{m:02d}:{s:02d}" for m in range(10) for s in (0, 30)]


def topics(*starts: str) -> dict:
    out = []
    for n, st in enumerate(starts, 1):
        out.append({"id": f"t{n}", "title": f"话题{n}", "kind": "talk" if n % 2 else "aside",
                    "start": st, "who": ["阿桥"], "gist": f"概要{n}"})
    return {"topics": out}


def errs(obj, starts: list[str] | None = None) -> str:
    return "\n".join(check_topics(obj, DUR, starts if starts is not None else STARTS))


def test_copied_starts_pass():
    assert check_topics(topics("00:00:00", "00:05:00"), DUR, STARTS) == []


def test_start_must_be_a_line_head():
    """自己算出来的时刻一律不认——`start` 只能是复制来的。"""
    e = errs(topics("00:00:00", "00:03:07"))
    assert "不是逐字稿里出现过的行首时间戳" in e and "00:03:07" in e


def test_a_near_miss_is_told_which_line_head_it_meant():
    """差一秒、或者写成 MM:SS 的，报错要带上最近那个行首——看见正确答案就能
    一次改对，不必再赌下一趟（一趟就是整集逐字稿重发一遍）。"""
    assert "最近的一个是 00:05:00" in errs(topics("00:00:00", "00:05:01"))
    # 连时刻都算不出来的（漏了小时位、乱写）就没有「最近」可言，只报不合法
    e = errs(topics("00:00:00", "05:00"))
    assert "不是逐字稿里出现过的行首时间戳" in e and "最近的一个是" not in e


def test_first_topic_starts_at_the_first_line():
    """开头漏掉一段就等于整集少讲一块，红线 2 不删事。"""
    assert "必须是第一行的 00:00:00" in errs(topics("00:00:30", "00:05:00"))


def test_starts_must_strictly_increase():
    assert "不晚于上一个话题的起点" in errs(topics("00:00:00", "00:05:00", "00:02:00"))
    # 两个话题共用一个起点也是不递增：那样推出来的话题长度会是 0
    assert "不晚于上一个话题的起点" in errs(topics("00:00:00", "00:05:00", "00:05:00"))


def test_ends_are_derived_so_the_chain_can_never_break():
    """`with_ends` 接出来的链：首尾相接、无缝、无重叠、无零长度。

    这一条是整套改造的理由——从前模型要手写 2N 个时间戳、其中 N-1 对必须两两
    相等，实测五次真跑四次挂在这上面；现在它只写 N 个、而且是复制来的。
    """
    ts = with_ends(topics("00:00:00", "00:05:00", "00:07:30")["topics"], DUR)
    assert [t["end"] for t in ts] == ["00:05:00", "00:07:30", "00:10:00"]
    for a, b in zip(ts, ts[1:]):
        assert a["end"] == b["start"]                  # 缝永远是 0
    assert all(t["start"] < t["end"] for t in ts)      # 零长度不可能


def test_line_starts_reads_the_text_actually_sent():
    """行首集合从实际发出去的那份文本里数，不另算一遍。"""
    segs = [{"start": 0.0, "end": 20.0, "speaker": "SPEAKER_00", "text": "开场"},
            {"start": 40.0, "end": 90.0, "speaker": "SPEAKER_00", "text": "正题"}]
    text = build_input("EP02", segs, {"SPEAKER_00": "瓜哥"})
    assert line_starts(text) == ["00:00:00", "00:00:40"]
    assert check_topics(topics("00:00:00", "00:00:40"), 90, line_starts(text)) == []


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


def test_duplicate_id():
    obj = topics("00:00:00", "00:05:00")
    obj["topics"][1]["id"] = obj["topics"][0]["id"]
    assert "`id` 重复" in errs(obj)


def test_shape_errors():
    assert check_topics([], DUR, STARTS) == ["顶层不是对象"]
    assert "`topics` 不是非空数组" in "\n".join(check_topics({}, DUR, STARTS))


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
