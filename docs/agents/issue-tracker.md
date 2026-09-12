# Issue Tracker: GitHub

**Location:** Issues live in the GitHub repository [`github.com/kildren-coder/story-machine`](https://github.com/kildren-coder/story-machine).

**Workflow:**
- Create issues via `gh issue create` for tasks, bugs, feature requests, or questions
- Name the pipeline layer the issue touches (e.g. "阶段 0 转写", "L2 逐话题整理", "L5a 事实核查") — layers are defined in `SPEC.md` §4
- Apply triage labels to route work (see `docs/agents/triage-labels.md`)
- Close issues when work is complete

**Note on PRs:** External pull requests are **not** currently used as a request surface; all work is driven by issues + direct commits.

**History:** Issues #1–#49 belong to the 2026-07 "断言表" design (wayfinder map #1 and its child tickets). They were closed in bulk on 2026-09-12 when the project was repositioned as a daily digest (ADR 0003). Read them as history only; do not reopen them for new work.

## Example Usage

```bash
# Create a new issue
gh issue create \
  --title "L3 闸门：限定词保留检查" \
  --body "整理稿里丢掉了引文中的「应该」「大概率」时要能机械发现" \
  --label "ready-for-agent"

# List open issues needing agent work
gh issue list --label "ready-for-agent" --state open
```
