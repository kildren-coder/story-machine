# -*- coding: utf-8 -*-
"""sm — story-machine 流水线的共用件（stdlib only，Python ≥ 3.11）。

一层一个无头调用（ADR 0004），所以每层的脚本只剩「读输入 → 调 runner → 校验 →
落产物」四步；这四步的机械部分全在这个包里，层自己只写 prompt、schema 检查和
渲染。

  text        时间戳与文本归一
  note        EP 笔记：frontmatter 与点名（读 + 只改两个键）
  paths       vault 下各目录的位置（SPEC §4.1 文件位置、§6）
  transcript  逐字稿正本 → 喂给模型的文本（SPEC §5.1 → §5.2）
  runner      无头调用的三种实现：真实 claude / 重放 / 测试假货
  pairs       三份留档 + 重试 + `_failed/`（SPEC §4.1、红线 9）
  prov        provenance（SPEC §9）与 prompt 版本
"""
