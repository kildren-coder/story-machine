# mkfixture.py -- 造一集「已知答案」的假直播，用来验说话人分离真的能分开人
#
#   python pc\mkfixture.py --ep EP90 --voices 2 --out E:\asr\staged
#
# 为什么需要它：EP01 和 EP02 都是主播一个人从头讲到尾，分离器对它们输出
# K=1 —— 看着对，但**证明不了任何事**。一个坏掉的聚类器（比如只会把离群
# 单点切出来的那种）在单人素材上同样输出 K=1。手上没有真·多人素材之前，
# 唯一能证伪的办法就是自己造一个答案已知的。
#
# 用 Windows 自带的 SAPI 语音轮流念稿，拼成一条音轨，同时按合成时的真实
# 边界写出 words.json / transcript.json —— 也就是把 faster-whisper 的产物
# 伪造得结构上完全一致，好让 smdiar.py 一个字都不用改地跑它。
#
# 局限（写在这里免得日后误读结论）：TTS 的两个音色干净、无重叠、无底噪，
# 比真实连麦好分得多。**跑通只说明聚类器没有结构性坏掉，不说明它在真素材
# 上够用。** 真正的验收要等第一集有嘉宾的直播。

import argparse
import json
import pathlib
import subprocess
import sys
import tempfile
import wave

SR = 16000

VOICES = ["Microsoft Huihui Desktop", "Microsoft Kangkang", "Microsoft Yaoyao"]

# 内容无所谓，只要够长、够杂，别让两个人念一模一样的字（那测的就成了音色以外的东西）
LINES = [
    "今天我们先把这一周的几条主线捋一遍，然后再回到上个月留下来的那个问题上去。",
    "我个人的看法是，这件事情的关键并不在表面上的那几个数字，而在于它背后的决策流程。",
    "如果按照去年同期的口径来对比，这个增速其实是被低估了，因为统计范围做过一次调整。",
    "有朋友在弹幕里问，那接下来会不会有进一步的动作，我觉得短期之内可能性并不大。",
    "我们把时间线拉长一点看，从两千零八年一直到现在，这条曲线的形状其实是很有意思的。",
    "第二个层面是产业链的位置问题，谁在上游、谁在下游，决定了议价能力在谁手里。",
    "这里我要强调一句，我说的只是一种可能性，并没有任何内部消息，大家自己判断。",
    "最后一部分我们聊聊外部环境，尤其是最近几个月汇率和大宗商品价格的联动关系。",
    "关于人口结构这一块，很多人只看总量，其实真正有影响的是年龄段的分布变化。",
    "从财政的角度讲，收入端和支出端要分开来看，混在一起谈很容易得出错误的结论。",
    "我再补充一个细节，这份文件里其实还有一段附注，很多报道都没有提到过它。",
    "所以综合来看，我倾向于认为目前这个阶段还是以观察为主，不适合做太重的判断。",
    "另外一条线索是技术路线的分歧，两条路各有各的成本结构，短期内看不出胜负。",
    "我们再看一下区域之间的差异，沿海和内陆在这个指标上的表现几乎是相反的。",
    "有人说这是周期性的，也有人说是结构性的，这两种解释推出来的政策建议完全不同。",
    "今天先讲到这里，下一次我们把剩下的两个话题接着往下说，感谢大家的陪伴。",
]

# 必须是 pwsh 7：Windows PowerShell 5.1 的 System.Speech 选不中 Kangkang/Yaoyao
# 这几个 OneCore 声音，SelectVoice 抛异常——而且默认是语句级非终止错误，脚本
# 会接着往下跑，用**默认声音**把音频写出来。第一版就是这么被骗的：两个「说话人」
# 其实是同一个人，wav 字节数完全相同。所以下面既锁 pwsh，也设 Stop，还回读
# $s.Voice.Name 让 Python 核对。造测试数据的东西自己出错不响，测试就没有意义。
PS_TTS = r"""
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Speech
$s = New-Object System.Speech.Synthesis.SpeechSynthesizer
$s.SelectVoice({voice})
$fmt = New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo({sr},
    [System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen,
    [System.Speech.AudioFormat.AudioChannel]::Mono)
$s.SetOutputToWaveFile({path}, $fmt)
$s.Speak({text})
$s.SetOutputToNull()
$s.Voice.Name
$s.Dispose()
"""


def ps_quote(s):
    return "'" + str(s).replace("'", "''") + "'"


def synth(voice, text, path):
    script = PS_TTS.format(voice=ps_quote(voice), sr=SR,
                           path=ps_quote(path), text=ps_quote(text))
    p = subprocess.run(["pwsh.exe", "-NoProfile", "-Command", script],
                       capture_output=True, text=True, errors="replace")
    if p.returncode != 0 or not pathlib.Path(path).exists():
        sys.exit("TTS 失败（%s）：%s" % (voice, (p.stderr or p.stdout or "")[-400:]))
    got = (p.stdout or "").strip().splitlines()[-1:] or [""]
    if got[0].strip() != voice:
        sys.exit("要的是 %r，实际用的是 %r —— 声音没选中，造出来的素材是假的" % (voice, got[0]))


def main():
    ap = argparse.ArgumentParser(prog="mkfixture.py")
    ap.add_argument("--ep", default="EP90")
    ap.add_argument("--voices", type=int, default=2)
    # 每个声音要稳稳超过 smdiar 的份额闸门（MIN_SECONDS=60），不然聚类稍有偏差
    # 就会因为「这个簇太短」被否掉，测试挂在了跟音色无关的地方
    ap.add_argument("--repeat", type=int, default=2, help="稿子念几轮")
    ap.add_argument("--out", default=r"E:\asr\staged")
    a = ap.parse_args()

    outdir = pathlib.Path(a.out)
    outdir.mkdir(parents=True, exist_ok=True)
    voices = VOICES[:a.voices]
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="mkfix_"))

    pcm, cursor = [], 0.0
    segments, wsegments, truth = [], [], []
    silence = b"\x00\x00" * int(0.4 * SR)     # 说话人之间留个自然的停顿

    script = LINES * a.repeat
    for i, line in enumerate(script):
        vi = i % len(voices)
        wav = tmp / ("turn%02d.wav" % i)
        synth(voices[vi], line, str(wav))
        with wave.open(str(wav), "rb") as w:
            assert w.getframerate() == SR and w.getnchannels() == 1, "SAPI 没按要求出格式"
            frames = w.readframes(w.getnframes())
            dur = w.getnframes() / float(SR)

        start, end = cursor, cursor + dur
        segments.append({"start": round(start, 2), "end": round(end, 2),
                         "speaker": None, "text": line})
        # 逐字均分这一段的时长：假的，但结构和 faster-whisper 的输出一致，
        # 而且窗口只要落在这一段里，归属就该是这个人
        chars = [c for c in line]
        step = dur / max(1, len(chars))
        wsegments.append([[round(start + k * step, 2),
                           round(start + (k + 1) * step, 2), c]
                          for k, c in enumerate(chars)])
        truth.append({"start": round(start, 2), "end": round(end, 2),
                      "voice": voices[vi], "voice_index": vi})

        pcm.append(frames)
        pcm.append(silence)
        cursor = end + 0.4
        print("  turn %02d  %-28s %6.1fs  %s" % (i, voices[vi], dur, line[:16]))

    audio = outdir / (a.ep + ".wav")
    with wave.open(str(audio), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(b"".join(pcm))

    def dump(name, obj):
        (outdir / name).write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")

    dump(a.ep + ".transcript.json",
         {"ep": a.ep, "audio": audio.name, "duration_s": round(cursor, 2),
          "engine": "mkfixture (SAPI TTS)", "config": "fixture",
          "diarization": "pending", "segments": segments})
    dump(a.ep + ".words.json", {"ep": a.ep, "segments": wsegments})
    dump(a.ep + ".truth.json",
         {"ep": a.ep, "voices": voices, "turns": truth,
          "seconds_per_voice": {
              v: round(sum(t["end"] - t["start"] for t in truth if t["voice"] == v), 1)
              for v in voices}})

    for f in tmp.glob("*"):
        f.unlink()
    tmp.rmdir()
    print("\n%s  %.1fs  %d 个声音  -> %s" % (a.ep, cursor, len(voices), outdir))


if __name__ == "__main__":
    main()
