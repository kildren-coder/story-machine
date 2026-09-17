# Domain Documentation

**Layout:** Single-context — `CONTEXT.md` (this directory root) + `docs/adr/` for architecture decisions.

## Reading Rules

1. **CONTEXT.md** is the short entry point: what the project is, the reading surfaces, the layered pipeline, the red lines
   - Read first to understand the problem space
   - The red-lines section locks in non-negotiables (ASR only transcribes, checks must carry links, the reader never sees intermediate products)

2. **docs/adr/** records architecture decisions (ADRs)
   - 0001 timestamp-seek plugin, 0002 queue note as state machine, 0003 daily digest replaces the claim table, 0004 layered headless pipeline
   - Reversals live here: when a red line or product shape was overturned, the ADR keeps the reasoning after the spec was rewritten

3. **SPEC.md** is the authoritative requirements document
   - CONTEXT.md is the short entry point; SPEC.md is the full spec. **On conflict, SPEC.md wins.**
   - Covers the layers L1–L7 (§4), data contracts (§5), vault layout (§6), model/effort table (§7), red lines (§8), dev priorities (§10)
   - v3 (2026-09-12) replaced v2 (2026-07-27, claim-table design); v2 is retrievable from the backup commit named in the SPEC header (`git show 28abfb5:SPEC.BACKUP.md`)

## When Consuming

- **Writing code?** Reference SPEC.md §4.1 (per-layer conventions), §8 (red lines) + the relevant ADR
- **Clarifying scope?** Read SPEC.md §1 (purpose, reading budget, what we don't do) and §10 (dev priorities)
- **Stuck on architecture?** Check docs/adr/ for related decisions and rationale
- **Working on a layer's prompt or schema?** See SPEC.md §4 (that layer) and §5 (its data contract); keep EP02 as the golden sample
- **Building Obsidian structure?** See SPEC.md §6

## Structure Summary

```
├── CONTEXT.md                          ← Start here: overview + red lines
├── SPEC.md                             ← Authoritative spec: layers, contracts, vault, red lines
├── docs/
│   ├── adr/
│   │   ├── README.md                   ← ADR template & index
│   │   ├── 0001-时间戳跳播自研插件.md
│   │   ├── 0002-队列笔记即状态机.md
│   │   ├── 0003-日报取代断言表.md
│   │   └── 0004-分层无头流水线.md
│   ├── agents/
│   │   ├── domain.md                   ← This file
│   │   ├── issue-tracker.md            ← GitHub issue workflow
│   │   ├── triage-labels.md            ← Label meanings
│   │   └── afk-sandcastle.md           ← AFK sandbox workflow + ready-for-agent admission checklist
│   ├── prototypes/daily-digest/        ← 2026-09-11 digest prototype: verdict + real fact-check samples
│   └── qa/                             ← Per-issue QA docs written by AFK agents (issue-<n>.md, -brief.md)
├── .sandcastle/                        ← AFK orchestrator, prompts, Dockerfile (not project code)
├── prompts/
│   └── L1-skeleton.md                  ← L1 骨架：整集 → 章节表（首行 version:）
├── scripts/
│   ├── digest.py                       ← 单集入口：`ep EP{n} --vault <dir>`（worker -Extract 转交它）
│   ├── sm/                             ← 各层共用的机械件（SPEC §4.1）
│   │   ├── text.py / note.py / paths.py        时间戳归一 / EP 笔记读写 / vault 路径
│   │   ├── transcript.py                       §5.1 正本 → §5.2 喂模型的文本
│   │   ├── runner.py / pairs.py / prov.py      无头调用三形态 / 三份留档与 _failed/ / provenance
│   │   ├── l1.py                               L1 调用、章节表检查与归一
│   │   └── render_ep.py                        整理稿标记块渲染与写回（§5.7）
│   ├── worker.ps1                      ← 阶段 0 执行器 + -Extract / -Name 等人触发入口
│   └── test.sh                         ← Offline test entry used by AFK and humans
├── tests/                              ← pytest 用例 + `fixtures/` 合成样例（红线 10）
└── CLAUDE.md                           ← Agent skills config + project summary
```
