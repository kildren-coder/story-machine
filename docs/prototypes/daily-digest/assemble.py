# -*- coding: utf-8 -*-
"""assemble.py — 把 data.json 注进 template.html，顺手给每条原话补上逐字稿片段（ctx）。
用法：python assemble.py   （在 proto 目录下跑）
"""
import json, io, sys, os
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
ASSETS = os.path.join(os.environ.get("SM_ASSETS", ""), "")

def hms(s):
    s = int(s); return f"{s//3600:02d}:{s%3600//60:02d}:{s%60:02d}"

def load_segments(ep):
    with open(os.path.join(ASSETS, f"{ep}.transcript.json"), encoding="utf-8") as f:
        return json.load(f)["segments"]

def seg_at(segs, ts, quote):
    """先找包含引文的段；找不到就取时间戳所在的段。"""
    for s in segs:
        if quote and quote.replace("，","").replace("。","") in s["text"]:
            return s
    h, m, sec = map(int, ts.split(":")); t = h*3600 + m*60 + sec
    best = None
    for s in segs:
        if s["start"] <= t + 0.5:
            best = s
        else:
            break
    return best

def main():
    data = json.load(open(os.path.join(HERE, "data-base.json"), encoding="utf-8"))
    # 话题片段按块顺序并进对应 source
    for src in data["sources"]:
        for frag in src.pop("frags", []):
            fp = os.path.join(HERE, frag)
            if not os.path.exists(fp):
                print("缺片段：", frag); continue
            f = json.load(open(fp, encoding="utf-8"))
            src.setdefault("topics", []).extend(f.get("topics", []))
            src.setdefault("channels", []).extend(f.get("channels", []))
    # 核查结果按文件挂到事件上
    picked = {}
    for ev in data["events"]:
        pk = ev.pop("checkPick", None)
        if pk:
            src = json.load(open(os.path.join(HERE, pk["file"]), encoding="utf-8"))
            devs = [d for d in src["deviations"] if d["ts"] in pk["ts"]]
            picked.setdefault(pk["file"], set()).update(pk["ts"])
            ev["check"] = {"overall": pk.get("overall", "none"), "deviations": devs, "support": [], "against": [],
                           "history": None, "sources": [l for d in devs for l in d.get("links", [])], "note": pk.get("note", "")}
    for ev in data["events"]:
        cf = ev.pop("checkFile", None)
        if cf:
            fp = os.path.join(HERE, cf)
            if os.path.exists(fp):
                ev["check"] = json.load(open(fp, encoding="utf-8"))
                gone = picked.get(cf, set())
                ev["check"]["deviations"] = [d for d in ev["check"]["deviations"] if d["ts"] not in gone]
            else:
                print("缺核查：", cf)
    missing = []
    for src in data["sources"]:
        segs = load_segments(src["id"])
        for t in src.get("topics", []):
            for q in t.get("quotes", []):
                s = seg_at(segs, q["ts"], q["text"])
                if s is None:
                    missing.append((src["id"], q["ts"])); continue
                q["ctx"] = s["text"]
                if q["text"].replace("，","").replace("。","") not in s["text"]:
                    missing.append((src["id"], q["ts"], q["text"][:20]))
    tpl = open(os.path.join(HERE, "template.html"), encoding="utf-8").read()
    html = tpl.replace("/*__DATA__*/null", json.dumps(data, ensure_ascii=False))
    out = os.path.join(HERE, "daily-proto.html")
    open(out, "w", encoding="utf-8").write(html)
    print("wrote", out, len(html), "bytes")
    if missing:
        print("引文未在所在段命中（闸门 1 会拦）：")
        for m in missing: print("  ", m)

if __name__ == "__main__":
    main()
