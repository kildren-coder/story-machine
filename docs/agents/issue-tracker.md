# Issue Tracker: GitHub

**Location:** Issues live in the GitHub repository [`github.com/kildren-coder/story-machine`](https://github.com/kildren-coder/story-machine).

**Workflow:**
- Create issues via `gh issue create` for tasks, bugs, feature requests, or questions
- Link to relevant stages in the processing pipeline (e.g., "Stage 2: Gemini extraction", "Obsidian template")
- Apply triage labels to route work (see `docs/agents/triage-labels.md`)
- Close issues when work is complete

**Note on PRs:** External pull requests are **not** currently used as a request surface; all work is driven by issues + direct commits.

## Example Usage

```bash
# Create a new issue
gh issue create \
  --title "Implement entity deduplication logic" \
  --body "Map entities from Gemini extract to _index/entities.json" \
  --label "ready-for-agent"

# List open issues needing agent work
gh issue list --label "ready-for-agent" --state open
```

## Consuming Skills

- **to-tickets** — reads/writes GitHub issues
- **triage** — applies issue labels and routes work
- **to-spec** — documents design decisions as issues
- **qa** — files bugs and test results as issues
