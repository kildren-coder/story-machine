# Claude Code Configuration

Local instructions for Claude when working on this project.

## Agent skills

### Issue tracker

Issues live in GitHub at [`github.com/kildren-coder/story-machine`](https://github.com/kildren-coder/story-machine). Use `gh issue create` to file tasks. See `docs/agents/issue-tracker.md`.

### Triage labels

Five canonical labels (`needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`) route issues to the right handler. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: `CONTEXT.md` + `docs/adr/` at repo root. See `docs/agents/domain.md` for reading rules.

---

## Project Summary

Audio-to-Obsidian knowledge graph workflow. Process long-form (3hr) political/economics episodes → structured, interconnected entity notes in Obsidian. Dual-machine setup (laptop + RTX 5070 PC for ASR via Tailscale+SSH). Map-Reduce extraction (Gemini Flash drafts → user review → Claude Code synthesis → wikilinked notes).

**Non-negotiables:**
- ASR is transcription-only (no hallucination, no summarization)
- Manual review gate before facts enter the knowledge graph
- One name per entity (aliases + index prevent duplicates)
- Verify only facts/claims, not opinions

See `CONTEXT.md` for full scope, constraints, and priorities.
