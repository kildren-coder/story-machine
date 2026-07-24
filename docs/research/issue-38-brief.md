## 问的是什么

多阶段媒体 CLI（beets / paperless / yt-dlp）在子命令边界、中间态、断点续跑、配置、中途等人、Windows 分发六事上的做法，哪些可抄到本项目 `transcribe` / `process`？

## 答案是什么

无一可整体照抄，各擅一维、拆开各取：抄 beets 胖动词 `import` + 置信度分档、yt-dlp 纯文本账本 + `.part` 原子改名、paperless 显式任务态 + 贵环节不自动重试；而"退出-等人-重进"的审核闸门三家皆无、须自造。人面向态用可读文件（拒 beets 的 sqlite/pickle）、进度态用每集 manifest；配置 TOML 两层（共享进库 + 机器本地走 env）；分发用 uv + `PYTHONUTF8=1`。

## 对项目意味着什么

喂 #5 CLI 形状与 spec 新增「状态管理」节：两胖动词、`process` 可重入、单步重跑走 flag；加幂等约束（阶段 4 合并不得重复追加来源行）、原子写、块级续跑；`claude -p` 喂逐字稿走文件不走管道。审核信号语义留 #4、模板留 #7。

## 最不可靠的地方

① "whisper 系无一支持跨机/续跑"是穷举否定，仅据各 README、非源码确认——错则"须自造桥接"的结论落空；验证：搜 whisperX / insanely-fast-whisper 有无 remote/server 模式。② uv 供的 Python 与 5070 Blackwell CUDA 栈相容性属实机未知——错则推翻"分发选 uv"；验证：5070 实测 `uv python install` + faster-whisper GPU 跑通。
