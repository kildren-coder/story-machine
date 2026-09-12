# setup-pipeline.ps1 — 一次性装配：vault 目录 + 控制台/队列笔记 + PC 侧脚本 + 两个插件
#
# 用法：
#   .\scripts\setup-pipeline.ps1              全装
#   .\scripts\setup-pipeline.ps1 -SkipPc      不动 5070（离线时）
#   .\scripts\setup-pipeline.ps1 -Force       覆盖已存在的控制台/队列笔记
#
# 幂等：目录已在就跳过；笔记已在就不覆盖（除非 -Force）；插件文件总是覆盖为仓库最新版。

[CmdletBinding()]
param(
    [string]$Vault = "D:\obsidian-task\任务栏\story-machine",
    [string]$ObsidianConfig = "D:\obsidian-task\任务栏\.obsidian",
    [string]$Host5070 = "pc-5070",
    [switch]$SkipPc,
    [switch]$SkipPlugins,
    [switch]$Force
)

$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$Repo = Split-Path $PSScriptRoot -Parent
$Utf8NoBom = [System.Text.UTF8Encoding]::new($false)

function Say { param($m, $c = 'Gray') Write-Host "  $m" -ForegroundColor $c }
function Step { param($m) Write-Host "`n$m" -ForegroundColor Cyan }

function Write-NoteIfAbsent {
    param([string]$Path, [string[]]$Lines)
    $name = Split-Path $Path -Leaf
    if ((Test-Path $Path) -and -not $Force) { Say "已存在，跳过：$name" DarkGray; return }
    $null = New-Item -ItemType Directory -Force (Split-Path $Path)
    [System.IO.File]::WriteAllLines($Path, $Lines, $Utf8NoBom)
    Say "已写入：$name" Green
}

# ---------------------------------------------------------------- vault 结构

Step "1/4  vault 目录（SPEC §6）"
foreach ($d in '_pipeline', '_assets', '10-Episodes', '15-Materials', '30-Threads',
    '_review', '_pairs', '_queries', '_index') {
    $p = Join-Path $Vault $d
    if (Test-Path $p) { Say "已在：$d" DarkGray }
    else { $null = New-Item -ItemType Directory -Force $p; Say "已建：$d" Green }
}

Step "2/4  控制台与队列笔记"

Write-NoteIfAbsent -Path (Join-Path $Vault "_pipeline\队列.md") -Lines @(
    '---'
    'type: pipeline-queue'
    '---'
    ''
    '> [!info] 这个文件由 worker 改写，是流水线的**唯一状态**。'
    '> 手动加集：新起一行 `- <链接>` 保存即可，`ep` 和 `阶段` worker 会补上。'
    '> 想重跑某一集：把它的 `[阶段:: …]` 改回 `待下载`（或用 `-Reset EP02`）。'
    ''
    '## 队列'
    ''
)

$workerPath = Join-Path $Repo "scripts\worker.ps1"
Write-NoteIfAbsent -Path (Join-Path $Vault "_pipeline\控制台.md") -Lines @(
    '---'
    'type: pipeline-console'
    '---'
    ''
    '# 流水线控制台'
    ''
    '粘链接 → 入队 → 运行。'
    ''
    '「运行」跑的是**阶段 0**，五步：下载 → 转写 → 说话人分离 → 取回 → 建 EP 笔记。'
    '走完显示「阶段 0 完成」，**不是这一集完事了**——后面还有点名、抽取、审核，'
    '每行下面的「下一步」会写明该干什么并链到那一集的笔记，状态条在笔记顶上。'
    ''
    '```sm-pipeline'
    '队列: story-machine/_pipeline/队列.md'
    "worker: $workerPath"
    '```'
    ''
    '## 进度总览'
    ''
    '一行一集，显示**全流程**位置——不只是阶段 0。各阶段的含义见页底「阶段说明」。'
    ''
    '```dataviewjs'
    '// 两个来源拼成一行：'
    '//   阶段 0 还在跑的 → 队列笔记（worker 的状态机，流水线的唯一状态）'
    '//   阶段 0 跑完的   → EP 笔记（`人物` 里还剩几个「未知N」，就是还欠几个点名）'
    '// 这里**不引入第三份状态**：全部现算，没有需要维护、会跟事实脱节的缓存字段。'
    '// 注意「填了名字但还没入库」这一档在这张表上看不出来（要 worker 跑过才算数），'
    '// 它只在 EP 笔记顶上的状态条里实时显示——那边是现读正文推的。'
    'const ROOT = "story-machine";'
    ''
    'const notes = new Map();'
    'for (const p of dv.pages(`"${ROOT}/10-Episodes"`).where((p) => p.episode)) {'
    '  notes.set(String(p.episode), p);'
    '}'
    'const reviews = dv.pages(`"${ROOT}/_review"`).map((p) => p.file.name).array();'
    ''
    'const seen = new Set();'
    'const items = [];'
    ''
    'for (const l of dv.pages(`"${ROOT}/_pipeline"`).file.lists.where((x) => x["ep"])) {'
    '  const ep = String(l["ep"]);'
    '  const stage = String(l["阶段"] ?? "");'
    '  const note = notes.get(ep);'
    '  seen.add(ep);'
    ''
    '  let now = "", detail = "";'
    '  if (stage !== "完成") {'
    '    // 阶段 0 内部：下载 / 转写 / 分离 / 取回 / 建笔记'
    '    now = "阶段 0 · " + (stage || "未入队");'
    '    detail = String(l["进度"] ?? "");'
    '  } else if (!note) {'
    '    now = "⚠ 阶段 0 完成，却找不到 EP 笔记";'
    '  } else {'
    '    const unknown = dv.array(note["人物"] ?? []).array()'
    '      .filter((x) => String(x).startsWith("未知")).length;'
    '    if (unknown) {'
    '      now = "点名";'
    '      detail = `还剩 ${unknown} 位没点名`;'
    '    } else {'
    '      const drafts = reviews.filter((n) => n.startsWith(ep + "-")).length;'
    '      if (drafts) {'
    '        now = "阶段 3 审核";'
    '        detail = `\`_review/\` 里有 ${drafts} 篇草稿等你审`;'
    '      } else {'
    '        now = "阶段 1–2 抽取";'
    '        detail = "去 EP 笔记顶上点「▶ 阶段 1–2 抽取」";'
    '      }'
    '    }'
    '  }'
    ''
    '  items.push({'
    '    ep,'
    '    link: note ? note.file.link : ep,'
    '    title: String(l["标题"] ?? ""),'
    '    now, detail,'
    '    err: String(l["错误"] ?? ""),'
    '    at: String(l["更新"] ?? ""),'
    '  });'
    '}'
    ''
    '// 手建、没进过队列的 EP 笔记也要露面，否则它们会从总览里凭空消失'
    'for (const [ep, p] of notes) {'
    '  if (seen.has(ep)) continue;'
    '  items.push({'
    '    ep, link: p.file.link, title: String(p.title ?? ""),'
    '    now: "不在队列里", detail: "手建的笔记？", err: "", at: "",'
    '  });'
    '}'
    ''
    'items.sort((a, b) => a.ep.localeCompare(b.ep));'
    'dv.table('
    '  ["集", "标题", "现在在哪", "详情", "错误", "更新"],'
    '  items.map((i) => [i.link, i.title, i.now, i.detail, i.err, i.at])'
    ');'
    '```'
    ''
    '## 已入库'
    ''
    '```dataview'
    'TABLE WITHOUT ID file.link AS "EP 笔记", 时长, 播出日期, 人物, 说话人分离'
    'FROM "story-machine/10-Episodes"'
    'WHERE type = "episode"'
    'SORT episode DESC'
    '```'
    ''
    '## 排障'
    ''
    '| 症状 | 处理 |'
    '| --- | --- |'
    '| 点「运行」没反应 | 展开面板下方日志看 `[spawn 失败]`；多半是 `worker:` 路径写错 |'
    '| 卡在「转写中」很久 | 3 小时音频约 4–5 分钟（43x 实时），首次还要加载模型；日志有 `PROGRESS` 就是在跑 |'
    '| 某集「失败」 | 面板上点「重试」，或看 `错误` 字段。改回 `[阶段:: 待下载]` 也能重跑 |'
    '| worker 中途被杀 | 下次运行会把「*中」自动打回「待*」重跑，不用手动收拾 |'
    '| EP 笔记顶上没有状态条 | 跑一次 worker（点「运行」即可）会补上；插件刚更新过的话要先重启 Obsidian |'
    '| 填了名字但表里还显示「没点名」 | 这张表要 worker 跑过才更新。EP 笔记顶上的状态条是实时的，以它为准 |'
    '| 点了抽取，半天没动静 | 正常：opus + high effort，一块 3–5 分钟，中间没有中间输出。日志出现「块A 调用 claude」就是在跑 |'
    '| 抽取失败 | 看日志。整块 schema 不合法会自动重跑 2 次，仍不过就落 `_failed/`——**块没丢**，改完 prompt 重点一次即可 |'
    '| 想重看某条断言怎么来的 | `_pairs/EP{n}/{块}.chunk.md` 是喂进去的原样输入，`{块}.raw.json` 是模型原话 |'
    ''
    '## 阶段说明'
    ''
    'SPEC §4 的全流程。**队列里的 `[阶段:: 完成]` 只表示阶段 0 完成**，不是这一集完事了。'
    ''
    '| 阶段 | 做什么 | 实现了吗 | 你要做什么 |'
    '| --- | --- | --- | --- |'
    '| **阶段 0** 转写 | 下载 → 转写 → 说话人分离 → 取回 → 建 EP 笔记。上面「运行」跑的就是它 | ✅ | 粘链接、点运行；失败了点「重试」 |'
    '| **点名** | 声纹库认不出的说话人显示「未知N」。人填一次名字入库，往后各集自动认出来 | ✅ | 在 EP 笔记「这集都有谁」里填行尾方括号，再点状态条上的「✓ 入库」 |'
    '| **阶段 1–2** 抽取 | 逐字稿切块（20–30 分钟／块，重叠 1–2 分钟）→ 无头 Claude Code 抽断言行 → 过三闸门 → 落 `_review/` | ✅ 只抽 `channel` | 在 EP 笔记顶上点「▶ 阶段 1–2 抽取」。一块几分钟，走订阅额度 |'
    '| **阶段 3** 审核 | 改 `type`／`情态`、删幻觉行、存疑打 `?`、裁决建议合并。审完把文件挪出 `_review/` 即为通过 | 草稿有了，动线还没做 | **这是你唯一该花时间的地方**（红线：永不要求通读逐字稿）。现在就是直接打开 `_review/` 里的草稿改 |'
    '| **阶段 4** 落库 | 断言行汇进 EP 笔记的「## 断言」；另出一份按主题分段的精简材料 | ❌ 未实现 | — |'
    '| **阶段 5** 脉络 | 读精简材料 + 查总库，手写脉络笔记 | 人做，**永不自动化** | 写 |'
    ''
    '> **阶段 1 和阶段 2 在界面上合成一格**：分块没有独立产物，也没有独立的人工动作——它只是抽取那一次调用的输入预处理，切完立刻就喂进去了。SPEC 分两个编号是为了把参数讲清楚。'
    '>'
    '> **本版只抽 `channel`**（他让你去哪查、该看谁），五类断言里的其余四类还不抽——SPEC §10 优先级第 3 条。所以草稿里没有 `fact`／`causal` 也是对的，不是漏了。'
    '>'
    '> 每块留下三份东西：`_review/EP{n}-{块}.draft.md` 是给你审的；`_pairs/EP{n}/{块}.chunk.md` 是喂给模型的**原样输入**；`{块}.raw.json` 是模型的原始响应。后两份让「这条是怎么来的」永远可复查，也让改渲染不用重新烧额度（`--replay`）。'
    '>'
    '> 闸门没过的条目**不会被丢掉**，它带着一条「闸门没过」的提示照样进草稿，由你处置。整块 schema 不合法才会重跑，重跑几次还不行就落 `_failed/` 报警——**绝不静默丢块**。'
    '>'
    '> 草稿是**散文体**，不是 `[key:: value]` 那种行内字段——那套写法是给 EP 笔记（容器）用的，为的是 Dataview 跨集查询必须挤在同一行。草稿是你唯一要看的界面，转成行内字段是阶段 4 落库时才做的事。草稿里的时间戳可以直接点着跳播。'
    ''
)

# ---------------------------------------------------------------- PC 侧

Step "3/4  5070 主机"
if ($SkipPc) { Say "跳过（-SkipPc）" DarkGray }
else {
    Say "连通性检查…"
    $probe = & ssh $Host5070 "Write-Output ok" 2>&1
    if ($LASTEXITCODE -ne 0) { throw "ssh $Host5070 连不上：$probe" }

    & ssh $Host5070 "New-Item -ItemType Directory -Force E:\asr\staged | Out-Null"
    if ($LASTEXITCODE -ne 0) { throw "无法创建 E:\asr\staged" }
    Say "E:\asr\staged 就绪" Green

    & scp -q (Join-Path $Repo "pc\smpc.py") "${Host5070}:C:/asr/smpc.py"
    if ($LASTEXITCODE -ne 0) { throw "smpc.py 上传失败" }
    Say "C:\asr\smpc.py 已更新" Green

    $ver = & ssh $Host5070 "C:\asr\venv\Scripts\python.exe -c `"import faster_whisper,sys;print('fw',faster_whisper.__version__)`"" 2>&1
    Say "转写环境：$ver" Green
    $yt = & ssh $Host5070 "if (Test-Path C:\asr\venv\Scripts\yt-dlp.exe) { 'yt-dlp ok' } else { 'yt-dlp MISSING' }" 2>&1
    Say "下载工具：$yt" $(if ("$yt" -match 'MISSING') { 'Red' } else { 'Green' })
}

# ---------------------------------------------------------------- 插件

Step "4/4  Obsidian 插件"
if ($SkipPlugins) { Say "跳过（-SkipPlugins）" DarkGray }
else {
    $pluginRoot = Join-Path $ObsidianConfig "plugins"
    foreach ($id in 'story-machine-timestamps', 'story-machine-pipeline') {
        $src = Join-Path $Repo "obsidian\$id"
        if (-not (Test-Path $src)) { Say "仓库里没有 $id，跳过" Yellow; continue }
        $dst = Join-Path $pluginRoot $id
        $null = New-Item -ItemType Directory -Force $dst
        Copy-Item (Join-Path $src 'manifest.json'), (Join-Path $src 'main.js'), (Join-Path $src 'styles.css') $dst -Force
        Say "已部署：$id" Green
    }

    # 登记进 community-plugins.json（保留已启用的其他插件）
    $cpPath = Join-Path $ObsidianConfig "community-plugins.json"
    $enabled = if (Test-Path $cpPath) { @(Get-Content $cpPath -Raw -Encoding utf8 | ConvertFrom-Json) } else { @() }
    $before = $enabled.Count
    foreach ($id in 'story-machine-timestamps', 'story-machine-pipeline') {
        if ($enabled -notcontains $id) { $enabled += $id }
    }
    if ($enabled.Count -ne $before) {
        [System.IO.File]::WriteAllText($cpPath, ($enabled | ConvertTo-Json -AsArray), $Utf8NoBom)
        Say "community-plugins.json 已登记（需重启 Obsidian）" Yellow
    }
    else { Say "community-plugins.json 已是最新" DarkGray }
}

Write-Host "`n装配完成。" -ForegroundColor Green
Write-Host "下一步：重启 Obsidian → 打开 " -NoNewline
Write-Host "story-machine/_pipeline/控制台.md" -ForegroundColor Cyan -NoNewline
Write-Host " → 粘链接 → 点「运行」"
