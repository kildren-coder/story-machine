#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PROTOTYPE — 用完即弃，不要进主干。

生成 proto-vault 里两类「必须由程序精确控制」的内容：

  1. _lab/A-语法矩阵样本.md
     缩进本身就是被测变量（4空格 / Tab / 2空格 / 零缩进 / 嵌套 list）。
     手写 markdown 无法保证字节级精确，所以由脚本生成。

  2. 10-Episodes/bulk/EPxxx.md
     规模实验用的合成断言行。默认不生成（实验 A/B 不需要），
     跑 `--bulk` 才产出，看完 `--clean` 删掉。

用法：
    python build.py                # 只写 A 样本
    python build.py --bulk 100     # 追加 100 集 × 30 行 = 3000 行
    python build.py --clean        # 删掉 bulk
"""

import argparse
import random
import shutil
from pathlib import Path

VAULT = Path(__file__).parent / "proto-vault"
LAB = VAULT / "_lab"
BULK = VAULT / "10-Episodes" / "bulk"

# ---------------------------------------------------------------- 实验 A

# 一条断言的字段体，各变体共用；差别只在「怎么把它们贴到 list item 上」
FIELDS = [
    ("type", "causal"),
    ("情态", "确定"),
    ("谁说的", "主播"),
    ("录音时间戳", "00:29:00"),
    ("事件时间", "2001-09-11"),
    ("事件时间精度", "day"),
    ("cause", "911 之后小布什在相当一段时间里非常害怕自己被斩首"),
    ("effect", "需要一个非正式小圈子，在正式指挥链断掉时仍能就政治经济事务做决策"),
    ("实体", "[[小布什]], [[美国国会八人帮]]"),
    ("主题", "总统权力, 战时授权"),
]

TEXT = "911 后小布什长期担心被斩首，因此设立八人帮作为指挥「备份」"


def variant(probe: str, style: str) -> str:
    """probe 用纯 ASCII 键，保证探针本身一定能被解析——
    这样即使中文键失败，行仍会出现在结果表里（只是列为空），
    而不是整行消失导致「失败」和「没写」分不清。"""
    head = f"- **{probe}** {TEXT} [probe:: {probe}]"
    if style == "one-line":
        inline = " ".join(f"[{k}:: {v}]" for k, v in FIELDS)
        return f"- **{probe}** {TEXT} [probe:: {probe}] {inline}\n"
    pad = {"sp4": "    ", "sp2": "  ", "tab": "\t", "none": ""}.get(style)
    if pad is not None:
        body = "".join(f"{pad}{k}:: {v}\n" for k, v in FIELDS)
        return head + "\n" + body
    if style == "nested":
        body = "".join(f"    - {k}:: {v}\n" for k, v in FIELDS)
        return head + "\n" + body
    raise ValueError(style)


VARIANTS = [
    ("V1", "sp4", "四空格续行 —— **SPEC §5.1 现方案**，成败在此一举"),
    ("V2", "tab", "Tab 续行 —— 有些编辑器会自动这么缩，得知道它等不等价"),
    ("V3", "sp2", "两空格续行 —— 缩进量是否敏感"),
    ("V4", "none", "零缩进续行 —— 大概率把字段甩给了整个页面而不是这一行；"
                   "危险在于它「看起来是对的」，人手写时很容易掉进去"),
    ("V5", "nested", "嵌套 list item —— 字段会各自成为独立的 list 条目，"
                     "父行本身多半是空的。若成立，代价是一条断言变成 11 个 list 条目"),
    ("V6", "one-line", "全挤一行括号式 —— SPEC 点名的退路。丑，但几乎不可能失败"),
]


def write_lab_a() -> None:
    LAB.mkdir(parents=True, exist_ok=True)
    out = [
        "---",
        "note: PROTOTYPE 样本，由 build.py 生成，不要手改",
        "---",
        "",
        "# 实验 A · 语法矩阵样本",
        "",
        "> 六种写法承载**完全相同**的一条断言。判读见 `_queries/A-语法矩阵结果.md`。",
        "> 每行首个字段 `[probe:: Vx]` 是纯 ASCII 括号式，**保证可解析**——",
        "> 它的作用是让失败的变体也留在结果表里（列空），而不是整行消失。",
        "",
    ]
    for probe, style, desc in VARIANTS:
        out += [f"## {probe} — {desc}", "", variant(probe, style)]
    (LAB / "A-语法矩阵样本.md").write_text("\n".join(out), encoding="utf-8")
    print(f"写入 {LAB / 'A-语法矩阵样本.md'}")


# ---------------------------------------------------------------- 规模实验

ENTITIES = ["小布什", "特朗普", "汤姆·科顿", "马克·华纳", "查克·舒默", "美联储",
            "美国财政部", "美国国会八人帮", "英国央行", "欧洲央行", "DSA", "北约"]
TOPICS = ["美债", "资金流向", "总统权力", "战时授权", "财政军事国家",
          "选举政治", "货币政策", "地缘冲突"]
TYPES = ["fact"] * 12 + ["causal"] * 8 + ["prediction"] * 5 + \
        ["judgment"] * 3 + ["channel"] * 2


def bulk_row(i: int, rng: random.Random) -> str:
    """V6 括号式单行 + 主题重复 key —— 唯一被实验 A/B 验证过能用的写法。
    旧版用四空格续行 + 逗号分隔主题，已被 A/B 推翻，字段全挂不上、主题也不会解析成数组。"""
    t = rng.choice(TYPES)
    ents = ", ".join(f"[[{e}]]" for e in rng.sample(ENTITIES, rng.randint(1, 3)))
    tops = rng.sample(TOPICS, rng.randint(1, 2))
    ts = f"{rng.randint(0, 2):02d}:{rng.randint(0, 59):02d}:{rng.randint(0, 59):02d}"
    fields = [
        ("type", t),
        ("情态", rng.choice(['确定', '推测', '传闻'])),
        ("谁说的", "主播"),
        ("归因类型", "无外部归因"),
        ("录音时间戳", ts),
    ]
    if rng.random() < 0.7:   # 三成没有事件时间，用来看 null 在排序里沉哪儿
        y = rng.randint(1690, 2026)
        fields += [("事件时间", f"{y}-{rng.randint(1,12):02d}-{rng.randint(1,28):02d}"),
                   ("事件时间精度", "day")]
    else:
        fields += [("事件时间", ""), ("事件时间精度", "未知")]
    if t == "causal":
        fields += [("cause", "合成原因，写得啰嗦一点以模拟真实长度和换行压力"),
                   ("effect", "合成结果，同样写长一些，让表格列宽的手感接近真实情况")]
    if t == "prediction":
        fields += [("时限类型", "事件锚定"), ("时限规范", "null"),
                   ("应验判据原文", "合成判据"), ("检验状态", "待检验")]
    if t == "channel":
        fields += [("渠道类型", "数据源"), ("名称", f"合成数据源 {i}"),
                   ("取数地址", "某张月度表"), ("链接", ""),
                   ("原话口径", "合成口径"), ("为什么值得看", "合成理由")]
    fields += [("实体", ents)]
    inline = " ".join(f"[{k}:: {v}]" for k, v in fields)
    topic_inline = " ".join(f"[主题:: {top}]" for top in tops)
    tail = f"[source_quote:: 合成引文 {i}，用于占位。] [合成:: 是]"
    head = f"- **A-{i:02d}** 合成断言 {i}，仅用于规模测试，内容无意义但字段形状真实"
    return f"{head} {inline} {topic_inline} {tail}\n"


def write_bulk(n_eps: int, rows_per_ep: int = 30) -> None:
    BULK.mkdir(parents=True, exist_ok=True)
    rng = random.Random(42)
    for ep in range(2, 2 + n_eps):
        body = [
            "---", "type: episode", f"episode: EP{ep:03d}",
            f"title: 合成集 {ep:03d}", f"播出日期: 2026-{(ep % 12) + 1:02d}-15",
            "合成: true",
            "---", "",
            f"# EP{ep:03d} 合成集（PROTOTYPE 规模测试用，看完即删）", "",
            "## 断言表", "",
        ]
        body += [bulk_row(i, rng) for i in range(1, rows_per_ep + 1)]
        (BULK / f"EP{ep:03d}.md").write_text("\n".join(body), encoding="utf-8")
    print(f"写入 {n_eps} 集 × {rows_per_ep} 行 = {n_eps * rows_per_ep} 行 → {BULK}")


def clean() -> None:
    if BULK.exists():
        shutil.rmtree(BULK)
        print(f"已删除 {BULK}")
    else:
        print("bulk 目录不存在，无需清理")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--bulk", type=int, metavar="N", help="生成 N 集合成断言（每集 30 行）")
    p.add_argument("--rows", type=int, default=30, help="每集行数，默认 30")
    p.add_argument("--clean", action="store_true", help="删除 bulk 目录")
    a = p.parse_args()
    if a.clean:
        clean()
    else:
        write_lab_a()
        if a.bulk:
            write_bulk(a.bulk, a.rows)
