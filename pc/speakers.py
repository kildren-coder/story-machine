# -*- coding: utf-8 -*-
"""speakers.py — 声纹库：把这一集的匿名 SPEAKER_XX 认成人名。

    python pc\\speakers.py --ep EP02                       只认，不改库
    python pc\\speakers.py --ep EP02 --names names.json    先入库再认（点名回填）
    python pc\\speakers.py --ep EP02 --out result.json     结果给 worker.ps1 读
    python pc\\speakers.py --list                          看看库里都有谁

在笔记本上跑，只要 numpy——`EP{n}.diar.json` 里带着各簇的质心，CAM++ 和 torch
留在 PC 上（见 smdiar.py 的 speaker_centroids）。

**为什么这件事做得成**：CAM++ 本来就是说话人**验证**模型，它的 embedding 生来
就是拿来比对的。实测用 EP01（瓜哥独白）建的声纹去认 EP02，主播 0.871、嘉宾
0.347，逐窗分布连碰都不碰。直播人物长期固定，所以库越攒越省事——认出来的不用
再点名，只有生面孔才需要人开口。

**库是人的判断的存档，不是自动结论。** 名字只有一个入口：人在 EP 笔记里点名。
认不出来就老实显示「未知N」，绝不猜。
"""

import argparse
import io
import json
import pathlib
import sys
import time

import numpy as np

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

VAULT = pathlib.Path(r"D:\obsidian-task\任务栏\story-machine")
ASSETS = VAULT / "_assets"
LIB = ASSETS / "speakers.json"

# 判「是同一个人」的门槛。实测的两头差得很远：同一人跨集 0.871，不同人 0.327–0.354，
# 中间 0.5–0.8 一片空白。0.65 落在这片空白正中，不是调出来的数。
# 但它目前只有**一对**跨集样本撑着（瓜哥 EP01→EP02），攒够几集要回来复核。
THRESHOLD = 0.65
# 还要甩开第二名这么多，否则算认不准。库里进了声音相近的人时这条才起作用。
MARGIN = 0.10
# 每人最多留这么多集的样本，按时长取长的。质心从样本按时长加权重算，
# 所以入库是幂等的：同一集再点一次名，替换而不是叠加。
MAX_SAMPLES = 20

# 库内两个人像到这个程度就报警。
#
# 为什么需要它：这个库是**全局**的，不按节目/来源分。人越攒越多，就越可能有个
# 新面孔碰巧跟某个老人撞过 0.65 被认错——而认错是**静默**的，笔记上只会写一个
# 看起来很正常的名字。实测目前不同人之间是 0.33–0.35，同一人跨集 0.87，中间一大
# 片空白；0.50 落在「已经明显高于正常异人值」和「还没到认定门槛」之间，报得出苗头
# 又不会天天叫。
#
# 报警不改任何判定——它只是让你在库变脏的那一天知道，而不是半年后翻出一堆错名字。
LIB_WARN = 0.50

ROLES = ("主播", "嘉宾")


def load(path, default=None):
    if not path.exists():
        return default
    with io.open(path, encoding="utf-8") as f:
        return json.load(f)


def save(path, doc):
    tmp = path.with_suffix(path.suffix + ".tmp")
    with io.open(tmp, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)
    tmp.replace(path)


def hms(sec):
    if sec is None:
        return ""
    sec = int(sec)
    return "%02d:%02d:%02d" % (sec // 3600, sec % 3600 // 60, sec % 60)


def unit(v):
    v = np.asarray(v, dtype=np.float64)
    return v / (np.linalg.norm(v) + 1e-9)


def empty_lib():
    return {"version": 1, "dim": 192, "threshold": THRESHOLD, "people": []}


def pooled(person):
    """按时长加权把样本合成一个质心。库文件里存的是样本，质心随取随算——
    这样「谁贡献了多少」永远查得到，删掉一集也能重算，不是一笔糊涂账。"""
    ws = np.asarray([max(1.0, s["seconds"]) for s in person["samples"]])
    m = np.asarray([unit(s["centroid"]) for s in person["samples"]])
    return unit((m * ws[:, None]).sum(axis=0) / ws.sum())


# ---------------------------------------------------------------- 入库

def enroll(lib, name, role, ep, centroid, seconds):
    # 改名要先把这一集从别人名下摘掉，否则「点错了改回来」会在旧主人那里留一份
    # 脏样本，而且越攒越难查——那正是把库搞脏的经典路径。
    for p in lib["people"]:
        if p["name"] != name:
            p["samples"] = [s for s in p["samples"] if s["ep"] != ep]
    lib["people"] = [p for p in lib["people"] if p["samples"] or p["name"] == name]

    by_name = {p["name"]: p for p in lib["people"]}
    person = by_name.get(name)
    if person is None:
        person = {"name": name, "role": role, "samples": []}
        lib["people"].append(person)
    elif role and person.get("role") != role:
        person["role"] = role

    sample = {"ep": ep, "seconds": round(float(seconds), 1),
              "centroid": [round(float(v), 6) for v in unit(centroid)],
              "at": time.strftime("%Y-%m-%dT%H:%M:%S")}
    person["samples"] = [s for s in person["samples"] if s["ep"] != ep] + [sample]
    person["samples"].sort(key=lambda s: -s["seconds"])
    dropped = person["samples"][MAX_SAMPLES:]
    person["samples"] = person["samples"][:MAX_SAMPLES]
    return person, len(dropped)


def parse_name(raw):
    """「历史哥」/「历史哥 嘉宾」/「历史哥/主播」 → (名字, 角色或 None)"""
    raw = (raw or "").strip()
    for r in ROLES:
        for sep in (" ", "/", "　", "、"):
            if raw.endswith(sep + r):
                return raw[:-(len(r) + 1)].strip(), r
    return raw, None


# ---------------------------------------------------------------- 比对

def risky_pairs(lib, floor=None):
    """库里两两比一遍，挑出像得过头的那些对，从高到低。"""
    floor = LIB_WARN if floor is None else floor
    people = lib["people"]
    if len(people) < 2:
        return []
    pr = {p["name"]: pooled(p) for p in people}
    names = sorted(pr)
    out = []
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            s = float(np.dot(pr[a], pr[b]))
            if s >= floor:
                out.append([a, b, round(s, 4)])
    return sorted(out, key=lambda r: -r[2])


def resolve(lib, diar):
    """给每个簇一个归属。返回按首次出现排序的列表。"""
    people = lib["people"]
    prints = {p["name"]: pooled(p) for p in people} if people else {}
    meta = diar.get("speakers") or {}

    rows = []
    for spk, cent in sorted(diar["centroids"].items()):
        c = unit(cent)
        scored = sorted(((float(np.dot(c, v)), n) for n, v in prints.items()), reverse=True)
        info = meta.get(spk) or {}
        # 所有键一律给全（缺的填 null）：worker.ps1 在 StrictMode 下取不存在的属性会抛
        rows.append({"speaker": spk, "seconds": info.get("seconds"),
                     "first": info.get("first"), "scored": scored,
                     "name": None, "role": None, "score": None, "status": "unknown",
                     "unknown": None, "dup_of": None, "like": []})

    # 贪心指派，每个人在一集里只能占一个簇。两个簇都指向同一个人不是要挑一个赢家，
    # 而是分离器把一个人切成了两半——那正是该让人看见的事，所以标成「疑似重复」
    # 而不是悄悄给第二个簇换个名字。
    taken = {}
    order = sorted(rows, key=lambda r: -(r["scored"][0][0] if r["scored"] else -1))
    for r in order:
        if not r["scored"]:
            continue
        best, name = r["scored"][0]
        runner = r["scored"][1][0] if len(r["scored"]) > 1 else -1.0
        r["score"] = round(best, 4)
        if best < THRESHOLD:
            continue
        if best - runner < MARGIN:
            r["status"] = "ambiguous"     # 库里有两个人都像，不猜
            r["like"] = [n for _, n in r["scored"][:2]]
            continue
        if name in taken:
            r["status"] = "dup"
            r["dup_of"] = taken[name]
            r["name"] = name
            continue
        taken[name] = r["speaker"]
        r["name"] = name
        r["status"] = "known"
        r["role"] = next((p.get("role") for p in people if p["name"] == name), None)

    n = 0
    for r in sorted(rows, key=lambda r: (r["first"] is None, r["first"])):
        if r["status"] != "known":
            n += 1
            r["unknown"] = "未知%d" % n
    for r in rows:
        r.pop("scored", None)
    return sorted(rows, key=lambda r: (r["first"] is None, r["first"]))


# ---------------------------------------------------------------- 命令

def cmd_list(lib):
    if not lib["people"]:
        print("库是空的。到 EP 笔记的说话人小表里点名，跑一次 worker 就入库了。")
        return
    print("声纹库 %s —— %d 人" % (LIB, len(lib["people"])))
    for p in sorted(lib["people"], key=lambda p: p["name"]):
        eps = "、".join(s["ep"] for s in p["samples"])
        secs = sum(s["seconds"] for s in p["samples"])
        print("  %-8s %-4s %d 集 / 共 %s   （%s）"
              % (p["name"], p.get("role") or "—", len(p["samples"]), hms(secs), eps))
    names = [p["name"] for p in lib["people"]]
    if len(names) > 1:
        print("\n库内两两相似度（同一人跨集实测 0.871，不同人 0.33；这里若有高分说明库脏了）：")
        pr = {p["name"]: pooled(p) for p in lib["people"]}
        for i, a in enumerate(names):
            for b in names[i + 1:]:
                print("  %s × %s  %.3f" % (a, b, float(np.dot(pr[a], pr[b]))))
        print_lib_warning(lib)


def print_lib_warning(lib):
    risky = risky_pairs(lib)
    if not risky:
        return
    print("\n⚠ 声纹库该体检了——下面这些人已经像到 %.2f 以上（认定门槛 %.2f）：" % (LIB_WARN, THRESHOLD))
    for a, b, s in risky:
        print("  %s × %s  %.3f%s" % (a, b, s, "   ← 已越过门槛，随时可能认错" if s >= THRESHOLD else ""))
    print("  多半是两种情况：(1) 某一集点错了名，把两个人的声音混进了同一个人名下；"
          "(2) 确实有两个人声音很像。\n"
          "  第一种去那一集的说话人小表改方括号里的名字即可（改一个字就是一次重新入库）。")


def main():
    ap = argparse.ArgumentParser(prog="speakers.py")
    ap.add_argument("--ep")
    ap.add_argument("--names", help="点名结果 JSON：{\"SPEAKER_01\": \"历史哥\"}，"
                                    "值可写成「名字 主播」带上角色")
    ap.add_argument("--out", help="把归属结果写到这个 JSON，供 worker.ps1 读")
    ap.add_argument("--vault", default=str(VAULT))
    ap.add_argument("--list", action="store_true")
    a = ap.parse_args()

    global ASSETS, LIB
    ASSETS = pathlib.Path(a.vault) / "_assets"
    LIB = ASSETS / "speakers.json"

    lib = load(LIB, empty_lib())
    if a.list:
        cmd_list(lib)
        return
    if not a.ep:
        ap.error("要么 --list，要么给 --ep")

    diar_path = ASSETS / ("%s.diar.json" % a.ep)
    diar = load(diar_path)
    if diar is None:
        sys.exit("没有 %s——这一集还没分离，或还没取回" % diar_path)
    if not diar.get("centroids"):
        sys.exit("%s 里没有 centroids：这一集分离于声纹库之前，"
                 "重跑一次 smdiar.py 即可（embedding 有缓存，很快）" % diar_path.name)

    if a.names:
        named = load(pathlib.Path(a.names)) or {}
        meta = diar.get("speakers") or {}
        # 先看库现在怎么判，只有人写的和库判的不一致才动库。所以人把认对的名字
        # 留在笔记里不会每轮重复入库，而改一个字就是一次更正。
        before = {r["speaker"]: r for r in resolve(lib, diar)}
        dirty = False
        for spk, raw in named.items():
            name, role = parse_name(raw)
            if not name or spk not in diar["centroids"]:
                continue
            was = before.get(spk) or {}
            person_now = next((p for p in lib["people"] if p["name"] == name), None)
            if was.get("name") == name and (not role or (person_now or {}).get("role") == role):
                continue
            secs = (meta.get(spk) or {}).get("seconds") or 0.0
            person, dropped = enroll(lib, name, role, a.ep, diar["centroids"][spk], secs)
            dirty = True
            print("入库 %s = %s%s，本集 %s，共 %d 集样本%s"
                  % (spk, name, "（%s）" % role if role else "", hms(secs),
                     len(person["samples"]), "（挤掉 %d 个短样本）" % dropped if dropped else ""))
        if dirty:
            lib["threshold"] = THRESHOLD
            save(LIB, lib)

    rows = resolve(lib, diar)
    print("=== %s ===" % a.ep)
    for r in rows:
        who = r["name"] or r.get("unknown")
        tag = {"known": "", "dup": "  ← 疑似与 %s 是同一人被切成两半" % r.get("dup_of"),
               "ambiguous": "  ← 库里 %s 都像，不猜" % "、".join(r.get("like") or []),
               "unknown": ""}[r["status"]]
        print("  %-12s %-8s 相似度 %-6s %s（%s 首次出现）%s"
              % (r["speaker"], who,
                 "%.3f" % r["score"] if r["score"] is not None else "—",
                 hms(r["seconds"]), hms(r["first"]), tag))

    print_lib_warning(lib)

    if a.out:
        # lib_risky 随每次比对一起回去，worker 只把**跟本集有关**的那几对写进笔记
        save(pathlib.Path(a.out), {"ep": a.ep, "threshold": THRESHOLD,
                                   "lib_warn": LIB_WARN, "lib_risky": risky_pairs(lib),
                                   "people": rows})


if __name__ == "__main__":
    main()
