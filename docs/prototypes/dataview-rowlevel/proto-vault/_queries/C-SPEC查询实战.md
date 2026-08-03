# C · SPEC §6.2 四条查询，原样跑

> 这四条是从 `SPEC.md` §6.2 抄过来的。
> 实验 A/B 验的是零件，这里验的是成品：**照 SPEC 写的查询，能不能跑出人想看的东西。**
>
> **2026-07-28 更新**：实验 A/B 已经把 SPEC §6.2 原来的写法推翻了三处——
> `实体` 匹配不能用纯字符串（要 `link()`）、`主题` 筛选不能直接 `contains()`（要 array/string 兼容表达式）、
> `事件时间` 排序空值会浮顶（要复合排序键）。下面四条已经照 SPEC 当前版本（修正后）誊抄，
> 不是原来那版会踩坑的写法了——C 组现在验的是「修正后的写法在真实抽取产物上能不能跑通」。
> `10-Episodes/EP01…md` 也已同步改写成 V6 括号式 + 主题重复 key（原是四空格续行 + 逗号分隔，已被 A/B 推翻）。

## C-1 待检验预测队列（周检用，SPEC §4.6）

```dataview
TABLE L.事件时间原文, L.应验判据原文, L.谁说的, file.link
FROM "10-Episodes"
FLATTEN file.lists AS L
WHERE L.type = "prediction" AND L.检验状态 = "待检验"
SORT L.录音时间戳 ASC
```

期望：EP01 只有 **A-02** 一条。跑了 `--bulk` 之后会多出一批合成行。

## C-2 人物时间轴

```dataview
TABLE L.事件时间, L.事件时间精度, L.text, L.谁说的, file.link
FROM "10-Episodes"
FLATTEN file.lists AS L
WHERE contains(L.实体, link("小布什"))
SORT L.事件时间 = null ASC, L.事件时间 ASC
```

期望：EP01 只有 **A-04**。**这条查询是「按人物拉时间轴」这个愿望的全部实现**——
它要么成立，要么 SPEC §5.3 把 `事件时间` 提升为一等索引键的整个论证就落空了。

跑 `--bulk` 后重点看三件事：
1. 几千行时**多久出结果**（有没有肉眼可见的卡顿）
2. 空 `事件时间` 的行排在**头部还是尾部**
3. `L.text` 列在长句下的**可读性**——这是人真正要读的一列

### C-2b ★ 补测：`L.text` 被全部方括号字段污染，能不能只取干净正文

> C-2 实测发现 V6 括号式写法下，`L.text` 是**整个 list item 的完整文本**，
> 正文句子后面跟着的全部 `[key:: value]` 字段都混在一起，不是一句能读的话。
> 候选修法：正文永远写在所有方括号字段**之前**，取 `L.text` 第一个 `[` 字符之前的部分即可，
> 不需要处理方括号配对（`实体` 字段里嵌套 `[[双链]]`，配对正则容易在这里踩坑，这个办法绕开了它）。

```dataview
TABLE WITHOUT ID
  file.link AS "文件",
  L.text AS "原始 L.text（对照，应该很乱）",
  split(L.text, "\\[")[0] AS "只取第一个 [ 之前"
FROM "10-Episodes"
FLATTEN file.lists AS L
WHERE contains(L.实体, link("小布什")) OR L.type = "channel"
```

> **踩坑记录**：`split()` 的第二个参数是**正则表达式**，裸 `"["` 会被解析成未闭合的字符类，直接报错。
> 必须转义成 `"\\["`。

> 特意把 A-08/A-09 也捞进来——它们的 `实体` 字段里嵌套着 `[[双链]]`（`[[美国国债]]`、`[[Martin Wolf]]` 等），
> 是最容易把简单方括号正则弄错的情况。若三行的"只取第一个 [ 之前"都干净、且没有截断，
> 说明 `split(L.text, "[")[0]` 是可靠的取正文写法，要写进所有面向阅读的查询模板（连同 §6.2 各条查询一起改）。

**结果（2026-07-28 跑通）**：第一次跑报错——`split()` 第二个参数是正则表达式，裸 `"["` 被解析成未闭合字符类。转义成 `"\\["` 后三行全部干净：A-04/A-08/A-09 都只剩正文那句话，没有截断，`[[双链]]` 嵌套也没破坏。
**结论：`split(L.text, "\\[")[0]` 是可靠的取正文写法。SPEC §6.2 所有拿 `L.text` 给人读的查询（人物时间轴、归因并集视图）都要改成这个写法，而不是直接显示 `L.text`。已同步 `SPEC.md` §6.2。**

## C-3 渠道索引（目的 B 的主产出）

他**明说**「你们去看」的：

```dataview
TABLE L.渠道类型, L.名称, L.作者或机构, L.取数地址, L.为什么值得看, file.link
FROM "10-Episodes"
FLATTEN file.lists AS L
WHERE L.type = "channel"
SORT L.渠道类型, L.名称
```

按主题反查（**实际使用形态**，SPEC §5.4 的例外条款就是为它写的）：

```dataview
TABLE L.渠道类型, L.名称, L.取数地址, L.为什么值得看
FROM "10-Episodes"
FLATTEN file.lists AS L
WHERE L.type = "channel" AND ((typeof(L.主题) = "array" AND contains(L.主题, "美债")) OR L.主题 = "美债")
```

期望：只捞到 **A-08**，不该捞到 A-09。若两条都出来，回头看实验 B-2 的子串陷阱。

## C-4 「他都看什么」＝并集视图的另一半

> 他没明说但在用的信源，藏在断言的归因里。SPEC §5.2 说这半边数量远大于 C-3。

```dataview
TABLE L.归因媒体, L.归因作者, L.text, file.link
FROM "10-Episodes"
FLATTEN file.lists AS L
WHERE L.归因作者 != null OR L.归因媒体 != null
SORT L.归因媒体
```

期望：EP01 捞到 **A-03**（归因作者 查克·舒默）和 **A-07**（外网社媒 / 未具名）。

⚠️ A-07 的 `归因作者:: 未具名` 会**混进结果里**——它是个占位值，不是一个人。
若确认碍事，SPEC §5.3 要补一句：**归因作者不详时留空，不要写「未具名」**，
「不详」这个信息由 `归因类型` 承担已经足够。这是原型该抓出来的那类小毛病。

**决定（2026-07-28）：留空，不写「未具名」。** 已同步：`SPEC.md` §5.3 字段表补充说明；
`10-Episodes/EP01…md` 的 A-07 已改成 `[归因作者::]`；抽取侧约束记进 issue #48。

## C-5 同一结果的不同解释（分歧素材）

```dataview
TABLE L.谁说的, L.cause, L.effect, file.link
FROM "10-Episodes"
FLATTEN file.lists AS L
WHERE L.type = "causal" AND contains(L.实体, link("小布什"))
```

> SPEC §5.5 明说**不做字面聚合**，人读 `cause`/`effect`。
> 这里唯一要看的是：**两列长文本并排放在表格里，还读得下去吗。**
> 若读不下去，说明「宁可啰嗦」和「表格视图」有张力——那就得考虑 `LIST` 视图而不是 `TABLE`。
