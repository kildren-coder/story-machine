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
    '粘链接 → 入队 → 运行。一集要走四步：**下载 → 转写 → 取回 → 建 EP 笔记**。'
    ''
    '```sm-pipeline'
    '队列: story-machine/_pipeline/队列.md'
    "worker: $workerPath"
    '```'
    ''
    '## 进度总览'
    ''
    '```dataview'
    'TABLE WITHOUT ID L.ep AS "集", L.标题 AS "标题", L.阶段 AS "阶段", L.进度 AS "进度", L.更新 AS "更新", L.错误 AS "错误"'
    'FROM "story-machine/_pipeline"'
    'FLATTEN file.lists AS L'
    'WHERE L.ep'
    'SORT L.ep ASC'
    '```'
    ''
    '## 已入库'
    ''
    '```dataview'
    'TABLE WITHOUT ID file.link AS "EP 笔记", 时长, 播出日期, 说话人分离'
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
