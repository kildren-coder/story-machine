# -*- coding: ascii -*-
# t2s_backfill.py -- normalise already-produced transcripts to simplified characters.
#
#   python pc\t2s_backfill.py E:\asr\staged          # on the PC (staged copies)
#   python pc\t2s_backfill.py <vault>\_assets        # on the laptop (vault copies)
#   python pc\t2s_backfill.py <dir> --dry-run
#
# smpc.py now converts at write time (see to_simplified there for why). Episodes
# transcribed before that carry Whisper's mixed orthography: the mainland host
# comes out simplified, the Taiwan-accented guest comes out ~73% traditional.
# This walks the artifacts and applies the same per-character table.
#
# Conversion is per character and idempotent, so a second run reports 0 and the
# words/transcript concatenation invariant that check_diar.py relies on survives.
# Files touched: *.transcript.json, *.transcript.nodiar.json (segment text),
# *.words.json (word tokens), *.txt (derived render). *.diar.json holds no text.
#
# ASCII only: this also runs over ssh, where stdout is a PowerShell code page.

import argparse
import io
import json
import pathlib
import sys

_CC = None
_CHAR = {}


def to_simplified(text):
    global _CC
    if _CC is None:
        import opencc
        _CC = opencc.OpenCC("t2s")
    buf = []
    for ch in text:
        if ch not in _CHAR:
            _CHAR[ch] = _CC.convert(ch)
        buf.append(_CHAR[ch])
    return "".join(buf)


def changed(before, after):
    return sum(1 for a, b in zip(before, after) if a != b)


def load(path):
    with io.open(path, encoding="utf-8") as f:
        return json.load(f)


def save(path, doc, indent):
    with io.open(path, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=indent)


def do_transcript(path, dry):
    doc = load(path)
    n = 0
    for seg in doc.get("segments") or []:
        before = seg.get("text") or ""
        after = to_simplified(before)
        n += changed(before, after)
        seg["text"] = after
    doc["orthography"] = "opencc t2s per-char"
    doc.setdefault("orthography_chars", 0)
    doc["orthography_chars"] += n
    # smpc.py writes transcript.json with indent=1, smdiar.py rewrites it compact;
    # follow whatever the file already is so the diff stays about the characters.
    if not dry:
        save(path, doc, 1 if path.name.endswith(".transcript.json") else None)
    return n


def do_words(path, dry):
    doc = load(path)
    n = 0
    for seg in doc.get("segments") or []:
        for w in seg:
            before = w[2]
            after = to_simplified(before)
            n += changed(before, after)
            w[2] = after
    if not dry:
        save(path, doc, None)
    return n


def do_text(path, dry):
    with io.open(path, encoding="utf-8") as f:
        before = f.read()
    after = to_simplified(before)
    n = changed(before, after)
    if not dry and n:
        with io.open(path, "w", encoding="utf-8") as f:
            f.write(after)
    return n


def main():
    ap = argparse.ArgumentParser(prog="t2s_backfill.py")
    ap.add_argument("dir")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    root = pathlib.Path(a.dir)
    if not root.is_dir():
        sys.exit("not a directory: %s" % root)

    jobs = []
    for p in sorted(root.glob("EP*")):
        if p.name.endswith(".transcript.json") or p.name.endswith(".transcript.nodiar.json"):
            jobs.append((p, do_transcript))
        elif p.name.endswith(".words.json"):
            jobs.append((p, do_words))
        elif p.suffix == ".txt":
            jobs.append((p, do_text))
    if not jobs:
        sys.exit("no EP* transcript artifacts under %s" % root)

    total = 0
    for p, fn in jobs:
        n = fn(p, a.dry_run)
        total += n
        print("%-40s %6d chars" % (p.name, n))
    print("%s: %d characters converted across %d files"
          % ("would convert" if a.dry_run else "converted", total, len(jobs)))


if __name__ == "__main__":
    main()
