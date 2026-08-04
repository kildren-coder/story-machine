# worker.ps1 — story-machine 流水线执行器（阶段 0：音频 → 逐字稿 → 落 vault）
#
# 用法：
#   .\scripts\worker.ps1                 处理完队列里所有待办就退出（单发）
#   .\scripts\worker.ps1 -Watch          常驻，每 5 秒扫一次队列笔记
#   .\scripts\worker.ps1 -Reset EP02     把某一集打回「待下载」重跑
#   .\scripts\worker.ps1 -Name EP02      只跑这一集的点名回填（不碰队列）
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
    [string]$Reset,
    [string]$Name          # 只跑某一集的点名回填，不碰队列
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
# 说话人分离要 torch，转写 venv 必须保持无 torch（SPEC 阶段0：独立 venv、纯 CPU）
$RemoteDiarPy = "C:\asr\venv-diar\Scripts\python.exe"
$RemoteDiarScript = "C:\asr\smdiar.py"
# 声纹比对在本机跑：质心随 EP{n}.diar.json 回来了，只要 numpy
$LocalPy = "python"
$SpeakersScript = Join-Path (Split-Path $PSScriptRoot -Parent) "pc\speakers.py"

# 阶段流转。键是「待办」，值是执行时的「进行中」标记与下一站。
$FLOW = [ordered]@{
    '待下载'   = @{ Busy = '下载中';   Next = '待转写' }
    '待转写'   = @{ Busy = '转写中';   Next = '待分离' }
    '待分离'   = @{ Busy = '分离中';   Next = '待取回' }
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
    # 调用方一律 @(Read-Utf8Lines ...)：函数返回单元素数组时 PowerShell 会把它
    # 拆成裸字符串，$lines.Count 于是在 StrictMode 下报「属性不存在」。
    # 跟 Read-Queue 那个是同一个坑（见其注释），只有一行的文件才踩得到。
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
    $lines = @(Read-Utf8Lines $QueuePath)
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
    # 这里**不能**写 `return , $rows`。那个逗号本意是防止单行队列被拆成裸对象，
    # 但裸函数名调用（`foreach ($row in Read-Queue)`，不加括号）不会把它拆开：
    #   0 行  → $row 是空 Object[]，$row.Fields 在 StrictMode 下报「属性不存在」
    #   1 行  → $row 是 Object[1]，$row.Fields 成员枚举后恰好解包成字典，**碰巧能跑**
    #   2 行+ → $row 是 Object[2]，$row.Fields 成员枚举成 Object[]，
    #           $row.Fields['ep'] 于是变成 [int]'ep' → 抛类型转换异常
    # 队列长期只有一行，这个巧合把 bug 藏到了第二集入队才炸。
    # 正确做法：直接返回，调用方一律 @(Read-Queue)，0/1/多 三种情况都兜得住。
    return $rows
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
    $lines = @(Read-Utf8Lines $QueuePath)
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
    foreach ($r in @(Read-Queue)) {
        if ($r.Fields.Contains('ep') -and $r.Fields['ep'] -match 'EP(\d+)') { $used += [int]$Matches[1] }
    }
    $n = if ($used.Count) { ($used | Measure-Object -Maximum).Maximum + 1 } else { 1 }
    return 'EP{0:00}' -f $n
}

# ---------------------------------------------------------------- 远端调用

function Invoke-Remote {
    <#
      在 5070 上跑 smpc.py / smdiar.py，逐行解析 ASCII 协议（PROGRESS / INFO / ERROR）。
      每收到进度就回写队列行，所以 Obsidian 侧能看到动。
    #>
    param(
        [string[]]$RemoteArgs,     # 不能叫 $Args——那是 PowerShell 的自动变量，会被静默吞掉
        $Row,
        [string]$Unit = 'pct',     # pct | sec
        [string]$Py = $RemotePy,   # 分离步走另一个 venv
        [string]$Script = $RemoteScript
    )
    $remote = "$Py $Script " + ($RemoteArgs -join ' ')
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

function Step-Diarize {
    param($Row)
    Invoke-Remote -RemoteArgs @('--ep', $Row.Fields['ep']) -Row $Row -Unit pct `
        -Py $RemoteDiarPy -Script $RemoteDiarScript
    Write-Log "  ✓ 说话人分离完成" Green
}

function Step-Fetch {
    param($Row)
    $ep = $Row.Fields['ep']
    $null = New-Item -ItemType Directory -Force $AssetsDir

    Copy-FromPc -RemoteFile "$ep.transcript.json" -LocalPath (Join-Path $AssetsDir "$ep.transcript.json")
    Write-Log "  ✓ 逐字稿正本已落 _assets/" Green
    # 窗口级分离明细，抽查某一段归属存疑时看它
    Copy-FromPc -RemoteFile "$ep.diar.json" -LocalPath (Join-Path $AssetsDir "$ep.diar.json")
    # 分离前的逐字稿 + 词级时间戳。留着才能机械核对「分离只改了分段和 speaker，
    # 一个字没动」——「ASR 只听写」这条红线要能被查，就得有个 before 和一份词表。
    # 见 pc/check_diar.py。
    Copy-FromPc -RemoteFile "$ep.transcript.nodiar.json" -LocalPath (Join-Path $AssetsDir "$ep.transcript.nodiar.json")
    Copy-FromPc -RemoteFile "$ep.words.json" -LocalPath (Join-Path $AssetsDir "$ep.words.json")

    # 音频扩展名以 meta 为准（一般是 m4a）
    $metaLocal = Join-Path $env:TEMP "$ep.meta.json"
    if (-not (Test-Path $metaLocal)) { Copy-FromPc -RemoteFile "$ep.meta.json" -LocalPath $metaLocal }
    $meta = Get-Content $metaLocal -Raw -Encoding utf8 | ConvertFrom-Json
    $ext = [System.IO.Path]::GetExtension($meta.audio_file)
    if (-not $ext) { $ext = '.m4a' }

    # 音频是一次性产物：EP 与 B 站稿件一一对应，不会变。重跑分离后再取回时
    # 没必要再拉一遍 100MB，只在本地缺失或字节数对不上（上次传一半断了）时才拷。
    $audioLocal = Join-Path $AssetsDir "$ep$ext"
    $haveAudio = (Test-Path $audioLocal) -and $meta.audio_bytes -and
                 ((Get-Item $audioLocal).Length -eq $meta.audio_bytes)
    if ($haveAudio) {
        Write-Log "  · 音频本地已完整，跳过传输" DarkGray
    }
    else {
        $Row.Fields['进度'] = '音频传输中…'
        Save-Row $Row
        Copy-FromPc -RemoteFile "$ep$ext" -LocalPath $audioLocal
    }
    Copy-FromPc -RemoteFile "$ep.meta.json" -LocalPath (Join-Path $AssetsDir "$ep.meta.json")

    $mb = (Get-Item $audioLocal).Length / 1MB
    Write-Log ("  ✓ 音频已落 _assets/ ({0:N1} MB)" -f $mb) Green
}

# 点名要快，人才会真去点。所以笔记里给一张说话人小表：各自说了多久、占比多少、
# 第一次出现在哪。那个时间戳会被 story-machine-timestamps 变成跳播按钮（ADR 0001），
# 于是「这是谁」只要点一下听两句就有答案，不用去逐字稿里翻。
# 用注释标记围起来，是为了补跑分离后能原地重写而不碰人写的任何东西。
#
# 认得出来的由声纹库直接填好（pc/speakers.py）；认不出来的显示「未知N」，
# 行尾留一个 `[SPEAKER_XX:: ]` 空位给人填。填完 worker 下一轮入库，往后自动认。
# 认对了的也把名字留在方括号里——那是更正入口：改一个字就是一次重新入库。
$SpkBegin = '<!-- speakers:auto -->'
$SpkEnd = '<!-- /speakers -->'
$SPK_FIELD_RE = '\[(SPEAKER_\d+)::\s*([^\]]*)\]'

function Read-SpeakerNames {
    param([string[]]$Lines)
    $names = @{}
    foreach ($l in $Lines) {
        foreach ($m in [regex]::Matches($l, $SPK_FIELD_RE)) {
            $v = $m.Groups[2].Value.Trim()
            if ($v -ne '') { $names[$m.Groups[1].Value] = $v }
        }
    }
    return $names
}

function Resolve-Speakers {
    <# 跑 pc\speakers.py：先把人填的名字入库，再给每个簇一个归属。#>
    param([string]$Ep, $Names)
    $diarPath = Join-Path $AssetsDir "$Ep.diar.json"
    if (-not (Test-Path $diarPath)) { return $null }
    # 声纹库之前分离的集数没有质心。这不是错误，是这一集还没重跑分离——
    # 当成「没这一集」跳过，别每轮抛一次异常刷屏。
    if ((Get-Content $diarPath -Raw -Encoding utf8 | ConvertFrom-Json).PSObject.Properties.Name -notcontains 'centroids') {
        Write-Log "  · $Ep.diar.json 里没有声纹质心（分离于声纹库之前），跳过点名；重跑一次分离即可" DarkGray
        return $null
    }

    $outFile = Join-Path $env:TEMP "sm-$Ep-speakers.json"
    Remove-Item $outFile -Force -ErrorAction SilentlyContinue
    $argv = @($SpeakersScript, '--ep', $Ep, '--vault', $Vault, '--out', $outFile)
    if ($Names -and $Names.Count) {
        # 中文只走文件，不进 argv——跟 ssh 那条契约同一个理由，本地 argv 也不例外
        $inFile = Join-Path $env:TEMP "sm-$Ep-names.json"
        [System.IO.File]::WriteAllText($inFile, (ConvertTo-Json -InputObject $Names -Compress),
            [System.Text.UTF8Encoding]::new($false))
        $argv += @('--names', $inFile)
    }
    $prevEap = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try { $log = & $LocalPy @argv 2>&1; $rc = $LASTEXITCODE }
    finally { $ErrorActionPreference = $prevEap }
    if ($rc -ne 0) { throw "声纹比对失败（$Ep）：$(($log -join ' ').Trim())" }
    foreach ($l in $log) { if ("$l" -match '^入库') { Write-Log "    $l" Green } }
    if (-not (Test-Path $outFile)) { throw "speakers.py 报成功但没写出 $outFile" }
    return Get-Content $outFile -Raw -Encoding utf8 | ConvertFrom-Json
}

function Get-SpeakerBlock {
    param($Res)
    if ($null -eq $Res) { return @() }
    $people = @($Res.people)
    if ($people.Count -lt 1) { return @() }
    $total = 0.0
    foreach ($p in $people) { if ($p.seconds) { $total += [double]$p.seconds } }

    $block = @(
        $SpkBegin
        '> [!question]- 这集都有谁'
        '> 「未知N」是声纹库认不出来的人：点它的时间戳听两句，把名字填进行尾方括号里保存，'
        '> worker 下一轮入库，往后各集自动认出来。第一次登记可以连角色一起写：`历史哥 嘉宾`。'
        '> 认错了就直接改方括号里的字。本块由 worker 重写，方括号以外别写东西。'
    )
    foreach ($p in $people) {
        $pct = if ($total -gt 0) { '{0:P0}' -f ([double]$p.seconds / $total) } else { '—' }
        $len = ConvertTo-Hms $p.seconds
        $when = ConvertTo-Hms $p.first
        if ($p.status -eq 'known') {
            $badge = @($p.role, ('声纹库 {0:N2}' -f [double]$p.score)) | Where-Object { $_ }
            $block += ('> - `{0}` **{1}**（{2}）说了 {3}（{4}），首次出现 {5}  [{0}:: {1}]' -f `
                    $p.speaker, $p.name, ($badge -join ' · '), $len, $pct, $when)
            continue
        }
        $warn = ''
        if ($p.status -eq 'dup') {
            $warn = '  ⚠ 声纹跟 {0}（{1}）是同一个人（{2:N2}）——多半是分离器把一个人切成了两半；确实是两个人就照填' -f `
                $p.dup_of, $p.name, [double]$p.score
        }
        elseif ($p.status -eq 'ambiguous') {
            $warn = '  ⚠ 库里 {0} 都像，不猜' -f (@($p.like) -join '、')
        }
        $block += ('> - `{0}` **{1}** 说了 {2}（{3}），首次出现 {4} → 点名 [{0}:: ]{5}' -f `
                $p.speaker, $p.unknown, $len, $pct, $when, $warn)
    }
    return $block + @($SpkEnd, '')
}

function Format-YamlList {
    param([string[]]$Items)
    $xs = @($Items | Where-Object { $_ })
    if ($xs.Count -eq 0) { return '[]' }
    return '[' + (($xs | ForEach-Object { '"' + ($_ -replace '"', '\"') + '"' }) -join ', ') + ']'
}

function Set-Frontmatter {
    <# 改一个 frontmatter 字段；没有就补在 frontmatter 末尾。
       -OnlyIfEmpty：人已经填过就一个字都不碰。#>
    param([string[]]$Lines, [string]$Key, [string]$Value, [switch]$OnlyIfEmpty)
    if ($Lines.Count -lt 2 -or $Lines[0] -ne '---') { return @{ Lines = $Lines; Changed = $false } }
    $end = -1
    for ($i = 1; $i -lt $Lines.Count; $i++) { if ($Lines[$i] -eq '---') { $end = $i; break } }
    if ($end -lt 0) { return @{ Lines = $Lines; Changed = $false } }

    for ($i = 1; $i -lt $end; $i++) {
        if ($Lines[$i] -match "^$([regex]::Escape($Key))\s*:\s*(.*)$") {
            $cur = $Matches[1].Trim()
            if ($OnlyIfEmpty -and $cur -ne '' -and $cur -ne '[]') {
                return @{ Lines = $Lines; Changed = $false }
            }
            if ($cur -eq $Value) { return @{ Lines = $Lines; Changed = $false } }
            $new = @($Lines)
            $new[$i] = "$Key`: $Value"
            return @{ Lines = $new; Changed = $true }
        }
    }
    $head = @($Lines[0..($end - 1)])
    $tail = @($Lines[$end..($Lines.Count - 1)])
    return @{ Lines = $head + @("$Key`: $Value") + $tail; Changed = $true }
}

function Sync-EpisodeSpeakers {
    <# 读笔记里人填的点名 → 入库 → 重写小表 + frontmatter。返回是否改动了文件。#>
    param([string]$NotePath, [string]$Ep)
    $lines = @(Read-Utf8Lines $NotePath)
    $res = Resolve-Speakers -Ep $Ep -Names (Read-SpeakerNames $lines)
    if ($null -eq $res) { return $false }

    $upd = Update-SpeakerBlock -Lines $lines -Block (Get-SpeakerBlock $res)
    $lines = $upd.Lines
    $changed = $upd.Changed

    # `人物:` 归机器所有，永远重写——未知的也列进去（写成「未知1」），
    # 这样跨集查询一眼看得出哪几集还欠点名。
    # 只认 known。疑似重复的簇虽然带着人名，但它列进去就成了「人物: [瓜哥, 瓜哥]」——
    # 那既不是事实，也把该让人处理的过切藏了起来。写「未知N」，让它留在待点名表里。
    $who = foreach ($p in @($res.people)) { if ($p.status -eq 'known') { $p.name } else { $p.unknown } }
    $r = Set-Frontmatter -Lines $lines -Key '人物' -Value (Format-YamlList $who)
    $lines = $r.Lines; $changed = $changed -or $r.Changed

    # 主播/嘉宾是人的字段，只在还空着时替他填一次，填过就再也不碰
    foreach ($role in @('主播', '嘉宾')) {
        $hit = @(foreach ($p in @($res.people)) { if ($p.role -eq $role -and $p.name) { $p.name } })
        if ($hit.Count) {
            $r = Set-Frontmatter -Lines $lines -Key $role -Value (Format-YamlList $hit) -OnlyIfEmpty
            $lines = $r.Lines; $changed = $changed -or $r.Changed
        }
    }

    if ($changed) { Write-Utf8Lines -Path $NotePath -Lines $lines }
    return $changed
}

function Update-SpeakerBlock {
    param([string[]]$Lines, [string[]]$Block)
    if (-not $Block.Count) { return @{ Lines = $Lines; Changed = $false } }
    $b = [array]::IndexOf($Lines, $SpkBegin)
    $e = [array]::IndexOf($Lines, $SpkEnd)
    if ($b -ge 0 -and $e -gt $b) {
        $old = $Lines[$b..$e]
        if (($old -join "`n") -eq (($Block[0..($Block.Count - 2)]) -join "`n")) {
            return @{ Lines = $Lines; Changed = $false }
        }
        $head = if ($b -gt 0) { @($Lines[0..($b - 1)]) } else { @() }
        $tail = if ($e -lt $Lines.Count - 1) { @($Lines[($e + 1)..($Lines.Count - 1)]) } else { @() }
        return @{ Lines = $head + $Block[0..($Block.Count - 2)] + $tail; Changed = $true }
    }
    # 老笔记还没有这一块：插在「## 断言」前面，够不着就补在末尾
    $at = [array]::IndexOf($Lines, '## 断言')
    if ($at -lt 0) { return @{ Lines = @($Lines) + @('') + $Block; Changed = $true } }
    $head = if ($at -gt 0) { @($Lines[0..($at - 1)]) } else { @() }
    return @{ Lines = $head + $Block + @($Lines[$at..($Lines.Count - 1)]); Changed = $true }
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
        # 整体跳过会让 frontmatter 停留在旧正本上——补跑说话人分离后，
        # 笔记会一直写着「说话人分离: pending」。只同步跟正本挂钩的那几行，
        # 人手填的（主播/嘉宾/播出日期）和正文一律不碰。
        $sync = @{
            '转写引擎'     = "$($tr.engine)"
            '说话人分离'   = "$($tr.diarization)"
        }
        $lines = @(Read-Utf8Lines $notePath)
        $hits = 0
        for ($i = 0; $i -lt $lines.Count; $i++) {
            if ($lines[$i] -eq '---' -and $i -gt 0) { break }      # frontmatter 结束
            foreach ($k in $sync.Keys) {
                if ($lines[$i] -match "^$k`:\s*(.*)$" -and $Matches[1] -ne $sync[$k]) {
                    $lines[$i] = "$k`: $($sync[$k])"
                    $hits++
                }
            }
        }
        if ($hits) { Write-Utf8Lines -Path $notePath -Lines $lines }
        $spk = Sync-EpisodeSpeakers -NotePath $notePath -Ep $ep
        if ($hits -or $spk) {
            $what = @()
            if ($hits) { $what += "$hits 个 frontmatter 字段" }
            if ($spk) { $what += '说话人小表' }
            Write-Log "  ✓ EP 笔记已存在，更新了$($what -join '、')（其余正文未动）" Green
        } else {
            Write-Log "  · EP 笔记已存在且元数据一致，未改动" DarkGray
        }
        return
    }

    # 简介/标签是嘉宾名单常见的唯一书面出处，且 UP 主改简介后就没了。
    # 原样搬进笔记当点名的证据——只搬运，不解析谁是嘉宾（那是人的判断）。
    # 早于本功能下载的集数 meta.json 里没有这两个字段，StrictMode 下要先探再取。
    $metaKeys = $meta.PSObject.Properties.Name
    $desc = if ($metaKeys -contains 'description') { "$($meta.description)".Trim() } else { '' }
    $tags = if ($metaKeys -contains 'tags') { @($meta.tags) } else { @() }

    $srcBlock = @()
    if ($desc -or $tags.Count) {
        $srcBlock += '> [!quote]- B 站原始简介（搬运，未加工——点名嘉宾时看这里）'
        if ($tags.Count) { $srcBlock += "> **标签**：$($tags -join '、')" ; $srcBlock += '>' }
        foreach ($l in ($desc -split "`r?`n")) { $srcBlock += "> $l" }
        $srcBlock += ''
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
        '嘉宾: []'
        '人物: []'          # 声纹库认出来的全部说话人，含还没点名的「未知N」；worker 独占
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
    ) + $srcBlock + @(
        '## 断言'
        ''
        '## 待办'
        ''
        '- [ ] 点名：上面「这集都有谁」里还剩「未知N」的，听两句填进方括号'
        '- [ ] 核对 `播出日期`——这里填的是**投稿日期**，直播日期常常早一天'
        '- [ ] 阶段 2 抽取 → `_review/`'
        ''
    )
    Write-Utf8Lines -Path $notePath -Lines $note
    # 说话人小表由声纹库现算，落盘后原地插进去，跟补跑分离时走的是同一条路
    $null = Sync-EpisodeSpeakers -NotePath $notePath -Ep $ep
    Write-Log "  ✓ EP 笔记已建：$([System.IO.Path]::GetFileName($notePath))" Green
}

$STEPS = @{
    '待下载'   = ${function:Step-Download}
    '待转写'   = ${function:Step-Transcribe}
    '待分离'   = ${function:Step-Diarize}
    '待取回'   = ${function:Step-Fetch}
    '待建笔记' = ${function:Step-Scaffold}
}

# ---------------------------------------------------------------- 主循环

function Initialize-Queue {
    <# 新粘的裸链接补上 ep 和阶段；卡在「*中」的行打回重跑（崩溃续跑）。#>
    $changed = $false
    foreach ($row in @(Read-Queue)) {
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

$script:NamedAt = @{}

function Invoke-NamingPass {
    <# 扫 EP 笔记，把人刚填的点名入库并回填。

       点名发生在流水线跑完之后（笔记建好，人才看得到「未知N」），所以它不能挂在
       队列的某个阶段上，只能每轮扫一遍。按「笔记 + diar.json 的修改时间」记账跳过
       没动过的集，免得每 5 秒白起一堆 python。#>
    param([string]$Only)
    if (-not (Test-Path $EpisodesDir)) { return }
    foreach ($f in Get-ChildItem $EpisodesDir -Filter '*.md' -File -ErrorAction SilentlyContinue) {
        if ($f.BaseName -notmatch '^(EP\d+)') { continue }
        $ep = $Matches[1]
        if ($Only -and $ep -ne $Only) { continue }
        $diar = Join-Path $AssetsDir "$ep.diar.json"
        if (-not (Test-Path $diar)) { continue }

        $stamp = "$($f.LastWriteTimeUtc.Ticks)/$((Get-Item $diar).LastWriteTimeUtc.Ticks)"
        if (-not $Only -and $script:NamedAt[$f.FullName] -eq $stamp) { continue }
        try {
            if (Sync-EpisodeSpeakers -NotePath $f.FullName -Ep $ep) {
                Write-Log "$ep 说话人小表已回填" Green
            }
            # 自己刚写过就要重新取修改时间，否则下一轮又跑一遍
            $script:NamedAt[$f.FullName] =
                "$((Get-Item $f.FullName).LastWriteTimeUtc.Ticks)/$((Get-Item $diar).LastWriteTimeUtc.Ticks)"
        }
        catch {
            Write-Log "$ep 点名回填失败：$_" Red
        }
    }
}

function Invoke-QueuePass {
    <# 扫一遍队列，推进第一个有待办的行。返回是否做了事。#>
    Initialize-Queue
    foreach ($row in @(Read-Queue)) {
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
    foreach ($row in @(Read-Queue)) {
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

if ($Name) {
    Invoke-NamingPass -Only $Name
    Write-Log "$Name 点名回填完毕" Green
    exit 0
}

Write-Log "队列：$QueuePath" DarkGray
if ($Watch) {
    Write-Log "常驻模式，每 $PollSeconds 秒扫一次。Ctrl+C 退出。" Cyan
    while ($true) {
        try {
            while (Invoke-QueuePass) { }
            Invoke-NamingPass
        }
        catch { Write-Log "扫描出错：$_" Red }
        Start-Sleep -Seconds $PollSeconds
    }
}
else {
    $did = $false
    while (Invoke-QueuePass) { $did = $true }
    Invoke-NamingPass
    if (-not $did) { Write-Log "队列里没有待办。" DarkGray }
}
