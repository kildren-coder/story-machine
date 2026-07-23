# Obsidian 音频转写类插件综述：对转写/CLI 环节的参考价值

> AFK research 记录票 [#18](https://github.com/kildren-coder/story-machine/issues/18)。不阻塞任何现存票；供 #5（CLI 技术栈与命令形状）与 #9（faster-whisper × RTX 5070 可行性）背景参考。
> 所有链接访问日期：**2026-07-22**。GitHub 元数据（stars/license/pushed）经 `gh api` 当日拉取。

## 问题

把「6 个 Obsidian 音频转写类项目已被排除」这一结论正式落档，并轻量核实两点：

1. 随手翻这几个插件的 README/源码，看「whisper 调用方式 / 音频分块 / 错误处理」上有没有值得抄进阶段 0 CLI 包装脚本的**具体做法**——有就摘出来，没有就明写「翻过、不需再回头看」。
2. 确认「AI Audio Transcription and Summary」（Obsidian 市场标 Premium 的那个）的开源边界：免费核心是否真是 MIT，付费部分是否闭源。

## 结论（TL;DR）

- **交付形态层面：6 个项目全部排除，结论站得住，无需再逐个回头深挖。** 它们的存在形态（Obsidian 插件 / SaaS）本身就不是我们要的交付形态（spec 明确 MVP 不做 Obsidian 插件），且大多把「ASR + LLM 后处理/总结」耦合成一步，撞我们「转写与整理严格分离」非协商项。
- **但「大概率没有值得抄的东西」这个先验被推翻了一半**：确有 **5 条具体、可落到阶段 0 脚本的结论**（见「对 story-machine 的影响」）。最有价值的一条是 whisper `initial_prompt` 的 **~224 token 硬窗口**——直接约束我们的热词库注入。其余多为「印证常识」而非「新技术」，但印证本身有价值（少走弯路）。
- **票面对这几个仓库的技术定性不准，需更正**：票面说它们「都是调用 whisper/whisper.cpp + 可选 LLM 后处理的同一种模式」。**实际只有 1 个真正跑本地 whisper.cpp**；其余分别是「自建 HTTP webservice」「云 API（Deepgram/AssemblyAI/Gladia/OpenAI）」「纯录音+转写」。对我们真正有参考价值的恰恰是那个**跑本地 whisper.cpp** 的和那个 **whisper webservice** 的。
- **`cristiangauma/whisperscribe` 现已 404**（`gh api` 打不开，作者公开仓库列表里也没有它），只在搜索缓存里留有「Audio transcription and summarizer for Obsidian」的描述。**票写下之后被删库或转私有**，无法核实源码——如实记录，不臆造。
- **「AI Audio Transcription and Summary」= `HackerHomeLab/AITranscribe`，整仓 MIT，没有闭源付费部分**。「Premium」纯是营销词（README 里指「Premium Visuals」即 UI 波形/闪烁/计时等观感），唯一变现是可选 Ko-fi 打赏。**免费核心 = 全部核心 = MIT；不存在「付费闭源部分」这回事。**

## 论证

### 1. 六个项目逐个定性

| 项目 | 形态 | ASR 后端 | License / ★ / 最近推送 | 排除理由 | 是否有可抄片段 |
|---|---|---|---|---|---|
| **Snipd** | SaaS + 同步插件 | 云端（黑箱） | 闭源 SaaS | 核心动作是 AI 摘要，且**只转写「高亮片段（snip）」不转写整集** | 无（拿不到源码） |
| **djmango/obsidian-transcription** | Obsidian 插件 | 自建 `whisper-asr-webservice`（Docker HTTP） | MIT / 224★ / 2025-09-03 | 插件形态非交付形态 | **有**：webservice 部署形态可参考（见 §3） |
| **akhmialeuski/advanced-audio-recorder** | Obsidian 插件（录音+转写） | 本地 `whisper.cpp`（+ 多家云） | MIT / 7★ / 2026-07-22 | 插件形态非交付形态 | **有**：本地 whisper.cpp 调用 + 16k 单声道预处理 + 存盘顺序（见 §3） |
| **jaliriogbarrios19/Audio_Transcript** | Obsidian 插件 | 云 API（Gladia/Deepgram/AssemblyAI/OpenAI/Groq）+ 可选本地 whisper.cpp | MIT / 0★ / 2026-06-30 | 插件形态；主打云端说话人分离 | **有**：转写前先落盘、provider 兜底链（见 §3） |
| **cristiangauma/whisperscribe** | （原 Obsidian 插件） | 未知 | **404，已删/转私有** | 无法访问 | 未能访问，不评 |
| **mssoftjp/obsidian-ai-transcriber**（"AI Transcriber"） | Obsidian 插件 | **OpenAI 云** GPT-4o/Whisper-1（非本地） | MIT / 4★ / 2026-07-15 | 插件形态；纯云、无本地路径 | **有（含反面教材）**：分块/重试参数 + VAD 丢音警示（见 §3） |

来源（各仓库本体，访问 2026-07-22）：
[Snipd Obsidian 说明](https://www.snipd.com/blog/sync-snips-to-obsidian-plugin) ·
[djmango/obsidian-transcription](https://github.com/djmango/obsidian-transcription) ·
[akhmialeuski/advanced-audio-recorder](https://github.com/akhmialeuski/advanced-audio-recorder) ·
[jaliriogbarrios19/Audio_Transcript](https://github.com/jaliriogbarrios19/Audio_Transcript) ·
[mssoftjp/obsidian-ai-transcriber](https://github.com/mssoftjp/obsidian-ai-transcriber)

**Snipd 细节（来源：Snipd 官方博客，第一手）**：每条 snip 同步「该高亮片段的完整转写 + AI 摘要 + 元数据」，工作流核心是「点耳机 → Snipd 的 AI 生成 snip（转写+摘要）」。**它不转写整集，只转写你标记的高亮片段**，且 AI 摘要是主产物。属 Readwise/Pocket 式高亮同步工具，不是忠实全集 ASR——与我们的需求正交，排除成立。

### 2. 「AI Audio Transcription and Summary」开源边界（票面第 2 问）

- Obsidian 社区插件页 [`ai-audio-transcription-summary`](https://community.obsidian.md/plugins/ai-audio-transcription-summary) → 作者 **HackerHomeLab**，仓库 **[`HackerHomeLab/AITranscribe`](https://github.com/hackerhomelab/AITranscribe)**（3★，最近推送 2026-07-09）。
- **License：整仓 MIT。** `gh api repos/HackerHomeLab/AITranscribe/license` 返回 `spdx_id: MIT`（第一手，非 README 自述）。
- **无闭源付费部分。** 仓库树完整含 TS 源码（`src/api.ts`、`src/main.ts`、`src/recorder.ts`、`src/settings.ts`），无闭源二进制、无 license-key/激活/订阅门控代码，releases（1.0.1–1.0.8）也无付费资产。README 里「Premium」指 **Premium Visuals**（波形动画/录音闪烁/计时器等观感），是功能描述不是收费墙；唯一变现是可选 Ko-fi 打赏。
- 技术上：录音 → OpenAI Whisper（云，22MB 处切块避开 25MB 限）或 Gemini（10MB 切块）转写 → Claude/GPT/Gemini 做 LLM 后处理/总结；API/网络失败时把原始音频落到 vault 并在笔记里链接（「本地备份保险」）。

**据此结论**：票面「免费核心是否真是 MIT / 付费部分是否闭源」——**免费核心即全部核心，MIT 开源；不存在闭源付费部分，「Premium」是营销词。** 此问可结案。

### 3. 源码层面：翻出来的具体片段（读了 §1 表中 4 个可访问且有源码的仓库）

> 方法：`gh api` 读源码（非 clone）。重点看 whisper 调用、音频分块、错误处理、音频预处理。

**a) 本地 whisper.cpp 调用（akhmialeuski，`src/transcription/providers/LocalWhisperProvider.ts`）**
`execFile(binaryPath, ['-m', model, '-f', wav, '-oj', '-of', base, '-l', lang, '--prompt', terms, ...extraArgs])`。要点：
- `binaryPath/modelPath/extraArgs` 全部用户配置，线程/beam 不硬编码；`--prompt` 放在 `extraArgs` 之前以便用户覆盖。
- `-oj` 输出 JSON，时间偏移单位是**毫秒**（`offsets.from/to` ÷1000）。
- `maxBuffer` 抬到 **64MB**（whisper.cpp 把全文吐 stdout，Node 默认 1MB 会杀掉长任务）——*这是 execFile 才有的坑，我们直接 SSH 跑 CLI 落文件不受此限。*
- 词表被截到 whisper **~224 token 的 prompt 窗口**（`termsWithinWhisperPrompt`）——**真实 whisper 约束**。

**b) whisper webservice 调用（djmango，`src/transcribe.ts`）**
POST `{baseUrl}/asr?output=json&word_timestamps=true[&language=..&initial_prompt=..&vad_filter=..&task=translate&encode=..]`，multipart 字段名 `audio_file`。**整文件一次上传、不做客户端分块**，长音频与 VAD 全交给服务端（`onerahmet/openai-whisper-asr-webservice` Docker）。多个 URL 用 `;` 分隔做**顺序兜底**（非重试），全失败报 `All Whisper ASR URLs failed`；无退避、无显式超时。当前版本 **OpenAI 后端已移除**，只剩 `whisper_asr`。

**c) 云 API 分块/重试（mssoftjp，`src/config/ModelProcessingConfig.ts`、`ApiClient.ts`）**——**只因云端 25MB/25min 硬限才存在**
- 边界感知 + 重叠：Whisper 档 25s 块 / 5s 重叠 / 静音点对齐（RMS 阈值 0.01）；GPT-4o 档 300s 块 / 30s 重叠；重叠靠 fuzzy 去重（相似度 0.85）+ 上文提示词消解。
- 重试：`maxRetries:3`，指数退避 **1s→2s→4s**，重试条件 `5xx || 429 || 408`，90s 本地超时，批间 3s 限速。
- **反面教材**：可选本地 VAD（fvad.wasm）去静音会**丢掉轻声/短促发言**——README 自述「quiet voices and short utterances can be lost」。撞我们「转写不得走样/丢内容」。

**d) 转写前先落盘 / provider 兜底（jaliriogbarrios）**：「recordings are saved before transcription, never lost on API failure」；某 provider 失败自动试下一个；批量队列。AITranscribe 同款「失败落本地备份」。

**e) 音频预处理（akhmialeuski，`audioChunks.ts`）**：`decodeToMono16k` 强制 **16kHz 单声道 16-bit PCM WAV**（`TRANSCRIBE_SAMPLE_RATE=16000`），用浏览器 OfflineAudioContext（非 ffmpeg，插件内无外部依赖）。whisper.cpp 要求 16k 单声道输入。

## 对 story-machine 的影响

落到 spec **阶段 0（音频转写）** 与相关开放问题。以下区分【事实/来源直述】与【据此推断】：

1. **阶段 0 不要在客户端切音频。**【推断，基于跨仓库一致信号】本地路径都是整文件送进 whisper（akhmialeuski 本地档不分块；djmango 整文件上传服务端）。`faster-whisper` 内部按 30s 窗 + 自带 Silero VAD 处理任意长音频，**开 `vad_filter=True` 即可，无需自己切**。mssoftjp 那套重叠/对齐/去重机器**只因 OpenAI 25MB/25min 限**存在，本地无此约束，照抄纯属浪费。
   - **顺带澄清 spec 用词**：spec「阶段 1 分块 20–30min」是**逐字稿层面**为 LLM 提取控 token，**不是音频层面**——音频整段进 whisper。两个「分块」不要混。

2. **热词库注入必须受 ~224 token 窗口约束。**【事实：akhmialeuski 源码 + 通用 whisper 约束】spec 阶段 0 热词机制把 `hotwords.json` 塞进 `initial_prompt`——**每次注入的词表切片要卡在 ~224 token 以内**，超出被静默截断。建议按主题取相关词、给个 token 预算上限，别把整个热词库怼进去。这是本票对 spec 最实的一条补充。

3. **上传→转写→取回 的健壮性默认值**【推断，综合 mssoftjp/jaliriogbarrios/AITranscribe】：
   - **先把音频完整 scp 上 PC 并校验，再触发 whisper**（转写前先落盘，别边传边转）。
   - SSH/whisper 调用包一层：**3 次重试、指数退避 1s→2s→4s、硬超时**（挂死的 ssh 要显式失败而非静默卡住）。
   - 断言输出逐字稿存在，缺文件报明确错误（"检查 binary/model 路径"式）；远程临时文件在 `finally` 清理。

4. **传输前可选 16kHz 单声道降采样——为省带宽，不为精度。**【推断】faster-whisper 内部会重采样，精度上不需要；但 3 小时原始音频过 Tailscale 传给 PC，先转 16kHz 单声道（Opus/FLAC）能大幅压小上传体积。属可选优化，非必需。

5. **repetition/丢音两个坑**【事实 + 推断】：faster-whisper large-v3 在静音/音乐段会**复读**——`vad_filter` + 一个「重复行折叠」后处理即可缓解；反过来，**不要用激进去静音 VAD**（mssoftjp 自述会丢轻声/短发言），与「ASR 不得丢内容」非协商项冲突——用 faster-whisper 保守的窗口 VAD，别做剥离式静音删除。

6. **给 #5 / #9 的架构备选**【事实】：djmango 用的 [`ahmetoner/whisper-asr-webservice`](https://github.com/ahmetoner/whisper-asr-webservice)（Docker HTTP，**支持 faster-whisper 引擎**、内建 VAD、词级时间戳）是「裸 CLI over SSH」之外的另一种阶段 0 部署形态：笔记本 POST 音频、PC 上跑常驻服务。权衡——多一个要在 PC 上维护的服务 vs. 直连 CLI 更简单。留给 #5/#9 定夺，本票不裁决。

**对交付形态的确认**：6 个项目**均为 Obsidian 插件/SaaS，不改变** spec「MVP 不做 Obsidian 插件、阶段 0 是本地 CLI 包装脚本」的决策。**这几个仓库不需要再回头深挖**——上面 6 条已是全部值得带走的东西。

## 未决问题

（以下为调研中冒出、但超出本票范围者，供开新票，不在本票研究掉）

- **`ahmetoner/whisper-asr-webservice` 常驻服务 vs. 裸 faster-whisper CLI over SSH**，哪个作阶段 0 后端更省心？——并入 #5/#9 评估即可，本票不展开。
- **热词库 → `initial_prompt` 的「按主题取词」策略与 token 预算**具体怎么定（取多少词、如何算 token、超限如何取舍）？——属 spec 阶段 0 热词机制的实现细节，值得单开一票。
- 其余无。
