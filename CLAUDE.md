# Claude Code Configuration

Local instructions for Claude when working on this project.

## Agent skills

### Issue tracker

Issues live in GitHub at [`github.com/kildren-coder/story-machine`](https://github.com/kildren-coder/story-machine). Use `gh issue create` to file tasks. See `docs/agents/issue-tracker.md`.

### Triage labels

Five canonical labels (`needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`) route issues to the right handler. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: `CONTEXT.md` + `docs/adr/` at repo root. See `docs/agents/domain.md` for reading rules.

### AFK (sandcastle)

`wayfinder:research` 票可由本地 Docker 沙箱夜跑消化（调研 + 评审双 agent，产出带摘要的 PR，不自动关票）。配置在 `.sandcastle/`，用法与额度纪律见 `docs/agents/afk-sandcastle.md`。与 agent-alert 共享额度池：同一晚只跑一个项目的 `--loop`。

---

## Project Summary

把 3 小时长的政经直播音频变成**可查、可比对、能回到原话**的断言表，让人在此之上做吸收和综合。两条目的：**(A) 快速了解并吸收一集内容**、**(B) 学会主播的分析框架，尤其是他们的信息源**。双机（笔记本 + RTX 5070 PC 跑 ASR，经 Tailscale+SSH）；全流程 LLM 走 Claude Code 订阅额度。

**产物是断言表，不是自动生成的知识图谱。** 人是唯一的下游——软件摆碎片，综合与判断归人。

**红线（节选）：**
- ASR 只听写，不总结不脑补
- 抽取不得脑补，`source_quote` 是机械载体
- 精简材料只删只排，**不增不综合**；限定词与不确定性标记必须原样保留
- 人工审核是质量闸门；且只审提取产物，**永不要求通读逐字稿**
- 综合归人——脉络笔记永不自动生成

See `CONTEXT.md` for the entry point and **`SPEC.md` for the authoritative spec** (data model, full red-line list, dev priorities).
