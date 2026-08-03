# Architecture Decision Records

This directory holds decisions that shaped the project's design: why Gemini Flash for extraction, the hotwords mechanism, chunk size tradeoffs, cost optimization, etc.

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

## Current ADRs

- [0001. 时间戳跳播自研 Obsidian 插件](0001-时间戳跳播自研插件.md) — 现成的 `timestamp-player` 按 DOM 位置绑音频，跨集必然静默播错集；`HH:MM:SS` 还会静默错 60 倍。
- [0002. 队列笔记即状态机，worker 只是执行器](0002-队列笔记即状态机.md) — 状态落在 `_pipeline/队列.md` 里换来崩溃可续跑，进度显示白来（Obsidian 自己重载文件），插件与 worker 之间零 IPC。

Existing high-level rationales live in CONTEXT.md; ADRs capture deeper design choices.

---

For more on ADR format, see [adr.github.io](https://adr.github.io/).
