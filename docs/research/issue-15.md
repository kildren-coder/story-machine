# 说话人分离（Speaker Diarization）方案选型：效果与部署成本调查

> AFK 调研票 [#15](https://github.com/kildren-coder/story-machine/issues/15)。本文只回答票面 Question，不做决策，给「ASR 方案确认」（[#11](https://github.com/kildren-coder/story-machine/issues/11)）供弹药。
> 所有来源访问日期均为 **2026-07-22**。文中区分三档可信度：**来源直写**（官方文档/仓库/model card 明写）、**自报**（候选方自己的 README/博客给出、含利益相关，需实测复核）、**据此推断/换算**（我据事实做的估算）。
> 姊妹票 [#9](https://github.com/kildren-coder/story-machine/issues/9)（faster-whisper × RTX 5070）的结论是本文显存预算分析的基线，多处引用。

## 问题

多人对谈类节目（主播+嘉宾）需要区分「谁在说话」：`提取 schema 定稿`（#3）把别名的 `语域` 字段设计成**立场指纹**（「蛤」戏谑-亲近 / 「维尼」敌意-颠覆），而指纹是**谁的**立场取决于是谁在说——同一句出自主播还是嘉宾，指纹相反。当前阶段 0 只输出裸时间戳逐字稿、不分说话人，保真链在源头就断。

**用户决策规则（给定）**：只要效果达标，优先部署**最简单、显存/依赖开销最低**的方案，不追求最优精度。

调查三个候选，回答四问：
1. **效果**：DER 在中英混杂、政经访谈类内容上的表现；对 2 人对谈是否合适（多数候选面向多人会议，2 人可能更简单）。
2. **部署成本**：与 faster-whisper（阶段 0，RTX 5070 12GB）集成难度；额外显存是否挤压 whisper large-v3；额外依赖（如 pyannote 的 HuggingFace token）。
3. **与 #9 显存预算是否冲突**。
4. **产出格式**：分离结果如何附加进现有 `HH:MM:SS` 逐字稿（新增说话人标签字段，具体落位留 #11）。

---

## 结论（TL;DR）

**三个候选（3D-Speaker、pyannote、NeMo/Sortformer）的效果都够本项目用；分离本身不是瓶颈，2 人对谈比它们基准里的多人会议更简单。按用户「效果达标→最省显存/依赖」的规则，排序如下：**

1. **主推：`3D-Speaker` 音频版流水线（默认 CN-EN 版 CAM++）。** 理由：
   - **题材最契合**：默认嵌入模型是 `speech_campplus_sv_zh_en_16k-common_advanced`——**专为中英双语训练**（来源直写，见 §1），正对本项目中英混杂政经内容；其自报的中文会议内测集 DER 明显优于 pyannote（16.8% vs 22.4%、12.0% vs 17.9%，§2）。
   - **显存冲突最小**：模型极小（CAM++ ~7M 参数），**可纯 CPU 跑**，自报 CPU RTF 0.03（§3）→ 3 小时音频约几分钟，**完全不占 5070 显存**，与 #9 的 whisper 预算零争用。
   - **零 HuggingFace 门槛**：核心音频路径全部从 ModelScope 下模型，**不需要 HF token、不需要过 gated 条款**（HF token 仅在可选的重叠检测模块才需要，§3）。
   - **许可宽松**：代码 Apache-2.0；原生输出 RTTM/JSON；可传 `speaker_num=2` 锁死 2 人（§6）。
   - **代价**：Python 依赖树重（`funasr`/`modelscope`/`torch` + `numpy` 被钉在 1.23.5），须装进**独立 venv**，别污染 faster-whisper 环境；与 whisper 的集成要自己把 RTTM 贴到逐字稿上（无 turnkey 组合件）。

2. **同级备选：`pyannote/speaker-diarization-3.1`，钉死在 `pyannote.audio` 3.3.x，经 `WhisperX` 与 faster-whisper 集成。** 当「turnkey 集成」比「省依赖/免 token」更重要时选它：WhisperX 一条命令产出词级+说话人标签的转写（§6），工程量最小。代价有三：① 需 **HF token + 接受 2 个 gated model 条款**（`segmentation-3.0` 与 diarization 管线）；② **必须避开 `pyannote.audio` 4.x / `community-1`**——4.x 有一个**未修复的 ~10–12GB 显存尖峰 bug**（§3、§4），在 12GB 卡上会 OOM，而 WhisperX 新版**默认就是 community-1**，需显式降级/改配置；③ 精度更高的 community-1（CC-BY-4.0）因此 bug 在 12GB 上暂不可用。

3. **不推：NVIDIA `NeMo` / Sortformer。** 精度强（尤其英语电话、流式），但**依赖最重、Linux/WSL 优先、GPU 独占**，直接违背「最简单/最省」的决策规则（§5）。仅当上面两者在真实数据上都不达标时再回看。

**显存冲突结论（回答第 3 问）**：**与 #9 无根本冲突。** 三点支撑：(a) 分离与转写**不必同时驻留显存**——顺序跑（whisper 转完→释放模型→再分离），峰值取 `max` 而非 `sum`；(b) 3D-Speaker 可纯 CPU，直接把分离移出 GPU；(c) 唯一真危险是 `pyannote.audio` 4.x 的 ~12GB 尖峰，避开即可。#9 基线：large-v3 `float16` 约 4.5–5GB、批处理约 6GB、`int8` 约 3GB，12GB 有余量。

**落格式结论（回答第 4 问）**：所有候选的分离产出都是 `(start, end, speaker_id)` 三元组（RTTM 是标准交换格式，3D-Speaker 与 pyannote 都能出 RTTM/JSON）。附加办法：按**时间重叠**把说话人标签贴到每条 whisper 段/词上（谁的说话区间覆盖该段中点/重叠最多就归谁）——这正是 WhisperX `assign_word_speakers` 干的事。**一个必须点名的断点**：分离输出的是**匿名** `SPEAKER_00 / SPEAKER_01`，它只知道「A 和 B 是不同的人」，**不知道 A 就是主播**。把匿名标签映射到「主播/嘉宾」需要一步分离本身不提供的操作（每集一次人工点名，或对主播做一次声纹注册）——**这一步直接决定 §问题 里的立场指纹归属**，见 §6 与「对 story-machine 的影响」。

---

## 论证

### 1. 三个候选与工作原理

| 候选 | 组成（默认管线） | 面向场景 | 关键特征 |
|---|---|---|---|
| **3D-Speaker**（阿里达摩院/ModelScope）| FSMN VAD → **CAM++（中英双语）嵌入** → 谱聚类（spectral）；可选 `pyannote/segmentation-3.0` 做重叠检测 | 通用 + 中文强 | 模型小、可 CPU；ModelScope 下载 |
| **pyannote-audio**（`speaker-diarization-3.1` / `community-1`）| `segmentation-3.0` 分段 → `wespeaker-voxceleb-resnet34-LM` 嵌入 → 凝聚聚类（AgglomerativeClustering）| 通用/会议 | 事实标准库；WhisperX 内置 |
| **NVIDIA NeMo / Sortformer** | 端到端 Transformer（NEST/Fast-Conformer encoder），无独立聚类步 | 2–4 人、流式/会议 | SOTA 级，但框架重 |

事实来源：
- 3D-Speaker 默认模型（**来源直写**，读 `speakerlab/bin/infer_diarization.py` 源码）：VAD=`iic/speech_fsmn_vad_zh-cn-16k-common-pytorch`；嵌入=`iic/speech_campplus_sv_zh_en_16k-common_advanced`（文件名 `campplus_cn_en_common.pt`，即中英 `zh_en` 版）；聚类=`spectral`，`min_num_spks=1, max_num_spks=15`；`--include_overlap` 时才加载 `pyannote/segmentation-3.0` 且**此时才需 `--hf_access_token`** — <https://github.com/modelscope/3D-Speaker/blob/main/speakerlab/bin/infer_diarization.py>
- 3D-Speaker 管线三模块（VAD/嵌入/谱聚类）与工具箱论文 — <https://github.com/modelscope/3D-Speaker/blob/main/egs/3dspeaker/speaker-diarization/README.md>、<https://arxiv.org/abs/2403.19971>
- pyannote 3.1 用 `segmentation-3.0` + `wespeaker-voxceleb-resnet34-LM` + 凝聚聚类（**来源直写**，model card 与 issue #1963）— <https://huggingface.co/pyannote/speaker-diarization-3.1>
- Sortformer 是端到端 Transformer 编码器、2–4 人（**来源直写**）— <https://docs.nvidia.com/nemo-framework/user-guide/latest/nemotoolkit/asr/speaker_diarization/models.html>、<https://catalog.ngc.nvidia.com/orgs/nvidia/riva/models/sortformer_diarizer/v1>

> CAM++ 的中英双语出身是本项目最强的区分点：多数会议向 diarization 用英语/多语通用嵌入，而这里默认就是「中英 common」，与题材（中英混杂政经）天然对齐。

### 2. 效果（DER）对比与 2 人 / 中英场景分析

DER = Diarization Error Rate（越低越好，含漏检+误检+说话人混淆）。下表口径尽量对齐「full DER，无 collar、计入重叠」，但**不同来源的评测集/口径不完全可比**，仅作量级参照。

| 测试集（题材）| pyannote 3.1 | pyannote community-1 | 3D-Speaker（无/有重叠检测）| 来源档 |
|---|---|---|---|---|
| AISHELL-4（中文会议）| 12.2% | 11.7% | 23.04% / **10.30%** | 直写/直写/自报 |
| AliMeeting（中文会议）| 24.4% | 20.3% | 32.79% / 19.73% | 直写/直写/自报 |
| AMI-SDM（英文会议远场）| 22.4% | 19.9% | 35.76% / 21.76% | 直写/直写/自报 |
| VoxConverse（英文，名人/媒体）| **11.3%** | 11.2% | 12.09% / 11.75% | 直写/直写/自报 |
| DIHARD3（多域）| 21.7% | 20.2% | — | 直写/直写 |
| RAMC（中文对话）| — | 20.8% | — | 直写 |
| **Meeting-CN_ZH-1（中文内测）** | 22.37% | — | **16.80%** / 18.91% | 自报 |
| **Meeting-CN_ZH-2（中文内测）** | 17.86% | — | **11.98%** / 12.78% | 自报 |

来源：
- pyannote 3.1 DER（**来源直写**，model card benchmark 表）— <https://huggingface.co/pyannote/speaker-diarization-3.1>
- community-1 DER（**来源直写**，model card 三列对比表 Legacy/Community-1/Precision-2）— <https://huggingface.co/pyannote/speaker-diarization-community-1>
- 3D-Speaker DER 与「vs pyannote」对比（**自报**，其 diarization recipe README 自建对比表；含利益相关，pyannote 列数字与官方 model card 基本一致故可交叉印证，但 CN_ZH 内测集无法独立复核）— <https://github.com/modelscope/3D-Speaker/blob/main/egs/3dspeaker/speaker-diarization/README.md>

**读表要点：**
- **公共学术集上三者一个量级**：中文会议 AISHELL-4/AliMeeting 与英文 VoxConverse，pyannote 与 3D-Speaker 互有胜负（VoxConverse pyannote 略优；AISHELL-4 3D-Speaker 开重叠检测后 10.3% 反超）。community-1 是全面小幅升级。
- **中文对话内测集 3D-Speaker 明显领先**（Meeting-CN_ZH-1/2：16.8% vs 22.4%、12.0% vs 17.9%）。这是**自报数据**，但方向与「CAM++ 中英双语嵌入」的设计一致，可信但**须在真实一集上复核**。
- **重叠检测（overlap detection）是双刃**：AISHELL-4 从 23%→10.3%（多人抢话多，值得开），但两个 CN_ZH 内测集**关掉反而更好**（16.80 vs 18.91、11.98 vs 12.78）。**对 2 人政经对谈（抢话少、以轮流长发言为主），倾向不开重叠检测**——顺带**也就不需要 pyannote/segmentation-3.0，连 HF token 都省了**。

**2 人对谈是否被过拟合调优？** 没有候选专门「为 2 人调优」；上面的 DER 都来自更难的多人会议。但两点让 2 人场景更稳：
1. **2 人本就更简单**（说话人越少、聚类越不易混淆），实际 DER 应**优于**上表会议数字。
2. **可锁死说话人数**：3D-Speaker 传 `speaker_num=2`（`infer_diarization.py` 的 `--speaker_num`）；pyannote/WhisperX 传 `--min_speakers 2 --max_speakers 2`。给定 oracle K=2 会进一步压低错误。

> **数据缺口（如实标注）**：**没有**「中英混杂政经访谈」题材的公开 diarization 基准。最接近的代理是上面的中文会议/对话集（AISHELL-4、AliMeeting、RAMC、CN_ZH 内测），量级 10–24% DER。真实题材 DER **需在一集真样本上实测**，不能从上表直接外推。

### 3. 部署成本：显存、依赖、HF token、许可

| 维度 | 3D-Speaker（音频版）| pyannote 3.1 @ audio 3.3.x | pyannote community-1 @ audio 4.x | NeMo/Sortformer |
|---|---|---|---|---|
| **GPU 显存** | 极小，**可 CPU**（据推断 <1GB GPU）| **~1.6GB**（72min 实测）| **~10–12GB 尖峰（bug）** | 中等（GPU 独占）|
| **CPU 可跑** | ✅ 自报 RTF 0.03 | 慢（RTF ~0.19）| 慢 | ✗（GPU 优先）|
| **HF token / gated** | **不需要**（核心路径；仅可选重叠检测需要）| **需要**（token + 接受 2 条款）| **需要** | 不需要（NGC/HF 公开）|
| **依赖重量** | 重（`funasr`/`modelscope`/`torch`/`onnxruntime-gpu`，`numpy==1.23.5` 硬钉）| 中（`pyannote.audio`+`torch`）| 中 | **最重**（NeMo 全家桶）|
| **Windows 原生** | 可（Python 包）| 可 | 可 | **差**（Linux/WSL 优先）|
| **许可** | 代码 Apache-2.0 | model card 标 **MIT** | model card 标 **CC-BY-4.0** | NeMo Apache-2.0 / 模型各异 |
| **与 faster-whisper 集成** | 自己贴 RTTM（无 turnkey）| **WhisperX turnkey** | WhisperX turnkey（但踩显存 bug）| 无 turnkey，最费事 |

事实来源：
- **pyannote `audio` 4.x 显存尖峰 bug（关键，一手 GitHub issue #1963，截至 2026-07-22 仍 OPEN）**：`pyannote.audio 3.3.2 + speaker-diarization-3.1` 峰值 **1.59GB**；`pyannote.audio 4.0.3` 无论配 `community-1` 还是 `speaker-diarization-3.1` 都飙到 **9.54GB**——即**尖峰由库版本 4.x 触发、与模型无关**。报告者的逐步实测把尖峰定位在 **`discrete_diarization`（聚类后的重构）步**（segmentation/embedding 两步各仅 ~0.4/0.05GB，与旧版持平），一位复现者在 `diarizer()` 内实测 **max_allocated 10.53GB / max_reserved 12.09GB**——`reserved` 已越过 12GB 线。报告者原话：4.0.3「making it impractical for GPUs with less than 12GB or for concurrent processing」— <https://github.com/pyannote/pyannote-audio/issues/1963>
- pyannote 3.1 在旧库上也比 2.x 吃内存（issue #1580，已关闭；用户 12GB 卡遇到 3.1 峰值到 14GB 触发换页）— <https://github.com/pyannote/pyannote-audio/issues/1580>
- 3D-Speaker CPU RTF 0.03、依赖清单（**自报 + 来源直写**）— recipe README（RTF 表）与 `egs/.../speaker-diarization/requirements.txt`（`funasr`/`modelscope`/`transformers`/`hdbscan`/`umap-learn`/`onnxruntime-gpu`/`pyannote.audio`/`numpy==1.23.5` 等）— <https://github.com/modelscope/3D-Speaker/tree/main/egs/3dspeaker/speaker-diarization>
- pyannote 许可与 gated（**来源直写** model card）：3.1 = `mit`、community-1 = `cc-by-4.0`，两者均需「accept the conditions」+ 在 `hf.co/settings/tokens` 建 token — <https://huggingface.co/pyannote/speaker-diarization-3.1>、<https://huggingface.co/pyannote/speaker-diarization-community-1>
- WhisperX 新版**默认用 community-1**、需 `--hf_token` 并接受其条款（**来源直写**）— <https://github.com/m-bain/whisperX>
- NeMo Linux/macOS 优先、Windows 走 WSL2、原生 Windows「Untested, Should Work」（**来源直写**）— <https://github.com/NVIDIA/NeMo-Agent-Toolkit/blob/develop/docs/source/get-started/installation.md>

> **据此推断**：3D-Speaker 的 GPU 显存我未见一手数字，但 CAM++ 是 ~7M 参数级小模型 + FSMN VAD（更小），推断 GPU 占用 <1GB；而它**能纯 CPU 跑**这一点让 GPU 显存问题直接消失。CPU RTF 0.03 是自报、偏乐观（3 小时→约 5–6 分钟）；即便实测落到 pyannote 级 RTF 0.2（3 小时→约 36 分钟），对「每天 1–2 集离线批处理」仍完全够用。

### 4. 与 #9 显存预算的冲突评估

**#9 基线（一手换算）**：RTX 5070 12GB 上 large-v3 —`float16` 约 4.5–5GB、`float16` 批处理（`batch_size=8`）约 6GB、`int8` 约 3GB，均远低于 12GB（<https://github.com/kildren-coder/story-machine/issues/9> → 依据 <https://github.com/SYSTRAN/faster-whisper#benchmark>）。→ whisper 之外**约有 6–7GB 余量**。

分三种落地方式看冲突：

| 落地方式 | 峰值显存 | 与 #9 冲突？ |
|---|---|---|
| **3D-Speaker 跑 CPU**（或跑笔记本）| whisper 峰值不变（~6GB）| **无**。分离不碰 GPU |
| **分离与 whisper 顺序跑 GPU**（转完释放 whisper 再分离）| `max(6GB, 分离峰值)` | 3D-Speaker(<1GB)/pyannote-3.1(~1.6GB)→**无**；pyannote-4.x(~12GB)→**危险** |
| **两者同时驻留 GPU** | `6GB + 分离峰值` | 3D-Speaker/pyannote-3.1（~7.6GB）→仍**放得下**；pyannote-4.x→**必 OOM** |

**结论**：**没有根本冲突，前提是避开一个雷**——`pyannote.audio` 4.x（即 community-1 的运行环境）的 ~10–12GB 尖峰 bug。它单独在 12GB 卡上都吃紧，叠加 whisper 必 OOM。规避手段任选：
- **走 3D-Speaker**：模型小 + 可 CPU，最省心；甚至可把分离整段移到笔记本 CPU，和阶段 0（PC/GPU）解耦。
- **走 pyannote 但钉死 3.3.x + `speaker-diarization-3.1`**：峰值 ~1.6GB（72min；3 小时会更高但仍是个位数 GB），顺序跑稳。**放弃 community-1 直到该 bug 修复。**
- 无论哪条，**推荐顺序执行**（whisper 转写→释放显存→再分离），让峰值取 `max` 不取 `sum`——WhisperX 本就是分阶段跑，天然如此。

> **提醒**：#9 已定 whisper 走**纯 faster-whisper、不装 PyTorch**（VAD 用 onnxruntime）。而 3D-Speaker 与 pyannote **都要 `torch`**。因此分离环境应是**独立 venv**，不要塞进 faster-whisper 那个「无 torch」的干净环境，以免 `numpy`/`torch`/CUDA 版本互撞（3D-Speaker 还硬钉 `numpy==1.23.5`）。

### 5. NeMo / Sortformer 为何不入选

- **精度确实强**：Sortformer 端到端，官方称在真实基准上优于 EEND-GLA / LS-EEND；流式 CallHome-eng0 报 6.0–6.2% DER。但该数字是 **0.25s collar 的英语电话двух-四人**口径，**与 pyannote/3D-Speaker 的 no-collar full DER 不可直接比**，别被「6%」误导。来源 — <https://catalog.ngc.nvidia.com/orgs/nvidia/riva/models/sortformer_diarizer/v1>、<https://docs.nvidia.com/nemo-framework/user-guide/latest/nemotoolkit/asr/speaker_diarization/models.html>
- **部署最重**：需要 NeMo 全家桶（大依赖树、Git-LFS 拉大模型），官方 **Linux/macOS 优先、Windows 建议 WSL2、原生 Windows「未测试」**——而本项目阶段 0 在 **Windows PC** 上（#9、spec §3）。
- **GPU 优先**，不像 3D-Speaker 有轻量 CPU 路。
- **结论**：在「效果都达标→挑最简单/最省」的规则下，Sortformer 的增量精度买不回它的部署重量，**MVP 不选**。仅当 3D-Speaker 与 pyannote 在真实中英政经样本上都不达标（例如 2 人也频繁 >20% DER）时，再回看端到端方案。

### 6. 分离结果如何附加进 `HH:MM:SS` 逐字稿（回答第 4 问）

**分离的原生产出**都是说话人轮次三元组：`(start_sec, end_sec, speaker_id)`。标准交换格式是 **RTTM**（每行 `SPEAKER file 1 <start> <dur> <NA> <NA> SPEAKER_00 <NA> <NA>`）；3D-Speaker `infer_diarization.py` 支持 `--out_type rttm|json`，pyannote 也可导 RTTM。

**贴到逐字稿的算法**（与 WhisperX `assign_word_speakers` 同款，**来源直写**其 README）：对每条 whisper 段（或词），取与之**时间重叠最大**（或覆盖其中点）的说话人轮次，把该 `speaker_id` 写进该段。示意（字段落位留 #11 拍板，这里只给形态）：

```
[00:12:34] SPEAKER_00: 我们看这次美联储的决议……
[00:12:41] SPEAKER_01: 但问题是市场早就 price in 了……
```

或 JSON 每段加一个字段：`{"start":"00:12:34","end":"00:12:40","speaker":"SPEAKER_00","text":"……"}`。

**必须点名的断点——匿名 → 身份映射：**
- 分离只给**匿名** `SPEAKER_00 / SPEAKER_01`，**不知道谁是主播**。而 #问题 要的立场指纹归属，需要「主播 vs 嘉宾」这一层。
- 补这一步的廉价办法（都不属本票裁决，仅列选项）：
  1. **每集一次人工点名**：在阶段 3 人工核对时，扫一眼「SPEAKER_00 = 主播」写进 frontmatter（1 行/集）。天然落在既有的**人工闸门**里，几乎零成本。
  2. **主播声纹注册**：对固定主播做一次声纹 enrollment，用嵌入相似度自动认出主播那一路（3D-Speaker 的 CAM++ 本就是说话人验证模型，天生支持）；嘉宾仍匿名。
- **粒度建议**：段级（segment）说话人标签足够支撑立场指纹归属；词级（WhisperX 能到词级）对本项目**过细**，非必要。

---

## 对 story-machine 的影响

落到 `audio-obsidian-pipeline-spec.md` 的具体环节，给 #11「ASR 方案确认」的弹药：

1. **阶段 0 增设「说话人分离」子步，作为转写的后处理**（不改架构）。产出在裸时间戳逐字稿之上叠加 `speaker` 字段。**推荐 3D-Speaker 音频版（默认 CN-EN CAM++），跑 CPU**——不吃 5070 显存、免 HF token、中文题材最贴。若更看重 turnkey 集成、可接受 HF token，则 `pyannote/speaker-diarization-3.1`（钉 `pyannote.audio` 3.3.x）经 WhisperX 亦达标。**两者都传 K=2 锁死 2 人**。

2. **显存约束写进环境文档**（承接 #9）：分离与 whisper **顺序执行 + 独立 venv**；**禁用 `pyannote.audio` 4.x / `community-1`**（~10–12GB 尖峰 bug，会撞爆 12GB 预算），直到该 bug（issue #1963）修复。3D-Speaker 路线则无此雷。

3. **schema（#3）落位建议留给 #11，但给出形态**：每条逐字稿段新增 `speaker`（值域 `SPEAKER_00/01…`，段级即可）。**并新增「匿名→身份」映射一步**：主播/嘉宾的认定放进**阶段 3 人工核对**（每集 1 行 frontmatter，如 `speaker_map: {SPEAKER_00: 主播, SPEAKER_01: 嘉宾-XXX}`）或用主播声纹注册自动化。**立场指纹（`语域`）必须挂在「身份」而非「匿名标签」上**，否则跨集不可比。

4. **对 `_pairs` 校对配对数据（spec §4 阶段 3 / §5）的连带影响**：说话人标签也是人工在阶段 3 会校正的对象（分离偶尔切错人），因此 `_pairs` 的 pre/post 快照应**包含 speaker 字段**，让它同样进入「模型草稿→人工修正」的微调/回归语料。

5. **2 人 vs 多人**：本项目多为主播+1 嘉宾，个别多嘉宾。默认 `speaker_num` 不写死、给 `max_speakers` 上限（如 4）更稳；确知 2 人的集可传 `speaker_num=2`。

6. **建议在真实一集上实测 DER 再定标**：公开基准无「中英政经访谈」题材，上表 10–24% 是会议代理值。先拿一集跑 3D-Speaker（和/或 pyannote-3.1）掐 DER，回填 spec。

---

## 未决问题

（调研中冒出、**超出本票范围**，列出供开新票，不在本票研究掉）

1. **匿名→身份映射的具体机制定型**：是「阶段 3 人工点名」还是「主播声纹注册自动化」？后者要一套 enrollment 流程与阈值——属阶段 0/3 工程，建议单开票（与本票的「立场指纹归属」强相关）。
2. **重叠语音（overlap）要不要处理**：2 人对谈抢话少，本文倾向**不开**重叠检测（省掉 pyannote/segmentation-3.0 与 HF token）；但若某些集抢话密集，需评估开启的收益/成本——留待真实数据观察。
3. **3D-Speaker 依赖树与 faster-whisper 的实际共存冲突**（`numpy==1.23.5` 硬钉、`onnxruntime-gpu` vs faster-whisper 的 `onnxruntime`、CUDA 版本）：本文建议独立 venv 规避，但**未实机验证**；装环境时需实测。
4. **真实题材 DER 标定**：中英混杂政经访谈无公开基准，需在一集真样本上实测 3D-Speaker / pyannote-3.1 的 DER 与错误模式，回填 spec（与 #9「真机墙钟基准缺失」类似，可合并到一次真机验证里做）。
5. **pyannote `audio` 4.x 显存 bug（issue #1963）的修复进展跟踪**：若上游修好，community-1（CC-BY-4.0、DER 更低）会重新成为 12GB 上的可选项，届时值得复评。
6. **说话人标签对下游提取（阶段 2 Gemini Flash）的利用方式**：把「谁说的」喂进提取提示词能否提升立场指纹判定的准确率——属阶段 2 提示词工程，超出本票。
