// .env 加载必须发生在任何「import 期就读 process.env」的模块被求值**之前**。
// quota.ts 的 UNITS_PER_PERCENT / STOP_PERCENT / RATE_LIMITS_FILE 都是模块级
// 常量,在被 import 的那一刻就把 process.env 读死了。ES 模块按 import 出现的
// 顺序深度优先求值,所以只要 afk.ts 把本模块摆在**第一个 import**,它的副作用
// (loadDotEnv)就先于 quota.ts 跑完,.env 里的覆盖才来得及生效。
//
// (agent-alert 2026-07-22 踩过的坑:loadDotEnv 原本写在 afk.ts 函数体里,
// quota.ts 的常量早已用默认值定死,.env 里的覆盖不生效。)

import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";

// 已存在于环境里的变量不覆盖(shell 显式 export 的优先级高于 .env);值两端的
// 引号剥掉。
export function loadDotEnv(path: string): void {
  if (!existsSync(path)) return;
  for (const line of readFileSync(path, "utf8").split(/\r?\n/)) {
    const m = line.match(/^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$/);
    if (m && m[2] && !(m[1] in process.env)) {
      process.env[m[1]] = m[2].replace(/^["']|["']$/g, "");
    }
  }
}

loadDotEnv(join(import.meta.dirname, ".env"));
