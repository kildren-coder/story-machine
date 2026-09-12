// AFK 编排器:取一个 ready-for-agent 的 issue → 沙箱里实现 → 沙箱里评审 →
// 推分支开 PR。AFK 的边界是"绿的 PR":合并由人决定;合并后拿 vault 里的真实
// 样例(EP02)跑一次相关层、看效果,也是人在交互式会话里做——沙箱里没有 vault,
// 也不许自己调 claude -p 烧额度。
//
// 与 agent-alert 的 .sandcastle/afk.ts 同源(设计论证与事故复盘见该仓库
// .exp/2026-07-21-afk-unattended-automation.md)。下面注释里出现的 #26/#30/#37
// 一类票号都是 agent-alert 的事故票,不是本仓库的 issue。两个项目共用同一个
// 5h 额度池,而 QuotaTracker 只看得见本进程的消耗——**同一晚只跑一个项目的
// --loop**,双开会互相看不见对方,双双低估、双双撞墙。
//
// 用法(在 .sandcastle/ 目录下)。注意 `--` 加了引号:PowerShell 会吞掉裸的
// `--` 分隔符,连带后面的参数一起丢(argv 变空,--loop/--max 全失效)。写成
// `'--'` 在 PowerShell 里保得住,在 bash 里被剥引号后等价于裸 `--`,两个 shell 通用。
//   npm run afk                    # frontier query 自动取号(半成品优先),跑一票
//   npm run afk '--' 20            # 指定 issue #20
//   npm run afk '--' 20 --dry-run  # 只报告会走全新还是续跑、注入哪些反馈,不起沙箱
//   npm run afk '--' 20 --fresh    # 强制全新实现:先把半成品分支退役再从头跑
//   npm run afk '--' --loop        # 串行循环:一票接一票,直到 frontier 空或额度到门槛
//   npm run afk '--' --loop --max 3  # 循环但最多跑 3 票
//   npm run afk '--' --quota       # 只打印当前额度判定(验证落盘数据用),不跑
//
// 全新还是续跑由分支状态自动判定,不需要人记住哪张票做到一半——见 detectMode。
// 没有 --continue:探测到半成品本来就会续,加个开关只是让人多记一件事。
//
// --loop 是给睡觉时段用的:一个 5h 额度窗口跑不满可惜,跑一半断掉更糟。额度
// 判定见 quota.ts;事前拦截为主(每取下一票之前查一次),撞限识别为兜底。
//
// 前置:Docker Desktop 运行中;.sandcastle/.env 已按 .env.example 填好;
// 宿主机 gh 已登录(host 侧取 issue、推分支、开 PR 用的是它)。

import "./env.ts"; // 必须是第一个 import:先加载 .env,再让 quota.ts 等模块求值其常量
import { execFileSync } from "node:child_process";
import { appendFileSync, existsSync, mkdirSync, readFileSync, rmSync } from "node:fs";
import { join, resolve } from "node:path";
import { claudeCode, createSandbox } from "@ai-hero/sandcastle";
import type { AgentStreamEvent, IterationResult } from "@ai-hero/sandcastle";
import { docker } from "@ai-hero/sandcastle/sandboxes/docker";
import { QuotaTracker, STOP_PERCENT, describe, lastRequestCount, looksLikeQuotaExhaustion, median, sessionStats } from "./quota.ts";

const REPO = "kildren-coder/story-machine";
const here = import.meta.dirname;
const repoRoot = resolve(here, "..");

// ── 本体日志:编排器自己的控制台也镜像落盘 ─────────────────────────
// 子 agent 的输出进 logs/issue-*.log,但 afk 本体(取号、额度判定、收工、被
// 信号中断)以前只打到终端。终端一旦被外部干掉(VS Code 重载、关标签、系统
// 事件),进程连带静默退出、什么都不留——2026-07-22 就这么丢过一次停机线索,
// 只能靠反推。把 console 镜像一份到文件,这个死角补上。
const runLogStamp = ((): string => {
  const p = (n: number) => String(n).padStart(2, "0");
  const d = new Date();
  return `${d.getFullYear()}${p(d.getMonth() + 1)}${p(d.getDate())}-${p(d.getHours())}${p(d.getMinutes())}${p(d.getSeconds())}`;
})();
const runLogPath = join(here, "logs", `afk-${runLogStamp}.log`);
mkdirSync(join(here, "logs"), { recursive: true });
for (const level of ["log", "warn", "error"] as const) {
  const orig = console[level].bind(console);
  console[level] = (...args: unknown[]): void => {
    orig(...args);
    try {
      appendFileSync(runLogPath, `${args.map((a) => (typeof a === "string" ? a : String(a))).join(" ")}\n`);
    } catch {}
  };
}

// ── 自持临时目录:绝不用系统 %TEMP% ────────────────────────────────
// sandcastle 在 Windows + worktree 模式下,会把改写过 gitdir: 的 .git 文件
// 写进 os.tmpdir(),再把这**单个文件** bind-mount 进容器当
// /home/agent/workspace/.git。Docker 的 bind mount 按路径绑定而非文件句柄:
// 宿主机上把源文件删掉,挂载不会重建也不报错,直接变悬空。
//
// 2026-07-20 09:45:16,第三方垃圾清理软件(腾讯电脑管家/火绒一类,非 Windows
// 自带清理——那些的计划任务时间对不上)一次性扫光了 %TEMP%\sandcastle-git-*
// 下的全部文件。当时 #26 的容器还活着,容器内 .git 当场蒸发,agent 提交 QA
// 文档失败;收尾 docker cp 抓 session 记录时 daemon 重新解析这个悬空挂载,
// mkdir 撞 EEXIST,SessionCaptureError 未被捕获,整个编排进程崩掉。
// 这个竞态一直存在,前几次 run 只是都在清理发生前就收工了。
//
// 把 tmpdir 挪进项目目录,清理软件扫不到。Node 的 os.tmpdir() 在 win32 上读
// TEMP/TMP,且 sandcastle 是在 createSandbox 内部才调用它,所以在这里赋值
// 来得及。按 pid 分目录:并行跑多个 afk 时各用各的,收尾删自己那份绝不会
// 拔掉别人正在挂载的文件(这正是本次事故的成因,不能在修复里重演)。
const runTmpDir = join(here, ".tmp", `run-${process.pid}`);
mkdirSync(runTmpDir, { recursive: true });
process.env.TEMP = runTmpDir;
process.env.TMP = runTmpDir;

// .env 的加载已提到 import 期(见首个 import 的 ./env.ts)——必须早于 quota.ts
// 那几个模块级常量求值,否则 .env 里的 AFK_UNITS_PER_PERCENT 等覆盖不生效。
const IMPLEMENT_MODEL = process.env.AFK_IMPLEMENT_MODEL ?? "claude-sonnet-5";
// 评审用 opus:冷读 diff 判验收是判断密集型,比实现更吃模型;实现留 sonnet 控成本。
const REVIEW_MODEL = process.env.AFK_REVIEW_MODEL ?? "claude-opus-4-8";
const EFFORT = (process.env.AFK_EFFORT ?? "high") as "low" | "medium" | "high" | "xhigh" | "max";

function gh(...args: string[]): string {
  return execFileSync("gh", args, {
    encoding: "utf8",
    cwd: repoRoot,
    maxBuffer: 32 * 1024 * 1024,
  });
}

function git(...args: string[]): string {
  return execFileSync("git", args, { encoding: "utf8", cwd: repoRoot });
}

// 取分支上某个文件的内容;文件不存在返回 undefined(agent 漏交不该让整个
// run 崩掉,PR 里留一条醒目的缺失提示即可)。
function showOnBranch(branch: string, path: string): string | undefined {
  try {
    // stderr 吞掉:文件不存在是**预期内**的常态(第一轮还没有摘要),但 git 会往
    // 终端喷一行 `fatal: path ... does not exist`,看着像出事了其实什么事都没有。
    return execFileSync("git", ["show", `${branch}:${path}`], {
      encoding: "utf8",
      cwd: repoRoot,
      stdio: ["ignore", "pipe", "ignore"],
    }).trim() || undefined;
  } catch {
    return undefined;
  }
}

function refExists(ref: string): boolean {
  try {
    git("rev-parse", "--verify", "--quiet", ref);
    return true;
  } catch {
    return false;
  }
}

// 基准优先用 origin/main:本地 main 可能落后好几个已合并的 PR,拿它当基准会把
// 「早就合并进去的 commit」算成「分支上还没做完的工作」,探测直接失准。
function baseRef(): string {
  return refExists("refs/remotes/origin/main") ? "origin/main" : "main";
}

function resolveRef(branch: string): string {
  return refExists(`refs/heads/${branch}`) ? branch : `origin/${branch}`;
}

// ── 分支即状态 ────────────────────────────────────────────────────
// 约定:`agent/issue-<n>` 这个名字**只表示「可以接着做的半成品」**。人不需要
// 记住哪个 issue 该续跑——探测分支就知道了。
//
// 代价是这个名字必须保持干净:方向被评审否掉(REJECTED)、或对应 PR 已合并/
// 已关闭的分支,都要改名退役,把名字腾出来。否则下一轮探测会把一具尸体当成
// 半成品接着做,那比不探测更坏。
function retireBranch(branch: string, reason: string): void {
  const stamp = new Date().toISOString().replace(/[-:]/g, "").slice(0, 15);
  const dead = `${branch}-${reason}-${stamp}`;
  if (refExists(`refs/remotes/origin/${branch}`)) {
    try {
      git("push", "origin", `refs/remotes/origin/${branch}:refs/heads/${dead}`);
      git("push", "origin", "--delete", branch);
    } catch {}
  }
  if (refExists(`refs/heads/${branch}`)) {
    releaseWorktreeHolding(branch); // 必须在改名前:理由见该函数注释
    try {
      git("branch", "-m", branch, dead);
    } catch {}
  }
  console.log(`分支 ${branch} 退役为 ${dead}(${reason})`);
}

// 哪个 worktree 正 checkout 着这个分支(没有则 undefined)。
function worktreeHolding(branch: string): string | undefined {
  let current: string | undefined;
  try {
    for (const line of git("worktree", "list", "--porcelain").split("\n")) {
      if (line.startsWith("worktree ")) current = line.slice(9).trim();
      else if (line.trim() === `branch refs/heads/${branch}`) return current;
    }
  } catch {}
  return undefined;
}

// 退役前必须先把分支从 worktree 上摘干净,否则 `git branch -m` 会把那个
// worktree 的 HEAD **一起**拖到退役名下——git 就是这么设计的,改名对 checkout
// 着它的工作树是透明的。
//
// 为什么会有 worktree 还占着待退役分支这种局面:上一轮崩在半路(idle timeout、
// 额度墙),removeWorktree 见有未提交改动就手下留情把 worktree 留了下来(那是
// 特性,#26 的 QA 文档就是这样捞回来的)。下一轮开局探测发现分支是空壳 →
// retire("empty") → 改名 → 残留 worktree 跟着改姓。
//
// 而 sandcastle 复用 worktree 只认**路径**(worktrees/agent-issue-N),不校验它
// 实际 checkout 在哪个分支,于是这一整轮的 commit 全落进退役分支,收尾按
// `refs/heads/agent/issue-N` 收集时一无所获,报成「实现 agent 没有产生
// commit」。#37 连着两轮整轮白跑(其中一轮已经全绿并写完 QA 文档)就是这么来的。
//
// 摘的办法不是删掉 worktree 了事——那会把上一轮没提交的产物一起扔掉,正是
// removeWorktree 手下留情要避免的。先把未提交改动落成一个 WIP commit(提交在
// 即将退役的分支上,墓地本来就是给人捞东西的地方,`git show` 一条命令就能看),
// worktree 因此变干净,再正常撤掉。产物不丢,名字腾干净,下一轮 sandcastle 从零
// 建 worktree,错位链从根上断掉。
function releaseWorktreeHolding(branch: string): void {
  const path = worktreeHolding(branch);
  if (!path) return;
  const managed = join(here, "worktrees").replace(/\\/g, "/").toLowerCase();
  if (!path.replace(/\\/g, "/").toLowerCase().startsWith(managed)) return; // 主工作树/别人的,不碰
  try {
    if (git("-C", path, "status", "--porcelain").trim()) {
      git("-C", path, "add", "-A");
      git("-C", path, "commit", "--no-verify", "-m", `WIP: ${branch} 退役前自动保存的未提交产物`);
      console.log(`退役前把 ${path} 的未提交改动落成 WIP commit 备查`);
    }
    git("worktree", "remove", "--force", path);
    git("worktree", "prune");
  } catch {}
}

// 「零 commit」有两种成因,报错时必须分开说,否则人只会当成 agent 摸鱼,重跑一
// 轮再白烧一轮额度:
//   a) agent 真的什么都没干 —— 分支在,但是空的;
//   b) commit 落到了别的分支上 —— 收尾按 `refs/heads/<branch>` 收集,而 worktree
//      当时 checkout 在别处(成因见 releaseWorktreeHolding)。
// (b) 的证据是同族退役分支 `<branch>-*` 上有领先基准的内容。这些 commit 是完好
// 的,改个名就能救回来,不必重跑——所以直接把分支名和 commit 数写进报错。
function strayCommitHint(branch: string): string {
  const notes: string[] = [];
  if (!refExists(`refs/heads/${branch}`)) notes.push(`分支 ${branch} 不存在`);
  try {
    const dead = git("for-each-ref", "--format=%(refname:short)", "refs/heads")
      .split("\n")
      .map((s) => s.trim())
      .filter((s) => s.startsWith(`${branch}-`));
    for (const d of dead) {
      const count = Number(git("rev-list", "--count", `${baseRef()}..${d}`).trim());
      if (count > 0) notes.push(`退役分支 ${d} 上有 ${count} 个领先 ${baseRef()} 的 commit`);
    }
  } catch {}
  if (notes.length === 0) return "";
  return `\n  ⚠ ${notes.join(";")}——commit 疑似落错分支(见 releaseWorktreeHolding 注释),改名归位即可,不必重跑。`;
}

// ── 收尾清理 ──────────────────────────────────────────────────────
// 正常路径下 sandcastle 自己会撤容器、撤 worktree。但它的清理挂在
// `await using` 的 dispose 上,而 dispose 本身就可能崩(#26 就崩在里面),
// 那一崩后面的清理全不执行,残留一次次累积。所以在编排器层再兜一道,放在
// finally 里,无论成功失败/抛没抛都跑。清理本身绝不抛,免得盖掉真正的错因。
let runBranch: string | undefined; // 供 cleanupHost 定位 worktree
// REJECTED 时要把本地分支改名退役,但分支此刻还被 worktree 占着,所以推迟到
// worktree 撤掉之后再做。远端那边在 REJECTED 分支里已经就地处理完了。
let deferredRetire: { branch: string; reason: string } | undefined;

// 一票收尾。--loop 下每票跑完都要做:worktree 必须撤掉,否则下一票的
// `git worktree add` 会撞上同一个 worktrees/ 目录;tmp 里的 .git 文件也得清,
// 但目录要留着——sandcastle 下一票还往 process.env.TEMP 里写。
function cleanupRun(): void {
  removeWorktree();

  if (deferredRetire && refExists(`refs/heads/${deferredRetire.branch}`)) {
    const stamp = new Date().toISOString().replace(/[-:]/g, "").slice(0, 15);
    // 上面的 removeWorktree 可能因为有未提交改动把 worktree 留下了,那它此刻
    // 还占着这个分支——同 retireBranch,改名前必须先摘,否则 worktree 跟着改姓。
    releaseWorktreeHolding(deferredRetire.branch);
    try {
      git("branch", "-m", deferredRetire.branch, `${deferredRetire.branch}-${deferredRetire.reason}-${stamp}`);
    } catch {}
  }
  runBranch = undefined;
  deferredRetire = undefined;

  try {
    rmSync(runTmpDir, { recursive: true, force: true });
    mkdirSync(runTmpDir, { recursive: true });
  } catch {}
}

function cleanupHost(): void {
  cleanupRun();
  // 自己那份 tmp:独占,闭眼删。
  try {
    rmSync(runTmpDir, { recursive: true, force: true });
  } catch {}
}

function removeWorktree(): void {
  if (!runBranch) return;
  const worktreePath = join(here, "worktrees", runBranch.replace(/\//g, "-"));
  if (!existsSync(worktreePath)) return;
  try {
    // 有未提交改动就留着——sandcastle 也是这么做的,那是特性不是泄漏:
    // 崩了以后 agent 写了没来得及提交的东西全靠它捞回来(#26 的
    // docs/qa/issue-26.md 就是这样活下来的)。别手快删掉别人的活。
    if (git("-C", worktreePath, "status", "--porcelain").trim()) {
      console.log(`worktree 有未提交改动,保留备查:${worktreePath}`);
      return;
    }
    git("worktree", "remove", "--force", worktreePath);
    git("worktree", "prune");
  } catch {}
}

interface IssueRef {
  number: number;
  title: string;
}

// 距上一行输出过去了多久。给的是**持续时间**不是绝对钟点:分析时一眼看出哪步慢,
// 不用自己去减两个时间戳(减法要么占脑子、要么让分析的 agent 烧 token 算)。
// <60s 给到 0.1s,超过就 `+2m05s`。定宽补齐,左边自成一列好扫。
function dur(ms: number): string {
  const s = ms / 1000;
  const raw = s < 60 ? `+${s.toFixed(1)}s` : `+${Math.floor(s / 60)}m${String(Math.round(s % 60)).padStart(2, "0")}s`;
  return raw.padEnd(8);
}

// 灰箱:把 agent 的输出流(叙述文本 + 每个工具调用)实时转发到终端。
// 这是对已有流的旁路转发,不产生任何额外 token、agent 也感知不到。
// 完整原始流仍在 logs/ 下的日志文件里。
//
// 每行开头的 `+Ns` = 距上一行的间隔。一次工具调用的耗时体现在**它之后那一行**的
// `+Ns` 上(下一行要等工具返回才发),所以 `Bash(pytest…)` 后面跟着 `+92.3s` 就是
// 那次 pytest 跑了 92 秒。计时只在真正打印出一行时推进,空文本事件不算进去。
function liveLog(phase: string): (event: AgentStreamEvent) => void {
  let last = Date.now();
  const emit = (iter: number, body: string, lead = ""): void => {
    const now = Date.now();
    process.stdout.write(`${lead}${dur(now - last)}[${phase}·第${iter}轮] ${body}\n`);
    last = now;
  };
  return (event) => {
    if (event.type === "text") {
      const msg = event.message.trim();
      if (msg) emit(event.iteration, msg, "\n");
    } else if (event.type === "toolCall") {
      const args = event.formattedArgs.replace(/\s+/g, " ").slice(0, 1000);
      emit(event.iteration, `→ ${event.name}(${args})`);
    }
  };
}

// 每轮的 context 占用。
//
// 只报收尾值不够:那是一轮的**峰值**(context 在一轮内单调增长),它告诉你水位
// 爬到过哪儿,不告诉你在高位待了多久。中位数补上后一半——峰值高但中位数低,说明
// 只是末尾冲了一下;两个都高,说明整轮大半时间都在退化区里做判断,那一轮的产出
// 质量本身就要打问号。
//
// context 占用 = input + cache读 + cache写:同一份 prompt 按计费方式拆开的账目。
// output 是模型的回复,不占已发送的 prompt,故不计入。
const CONTEXT_WINDOW = 200_000;
function printUsage(phase: string, iterations: IterationResult[]): void {
  const k = (n: number) => (n >= 1000 ? `${(n / 1000).toFixed(1)}k` : String(n));
  const pct = (n: number) => `${Math.round((n / CONTEXT_WINDOW) * 100)}%`;
  iterations.forEach((it, i) => {
    const s = it.sessionFilePath ? sessionStats(it.sessionFilePath) : undefined;
    if (s) {
      const peak = Math.max(...s.contexts);
      const mid = median(s.contexts);
      console.log(
        `[${phase}] 第${i + 1}轮 ${s.requests} 次请求,context 峰值 ${k(peak)}(${pct(peak)})` +
          `/中位 ${k(mid)}(${pct(mid)})`,
      );
      return;
    }
    // 退回快照:只有收尾那一次请求,拿不到中位数。
    const u = it.usage;
    if (!u) return;
    const ctx = u.inputTokens + u.cacheReadInputTokens + u.cacheCreationInputTokens;
    console.log(`[${phase}] 第${i + 1}轮收尾 context ${k(ctx)}(${pct(ctx)})(无会话文件,仅末次请求)`);
  });
}

// 哪些 issue 号在分支上留着未完的工作。只看「分支在不在、有没有领先 main」,
// 不查 PR——这里只用于排序,精确分类留到真正领到票时的 detectMode。
function halfDoneIssues(): Set<number> {
  const out = new Set<number>();
  let refs: string[];
  try {
    refs = git(
      "for-each-ref", "--format=%(refname:short)",
      "refs/heads/agent/", "refs/remotes/origin/agent/",
    ).split(/\r?\n/);
  } catch {
    return out;
  }
  const base = baseRef();
  for (const r of refs) {
    const m = r.match(/^(?:origin\/)?agent\/issue-(\d+)$/); // 带后缀的退役分支不匹配
    if (!m) continue;
    try {
      if (Number(git("rev-list", "--count", `${base}..${r}`).trim()) > 0) out.add(Number(m[1]));
    } catch {}
  }
  return out;
}

// docs/agents/issue-tracker.md 的 frontier query:开放的 ready-for-agent、
// 无 assignee、无未关闭的 blocker(GitHub 原生 issue dependencies)。
//
// 排序:**半成品优先**,同类内再取最小号。否则一旦有票在半路被打断(额度耗尽、
// 崩溃、被打回返工),循环每次都会去挑更小号的新票,攒下一堆开了头没做完的分支。
//
// `skip` 是循环模式的必要保险:这一轮已经处理过的票不能再取。失败、REJECTED
// 都会撤掉 assignee 把票放回 frontier,而半成品优先又会把它顶到队首——不排除
// 就是原地死循环,反复撞同一堵墙。
function pickIssue(explicit?: number, skip: Set<number> = new Set()): IssueRef | undefined {
  if (explicit !== undefined) {
    const it = JSON.parse(gh("api", `repos/${REPO}/issues/${explicit}`));
    return { number: it.number, title: it.title };
  }
  const items: any[] = JSON.parse(
    gh("api", `repos/${REPO}/issues?labels=ready-for-agent&state=open&per_page=100`),
  );
  const halfDone = halfDoneIssues();
  const frontier = items
    .filter(
      (i) =>
        !i.pull_request &&
        !skip.has(i.number) &&
        (i.assignees?.length ?? 0) === 0 &&
        (i.issue_dependencies_summary?.blocked_by ?? 0) === 0,
    )
    .sort((a, b) => {
      const ha = halfDone.has(a.number) ? 0 : 1;
      const hb = halfDone.has(b.number) ? 0 : 1;
      return ha !== hb ? ha - hb : a.number - b.number;
    });
  if (frontier.length === 0) return undefined;
  return { number: frontier[0].number, title: frontier[0].title };
}

interface PrRef {
  number: number;
  url: string;
  state: string;
}

type Mode =
  | { kind: "fresh" }
  | { kind: "continue"; pr?: PrRef; feedback: string; count: number };

// 从分支状态推断这一轮该怎么跑。人不需要记住也不需要敲 flag:
//   有 commit 领先 main + 有开着的 PR  → A 类返工(注入反馈)
//   有 commit 领先 main + 没有 PR      → 上一轮被打断(额度/崩溃),接着做完
//   没分支 / PR 已合并或关闭 / 分支是空的 → 全新实现
function detectMode(branch: string, issueComments: any[], dryRun = false): Mode {
  // dry-run 下只报告不改分支:探测本身要能随便跑,不能有副作用。
  const retire = (reason: string) =>
    dryRun ? console.log(`(dry-run)分支 ${branch} 本应退役(${reason})`) : retireBranch(branch, reason);

  if (!refExists(`refs/heads/${branch}`) && !refExists(`refs/remotes/origin/${branch}`)) {
    return { kind: "fresh" };
  }
  const ref = resolveRef(branch);
  if (Number(git("rev-list", "--count", `${baseRef()}..${ref}`).trim()) === 0) {
    retire("empty"); // 空壳分支,占着名字没有内容
    return { kind: "fresh" };
  }

  const prs: PrRef[] = JSON.parse(
    gh("pr", "list", "--head", branch, "--state", "all", "--limit", "10", "--json", "number,url,state"),
  );
  const open = prs.find((p) => p.state === "OPEN");
  if (!open && prs.length > 0) {
    // PR 已合并或已关闭 ⇒ 这个分支的活儿结束了。issue 还开着(合并 PR 与关闭
    // issue 本就解耦)说明是新一轮工作,不该在旧分支上叠。
    retire(prs.some((p) => p.state === "MERGED") ? "merged" : "closed");
    return { kind: "fresh" };
  }

  // 反馈 = 前一轮最后一个 commit **之后**出现的言论。更早的都是上一轮已经消化
  // 过的,再喂一遍只会让 agent 去改早就改好的东西。
  const sinceMs = Date.parse(git("log", "-1", "--format=%cI", ref).trim());
  const items: { at: number; from: string; body: string }[] = [];
  const take = (at: string | undefined, from: string, body: string | undefined, author?: string) => {
    if (!at || !body?.trim()) return;
    const ms = Date.parse(at);
    if (ms > sinceMs) items.push({ at: ms, from: author ? `${from}·${author}` : from, body });
  };
  for (const c of issueComments) take(c.createdAt, "issue 评论", c.body, c.author?.login);
  if (open) {
    const d = JSON.parse(gh("pr", "view", String(open.number), "--json", "comments,reviews"));
    for (const c of d.comments ?? []) take(c.createdAt, "PR 评论", c.body, c.author?.login);
    for (const r of d.reviews ?? []) take(r.submittedAt, "PR 评审", r.body, r.author?.login);
  }
  items.sort((a, b) => a.at - b.at);

  const feedback = items.length
    ? items
        .map((i) => `### 来自${i.from}(${new Date(i.at).toISOString().slice(0, 10)})\n\n${i.body}`)
        .join("\n\n")
    : "**没有新反馈。** 上一轮是被打断的,不是被打回的——按「被打断的续跑」处理:" +
      "逐条对着验收标准查已有实现和测试,把还没做完的部分补上。";
  return { kind: "continue", pr: open, feedback, count: items.length };
}

// PR body 分两层,按海拔排:
//   顶部 = 评审 agent 写的 300 字摘要(为什么做/改了什么/效果/最大风险),
//          给"要在几分钟内决定合不合的人"看;
//   折叠 = QA 文档全文(改动摘要、验收标准↔测试对照、真实样例验证指引),
//          给评审细节和合并后跑真实样例的人看。
// 细节一个字没少,只是收进 <details>,免得把摘要压到屏幕外。
function buildPrBody(n: string, brief: string, qaDoc: string): string {
  return [
    `Closes #${n}`,
    "",
    brief,
    "",
    "---",
    "",
    "AFK sandcastle run:实现 + 评审两轮 agent,`bash scripts/test.sh` 在沙箱内全绿。",
    "合并前请人工过 diff;合并后按 QA 文档的指引用 vault 里的 EP02 真实样例跑一次相关层(不在本 PR 范围)。",
    "",
    "<details>",
    "<summary>QA 文档(验收标准↔测试对照,含真实样例验证指引)</summary>",
    "",
    qaDoc,
    "",
    "</details>",
    "",
    "🤖 Generated with [Claude Code](https://claude.com/claude-code)",
  ].join("\n");
}

type Outcome = "done" | "blocked" | "rejected" | "failed" | "quota-exhausted" | "env-broken" | "auth-broken";

// 环境坏了 ≠ 这一票做失败了。2026-07-21 那次 `gh issue edit --add-assignee` 撞上
// 代理抽风(dial tcp 28.0.0.131:443 —— Clash 的 fake-IP),整个 run 在沙箱起来前
// 就带着一坨堆栈崩了。这和撞限是同一类误判:在 --loop 下,把它当"这票失败"会让
// 循环拿下一票去撞同一堵墙,而 GitHub 不通时 Claude API 多半也不通,后面每一票
// 都注定白跑。所以认出来 → 停循环 → 只打一行原因。
const ENV_BROKEN = [
  /dial tcp/i,
  /connectex/i,
  /ECONNREFUSED|ECONNRESET|ETIMEDOUT|ENOTFOUND|EAI_AGAIN/,
  /connection (?:refused|reset|timed out)/i,
  /could not resolve host/i,
  /(?:docker )?daemon.{0,40}(?:not running|cannot connect)/i,
  /cannot connect to the docker daemon/i,
];

function looksLikeEnvBroken(text: string): boolean {
  return ENV_BROKEN.some((re) => re.test(text));
}

// 认证失效又是一类误判,和撞限、环境不通同族:不是这一票的错,换票也没用——
// token 不换,下一票还是同一个 401。2026-07-22 头一次真跑 --loop 就撞上:启动检查
// 只看 token 在不在(在),沙箱里第一次真调 API 才 401 —— `sk-ant-oat01` 这种
// setup-token 会过期/被吊销。归成"这票失败"的话,#31 分支被当坏票改名退役,循环
// 再拿 #32 去撞同一堵墙。和 env-broken 分开是因为**修法不同**:这个要重开 token,
// 不是修网络,消息得说清楚往哪儿使劲。
const AUTH_BROKEN = [
  /invalid authentication/i,
  /invalid api key/i,
  /authentication[_ ]?error/i,
  /401\b.{0,40}(?:auth|credential|api key)/i,
  /oauth token.{0,30}(?:expired|invalid|revoked)/i,
];

function looksLikeAuthBroken(text: string): boolean {
  return AUTH_BROKEN.some((re) => re.test(text));
}

// 日志尾巴:撞限时 agent 往往不是抛异常,而是安静地结束、什么信号都没有。
// 真正的错因只在日志里,所以要去日志尾巴上认。
function tailLog(path: string | undefined, bytes = 20_000): string {
  if (!path || !existsSync(path)) return "";
  try {
    const s = readFileSync(path, "utf8");
    return s.slice(-bytes);
  } catch {
    return "";
  }
}

// 跑一票:实现 → 评审 → 开 PR(续跑则刷新原 PR)。
// 不做收尾——worktree / tmp / 延迟退役交给调用方的 finally,循环模式下每票一次。
async function runOne(
  issue: IssueRef,
  opts: { forceFresh: boolean; dryRun: boolean; quota: QuotaTracker },
): Promise<{ outcome: Outcome; error?: unknown }> {
  const { forceFresh, dryRun, quota } = opts;
  const n = String(issue.number);
  console.log(`领取 issue #${n}:${issue.title}`);

  const detail = JSON.parse(gh("issue", "view", n, "--json", "title,body,comments"));
  const branch = `agent/issue-${n}`;

  let mode: Mode;
  if (forceFresh) {
    // 强制全新就得真的全新:分支还在的话 worktree 会直接 checkout 它,新 agent
    // 会在旧 commit 上继续叠——那不是 fresh。先把它退役让开。
    if (!dryRun && (refExists(`refs/heads/${branch}`) || refExists(`refs/remotes/origin/${branch}`))) {
      retireBranch(branch, "superseded");
    }
    mode = { kind: "fresh" };
  } else {
    mode = detectMode(branch, detail.comments ?? [], dryRun);
  }

  if (mode.kind === "continue") {
    console.log(
      `#${n} 检测到半成品分支 ${branch}` +
        (mode.pr ? `(已有 PR #${mode.pr.number})→ 返工模式` : "(无 PR,上一轮被打断)→ 续跑模式") +
        `,注入 ${mode.count} 条反馈。`,
    );
  } else {
    console.log(forceFresh ? `#${n} --fresh:强制按全新实现跑。` : `#${n} 全新实现。`);
  }

  const promptArgs = {
    ISSUE_NUMBER: n,
    ISSUE_TITLE: detail.title ?? "",
    ISSUE_BODY: detail.body || "(空)",
    ISSUE_COMMENTS:
      // 带作者和日期:prompt 说"以最新为准",但没有时间戳 agent 分不清哪条新;
      // 没有作者则分不清"人拍板的决策"和"前一轮 agent 的 BLOCKED 提问"。
      (detail.comments ?? [])
        .map((c: any) => `### ${c.author?.login ?? "(未知)"} @ ${(c.createdAt ?? "").slice(0, 10)}\n\n${c.body}`)
        .join("\n\n---\n\n") || "(无评论)",
    FEEDBACK: mode.kind === "continue" ? mode.feedback : "(不适用:本轮是全新实现。)",
  };

  if (dryRun) {
    console.log("--dry-run:只做探测,不起沙箱。");
    if (mode.kind === "continue") {
      console.log(`prompt = continue.md,注入的反馈:\n${"─".repeat(60)}\n${mode.feedback}\n${"─".repeat(60)}`);
    } else {
      console.log("prompt = implement.md");
    }
    return { outcome: "done" };
  }

  const briefPath = `docs/qa/issue-${n}-brief.md`;
  const qaPath = `docs/qa/issue-${n}.md`;
  // 上一版摘要要在动工**之前**抓下来:它描述的是刷新前的代码,跑完就被覆盖了。
  const prevBrief = mode.kind === "continue" ? showOnBranch(resolveRef(branch), briefPath) : undefined;

  runBranch = branch;
  const logDir = join(here, "logs");
  mkdirSync(logDir, { recursive: true });
  // 沙箱内 agent 需要 GH_TOKEN 才能在受阻时评论 issue;宿主机侧的 gh 走本机登录。
  //
  // Bash 超时给足,是**机制层**堵死后台化:agent 是串行的,跑测试时没有别的活
  // 能并行,后台化换不来任何东西,反而常诱发它手搓轮询空转、每轮重发上下文白烧
  // 额度(agent-alert #30)。前台阻塞跑保证零浪费。本仓库的离线测试是秒级的,
  // 这个上限纯粹是裕量。
  //
  // 容器出网:本机 Clash TUN 通常透明代理容器流量;不通时在 .env 设
  // AFK_SANDBOX_PROXY 显式走代理(编码期 agent 只需要到得了 Claude API 与 GitHub)。
  const proxy = process.env.AFK_SANDBOX_PROXY;
  const agentEnv = {
    ...(process.env.GH_TOKEN ? { GH_TOKEN: process.env.GH_TOKEN } : {}),
    ...(proxy ? { HTTPS_PROXY: proxy, HTTP_PROXY: proxy } : {}),
    BASH_DEFAULT_TIMEOUT_MS: "600000",
    BASH_MAX_TIMEOUT_MS: "1200000",
  };

  // 撞限往往不是抛异常:agent 安静地结束、一个 completionSignal 都没给,错因
  // 只在日志尾巴上。认出来才能让外层循环停下,而不是拿下一票去撞同一堵墙。
  const hitQuotaWall = (r: { completionSignal?: string; logFilePath?: string }): boolean =>
    !r.completionSignal && looksLikeQuotaExhaustion(tailLog(r.logFilePath));

  try {
    // claim(issue-tracker.md 约定的首个写操作)。放在 try 里面:它以前在外面,
    // 2026-07-21 这一行撞上代理抽风,直接把整个进程带走了——连"这票没做成"这个
    // 结论都没留下,--loop 下一夜就到此为止。
    gh("issue", "edit", n, "--add-assignee", "@me");

    await using sandbox = await createSandbox({
      branch,
      // 新分支从 main 拉,**不能用默认的 HEAD**。2026-07-21 #30 那次就是在
      // afk/pr-brief 上起跑的,agent/issue-30 直接继承了 4 个无关的 AFK commit:
      // PR 会混进无关改动,而且 agent 真去读了 .sandcastle/ 和 .exp/ 的 diff
      // ——prompt 明令禁止它碰的两个目录,却被 diff 送到了它眼前。
      // 分支已存在时(续跑)这个参数被忽略,不影响复跑。
      baseBranch: baseRef(),
      sandbox: docker(),
      cwd: repoRoot,
    });

    const impl = await sandbox.run({
      agent: claudeCode(IMPLEMENT_MODEL, { effort: EFFORT, permissionMode: "bypassPermissions", env: agentEnv }),
      // 续跑走独立 prompt:implement.md 写着"你的交付物是这个分支上的一串
      // commit",冷读它的 agent 会以为要从头实现。范围窄,轮数也少给。
      promptFile: join(here, "prompts", mode.kind === "continue" ? "continue.md" : "implement.md"),
      promptArgs,
      maxIterations: mode.kind === "continue" ? 30 : 50,
      // agent-alert 那边默认 600s 曾杀掉"等全量 pytest"的 agent(#37 两轮全损)。
      // 本仓库测试秒级,20min 纯属裕量;真死循环靠 maxIterations 兜底。
      idleTimeoutSeconds: 1200,
      completionSignal: ["<promise>COMPLETE</promise>", "<promise>BLOCKED</promise>"],
      logging: {
        type: "file",
        path: join(logDir, `issue-${n}-implement.log`),
        onAgentStreamEvent: liveLog("实现"),
      },
      name: `implement-${n}`,
    });
    printUsage("实现", impl.iterations);
    console.log(`[实现] 本轮 ${(quota.add(impl.iterations) / 1000).toFixed(0)}k 加权成本单位,${lastRequestCount} 次 API 请求`);

    if (hitQuotaWall(impl)) {
      gh("issue", "edit", n, "--remove-assignee", "@me");
      console.log(`#${n} 实现阶段疑似撞额度上限(日志:${impl.logFilePath})。分支与 commit 保留,下个窗口会自动续跑。`);
      return { outcome: "quota-exhausted" };
    }
    if (impl.completionSignal?.includes("BLOCKED")) {
      gh("issue", "edit", n, "--remove-label", "ready-for-agent", "--add-label", "needs-info");
      gh("issue", "edit", n, "--remove-assignee", "@me");
      console.log(`#${n} 受阻:已转 needs-info,agent 的问题见 issue 评论。`);
      return { outcome: "blocked" };
    }
    // 全新实现零 commit = 什么都没做,是故障。续跑零 commit 未必:分支上本就
    // 有工作,agent 可能核对后判定没有需要改的。交给评审去判断做没做完。
    if ((!impl.commits || impl.commits.length === 0) && mode.kind === "fresh") {
      throw new Error(
        `实现 agent 结束但没有产生 commit,日志:${impl.logFilePath}${strayCommitHint(branch)}`,
      );
    }

    const rev = await sandbox.run({
      agent: claudeCode(REVIEW_MODEL, { effort: EFFORT, permissionMode: "bypassPermissions", env: agentEnv }),
      promptFile: join(here, "prompts", "review.md"),
      promptArgs,
      maxIterations: 3,
      // 同上。
      idleTimeoutSeconds: 1200,
      completionSignal: ["<promise>COMPLETE</promise>", "<promise>REJECTED</promise>"],
      logging: {
        type: "file",
        path: join(logDir, `issue-${n}-review.log`),
        onAgentStreamEvent: liveLog("评审"),
      },
      name: `review-${n}`,
    });
    printUsage("评审", rev.iterations);
    console.log(`[评审] 本轮 ${(quota.add(rev.iterations) / 1000).toFixed(0)}k 加权成本单位,${lastRequestCount} 次 API 请求`);

    if (hitQuotaWall(rev)) {
      gh("issue", "edit", n, "--remove-assignee", "@me");
      console.log(`#${n} 评审阶段疑似撞额度上限(日志:${rev.logFilePath})。实现的 commit 保留,下个窗口续跑时会重走评审。`);
      return { outcome: "quota-exhausted" };
    }
    if (rev.completionSignal?.includes("REJECTED")) {
      // 方向被否掉的分支不能留在 `agent/issue-<n>` 这个名字上,否则下一轮探测
      // 会把它当成「可续的半成品」接着做错的方向。推到带后缀的死分支名备查,
      // 把名字腾出来让 issue 重新走全新实现。
      const stamp = new Date().toISOString().replace(/[-:]/g, "").slice(0, 15);
      const dead = `${branch}-rejected-${stamp}`;
      git("push", "origin", `${branch}:refs/heads/${dead}`);
      try {
        git("push", "origin", "--delete", branch); // 前几轮可能推过同名分支
      } catch {}
      deferredRetire = { branch, reason: "rejected" }; // 本地改名等 worktree 撤掉再做
      gh(
        "issue", "comment", n, "--body",
        `AFK 评审 agent 判定实现方向偏差,未开 PR。分支已推送为 \`${dead}\` 备查,日志见 .sandcastle/logs/。\n\n` +
          `\`agent/issue-${n}\` 已腾空:下次 AFK 取到本票会按全新实现重跑。若方向本身需要重新讨论,请先改标签。`,
      );
      gh("issue", "edit", n, "--remove-assignee", "@me");
      console.log(`#${n} 评审 REJECTED:分支已退役为 ${dead},未开 PR。`);
      return { outcome: "rejected" };
    }

    git("push", "-u", "origin", branch);

    const brief = showOnBranch(branch, briefPath)
      ?? `⚠️ 评审 agent 未提交 \`${briefPath}\`——本 PR 缺少人读摘要,只能直接看下面的 QA 文档。`;
    const qaDoc = showOnBranch(branch, qaPath)
      ?? `⚠️ agent 未提交 \`${qaPath}\`——合并前需补 QA 文档(改动摘要 + 真实样例验证指引)。`;
    const body = buildPrBody(n, brief, qaDoc);

    let prUrl: string;
    if (mode.kind === "continue" && mode.pr) {
      // 复跑落在原 PR 上,body **必须重刷**:stale 的摘要描述的是已经不存在的
      // 代码,比没有摘要更坏——它会主动误导要在几分钟内决定合不合的人。
      // 分工:body = 现状(可覆盖、无历史),评论 = 变更记录(append-only)。
      // 旧摘要折进评论存档,历史不丢,顶部不骗人。
      gh(
        "pr", "comment", String(mode.pr.number), "--body",
        [
          `🔁 **AFK 复跑**(${new Date().toISOString().slice(0, 10)}):已按 ${mode.count} 条反馈改动并重走实现 + 评审双闸,` +
            `PR 顶部摘要已刷新为当前实现。本轮 commit 叠在原有 commit 之上,\`git log\` 可见前后两轮。`,
          "",
          "<details>",
          "<summary>刷新前的摘要(存档,描述的是改动前的代码)</summary>",
          "",
          prevBrief ?? "(上一轮没有留下摘要)",
          "",
          "</details>",
        ].join("\n"),
      );
      gh("pr", "edit", String(mode.pr.number), "--body", body);
      prUrl = mode.pr.url;
      console.log(`#${n} 复跑完成,已刷新 PR:${prUrl}`);
    } else {
      prUrl = gh(
        "pr", "create",
        "--base", "main",
        "--head", branch,
        "--title", `${issue.title} (#${n})`,
        "--body", body,
      ).trim();
      console.log(`#${n} 完成:${prUrl}`);
    }
    return { outcome: "done" };
  } catch (err) {
    // 失败时释放认领,frontier 不会被卡死
    try {
      gh("issue", "edit", n, "--remove-assignee", "@me");
    } catch {}
    // 撞限不是"这个 issue 做失败了",两者以前一视同仁。分开之后循环才知道该
    // 停(墙不会因为换一张票就消失),而这条退出路径本身不耗额度——afk.ts 是
    // 宿主机上的普通进程,不是 agent。
    const msg = err instanceof Error ? `${err.message}\n${err.stack ?? ""}` : String(err);
    if (looksLikeQuotaExhaustion(msg)) {
      console.log(`#${n} 撞额度上限:已释放认领,分支与 commit 保留,下个窗口自动续跑。`);
      return { outcome: "quota-exhausted", error: err };
    }
    if (looksLikeAuthBroken(msg)) {
      console.log(
        `#${n} 认证失败:CLAUDE_CODE_OAUTH_TOKEN 失效/无效(sk-ant-oat01 会过期或被吊销)。` +
          "`claude setup-token` 重新生成、更新 .sandcastle/.env 后重跑。已释放认领,分支与 commit 保留。",
      );
      return { outcome: "auth-broken", error: err };
    }
    if (looksLikeEnvBroken(msg)) {
      console.log(`#${n} 环境不通(网络/代理/Docker):已释放认领,分支与 commit 保留,修好后重跑即可。`);
      return { outcome: "env-broken", error: err };
    }
    return { outcome: "failed", error: err };
  }
}

const EXIT: Record<Outcome, number> = {
  done: 0,
  failed: 1,
  blocked: 2,
  rejected: 3,
  "quota-exhausted": 4,
  "env-broken": 5,
  "auth-broken": 6,
};

async function main(): Promise<number> {
  const args = process.argv.slice(2);
  const quota = new QuotaTracker();

  // --quota 只读盘不跑活:验收要求「用伪造的过期 JSON 验证起点按 0% 重算」,
  // 配合 AFK_RATE_LIMITS_FILE 就能验,不用动真文件、不用起沙箱。
  if (args.includes("--quota")) {
    console.log(describe(quota.read()));
    return 0;
  }

  if (!process.env.CLAUDE_CODE_OAUTH_TOKEN && !process.env.ANTHROPIC_API_KEY) {
    console.error("缺少 CLAUDE_CODE_OAUTH_TOKEN(或 ANTHROPIC_API_KEY)——先按 .env.example 配好 .sandcastle/.env");
    return 1;
  }

  const forceFresh = args.includes("--fresh");
  const dryRun = args.includes("--dry-run");
  let loop = args.includes("--loop");
  const maxIdx = args.indexOf("--max");
  const max = maxIdx >= 0 ? Number(args[maxIdx + 1]) : Infinity;
  // `--max 3` 的 3 也是个裸数字,别把它当成 issue 号。
  const positional = args.filter((a, i) => /^\d+$/.test(a) && args[i - 1] !== "--max");
  const explicit = positional.length ? Number(positional[0]) : undefined;

  if (explicit !== undefined && loop) {
    console.warn("指定了 issue 号,--loop 忽略:循环是让 frontier 自己排队,指定号就只跑那一票。");
    loop = false;
  }

  const skip = new Set<number>();
  let handled = 0;
  let exit = 0;

  for (;;) {
    // 事前拦截:每取下一票**之前**查一次额度。事前比事后可靠——撞限识别只是
    // 兜底,真撞上了那一票的 token 已经白烧了。
    const q = quota.read();
    console.log(`\n[额度] ${describe(q)}`);
    if (q.percent >= STOP_PERCENT) {
      console.log(`已达 ${STOP_PERCENT}% 门槛,不开下一票,干净收工(本轮已处理 ${handled} 票)。`);
      break;
    }
    if (handled >= max) {
      console.log(`已达 --max ${max},收工。`);
      break;
    }

    // 探测分支状态要看得见远端:半成品可能是别的机器推上去的,本地未必有。
    // 每票都 fetch 一次——循环跑一夜,期间远端可能有人合了 PR。
    try {
      git("fetch", "--prune", "origin");
    } catch {
      console.warn("git fetch 失败,只能按本地分支状态判断续跑与否。");
    }

    const issue = pickIssue(explicit, skip);
    if (!issue) {
      console.log(
        handled === 0
          ? "frontier 为空:没有未认领且未被阻塞的 ready-for-agent issue。"
          : `frontier 已空,收工(本轮共处理 ${handled} 票)。`,
      );
      break;
    }
    skip.add(issue.number); // 同一轮不重复取:失败/REJECTED 会把票放回 frontier

    let res: { outcome: Outcome; error?: unknown };
    try {
      res = await runOne(issue, { forceFresh, dryRun, quota });
    } finally {
      cleanupRun(); // 每票收尾,不能攒到进程结束:worktree 占着下一票就起不来
    }
    handled++;

    // 撞限是预期内的事,不是崩溃:只报一行原因,别甩一坨堆栈。真故障才要堆栈。
    if (res.error) {
      const e = res.error;
      const label =
        res.outcome === "quota-exhausted"
          ? "撞限退出"
          : res.outcome === "env-broken"
            ? "环境不通"
            : res.outcome === "auth-broken"
              ? "认证失败"
              : "失败";
      console.error(`\n#${issue.number} ${label}:${e instanceof Error ? e.message : String(e)}`);
      if (res.outcome === "failed" && e instanceof Error && e.stack) console.error(e.stack);
    }
    if (!loop) return EXIT[res.outcome];

    if (res.outcome === "quota-exhausted") {
      console.log("撞到额度上限,停止循环——换一张票也是撞同一堵墙。");
      exit = EXIT["quota-exhausted"];
      break;
    }
    if (res.outcome === "env-broken") {
      console.log("环境不通,停止循环——GitHub 都连不上时,Claude API 多半也不通,后面每票都是白跑。");
      exit = EXIT["env-broken"];
      break;
    }
    if (res.outcome === "auth-broken") {
      console.log("认证失败,停止循环——token 不换,后面每票都是同一个 401。");
      exit = EXIT["auth-broken"];
      break;
    }
    if (res.outcome === "failed") exit = 1; // 记下来,但别让一票的故障停掉一夜
  }

  if (loop) {
    console.log(`\n[收工] 处理 ${handled} 票。${describe(quota.read())}`);
    console.log("标定用:把「本轮跑了几票 / statusline 上 5h% 涨了多少」写回 docs/agents/afk-sandcastle.md 的「标定」一节。");
  }
  return exit;
}

// 外部中断(关终端、VS Code 重载、系统关机/更新)会给进程发信号。没有处理器
// 时 node 直接静默退出:本体日志不落一个字,worktree 也可能留脏。装上处理器,
// 让外部中断至少留一行痕 + 清理临时物。未跑完的票没被 assign 死(runOne 的
// catch 会 remove-assignee),回到 frontier,下个窗口自动续跑。
for (const sig of ["SIGINT", "SIGTERM", "SIGHUP", "SIGBREAK"] as const) {
  try {
    process.on(sig, () => {
      console.error(`\nAFK 收到 ${sig},收工:清理临时物后退出。未跑完的票会回到 frontier,下个窗口自动续跑。`);
      try {
        cleanupHost();
      } catch {}
      process.exit(130);
    });
  } catch {}
}

try {
  process.exitCode = await main();
} catch (err) {
  // 编排器崩溃要留成可读的失败,不是一坨 uncaught 堆栈——#26 那次
  // SessionCaptureError 就是从 dispose 里直穿出来把进程带走的。
  console.error(`\nAFK 运行失败:${err instanceof Error ? err.message : String(err)}`);
  if (err instanceof Error && err.stack) console.error(err.stack);
  process.exitCode = 1;
} finally {
  cleanupHost();
}
