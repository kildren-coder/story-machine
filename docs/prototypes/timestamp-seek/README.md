# 时间戳跳播验证（2026-08-02 ~ 08-03）

**问的问题：** 点断言行的 `录音时间戳`，能不能直接从那个位置听主播原话？

**结论：** 自研插件 `story-machine-timestamps`，见 [ADR 0001](../../adr/0001-时间戳跳播自研插件.md)。

## 这里是什么

从生产 vault（`D:\obsidian-task\任务栏\story-machine\_lab\`）拷回来的实测记录。**这些笔记要在装了 Dataview 的 Obsidian 里、用阅读视图才能复现**，直接读 markdown 只能看到结论表。

| 文件 | 作用 |
| --- | --- |
| `T-时间戳跳播验证.md` | 主记录。A–G 七轮矩阵 + 每轮的源码分析和回填结果 |
| `EP-sample.md` | EP01 的五条断言行（SPEC §5.1 形状），含 `HH:MM:SS` / 三位数分钟等边界 |
| `EP-sample2.md` | 第二「集」，音频是 EP01 的 60:00–70:00 切片。和 EP-sample 撞同一个 `05:00`，用来验跨集串音频 |

音频（`EP01.m4a` 71.7MB / `EP02.m4a` 5.1MB）没进 git。EP02 的复现方式：

```
ffmpeg -ss 3600 -i <EP01 原文件> -t 600 -c copy EP02.m4a
```

判别器是**听觉的**：EP02 的 `05:00` 等于 EP01 的 `65:00`，两段话完全不同，听一句就知道点中了哪一集。

## 值得留意的两处预判被推翻

**推翻一（C 组）**：读 `timestamp-player` 源码看到 `querySelectorAll("p")`，推断 Dataview 表里的时间戳不会变按钮（`renderCompactMarkdown` 会剥掉 `<p>`）。实测全过——post processor 跑在**剥 `<p>` 之前**的中间 DOM 上，按钮先造好、`<p>` 后被剥，按钮活了下来。

**推翻二（E-4）**：以为按钮造出来就完事。实测断言行能显示按钮但点不动，而同一篇笔记的松散列表正常——差别是断言行有 inline field，**Dataview 在 post processor 跑完之后重画那一行，把按钮抹了**。修法是 `sortOrder=200` + MutationObserver 补画 + 事件委托（mousedown 和 mouseup 落在不同节点时 `click` 根本不触发）。

两次都是「读源码得到的推断」输给「实际渲染管线的时序」。**涉及 Obsidian 渲染顺序的结论，源码分析只能生成假设，必须点一遍。**
