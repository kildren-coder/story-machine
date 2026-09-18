# AFK 工作流：sandcastle

用 [mattpocock/sandcastle](https://github.com/mattpocock/sandcastle) 在本机
Docker 沙箱里跑 AFK coding agent，消化 `ready-for-agent` 的 issue。与
agent-alert 的 `.sandcastle/` 同源（编排器、额度门槛、续跑机制全部照搬，设计
论证与事故复盘在那个仓库的 `.exp/2026-07-21-afk-unattended-automation.md`），
只有任务形状按本项目改：**离线测试 + 红线核对 + 真实样例验证指引**。

**边界：AFK 的产物是「绿的 PR」。** 合并由人决定。合并后拿 vault 里的 EP02
跑一次相关层、看效果，也是人在笔记本的交互式会话里做——沙箱里没有 vault，
也不许自己调 `claude -p`。AFK agent 永远不合并 PR、不动 main、不碰 vault。

## 一次运行的流程

`.sandcastle/afk.ts` 编排，每次消化一个 issue：

1. **取号**：frontier query——开放的 `ready-for-agent`、无 assignee、无未关闭
   blocker（GitHub 原生 dependencies）；**半成品优先**，同类内取最小号；或命令行
   指定。
2. **判模式**：看分支状态决定这一轮是全新实现还是续跑（见「续跑」）。
3. **认领**：`--add-assignee @me`。
4. **实现**：沙箱内 Claude Code 在分支 `agent/issue-<n>` 上实现，issue 正文 /
   评论由编排器在宿主机取好注入 prompt。验证只靠 `bash scripts/test.sh`
   （离线；沙箱里没有 vault、逐字稿、PC、Obsidian）。
5. **QA 文档**：实现 agent 完工时必须提交 `docs/qa/issue-<n>.md`——改动摘要、
   沙箱内已验证清单，以及**给合并后跑真实样例的人的验证指引**（对 EP02 跑哪条
   命令、看哪个文件、期望形状、怎么判断坏了、怎么回退）。这份内容只有实现完的
   agent 写得准。
6. **评审**：同一沙箱内第二个 agent 对照 issue 验收标准审 diff、复跑测试、
   **逐条核对红线**（合成样例不是真转写、闸门只删不改、渲染不改写、provenance
   齐全）、核对 QA 文档与 diff 一致、直接修小问题；并提交
   `docs/qa/issue-<n>-brief.md`——300 字四段（为什么做 / 改了什么 / 效果 / 最大
   风险），给「几分钟内决定合不合的人」看。由评审 agent 写而非实现 agent：实现
   agent 泡在自己上下文里分不清什么重要，评审 agent 冷读 issue + diff，视角和
   打开 PR 的人相同。
7. **收尾**：推分支；评审通过则开 PR（续跑时是刷新原 PR），PR 带 `Closes #<n>`；
   否则把分支改名退役备查并评论 issue。PR body 顶部是那 300 字摘要，QA 文档
   全文折进 `<details>`。
8. **清理**：撤容器、撤 worktree、删本次 run 的临时目录；worktree 有未提交改动
   则保留备查。

终止信号：实现 agent 受阻输出 `BLOCKED`（issue 自动转 `needs-info` 并释放认领）；
评审 agent 判定方向性偏差或红线违规输出 `REJECTED`（不开 PR）。任何异常都会释放
认领，frontier 不会被卡死。

## PR 之后：先分 A 类还是 B 类

读完 PR 摘要，常会想再改点什么。**动手之前先分类**。

判据一句话：**「这是没做对」→ A 类；「这是做对了以后才看见的下一个问题」→ B 类。**
等价问法：这个改动还在原 issue 的验收标准之内吗？

| | A 类（返工） | B 类（新工作） |
|---|---|---|
| 处置 | 反馈写成 issue 或 PR 评论 → 重跑 AFK，重走实现 + 评审双闸 | 原 PR 照常合并，另开 issue，走正常 triage |
| 落点 | **同一个 PR**（分支没变，commit 叠上去） | 独立 issue、独立分支、独立 PR |

**不要在交互式会话里手工把改动做掉再追一条评论。** 那样绕过了双闸，决策只
活在会消失的 session 里。写成评论、重跑 AFK，是把决策落进仓库的唯一路径。

真实样例跑出来效果不好（整理稿读着不对、闸门拦多了）多半是 **B 类**：机械
部分对了，是 prompt 或参数要调，另开票。

## 续跑：分支即状态，人不需要记

`agent/issue-<n>` 这个分支名只表示「有可以接着做的半成品」。`npm run afk`
不需要 `--continue`——`git fetch` 之后看分支就知道该怎么跑：

| 分支状态 | 含义 | 用哪个 prompt |
|---|---|---|
| 有 commit 领先 main + 有开着的 PR | A 类返工 | `continue.md`，注入反馈 |
| 有 commit 领先 main + 没有 PR | 上一轮被打断（额度 / 崩溃） | `continue.md`，反馈为空 |
| 没有分支 | 全新 | `implement.md` |
| PR 已合并 / 已关闭 / 分支是空壳 | 上一轮已了结 | 退役该分支后按全新跑 |

方向被否掉或已了结的分支一律改名退役为
`agent/issue-<n>-{rejected,merged,closed,empty}-<时间戳>`，内容不丢，只是把
名字腾出来。注入的「反馈」= 分支最后一个 commit 之后出现的言论（issue 评论 +
PR 评论 + PR review，按时间序）；全部 issue 评论仍作为背景单独注入。
`--dry-run` 只报告判定结果，无副作用；`--fresh` 强制退役半成品后从头跑。

本仓库 2026-07 research 版 AFK 留下的 `agent/issue-{6,9,16,28,37}` 及其
`-empty-*` 退役分支属于已关闭的旧票，frontier 不会取到它们；可整批删掉。

## 首次配置

1. Docker Desktop 运行中；`gh auth login` 已完成。
2. `cd .sandcastle && npm install`
3. `cp .env.example .env`，填 `CLAUDE_CODE_OAUTH_TOKEN`（`claude setup-token`）
   和 `GH_TOKEN`（`gh auth token`）。与 agent-alert 同一订阅、同一账号，直接拷
   那边的 `.env` 也行（连标定过的 `AFK_UNITS_PER_PERCENT` 一起）。
4. 构建沙箱镜像（**必须在仓库根目录执行**，docker provider 只认
   `sandcastle:story-machine` 这个镜像名）：
   `./.sandcastle/node_modules/.bin/sandcastle docker build-image`
5. `npm run afk '--' --quota` 确认能读到落盘的额度真值（见「额度从哪来」）。

## 日常使用

```sh
cd .sandcastle
npm run afk                    # 自动取 frontier 上第一个 issue（半成品优先）
npm run afk '--' 61            # 指定 issue #61（跳过 frontier query）
npm run afk '--' 61 --dry-run  # 只报告会走全新还是续跑、注入哪些反馈，不起沙箱
npm run afk '--' 61 --fresh    # 强制全新实现：先把半成品分支退役再从头跑

npm run afk '--' --loop          # 串行循环：一票接一票，直到 frontier 空或额度到门槛
npm run afk '--' --loop --max 3  # 循环但最多跑 3 票
npm run afk '--' --quota         # 只打印当前额度判定，不跑活
```

> ⚠️ **PowerShell 必须给 `--` 加引号写成 `'--'`。** 裸的 `--` 会连同后面的参数
> 一起被吞掉，`--loop` / `--max` 全部失效、跑完一票就退出。bash 下 `'--'` 等价于
> 裸 `--`，两个 shell 通用。

- **一次 `npm run afk` = 一个 issue = 一条分支 = 一个 PR。**
- 灰箱输出：终端实时打印 agent 的叙述和每个工具调用，每轮结束打印 context /
  token 用量。完整原始日志在 `.sandcastle/logs/issue-<n>-{implement,review}.log`，
  编排器本体日志在 `.sandcastle/logs/afk-<时间戳>.log`。
- 模型：默认实现 `claude-sonnet-5`、评审 `claude-opus-4-8`，思考程度 `high`。
  `.env` 可覆盖：`AFK_IMPLEMENT_MODEL` / `AFK_REVIEW_MODEL` / `AFK_EFFORT`。
- `maxIterations`（实现 50、评审 3）是**单个 issue 内** agent 的续跑上限，与
  issue 数量无关。

## 串行循环与额度门槛（`--loop`）

给睡觉时段用的：「取票 → 跑 → 额度够就取下一票」，直到 frontier 空或额度到门槛。

**⚠️ 与 agent-alert 共用同一个 5h 额度池，而 `QuotaTracker` 只看得见本进程的
消耗——同一晚只跑一个项目的 `--loop`。** 双开会互相看不见对方，双双低估、双双
撞墙。

### 额度从哪来

`afk.ts` 是宿主机上的普通进程，不是 agent、不耗额度，也因此看不见额度。真值只
存在于 Claude Code 喂给 statusline 的 payload（`rate_limits.five_hour`）：

1. `~/.claude/statusline-command.ps1` 把 `rate_limits` 连同写入时间戳落盘到
   `~/.claude/rate-limits.json`。
2. `afk.ts` 读它当**起点**，夜间增量按 agent 的 token 用量估算叠上去（`quota.ts`）。
3. 起点 + 估算 ≥ **90%** 就不开下一票，干净收工。

> 第 1 步那个脚本在 `~/.claude/` 下，不在本仓库里，换机器要重新加。没加也不
> 报错——`--quota` 会显示「无落盘真值」，起点按 0% 算，门槛基本等于没拦。

误差不累积一整夜：落盘数据带 `resets_at`，过期就按新窗口 0% 重算。估算错了不是
事故：撞限那一票白烧部分 token，但 issue 干净地回到 frontier，分支和 commit 都
留着，下个窗口自动续跑。

### 事前拦截为主，撞限识别为兜底

每取下一票**之前**查一次额度。事后把「撞额度上限」（退出码 4）、「环境不通」
（退出码 5）、「认证失效」（退出码 6）从「这票做失败了」里分出来——这三类换一
张票也是撞同一堵墙，识别到就停循环。

### 标定

`AFK_UNITS_PER_PERCENT` 是 token → 额度的换算常数，与 agent-alert 共用同一把尺
（同一订阅、同一模型）。当前 `.env` 里的值是从那边拷来的标定值。要重新标定：
跑完一轮 `--loop` 后，用「本轮报的加权单位数 ÷ statusline 上 5h% 的实际涨幅」，
把结果写回这里：

- **2026-09-17，issue #51**（实现与评审都是 `claude-opus-5`，effort `xhigh`）：
  实现 2205k + 评审 599k = **2804k 加权单位**，5h 窗口 2.0% → 15.0%，即
  **约 216k 单位/%**。`.env` 取 `200000` 留余量——那 13 个百分点里还含同期交互式
  会话自己的消耗，AFK 独占的份额更小，真值比 216k 高，取小值偏保守。
  一票这个体量约占窗口 13%，配 90% 门槛，一个窗口大致跑得下 6 票。
  换模型或换 effort 后这个数就不作数了，重标。

## 宿主机资源与清理

一次 run 在宿主机上留下四样东西，只有前两样是长期资产：

| 产物 | 位置 | 谁负责清 |
|---|---|---|
| 分支 + commit | `.git` | 不清，那是成果 |
| 日志 | `.sandcastle/logs/` | 不清，审计用，量极小 |
| worktree | `.sandcastle/worktrees/agent-issue-<n>/` | 干净则删，**脏则保留** |
| 临时 gitdir 文件 | `.sandcastle/.tmp/run-<pid>/` | run 结束必删 |

**脏 worktree 一律保留**：run 崩掉时 agent 写了但没来得及提交的文件全靠它捞
回来。终端会打印保留路径，人工处理完自己删。

**临时目录不用系统 `%TEMP%`**：sandcastle 会把改写过的 `.git` 文件 bind-mount
进容器，本机的第三方清理软件会定时扫 `%TEMP%`，源文件一删挂载就悬空、整个
进程崩掉（agent-alert 2026-07-20 真炸过）。`afk.ts` 开头把 `TEMP`/`TMP` 指向
`.sandcastle/.tmp/run-<pid>/`，按 pid 分目录，并行跑时互不拔线。

真正吃磁盘的是 Docker 镜像和构建缓存，手动清：`docker system df`、
`docker builder prune`、`docker image prune`。

## ready-for-agent 的 issue 必须满足

打 `ready-for-agent` 前自查（否则 agent 大概率 BLOCKED 或做偏）：

- **纵切，不横切（曳光弹）**：每张票必须给程序带来一个人能打开看的变化——笔记里
  多了什么、命令的行为变了什么——并写成票面的「可见变化」一节：一条在 fixture 副本
  上跑的演示命令（沙箱 agent 能跑，QA 文档必须贴出它产出的笔记片段，合成内容可进
  仓库），一条合并后在真实 vault 上跑的命令（人跑）。「只加一个模块 / 只产出中间
  JSON」的票不合格，要和它的消费者切在同一张票里。里程碑的第一张票是行走骨架：打穿
  全部层跑通最细的一条路径，允许比下面的「几百行」大；之后每张票在这条路径上加厚。
  理由：横切要到最后一张票才看得见效果，层间契约错误最晚暴露，人拿真实样例打磨
  prompt 的工作也无法提前开始（2026-09-13 地图 #70 由横切改纵切的教训）。
- **一次运行的量**：约一个 PR、几百行 diff 以内（骨架票除外）；设计取舍已在父票 /
  wayfinder grilling 阶段定死，不留开放问题。描述里有「顺便 / 以及 / 同时」，先拆——
  但拆的方向是「更细的纵切」，不是拆回模块。
- **验收标准可离线机判**：每条验收标准都能翻译成 `bash scripts/test.sh` 里的
  断言。「EP02 的整理稿读着通顺」「闸门 1 通过率 100%」这类只能拿真实样例验证
  的标准不属于 AFK 票——那是合并后人在交互式会话里做的事，写进票的「真实样例
  验证」一节即可，不算验收标准。
- **Fixture check（出题时逐票必问）**：这张票的正确性是否取决于输入数据的形状
  （逐字稿 JSON 的字段、`chapters.json` / `topics.json` / `frag-*.json` 的结构、EP 笔记
  frontmatter）？是——出题时把一份**合成的**样例放进 `tests/fixtures/`（结构照
  SPEC §5，内容自己编，**绝不能是真实转写的片段**，红线 10），并在验收标准里
  引用它；样例没落库前不得打 `ready-for-agent`。沙箱里没有 vault，agent 造不出
  像样的样例，这一步只能发生在出题侧。
- **准入必问（出题时逐票必问）**：下面每一条逐项给出「已回答（答案写进票面或
  SPEC）」或「显式不适用」，有一项答不出就不打 `ready-for-agent`。票面上这一节
  沿用「## 四问」这个小节名（历史名字，现在是六条；别和 L5b 的「六问卡」混淆）：
  1. **失败语义**：这一层这一单元挂了会怎样？schema 不过是进 `_failed/` 还是
     整集停？重跑只重跑该单元还是整层？（SPEC §4.1 有默认答案，票面要确认适用）
  2. **资源边界**：一集切几块、一块多长、一层调几次、超时多久？撞上限后的行为？
  3. **生命周期边缘**：首次跑、`--replay` 重放、`--force` 覆盖、中断后续跑，
     分别是什么行为？已有产物会不会被静默覆盖？
  4. **集成契约**：对面的硬约束确认过了吗——`claude -p` 的输出格式、Obsidian
     frontmatter 的解析规则、队列笔记的状态字段（ADR 0002）、B 站 API 的形状。
     读过源码或文档，还是在猜？
  5. **闸门宽容度**（SPEC §4.1）：检查器打回的每一条，代码能不能不碰模型写的
     字就修好？能修的归一、不打回；代码能推出来的键不让模型写；票面列出真正
     会打回的条件，并说明每一条为什么修不了。每次打回都是整单元重发一趟。
  6. **量化预算**：这一层的产物有没有 SPEC 里已经写死的量化指标——字数、条数、
     时长、通过率、压缩比？有就逐条抄进票面。**代码算得出来的（输入字数 ×
     压缩比、条数上限、时长合计）落进本票，作为输入的一部分交给模型，并在日志
     里报实际值对目标值**；代码判不了的（读着通不通顺）写进「真实样例验证」。
     prompt 里一个字都没提的预算等于不存在——SPEC 写了 0.2，#52 的 prompt 没提，
     跑出来 0.73，而那张票自己的 108 个测试全绿（2026-09-18 EP02 实跑的教训）。
     预算是**相对量**时不许硬写绝对值：输入多长是未知的，写死 12,000 字下一集
     就错。
- **红线映射**：票面写明本票触到哪几条红线（SPEC §8），验收标准里有对应的
  测试（例如闸门只删不改、渲染不改写整理层文字、派生文件带 provenance）。
- **大切片用父子结构**：#50 是 v1 总跟踪票（不打 `ready-for-agent`），每个
  里程碑拆成子票，用 GitHub sub-issue + 原生 dependency 连接，只给子票打
  `ready-for-agent`。涉及 prompt 效果的工作（话题粒度、锚点数、model / effort
  实测）不是 AFK 票，那是人拿 EP02 跑出来的。

## 沙箱已知坑

沙箱内实测过、与宿主机行为不同、会让 agent 掉进兔子洞的环境特性。implement
prompt 只放一行指向这里的指针，细节全部落在这节；再踩到新坑就往这里追加。

- **没有 vault。** 宿主机上的 vault 在 `D:\obsidian-task\...`，沙箱里不存在，
  `scripts/digest.py` 的 `--vault` 也因此没有默认值。测试一律先把
  `tests/fixtures/vault/` 拷进 `tmp_path` 再显式传进去（`tests/conftest.py` 的
  `vault` fixture 就干这件事），**不要写回 fixture**；不要去找、不要去造 vault
  目录结构以外的东西。
- **没有 PowerShell。** `scripts/*.ps1`（worker、setup）只能静态改，改了在 QA
  文档里写人怎么验。
- **不要调 `claude -p`。** 沙箱里的 token 就是本订阅的额度；而且没有真实逐字稿，
  跑出来的东西证明不了层的效果。
- **容器用户 UID 必须是 1000。** sandcastle 在 Windows 宿主上拿不到 uid，固定
  以 `--user 1000` 起容器；Dockerfile 里 `useradd -u 1000` 已钉死，别改。
- **中文输出与编码。** 脚本自己 `reconfigure(encoding="utf-8")`，沙箱内 Python
  默认 UTF-8，宿主机 Windows 上不一定——新写的入口照 `scripts/digest.py` 开头那
  几行处理 stdout（worker 用 `& $LocalPy @argv 2>&1 | ForEach-Object` 捞日志，
  stdout 不是 UTF-8 逐行就会变乱码）。

## 沙箱镜像维护

`.sandcastle/Dockerfile` 只预装 Python 3.11 + pytest；仓库代码本身零第三方
依赖。**若某张票引入了第三方包，同步加进 Dockerfile 并重建镜像**，否则沙箱内
import 失败白烧一轮。
