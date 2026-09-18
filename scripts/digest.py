#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""digest.py — 单集入口：逐字稿 → L1 章节表 → L2 逐章节整理 → EP 笔记里的整理稿

    python scripts/digest.py ep EP02 --vault D:\\obsidian-task\\任务栏\\story-machine

跑完 EP 笔记的 `<!-- /speakers -->` 之后多一块 `## 整理稿`：一个话题一节
`### [HH:MM:SS] 标题`，下面是带时间戳的段落、原话锚点、可核查的说法、提到的
信源、疑似 ASR 生音，点时间戳跳播（ADR 0001）；frontmatter 的 `整理:` 置 `done`、
`整理版本:` 置 L2 的 prompt 版本。产物齐全就跳过，`--force` 才覆盖（SPEC §4.1）。

L1 整集一次调用，L2 一章一次调用（并发 3）。**每一章都完成才渲染**：任一章进
`_failed/` 就打 `整理: failed`、不写块、退出码 1——半份整理稿比没有更坏，人会
以为那就是全部。

红线 6：这里一步一行中文日志，**不打印任何产物内容**——人只读日报，不审中间
产物。红线 9：检查不过的单元落 `_failed/`，笔记上打 `整理: failed`，绝不静默
通过。

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
from sm.l2 import body_chars, paras_chars, ratio_of, run_l2       # noqa: E402
from sm.note import read_frontmatter, read_note, read_speakers    # noqa: E402
from sm.paths import VaultPaths                                   # noqa: E402
from sm.prov import now_iso, read_prompt                          # noqa: E402
from sm.render_ep import render_digest, write_into_note           # noqa: E402
from sm.runner import ClaudeRunner, FakeRunner                    # noqa: E402
from sm.text import hms                                           # noqa: E402
from sm.transcript import build_lines, duration_s, read_transcript  # noqa: E402

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
    l2_prompt_file = Path(args.l2_prompt)

    tr = paths.transcript(ep)
    if not tr.exists():
        log(f"✖ 找不到逐字稿 {tr}——这一集跑完阶段 0 了吗？")
        return 2
    note = paths.find_episode_note(ep)
    if not note:
        log(f"✖ 在 {paths.episodes} 里找不到 {ep} 的笔记")
        return 2
    for p in (prompt_file, l2_prompt_file):
        if not p.exists():
            log(f"✖ 找不到 prompt {p}")
            return 2

    note_text = read_note(note)
    fm = read_frontmatter(note_text)
    speakers = read_speakers(note_text, fm)
    segments, _ = read_transcript(tr)
    dur = duration_s(segments)
    prompt = read_prompt(prompt_file)
    l2_prompt = read_prompt(l2_prompt_file)
    now = args.now or now_iso()

    named = "、".join(dict.fromkeys(speakers.values())) or "未点名"
    log(f"{ep}：{len(segments)} 段 / {hms(dur)}，说话人 {named}，"
        f"prompt {prompt['version']}@{prompt['sha8']}")
    unnamed = sorted({s.get("speaker") for s in segments
                      if s.get("speaker") and s.get("speaker") not in speakers})
    if unnamed:
        log(f"⚠ 还有没点名的说话人 {unnamed}——行首保留 SPEAKER_XX 原样，"
            f"先去笔记里点名再重跑效果更好")

    runner = make_runner(args.runner)
    chapters_path = paths.digest(ep) / "chapters.json"
    if chapters_path.exists() and not args.force:
        # 产物坏了就停在这儿报出来：悄悄重跑会把人正要看的证据覆盖掉
        try:
            obj = json.loads(chapters_path.read_bytes().decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as e:
            log(f"✖ {paths.rel(chapters_path)} 不是合法 JSON（{e}）——看一眼再删，"
                f"或者直接 --force 重跑")
            return 2
        if not (obj.get("chapters") or []):
            log(f"✖ {paths.rel(chapters_path)} 里没有章节——看一眼再删，"
                f"或者直接 --force 重跑")
            return 2
        log(f"L1 产物已在（{paths.rel(chapters_path)}），跳过调用——要重跑加 --force")
    else:
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
            if obj is None and write_into_note(note, None, "failed"):
                # 没有 frontmatter 就写不进去。这一步也不许静默：不然人的阅读面
                # 上既没有块也没有 failed，看上去像什么都没发生过
                log(f"⚠ {paths.rel(note)} 没有 frontmatter，整理: failed 没写进去")
        if obj is None:
            log(f"✖ L1 检查不过（{len(errors)} 项），已落 "
                f"{paths.rel(paths.failed(ep))}，笔记打 整理: failed")
            for e in errors[:5]:
                log(f"    · {e}")
            return 1
        log(f"L1 通过：{len(obj.get('chapters') or [])} 章 → {paths.rel(chapters_path)}")

    chapters = obj.get("chapters") or []
    log(f"L2 逐章节整理：{len(chapters)} 章，一章一次调用（{args.l2_model} / effort "
        f"{args.l2_effort}，并发 {args.workers}，超时 {args.timeout}s/章，"
        f"prompt {l2_prompt['version']}@{l2_prompt['sha8']}）")
    topics, frags, failed = run_l2(
        paths, runner, ep, chapters, segments, speakers, l2_prompt,
        workers=args.workers, force=args.force, model=args.l2_model,
        effort=args.l2_effort, timeout=args.timeout, retries=args.retries,
        generated_at=now, log=lambda m: log(m))

    heads = (topics or {}).get("topics") or []
    done = {t.get("chapter") for t in heads}
    missing = [c.get("id") for c in chapters if c.get("id") not in done]
    if missing:
        # **每一章都完成才渲染**：半份整理稿比没有更坏，人会把它当成全部（红线 6
        # 说人只读这一面）。缺的章下次重跑只补它自己
        if write_into_note(note, None, "failed"):
            log(f"⚠ {paths.rel(note)} 没有 frontmatter，整理: failed 没写进去")
        where = f"，其中 {len(failed)} 章落进 {paths.rel(paths.failed(ep))}" if failed else ""
        log(f"✖ L2 有 {len(missing)} 章没整理出来（{'、'.join(missing)}）{where}；"
            f"笔记打 整理: failed，不写块。下次重跑只补这几章")
        return 1

    prov = topics.get("provenance") or {}
    version = prov.get("prompt_version") or l2_prompt["version"]
    kinds = {k: sum(1 for t in topics["topics"] if t.get("kind") == k)
             for k in ("talk", "aside", "filler")}
    # 压缩比是阅读预算的主口径（SPEC §1.3，约 0.2）：整集跑完报一次，人不用自己去
    # 数字数就知道这一趟的整理稿有多长。只报数，不打印内容（红线 6）
    wrote = paras_chars(frags.values())
    src = body_chars(build_lines(segments))
    log(f"L2 通过：{len(topics['topics'])} 个话题（talk {kinds['talk']}、"
        f"aside {kinds['aside']}、filler {kinds['filler']}）；正文合计 {wrote} 字 / "
        f"逐字稿 {src} 字，压缩比 {ratio_of(wrote, src)} → "
        f"{paths.rel(paths.digest(ep) / 'topics.json')}")
    # 块首行那个时间说的是「这份整理稿什么时候生成的」，取产物自己记的那个：跳过
    # L2 重渲染时用当下，笔记每跑一次就变一次（Obsidian 记一条新版本、同步重传）
    block = render_digest(topics["topics"], frags, version,
                          prov.get("generated_at") or now)
    missed = write_into_note(note, block, "done", version)
    if missed:
        log(f"⚠ 笔记没有 frontmatter，{'、'.join(missed)} 没写进去")
    log(f"整理稿已写进 {paths.rel(note)}（整理: done，整理版本 {version}）")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="单集整理：L1 章节表 → L2 整理稿 → EP 笔记")
    sub = ap.add_subparsers(dest="cmd", required=True)
    one = sub.add_parser("ep", help="跑一集")
    one.add_argument("ep", help="EP02")
    one.add_argument("--vault", required=True, help="story-machine 根目录（不是 Obsidian 库根）")
    one.add_argument("--prompt", default=str(REPO / "prompts" / "L1-skeleton.md"),
                     help="L1 的 prompt")
    one.add_argument("--model", default="sonnet", help="L1 的模型")
    one.add_argument("--effort", default="low", help="L1 的 effort")
    one.add_argument("--l2-prompt", default=str(REPO / "prompts" / "L2-topic.md"))
    one.add_argument("--l2-model", default="sonnet")
    one.add_argument("--l2-effort", default="medium")
    one.add_argument("--workers", type=int, default=3, help="L2 同时跑几章")
    one.add_argument("--timeout", type=int, default=1800, help="每次调用的超时")
    one.add_argument("--retries", type=int, default=1, help="检查不过时重跑几次")
    one.add_argument("--force", action="store_true", help="产物已在也重跑并覆盖")
    one.add_argument("--runner", default="claude", help="claude | fake:<root>")
    one.add_argument("--now", default="", help="固定时钟（测试用，ISO8601）")
    one.set_defaults(func=cmd_ep)
    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
