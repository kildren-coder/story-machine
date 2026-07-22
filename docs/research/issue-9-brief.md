## 问的是什么

RTX 5070(Blackwell/12GB)跑 faster-whisper large-v3 是否可行、要哪套版本、3 小时音频多久——给「ASR 方案确认」票供弹药,不做决策。

## 答案是什么

可行且推荐,架构不改。硬门槛:CTranslate2≥4.7.0(荐 4.8.1)+ CUDA 12.8 cuBLAS 才能在 Blackwell 开 INT8;首跑用 `float16` 最稳。12GB 对 large-v3 富余;3 小时音频批处理约 4 分钟、顺序约 15 分钟(据 3070 Ti 官方基准换算)。

## 对项目意味着什么

spec 阶段 0 方案不变,建议把版本下限钉进 spec:CT2≥4.7.0、CUDA 12.8+、`compute_type` 起步 `float16` 再切 `int8_float16`、开 VAD、不装 PyTorch。

## 最不可靠的地方

1. 速度是从 3070 Ti 基准外推,无 5070 原生多小时实测——偏差会让「几分钟」落空;验证:真机跑一集 large-v3 掐表。
2. Blackwell INT8 修复的硬件确认来自社区 5060 Ti(非官方 CI、非 5070 本体)——若不成立则一开 `word_timestamps` 就崩;验证:装好后跑一段看是否报 `CUBLAS_STATUS_NOT_SUPPORTED`。
