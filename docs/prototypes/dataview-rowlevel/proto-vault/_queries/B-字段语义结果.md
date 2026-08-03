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

### B-2b ★ 补测：`contains(L.实体, "小布什")` 全部返回 false 之后，换种写法再试

> 上面那条用纯字符串去匹配 Link 数组，五行全 false——连 B05/B06/V6 这种明摆着有 `[[小布什]]` 的行都没匹配上。
> 怀疑是 Link 对象不能直接跟字符串比较。用 `link()` 构造出 Link 对象再比一次：

```dataview
TABLE WITHOUT ID
  L.probe AS "探针",
  L.实体 AS "实体",
  contains(L.实体, link("小布什")) AS "contains(实体, link(小布什))"
FROM "_lab"
FLATTEN file.lists AS L
WHERE L.probe != null AND (contains(L.probe, "B0") OR L.probe = "V6")
  AND (L.probe = "B05" OR L.probe = "B06" OR L.probe = "B07" OR L.probe = "B08" OR L.probe = "V6")
SORT L.probe ASC
```

> 若这条对 B05/B06/B08/V6 返回 true、对 B07 返回 false——说明正确写法是 `contains(L.实体, link("目标名"))`，
> SPEC §6.2「人物时间轴」的查询要照此改写。若这条也全 false，问题更深，需要另外查 Dataview 的 Link 比较 API。

**结果（2026-07-28 跑通）**：B05/B06/B08/V6 = true，B07 = false，精确对上预期，且 B08 的别名 `[[小布什|布什总统]]` 正确按底层链接目标匹配，不受显示别名干扰。
**结论：`contains(L.实体, "纯字符串")` 是错误写法（Link 数组不跟字符串比较，永远 false）；正确写法是 `contains(L.实体, link("目标名"))`。已同步：`SPEC.md` §6.2「人物时间轴」改写。**

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

**结果（2026-07-28 跑通）**：两个问题都实锤了。
1. **空值浮顶，不是沉底**：22 行空 `事件时间` 全部排在最前面，B13/B10/B09/B11 四行有值的反而挤在最后——与 SPEC §5.3「排序沉底」的说法相反。
2. **混合类型排序确实乱了，且很隐蔽**：B13(1690-01-01)→B10(1978-03)→B09(2001-09-11) 三个 `date` 类型升序正确，但 **B11（裸写 `1690`，`typeof` 是 `number`）排在了 B09(2001) 之后**——明明是四行里最早的年份，却因为类型是 `number` 不是 `date`，被排到了最末尾，不是"差一点"，是整个颠倒。
**结论：`事件时间` 必须强制统一写成定长 ISO 字符串（`1690-01-01`），不许裸写数字年份；空值排位不能指望默认排序，查询要用复合排序键把空值挤到尾部（见 B-4b）。**

```dataview
TABLE WITHOUT ID
  L.probe, L.录音时间戳, typeof(L.录音时间戳)
FROM "_lab"
FLATTEN file.lists AS L
WHERE L.录音时间戳 != null
SORT L.录音时间戳 ASC
```

> `00:29:00` 可能被解析成 duration、time 或 string。只要 **B14 排在 B15 前面**就够用了。

## B-4b ★ 补测：空值挤到尾部的排序技巧管不管用

> B-4 发现两个问题：① 空 `事件时间` 排在了头部而非 SPEC 说的"沉底"；
> ② `B11`（裸写数字 `1690`，`typeof` 是 `number`）跟其他 `date` 类型混排后顺序整个乱掉。
> 这里只测①的解法——用复合排序键把"是否为空"当第一排序键，空值强制排到最后：

```dataview
TABLE WITHOUT ID
  L.probe AS "探针",
  L.事件时间 AS "事件时间",
  typeof(L.事件时间) AS "typeof"
FROM "_lab"
FLATTEN file.lists AS L
WHERE L.probe != null AND startswith(L.probe, "B")
SORT L.事件时间 = null ASC, L.事件时间 ASC
```

> 期望：所有有值的行（B09/B10/B11/B13）排在前面、所有空值行排在最后面。
> **②(B11 类型错位)不会被这条技巧解决**——那是数据侧问题（裸数字没被解析成 date），
> 解法是书写规范强制 `事件时间` 永远写定长 ISO 字符串（`1690-01-01`），不是查询能补救的。
> 这条只验证空值排位，两个问题分开看。

**结果（2026-07-28 跑通）**：完全生效。四行有值的（B13/B10/B09/B11）全部排到前面，22 行空值全部挤到最后。
非空组内部顺序仍是 B13→B10→B09→B11，B11 依旧排在末位——确认这条技巧只解决空值排位，不解决类型混排。
**结论：SPEC §6.2 所有涉及 `事件时间` 排序的查询，都要加上 `SORT L.事件时间 = null ASC, L.事件时间 ASC` 这个复合排序键。**

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

## B-7 ★ 补测：`主题` 换成方括号字面量语法，还会不会踩子串陷阱

> B-1 已确认 `主题:: 美债, 资金流向`（纯逗号）无论中英文逗号 `typeof` 都是 `string`，
> 导致 `contains()` 变成子串匹配，B01~B04 对「美债」全部误命中。
> 这里换 Dataview 自己的列表字面量语法（`[主题:: [a, b]]`）再测一次类型和子串行为。

```dataview
TABLE WITHOUT ID
  L.probe AS "探针",
  typeof(L.主题) AS "typeof",
  L.主题 AS "主题值",
  contains(L.主题, "美债") AS "contains 美债"
FROM "_lab"
FLATTEN file.lists AS L
WHERE L.probe = "B23" OR L.probe = "B24"
SORT L.probe ASC
```

> **B23**（`[美债, 资金流向]`）该是 `array`，`contains` 该是 `true`（精确元素匹配）。
> **B24**（`[美债市场]`，刻意只放一个像子串的值）——若 `typeof` 是 `array` 且 `contains` 返回 `false`，
> 说明方括号字面量语法下 `contains()` 按**数组元素相等**比较，不再是子串匹配，子串陷阱解除。
> 若 `typeof` 仍是 `string`，说明这条路也走不通，得改用别的匹配函数（如 `any(split(L.主题, ", "), (t) => t = "美债")`）。

**结果（2026-07-28 跑通）**：B23/B24 的 `typeof` 都还是 `string`，`主题值` 里连字面的方括号字符都保留了下来（没有被解析成列表语法），`contains` 两个都是 `true`。**方括号字面量语法不成立**，Dataview 的行内字段值永远是标量，不支持这种字面量数组写法。

## B-8 ★ 补测二：照搬 `source_quote`（B19）的成功机制——重复 key 而非逗号分隔

> B19 证明「同一个 key 在同一个 list item 里重复出现」会自动合并成 `array`（这才是 Dataview 真正支持的多值写法）。
> 照此重做多值主题：`[主题:: 美债] [主题:: 资金流向]`，而不是 `[主题:: 美债, 资金流向]`。

```dataview
TABLE WITHOUT ID
  L.probe AS "探针",
  typeof(L.主题) AS "typeof",
  L.主题 AS "主题值",
  contains(L.主题, "美债") AS "contains 美债"
FROM "_lab"
FLATTEN file.lists AS L
WHERE L.probe = "B25" OR L.probe = "B26"
SORT L.probe ASC
```

> **B25**（`[主题:: 美债] [主题:: 资金流向]`）该是 `array`，`contains` 该是 `true`（精确元素匹配）。
> **B26**（`[主题:: 美债市场]`，单值、刻意像子串）——若 `typeof` 变成 `array`（哪怕单元素）且 `contains` 返回 `false`，
> 说明**重复 key 才是主题多值的正确写法**：SPEC §5.4/§5.3 的 `主题` 书写规范要从「逗号分隔」改成「每个主题一个独立的 `[主题:: x]`」，`prompts/stage2-extract.md` 也要照此改。
> 若这条也不行，子串陷阱就没有语法层面的解法，只能在查询侧改用 `any(split(L.主题, ", "), (t) => t = "美债")` 这类精确匹配函数。

**结果（2026-07-28 跑通）**：B25（重复 key，2 值）→ `array`，`contains` 精确匹配、`true`，符合预期。
**B26（重复 key，但只有 1 个值）→ 仍是 `string`，`contains` 仍是 `true`（子串误中）。单值永远是标量，这是 Dataview 的通用行为，不是写法问题——「重复 key」只解决了「两个及以上值」的情况，解决不了单值。**

## B-8b ★ 收尾验证：查询侧同时处理 array/string 两种类型，子串陷阱能不能靠这个绕开

> 既然「单值必然是 string」绕不开，改在查询层面下手：数组用 `contains()` 精确匹配元素，
> 标量用 `=` 精确相等（"美债市场" 天然不等于 "美债"）。两者 `OR` 拼起来：

```dataview
TABLE WITHOUT ID
  L.probe AS "探针",
  L.主题 AS "主题值",
  ((typeof(L.主题) = "array" AND contains(L.主题, "美债")) OR L.主题 = "美债") AS "精确命中 美债"
FROM "_lab"
FLATTEN file.lists AS L
WHERE L.probe = "B03" OR L.probe = "B04" OR L.probe = "B25" OR L.probe = "B26"
SORT L.probe ASC
```

> 期望：**B03**（单值"美债"）→ `true`；**B04**（单值"美债市场"）→ `false`；
> **B25**（数组，含"美债"）→ `true`；**B26**（单值"美债市场"）→ `false`。
> 若四行都对，`(typeof(L.主题) = "array" AND contains(L.主题, "x")) OR L.主题 = "x"` 就是子串陷阱的正式解法，
> 要同步进 SPEC §6.2「渠道索引…按主题翻」和「人物时间轴」之外所有按 `主题` 筛选的查询模板。

**结果（2026-07-28 跑通）**：B03=true、B04=false、B25=true、B26=false，四行全对。
**结论：`主题` 多值必须写成重复 key（`[主题:: x] [主题:: y]`），不能逗号分隔（后者永远解析成一整条 string，§5.3/§5.4 书写规范要改）；
按主题筛选一律用 `(typeof(L.主题) = "array" AND contains(L.主题, "x")) OR L.主题 = "x"`，不能直接 `contains()`（会踩子串陷阱）。
已同步：`SPEC.md` §5.3 示例、§5.4 书写规范、§6.2「渠道索引」查询。**
