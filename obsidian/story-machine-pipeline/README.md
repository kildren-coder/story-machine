# story-machine-pipeline

Obsidian 里的流水线控制台：粘链接 → 入队 → 点「运行」，看着一集从**下载**走到**转写**、**说话人分离**、**取回**、**建 EP 笔记**。

## 设计：队列笔记是唯一状态

本插件**不持有任何进度状态**。它只做两件事：把队列文件渲染成面板，以及把 worker 拉起来。

```
你 ──粘链接──► _pipeline/队列.md ◄──改写──┐
                     │                    │
                  插件渲染               worker.ps1
                     │                    │
                     ▼                    └── ssh ──► 5070 主机
                  控制台面板
```

进度因此是**白来的**：worker 每完成一步就改写队列文件，Obsidian 检测到磁盘变更触发 `vault.on("modify")`，面板重画。插件和 worker 之间不需要任何进程间通道——面板下方的日志窗只是排障用的副产物，关掉也不影响状态正确。

这条设计还顺带给了两个性质：

- **崩溃可续跑。** 状态在文件里，不在内存里。worker 被杀、Obsidian 关掉、机器重启都一样——下次运行时把卡在「\*中」的行打回对应的「待\*」重跑。
- **不装插件也能用。** 直接在队列笔记里敲 `- <链接>`，然后终端跑 `.\scripts\worker.ps1`，效果完全相同。插件是便利层，不是必需层。

## 为什么和 story-machine-timestamps 分成两个插件

这里要 `require('child_process')` 拉子进程，必须标 `isDesktopOnly: true`。时间戳插件是纯渲染、零 Node 依赖，没必要跟着降级成桌面独占。两个插件由 `scripts/setup-pipeline.ps1` 一起部署，安装成本还是一步。

## 用法

笔记里放一个代码块：

````markdown
```sm-pipeline
队列: story-machine/_pipeline/队列.md
worker: D:\code\story-machine\scripts\worker.ps1
```
````

| 配置键 | 说明 |
| --- | --- |
| `队列` | 队列笔记路径，**相对 vault 根**（不是相对本笔记） |
| `worker` | `worker.ps1` 的绝对路径 |
| `pwsh` | 可选，默认 `powershell.exe`；想用 PS7 就写 `pwsh.exe` |

`-Vault` 参数不用配——插件从队列路径的爷爷目录推出来（`<vault>/story-machine/_pipeline/队列.md` → `<vault>/story-machine`）。

面板上：输入框回车或点「＋ 入队」追加一行裸链接；「▶ 运行」拉起 worker（运行中变成「■ 停止」）；失败的行会多一个「重试」按钮。

**入队的契约刻意做薄**：插件只追加 `- <链接>`，`ep` 编号和 `阶段` 都由 worker 补。这样插件和 worker 不会为了抢着写同一批字段而打架。

## 队列行长什么样

```markdown
- https://www.bilibili.com/video/BVxxx [ep:: EP01] [标题:: …] [阶段:: 转写中] [进度:: 43% (01:01:20/02:21:25)] [时长:: 02:21:25] [更新:: 20:58:12]
```

括号式 inline field 是 `proto/dataview-rowlevel` 那轮验证过的写法（续行式不成立），所以队列可以直接被 Dataview 查询——控制台笔记里的「进度总览」表就是这么来的。

阶段取值：`待下载 → 下载中 → 待转写 → 转写中 → 待分离 → 分离中 → 待取回 → 取回中 → 待建笔记 → 建笔记中 → 完成`，外加终态 `失败`。手工把 `阶段` 改回任意一个「待\*」就能从那一步重跑。

## 排障

| 症状 | 多半是 |
| --- | --- |
| 点「运行」弹「spawn 失败」 | `worker:` 路径写错，或该路径不存在 |
| 面板说「找不到队列笔记」 | `队列:` 写成了相对本笔记的路径。要写相对 vault 根的 |
| 日志里中文乱码 | worker.ps1 顶部的 `[Console]::OutputEncoding` 被改掉了 |
| 表格不动但日志在滚 | Dataview 表要等文件变更；面板本身是实时的，以面板为准 |
