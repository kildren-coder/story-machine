# C · SPEC §6.2 四条查询，原样跑

> 这四条是从 `SPEC.md` §6.2 **一字未改**抄过来的。
> 实验 A/B 验的是零件，这里验的是成品：**照 SPEC 写的查询，能不能跑出人想看的东西。**
>
> 若 A 判定中文键要用方括号访问，这四条都要改写——那本身就是本次原型最重要的产出之一。

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
WHERE contains(L.实体, "小布什")
SORT L.事件时间 ASC
```

期望：EP01 只有 **A-04**。**这条查询是「按人物拉时间轴」这个愿望的全部实现**——
它要么成立，要么 SPEC §5.3 把 `事件时间` 提升为一等索引键的整个论证就落空了。

跑 `--bulk` 后重点看三件事：
1. 几千行时**多久出结果**（有没有肉眼可见的卡顿）
2. 空 `事件时间` 的行排在**头部还是尾部**
3. `L.text` 列在长句下的**可读性**——这是人真正要读的一列

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
WHERE L.type = "channel" AND contains(L.主题, "美债")
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

## C-5 同一结果的不同解释（分歧素材）

```dataview
TABLE L.谁说的, L.cause, L.effect, file.link
FROM "10-Episodes"
FLATTEN file.lists AS L
WHERE L.type = "causal" AND contains(L.实体, "小布什")
```

> SPEC §5.5 明说**不做字面聚合**，人读 `cause`/`effect`。
> 这里唯一要看的是：**两列长文本并排放在表格里，还读得下去吗。**
> 若读不下去，说明「宁可啰嗦」和「表格视图」有张力——那就得考虑 `LIST` 视图而不是 `TABLE`。
