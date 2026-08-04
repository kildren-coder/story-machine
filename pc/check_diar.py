# check_diar.py -- 核对说话人分离没有动过逐字稿的内容
#
#   python pc\check_diar.py              # 查 _assets 下所有 EP
#   python pc\check_diar.py EP02
#
# 在笔记本上跑，只用标准库 + smdiar 的纯逻辑函数（不需要 torch，不需要 PC）。
#
# 红线是「ASR 只听写，不总结不脑补」。分离这一步重建了分段，于是它有能力
# 悄悄改字——事实上它改过：第一版 build_windows 丢掉了零时长词（EP02 的
# "H-E-U-T-A" 少了几个连字符），又按 start 排序把交叉时间戳的相邻词换了位
# （EP01 的「战斗机中国」变成「战斗中国…机」）。两处都不报错、都只差几个字，
# 靠眼睛永远看不出来。所以这个核对必须是机械的，且每次改分离逻辑都要跑。
#
# 查四件事：
#   1. words.json 原序拼接 == 分离前逐字稿          （ASR 自身一致）
#   2. 分离后各段拼接      == 分离前逐字稿          （分离没增没删没换位）
#   3. 每个词恰好被一个窗口覆盖                     （没有词悄悄漏掉）
#   4. 分离后段的时间戳单调                         （跳播依赖它）
# 比对时忽略空白：重新分段必然改变空格落点，非空白字符序列则一个都不许变。

import io
import json
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from smdiar import build_windows                                   # noqa: E402

ASSETS = pathlib.Path(r"D:\obsidian-task\任务栏\story-machine\_assets")


def load(p):
    return json.load(io.open(p, encoding="utf-8"))


def norm(s):
    return re.sub(r"\s+", "", s)


def hms(sec):
    sec = int(sec)
    return "%02d:%02d:%02d" % (sec // 3600, sec % 3600 // 60, sec % 60)


def first_diff(a, b):
    for i in range(min(len(a), len(b))):
        if a[i] != b[i]:
            return i, a[max(0, i - 30):i + 30], b[max(0, i - 30):i + 30]
    return min(len(a), len(b)), a[len(b):][:60], b[len(a):][:60]


def check(ep):
    new = load(ASSETS / f"{ep}.transcript.json")
    old_path = ASSETS / f"{ep}.transcript.nodiar.json"
    if not old_path.exists():
        print(f"=== {ep} ===\n  跳过：没有 {old_path.name}，这一集还没分离过")
        return True
    old = load(old_path)

    print(f"=== {ep} ===")
    print(f"  分段 {len(old['segments'])} -> {len(new['segments'])}"
          f"   说话人 {new.get('speakers')}"
          f"   轮廓系数 {new.get('diarization_silhouette')}")
    for name, sec in (new.get("speaker_seconds") or {}).items():
        print(f"    {name} {hms(sec)}")

    ok = True
    base = norm("".join(s["text"] for s in old["segments"]))

    # 1 + 3：词表本身
    wpath = ASSETS / f"{ep}.words.json"
    if wpath.exists():
        wsegs = load(wpath)["segments"]
        windows, words = build_windows(wsegs)
        joined = norm("".join(w[2] for w in words))
        if joined == base:
            print(f"  ✓ words.json 原序拼接与分离前逐字稿一致（{len(words)} 词）")
        else:
            ok = False
            i, a, b = first_diff(base, joined)
            print(f"  ✗ words.json 与逐字稿对不上，第 {i} 字：\n"
                  f"      稿…{a}…\n      词…{b}…")

        cover = [0] * len(words)
        for _, _, i, j in windows:
            for k in range(i, j + 1):
                cover[k] += 1
        bad = [k for k, c in enumerate(cover) if c != 1]
        if bad:
            ok = False
            print(f"  ✗ {len(bad)} 个词没被恰好一个窗口覆盖，前几个下标 {bad[:5]}")
        else:
            print(f"  ✓ {len(words)} 个词各被恰好一个窗口覆盖（{len(windows)} 窗）")
    else:
        print(f"  · 没有 {wpath.name}，跳过词级核对")

    # 2：分离前后文本
    after = norm("".join(s["text"] for s in new["segments"]))
    if after == base:
        print(f"  ✓ 分离前后逐字一致（{len(base)} 字）")
    else:
        ok = False
        i, a, b = first_diff(base, after)
        print(f"  ✗ 分离改了文本！{len(base)} 字 -> {len(after)} 字，第 {i} 字：\n"
              f"      前…{a}…\n      后…{b}…")

    # 4：时间轴
    segs = new["segments"]
    back = [i for i in range(1, len(segs)) if segs[i]["start"] < segs[i - 1]["start"]]
    if back:
        ok = False
        print(f"  ✗ 时间戳回退，前几处下标 {back[:5]}")
    else:
        print("  ✓ 时间戳单调")

    sw = sum(1 for i in range(1, len(segs))
             if segs[i].get("speaker") != segs[i - 1].get("speaker"))
    print(f"  · 说话人切换 {sw} 次")
    return ok


def main():
    eps = sys.argv[1:]
    if not eps:
        eps = sorted({p.name.split(".")[0] for p in ASSETS.glob("EP*.transcript.json")})
    if not eps:
        print(f"{ASSETS} 里没有 EP*.transcript.json")
        sys.exit(2)
    results = [check(ep) for ep in eps]   # 全查完再判，别 all() 短路掉后面几集
    if not all(results):
        print("\n有集没通过——分离逻辑改动了逐字稿内容，不要用这批产物。")
        sys.exit(1)
    print("\n全部通过。")


if __name__ == "__main__":
    main()
