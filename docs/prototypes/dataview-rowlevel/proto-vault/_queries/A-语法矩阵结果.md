# A · 语法矩阵结果

> 样本：`_lab/A-语法矩阵样本.md`。六种写法承载同一条断言。
> **切到阅读视图（Ctrl+E）才会渲染 Dataview。**

## A-1 主判读表

每行应该有 **6 个变体**。列有值＝该写法的字段挂上了这一行；列空＝没挂上。

```dataview
TABLE WITHOUT ID
  L.probe AS "变体",
  L.type AS "type",
  L.情态 AS "情态·点号",
  L["情态"] AS "情态·方括号",
  L.谁说的 AS "谁说的",
  L.事件时间 AS "事件时间",
  L.实体 AS "实体"
FROM "_lab"
FLATTEN file.lists AS L
WHERE L.probe != null AND startswith(L.probe, "V")
SORT L.probe ASC
```

**怎么读这张表**

| 观察 | 结论 |
|---|---|
| V1 那行各列都有值 | ✅ **SPEC §5.1 成立**，数据模型不用动 |
| V1 行在、但除「变体」外全空 | ❌ 续行字段没挂上父行 → 看 V2/V3 有没有救，都没有就退 V6 |
| V1 行整个不出现 | 说明 `startswith` 或 `probe` 本身有问题，先修查询再判 |
| 「情态·点号」空但「情态·方括号」有值 | ⚠️ **中文字段名不能用点号访问**——SPEC §6.2 全部查询要改写成 `L["情态"]` |
| 两列都有值 | ✅ 中文键随便用，SPEC §6.2 原样可跑 |
| V4（零缩进）也有值 | ⚠️ 危险的假阳性：字段很可能挂到了**整个页面**而不是这一行，见 A-3 |
| V5（嵌套 list）父行空、但多出 10 个碎行 | 符合预期：一条断言炸成 11 个 list 条目，不可接受 |

## A-2 这个文件到底被切成了多少个 list 条目

> V5（嵌套）会让条目数暴涨。理想情况：6 个变体 = 6 条（V5 除外）。

```dataview
TABLE WITHOUT ID
  L.probe AS "probe(空=非顶层条目)",
  L.text AS "条目正文（截断看形状即可）"
FROM "_lab"
FLATTEN file.lists AS L
WHERE contains(file.name, "A-语法矩阵")
```

## A-3 零缩进（V4）的字段是不是跑到页面级去了

> 如果下面这张表里出现了 `causal` / `确定`，说明 V4 的字段被当成了**整篇笔记的属性**。
> 那是最坏的一种失败：单看渲染以为成功了，一做跨集查询就发现一集只有一条「断言」。

```dataview
TABLE WITHOUT ID
  file.link AS "文件",
  type AS "页面级 type",
  情态 AS "页面级 情态"
FROM "_lab"
WHERE type != null OR 情态 != null
```

## A-4 退路验证：V6（全挤一行）是不是真的稳

```dataview
TABLE WITHOUT ID
  L.probe, L.type, L.情态, L.cause, L.effect
FROM "_lab"
FLATTEN file.lists AS L
WHERE L.probe = "V6"
```

> V6 若成立，最坏情况下数据模型不必改，只是 markdown 源码更难读——
> 而 SPEC §5.1 已经声明「EP 笔记是容器不是阅读界面」，所以这个代价**是可以接受的**。
> 换句话说：**这次实验不存在「方案作废」的结局，只有「用哪种写法」的结局。**
