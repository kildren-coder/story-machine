# -*- coding: utf-8 -*-
"""smpc.py — story-machine 在 5070 主机上的执行器。部署到 C:\\asr\\smpc.py。

子命令：
    download   --ep EPxx --url <链接>     yt-dlp 抓音频流 → 暂存区 EPxx.m4a + EPxx.meta.json
    transcribe --ep EPxx                  FireRedASR2-AED 转写 → EPxx.transcript.json + EPxx.words.json

两个子命令跑在不同 venv：download / meta 用 C:\\asr\\venv（yt-dlp 在那里，无 torch），
transcribe 用 E:\\asr\\venv-fired（torch CUDA 版）。所以本文件顶层只 import 标准库和
asrblocks（纯标准库）；引擎接线 fired_engine 在 transcribe 里才 import。

调用契约（笔记本侧的 worker.ps1 依赖，改动前先看这几条）：

1. **所有命令行参数保持纯 ASCII。** B 站标题必然带中文，经 ssh 的 stdout/argv
   会撞 PowerShell 5.1 的代码页；一切中文只经由 UTF-8 文件传递，worker 用 scp
   取回后本地解析。EPxx 是本脚本认识的唯一标识，中文文件名不出 PC。
2. **stdout 只输出 ASCII 协议行**，worker 逐行解析：
       PROGRESS <已完成> <总量>    进度（两个浮点数，单位随阶段：下载是百分比，转写是秒）
       INFO <文本>                 人可读日志，worker 原样转发到终端
       ERROR <文本>                失败原因；非零退出码同时置位
3. **产物一律落 E:\\asr\\staged\\，且文件名一律 EPxx.***。scp 只搬 ASCII 名。

红线相关：本脚本只做听写，不做任何摘要、改写、纠错。转写配置是 SPEC §4 阶段0
冻结的那一套（FireRedASR2-AED / fp32 / beam 3 / batch 4 / VAD 30 秒块 / CTC 词时刻，
常量在 asrblocks.py 顶上），不要在这里"调优"。后处理只有两样：繁→简逐字归一（见
to_simplified 的注释），只统一字形；FireRedPunc 加的标点另存在顶层 `punc`，正本
`segments[].text` 不带标点。
"""

import argparse
import json
import pathlib
import re
import shutil
import subprocess
import sys
import time

import asrblocks         # 同目录，纯标准库；缺了要当场炸，别等转写完才发现

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

AUDIO_DIR = pathlib.Path(r"E:\asr\audio")
STAGE_DIR = pathlib.Path(r"E:\asr\staged")
VENV_BIN = pathlib.Path(r"C:\asr\venv\Scripts")
COOKIES = pathlib.Path(r"E:\asr\bili-cookies.txt")


def out(kind, *parts):
    print(kind + " " + " ".join(str(p) for p in parts), flush=True)


def info(*parts):
    out("INFO", *parts)


def fail(msg):
    out("ERROR", msg)
    sys.exit(1)


# --------------------------------------------------------------------------
# download
# --------------------------------------------------------------------------

BV_RE = re.compile(r"(BV[0-9A-Za-z]{10})")
PCT_RE = re.compile(r"\[download\]\s+([\d.]+)%")


def normalize_url(url):
    """短链展开 + 提取 BV 号。返回 (clean_url, bv, part_or_None)。"""
    target = url
    if not BV_RE.search(target):
        import urllib.request
        req = urllib.request.Request(target, method="HEAD")
        with urllib.request.urlopen(req, timeout=30) as resp:
            target = resp.geturl()
    m = BV_RE.search(target)
    if not m:
        fail("cannot extract BV id from: " + url)
    bv = m.group(1)
    part = None
    pm = re.search(r"[?&]p=(\d+)", target)
    if pm:
        part = int(pm.group(1))
    clean = "https://www.bilibili.com/video/" + bv
    if part:
        clean += "?p=%d" % part
    return clean, bv, part


def ytdlp(args, stream_progress=False):
    exe = VENV_BIN / "yt-dlp.exe"
    if not exe.exists():
        fail("yt-dlp not found at " + str(exe))
    cmd = [str(exe)] + args
    if COOKIES.exists():
        cmd = [str(exe), "--cookies", str(COOKIES)] + args
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            encoding="utf-8", errors="replace", bufsize=1)
    collected = []
    last_pct = -5.0
    for line in proc.stdout:
        line = line.rstrip("\n")
        collected.append(line)
        if stream_progress:
            pm = PCT_RE.search(line)
            if pm:
                pct = float(pm.group(1))
                if pct - last_pct >= 2.0 or pct >= 100.0:
                    last_pct = pct
                    out("PROGRESS", "%.1f" % pct, "100")
    proc.wait()
    return proc.returncode, collected


def cmd_download(ep, url):
    STAGE_DIR.mkdir(parents=True, exist_ok=True)
    AUDIO_DIR.mkdir(parents=True, exist_ok=True)

    clean, bv, part = normalize_url(url)
    info("bv=%s part=%s" % (bv, part if part else "-"))

    # 先取元数据：标题、时长、分 P 总数。--no-playlist 使多 P 时只描述当前这一个。
    rc, lines = ytdlp(["-J", "--no-playlist", "--skip-download", clean])
    if rc != 0:
        fail("yt-dlp metadata failed (exit %d): %s" % (rc, " | ".join(lines[-3:])))
    meta_raw = None
    for line in lines:
        if line.startswith("{"):
            meta_raw = line
            break
    if meta_raw is None:
        fail("yt-dlp -J produced no JSON")
    j = json.loads(meta_raw)

    title = j.get("title") or bv
    duration = j.get("duration")
    # 多 P：yt-dlp 在 --no-playlist 下只描述目标那一 P，总数要从 entries 之外的字段推
    parts_total = j.get("n_entries") or len(j.get("entries") or []) or 1

    # 下载音频流
    tmpl = str(AUDIO_DIR / ("%s.%%(ext)s" % ep))
    rc, lines = ytdlp(["-f", "ba", "-N", "4", "--no-playlist", "-o", tmpl, clean],
                      stream_progress=True)
    if rc != 0:
        fail("yt-dlp download failed (exit %d): %s" % (rc, " | ".join(lines[-3:])))

    got = sorted(AUDIO_DIR.glob(ep + ".*"))
    got = [p for p in got if p.suffix.lower() not in (".part", ".ytdl", ".json")]
    if not got:
        fail("download reported success but no file matched " + ep + ".*")
    src = max(got, key=lambda p: p.stat().st_mtime)

    # 暂存成 ASCII 名，供 scp 取回
    dst = STAGE_DIR / (ep + src.suffix.lower())
    if dst.resolve() != src.resolve():
        if dst.exists():
            dst.unlink()
        src.replace(dst)

    meta = {
        "ep": ep,
        "bv": bv,
        "part": part,
        "parts_total": parts_total,
        "title": title,
        "url": clean,
        "duration_s": duration,
        "audio_file": dst.name,
        "audio_bytes": dst.stat().st_size,
        "uploader": j.get("uploader"),
        "upload_date": j.get("upload_date"),
        # 简介和 tag 常常是嘉宾名单唯一的书面出处，而且过期就没了（UP 主会改）。
        # 原样搬运，不解析不推断——谁是嘉宾由人看着简介点名。
        "description": j.get("description") or "",
        "tags": j.get("tags") or [],
        "downloaded_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    (STAGE_DIR / (ep + ".meta.json")).write_text(
        json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")

    info("staged %s (%.1f MB)" % (dst.name, dst.stat().st_size / 1048576))
    if parts_total and parts_total > 1:
        info("multipart total=%d (this row took p=%s)" % (parts_total, part or 1))
    out("PROGRESS", "100", "100")


# --------------------------------------------------------------------------
# transcribe
# --------------------------------------------------------------------------

_T2S = None
_T2S_CHAR = {}


def load_t2s():
    """加载繁→简字表。转写前先调一次：缺依赖要当场炸，别等 1.5 小时之后。"""
    global _T2S
    if _T2S is None:
        try:
            import opencc
        except ImportError:
            fail("opencc missing in venv: pip install opencc-python-reimplemented")
        _T2S = opencc.OpenCC("t2s")
    return _T2S


def to_simplified(text):
    """繁体字形归一成简体。不分引擎，段文本和词片段一律过这一张表。

    起因在旧引擎 whisper：它的中文词表里 `這` 和 `这` 是两个不同的 token，没有独立的字形选择
    环节。训练语料中台港来源的音频配的是繁体字幕、大陆来源的配简体，于是模型
    把「听起来像哪边的人」学成了字形先验：同一场直播，主播出简体、台湾口音的
    嘉宾出繁体（EP02 实测嘉宾 72.8% 繁）。已验证与用词无关（他自己的繁体段和
    简体段功能词频率相同，且零台式词汇），也与信道无关（把主播 EQ 成嘉宾的频谱
    后繁体占比纹丝不动，仍是 0.0%）。

    字形是解码器的产物，说话人没有「写」过任何字——所以这里没有原档要保，直接
    原地归一。不用 initial_prompt 那条路：实测提示词能把字形彻底掰过去，但同时
    会诱发标点、且逆着先验推时掉字（主播加繁体提示掉了 29% 的字），那是在改听写
    结果本身，撞红线。

    只做**逐字**转换，绝不用 tw2sp 之类词汇表：那会把「影片」改成「视频」、
    「網路」改成「网络」，属于改写原话。逐字表还保证
    convert(a + b) == convert(a) + convert(b)，所以 words.json 的词和
    transcript.json 的整段无论怎么重新拼接都一致（check_diar.py 依赖这条）。
    """
    cc = load_t2s()
    buf = []
    for ch in text:
        if ch not in _T2S_CHAR:
            _T2S_CHAR[ch] = cc.convert(ch)
        buf.append(_T2S_CHAR[ch])
    return "".join(buf)


def ascii_only(text):
    """worker 的行协议只认 ASCII（本文件头第 2 条）。异常消息不一定是。"""
    return str(text).encode("ascii", "replace").decode("ascii")


def _plain(o):
    """写盘的兜底：漏进产物的 numpy 标量收成内建类型，别让几小时的转写在写盘那一下炸掉。"""
    if hasattr(o, "item"):
        return o.item()
    raise TypeError("not JSON serializable: %r" % (o,))


def cmd_transcribe(ep):
    STAGE_DIR.mkdir(parents=True, exist_ok=True)
    cands = [p for p in STAGE_DIR.glob(ep + ".*")
             if p.suffix.lower() in (".m4a", ".mp3", ".webm", ".opus", ".aac", ".wav", ".mp4")]
    if not cands:
        fail("no staged audio for " + ep + " in " + str(STAGE_DIR))
    audio = max(cands, key=lambda p: p.stat().st_mtime)
    info("audio=" + audio.name)

    load_t2s()          # 依赖缺失就在这里炸，别转写完了才发现写不出简体
    t0 = time.time()
    try:
        import fired_engine
        eng = fired_engine.Engine()
    except Exception as e:
        fail("model load failed: " + ascii_only(repr(e)))
    t_load = time.time() - t0
    info("model loaded in %.1fs (%s %s, %s)"
         % (t_load, asrblocks.ENGINE, asrblocks.CONFIG, eng.versions))

    # 块音频照实验的喂法写成 wav，转完删掉
    blocks_dir = STAGE_DIR / (ep + ".blocks")
    shutil.rmtree(blocks_dir, ignore_errors=True)
    try:
        t0 = time.time()
        try:
            pcm, blocks = fired_engine.vad_blocks(audio)
            wavs = fired_engine.write_block_wavs(pcm, blocks, blocks_dir)
        except Exception as e:
            fail("vad failed: " + ascii_only(repr(e)))
        total = len(pcm) / asrblocks.SR
        del pcm
        t_vad = time.time() - t0
        info("vad: blocks=%d span=%.0fs of %.0fs in %.0fs"
             % (len(blocks), sum(asrblocks.span(b) for b in blocks), total, t_vad))

        t0 = time.time()
        segments, words_side, asr = asrblocks.run(
            blocks, eng.decoder(wavs), t2s=to_simplified,
            # 单位是秒：已解块的音频秒数 / 全部块的音频秒数
            progress=lambda done, all_s: out("PROGRESS", "%.1f" % done, "%.1f" % all_s),
            log=lambda msg: info(ascii_only(msg)))
        t_run = time.time() - t0
    finally:
        shutil.rmtree(blocks_dir, ignore_errors=True)

    asr.update(eng.memory())
    n_t2s = asr.pop("t2s_chars")
    info(asrblocks.asr_line(asr)
         + " retried=%d in %.0fs (%.1fx realtime) peak=%.1fGB reserved=%.1fGB"
         % (asr["retried"], t_run, total / t_run if t_run else 0,
            asr["peak_gpu_gb"], asr["reserved_gpu_gb"]))
    for key in ("error_blocks", "linear_blocks"):
        if asr[key]:
            info("asr: %s k=%s" % (key, ",".join(str(k) for k in asr[key])))

    # 标点另存：正本 segments[].text 不带标点；这一步失败不让转写失败
    t0 = time.time()
    punc = asrblocks.punc_pass(segments, eng.punc)
    punc["elapsed_s"] = round(time.time() - t0, 1)
    if punc["skipped"]:
        info("punc: skipped (%s)" % ascii_only(punc["skipped"]))
    else:
        info("punc: segments=%d unmatched=%d in %.1fs"
             % (len(punc["segments"]), punc["unmatched"], punc["elapsed_s"]))

    doc = {
        "ep": ep,
        "audio": audio.name,
        "duration_s": round(total, 1),
        "engine": asrblocks.ENGINE,
        "config": asrblocks.CONFIG,
        "diarization": "pending",     # 显式标记：不是忘了，是这一步还没跑
        "orthography": "opencc t2s 逐字",   # 缺这个字段 = 这一集早于字形归一，别信它的字形
        "orthography_chars": n_t2s,
        "transcribed_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "load_s": round(t_load, 1),
        "vad_s": round(t_vad, 1),
        "transcribe_s": round(t_run, 1),
        "realtime_factor": round(total / t_run, 1) if t_run else None,
        "asr": asr,
        "punc": punc,
        "segments": segments,
    }
    dest = STAGE_DIR / (ep + ".transcript.json")
    dest.write_text(json.dumps(doc, ensure_ascii=False, indent=1, default=_plain), encoding="utf-8")

    # 词时间戳留在 PC 侧：说话人分离要靠它在切换点拆段，
    # 存着就不必为了补跑分离而重转一遍。不进 vault（体积大且非面向人）。
    (STAGE_DIR / (ep + ".words.json")).write_text(
        json.dumps({"ep": ep, "segments": words_side}, ensure_ascii=False, default=_plain),
        encoding="utf-8")

    info("segments=%d  %.1fmin  t2s=%d chars" % (len(segments), total / 60, n_t2s))
    out("PROGRESS", "%.1f" % total, "%.1f" % total)


def cmd_meta(ep, url):
    """只重取元数据，不碰音频。

    用途：(a) 给早于「抓简介」这个功能下载的集数补 description/tags；
          (b) UP 主事后改了简介或标题时刷新。
    音频相关字段（audio_file/audio_bytes/downloaded_at）原样保留。
    """
    path = STAGE_DIR / (ep + ".meta.json")
    if not path.exists():
        fail("no meta.json for %s at %s" % (ep, path))
    meta = json.loads(path.read_text(encoding="utf-8"))

    clean, bv, part = normalize_url(url)
    rc, lines = ytdlp(["-J", "--no-playlist", "--skip-download", clean])
    if rc != 0:
        fail("yt-dlp metadata failed (exit %d): %s" % (rc, " | ".join(lines[-3:])))
    meta_raw = next((l for l in lines if l.startswith("{")), None)
    if meta_raw is None:
        fail("yt-dlp -J produced no JSON")
    j = json.loads(meta_raw)

    for key, val in (("title", j.get("title")),
                     ("uploader", j.get("uploader")),
                     ("upload_date", j.get("upload_date")),
                     ("description", j.get("description") or ""),
                     ("tags", j.get("tags") or [])):
        meta[key] = val
    meta["meta_refreshed_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    path.write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")

    info("meta refreshed: desc=%d chars, tags=%d"
         % (len(meta["description"]), len(meta["tags"])))


# --------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(prog="smpc.py")
    sub = ap.add_subparsers(dest="cmd", required=True)

    d = sub.add_parser("download")
    d.add_argument("--ep", required=True)
    d.add_argument("--url", required=True)

    t = sub.add_parser("transcribe")
    t.add_argument("--ep", required=True)

    m = sub.add_parser("meta")
    m.add_argument("--ep", required=True)
    m.add_argument("--url", required=True)

    a = ap.parse_args()
    if not re.fullmatch(r"EP\d{2,4}", a.ep):
        fail("--ep must look like EP01 (got %r)" % a.ep)

    if a.cmd == "download":
        cmd_download(a.ep, a.url)
    elif a.cmd == "transcribe":
        cmd_transcribe(a.ep)
    elif a.cmd == "meta":
        cmd_meta(a.ep, a.url)


if __name__ == "__main__":
    main()
