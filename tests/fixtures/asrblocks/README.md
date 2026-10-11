# tests/fixtures/asrblocks — 阶段 0 转写规则层的合成样例

**全部内容虚构**（红线 10）：句子表在 `mk_asrblocks.py`，沿用上级「河口夜话」设定。改样例改脚本重生成：
`python tests/fixtures/asrblocks/mk_asrblocks.py`。脚本自己合一遍块、拼一遍 token，并断言与 `expect` 一致。

`EP95.asrblocks.json`：VAD 语音区间（合成 6 块）、假解码表 `decodes[k]`（文本 + CTC token，块内秒）、
整批缺结果的块 `batch_missing`、假标点表 `punc`。

| 块 | 情形 | 预期 |
|---|---|---|
| 0 | 正常（纯汉字） | 出段，词按 token 挂上 |
| 1 | 汉字夹英文：`老周说 northbridge toll明年…`；标点版把英文首字母大写 | 出段，英文词带上后面的空格；标点版仍是小写 |
| 2 | 解码为空 | 不出段，计入 `empty` |
| 3 | token 拼出来是「夜事」，文本是「夜市」 | 出段，整块按字均分，计入 `words_linear` |
| 4 | 整批里缺结果 | 单独重解一次拿回来，出段 |
| 5 | 正常 | 出段 |

`python pc/asrblocks.py --demo tests/fixtures/asrblocks/EP95.asrblocks.json` 末行：
`asr: blocks=6 segments=5 empty=1 errors=0 words_linear=1`。
