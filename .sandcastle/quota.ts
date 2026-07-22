// 额度门槛:AFK 在睡觉时段自动连着跑,必须自己判断「还够不够开下一票」。
//
// 真值只在 Claude Code 喂给 statusline 的 stdin payload 里(`rate_limits`),
// afk.ts 这个宿主机进程拿不到。所以 statusline 脚本顺手把它落盘
// (`~/.claude/rate-limits.json`),这里读盘当**起点**,夜间增量用 agent 的
// token 用量估算叠上去。
//
// 本文件与 agent-alert 的 .sandcastle/quota.ts 同源(设计论证见该仓库
// .exp/2026-07-21-afk-unattended-automation.md)。已查证堵死的路,别再走一遍:
// `claude` CLI 没有 usage 子命令;transcript JSONL 不含 rate limit 字段;
// ccusage 只算 token 和 $ 成本,不知道套餐上限。
//
// **估算错了不是事故。** 撞限那一票会白烧部分 token,但 issue 会干净地回到
// frontier、分支和 commit 都留着,下个窗口自动续跑。所以精度只影响浪费多少,
// 不影响正确性——不必为精确做复杂设计。

import { existsSync, readFileSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";

// 落盘文件路径可覆盖:「用伪造的过期 JSON 验证起点按 0% 重算」有这个开关
// 就不用去动真文件。
export const RATE_LIMITS_FILE =
  process.env.AFK_RATE_LIMITS_FILE ?? join(homedir(), ".claude", "rate-limits.json");

// 达到这个百分比就不再开下一票。留 10% 余量是因为估算偏低比偏高常见,
// 而且正在跑的那一票还要跑完。
export const STOP_PERCENT = Number(process.env.AFK_QUOTA_STOP_PERCENT ?? 90);

// 标定常数:多少「加权成本单位」算 5h 窗口的 1%。
//
// **这个默认值是一阶估算,不是实测值**——与 agent-alert 共用同一把尺(同一
// 订阅、同一模型),那边标定完成后把实测值同步过来。故意取偏小的值:单位/%
// 越小,估算涨得越快,越早收工——宁可少跑一票,不要撞墙。
export const UNITS_PER_PERCENT = Number(process.env.AFK_UNITS_PER_PERCENT ?? 60_000);

interface Usage {
  inputTokens: number;
  outputTokens: number;
  cacheReadInputTokens: number;
  cacheCreationInputTokens: number;
}

// 加权成本单位:按 Sonnet 的计费比价把四种 token 折成同一把尺(cache 读 0.1×、
// cache 写 1.25×、output 5× input)。额度消耗大体正比于成本,所以这把尺比裸
// token 数准得多——output 只占 token 数的几个百分点,却占成本的一大半。
const W = { input: 1, cacheRead: 0.1, cacheWrite: 1.25, output: 5 };

const weigh = (input: number, cacheR: number, cacheW: number, output: number): number =>
  input * W.input + cacheR * W.cacheRead + cacheW * W.cacheWrite + output * W.output;

// 一轮 = 几十次 API 请求,不是一次。sandcastle 的 `iteration.usage` 只是"该轮
// **最后一条** assistant 消息"的快照——那是收尾时的 context 大小,不是这一轮
// 花掉的钱。agent 每调一次工具就是一次完整请求,整个 context 要重发一遍,
// 真实开销 ≈ Σ(每次请求的 context),差的正好是请求次数那个量级
// (agent-alert 实测低估 25~35 倍)。真账在会话 JSONL 里,每条 assistant
// 消息带自己那次请求的 usage;同一条消息会因流式分片重复出现多行,按
// message.id 去重。
export interface SessionStats {
  units: number;
  requests: number;
  /** 每次请求送进模型的 prompt 大小,按请求先后排列。 */
  contexts: number[];
}

const cache = new Map<string, SessionStats | undefined>();

export function sessionStats(path: string): SessionStats | undefined {
  if (cache.has(path)) return cache.get(path);
  const parsed = parseSession(path);
  cache.set(path, parsed);
  return parsed;
}

function parseSession(path: string): SessionStats | undefined {
  if (!existsSync(path)) return undefined;
  let text: string;
  try {
    text = readFileSync(path, "utf8");
  } catch {
    return undefined;
  }
  const byId = new Map<string, { units: number; context: number }>();
  for (const line of text.split("\n")) {
    if (!line.trim()) continue;
    let o: any;
    try {
      o = JSON.parse(line);
    } catch {
      continue;
    }
    const u = o?.message?.usage;
    if (o?.type !== "assistant" || !u) continue;
    const input = u.input_tokens ?? 0;
    const cacheR = u.cache_read_input_tokens ?? 0;
    const cacheW = u.cache_creation_input_tokens ?? 0;
    byId.set(o.message.id ?? `${byId.size}`, {
      units: weigh(input, cacheR, cacheW, u.output_tokens ?? 0),
      // context 占用 = 这三项之和:同一份 prompt 按计费方式拆开的账目。
      // output 是模型的回复,不占已发送的 prompt。
      context: input + cacheR + cacheW,
    });
  }
  if (byId.size === 0) return undefined;
  const rows = [...byId.values()];
  return {
    units: rows.reduce((a, r) => a + r.units, 0),
    requests: rows.length,
    contexts: rows.map((r) => r.context),
  };
}

export function median(xs: number[]): number {
  const s = [...xs].sort((a, b) => a - b);
  const m = s.length >> 1;
  return s.length % 2 ? s[m]! : Math.round((s[m - 1]! + s[m]!) / 2);
}

// 请求次数单独报一个数:它是诊断浪费的关键指标。轮询空转在 token 账上只是
// "context 又重发了一遍",看不出异常;但请求数会明显偏高。
export let lastRequestCount = 0;

export function costUnits(iterations: { usage?: Usage; sessionFilePath?: string }[]): number {
  let sum = 0;
  lastRequestCount = 0;
  for (const it of iterations) {
    const real = it.sessionFilePath ? sessionStats(it.sessionFilePath) : undefined;
    if (real !== undefined) {
      sum += real.units;
      lastRequestCount += real.requests;
      continue;
    }
    // 会话文件拿不到时退回快照。它只是收尾 context,会**大幅低估**——聊胜于无,
    // 但别拿它当真值用。
    const u = it.usage;
    if (!u) continue;
    sum += weigh(u.inputTokens, u.cacheReadInputTokens, u.cacheCreationInputTokens, u.outputTokens);
  }
  return Math.round(sum);
}

// 时间一律按本机时区显示。落盘的是 UTC(statusline 写 ISO Z、resets_at 是 unix
// 秒),直接打出来会和状态栏差 8 小时,夜里看这个数只会误判。
function local(ms: number): string {
  const d = new Date(ms);
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
}

interface Snapshot {
  written_at?: string;
  five_hour?: { used_percentage?: number | null; resets_at?: number | null };
  seven_day?: { used_percentage?: number | null; resets_at?: number | null };
}

function load(): Snapshot | undefined {
  try {
    if (!existsSync(RATE_LIMITS_FILE)) return undefined;
    return JSON.parse(readFileSync(RATE_LIMITS_FILE, "utf8"));
  } catch {
    return undefined; // 读到写了一半的 JSON 也不该让编排器崩
  }
}

export interface QuotaReading {
  percent: number; // 起点 + 估算增量
  baseline: number; // 落盘真值(窗口已翻篇则 0)
  estimated: number; // 本进程估出来的增量
  units: number; // 计入增量的加权成本单位
  source: string; // 人读的来源说明,打印出来让人能判断这数可不可信
}

// 一次 AFK 进程(可能连跑多票)期间的额度账本。
export class QuotaTracker {
  private units = 0;
  // 累加从哪一刻起算。落盘真值比它新时,说明期间有交互式 session 刷新过
  // statusline,那份真值已经包含了我们估的这段,估算要清零重新起算。
  private since = Date.now();

  add(iterations: { usage?: Usage }[]): number {
    const u = costUnits(iterations);
    this.units += u;
    return u;
  }

  read(): QuotaReading {
    const now = Date.now();
    const snap = load();
    const five = snap?.five_hour;
    const resetMs = five?.resets_at ? five.resets_at * 1000 : 0;

    if (!snap || five?.used_percentage == null || !resetMs) {
      return this.reading(0, `无落盘真值(${RATE_LIMITS_FILE} 不存在或没有 five_hour)`);
    }

    if (now >= resetMs) {
      // `resets_at` 已过 ⇒ 进了新窗口。起点按 0% 重算,上个窗口攒的估算一并
      // 清零。这正是误差不会累积一整夜的原因:每个窗口自动归零。
      if (this.units > 0) {
        this.units = 0;
        this.since = now;
      }
      return this.reading(0, `落盘快照已过 resets_at(${local(resetMs)}),按新窗口 0% 起算`);
    }

    const writtenMs = Date.parse(snap.written_at ?? "");
    if (Number.isFinite(writtenMs) && writtenMs > this.since) {
      // 真值比估算新:有交互式 session 刚渲染过 statusline。直接采信,估算清零。
      this.units = 0;
      this.since = writtenMs;
    }
    const wrote = Number.isFinite(writtenMs) ? local(writtenMs) : "?";
    return this.reading(
      five.used_percentage,
      `落盘真值 ${five.used_percentage.toFixed(1)}%(写于 ${wrote},窗口 ${local(resetMs)} 重置,均为本地时间)`,
    );
  }

  private reading(baseline: number, source: string): QuotaReading {
    const estimated = UNITS_PER_PERCENT > 0 ? this.units / UNITS_PER_PERCENT : 0;
    return {
      baseline,
      estimated,
      units: this.units,
      percent: baseline + estimated,
      source,
    };
  }
}

export function describe(q: QuotaReading): string {
  return (
    `5h 额度约 ${q.percent.toFixed(1)}% = 起点 ${q.baseline.toFixed(1)}% + 估算 ${q.estimated.toFixed(1)}%` +
    `(${(q.units / 1000).toFixed(0)}k 加权单位 ÷ ${(UNITS_PER_PERCENT / 1000).toFixed(0)}k/%)。${q.source}`
  );
}

// 撞限识别(事后兜底)。事前拦截靠估算,估算不准时靠它把外层循环停下来——
// 别拿下一票去撞同一堵墙。真实文案(agent-alert 实测)是
//   `You've hit your session limit · resets 11:40pm (UTC)`
// ——真文案优先放前面。
const EXHAUSTED = [
  /session limit/i,
  /hit your .{0,20}limit/i,
  /usage limit reached/i,
  /rate[ _-]?limit/i,
  /\b429\b/,
  /quota (?:exceeded|exhausted)/i,
  /credit balance is too low/i,
  /insufficient (?:quota|credit)/i,
];

export function looksLikeQuotaExhaustion(text: string | undefined): boolean {
  if (!text) return false;
  return EXHAUSTED.some((re) => re.test(text));
}
