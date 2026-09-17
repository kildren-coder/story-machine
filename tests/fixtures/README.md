# tests/fixtures — 合成样例

**全部内容虚构**（红线 10）：UP 主「河口夜话」、河口市、北港大桥、河口夜市、阿桥、老周都是编的，
不是任何真实直播的转写或改写。生成脚本的对白表是唯一事实来源；引文已由生成脚本断言为
某一段的连续子串，时间戳由段起点计算。改样例请改脚本重生成，不要手改 JSON。

## 布局

| 路径 | 是什么 | 对应 SPEC |
|---|---|---|
| `vault/` | 迷你 vault：两集逐字稿、两张 EP 笔记、一张已存在的事件笔记 | §5.1、§6.1、§5.8 |
| `vault/_assets/EP91.transcript.json` | 42:40，两位说话人，76 段；含一处 ASR 生音「北岗大桥」 | §5.1 |
| `vault/_assets/EP92.transcript.json` | 14:00，单说话人，22 段；同日加更，谈同一事件 | §5.1 |
| `vault/10-Episodes/EP91 ….md` | 没有 `整理:` 字段（仿现网旧笔记），带 `## 断言` `## 待办` 旧节 | §6.1 |
| `vault/10-Episodes/EP92 ….md` | 有 `整理: pending` | §6.1 |
| `vault/30-Events/2026-northbridge-toll.md` | first_seen 2026-03-05，「我的判断」有人写的内容 | §5.8 |
| `digest/EP91/`、`digest/EP92/` | L1 章节表 `chapters.json`、L2 片段 `frag-<话题>.json` 与话题表 `topics.json` 的**解析后产物**形状（带 `provenance`） | §5.3、§5.4、§9 |
| `digest/2026-03-12/events.json` | L4 事件清单：跨 EP 合并、同一 EP 内被打断的同一事件合并、沿用已有事件 id | §5.5 |
| `l3/frag-market-01.bad.json` | 故意违规的片段：闸门 1（引文改写）、2（时间戳越界）、3（丢 hedge）、5（asr.heard 不存在） | §4 L3 |
| `raw/<EP 或日期>/<层>-<单元>.raw.json` | 假 `claude -p --output-format json` 信封；L1 / L2 带 `structured_output`（`--json-schema` 的形状），L4 的 `result` 是围栏 JSON | §4.1 |
| `raw-bad/…` | 坏响应（只有 `result`）：L1 行号不在这一集里 + 缺 title；L2 闸门违规；L2 纯散文无 JSON；L4 引用不存在话题 + aside 成事件 | §4.1 |

`raw/` 的键与 `_pairs/` 的文件名一致：`_pairs/EP91/L2-bridge.in.md` ↔ `raw/EP91/L2-bridge.raw.json`。
L2 的单元是**章节**：一章一次调用，响应里是这一章的全部话题。假 runner 按这个键取响应，缺键即报错（不是静默跳过）。

## 章节与话题速查

| 集 | 章节（L1） | 章内话题（L2，`id` 由程序按 `<章节>-NN` 编） |
|---|---|---|
| EP91 | `bridge` 00:00:00–00:19:00 | `bridge-01` 开场（`filler`）、`bridge-02` 大桥收费（`talk`） |
| EP91 | `market` 00:19:00–00:42:40 | `market-01` 夜市搬迁（`talk`）、`market-02` 回到大桥（`talk`）、`market-03` 结尾弹幕（`aside`） |
| EP92 | `followup` 00:00:00–00:14:00 | `followup-01` 加更说明（`aside`）、`followup-02` 货车费率（`talk`）、`followup-03` 下周预告（`filler`） |

EP91 的 L1 响应里模型切了三章（`bridge` / `market` / `bridge-again`），第三章只有 6 分 40 秒，
程序把它并进 `market`（标题用顿号接、gist 顺序接），所以章节表里是两章、L2 调两次。
大桥那件事在 EP91 里被夜市打断，落在 `bridge-02` 与 `market-02` 两个话题里，L4 把它们归回同一个事件。

## 行号速查（EP91）

两集的段都比 30 秒长，所以 §5.2 文本的第 n 行就是对白表的第 n 段。行号 → 时间戳：第 7 行 00:03:30，
第 11 行 00:05:43，第 21 行 00:11:15（ASR 生音所在行），第 35 行 00:19:00，第 63 行 00:36:00，第 73 行 00:41:30。
