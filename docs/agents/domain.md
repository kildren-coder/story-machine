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

3. **audio-obsidian-pipeline-spec.md** is a detailed requirements document
   - Supplements CONTEXT.md with full stage-by-stage walkthroughs
   - Referenced for implementation details (e.g., exact chunk overlap, entity note template)

## When Consuming

- **Writing code?** Reference CONTEXT.md constraints (non-negotiables) + the relevant ADR
- **Clarifying scope?** Read CONTEXT.md "Non-Negotiables" and "Development Priorities"
- **Stuck on architecture?** Check docs/adr/ for related decisions and rationale
- **Building Obsidian templates?** See audio-obsidian-pipeline-spec.md Section 5

## Structure Summary

```
├── CONTEXT.md                          ← Start here: overview + constraints
├── audio-obsidian-pipeline-spec.md     ← Detailed spec: stages, templates, cost strategy
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
