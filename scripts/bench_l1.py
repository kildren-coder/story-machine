#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""bench_l1.py — 量 L1 的首发通过率（SPEC §4.1：上线前 3 集各 3 轮，目标 100%）

    python scripts/bench_l1.py v1 EP01 EP02 EP03 --vault <vault>
    python scripts/bench_l1.py v1 --vault <vault> --model haiku --effort medium --reps 2
    python scripts/bench_l1.py v1 --vault <vault> --rejudge     # 不烧额度

每轮只发一趟（`retries=0`），所以过/不过就是首发通过率。真库只读（逐字稿 + 笔记
里的点名），产物全写 `--out`，不碰 `10-Episodes/`、`_digest/`、`_pairs/`。

`--rejudge` 拿**当前**的解析器与检查器重判 `--out` 里已有的原始响应：改了闸门
之后想知道「同一批响应现在能过几个」，不必再烧一遍额度。

**`--out` 不许落在仓库里**：`.in.md` 是整集逐字稿，响应是它的转述（红线 10）。

除了过/不过，还报几项 prompt 规矩的遵守度，全是机判：
  短  非 filler 且不到 3 分钟的话题数（prompt 说要并进相邻话题）
  长  超过 20 分钟的话题数（prompt 说八成漏切了）
  零  起点与上一个相同、推出来长度为 0 的话题数
  乱  模型给的顺序里，位置和按起点排完不一样的话题数（代码已排好）
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from sm.l1 import build_input, check_topics, out_of_order, tidy, with_ends   # noqa: E402
from sm.note import read_frontmatter, read_note, read_speakers              # noqa: E402
from sm.pairs import call_layer                                             # noqa: E402
from sm.paths import VaultPaths                                             # noqa: E402
from sm.prov import read_prompt                                             # noqa: E402
from sm.runner import ClaudeRunner, extract_json                            # noqa: E402
from sm.text import parse_hms                                               # noqa: E402
from sm.transcript import duration_s, read_transcript                       # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

REPO = Path(__file__).resolve().parent.parent
DEFAULT_OUT = Path(tempfile.gettempdir()) / "story-machine-bench"


def quality(topics: list[dict], dur: int) -> dict:
    ts = with_ends(topics, dur)
    spans = [(t, parse_hms(t["end"]) - parse_hms(t["start"])) for t in ts]
    return {"n": len(ts),
            "short": sum(1 for t, s in spans if t.get("kind") != "filler" and 0 < s < 180),
            "long": sum(1 for _, s in spans if s > 1200),
            "zero": sum(1 for _, s in spans if s == 0),
            "moved": out_of_order(topics)}


def judge(result_text: str, dur: int) -> tuple[dict | None, list[str]]:
    """和 run_l1 走同一条路：解析 → tidy → check。"""
    try:
        obj = tidy(extract_json(result_text))
    except ValueError as e:                       # JSONDecodeError 也是 ValueError
        return None, [f"响应不是合法 JSON：{e}"]
    errs = check_topics(obj, dur)
    return (None, errs) if errs else (obj, [])


def line(tag: str, r: dict) -> str:
    if not r["ok"]:
        return f"  {tag}: 不过  {r['secs']:4d}s  ${r['usd']}\n        · " + "\n        · ".join(r["errors"][:4])
    return (f"  {tag}: 过  {r['n']:3d} 个话题  {r['secs']:4d}s  ${r['usd']}  "
            f"短{r['short']} 长{r['long']} 零{r['zero']} 乱{r['moved']}")


def run(args, vault: VaultPaths, root: Path) -> list[dict]:
    prompt = read_prompt(Path(args.prompt))
    print(f"{args.label} · {args.model}/{args.effort} · prompt {prompt['version']}@{prompt['sha8']} · "
          f"每集 {args.reps} 轮 · 每轮只发一趟 · 产物 {root}")
    rows: list[dict] = []
    for ep in args.eps:
        segs, _ = read_transcript(vault.transcript(ep))
        text = read_note(vault.find_episode_note(ep))
        speakers = read_speakers(text, read_frontmatter(text))
        dur = duration_s(segs)
        print(f"\n--- {ep}（{len(segs)} 段 / {dur}s）---")
        for rep in range(1, args.reps + 1):
            t0 = time.time()
            obj, env, errors = call_layer(
                VaultPaths(root / f"{ep}-r{rep}"), ClaudeRunner(), ep, "L1", "all",
                Path(args.prompt), build_input(ep, segs, speakers),
                lambda o: check_topics(tidy(o), dur),
                retries=0, model=args.model, effort=args.effort, timeout=args.timeout,
                log=lambda m: None)
            usd = sum(m.get("costUSD", 0) for m in (env.get("modelUsage") or {}).values())
            r = {"ep": ep, "rep": rep, "model": args.model, "effort": args.effort,
                 "ok": obj is not None, "errors": errors,
                 "secs": round(time.time() - t0), "usd": round(usd, 4)}
            if obj is not None:
                r.update(quality(tidy(obj)["topics"], dur))
            rows.append(r)
            # 每轮落一次盘：中途被杀也留得下已经跑完的
            (root / "rows.json").write_bytes(
                json.dumps(rows, ensure_ascii=False, indent=1).encode("utf-8"))
            print(line(f"r{rep}", r))
    return rows


def rejudge(vault: VaultPaths, root: Path) -> list[dict]:
    saved = {}
    if (root / "rows.json").exists():
        saved = {(r["ep"], r["rep"]): r
                 for r in json.loads((root / "rows.json").read_bytes().decode("utf-8"))}
    durs: dict[str, int] = {}
    rows = []
    for f in sorted(root.glob("*/_pairs/*/L1-all.raw.json")):
        ep, rep = f.parts[-4].rsplit("-r", 1)
        if ep not in durs:
            durs[ep] = duration_s(read_transcript(vault.transcript(ep))[0])
        env = json.loads(f.read_bytes().decode("utf-8"))
        obj, errors = judge(env.get("result", ""), durs[ep])
        old = saved.get((ep, int(rep)), {})
        r = {"ep": ep, "rep": int(rep), "ok": obj is not None, "errors": errors,
             "secs": old.get("secs", 0), "usd": old.get("usd", 0.0)}
        if obj is not None:
            r.update(quality(obj["topics"], durs[ep]))
        rows.append(r)
        print(line(f"{ep}-r{rep}", r))
    return rows


def summary(rows: list[dict]) -> None:
    print("\n========== 汇总 ==========")
    for ep in dict.fromkeys(r["ep"] for r in rows):
        sub = [r for r in rows if r["ep"] == ep]
        good = [r for r in sub if r["ok"]]
        print(f"  {ep}: 首发过 {len(good)}/{len(sub)}   话题数 {[r['n'] for r in good]}")
    ok = sum(1 for r in rows if r["ok"])
    print(f"  合计首发通过率 {ok}/{len(rows)}   合计 ${round(sum(r['usd'] for r in rows), 3)}")


def main() -> int:
    ap = argparse.ArgumentParser(description="量 L1 的首发通过率（每轮只发一趟）")
    ap.add_argument("label", help="这一组的名字，产物落在 <out>/<label>/")
    ap.add_argument("eps", nargs="*", help="EP01 EP02 …")
    ap.add_argument("--vault", required=True, help="story-machine 根目录（只读）")
    ap.add_argument("--out", default=str(DEFAULT_OUT), help="产物根目录，不许在仓库里")
    ap.add_argument("--reps", type=int, default=3)
    ap.add_argument("--model", default="sonnet")
    ap.add_argument("--effort", default="low")
    ap.add_argument("--timeout", type=int, default=2400)
    ap.add_argument("--prompt", default=str(REPO / "prompts" / "L1-skeleton.md"))
    ap.add_argument("--rejudge", action="store_true", help="用当前代码重判已有响应，不调模型")
    args = ap.parse_args()

    root = (Path(args.out) / args.label).resolve()
    if root == REPO or REPO in root.parents:
        print(f"✖ --out 落在仓库里（{root}）：.in.md 是整集逐字稿，不许进公开仓库（红线 10）")
        return 2
    vault = VaultPaths(args.vault)
    if args.rejudge:
        rows = rejudge(vault, root)
    else:
        if not args.eps:
            print("✖ 要给至少一个集号（EP01 …），或者加 --rejudge")
            return 2
        root.mkdir(parents=True, exist_ok=True)
        rows = run(args, vault, root)
    if not rows:
        print(f"✖ {root} 里没有可判的响应")
        return 2
    summary(rows)
    return 0 if all(r["ok"] for r in rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
