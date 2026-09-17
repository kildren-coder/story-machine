#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""digest.py — 单集入口：逐字稿 → L1 话题表 → EP 笔记里的可跳播大纲

    python scripts/digest.py ep EP02 --vault D:\\obsidian-task\\任务栏\\story-machine

跑完 EP 笔记的 `<!-- /speakers -->` 之后多一块 `## 整理稿`，每个话题一行
`### [HH:MM:SS] 标题`，点时间戳跳播（ADR 0001）；frontmatter 的 `整理:` 置
`done`。产物齐全就跳过，`--force` 才覆盖（SPEC §4.1）。

红线 6：这里一步一行中文日志，**不打印任何产物内容**——人只读日报，不审中间
产物。红线 9：L1 检查不过的单元落 `_failed/`，笔记上打 `整理: failed`，绝不
静默通过。

不烧额度的跑法：`--runner fake:tests/fixtures/raw` 从存档信封里取响应。
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from sm.l1 import run_l1                                          # noqa: E402
from sm.note import read_frontmatter, read_note, read_speakers    # noqa: E402
from sm.paths import VaultPaths                                   # noqa: E402
from sm.prov import now_iso, read_prompt                          # noqa: E402
from sm.render_ep import render_outline, write_into_note          # noqa: E402
from sm.runner import ClaudeRunner, FakeRunner                    # noqa: E402
from sm.text import hms                                           # noqa: E402
from sm.transcript import duration_s, read_transcript             # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

REPO = Path(__file__).resolve().parent.parent


def log(msg: str) -> None:
    print(f"[{datetime.now():%H:%M:%S}] {msg}", flush=True)


def make_runner(spec: str):
    """`claude`（真跑）或 `fake:<root>`（读存档信封，不烧额度）。"""
    if spec == "claude":
        return ClaudeRunner()
    if spec.startswith("fake:"):
        return FakeRunner(spec[len("fake:"):])
    raise SystemExit(f"--runner 只认 claude 或 fake:<root>，收到 {spec!r}")


def cmd_ep(args) -> int:
    paths = VaultPaths(args.vault)
    ep = args.ep.strip()
    prompt_file = Path(args.prompt)

    tr = paths.transcript(ep)
    if not tr.exists():
        log(f"✖ 找不到逐字稿 {tr}——这一集跑完阶段 0 了吗？")
        return 2
    note = paths.find_episode_note(ep)
    if not note:
        log(f"✖ 在 {paths.episodes} 里找不到 {ep} 的笔记")
        return 2
    if not prompt_file.exists():
        log(f"✖ 找不到 prompt {prompt_file}")
        return 2

    note_text = read_note(note)
    fm = read_frontmatter(note_text)
    speakers = read_speakers(note_text, fm)
    segments, _ = read_transcript(tr)
    dur = duration_s(segments)
    prompt = read_prompt(prompt_file)
    now = args.now or now_iso()

    named = "、".join(dict.fromkeys(speakers.values())) or "未点名"
    log(f"{ep}：{len(segments)} 段 / {hms(dur)}，说话人 {named}，"
        f"prompt {prompt['version']}@{prompt['sha8']}")
    unnamed = sorted({s.get("speaker") for s in segments
                      if s.get("speaker") and s.get("speaker") not in speakers})
    if unnamed:
        log(f"⚠ 还有没点名的说话人 {unnamed}——行首保留 SPEAKER_XX 原样，"
            f"先去笔记里点名再重跑效果更好")

    topics_path = paths.digest(ep) / "topics.json"
    if topics_path.exists() and not args.force:
        obj = json.loads(topics_path.read_bytes().decode("utf-8"))
        log(f"L1 产物已在（{paths.rel(topics_path)}），跳过调用——要重跑加 --force")
    else:
        runner = make_runner(args.runner)
        log(f"L1 骨架：整集一次调用（{args.model} / effort {args.effort}，"
            f"超时 {args.timeout}s）")
        obj = None
        try:
            obj, errors = run_l1(paths, runner, ep, segments, speakers, prompt,
                                 model=args.model, effort=args.effort,
                                 timeout=args.timeout, retries=args.retries,
                                 generated_at=now, log=lambda m: log(m))
        finally:
            # 检查不过、或者 runner 自己抛了（CLI 不在、退出码非 0、信封不是
            # JSON），人的阅读面上都得看到 failed；抛的那种照抛，别在这里吞掉
            if obj is None:
                write_into_note(note, None, "failed")
        if obj is None:
            log(f"✖ L1 检查不过（{len(errors)} 项），已落 "
                f"{paths.rel(paths.failed(ep))}，笔记打 整理: failed")
            for e in errors[:5]:
                log(f"    · {e}")
            return 1
        log(f"L1 通过：{len(obj.get('topics') or [])} 个话题 → {paths.rel(topics_path)}")

    version = (obj.get("provenance") or {}).get("prompt_version") or prompt["version"]
    block = render_outline(obj.get("topics") or [], version, now)
    missed = write_into_note(note, block, "done", version)
    if missed:
        log(f"⚠ 笔记没有 frontmatter，{'、'.join(missed)} 没写进去")
    log(f"话题大纲已写进 {paths.rel(note)}（整理: done，整理版本 {version}）")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="单集整理：L1 话题表 → EP 笔记大纲")
    sub = ap.add_subparsers(dest="cmd", required=True)
    one = sub.add_parser("ep", help="跑一集")
    one.add_argument("ep", help="EP02")
    one.add_argument("--vault", required=True, help="story-machine 根目录（不是 Obsidian 库根）")
    one.add_argument("--prompt", default=str(REPO / "prompts" / "L1-skeleton.md"))
    one.add_argument("--model", default="sonnet")
    one.add_argument("--effort", default="low")
    one.add_argument("--timeout", type=int, default=1800)
    one.add_argument("--retries", type=int, default=1, help="检查不过时重跑几次")
    one.add_argument("--force", action="store_true", help="产物已在也重跑并覆盖")
    one.add_argument("--runner", default="claude", help="claude | fake:<root>")
    one.add_argument("--now", default="", help="固定时钟（测试用，ISO8601）")
    one.set_defaults(func=cmd_ep)
    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
