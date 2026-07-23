# PR 摘要：issue #18

## 问的是什么
把 6 个 Obsidian 音频转写插件（Snipd 等）"已排除"正式落档，并答两点：它们在 whisper 调用/分块/错误处理上有无值得抄进阶段 0 CLI 脚本的做法；"AI Audio Transcription and Summary" 免费核心是否 MIT、付费部分是否闭源。

## 答案是什么
6 个全部排除成立（均为插件/SaaS，非交付形态）。但"没啥可抄"的先验被推翻：摘出 5 条可落地做法，最硬的是 whisper `initial_prompt` 仅 ~224 token 窗口。AITranscribe 整仓 MIT、无闭源付费部分，"Premium" 只是 UI 观感营销词，只靠 Ko-fi 打赏变现。

## 对项目意味着什么
落到 spec 阶段 0：热词注入须卡在 ~224 token 内（超出被静默截断，最实一条）；本地路径别在客户端切音频、改用 faster-whisper 的 `vad_filter`；别用激进去静音 VAD（会丢轻声）。webservice 常驻服务作后端的备选留给 #5/#9。

## 最不可靠的地方
224 token 窗口是唯一"改参数"级结论：错了会让热词库被悄悄截断、热词失效——验证法是在 faster-whisper 塞一段超长 `initial_prompt`，看尾部词是否还影响识别。其余（whisperscribe 已 404、Snipd 闭源）靠二手描述，但均属排除项，错了无碍。
