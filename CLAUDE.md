# Claude Code Configuration

Local instructions for Claude when working on this project.

## Agent skills

### Issue tracker

Issues live in GitHub at [`github.com/kildren-coder/story-machine`](https://github.com/kildren-coder/story-machine). Use `gh issue create` to file tasks. See `docs/agents/issue-tracker.md`. #1–#49 are history (2026-07 断言表 design); #50 tracks v1.

### Triage labels

Five canonical labels (`needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`) route issues to the right handler. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: `CONTEXT.md` + `docs/adr/` at repo root. See `docs/agents/domain.md` for reading rules.

---

## Project Summary

把关注的 UP 主每天发布的**直播录播和视频**自动整理成一份**日报**：讲了什么（不简略）、重大事实偏差、支持与不支持的证据、历史先例与当时 vs 现在、有见地的分析、他们提到的信源。**AI 做信息初筛与整理，知识与事实的构建归人**——人每天只读日报，周末确认核查判定、写自己的判断。双机（笔记本 + RTX 5070 PC 跑 ASR，经 Tailscale+SSH）；全流程 LLM 走 Claude Code 订阅，一层一个无头调用（ADR 0004）。

**红线（节选）：**
- ASR 只听写，不总结不脑补
- 整理不脑补、不删事；原话锚点逐字来自逐字稿；限定词与不确定语气原样保留
- 核查判定是 AI 初判，每条必带来源链接；核查只加批注，不改整理稿
- 人每天只读日报，**永不通读逐字稿、永不审中间产物**
- 综合归人——「我的判断」永不自动生成
- 逐字稿片段不进公开仓库（仓库是公开的）

**工作方式：**
- 派 Agent 子代理**必须显式 `model: "sonnet"`**（论证类才 opus），一次并发 ≤ 3；默认继承会烧光月度额度
- 全量重写长文档走「备份 commit → 删备份 commit」两步
- 面向用户的输出一律中文

See `CONTEXT.md` for the entry point and **`SPEC.md` for the authoritative spec** (layers, data contracts, red lines, dev priorities).
