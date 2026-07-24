## 问的是什么

权威存储押结构化 Markdown 后，`key:: value` 行内字段有没有 Obsidian 外的可靠解析器？原生 Properties / Bases 能否取代 Dataview？

## 答案是什么

行内字段无正式规范、无成熟外部解析器（Dataview 的 TS 实现是唯一忠实版），须上报为架构风险。机器真相应押 YAML frontmatter + 已有 JSON 边车，行内字段只留 `_review/` 草稿给 LLM 消费；原生 Properties 够承载页级字段，Dataview/Bases 退为可选视图层。

## 对项目意味着什么

spec 第 5/7 节新增「机器真相分层」原则；#1 地基决策里「行内字段」需限定作用域为草稿；#3 的 JSON 边车做法确认正确；派生解析器用 python-frontmatter + json + 锚点安全插入器，不上 Node+Dataview；#7 可直接用文中两套约定片段。

## 最不可靠的地方

「无外部解析器」是穷举得出的否定判断，可能漏掉新库——错则风险被高估，可 npm/PyPI 复搜「dataview inline field parser」验证。归一化等语法细节随 Dataview 版本可能变，盯 `inline-field.ts` 的 commit 即可验。
