# AFK 工作流:sandcastle(research 版)

用 [mattpocock/sandcastle](https://github.com/mattpocock/sandcastle) 在本机
Docker 沙箱里跑 AFK 调研 agent,消化 wayfinder 地图([issue #1](https://github.com/kildren-coder/story-machine/issues/1))
上的 `wayfinder:research` 票。与 agent-alert 的 `.sandcastle/` 同源,任务形状
不同:那边是"代码 + 离线 pytest",这边是"联网调研 + markdown 文档 + 来源抽查"。

**边界:AFK 的产物是"带摘要的调研 PR"。** 合并由人决定;wayfinder 收尾
(结论评论定稿、关票、回填地图 Decisions so far)由人工或后续会话完成——
PR **不带 Closes**,合并不会自动关票。AFK agent 永远不改地图、不关 issue。

## 一次运行的流程

`.sandcastle/afk.ts` 编排,每次消化一张票:

1. **取号**:开放的 `wayfinder:research`、无 assignee、无未关闭 blocker
   (GitHub 原生 dependencies)、无 `needs-info`;**半成品优先**,同类内取
   最小号;或命令行指定。
2. **判模式**:看分支状态决定这一轮是全新调研还是续跑(见"续跑")。
3. **认领**:`--add-assignee @me`。
4. **调研**:沙箱内 Claude Code 在分支 `agent/issue-<n>` 上联网调研,产出
   `docs/research/issue-<n>.md`(结论先行、来源链接 + 访问日期、事实与推断
   分开、落到 spec 具体环节)。issue 正文/评论由编排器在宿主机取好注入 prompt。
5. **评审**:同一沙箱内第二个 agent 冷读票面 Question 与文档,**实访抽查
   3~5 个来源链接**,小问题直接修;并提交 `docs/research/issue-<n>-brief.md`
   ——300 字四段(问的是什么/答案是什么/对项目意味着什么/最不可靠的地方),
   给"几分钟内决定合不合的人"看。这份由评审 agent 写而非调研 agent:调研
   agent 泡在自己上下文里分不清什么重要,评审 agent 视角和打开 PR 的人相同。
6. **收尾**:推分支;评审通过则开 PR(续跑时是刷新原 PR),PR 顶部是 300 字
   摘要、调研全文折进 `<details>`;并在 issue 上留一条指路评论。评审 REJECTED
   则分支改名退役备查并评论 issue,不开 PR。
7. **清理**:撤容器、撤 worktree、删本次 run 的临时目录;worktree 有未提交
   改动则保留备查。

终止信号:调研 agent 判定票面 Question 有歧义时输出 `BLOCKED`(issue 加
`needs-info` 并释放认领——`needs-info` 同时把票挡出 frontier,人答复后移除
该标签即回到 frontier);评审 agent 判定答非所问/来源大面积失实输出
`REJECTED`(不开 PR)。任何异常都会释放认领,frontier 不会被卡死。

## PR 之后:人审 + wayfinder 收尾

1. 读 PR 顶部 300 字摘要,必要时展开全文。
2. 有问题 → 把反馈写成 PR 评论或 issue 评论,重跑
   `npm run afk '--' <n>`(成功后票上有 assignee,自动取号会跳过它,须显式
   指定号)——复跑走返工模式,commit 叠加、摘要重刷、旧摘要折进评论存档。
3. 满意 → 合并 PR。然后做 wayfinder 收尾(人工或丢给一个会话):按 wayfinder
   流程发结论评论、关票、往地图 Decisions so far 追加一行、graduate 相关 fog。

## 续跑:分支即状态,人不需要记

`agent/issue-<n>` 这个分支名只表示「有可以接着做的半成品」:

| 分支状态 | 含义 | 用哪个 prompt |
|---|---|---|
| 有 commit 领先 main + 有开着的 PR | 返工 | `continue.md`,注入反馈 |
| 有 commit 领先 main + 没有 PR | 上一轮被打断(额度/崩溃) | `continue.md`,反馈为空 |
| 没有分支 | 全新 | `research.md` |
| PR 已合并 / 已关闭 / 分支是空壳 | 上一轮已了结 | 退役该分支后按全新跑 |

方向被否掉或已了结的分支一律改名退役为
`agent/issue-<n>-{rejected,merged,closed,empty}-<时间戳>`,内容不丢,只是把
名字腾出来。注入的"反馈"= 分支最后一个 commit 之后出现的言论(issue 评论 +
PR 评论 + PR review,按时间序);全部 issue 评论仍作为背景单独注入。
`--dry-run` 只报告判定结果,无副作用;`--fresh` 强制退役半成品后从头跑。

## 首次配置

1. Docker Desktop 运行中;`gh auth login` 已完成。
2. `cd .sandcastle && npm install`
3. `cp .env.example .env`,填 `CLAUDE_CODE_OAUTH_TOKEN`(`claude setup-token`
   生成)和 `GH_TOKEN`(`gh auth token`)。`.env` 已被 gitignore。
4. 构建沙箱镜像(**必须在仓库根目录执行**,docker provider 只认
   `sandcastle:story-machine` 这个镜像名):
   `./.sandcastle/node_modules/.bin/sandcastle docker build-image`
5. 验证容器网络(调研必须出得去公网):
   `docker run --rm sandcastle:story-machine curl -sS -o /dev/null -w '%{http_code}\n' https://api.anthropic.com/v1/messages`
   期望 `401`(包到达,认证失败属正常)。再试一个一般站点;不通就在 `.env`
   里设 `AFK_SANDBOX_PROXY=http://host.docker.internal:7890` 走 Clash。

## 日常使用

```sh
cd .sandcastle
npm run afk                    # 自动取 frontier 上第一张 research 票(半成品优先)
npm run afk '--' 6             # 指定 issue #6(跳过 frontier query)
npm run afk '--' 6 --dry-run   # 只报告会走全新还是续跑、注入哪些反馈,不起沙箱
npm run afk '--' 6 --fresh     # 强制全新调研:先把半成品分支退役再从头跑

npm run afk '--' --loop          # 串行循环:一票接一票,直到 frontier 空或额度到门槛
npm run afk '--' --loop --max 3  # 循环但最多跑 3 票
npm run afk '--' --quota         # 只打印当前额度判定,不跑活
```

> ⚠️ **PowerShell 必须给 `--` 加引号写成 `'--'`**,否则 npm shim 会把裸 `--`
> 连同后面所有参数一起吞掉(`--loop`/`--max` 全失效)。bash 下 `'--'` 等价于
> 裸 `--`,两个 shell 通用。

- 模型:默认调研 `claude-opus-4-8`、评审 `claude-opus-4-8`——两边都是开放式
  判断(调研:哪些来源可信、怎么归纳;评审:冷读判"是否答对了问题"),不是
  照葫芦画瓢的执行,值得上重模型。`.env` 可覆盖:`AFK_RESEARCH_MODEL` /
  `AFK_REVIEW_MODEL`。
- 思考强度:调研、评审各自独立配置,默认都是 `xhigh`(同样因为是开放式
  判断,吃满);`.env` 可覆盖 `AFK_RESEARCH_EFFORT` / `AFK_REVIEW_EFFORT`。
  可选档位 `low`/`medium`/`high`/`xhigh`/`max`。
- 编码期的 implement-AFK 才读 `AFK_IMPLEMENT_MODEL` / `AFK_IMPLEMENT_EFFORT`
  (默认 `claude-sonnet-5` + `high`)——写代码是执行密集型,没必要上 opus/xhigh。
- 灰箱输出:终端实时打印 agent 叙述与每个工具调用;完整日志在
  `.sandcastle/logs/issue-<n>-{research,review}.log`,编排器本体日志在
  `.sandcastle/logs/afk-<时间戳>.log`(同步落盘,外部硬杀也留痕)。

## 额度纪律(与 agent-alert 共享额度池)

- 额度真值来自 `~/.claude/statusline-command.ps1` 落盘的
  `~/.claude/rate-limits.json`——**机器级设施,本笔记本已配好**;换机器要
  重新加,搬完先跑 `npm run afk '--' --quota` 确认(显示"无落盘真值"就是没加)。
- 事前拦截:每取下一票之前查一次额度,起点(落盘真值)+ 本进程估算 ≥ 90%
  就干净收工;撞限识别为兜底(退出码 4)。估算错了不是事故:撞限那票回
  frontier,下个窗口自动续跑。
- **同一晚只跑一个项目的 `--loop`。** 本项目与 agent-alert 共享同一个 5h
  额度池,而各自的估算器只看得见自己进程的消耗——双开会双双低估、双双撞墙。
  多项目轮转是后续工作(agent-alert 侧待办)。
- 换算常数 `AFK_UNITS_PER_PERCENT`(默认 60000)与 agent-alert 共用同一把尺,
  目前仍是估算值;那边标定完成后两边同步。

## research 票打给 AFK 前自查

- 票面 **Question 写得精确**:一句话能说清要回答什么,设计取舍不留给 agent
  裁决(有歧义它会 BLOCKED,一晚就停在那)。
- **单会话可完成**:一张票 ≈ 一份调研文档;发现"以及/顺便/同时",先拆。
- **纯靠公网可答**:需要实测本地硬件(如真跑一次 faster-whisper)的部分不属于
  research 票——那是 task 票,AFK research 只能给出文献层面的预判。
- 无未关闭 blocker、无 needs-info。

## 宿主机资源与清理

| 产物 | 位置 | 谁负责清 |
|---|---|---|
| 分支 + commit | `.git` | 不清,那是成果 |
| 日志 | `.sandcastle/logs/` | 不清,审计用,量极小 |
| worktree | `.sandcastle/worktrees/agent-issue-<n>/` | 干净则删,**脏则保留**(捞未提交的活) |
| 临时 gitdir 文件 | `.sandcastle/.tmp/run-<pid>/` | run 结束必删 |

临时文件不落系统 `%TEMP%`(本机的垃圾清理软件会扫它,bind-mount 会变悬空
——agent-alert 2026-07-20 的事故),`afk.ts` 开头已把 TEMP/TMP 指向项目内
按 pid 分的目录。真正吃磁盘的是 Docker 镜像与构建缓存,`docker system df`
看账,`docker builder prune` / `docker image prune` 手动清。

## 后续:编码期扩 implement-AFK

spec 定稿、MVP 进入编码期后,在同一副底盘上扩展:

1. Dockerfile 加回 Python 层(装本项目管线的运行时 + 测试依赖);
2. 加 `implement.md`/编码版 `continue.md`(参考 agent-alert 的版本,验证命令
   换成本项目的测试);
3. frontier query 扩到 `ready-for-agent` 票(或按当时的标签体系分派票型)。

循环、额度、认领、分支退役、日志、信号处理全部复用,不另起炉灶。
