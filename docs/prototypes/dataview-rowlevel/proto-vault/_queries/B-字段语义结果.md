# B · 字段语义结果

> 样本：`_lab/B-字段语义样本.md`。
> 若实验 A 判定**中文键不能点号访问**，把下面所有 `L.主题` 改成 `L["主题"]` 再看。

## B-1 每个字段被解析成了什么类型

```dataview
TABLE WITHOUT ID
  L.probe AS "探针",
  typeof(L.主题) AS "typeof 主题",
  L.主题 AS "主题值",
  typeof(L.实体) AS "typeof 实体",
  typeof(L.事件时间) AS "typeof 事件时间",
  L.事件时间 AS "事件时间值"
FROM "_lab"
FLATTEN file.lists AS L
WHERE L.probe != null AND startswith(L.probe, "B")
SORT L.probe ASC
```

| 观察 | 结论 |
|---|---|
| B01 是 `array`、B02 是 `string` | ✅ **多值必须用英文逗号**，中文逗号不切分 → 写进 prompt 硬约束 |
| B01 和 B02 都是 `array` | ⚠️ 中文逗号也切 → 自由文本字段有被误切的风险，见 B-3 |
| B03（单值）是 `string` 而非单元素 `array` | ⚠️ 单值/多值类型不一致，`contains` 行为随之改变 → 见 B-2 |

## B-2 `contains` 到底在匹配什么（子串陷阱）

> 这几行**都不该**被「美债」命中，只有 B01/B03 该命中。

```dataview
TABLE WITHOUT ID
  L.probe AS "探针",
  L.主题 AS "主题",
  contains(L.主题, "美债") AS "contains 主题 美债"
FROM "_lab"
FLATTEN file.lists AS L
WHERE L.probe != null AND L.主题 != null
SORT L.probe ASC
```

**B04（主题写作「美债市场」）如果返回 true，就是子串误召回。**
修法两条，二选一，跑完在这里记下选了哪条：
- 查询侧改成 `any(L.主题, (t) => t = "美债")`（精确匹配，但对 string 型单值不成立）
- 数据侧强制**永远至少两个值**或统一带前缀 —— 丑，不推荐

同一组问题对 `实体` 再来一遍（SPEC §6.2 的人物时间轴压在这上面）：

```dataview
TABLE WITHOUT ID
  L.probe AS "探针",
  L.实体 AS "实体",
  contains(L.实体, "小布什") AS "contains 实体 小布什"
FROM "_lab"
FLATTEN file.lists AS L
WHERE L.probe != null AND L.实体 != null
SORT L.probe ASC
```

> 重点看 **B07**（`[[小布什的国家安全顾问]]`，不该命中）和 **B08**（`[[小布什|布什总统]]`，应该命中）。
> 这两行决定「人物时间轴」是不是一个可信的视图，还是一个悄悄多召回/漏召回的视图。

## B-3 ★ 自由文本里的逗号会不会把 effect 切碎

```dataview
TABLE WITHOUT ID
  L.probe AS "探针",
  typeof(L.effect) AS "typeof",
  L.effect AS "effect 渲染出来的样子"
FROM "_lab"
FLATTEN file.lists AS L
WHERE L.effect != null
SORT L.probe ASC
```

**B17 若 typeof = `array`**，那么 SPEC §5.5「宁可啰嗦」就带了一条隐藏约束：
> **自由文本字段（`cause` / `effect` / `source_quote` / `原话口径` / `为什么值得看` / list item 正文）一律用中文逗号；英文逗号是多值分隔符的保留字。**

这条要写进 `prompts/stage2-extract.md`，并且**做成一条出口闸门**——机械可检，正是闸门擅长的活。

## B-4 三种时间能不能排序

```dataview
TABLE WITHOUT ID
  L.probe AS "探针",
  L.事件时间 AS "事件时间",
  L.事件时间精度 AS "精度",
  typeof(L.事件时间) AS "typeof"
FROM "_lab"
FLATTEN file.lists AS L
WHERE L.probe != null AND startswith(L.probe, "B")
SORT L.事件时间 ASC
```

看两件事：
1. `1690` / `1978-03` / `2001-09-11` / 空值 混排后**顺序对不对**
2. **空值（B12）落在头部还是尾部** —— SPEC §5.3 说「排序沉底」，若实际浮在顶部，
   要么改 SPEC 的说法，要么给空值填一个哨兵值（不推荐，等于伪造时间）

```dataview
TABLE WITHOUT ID
  L.probe, L.录音时间戳, typeof(L.录音时间戳)
FROM "_lab"
FLATTEN file.lists AS L
WHERE L.录音时间戳 != null
SORT L.录音时间戳 ASC
```

> `00:29:00` 可能被解析成 duration、time 或 string。只要 **B14 排在 B15 前面**就够用了。

## B-5 同名字段写两次

```dataview
TABLE WITHOUT ID
  L.probe, typeof(L.source_quote) AS "typeof", L.source_quote
FROM "_lab"
FLATTEN file.lists AS L
WHERE L.source_quote != null
SORT L.probe ASC
```

> `array` → SPEC §5.3「`source_quote` 可多条」原样成立。
> 否则要改成单字段内分隔（用什么分隔符要绕开 B-3 的结论）。

## B-6 括号式与续行式的解析规则是否一致

> 只在实验 A 判定续行成立时才有意义。B20/B21/B22 应与 B01/B17/B19 逐项一致。

```dataview
TABLE WITHOUT ID
  L.probe, typeof(L.主题), typeof(L.effect), typeof(L.source_quote)
FROM "_lab"
FLATTEN file.lists AS L
WHERE L.probe != null AND (L.probe = "B01" OR L.probe = "B17" OR L.probe = "B19"
   OR L.probe = "B20" OR L.probe = "B21" OR L.probe = "B22")
SORT L.probe ASC
```
