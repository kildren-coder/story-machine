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
- [0005. L1 只切章节，话题交给 L2；位置用行号，形状交给 CLI](0005-L1切章节-L2切话题.md) — 整集一次切到话题，话题数同一集能差一倍多（EP02：29–75），L2 的调用次数跟着摆；改成 L1 切十几分钟一章的容器、章数由时长定，模型用行号指位置，产物形状经 `--json-schema` 交给 CLI 把关。
- [0006. 转写引擎换 FireRedASR2-AED](0006-转写引擎换FireRed.md) — 盲听推翻了 9 月「按上下文判 whisper 更准」：whisper 写得通顺但不是原话（30 处 FireRed 对 21、whisper 对 8）；首测 1.2× 是显存溢出，K/V 缓存 + 显存上限后 fp32 24× 且逐字不变；英文变差，交给下游。
- [0007. 述线制取代按集日报：跨集收纳、初筛页把关](0007-述线制取代按集日报.md) — 按天聚事件接不上隔几周再谈的同一件事；组织单位改成跨集的述线，初筛页一页让人挑、述线页按线读；一段可挂多条、旁段也挂、开线看内容、不分上下级。
- [0008. 上下文预算与本地索引](0008-上下文预算与本地索引.md) — 每次调用 12 万目标、15 万硬上限；模型输入不随历史涨，涨的只有本机索引；挂述线拆成 4a / 4b / 4c、步间检索；工作单位是队列里的项，不是「集」。
- [0009. 原话由程序抄定](0009-原话由程序抄定.md) — 模型只给行号加前几个字，代码从逐字稿抄字、查词表定时刻；闸门按整章连续文本比，跨块不再误删；闸门 3 不做，#83 并入。
- [0010. 听错与黑话](0010-听错与黑话.md) — 本地大模型改正本否决（抽样错 26 对 13）；L2 近音改正并列出、黑话只标不解；正字是每次运行按词排队的处理阶段，听错与黑话都出改字表、不改写正文、改处可见并带证据种类；确认过的词回灌两份词表，黑话表分通用层与主播层。
- [0011. 记录只追加，当前视图派生](0011-记录只追加-当前视图派生.md) — 先跑新集再补旧集暴露五处毛病；挂法、开线、判定只追加带时间的记录，页面由代码重算；首次出现、上次更新、播出日期、挂上的那次运行分开记；改判也是追加盖过。
- [0013. 说法台账全系统一张](0013-说法台账.md) — 核什么由诊断力定不按条数（32 条里能分辨论点的 3 条、最该核的 8 句不在清单里）；判定四态加把握加「现在」字段，过时不做档；证据全记、立场先记不析、社媒打折；检索在模型外、语种跟当事方；机检三态；核一次被引用、改判追加传播。

Existing high-level rationales live in CONTEXT.md; ADRs capture deeper design choices.

---

For more on ADR format, see [adr.github.io](https://adr.github.io/).
