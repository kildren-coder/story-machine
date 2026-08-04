# smdiar.py -- speaker diarization for story-machine (SPEC stage 0 sub-step)
#
#   C:\asr\venv-diar\Scripts\python.exe C:\asr\smdiar.py --ep EP01
#   ...                                 --ep EP01 --speakers 2      lock K
#
# Contract (same as smpc.py, see its header):
#   1. stdout is ASCII only: PROGRESS <done> <total> / INFO <text> / ERROR <text>
#   2. all artifacts land in E:\asr\staged\EP{n}.*
#   3. non-ASCII (transcript text) travels by file, never through argv/stdout
#
# Why this exists as a separate venv: 3D-Speaker needs torch, the ASR venv
# must stay torch-free (SPEC stage 0: "independent venv, CPU only").
#
# Approach -- and why not the packaged diarization pipeline:
#   faster-whisper already gave us VAD-filtered segments AND word timestamps.
#   The packaged pipeline would redo VAD and hand back a speaker timeline we
#   then have to reconcile with our words. Instead we embed short windows cut
#   at word boundaries, cluster those, and label the words directly -- one
#   less alignment step, and the boundaries stay exactly on words.
#
#   Segments from Whisper run ~26s median, so "one speaker per segment" is far
#   too coarse for a multi-person show; segments get rebuilt from labelled
#   words. The pre-diarization transcript is kept as EP{n}.transcript.nodiar.json.

import argparse
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import time

os.environ.pop("HF_ENDPOINT", None)   # hf-mirror 302s and breaks resolve; see notes

STAGE_DIR = pathlib.Path(r"E:\asr\staged")
MODEL = "iic/speech_campplus_sv_zh_en_16k-common_advanced"   # CAM++ CN-EN
SR = 16000

# Swept 1.5 / 2 / 3 / 4s against the two-voice fixture: 93.7 / 96.3 / 98.2 / 97.9%.
# 3s also embeds ~30% fewer windows than 2s. Longer than that starts swallowing
# short interjections, and the gain is already gone by 4s.
WINDOW_S = 3.0      # target embedding window
MIN_WINDOW_S = 0.6  # shorter than this yields an unreliable embedding
GAP_S = 0.35        # word gap that may hide a speaker change
MERGE_GAP_S = 1.0   # gap above which we start a new segment even for one speaker
MAX_SEG_S = 30.0    # keep rebuilt segments comparable to Whisper's


def out(kind, *parts):
    sys.stdout.write(kind + (" " + " ".join(str(p) for p in parts) if parts else "") + "\n")
    sys.stdout.flush()


def info(msg):
    out("INFO", msg)


def fail(msg):
    out("ERROR", msg)
    sys.exit(1)


def hms(sec):
    sec = int(sec)
    return "%02d:%02d:%02d" % (sec // 3600, sec % 3600 // 60, sec % 60)


# ---------------------------------------------------------------- audio

def decode_16k_mono(src, dst):
    cmd = ["ffmpeg", "-nostdin", "-loglevel", "error", "-y", "-i", str(src),
           "-ac", "1", "-ar", str(SR), "-f", "wav", str(dst)]
    p = subprocess.run(cmd, capture_output=True, text=True, errors="replace")
    if p.returncode != 0:
        fail("ffmpeg failed (exit %d): %s" % (p.returncode, (p.stderr or "")[-300:]))


# ---------------------------------------------------------------- windows

def build_windows(word_segments):
    """Cut the word stream into ~WINDOW_S windows. Returns (windows, words).

    windows: list of (start, end, first_word_idx, last_word_idx)
    words:   flat list of (start, end, text), in the order Whisper emitted them

    Every word lands in exactly one window and the order is never touched.
    Both halves of that were bugs once, and both silently corrupted the
    transcript:
      - dropping zero-length words deleted characters (EP02 lost the dashes
        out of "H-E-U-T-A"; 20 and 36 words in EP01/EP02 have start == end)
      - sorting by start time swapped neighbours wherever Whisper emits
        crossing timestamps ("战斗机中国" came back as "战斗中国...机")
    The transcript is ground truth here. Timestamps annotate it; they do not
    order it, and they are not always sane.
    """
    words = [(float(w[0]), float(w[1]), w[2]) for seg in word_segments for w in seg]
    if not words:
        return [], words

    # split into runs at word gaps -- a gap is where a turn change can hide.
    # crossing timestamps make the gap negative, which simply never splits.
    runs, cur = [], [0]
    for i in range(1, len(words)):
        if words[i][0] - words[i - 1][1] >= GAP_S:
            runs.append(cur)
            cur = []
        cur.append(i)
    runs.append(cur)

    windows = []
    for run in runs:
        i = 0
        while i < len(run):
            j, start = i, words[run[i]][0]
            while j < len(run) and words[run[j]][1] - start < WINDOW_S:
                j += 1
            j = min(max(j, i + 1), len(run))
            span = run[i:j]                       # contiguous, so nothing is skipped
            lo = min(words[k][0] for k in span)   # min/max, not first/last: see above
            hi = max(words[k][1] for k in span)
            windows.append((lo, hi, span[0], span[-1]))
            i = j
    return windows, words


# ---------------------------------------------------------------- embeddings

def load_emb_cache(path, bounds):
    """Return cached embeddings iff they were computed for exactly these windows."""
    import numpy as np
    if not path.exists():
        return None
    try:
        z = np.load(path)
        w = z["windows"]
    except Exception as ex:                       # corrupt cache is not an error
        info("ignoring unreadable %s (%s)" % (path.name, type(ex).__name__))
        return None
    if w.shape != bounds.shape or not np.allclose(w, bounds, atol=1e-3):
        info("window layout changed -> re-embedding")
        return None
    return z["embs"]


# ---------------------------------------------------------------- clustering

# A real participant talks for at least this long. Deliberately absolute and not
# a share of the episode: a 5% floor sounds harmless until you notice that 5% of
# a three-hour show is nine minutes, so a guest who says his piece in eight gets
# silently merged into the host. That guest is exactly who the roll-call in the
# EP note exists to surface. An outlier cluster is a second or two, so 60s alone
# already keeps those out, and over-splitting is the cheap failure here: a human
# spots a duplicate at naming time in seconds, a silent merge is invisible.
MIN_SECONDS = 60.0


def pick_labels(embs, durations, forced_k, max_k):
    """Cluster window embeddings, choosing K by silhouette among *plausible* Ks.

    Two things had to be got right here, and the first version got both wrong.

    Clusterer: cosine + average linkage does not work on these embeddings. It
    peels off one outlier window at a time and calls that a cluster, which looks
    like a beautiful silhouette and means nothing. Measured on a fixture of two
    TTS voices reading in turns (pc/mkfixture.py), it scored 51.9% -- chance.
    Centre-then-renormalise (drop the per-recording component: the room, the mic,
    the codec) followed by Ward linkage scored 96.3% on the same audio, and it is
    what finally separated EP02's host from his guest -- an episode this function
    had previously reported as one person.

    K: silhouette alone still is not enough, because a lone outlier keeps
    scoring well at every K. So a K only counts if every cluster holds a real
    amount of talk time; otherwise it is an outlier, not a person.
    """
    import numpy as np
    from sklearn.cluster import AgglomerativeClustering
    from sklearn.metrics import silhouette_score

    def unit(v):
        return v / (np.linalg.norm(v, axis=1, keepdims=True) + 1e-9)

    x = unit(unit(embs) - unit(embs).mean(axis=0, keepdims=True))
    dur = np.asarray(durations, dtype=np.float64)
    total = float(dur.sum())

    def cluster(k):
        return AgglomerativeClustering(n_clusters=k, linkage="ward").fit_predict(x)

    if forced_k:
        info("K locked to %d by --speakers" % forced_k)
        lab = cluster(forced_k) if forced_k > 1 else np.zeros(len(x), dtype=int)
        return lab, forced_k, None

    best_k, best_lab, best_sil = 1, None, -1.0
    for k in range(2, max_k + 1):
        if len(x) <= k:
            break
        lab = cluster(k)
        sil = float(silhouette_score(x, lab, metric="cosine"))
        secs = [float(dur[lab == c].sum()) for c in range(k)]
        smallest = min(secs)
        ok = smallest >= MIN_SECONDS
        info("  K=%d silhouette=%.3f smallest_cluster=%.0fs (%.1f%%) %s"
             % (k, sil, smallest, 100 * smallest / total, "ok" if ok else "REJECTED"))
        if ok and sil > best_sil:
            best_k, best_lab, best_sil = k, lab, sil

    if best_lab is None:
        info("no K>=2 survived the share test -> single speaker")
        return np.zeros(len(x), dtype=int), 1, None
    # Measured: EP01 (one man talking for two hours) tops out at 0.064, while
    # EP02 (host + guest) sits at 0.450 and the TTS fixture at 0.564. The gap is
    # wide enough that 0.10 is not a tuned number, it is the middle of nowhere.
    # Erring low is deliberate anyway: a human spots an over-split at naming
    # time in seconds, whereas a silent merge is invisible.
    if best_sil < 0.10:
        info("best silhouette %.3f below 0.10 -> single speaker" % best_sil)
        return np.zeros(len(x), dtype=int), 1, best_sil
    return best_lab, best_k, best_sil


# ---------------------------------------------------------------- voiceprints

def speaker_centroids(embs, names):
    """One voiceprint per cluster, for matching against the speaker library.

    In the RAW embedding space, deliberately not the centred space pick_labels
    clusters in. Centring subtracts *this recording's* own mean, so those
    coordinates only mean anything inside this one file -- measured across
    EP01/EP02 the same man's centred vectors score -0.305 and 0.324 against each
    other, the sign itself flips. Raw, that pair scores 0.871 while the other
    speaker scores 0.347, and the per-window distributions do not even overlap.

    Averaging is what buys that margin: a centroid pools ~1.5h of speech, so the
    room, the mic and the mood average out in a way no single window can.
    """
    import numpy as np
    x = embs / (np.linalg.norm(embs, axis=1, keepdims=True) + 1e-9)
    out = {}
    for n in sorted(set(names)):
        pick = np.asarray([m == n for m in names])
        c = x[pick].mean(axis=0)
        c = c / (np.linalg.norm(c) + 1e-9)
        out[n] = [round(float(v), 6) for v in c]
    return out


# ---------------------------------------------------------------- segments

def rebuild_segments(words, word_speaker):
    segs = []
    cur = None
    for i, (s, e, txt) in enumerate(words):
        spk = word_speaker[i]
        if (cur is None or spk != cur["speaker"]
                or s - cur["end"] >= MERGE_GAP_S
                or e - cur["start"] > MAX_SEG_S):
            if cur:
                segs.append(cur)
            cur = {"start": s, "end": e, "speaker": spk, "parts": [txt]}
        else:
            cur["end"] = max(cur["end"], e)   # crossing timestamps must not rewind it
            cur["parts"].append(txt)
    if cur:
        segs.append(cur)

    for sg in segs:
        text = "".join(sg.pop("parts"))
        # Whisper emits leading spaces on latin tokens; collapse the doubles that
        # creates without touching the Chinese, which carries no spaces at all.
        sg["text"] = " ".join(text.split()) if " " in text else text
        sg["start"] = round(sg["start"], 2)
        sg["end"] = round(sg["end"], 2)
    return segs


# ---------------------------------------------------------------- main

def cmd_diarize(ep, forced_k, max_k):
    words_path = STAGE_DIR / (ep + ".words.json")
    tr_path = STAGE_DIR / (ep + ".transcript.json")
    audio = None
    for cand in STAGE_DIR.glob(ep + ".*"):
        if cand.suffix.lower() in (".m4a", ".mp3", ".wav", ".webm", ".opus"):
            audio = cand
            break
    if not words_path.exists():
        fail("missing %s -- re-run transcribe to get word timestamps" % words_path.name)
    if not tr_path.exists():
        fail("missing %s" % tr_path.name)
    if audio is None:
        fail("no audio file for %s in %s" % (ep, STAGE_DIR))

    import numpy as np
    import soundfile as sf
    import torch

    torch.set_num_threads(os.cpu_count() or 4)

    # Reruns must start from the pristine transcript, not from our own output --
    # otherwise the "segments N -> M" line compares against an already-rebuilt count.
    nodiar = STAGE_DIR / (ep + ".transcript.nodiar.json")
    doc = json.loads((nodiar if nodiar.exists() else tr_path).read_text(encoding="utf-8"))
    if nodiar.exists():
        info("restarting from %s" % nodiar.name)
    word_segments = json.loads(words_path.read_text(encoding="utf-8"))["segments"]
    windows, words = build_windows(word_segments)
    info("words=%d windows=%d (from %d whisper segments)"
         % (len(words), len(windows), len(doc["segments"])))
    if not windows:
        fail("no usable windows -- word timestamps look empty")

    # Embedding is the whole cost of this step (~160s for a 2h show) and it does
    # not depend on how we cluster. Cache it keyed on the window boundaries, so
    # trying a different K or a different clusterer is free.
    cache = STAGE_DIR / (ep + ".emb.npz")
    bounds = np.asarray([[w[0], w[1]] for w in windows], dtype=np.float32)
    embs = load_emb_cache(cache, bounds)
    if embs is not None:
        info("reusing %d cached embeddings (%s)" % (len(embs), cache.name))
    else:
        tmpdir = pathlib.Path(tempfile.mkdtemp(prefix="smdiar_"))
        wav = tmpdir / (ep + ".wav")
        t0 = time.time()
        decode_16k_mono(audio, wav)
        info("decoded to 16k mono in %.1fs (%s)" % (time.time() - t0, audio.name))

        from modelscope.pipelines import pipeline
        t0 = time.time()
        sv = pipeline(task="speaker-verification", model=MODEL, device="cpu")
        info("CAM++ loaded in %.1fs" % (time.time() - t0))

        # The pipeline only takes pairs, so windows go through two at a time.
        t0 = time.time()
        embs = np.zeros((len(windows), 192), dtype=np.float32)
        short = 0
        with sf.SoundFile(str(wav)) as snd:
            def grab(w):
                nonlocal short
                start, end = w[0], w[1]
                if end - start < MIN_WINDOW_S:      # pad short windows outward
                    short += 1
                    mid = (start + end) / 2
                    start, end = mid - MIN_WINDOW_S / 2, mid + MIN_WINDOW_S / 2
                a = max(0, int(start * SR))
                n = max(1, int((end - start) * SR))
                snd.seek(a)
                x = snd.read(n, dtype="float32", always_2d=False)
                return x if len(x) else np.zeros(int(MIN_WINDOW_S * SR), dtype=np.float32)

            for i in range(0, len(windows), 2):
                pair = [grab(windows[i])]
                pair.append(grab(windows[i + 1]) if i + 1 < len(windows) else pair[0])
                r = sv(pair, output_emb=True)
                e = np.asarray(r["embs"], dtype=np.float32)
                embs[i] = e[0]
                if i + 1 < len(windows):
                    embs[i + 1] = e[1]
                if i % 200 == 0:
                    out("PROGRESS", i, len(windows))
        out("PROGRESS", len(windows), len(windows))
        info("embedded %d windows in %.0fs (%d padded as too short)"
             % (len(windows), time.time() - t0, short))
        np.savez(cache, windows=bounds, embs=embs)
        for f in tmpdir.glob("*"):
            f.unlink()
        tmpdir.rmdir()

    labels, k, sil = pick_labels(embs, [w[1] - w[0] for w in windows], forced_k, max_k)

    # name speakers by first appearance so SPEAKER_00 is whoever opens the show
    order, seen = {}, 0
    for lab in labels:
        if lab not in order:
            order[lab] = seen
            seen += 1
    names = ["SPEAKER_%02d" % order[l] for l in labels]

    word_speaker = [None] * len(words)
    for (_, _, wi, wj), name in zip(windows, names):
        for idx in range(wi, wj + 1):
            word_speaker[idx] = name
    for i in range(len(word_speaker)):        # words that fell between windows
        if word_speaker[i] is None:
            word_speaker[i] = word_speaker[i - 1] if i else names[0]

    segs = rebuild_segments(words, word_speaker)

    talk = {}
    for sg in segs:
        talk[sg["speaker"]] = talk.get(sg["speaker"], 0.0) + (sg["end"] - sg["start"])
    info("K=%d  segments %d -> %d" % (k, len(doc["segments"]), len(segs)))
    for name in sorted(talk):
        info("  %s %s (%.1f%%)" % (name, hms(talk[name]), 100 * talk[name] / sum(talk.values())))

    # keep the pre-diarization transcript for one round of comparison
    if not nodiar.exists():
        nodiar.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")

    doc["segments"] = segs
    doc["diarization"] = "3dspeaker-campp"
    doc["diarization_model"] = MODEL
    doc["speakers"] = sorted(talk)
    doc["speaker_seconds"] = {n: round(v, 1) for n, v in sorted(talk.items())}
    doc["diarization_silhouette"] = round(sil, 4) if sil is not None else None
    doc["diarized_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    tr_path.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")

    # Window-level detail for spot-checking a suspicious stretch, plus the
    # voiceprints. The centroids ride along here so the naming step can run on
    # the laptop with nothing but numpy -- CAM++ and torch stay on the PC.
    first = {}
    for sg in segs:
        first.setdefault(sg["speaker"], sg["start"])
    (STAGE_DIR / (ep + ".diar.json")).write_text(json.dumps(
        {"ep": ep, "model": MODEL, "k": k, "silhouette": sil,
         "centroids": speaker_centroids(embs, names),
         "speakers": {n: {"seconds": round(talk[n], 1), "first": first.get(n)}
                      for n in sorted(talk)},
         "windows": [[round(w[0], 2), round(w[1], 2), n] for w, n in zip(windows, names)]},
        ensure_ascii=False), encoding="utf-8")

    info("done")


def main():
    ap = argparse.ArgumentParser(prog="smdiar.py")
    ap.add_argument("--ep", required=True)
    ap.add_argument("--speakers", type=int, default=0, help="lock K instead of estimating")
    ap.add_argument("--max-speakers", type=int, default=4)
    ap.add_argument("--window", type=float, default=WINDOW_S,
                    help="embedding window in seconds (for sweeping; default %g)" % WINDOW_S)
    a = ap.parse_args()
    globals()["WINDOW_S"] = a.window
    cmd_diarize(a.ep, a.speakers, a.max_speakers)


if __name__ == "__main__":
    main()
