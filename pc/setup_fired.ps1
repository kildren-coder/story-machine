# setup_fired.ps1 — 5070 上的转写环境（FireRedASR2-AED，ADR 0006 / SPEC §4 阶段 0）。一次性，可重复跑。
#
#   powershell -ExecutionPolicy Bypass -File E:\asr\setup_fired.ps1
#
# 装三样，已在的跳过：
#   venv    E:\asr\venv-fired          Python 3.12 + torch/torchaudio 2.11.0+cu128，版本钉成 EP02 对照实验那一套
#   源码    E:\asr\src\FireRedASR2S    固定版本的源码快照（不 pip 安装，fired_engine.py 加 sys.path），附 VERSION.txt
#   权重    E:\asr\models\FireRedASR2-AED、E:\asr\models\FireRedPunc
# 末尾自检：加载两个模型，解一段 3 秒静音，打印 torch / CUDA 版本。
#
# 大文件一律在 E 盘。用 uv 建 venv（E:\asr\bin\uv.exe）；Python 也由 uv 装在 E:\asr\uv-python。
# 本文件含中文，必须存 UTF-8 with BOM（PowerShell 5.1）。
param(
    [string]$Uv = 'E:\asr\bin\uv.exe',
    [string]$FromSrc = 'E:\asr\exp\engines\src\FireRedASR2S-main',   # 源码快照的来源（实验那份）
    [string]$FromModels = 'E:\asr\exp\engines\models'                 # 权重的来源（实验那份）
)
# 原生命令（uv）往 stderr 写进度，5.1 经 ssh 跑时会把它当错误；原生命令一律看退出码（Check），cmdlet 各自 -ErrorAction Stop
$ErrorActionPreference = 'Continue'

$Venv = 'E:\asr\venv-fired'
$Py = "$Venv\Scripts\python.exe"
$Src = 'E:\asr\src\FireRedASR2S'
$Models = 'E:\asr\models'
$PyVersion = '3.12.14'
$env:UV_PYTHON_INSTALL_DIR = 'E:\asr\uv-python'
$env:UV_CACHE_DIR = 'E:\asr\uv-cache'
$env:UV_HTTP_TIMEOUT = '600'
$env:TEMP = 'E:\asr\tmp'
$env:TMP = 'E:\asr\tmp'
$env:PYTHONIOENCODING = 'utf-8'
# torch 走南大镜像的 download.pytorch.org/whl/cu128，其余走清华 PyPI 镜像（2026-10 直连 pytorch.org 断过）
$TorchIndex = 'https://mirror.nju.edu.cn/pytorch/whl/cu128'
$PyPI = 'https://pypi.tuna.tsinghua.edu.cn/simple'

# 与 EP02 对照实验的 venv 逐个相同；faster-whisper / av / onnxruntime 与生产 C:\asr\venv 相同（VAD 与解音频同一套）
$Torch = @('torch==2.11.0+cu128', 'torchaudio==2.11.0+cu128')
$Deps = @(
    'transformers==4.51.3', 'tokenizers==0.21.4', 'huggingface-hub==0.36.2', 'safetensors==0.8.0',
    'accelerate==1.15.0', 'peft==0.21.2', 'numpy==1.26.4', 'cn2an==0.5.24', 'kaldiio==2.18.1',
    'kaldi-native-fbank==1.22.3', 'sentencepiece==0.2.2', 'soundfile==0.14.0', 'textgrid==1.6.1',
    'faster-whisper==1.2.1', 'ctranslate2==4.8.1', 'av==18.0.0', 'onnxruntime==1.27.0',
    'opencc-python-reimplemented==0.1.7'
)

function Step($name) { Write-Host "=== $name  $(Get-Date -Format HH:mm:ss)" -ForegroundColor Cyan }
function Check($what) { if ($LASTEXITCODE -ne 0) { throw "$what failed (exit $LASTEXITCODE)" } }

New-Item -ItemType Directory -Force $env:TEMP, $Models, (Split-Path $Src) -ErrorAction Stop | Out-Null
if (-not (Test-Path $Uv)) {
    throw "uv not found at $Uv. Put uv.exe there (https://github.com/astral-sh/uv/releases), then rerun."
}

Step 'python'
& $Uv python install $PyVersion; Check 'uv python install'

Step 'venv'
if (Test-Path $Py) { Write-Host "$Venv exists, keeping it" }
else { & $Uv venv $Venv --python $PyVersion; Check 'uv venv' }

Step 'torch'
& $Uv pip install --python $Py @Torch --index-url $TorchIndex --extra-index-url $PyPI --index-strategy unsafe-best-match
Check 'torch install'

Step 'deps'
& $Uv pip install --python $Py @Deps --index-url $PyPI; Check 'deps install'

Step 'source'
if (Test-Path "$Src\fireredasr2s\fireredasr2\asr.py") { Write-Host "$Src exists, keeping it" }
else {
    if (-not (Test-Path "$FromSrc\fireredasr2s\fireredasr2\asr.py")) {
        throw "no FireRedASR2S source at $FromSrc. Unzip https://codeload.github.com/FireRedTeam/FireRedASR2S/zip/refs/heads/main there (or pass -FromSrc), then rerun."
    }
    Copy-Item -Recurse $FromSrc $Src -ErrorAction Stop
    $zip = Join-Path (Split-Path (Split-Path $FromSrc)) 'fired.zip'
    $zipInfo = if (Test-Path $zip) {
        "zip $zip sha256 $((Get-FileHash $zip).Hash) saved $((Get-Item $zip).LastWriteTime.ToString('yyyy-MM-dd'))"
    } else { 'zip not found next to the source' }
    @(
        'FireRedASR2S source snapshot (main branch), used by C:\asr\fired_engine.py via sys.path; not pip-installed.',
        'origin: https://codeload.github.com/FireRedTeam/FireRedASR2S/zip/refs/heads/main',
        "copied: $(Get-Date -Format yyyy-MM-dd) from $FromSrc",
        $zipInfo,
        'patches: none in the source. fired_engine.py wraps DecoderMultiHeadAttention.forward (cross-attn K/V cache)',
        '         and torchaudio forced_align at runtime. After replacing this snapshot, re-verify fp32 output',
        '         is identical with and without the patches (SPEC section 4, stage 0).'
    ) | Out-File -Encoding ascii "$Src\VERSION.txt"
}

Step 'weights'
foreach ($m in 'FireRedASR2-AED', 'FireRedPunc') {
    if (Test-Path "$Models\$m\model.pth.tar") { Write-Host "$Models\$m exists, keeping it"; continue }
    if (-not (Test-Path "$FromModels\$m\model.pth.tar")) {
        throw "no weights at $FromModels\$m. Download FireRedTeam/$m (HuggingFace or ModelScope) there (or pass -FromModels), then rerun."
    }
    Copy-Item -Recurse "$FromModels\$m" "$Models\$m" -ErrorAction Stop
}

Step 'self-check'
$check = Join-Path $env:TEMP 'fired_selfcheck.py'
@'
import os, sys, wave
sys.path.insert(0, r"E:\asr\src\FireRedASR2S\fireredasr2s")
import torch
print("torch", torch.__version__, "cuda", torch.version.cuda,
      "gpu", torch.cuda.get_device_name(0) if torch.cuda.is_available() else None)
import faster_whisper, opencc
from fireredasr2.asr import FireRedAsr2, FireRedAsr2Config
from fireredpunc.punc import FireRedPunc, FireRedPuncConfig
p = os.path.join(os.environ["TEMP"], "fired_selfcheck.wav")
with wave.open(p, "wb") as w:
    w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000); w.writeframes(b"\0\0" * 48000)
m = FireRedAsr2.from_pretrained("aed", r"E:\asr\models\FireRedASR2-AED",
                                FireRedAsr2Config(use_gpu=True, use_half=False, return_timestamp=True))
print("aed on 3 s of silence:", m.transcribe(["silence"], [p]))
pu = FireRedPunc.from_pretrained(r"E:\asr\models\FireRedPunc", FireRedPuncConfig(use_gpu=True))
print("punc:", pu.process(["self check ok"])[0]["punc_text"])
print("faster_whisper", faster_whisper.__version__)
print("SELFCHECK OK")
'@ | Out-File -Encoding ascii $check
& $Py $check; Check 'self-check'
Remove-Item $check -ErrorAction SilentlyContinue
Write-Host "=== done. venv $Venv, source $Src, weights $Models" -ForegroundColor Green
