# Triage Labels

Five canonical labels for routing work:

| Label | Meaning | When to apply |
|-------|---------|---------------|
| `needs-triage` | Issue is new, not yet categorized | Auto-applied to new issues; remove once triaged |
| `needs-info` | Blocked on missing information | Ask in comments for details; remove when clarified |
| `ready-for-agent` | AFK sandbox can consume it | Passes the admission checklist in `docs/agents/afk-sandcastle.md`: one-PR size, acceptance offline-testable, synthetic fixtures in repo, four questions answered |
| `ready-for-human` | Requires human decision/input | e.g., architecture review, cost/priority tradeoff |
| `wontfix` | Not planning to address | Closed with this label for reference |

**Default behavior:**
- New issues start with `needs-triage`
- Assign exactly one of the five labels per issue
- Move between labels as status changes (e.g., `needs-info` → `ready-for-agent` once clarified)

## Priority (orthogonal to the five)

| Label | Meaning | When to apply |
|-------|---------|---------------|
| `priority:high` | Jump the AFK queue | Only a human applies it. The AFK frontier picks half-finished issues first, then `priority:high`, then the lowest issue number (`.sandcastle/afk.ts` `pickIssue`). Without it a newly filed urgent ticket always sorts last. Remove it once the issue is done or no longer urgent. |

## Examples

- **`needs-triage`** → "关注列表自动扫新投稿入队" (new, scope unclear)
- **`ready-for-agent`** → "L3 闸门：限定词保留检查" (clear spec in SPEC §4 L3, actionable)
- **`needs-info`** → "L5a 事实核查要不要升 opus" (needs token cost vs. quality data from a real run; SPEC §11)
- **`ready-for-human`** → "时间戳跳播加不加 B 站 `?t=` 第二按钮" (product decision; SPEC §11)
- **`wontfix`** → "给「他们提到的信源」打信用分" (SPEC §1.4 不做)
