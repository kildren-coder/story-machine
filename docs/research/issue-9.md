# faster-whisper × RTX 5070 可行性调查

> AFK 调研票 [#9](https://github.com/kildren-coder/story-machine/issues/9)。本文只回答票面 Question,不做决策,给「ASR 方案确认」票供弹药。
> 所有来源访问日期均为 **2026-07-22**。文中区分「来源直接写明」与「据此换算/推断」。

## 问题

RTX 5070 是 Blackwell 架构、12GB 显存(计算能力 `sm_120` / CC 12.0)。调查:

1. faster-whisper(底层 CTranslate2)当前对 CUDA 12.8+/Blackwell 的支持状态,推荐的版本组合(CUDA / cuDNN / CTranslate2 / faster-whisper)。
2. `large-v3` 在 12GB 显存下的可行配置(`compute_type`、batch 等)与预估速度(3 小时音频约需多久)。
3. 已知的坑与报错模式。
4. 若此路不通:whisper.cpp 或其他备选的评估。

本项目背景:转写是流水线**阶段 0**,在房间 PC(RTX 5070,Windows + OpenSSH)上跑,笔记本经 Tailscale+SSH 远程触发;要求**带时间戳**、**只听写不脑补**;转写完的整篇逐字稿再在笔记本上分块。见 `CONTEXT.md`、`audio-obsidian-pipeline-spec.md` 阶段 0。

---

## 结论(TL;DR)

**faster-whisper 这条路现在(2026-07)是通的,是本项目 ASR 的推荐方案,无需改架构。** 关键点:

- **必须用 CTranslate2 ≥ 4.7.0**(当前最新 4.8.1)。这是能否在 Blackwell 上用 INT8 的分水岭:4.7.0 才修好了 sm_120 上 INT8 的 `CUBLAS_STATUS_NOT_SUPPORTED` 崩溃。4.6.2/4.6.3 会**强制禁用 INT8**,更早版本直接崩。
- **推荐版本组合**:CUDA 运行库(cuBLAS)**12.8+** + cuDNN 9(CT2≥4.6.3 起 cuDNN 变为**可选**)+ **CTranslate2 4.8.1** + **faster-whisper 1.2.1**。faster-whisper 只依赖 `ctranslate2>=4.0,<5`,`pip install -U` 会自动装到 4.8.x,**纯 faster-whisper 不需要 PyTorch**。
- **12GB 显存对 large-v3 绰绰有余**:`float16` 权重+激活约 4.5–5GB,`int8` 约 3GB,开批处理(`batch_size=8`)约 4.5–6GB,均远低于 12GB。
- **速度**:据 RTX 3070 Ti 官方基准换算(见论证),3 小时音频顺序解码约 **~15 分钟**、批处理约 **~4 分钟**;RTX 5070 应至少与之相当或更快。**但**有真实用户报告 Blackwell(5070 Ti)在此负载上并不比上代快、甚至略慢(早期驱动/cuBLAS 调优不成熟),**别指望相对 40 系有大提速**。
- **保守起步建议**:若嫌 INT8 兼容性折腾,`compute_type="float16"` 在 Blackwell 上从一开始就稳(FP16 从未受此 bug 影响),精度更高,12GB 也放得下。追求更省显存/更快再上 `int8_float16`(需 CT2≥4.7.0)。
- **备选**:whisper.cpp 可用但 Windows 官方预编译包**不含 sm_120**,需自行用 CUDA 12.8+ 源码编译(`-DCMAKE_CUDA_ARCHITECTURES=120`),或用 Vulkan 后端绕开 CUDA;它不受 CT2 的 INT8 bug 影响,可作为逃生口。openai-whisper / WhisperX 走 PyTorch cu128 也能在 Blackwell 跑,但更慢/更重。

一句话:**装最新 faster-whisper + CTranslate2 4.8.x + CUDA 12.8 cuBLAS,large-v3 先用 float16 跑通,再按需切 int8_float16。**

---

## 论证

### 1. Blackwell 支持的时间线(全部来自 CTranslate2 官方 release notes 与 PR)

RTX 50 系(含 5070)是 `sm_120`,cuBLAS 里报告为 `CC=12.0`。核心事实:cuBLAS 在 sm_120 上**丢掉了部分未对齐的 INT8/IMMA kernel**,导致 Whisper 词表维度(多语模型 vocab=51865,v3=51866,均**不被 4 整除**)在 GEMM 调用时返回 `CUBLAS_STATUS_NOT_SUPPORTED`。

| CTranslate2 版本 | 发布日期 | 对 Blackwell 的意义 |
|---|---|---|
| ≤ 4.6.1 | — | INT8 在 sm_120 直接崩(`CUBLAS_STATUS_NOT_SUPPORTED`) |
| **4.6.2** | 2025-12-05 | 止血:**禁用** sm_120 上的 INT8(日志出现 `Allow INT8: false`);FP16 可用 |
| **4.6.3** | 2026-01-06 | 官方加 **CUDA 12.8 支持**;conv1d 纯 CUDA 实现使 **cuDNN 变为可选依赖** |
| **4.7.0** | 2026-02-03 | **修复并重新启用** sm_120 的 INT8(把 vocab 补齐到 16 的倍数)|
| 4.8.1(最新) | 2026-07-03 | 常规修复,含 Whisper `align()` 空窗除零崩溃修复 |

事实来源:
- CT2 v4.6.2 release notes:"Disable INT8 for sm120 - Blackwell GPUs (#1937)" — <https://github.com/OpenNMT/CTranslate2/releases/tag/v4.6.2>
- CT2 v4.6.3 release notes:"Support for CUDA 12.8 (#1937, #1940)"、"Conv1d pure CUDA implementation (#1949), makes cuDNN an optional dependency" — <https://github.com/OpenNMT/CTranslate2/releases/tag/v4.6.3>
- CT2 v4.7.0 release notes:"Enable multiple of 16 padding for INT8 Tensor Cores (#1982)" — <https://github.com/OpenNMT/CTranslate2/releases/tag/v4.7.0>
- CT2 v4.8.1 release notes — <https://github.com/OpenNMT/CTranslate2/releases/tag/v4.8.1>
- 根因分析(PR #1937 作者调试):"CUBLAS_STATUS_NOT_SUPPORTED only when n[vocab] is not multiple of 4 … NVIDIA dropped some kernels for sm120";并指出 **`word_timestamps=True` 是稳定复现路径** — <https://github.com/OpenNMT/CTranslate2/pull/1937>
- 修复 PR #1982:"Enable multiple of 16 padding … Re-enable INT8 for sm120 … the padding should fix CUBLAS_STATUS_NOT_SUPPORTED"(合并 2026-01-21)— <https://github.com/OpenNMT/CTranslate2/pull/1982>
- cuDNN 变可选的依据 PR #1949:"Makes CUDNN OFF by default … Conv1D is only used by Whisper and represents < 5% of total compute time"(纯 CUDA conv1d 比 cuDNN 慢约 2 倍,但占比 <5%,整体影响可忽略)— <https://github.com/OpenNMT/CTranslate2/pull/1949>

**真实 Blackwell 硬件确认(一手,关键证据)**:CT2 issue #1981,用户 Grohnheit 在**真实 RTX 5060 Ti(CC=12.0,与 5070 同为 sm_120)** 上:4.6.2/4.6.3 日志显示 `Allow INT8: false`;装上 #1982 的补丁 wheel 后,用 `word_timestamps=True` + 多语模型 + 真实音频测试,INT8 正常工作,**显存从 2200MB 降到 1300MB**。— <https://github.com/OpenNMT/CTranslate2/issues/1981>
> 置信度说明:该确认用的是 #1982 的 CI 预编译 wheel(代码即 4.7.0 内容),测的是 5060 Ti 而非 5070 本体,但两者同 `sm_120` 架构,结论可迁移。核心维护者当时**手头没有 Blackwell 卡**(见 #1865 讨论),因此该修复的硬件验证主要来自此社区用户,而非官方 CI。

### 2. 版本组合与安装(推荐口径)

| 组件 | 推荐版本 | 说明 |
|---|---|---|
| faster-whisper | **1.2.1**(最新) | 依赖声明 `ctranslate2>=4.0,<5`,不会卡住新 CT2 |
| CTranslate2 | **4.8.1**(≥4.7.0 是硬底线) | Blackwell INT8 必须 ≥4.7.0 |
| CUDA cuBLAS 运行库 | **12.8+** | Blackwell 的 IMMA kernel 在 12.8 才齐;cuBLAS 版本过旧(如 12.4)正是 bug 温床 |
| cuDNN | 9.x(**可选**,CT2≥4.6.3) | 装了转写略快(conv1d);不装靠纯 CUDA 回退,差异 <5% |
| PyTorch | **不需要** | 纯 faster-whisper 用 CTranslate2 独立运行;VAD 走 onnxruntime(CPU),不依赖 torch |

事实来源:
- faster-whisper 1.2.1 依赖 `ctranslate2>=4.0,<5`(`requirements.cuda.txt`);最新版本 1.2.1(2025-10-31)— <https://github.com/SYSTRAN/faster-whisper/releases>
- faster-whisper README「GPU」节:"GPU execution requires cuBLAS for CUDA 12 and cuDNN 9 for CUDA 12";"latest ctranslate2 only support CUDA 12 and cuDNN 9"(此 README 文字略滞后于 4.6.3 的 cuDNN 可选化,以 release notes 为准)— <https://github.com/SYSTRAN/faster-whisper>
- 依赖清单含 `onnxruntime>=1.14`、`av>=11`,**无 torch** — 同上 `requirements.txt`

> **据此推断**:Windows 上最省事的落地路径是 ① 装 CUDA Toolkit 12.8+(带 cuBLAS);② `pip install -U faster-whisper`(自动带最新 CT2 4.8.x);③ 首跑用 `float16` 验证环境,再切 `int8_float16`。cuDNN 可后置。**若走 pip 装 `nvidia-cublas-cu12`/`nvidia-cudnn-cu12` 的方式,务必取 CUDA 12.8+ 对应版本**(旧版 cuBLAS 缺 sm_120 kernel)。

### 3. large-v3 在 12GB 下的配置与速度

**显存**:large-v3 与 large-v2 同规格。官方基准(RTX 3070 Ti 8GB,large-v2)显存占用:fp16 beam5 = 4525MB;fp16 `batch_size=8` = 6090MB;int8 beam5 = 2926MB;int8 `batch_size=8` = 4500MB。→ **12GB 全部放得下,余量充足**。来源:<https://github.com/SYSTRAN/faster-whisper#benchmark>

**速度(一手基准 + 换算)**:官方基准是 **13 分钟音频(=780 秒)**,RTX 3070 Ti 8GB,CUDA 12.4,large-v2,beam_size=5:

| 配置 | 用时 | 显存 | 实时倍率(换算) |
|---|---|---|---|
| fp16,顺序(beam5) | 1m03s | 4525MB | ~12.4× |
| fp16,`batch_size=8` | 17s | 6090MB | ~46× |
| int8,顺序(beam5) | 59s | 2926MB | ~13.2× |
| int8,`batch_size=8` | 16s | 4500MB | ~49× |

来源(用时/显存为一手):<https://github.com/SYSTRAN/faster-whisper#benchmark>。**实时倍率一列为据 780s 换算的推断。**

> **据此换算(以 3070 Ti 为下限代理)** 3 小时(10800s)音频:
> - fp16 顺序:10800 / 12.4 ≈ **~14.5 分钟**
> - fp16 批处理(`batch_size=8`):10800 / 46 ≈ **~4 分钟**
> - int8 批处理:10800 / 49 ≈ **~3.7 分钟**
>
> RTX 5070 算力高于 3070 Ti,**应至少不慢于**上表。批处理走 faster-whisper 的 `BatchedInferencePipeline`(1.1+ 内置,`batch_size=8~16`)。

**Blackwell 实测的告诫(一手,重要)**:faster-whisper issue #1287,真实 **RTX 5070 Ti** 用户报告在 whisper 负载上比 **4070 Ti Super 慢约 10%**;多位用户复现 50 系在此任务上并不占优,疑因早期(2025 年上半年)cuBLAS/cuDNN 对 Blackwell 调优不成熟。建议**调大 `batch_size`**(50 系最优 batch 可能高于 40 系)。— <https://github.com/SYSTRAN/faster-whisper/issues/1287>
> 置信度:该帖为 2025-04(卡刚上市)的社区实测,截至本文未见更新的 5070 系 large-v3 多小时基准。**结论保守取「与上代持平」而非提速**;实际 3 小时用时仍在「几分钟到十几分钟」量级,对本项目(每天 1-2 集、离线批处理)完全够用。

**没有找到可靠的 RTX 5070 专属 large-v3 多小时墙钟基准**——网上 GPU 厂商博客(如 gigagpu)给的 5090/5080 RTF 数字自相矛盾、方法学不明,**不予采信**;此处如实标注该数据缺口。

### 4. 已知的坑与报错模式

| 报错 / 现象 | 触发条件 | 处理 |
|---|---|---|
| `CUBLAS_STATUS_NOT_SUPPORTED`(cublasGemmEx 返回 15) | Blackwell + INT8 + CT2<4.7.0;**`word_timestamps=True` 稳定复现**,大 `beam_size`、批处理也会 | 升级 **CT2≥4.7.0**;或临时用 `compute_type="float16"` 绕开 |
| `no kernel image is available for execution on the device` | **PyTorch** 一侧未编 sm_120(用了 cu121/旧 torch)——出现在 WhisperX/openai-whisper/torch-VAD 路径 | 装 **PyTorch cu128**(≥2.7 起原生 sm_120)。纯 faster-whisper 无此问题 |
| `Allow INT8: false`(日志) | CT2 4.6.2/4.6.3 在 sm_120 上主动禁 INT8 | 升级到 4.7.0+ 即恢复 |
| 词表非 16 倍数导致的 GEMM 失败残留 | 极旧 CT2 | 升级 |
| SubtitleEdit / whisper-standalone-win 打包版仍崩 | 打包的 CT2 二进制未跟进 4.7.0 | 见下,认准内置 CT2 版本或改用 pip 装 |

来源:
- 触发条件与错误签名:CT2 #1865 / PR #1937(见上)。#1865 附有 GEMM 模拟器实测:RTX 5090 上 `n=51865/51866` 触发 `CUBLAS_STATUS_NOT_SUPPORTED` — <https://github.com/OpenNMT/CTranslate2/issues/1865>
- **SubtitleEdit issue #10180**(二手工具链,截至 2026-07-22 仍 **OPEN**):RTX 50 系(含 5070、5090)默认 int8 崩,**官方给出的绕法就是把 Compute Type 手动设为 `float16`**。根因是 SubtitleEdit 打包的 Purfview whisper-standalone-win 二进制当时尚未用 CT2 4.7.0 重编,并非 SE 代码问题 — <https://github.com/SubtitleEdit/subtitleedit/issues/10180>
- **whisperX issue #1211**:sm_120 上多数人先撞的是 PyTorch 的 `no kernel image`;可用组合为 **CUDA 12.8 + PyTorch cu128 + whisperX PR #1182**(把 torch 抬到 2.7.1/cu128)— <https://github.com/m-bain/whisperX/issues/1211>、<https://github.com/m-bain/whisperX/pull/1182>

> **对本项目的直接提醒**:热词库机制里的「纠错遍」需要词级定位、且 spec 要求**带时间戳输出** → 大概率会用到 `word_timestamps=True`,而这正是 INT8 bug 的稳定触发点。因此 **CT2 版本必须 ≥4.7.0**,否则一开 word timestamps 就崩;保守起步直接用 `float16` 最稳。

### 5. 若此路不通:备选评估

| 方案 | Blackwell 可用性 | 适配本项目(3hr、要时间戳、不脑补)| 备注 |
|---|---|---|---|
| **whisper.cpp**(ggml-org)v1.9.1 | 可用,但**需自行源码编译**:CUDA 12.8+ 工具链 + `-DCMAKE_CUDA_ARCHITECTURES=120`。**官方 Windows 预编译包只到 cublas 12.4,不含 sm_120** | 支持时间戳;走自家 ggml CUDA kernel,**不受 CT2 INT8 bug 影响** | 另有 **Vulkan 后端**(`-DGGML_VULKAN=1`)可绕开 CUDA arch 问题,牺牲部分性能。README 里 `-DCMAKE_CUDA_ARCHITECTURES=86` 是过时示例,Blackwell 要填 `120` |
| **WhisperX**(基于 faster-whisper)| 同 CT2 依赖 → **同 INT8 caveat**(需 CT2≥4.7.0,默认 float16 本就避坑);另需 torch cu128 | 词级对齐/说话人分离更强,但**依赖更重**;默认走 VAD | 若只要转写+时间戳,直接用 faster-whisper 更轻 |
| **openai-whisper**(PyTorch 参考实现)| 靠 **PyTorch cu128(≥2.7 原生 sm_120)** 可跑 | 段级时间戳,`word_timestamps=True` 出词级 | 比 faster-whisper **慢 2–4 倍、显存更高**;无内置 VAD,静音/音乐处更易幻觉 |
| **whisper-standalone-win**(Purfview,Windows 友好)| 新版 Pro 已把 torch 抬到 2.8+cu128(修 VAD),但**内置 CT2 是否 ≥4.7.0 需逐个下载核对** | 开箱即用的 Windows CLI,契合「PC 上一句命令转写」 | 未跟进 CT2 4.7.0 前,`--compute_type float16` 绕开 |

来源:
- whisper.cpp 仓库/最新版 v1.9.1(2026-06-19),Windows 资产仅 `whisper-cublas-11.8.0` 与 `whisper-cublas-12.4.0`(经 GitHub API 核对资产列表)、NVIDIA/Vulkan 构建说明 — <https://github.com/ggml-org/whisper.cpp>、<https://github.com/ggml-org/whisper.cpp/releases/tag/v1.9.1>
- WhisperX 仓库 — <https://github.com/m-bain/whisperX>
- openai-whisper 仓库 — <https://github.com/openai/whisper>
- whisper-standalone-win — <https://github.com/Purfview/whisper-standalone-win>

> **无脑补(不幻觉)提醒**(spec 非协商约束 #1):所有方案跑的都是同一套 Whisper 权重,均有在静音/音乐段幻觉的倾向。faster-whisper / WhisperX **内置 VAD 过滤**可缓解;openai-whisper、transformers 默认不带。就本项目「不脑补 + 人工核对闸门」的定位,**faster-whisper(开 VAD)是更合适的底座**。

---

## 对 story-machine 的影响

落到 `audio-obsidian-pipeline-spec.md` 的具体环节:

1. **阶段 0(转写)确认可行,方案不变**:继续用 `faster-whisper` + `large-v3`,在 RTX 5070 上跑。spec 第 42 行「需要较新的 CUDA(12.8+)及对应构建」**成立且需收紧为可执行版本约束**。
2. **建议在 spec / 环境文档里钉死版本下限**:
   - `CTranslate2 >= 4.7.0`(推荐 4.8.1)——**这是 Blackwell 上 INT8 + word timestamps 不崩的硬门槛**。
   - CUDA cuBLAS 运行库 **12.8+**;cuDNN 9 可选。
   - `pip install -U faster-whisper`(1.2.1),**不装 PyTorch**(纯 CT2 路径,VAD 走 onnxruntime)。
3. **`compute_type` 取值建议**:起步用 `float16`(Blackwell 从不受该 bug 影响、精度高、12GB 放得下);确认 CT2≥4.7.0 后再切 `int8_float16` 省显存/提速。**不要用默认 `auto`**,以免旧栈下自动选 int8 触发崩溃。
4. **batch 建议**:用 `BatchedInferencePipeline`,`batch_size` 起步 8、可试到 16(#1287 建议 50 系用更大 batch)。3 小时音频**据 3070 Ti 基准换算约 4 分钟(批处理)/ 15 分钟(顺序)**,对「每天 1-2 集」节奏绰绰有余。
5. **热词库/纠错遍的连带约束**:阶段 0 要「带时间戳」、纠错遍要词级定位 → 会用 `word_timestamps=True`,**正是 INT8 bug 触发点**,进一步佐证第 2 点的版本下限必须遵守。
6. **逃生口写进文档**:若 Windows 上 CT2 栈难搞,备选是「whisper.cpp 源码编译(CUDA 12.8+,arch=120)或 Vulkan 后端」——它不受 CT2 INT8 bug 影响,且同样输出时间戳。

**建议 spec 阶段 0 增补一句版本约束**,例如:
> 环境:CUDA 12.8+ cuBLAS、CTranslate2 ≥ 4.7.0(推荐 4.8.x)、faster-whisper 1.2.x;首跑 `compute_type="float16"` 验证,再切 `int8_float16`;开启 VAD 过滤以抑制幻觉。

---

## 未决问题

(以下为调研中冒出、但**超出本票范围**的相邻问题,列出供开新票,不在本票内研究掉)

1. **中英混杂内容的实际转写质量**:spec 要求「中英混杂保留原文语言、不强制音译」。large-v3 对中英 code-switching 的分段/语言标注表现如何、是否需要 `language` 固定或分段策略,需实测——属「ASR 质量调优」范畴,建议单开票。
2. **热词/`initial_prompt` 对 faster-whisper 的实际增益与上限**(prompt 长度限制、是否用新版 `hotwords` 参数),属阶段 0 参数调优。
3. **RTX 5070 上 large-v3 的可信墙钟基准缺失**:本调研未找到 5070 专属多小时基准,建议方案确认后在真机上实测一次,回填 spec。
4. **Wake-on-LAN + 远程触发脚本**里 PC 睡眠→唤醒→GPU 就绪的时序(冷启动首次加载模型耗时),属阶段 0 桥接工程,与本票 ASR 可行性无关。
5. **transformers Whisper + FlashAttention2 的分块长音频路线**是否值得作为第二备选(边界处理更易错),本票未展开。
