# Story Machine — Project Context

## Overview

An automated audio-to-Obsidian knowledge graph workflow for processing long-form political/economics content (typically ~3 hours per episode). The system bridges local speech recognition (faster-whisper on a dedicated RTX 5070 PC) with AI-powered content extraction and knowledge synthesis.

**Two core needs:**
1. **Accurate transcription** — faithful to source audio, no hallucination
2. **Structured knowledge graph** — continuous accumulation of interconnected entities (people, events, places, concepts, periods) in Obsidian, not scattered notes

## Key Constraints & Decisions

### Architecture
- **Dual-machine setup**: Laptop (Claude Code + Obsidian) ↔ Room PC (RTX 5070, faster-whisper via Tailscale+SSH)
- **Map-Reduce processing**: Long transcripts split into 20–30min chunks before extraction (Gemini Flash → draft → user review → Claude Code → Obsidian)
- **Manual review gate**: Stage 3 (user validation in `_review/` before facts enter the knowledge graph) is non-negotiable

### Cost Optimization
| Stage | Tool | Cost |
|-------|------|------|
| ASR | faster-whisper (local) | Free (electricity) |
| Draft extraction | Gemini Flash | Free tier |
| Entity merging & fact-checking | Claude Code | Subscription |
| Personal understanding | NotebookLM | Free tier (parallel, not integrated) |

- **Hotwords mechanism**: ASR quality improves over time via persistent `hotwords.json`, seeded from episode show notes
- **Fact-check budget**: Verify only `history` and `claim` assertions, skip `opinion`. Limit to 10–20 checks per episode to control costs

### Processing Pipeline
**Stage 0** → Transcription (PC, triggered remotely)  
**Stage 1** → Chunking (20–30min with 1–2min overlap)  
**Stage 2** → Draft extraction (Gemini Flash)  
**Stage 3** → Manual review (`_review/` staging area)  
**Stage 4** → Entity merge, fact-check, note generation (Claude Code)  
**Stage 5** → Obsidian storage with full [[wikilinks]]

### Obsidian Vault Structure
```
Vault/
├── 10-Episodes/       MOCs (maps of content) per episode
├── 20-People/         Person entities
├── 21-Events/         Historical/news events
├── 22-Places/         Countries, regions, places
├── 23-Concepts/       Concepts, schools of thought
├── 24-Periods/        Historical periods
├── _review/           User review staging (excluded from graph)
└── _index/entities.json (program-managed, not human-edited)
```

Entity notes carry frontmatter (`type`, `aliases`, `tags`) and link all related notes via `[[wikilinks]]`. Obsidian Graph View auto-renders the network.

## Non-Negotiables

1. **ASR ≠ summarization**: Transcription is listen-only, no LLM smoothing or hallucination
2. **Extraction ≠ synthesis**: Prompts must forbid adding model background knowledge; extract only what's in the transcript
3. **Human review is a QA gate**: Drafts never bypass `_review/` staging; user confirmation required before facts enter the graph
4. **One name per entity**: `aliases` field + `_index/entities.json` prevent duplicate notes — essential for auto-linking
5. **Facts vs. opinions**: Only verify `history`/`claim` assertions; `opinion` entries are filed as-is, unchecked

## Development Priorities (rough order)
1. Laptop ↔ PC bridging (Tailscale+SSH) + remote transcription CLI wrapper
2. Chunking + Gemini Flash draft extraction (single chunk → batch)
3. Obsidian vault scaffold + `_review/` read/write
4. Entity index (`entities.json`) + deduplication logic
5. Claude Code merge, fact-check, note generation
6. Hotwords refinement
7. Parameter tuning (chunk duration, fact-check limits, etc.)

## Open Questions
- Specific defaults for chunk overlap, fact-check limit per episode?
- How to signal "review complete" from Obsidian to next stage (filename, frontmatter, CLI flag)?
- Batch-queue mode for auto-processing 1–2 episodes/day, or always manual trigger?
- Will Pro subscription suffice, or upgrade to Max 5x/20x after two weeks of real usage?

See `audio-obsidian-pipeline-spec.md` for full specification.

See `docs/vision.md` for the four downstream visions (求真引擎 / 资产分析框架 / 故事素材库 / 信源信用档案) and which base cheap-insurance fields each one depends on. Vision implementations are out of MVP scope; ideas accumulate in the `vision`-labeled issues.
