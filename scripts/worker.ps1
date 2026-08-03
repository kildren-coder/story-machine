# worker.ps1 — story-machine 流水线执行器（阶段 0：音频 → 逐字稿 → 落 vault）
#
# 用法：
#   .\scripts\worker.ps1                 处理完队列里所有待办就退出（单发）
#   .\scripts\worker.ps1 -Watch          常驻，每 5 秒扫一次队列笔记
#   .\scripts\worker.ps1 -Reset EP02     把某一集打回「待下载」重跑
#
# 设计：**队列笔记是状态机，本脚本是执行器。**
#   状态全部落在 `_pipeline/队列.md` 的括号式 inline field 里，所以
#   （a）进度是白来的——Obsidian 检测到磁盘变更自动重载，Dataview 直接渲染；
#   （b）崩溃可续跑——worker 重启时把卡在「*中」的行打回对应的「待*」。
#
# 与 PC 的契约见 pc/smpc.py 顶部：跨 ssh 的参数一律纯 ASCII，中文只走文件。

[CmdletBinding()]
param(
    [string]$Vault = "D:\obsidian-task\任务栏\story-machine",
    [string]$Host5070 = "pc-5070",
    [switch]$Watch,
    [int]$PollSeconds = 5,
    [string]$Reset
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

# 插件用 child_process 捞 stdout，按 UTF-8 解码；不定死这里中文日志会变乱码
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8

$QueuePath = Join-Path $Vault "_pipeline\队列.md"
$AssetsDir = Join-Path $Vault "_assets"
$EpisodesDir = Join-Path $Vault "10-Episodes"
$RemoteStage = "E:/asr/staged"
$RemotePy = "C:\asr\venv\Scripts\python.exe"
$RemoteScript = "C:\asr\smpc.py"

# 阶段流转。键是「待办」，值是执行时的「进行中」标记与下一站。
$FLOW = [ordered]@{
    '待下载'   = @{ Busy = '下载中';   Next = '待转写' }
    '待转写'   = @{ Busy = '转写中';   Next = '待取回' }
    '待取回'   = @{ Busy = '取回中';   Next = '待建笔记' }
    '待建笔记' = @{ Busy = '建笔记中'; Next = '完成' }
}
$FIELD_ORDER = @('ep', '标题', '阶段', '进度', '时长', '更新', '备注', '错误')

# ---------------------------------------------------------------- 基础工具

function Write-Log {
    param([string]$Message, [string]$Color = 'Gray')
    Write-Host ("[{0}] {1}" -f (Get-Date -Format 'HH:mm:ss'), $Message) -ForegroundColor $Color
}

function Read-Utf8Lines {
    param([string]$Path)
    return [System.IO.File]::ReadAllLines($Path, [System.Text.UTF8Encoding]::new($false))
}

function Write-Utf8Lines {
    param([string]$Path, [string[]]$Lines)
    # 原子写：先落临时文件再替换，避免 Obsidian 读到写了一半的队列
    $tmp = "$Path.tmp"
    [System.IO.File]::WriteAllLines($tmp, $Lines, [System.Text.UTF8Encoding]::new($false))
    [System.IO.File]::Copy($tmp, $Path, $true)
    Remove-Item $tmp -Force -ErrorAction SilentlyContinue
}

function ConvertTo-Hms {
    param($Seconds)
    # 不能写 `$Seconds -eq ''`：PowerShell 把 '' 转成 0，于是 0 秒被判成空值，
    # 每集第一段（start=0）会渲染成空时间戳。
    if ($null -eq $Seconds) { return '' }
    if ($Seconds -is [string] -and $Seconds.Trim() -eq '') { return '' }
    $t = [TimeSpan]::FromSeconds([double]$Seconds)
    # [int] 在 PowerShell 里是四舍五入不是截断——[int]0.6 得 1，
    # 会把 00:36:00 显示成 01:36:00。渲染的 [HH:MM:SS] 要喂给时间戳跳播，
    # 错一个小时就是把人送到错误位置，必须 Floor。
    $h = [int][math]::Floor($t.TotalHours)
    return '{0:00}:{1:00}:{2:00}' -f $h, $t.Minutes, $t.Seconds
}

# ---------------------------------------------------------------- 队列读写

# 一行 = 一集。形如：
#   - https://... [ep:: EP02] [阶段:: 转写中] [进度:: 43%] [更新:: 17:02:11]
$ROW_RE = '^(?<indent>\s*)-\s+(?<url>https?://\S+)(?<rest>.*)$'
$FIELD_RE = '\[(?<k>[^\[\]:]+?)::\s*(?<v>[^\]]*)\]'

function Read-Queue {
    if (-not (Test-Path $QueuePath)) { return @() }
    $lines = Read-Utf8Lines $QueuePath
    $rows = @()
    for ($i = 0; $i -lt $lines.Count; $i++) {
        $m = [regex]::Match($lines[$i], $ROW_RE)
        if (-not $m.Success) { continue }
        $fields = [ordered]@{}
        foreach ($fm in [regex]::Matches($m.Groups['rest'].Value, $FIELD_RE)) {
            $fields[$fm.Groups['k'].Value.Trim()] = $fm.Groups['v'].Value.Trim()
        }
        $rows += [pscustomobject]@{
            LineNo = $i
            Indent = $m.Groups['indent'].Value
            Url    = $m.Groups['url'].Value
            Fields = $fields
        }
    }
    return , $rows
}

function Format-Row {
    param($Row)
    $parts = @("$($Row.Indent)- $($Row.Url)")
    $seen = @{}
    foreach ($k in $FIELD_ORDER) {
        if ($Row.Fields.Contains($k)) {
            $v = $Row.Fields[$k]
            if ($v -ne '') { $parts += "[$k`:: $v]" }
            $seen[$k] = $true
        }
    }
    foreach ($k in $Row.Fields.Keys) {           # 人手加的字段原样保留
        if ($seen.ContainsKey($k)) { continue }
        if ($Row.Fields[$k] -ne '') { $parts += "[$k`:: $($Row.Fields[$k])]" }
    }
    return ($parts -join ' ')
}

function Save-Row {
    param($Row)
    $Row.Fields['更新'] = Get-Date -Format 'HH:mm:ss'
    $lines = Read-Utf8Lines $QueuePath
    $lines[$Row.LineNo] = Format-Row $Row
    Write-Utf8Lines -Path $QueuePath -Lines $lines
}

function Get-NextEp {
    $used = @()
    if (Test-Path $EpisodesDir) {
        foreach ($f in Get-ChildItem $EpisodesDir -Filter '*.md' -File -ErrorAction SilentlyContinue) {
            if ($f.BaseName -match 'EP(\d+)') { $used += [int]$Matches[1] }
        }
    }
    foreach ($r in Read-Queue) {
        if ($r.Fields.Contains('ep') -and $r.Fields['ep'] -match 'EP(\d+)') { $used += [int]$Matches[1] }
    }
    $n = if ($used.Count) { ($used | Measure-Object -Maximum).Maximum + 1 } else { 1 }
    return 'EP{0:00}' -f $n
}

# ---------------------------------------------------------------- 远端调用

function Invoke-Remote {
    <#
      在 5070 上跑 smpc.py，逐行解析 ASCII 协议（PROGRESS / INFO / ERROR）。
      每收到进度就回写队列行，所以 Obsidian 侧能看到动。
    #>
    param(
        [string[]]$RemoteArgs,     # 不能叫 $Args——那是 PowerShell 的自动变量，会被静默吞掉
        $Row,
        [string]$Unit = 'pct'      # pct | sec
    )
    $remote = "$RemotePy $RemoteScript " + ($RemoteArgs -join ' ')
    Write-Log "  → ssh $Host5070 : $($RemoteArgs -join ' ')" DarkGray

    # ForEach-Object 的脚本块是子作用域，里面给变量赋值传不出来；
    # 改成改一个哈希表的字段——那是同一个对象，外面看得到。
    $st = @{ Err = $null; LastWrite = [datetime]::MinValue }

    # 原生命令的 stderr 经 2>&1 会变成 ErrorRecord，撞上 EAP=Stop 会直接中断，
    # 而 ssh 把正常日志写 stderr 是常态。这一段临时放宽。
    $prevEap = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        & ssh $Host5070 $remote 2>&1 | ForEach-Object {
            $line = "$_"
            if ($line -match '^PROGRESS\s+([\d.]+)\s+([\d.]+)') {
                $done = [double]$Matches[1]; $total = [double]$Matches[2]
                $pct = if ($total -gt 0) { [int](100 * $done / $total) } else { 0 }
                $text = if ($Unit -eq 'sec') {
                    '{0}% ({1}/{2})' -f $pct, (ConvertTo-Hms $done), (ConvertTo-Hms $total)
                } else { "$pct%" }
                $Row.Fields['进度'] = $text
                # 限流：进度写得太密会让 Obsidian 反复重载
                if (([datetime]::Now - $st.LastWrite).TotalSeconds -ge 2) {
                    $st.LastWrite = [datetime]::Now
                    Save-Row $Row
                    Write-Host "    $text" -ForegroundColor DarkCyan
                }
            }
            elseif ($line -match '^INFO\s+(.*)') { Write-Log "    $($Matches[1])" DarkGray }
            elseif ($line -match '^ERROR\s+(.*)') { $st.Err = $Matches[1] }
            elseif ($line.Trim()) { Write-Log "    $line" DarkGray }
        }
        $rc = $LASTEXITCODE
    }
    finally { $ErrorActionPreference = $prevEap }

    if ($rc -ne 0) {
        $msg = if ($st.Err) { $st.Err } else { "远端退出码 $rc" }
        throw $msg
    }
}

function Copy-FromPc {
    param([string]$RemoteFile, [string]$LocalPath)
    $null = New-Item -ItemType Directory -Force (Split-Path $LocalPath)
    $prevEap = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        $out = & scp -q "${Host5070}:$RemoteStage/$RemoteFile" $LocalPath 2>&1
        $rc = $LASTEXITCODE
    }
    finally { $ErrorActionPreference = $prevEap }
    if ($rc -ne 0) { throw "scp 取回失败（$RemoteFile）：$($out -join ' ')" }
    if (-not (Test-Path $LocalPath)) { throw "scp 报成功但本地没有文件：$LocalPath" }
}

# ---------------------------------------------------------------- 四个阶段

function Step-Download {
    param($Row)
    Invoke-Remote -RemoteArgs @('download', '--ep', $Row.Fields['ep'], '--url', "'$($Row.Url)'") -Row $Row -Unit pct

    # 元数据（含中文标题）走文件回来，不经 ssh stdout
    $ep = $Row.Fields['ep']
    $metaLocal = Join-Path $env:TEMP "$ep.meta.json"
    Copy-FromPc -RemoteFile "$ep.meta.json" -LocalPath $metaLocal
    $meta = Get-Content $metaLocal -Raw -Encoding utf8 | ConvertFrom-Json

    $Row.Fields['标题'] = $meta.title -replace '[\[\]]', ''     # 方括号会破坏 inline field
    if ($meta.duration_s) { $Row.Fields['时长'] = ConvertTo-Hms $meta.duration_s }
    if ($meta.parts_total -and $meta.parts_total -gt 1) {
        $p = if ($meta.part) { $meta.part } else { 1 }
        $Row.Fields['备注'] = "多P共$($meta.parts_total)个，本行只取 p=$p"
    }
    Write-Log "  ✓ 下载完成：$($meta.title)" Green
}

function Step-Transcribe {
    param($Row)
    Invoke-Remote -RemoteArgs @('transcribe', '--ep', $Row.Fields['ep']) -Row $Row -Unit sec
    Write-Log "  ✓ 转写完成" Green
}

function Step-Fetch {
    param($Row)
    $ep = $Row.Fields['ep']
    $null = New-Item -ItemType Directory -Force $AssetsDir

    Copy-FromPc -RemoteFile "$ep.transcript.json" -LocalPath (Join-Path $AssetsDir "$ep.transcript.json")
    Write-Log "  ✓ 逐字稿正本已落 _assets/" Green

    # 音频扩展名以 meta 为准（一般是 m4a）
    $metaLocal = Join-Path $env:TEMP "$ep.meta.json"
    if (-not (Test-Path $metaLocal)) { Copy-FromPc -RemoteFile "$ep.meta.json" -LocalPath $metaLocal }
    $meta = Get-Content $metaLocal -Raw -Encoding utf8 | ConvertFrom-Json
    $ext = [System.IO.Path]::GetExtension($meta.audio_file)
    if (-not $ext) { $ext = '.m4a' }

    $Row.Fields['进度'] = '音频传输中…'
    Save-Row $Row
    Copy-FromPc -RemoteFile "$ep$ext" -LocalPath (Join-Path $AssetsDir "$ep$ext")
    Copy-FromPc -RemoteFile "$ep.meta.json" -LocalPath (Join-Path $AssetsDir "$ep.meta.json")

    $mb = (Get-Item (Join-Path $AssetsDir "$ep$ext")).Length / 1MB
    Write-Log ("  ✓ 音频已落 _assets/ ({0:N1} MB)" -f $mb) Green
}

function Step-Scaffold {
    param($Row)
    $ep = $Row.Fields['ep']
    $null = New-Item -ItemType Directory -Force $EpisodesDir

    $tr = Get-Content (Join-Path $AssetsDir "$ep.transcript.json") -Raw -Encoding utf8 | ConvertFrom-Json
    $meta = Get-Content (Join-Path $AssetsDir "$ep.meta.json") -Raw -Encoding utf8 | ConvertFrom-Json

    # 可读渲染（派生件，随时可从正本重生成）
    $render = foreach ($s in $tr.segments) {
        $spk = if ($s.speaker) { "$($s.speaker): " } else { '' }
        "[{0}] {1}{2}" -f (ConvertTo-Hms $s.start), $spk, $s.text.Trim()
    }
    Write-Utf8Lines -Path (Join-Path $AssetsDir "$ep.txt") -Lines $render

    # ConvertFrom-Json 会把 ISO 8601 字符串自动转成 DateTime，再插值就成了美式 locale
    $tsAt = if ($tr.transcribed_at -is [datetime]) {
        $tr.transcribed_at.ToString('yyyy-MM-ddTHH:mm:ss')
    } else { "$($tr.transcribed_at)" }

    $title = $Row.Fields['标题']
    $airDate = ''
    if ($meta.upload_date -and "$($meta.upload_date)" -match '^(\d{4})(\d{2})(\d{2})$') {
        $airDate = "$($Matches[1])-$($Matches[2])-$($Matches[3])"
    }
    $ext = [System.IO.Path]::GetExtension($meta.audio_file); if (-not $ext) { $ext = '.m4a' }

    # 文件名里的标题要去掉 Windows 非法字符
    $safe = $title -replace '[\\/:*?"<>|]', '·'
    $notePath = Join-Path $EpisodesDir "$ep $safe.md"

    if (Test-Path $notePath) {
        Write-Log "  ! EP 笔记已存在，跳过不覆盖：$([System.IO.Path]::GetFileName($notePath))" Yellow
        return
    }

    # frontmatter 里的 `音频:` 是时间戳跳播插件的绑定前提（ADR 0001），不能省。
    $note = @(
        '---'
        'type: episode'
        "episode: $ep"
        "title: $title"
        "音频: $ep$ext"
        "播出日期: $airDate"
        '主播: []'
        "transcript: ../_assets/$ep.transcript.json"
        "逐字稿渲染: ../_assets/$ep.txt"
        "时长: $($Row.Fields['时长'])"
        "来源: $($meta.url)"
        "转写引擎: $($tr.engine)"
        "说话人分离: $($tr.diarization)"
        "转写时间: $tsAt"
        '---'
        ''
        "# $ep $title"
        ''
        '> [!warning] 本笔记是容器，不是阅读面。'
        '> 断言行由阶段 2 抽取、阶段 3 人工审核后落到下面。**现在是空的，这是正常的。**'
        '> 逐字稿正本在 `_assets/`，永不要求通读。'
        ''
        '## 断言'
        ''
        '## 待办'
        ''
        '- [ ] 主播点名（把 frontmatter 的 `主播:` 填上）'
        '- [ ] 核对 `播出日期`——这里填的是**投稿日期**，直播日期常常早一天'
        '- [ ] 阶段 2 抽取 → `_review/`'
        ''
    )
    Write-Utf8Lines -Path $notePath -Lines $note
    Write-Log "  ✓ EP 笔记已建：$([System.IO.Path]::GetFileName($notePath))" Green
}

$STEPS = @{
    '待下载'   = ${function:Step-Download}
    '待转写'   = ${function:Step-Transcribe}
    '待取回'   = ${function:Step-Fetch}
    '待建笔记' = ${function:Step-Scaffold}
}

# ---------------------------------------------------------------- 主循环

function Initialize-Queue {
    <# 新粘的裸链接补上 ep 和阶段；卡在「*中」的行打回重跑（崩溃续跑）。#>
    $changed = $false
    foreach ($row in Read-Queue) {
        $stage = if ($row.Fields.Contains('阶段')) { $row.Fields['阶段'] } else { '' }
        if (-not $row.Fields.Contains('ep') -or $row.Fields['ep'] -eq '') {
            $row.Fields['ep'] = Get-NextEp
            $changed = $true
        }
        if ($stage -eq '') {
            $row.Fields['阶段'] = '待下载'
            Write-Log "入队 $($row.Fields['ep'])：$($row.Url)" Cyan
            $changed = $true
        }
        elseif ($stage -like '*中') {
            $back = ($FLOW.Keys | Where-Object { $FLOW[$_].Busy -eq $stage })
            if ($back) {
                $row.Fields['阶段'] = $back
                $row.Fields['进度'] = ''
                Write-Log "$($row.Fields['ep']) 上次中断在「$stage」，打回「$back」重跑" Yellow
                $changed = $true
            }
        }
        if ($changed) { Save-Row $row; $changed = $false }
    }
}

function Invoke-QueuePass {
    <# 扫一遍队列，推进第一个有待办的行。返回是否做了事。#>
    Initialize-Queue
    foreach ($row in Read-Queue) {
        if (-not $row.Fields.Contains('阶段')) { continue }
        $stage = $row.Fields['阶段']
        if (-not $FLOW.Contains($stage)) { continue }     # 完成 / 失败 / 人手改的值

        $ep = $row.Fields['ep']
        $busy = $FLOW[$stage].Busy
        Write-Log "$ep $stage → $busy" Cyan

        $row.Fields['阶段'] = $busy
        $row.Fields['错误'] = ''
        $row.Fields['进度'] = ''
        Save-Row $row
        try {
            & $STEPS[$stage] $row
            $row.Fields['阶段'] = $FLOW[$stage].Next
            $row.Fields['进度'] = ''
            Save-Row $row
            if ($row.Fields['阶段'] -eq '完成') {
                Write-Log "$ep 全流程完成 ✓" Green
            }
        }
        catch {
            $row.Fields['阶段'] = '失败'
            $row.Fields['进度'] = ''
            $row.Fields['错误'] = ("$_" -replace '[\[\]\r\n]', ' ').Trim()
            Save-Row $row
            Write-Log "$ep 在「$stage」失败：$_" Red
            Write-Log "  改回 [阶段:: $stage] 保存即可重试；或 .\scripts\worker.ps1 -Reset $ep" DarkYellow
        }
        return $true
    }
    return $false
}

# ---------------------------------------------------------------- 入口

if (-not (Test-Path $Vault)) { throw "vault 目录不存在：$Vault" }
if (-not (Test-Path $QueuePath)) {
    throw "队列笔记不存在：$QueuePath`n先跑 .\scripts\setup-pipeline.ps1 初始化"
}

if ($Reset) {
    foreach ($row in Read-Queue) {
        if ($row.Fields.Contains('ep') -and $row.Fields['ep'] -eq $Reset) {
            $row.Fields['阶段'] = '待下载'
            $row.Fields['进度'] = ''
            $row.Fields['错误'] = ''
            Save-Row $row
            Write-Log "$Reset 已重置为「待下载」" Green
            exit 0
        }
    }
    throw "队列里没有 $Reset"
}

Write-Log "队列：$QueuePath" DarkGray
if ($Watch) {
    Write-Log "常驻模式，每 $PollSeconds 秒扫一次。Ctrl+C 退出。" Cyan
    while ($true) {
        try { while (Invoke-QueuePass) { } }
        catch { Write-Log "扫描出错：$_" Red }
        Start-Sleep -Seconds $PollSeconds
    }
}
else {
    $did = $false
    while (Invoke-QueuePass) { $did = $true }
    if (-not $did) { Write-Log "队列里没有待办。" DarkGray }
}
