# Architecture Decision Records

This directory holds the decisions that shaped the project's design and, above all, the **reversals**: when a red line or a product shape was overturned, the ADR is where the reasoning survives after the spec has been rewritten. `SPEC.md` says what the system is; an ADR says why it stopped being something else.

## Format

Each ADR is a markdown file named `NNNN-kebab-case-title.md` with:

```markdown
# NNNN. Decision Title

**Date:** YYYY-MM-DD  
**Status:** Accepted | Pending | Superseded

## Context
[Problem or situation that prompted the decision]

## Decision
[What we chose to do, stated clearly]

## Rationale
[Why this choice, trade-offs considered]

## Consequences
[Implications: what becomes easier, harder, or different]

## Related
[Links to related ADRs, issues, or CONTEXT.md sections]
```

Later findings go into the existing ADR as dated additions under **Consequences** (see 0001), not into a new file, as long as the decision itself still stands.

## Current ADRs

- [0001. 时间戳跳播自研 Obsidian 插件](0001-时间戳跳播自研插件.md) — 现成的 `timestamp-player` 按 DOM 位置绑音频，跨集必然静默播错集；`HH:MM:SS` 还会静默错 60 倍。
- [0002. 队列笔记即状态机，worker 只是执行器](0002-队列笔记即状态机.md) — 状态落在 `_pipeline/队列.md` 里换来崩溃可续跑，进度显示白来（Obsidian 自己重载文件），插件与 worker 之间零 IPC。
- [0003. 日报取代断言表](0003-日报取代断言表.md) — 产物从断言表改成按事件读的日报；每日人工审核闸门取消，人只在周末确认；被删掉的「判真假」层以受约束的形式回归。
- [0004. 分层无头流水线](0004-分层无头流水线.md) — 一层一个无头调用，前一层输出是后一层输入；每层单独定 model 与 effort；机械闸门在代码里，不让模型自己核对。

Existing high-level rationales live in CONTEXT.md; ADRs capture deeper design choices.

---

For more on ADR format, see [adr.github.io](https://adr.github.io/).
