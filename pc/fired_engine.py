# -*- coding: utf-8 -*-
"""fired_engine.py — FireRedASR2-AED 的引擎接线（SPEC §4 阶段 0，ADR 0006）。部署到 C:\\asr\\fired_engine.py。

只给 `smpc.py transcribe` 用，跑在 `E:\\asr\\venv-fired`（torch CUDA 版）。torch、numpy、
faster_whisper、FireRedASR2S 一律在函数里 import：smpc.py 的 download 子命令跑在没有
torch 的 C:\\asr\\venv，不能因为 import 本文件就炸。

规则（切块、分批、对账、挂词、标点只插不改）都在 asrblocks.py；这里只管：
- 解音频、跑 VAD、把块切成 16 kHz int16 wav（喂法与 EP02 对照实验相同）；
- 加载 AED 与 Punc，打两处工程修补（都不改数学，升级 FireRedASR2S 后必须重验
  「修补前后 fp32 逐字相同」）：交叉注意力 K/V 缓存、显存上限 + 每批 empty_cache；
- 把 FireRed 的返回按块号对账成 asrblocks.run 要的形状。
"""

import pathlib
import sys
import wave

import asrblocks

SRC = pathlib.Path(r"E:\asr\src\FireRedASR2S")
AED_DIR = pathlib.Path(r"E:\asr\models\FireRedASR2-AED")
PUNC_DIR = pathlib.Path(r"E:\asr\models\FireRedPunc")
SR = asrblocks.SR


# ---------------------------------------------------------------- 音频与块
def vad_blocks(audio_path):
    """解音频 → VAD → 块。返回 (pcm float32, blocks)。

    VAD 用 faster_whisper 的 silero（不加载 whisper 模型）；合块条件与跨度见 asrblocks.make_blocks。
    """
    from faster_whisper.audio import decode_audio
    from faster_whisper.vad import VadOptions, get_speech_timestamps

    pcm = decode_audio(str(audio_path), sampling_rate=SR)
    opts = VadOptions(max_speech_duration_s=asrblocks.MAX_CHUNK_SPEECH_S,
                      min_silence_duration_ms=asrblocks.VAD_MIN_SILENCE_MS)
    speech = [[t["start"] / SR, t["end"] / SR] for t in get_speech_timestamps(pcm, opts)]
    return pcm, asrblocks.make_blocks(speech)


def write_block_wavs(pcm, blocks, out_dir):
    """每块的 `[start, end)` 切成一个 16 kHz 单声道 int16 wav。返回 {k: 路径}。

    转 int16 与切片的写法照抄实验（clip 后乘 32767 截断；样点下标 int(秒 × 16000)）——
    换个写法差一个样点，解码就未必逐字相同。
    """
    import numpy as np

    out_dir = pathlib.Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    pcm16 = (np.clip(pcm, -1, 1) * 32767).astype("<i2")
    paths = {}
    for b in blocks:
        p = out_dir / ("k%04d.wav" % b["k"])
        with wave.open(str(p), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(SR)
            w.writeframes(pcm16[int(b["start"] * SR):int(b["end"] * SR)].tobytes())
        paths[b["k"]] = str(p)
    return paths


# ---------------------------------------------------------------- 引擎
class Engine:
    def __init__(self):
        if str(SRC / "fireredasr2s") not in sys.path:
            sys.path.insert(0, str(SRC / "fireredasr2s"))
        import torch
        import torchaudio.functional as taf
        from fireredasr2.asr import FireRedAsr2, FireRedAsr2Config
        from fireredasr2.models.module import transformer_decoder as td

        self.torch = torch
        torch.cuda.set_per_process_memory_fraction(asrblocks.MEM_FRACTION)
        self.align = {"ok": 0, "err": 0}
        self._patch_forced_align(taf)

        cfg = FireRedAsr2Config(use_gpu=True, use_half=False, **asrblocks.DECODE)
        self.model = FireRedAsr2.from_pretrained("aed", str(AED_DIR), cfg)
        self._patch_cross_kv(td)
        torch.cuda.reset_peak_memory_stats()
        self.punc_model = None
        self.versions = "torch %s cuda %s" % (torch.__version__, torch.version.cuda)

    def _patch_forced_align(self, taf):
        """CTC 强制对齐的 logits 转 float32 再对齐（fp32 下是空操作，留着防半精度误开），并计数。"""
        orig = taf.forced_align
        align = self.align

        def forced_align(log_probs, *args, **kw):
            try:
                r = orig(log_probs.float(), *args, **kw)
            except Exception:
                align["err"] += 1
                raise
            align["ok"] += 1
            return r

        taf.forced_align = forced_align

    def _patch_cross_kv(self, td):
        """交叉注意力对编码器输出的 K/V 投影，整个束搜索只算一次。

        上游每一步都重算一遍（束搜索 ys 每步 torch.cat，显存碎片越堆越多）；数学不变。
        套在 DecoderMultiHeadAttention.forward 外面，只对标了 `_is_cross` 的层生效。
        """
        orig = td.DecoderMultiHeadAttention.forward

        def forward(self, q, k, v, mask=None):
            if not getattr(self, "_is_cross", False):
                return orig(self, q, k, v, mask)
            bs = q.size(0)
            c = getattr(self, "_xkv", None)
            if c is not None and c[0] is k:     # 与上一步是同一个编码器输出张量
                kp, vp = c[1], c[2]
            else:
                kp = self.w_ks(k).view(bs, -1, self.n_head, self.d_k).transpose(1, 2)
                vp = self.w_vs(v).view(bs, -1, self.n_head, self.d_k).transpose(1, 2)
                self._xkv = (k, kp, vp)          # 拿着 k，缓存期间它的存储不会被复用
            qp = self.w_qs(q).view(bs, -1, self.n_head, self.d_k).transpose(1, 2)
            if mask is not None:
                mask = mask.unsqueeze(1)
            o = self.attention(qp, kp, vp, mask=mask)
            o = o.transpose(1, 2).contiguous().view(bs, -1, self.d_model)
            return self.dropout(self.fc(o))

        td.DecoderMultiHeadAttention.forward = forward
        self.cross = [layer.cross_attn for layer in self.model.model.decoder.layer_stack]
        for a in self.cross:
            a._is_cross = True

    def decoder(self, wavs):
        """asrblocks.run 的 decode 回调。wavs = write_block_wavs 的 {k: 路径}。"""
        def decode(group):
            ids = ["k%03d" % b["k"] for b in group]   # 块号作 uttid，与实验同名
            by_id = {u: b["k"] for u, b in zip(ids, group)}
            try:
                res = self.model.transcribe(ids, [wavs[b["k"]] for b in group])
            finally:
                for a in self.cross:
                    a._xkv = None
                self.torch.cuda.empty_cache()
            out = {}
            for r in res or []:
                k = by_id.get(r.get("uttid"))
                # 没有 confidence 的是上游在特征那一步出错时填的空壳（text 为空），不是真解出空
                if k is None or "confidence" not in r:
                    continue
                out[k] = {"text": r.get("text") or "",
                          "tokens": [[t, s, e] for t, s, e in (r.get("timestamp") or [])]}
            return out

        return decode

    def memory(self):
        gb = 1e9
        return {"peak_gpu_gb": round(self.torch.cuda.max_memory_allocated() / gb, 2),
                "reserved_gpu_gb": round(self.torch.cuda.max_memory_reserved() / gb, 2),
                "align_errors": self.align["err"]}

    def punc(self, texts):
        """asrblocks.punc_pass 的 punc 回调。第一次调用时卸掉 AED、加载 FireRedPunc。"""
        if self.punc_model is None:
            from fireredpunc.punc import FireRedPunc, FireRedPuncConfig

            self.model = None
            self.torch.cuda.empty_cache()
            self.punc_model = FireRedPunc.from_pretrained(str(PUNC_DIR), FireRedPuncConfig(use_gpu=True))
        return [r["punc_text"] for r in self.punc_model.process(list(texts))]
