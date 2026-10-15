# -*- coding: utf-8 -*-
"""生成 `scripts/sm/data/pinyin.tsv`：单字 → 无声调拼音，给词表预扫（拼音相近）用。

    python scripts/mk_pinyin_table.py

只在出题侧的机器上跑（要装 pypinyin）；沙箱与流水线只读生成出的表，不 import pypinyin。
范围：CJK 统一表意文字基本区 U+4E00–U+9FFF 加「〇」。多音字取 pypinyin 的第一读音——
预扫两边（词表的规范写法、逐字稿的窗口）走同一张表，同一个字永远映射到同一个音，
够判「读音相近」；pypinyin 认不出的字不写进表，读表的一方把这种字当成它自己。
"""
import sys
from pathlib import Path

import pypinyin
from pypinyin import Style, pinyin

OUT = Path(__file__).resolve().parent / "sm" / "data" / "pinyin.tsv"


def main() -> int:
    rows = []
    for cp in [*range(0x4E00, 0xA000), 0x3007]:
        ch = chr(cp)
        p = pinyin(ch, style=Style.NORMAL, heteronym=False, errors=lambda x: [""])[0][0]
        if p and p != ch:
            rows.append(f"{ch}\t{p}\n")
    head = (f"# 单字<TAB>无声调拼音；由 scripts/mk_pinyin_table.py 用 pypinyin {pypinyin.__version__}"
            "（MIT）生成，多音字取第一读音；以 # 开头的行是注释\n")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(head + "".join(rows), encoding="utf-8", newline="\n")
    print(f"{OUT}: {len(rows)} 字, {OUT.stat().st_size} 字节")
    return 0


if __name__ == "__main__":
    sys.exit(main())
