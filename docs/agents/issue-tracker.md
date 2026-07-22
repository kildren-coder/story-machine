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

## Wayfinding operations

Used by `/wayfinder`. The **map** is a single issue with **child** issues as tickets. This is a separate routing system from the triage labels above — wayfinder child tickets never carry `ready-for-agent` etc.; a ticket's AFK-eligibility is signalled by its `wayfinder:<type>` label itself (see `docs/agents/afk-sandcastle.md` for the research-AFK that currently consumes `wayfinder:research`).

- **Map**: a single issue labelled `wayfinder:map`, holding the Notes / Decisions-so-far / Fog body. `gh issue create --label wayfinder:map`.
- **Child ticket**: an issue linked to the map as a GitHub sub-issue (`gh api` on the sub-issues endpoint). Where sub-issues aren't enabled, add the child to a task list in the map body and put `Part of #<map>` at the top of the child body. Labels: `wayfinder:<type>` (`research`/`prototype`/`grilling`/`task`). Once claimed, the ticket is assigned to the driving dev.
- **Blocking**: GitHub's **native issue dependencies** — the canonical, UI-visible representation. Add an edge with `gh api --method POST repos/kildren-coder/story-machine/issues/<child>/dependencies/blocked_by -F issue_id=<blocker-db-id>`, where `<blocker-db-id>` is the blocker's numeric **database id** (`gh api repos/kildren-coder/story-machine/issues/<n> --jq .id`, _not_ the `#number` or `node_id`). GitHub reports `issue_dependencies_summary.blocked_by` (open blockers only — the live gate). A ticket is unblocked when every blocker is closed.
- **Frontier query**: list the map's open children (`gh issue list --state open`, scoped to the map's sub-issues / task list), drop any with an open blocker (`issue_dependencies_summary.blocked_by > 0`), an assignee, or a `needs-info` label — story-machine convention keeps a BLOCKED ticket's `wayfinder:<type>` label and only adds `needs-info`, so frontier queries must exclude it explicitly. First in map order wins.
- **Claim**: `gh issue edit <n> --add-assignee @me` — the session's first write.
- **Resolve**: `gh issue comment <n> --body "<answer>"`, then `gh issue close <n>`, then append a context pointer (gist + link) to the map's Decisions-so-far.

## Consuming Skills

- **to-tickets** — reads/writes GitHub issues
- **triage** — applies issue labels and routes work
- **to-spec** — documents design decisions as issues
- **qa** — files bugs and test results as issues
- **wayfinder** — charts and works the map; see "Wayfinding operations" above
