# D · 规模与性能

> 先跑：`python docs/prototypes/dataview-rowlevel/build.py --bulk 100`
> → `10-Episodes/bulk/` 下 100 集 × 30 行 = **3000 条断言行**（合成，字段形状真实）。
> 看完：`python build.py --clean`。
>
> 参照现实量级：一集 3 小时约 30–60 条断言。**3000 行 ≈ 攒了 60–100 集**，
> 也就是一年多的量。如果这个规模就已经卡，那数据模型撑不到有用的那天。

## D-1 总行数

```dataview
TABLE WITHOUT ID
  length(rows) AS "断言行总数"
FROM "10-Episodes"
FLATTEN file.lists AS L
WHERE L.type != null
GROUP BY true
```

## D-2 按 type 分布

> **踩坑记录**：`GROUP BY L.type` 之后 `L` 不再指向单条记录，`L.type AS "type"` 拿不到分组键，
> 那一列会渲染成空。必须显式给分组键起别名，再直接引用别名（不带 `L.` 前缀）。
>
> **结果（2026-07-28 跑通）**：改用 `GROUP BY L.type AS grp` + `TABLE grp AS "type"` 后，五个 type 正常显示：
> fact 1233、causal 844、prediction 481、judgment 277、channel 174，加总 3009，与 D-1 总行数一致。

```dataview
TABLE WITHOUT ID
  grp AS "type",
  length(rows) AS "条数"
FROM "10-Episodes"
FLATTEN file.lists AS L
WHERE L.type != null
GROUP BY L.type AS grp
SORT length(rows) DESC
```

## D-3 全量时间轴（最重的一条：全表扫 + 排序 + 长文本渲染）

> 查询已按 A/B/C 组结论更新：`L.text` 直接显示会带出全部方括号字段，改用 `split(L.text, "\\[")[0]` 只取正文（见 C-2b）。

```dataview
TABLE L.事件时间, L.事件时间精度, L.type, split(L.text, "\\[")[0] AS "断言"
FROM "10-Episodes"
FLATTEN file.lists AS L
WHERE L.事件时间 != null
SORT L.事件时间 ASC
LIMIT 200
```

## D-4 把 LIMIT 去掉、把「只看有日期的行」也去掉——真正的全量 3000 行

> 3000 行全渲染。**卡就是卡了**——这不是失败，是一条要记住的使用约束：
> 保存查询一律带 `LIMIT`，或按 `播出日期` 先收窄。
> 这条也不再过滤 `事件时间 != null`（原 D-3/D-4 都过滤掉了空值，导致「空值排在头/尾」这个观察项其实无从验证），
> 换成复合排序键，顺便在 3000 行规模下复核 B-4b 的结论是否依然成立。

```dataview
TABLE L.事件时间, L.type, split(L.text, "\\[")[0] AS "断言"
FROM "10-Episodes"
FLATTEN file.lists AS L
SORT L.事件时间 = null ASC, L.事件时间 ASC
```

## 记录处（2026-07-28 跑通）

| 观察项 | 结果 |
|---|---|
| 行数 | 3009（3000 合成 + 9 条 EP01 真实数据，D-1 验证对上） |
| D-3/D-4 切到阅读视图出结果耗时 | 约 10 秒 |
| 编辑一条断言（bulk 文件内）后，查询多久刷新 | 体感 <2 秒，可用 |
| 空 `事件时间` 排在头 / 尾 | 机制同 B-4b（复合排序键），D-4 首屏展示的确是有值行，符合预期 |
| Obsidian 整体是否发烫/卡顿 | **不是笔记本身卡，是切换标签页时卡**——从 D（含 D-4 这条无 LIMIT 的全量查询）切到 C，有约 30 秒明显卡顿；切回 D 之后反而恢复正常速度 |

> **判读线**：只要「编辑后刷新」在 1–2 秒内，日常就是可用的——
> 因为真实使用是**看保存好的查询**，不是反复重排全表。
> 真正致命的只有一种情况：打开任意一个 EP 笔记本身就卡（说明索引开销在写入侧）。
>
> **新发现，判读线要补一条**：致命的不只是「笔记本身卡」，**切出/切回**含无 `LIMIT` 全量查询的笔记也会卡（本次实测约 30 秒）。
> 推测是 Dataview 在后台重新求值该笔记里挂着的重量级查询。这不是新的失败模式，而是印证了 D-4 自己早就写明的结论——
> **保存查询一律带 `LIMIT`，或按 `播出日期` 先收窄**——现在多了一条实证：不只查询本身的渲染耗时要控制，
> **挂着无界查询的笔记本身也不该被长期留在打开的标签页里**，切走它同样有代价。
