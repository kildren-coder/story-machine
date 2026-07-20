# Triage Labels

Five canonical labels for routing work:

| Label | Meaning | When to apply |
|-------|---------|---------------|
| `needs-triage` | Issue is new, not yet categorized | Auto-applied to new issues; remove once triaged |
| `needs-info` | Blocked on missing information | Ask in comments for details; remove when clarified |
| `ready-for-agent` | Agent can pick up and work | Issue is clear and actionable for Claude Code |
| `ready-for-human` | Requires human decision/input | e.g., architecture review, cost/priority tradeoff |
| `wontfix` | Not planning to address | Closed with this label for reference |

**Default behavior:**
- New issues start with `needs-triage`
- Assign exactly one of the five labels per issue
- Move between labels as status changes (e.g., `needs-info` → `ready-for-agent` once clarified)

## Examples

- **`needs-triage`** → "Add CLI command for bulk transcription" (new, unclear scope)
- **`ready-for-agent`** → "Implement Gemini Flash extraction for Stage 2" (clear spec, actionable)
- **`needs-info`** → "Decide on max fact-checks per episode" (needs cost/quality tradeoff discussion)
- **`ready-for-human`** → "Should we auto-batch process 1–2 episodes/day?" (design decision)
- **`wontfix`** → "NotebookLM integration" (out-of-scope; parallel tool only)
