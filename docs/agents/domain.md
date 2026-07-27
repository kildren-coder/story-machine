# Domain Documentation

**Layout:** Single-context — `CONTEXT.md` (this directory root) + `docs/adr/` for architecture decisions.

## Reading Rules

1. **CONTEXT.md** is the authoritative source for project scope, constraints, and design principles
   - Read first to understand the problem space
   - Constraints section locks in non-negotiables (e.g., manual review gate, no hallucination in ASR)
   - Refer to specific sections when designing or reviewing implementations

2. **docs/adr/** records architecture decisions (ADRs)
   - One file per significant decision (e.g., why Gemini Flash for draft extraction, hotwords mechanism)
   - Includes context, decision, and consequences
   - When a design choice seems unclear, check the corresponding ADR

3. **SPEC.md** is the authoritative requirements document
   - CONTEXT.md is the short entry point; SPEC.md is the full spec. **On conflict, SPEC.md wins.**
   - Covers stage-by-stage walkthroughs, the claim data model (§5), red lines (§8), and dev priorities (§10)
   - Replaced `audio-obsidian-pipeline-spec.md` on 2026-07-27; the old file is in git history only

## When Consuming

- **Writing code?** Reference SPEC.md §8 (red lines) + the relevant ADR
- **Clarifying scope?** Read SPEC.md §1 (purpose & boundaries) and §10 (dev priorities)
- **Stuck on architecture?** Check docs/adr/ for related decisions and rationale
- **Working on the claim schema?** See SPEC.md §5 — field table, `type` semantics, why cause/effect is free text
- **Building Obsidian structure or queries?** See SPEC.md §6

## Structure Summary

```
├── CONTEXT.md                          ← Start here: overview + red lines
├── SPEC.md                             ← Authoritative spec: stages, data model, cost strategy
├── docs/
│   ├── adr/
│   │   ├── README.md                   ← ADR template & index
│   │   ├── 0001-gemini-flash-for-extraction.md
│   │   ├── 0002-hotwords-mechanism.md
│   │   └── ...
│   └── agents/
│       ├── domain.md                   ← This file
│       ├── issue-tracker.md            ← GitHub issue workflow
│       └── triage-labels.md            ← Label meanings
└── CLAUDE.md                           ← Agent skills config
```
