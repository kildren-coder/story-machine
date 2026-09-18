# worker.ps1 — story-machine 流水线执行器（阶段 0：音频 → 逐字稿 → 落 vault）
#
# 用法：
#   .\scripts\worker.ps1                 处理完队列里所有待办就退出（单发）
#   .\scripts\worker.ps1 -Watch          常驻，每 5 秒扫一次队列笔记
#   .\scripts\worker.ps1 -Retry EP02     失败后接着**摔倒的那一步**重跑（常用）
#   .\scripts\worker.ps1 -Reset EP02     打回「待下载」整条重来（少用，会白扔转写）
#   .\scripts\worker.ps1 -Name EP02      只跑这一集的点名回填（不碰队列）
#   .\scripts\worker.ps1 -Extract EP02   只跑这一集的整理（+ -Redo 覆盖已有产物）
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
    [string]$Retry,        # 打回**失败的那一步**重跑（对比 -Reset：那是整条重来）
    [string]$Name,         # 只跑某一集的点名回填，不碰队列
    [string]$Extract,      # 只跑某一集的整理（转交 scripts\digest.py）
    [switch]$Redo          # 配 -Extract：产物已在也重跑（会覆盖）
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
# 整理（L1 起）也在本机跑：它调的是无头 Claude Code，走的是笔记本上的订阅额度
$DigestScript = Join-Path $PSScriptRoot "digest.py"
# 取回走 sftp（要续传，见 Copy-FromPc）。用绝对路径起进程，省得依赖 PATH。
$SftpExe = (Get-Command sftp -ErrorAction SilentlyContinue).Source
if (-not $SftpExe) { $SftpExe = 'C:\Windows\System32\OpenSSH\sftp.exe' }

# 阶段流转。键是「待办」，值是执行时的「进行中」标记与下一站。
$FLOW = [ordered]@{
    '待下载'   = @{ Busy = '下载中';   Next = '待转写' }
    '待转写'   = @{ Busy = '转写中';   Next = '待分离' }
    '待分离'   = @{ Busy = '分离中';   Next = '待取回' }
    '待取回'   = @{ Busy = '取回中';   Next = '待建笔记' }
    '待建笔记' = @{ Busy = '建笔记中'; Next = '完成' }
}
$FIELD_ORDER = @('ep', '标题', '阶段', '进度', '时长', '更新', '备注', '失败于', '错误')

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

# 取回的暂存区：**先下到 vault 外面的 ASCII 目录，传完整了才搬进 _assets/。**
# 三个理由，都踩过：
#   (a) 半截文件绝不能出现在 _assets/——Obsidian 和时间戳插件都照文件名认音频，
#       一个 1.1MB 的断头 m4a 看上去跟好的一模一样（2026-08-11 EP03 就在库里躺着）；
#   (b) 断点续传要有个稳定的落脚点，重试才能接着上次的字节数下；
#   (c) sftp 的批处理脚本里塞中文路径（vault 在「任务栏」下）不可靠，ASCII 没这问题。
$FetchTmp = Join-Path $env:TEMP 'sm-fetch'

function Copy-FromPc {
    <#
      从 PC 取一个文件。

      用 sftp 的 reget 而不是 scp：**scp 没有续传**，断在 22/23 MB 也得从 0 重来。
      reget 从本地已有的字节数接着下（实测把文件截断到 5000 字节再续传，
      sha256 与完整文件一致）。

      配合 ssh config 里的 ServerAliveInterval，断链的表现从「永远挂着」变成
      「约 60 秒内报错 → 重试接着传」。EP03 那次是直连路径死了退化成 DERP，
      scp 进程 CPU 0.00 躺了十分钟，队列上只有一行不动的「音频传输中…」。
    #>
    param(
        [string]$RemoteFile,
        [string]$LocalPath,
        $Row,                      # 给了就把进度写回队列，让人看得见它在动
        [long]$ExpectBytes = 0,    # 知道该多大就校验，顺便算百分比
        [int]$Retries = 3
    )
    $null = New-Item -ItemType Directory -Force (Split-Path $LocalPath)
    $null = New-Item -ItemType Directory -Force $FetchTmp
    $tmp = Join-Path $FetchTmp $RemoteFile
    $batch = Join-Path $FetchTmp 'batch.txt'
    $logOut = Join-Path $FetchTmp 'sftp.out'
    $logErr = Join-Path $FetchTmp 'sftp.err'

    # 暂存区里剩的比该有的还大 = 上一轮留下的脏文件，reget 只会往后接，永远对不上
    if ($ExpectBytes -gt 0 -and (Test-Path $tmp) -and (Get-Item $tmp).Length -gt $ExpectBytes) {
        Remove-Item $tmp -Force
    }

    # 远端路径必须带前导斜杠。`E:/asr/staged/x` 会被当成相对家目录的路径，
    # 解析成 `/C:/Users/admin/E:/asr/staged/x` 然后报 not found。
    [System.IO.File]::WriteAllText($batch,
        "reget `"/$RemoteStage/$RemoteFile`" `"$($tmp -replace '\\', '/')`"`n",
        [System.Text.ASCIIEncoding]::new())

    $err = ''
    for ($try = 1; $try -le $Retries; $try++) {
        $had = if (Test-Path $tmp) { (Get-Item $tmp).Length } else { 0 }
        if ($try -gt 1) {
            Write-Log ("  · 重试 {0}/{1}（已有 {2:N1} MB，接着下）" -f $try, $Retries, ($had / 1MB)) DarkYellow
        }
        # **不能用 Start-Process -PassThru。** worker 跑在 powershell.exe 5.1 下，
        # 那里返回的 Process 对象拿不到句柄，`$p.ExitCode` 是空的——于是
        # `$p.ExitCode -eq 0` 恒为假，明明下载成功也被判成失败重试三轮然后抛错。
        # （pwsh 7 里它是好的，所以手测发现不了。）直接用 .NET 的 Process 才可靠。
        $psi = New-Object System.Diagnostics.ProcessStartInfo
        $psi.FileName = $SftpExe
        # .NET Framework 4.8 没有 ArgumentList，只能拼字符串，所以路径要自己加引号
        $psi.Arguments = '-q -b "{0}" {1}' -f $batch, $Host5070
        $psi.UseShellExecute = $false
        $psi.RedirectStandardOutput = $true
        $psi.RedirectStandardError = $true
        $psi.CreateNoWindow = $true
        $p = [System.Diagnostics.Process]::Start($psi)
        # 管道要一直抽干，写满了子进程会卡在写 stdout 上（输出很小，异步读到底即可）
        $so = $p.StandardOutput.ReadToEndAsync()
        $se = $p.StandardError.ReadToEndAsync()

        # 进度靠轮询暂存文件的大小——sftp 自带的进度条是给终端画的（\r 覆盖行），
        # 解析它不如直接看文件长到哪了，而且这样连「一动不动」都看得出来。
        $last = [datetime]::MinValue
        while (-not $p.HasExited) {
            Start-Sleep -Milliseconds 400
            if (-not $Row -or $ExpectBytes -le 0) { continue }
            if (([datetime]::Now - $last).TotalSeconds -lt 2) { continue }
            $last = [datetime]::Now
            $now = if (Test-Path $tmp) { (Get-Item $tmp).Length } else { 0 }
            $Row.Fields['进度'] = '{0}% ({1:N1}/{2:N1} MB)' -f `
                [int](100 * $now / $ExpectBytes), ($now / 1MB), ($ExpectBytes / 1MB)
            Save-Row $Row
        }
        $p.WaitForExit()
        $rc = $p.ExitCode
        $log = (("$($so.Result) $($se.Result)") -replace '\s+', ' ').Trim()
        [System.IO.File]::WriteAllText($logOut, $log)   # 留一份给事后翻

        if ($rc -eq 0 -and (Test-Path $tmp)) {
            $got = (Get-Item $tmp).Length
            if ($ExpectBytes -gt 0 -and $got -ne $ExpectBytes) {
                $err = "字节数对不上：拿到 $got，应为 $ExpectBytes"
            }
            else {
                # 跨盘 Move 是「拷贝再删」，中途 _assets/ 里会短暂出现半截文件。
                # 先落 .part（插件不认这个后缀），再同盘改名——改名才是原子的。
                $part = "$LocalPath.part"
                Move-Item -LiteralPath $tmp -Destination $part -Force
                Move-Item -LiteralPath $part -Destination $LocalPath -Force
                return
            }
        }
        else {
            $err = if ($log) { $log } else { "sftp 退出码 $rc" }
            # 远端压根没这个文件，重试三轮也变不出来
            if ($err -match 'not found|No such file') { break }
        }
        if ($try -lt $Retries) { Start-Sleep -Seconds ([Math]::Min(15, 3 * $try)) }
    }
    throw "取回失败（$RemoteFile）：$err"
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
    $expect = if ($meta.PSObject.Properties.Name -contains 'audio_bytes') { [long]$meta.audio_bytes } else { 0 }
    $haveAudio = (Test-Path $audioLocal) -and $expect -and
                 ((Get-Item $audioLocal).Length -eq $expect)
    if ($haveAudio) {
        Write-Log "  · 音频本地已完整，跳过传输" DarkGray
    }
    else {
        Write-Log ("  · 取音频 {0:N1} MB" -f ($expect / 1MB)) DarkGray
        # 音频比其它文件大两个数量级，Tailscale 这条链路又常常传着传着就 Connection
        # closed（EP03 实测 3 次重试只走到 15.2/23.1 MB）。重试是续传，每一轮都往前
        # 推进，所以多给几次就是纯赚——反正断了也不会从头再来。
        Copy-FromPc -RemoteFile "$ep$ext" -LocalPath $audioLocal -Row $Row -ExpectBytes $expect -Retries 12
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
$script:WarnedPairs = @{}

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
    $res = Get-Content $outFile -Raw -Encoding utf8 | ConvertFrom-Json

    # 声纹库体检。每个坏对只吼一次，否则 -Watch 模式下每 5 秒刷一遍屏。
    if ($res.PSObject.Properties.Name -contains 'lib_risky') {
        foreach ($pair in @($res.lib_risky)) {
            $key = "$($pair[0])|$($pair[1])"
            if ($script:WarnedPairs.ContainsKey($key)) { continue }
            $script:WarnedPairs[$key] = $true
            Write-Log ("  ⚠ 声纹库体检：{0} × {1} = {2:N3}（认定门槛 {3:N2}）——" -f `
                    $pair[0], $pair[1], [double]$pair[2], [double]$res.threshold) Yellow
            Write-Log "     跑 python pc\speakers.py --list 看详情" DarkYellow
        }
    }
    return $res
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

    # 声纹库是全局的（不按节目/来源分），人越攒越多越容易撞脸，而认错是静默的——
    # 笔记上只会写一个看起来很正常的名字。跟本集**无关**的坏对不在这里报，
    # 只在你正要做归属判断的这一刻，提醒你这一位在库里有个像的。
    # 「跟本集有关」要连候选人一起算。库脏到两人都像时，比对器会先一步把这个簇
    # 判成 ambiguous、`name` 留空——只看 name 的话，正是最该报警的那一集反而不报。
    $here = @{}
    foreach ($p in $people) {
        if ($p.name) { $here[$p.name] = $true }
        foreach ($n in @($p.like)) { if ($n) { $here[$n] = $true } }
    }
    # 这里**不能**写 `$risky = if (…) { @($Res.lib_risky) } else { @() }`。
    # if 当表达式用时结果要过一遍管道，外层数组会被拆掉一层，于是只有一对坏数据时
    # foreach 迭代到的是「瓜哥」「老王」「0.978」三个标量而不是一个三元组，
    # $pair[2] 变成对 Decimal 取下标。跟 Read-Queue 那个 `return , $rows` 同源。
    $risky = @()
    if ($Res.PSObject.Properties.Name -contains 'lib_risky') { $risky = $Res.lib_risky }
    foreach ($pair in @($risky)) {
        if (-not ($here.ContainsKey($pair[0]) -or $here.ContainsKey($pair[1]))) { continue }
        $block += ('> ')
        $block += ('> ⚠ **声纹库体检**：`{0}` 和 `{1}` 的声纹已经像到 {2:N3}（认定门槛 {3:N2}），本集出现了其中一位。' -f `
                $pair[0], $pair[1], [double]$pair[2], [double]$Res.threshold)
        $block += '> 下面那个名字值得点开听两句核一下。若是早先某一集点错了名、把两个人混进了同一个人名下，'
        $block += '> 去那一集的小表改方括号即可（改一个字就是一次重新入库）。'
    }

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
    return $block + @($SpkEnd)
}

# 笔记顶上的状态条。插件把这个代码块渲染成「现在在哪一阶段 + 下一步按钮」，
# 免得人点开一集只看见一份空笔记，还得回控制台猜该干什么。
# `worker:` 由脚本写自己的路径，仓库搬家后下一次 worker 跑过就自愈——
# 不做插件设置项，是为了让「哪个 worker」这件事只有一个出处。
$EpBegin = '<!-- ep:auto -->'
$EpEnd = '<!-- /ep -->'

function Get-EpBlock {
    param([string]$Ep)
    return @($EpBegin, '```sm-ep', "ep: $Ep", "worker: $PSCommandPath", '```', $EpEnd)
}

function Update-EpBlock {
    param([string[]]$Lines, [string]$Ep)
    return Update-MarkedBlock -Lines $Lines -Block (Get-EpBlock $Ep) -Begin $EpBegin -End $EpEnd `
        -AnchorRe '^#\s' -Where After
}

function Format-YamlList {
    param([string[]]$Items)
    $xs = @($Items | Where-Object { $_ })
    if ($xs.Count -eq 0) { return '[]' }
    return '[' + (($xs | ForEach-Object { '"' + ($_ -replace '"', '\"') + '"' }) -join ', ') + ']'
}

function Get-FmValue {
    <# 读 frontmatter 里某个键的现值，返回 @{ Text; Last }（Last = 该键最后占用的行号）。

       **值不一定在键那一行上。** Obsidian 的属性面板一律把列表写成块状：
           人物:
             - 奇衡
       人在属性面板里填过 `主播`/`嘉宾` 之后，磁盘上就是这个样子。 #>
    param([string[]]$Lines, [int]$KeyLine, [int]$End, [string]$Inline)
    $last = $KeyLine
    $items = @()
    for ($j = $KeyLine + 1; $j -lt $End; $j++) {
        if ($Lines[$j] -notmatch '^\s+\S') { break }      # 不缩进 = 下一个键，续行到此为止
        $last = $j
        if ($Lines[$j] -match '^\s*-\s*(.*)$') { $items += $Matches[1].Trim() }
    }
    $text = if ($Inline.Trim() -ne '') { $Inline } else { $items -join ', ' }
    return @{ Text = $text.Trim(); Last = $last }
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
        if ($Lines[$i] -notmatch "^$([regex]::Escape($Key))\s*:\s*(.*)$") { continue }
        # 续行必须连读带删（见 Get-FmValue）。只认键行会同时踩两个坑：
        #   (a) 块状列表被读成空值 → -OnlyIfEmpty 判定「人没填过」，
        #       把人手填的 `主播:` 覆盖掉——那正是这个开关要防的事；
        #   (b) 改写时只换键行，底下的 `  - 奇衡` 成了孤儿：
        #           人物: ["奇衡"]
        #             - 奇衡
        #       这不是合法 YAML，Obsidian 整份 frontmatter 报废，
        #       连带 Dataview 查不到这一集——而它一句话都不会报。
        $cur = Get-FmValue -Lines $Lines -KeyLine $i -End $end -Inline $Matches[1]
        if ($OnlyIfEmpty -and $cur.Text -ne '' -and $cur.Text -ne '[]') {
            return @{ Lines = $Lines; Changed = $false }
        }
        if ($cur.Last -eq $i -and $Lines[$i] -eq "$Key`: $Value") {
            return @{ Lines = $Lines; Changed = $false }
        }
        # 这里**不能**写 `$head = if ($i -gt 0) { @($Lines[0..($i-1)]) } else { @() }`。
        # if 当表达式用时结果要过一遍管道，单元素数组会被拆成裸字符串，于是后面的
        # `$head + @(…)` 从「拼数组」变成了「拼字符串」——三行 frontmatter 被粘成
        # 一行 `---主播: ["奇衡"]---`。只有键在第 1 行（$head 恰好一个元素）时才踩得到。
        # 跟 Read-Queue 的 `return , $rows`、Get-SpeakerBlock 的 $risky 是同一个坑。
        # 累加式没有这个问题：$out 一开始就是数组，`+=` 只会往里加元素。
        $out = @()
        if ($i -gt 0) { $out += $Lines[0..($i - 1)] }
        $out += "$Key`: $Value"
        $out += $Lines[($cur.Last + 1)..($Lines.Count - 1)]
        return @{ Lines = $out; Changed = $true }
    }
    $out = @()
    $out += $Lines[0..($end - 1)]
    $out += "$Key`: $Value"
    $out += $Lines[$end..($Lines.Count - 1)]
    return @{ Lines = $out; Changed = $true }
}

function Sync-EpisodeSpeakers {
    <# 读笔记里人填的点名 → 入库 → 重写小表 + frontmatter，顺带保证状态条在。
       返回是否改动了文件。#>
    param([string]$NotePath, [string]$Ep)
    $lines = @(Read-Utf8Lines $NotePath)

    # 状态条不依赖声纹库，先写死在这儿——没有质心的老集数一样该有它
    $upd = Update-EpBlock -Lines $lines -Ep $Ep
    $lines = $upd.Lines
    $changed = $upd.Changed

    $res = Resolve-Speakers -Ep $Ep -Names (Read-SpeakerNames $lines)
    if ($null -eq $res) {
        if ($changed) { Write-Utf8Lines -Path $NotePath -Lines $lines }
        return $changed
    }

    $upd = Update-SpeakerBlock -Lines $lines -Block (Get-SpeakerBlock $res)
    $lines = $upd.Lines
    $changed = $changed -or $upd.Changed

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

function Update-MarkedBlock {
    <#
      把 `<!-- x -->` … `<!-- /x -->` 之间的内容原地换成 $Block（$Block 自带首尾标记）。
      区段还不存在就按 $AnchorRe / $Where 插进去，锚点也找不着才补在末尾。

      幂等是硬要求：内容没变必须报 Changed=$false。否则 -Watch 每轮都重写文件，
      Obsidian 每 5 秒重载一次笔记，人正在里面打字就会被打断。
      空行留在标记**外面**，这样替换路径只需逐字比对标记之间的部分。
    #>
    param(
        [string[]]$Lines,
        [string[]]$Block,
        [string]$Begin,
        [string]$End,
        [string]$AnchorRe,
        [ValidateSet('Before', 'After')][string]$Where = 'Before'
    )
    if (-not $Block.Count) { return @{ Lines = $Lines; Changed = $false } }

    # 全程累加式建数组。`$x = if (…) { @(…) } else { @() }` 会在单元素时被管道
    # 拆成裸字符串，后面的 `+` 就成了字符串拼接（详见 Set-Frontmatter 里的长注释）。
    $b = [array]::IndexOf($Lines, $Begin)
    $e = [array]::IndexOf($Lines, $End)
    if ($b -ge 0 -and $e -gt $b) {
        if ((@($Lines[$b..$e]) -join "`n") -eq ($Block -join "`n")) {
            return @{ Lines = $Lines; Changed = $false }
        }
        $out = @()
        if ($b -gt 0) { $out += $Lines[0..($b - 1)] }
        $out += $Block
        if ($e -lt $Lines.Count - 1) { $out += $Lines[($e + 1)..($Lines.Count - 1)] }
        return @{ Lines = $out; Changed = $true }
    }

    $at = -1
    for ($i = 0; $i -lt $Lines.Count; $i++) {
        if ($Lines[$i] -match $AnchorRe) {
            $at = if ($Where -eq 'After') { $i + 1 } else { $i }
            break
        }
    }
    if ($at -lt 0) {
        $out = @($Lines)
        if ($out.Count -and $out[-1] -ne '') { $out += '' }
        $out += $Block
        return @{ Lines = $out; Changed = $true }
    }
    # 空行只在两边还没有空行时才补——否则每插一次就多攒一行空白
    $out = @()
    if ($at -gt 0) { $out += $Lines[0..($at - 1)] }
    if ($out.Count -and $out[-1] -ne '') { $out += '' }
    $out += $Block
    if ($at -lt $Lines.Count) {
        if ($Lines[$at] -ne '') { $out += '' }
        $out += $Lines[$at..($Lines.Count - 1)]
    }
    return @{ Lines = $out; Changed = $true }
}

function Update-SpeakerBlock {
    param([string[]]$Lines, [string[]]$Block)
    return Update-MarkedBlock -Lines $Lines -Block $Block -Begin $SpkBegin -End $SpkEnd `
        -AnchorRe '^## 断言$' -Where Before
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

function Invoke-Extract {
    <# 整理：转交 scripts\digest.py。worker 在这里只做三件事——检查前置、起进程、
       把 python 的日志原样喷给插件的日志面板。切片、调模型、闸门、写笔记全在
       python 那边，别在 PowerShell 里重写一遍。

       为什么不挂进队列状态机：整理要跑几分钟且烧订阅额度，得由人按按钮触发；
       队列那套是「粘了链接就该自动跑完」的东西，两者节奏不同。#>
    param([string]$Ep, [switch]$Again)
    if (-not (Test-Path $DigestScript)) { throw "找不到整理脚本：$DigestScript" }
    $tr = Join-Path $AssetsDir "$Ep.transcript.json"
    if (-not (Test-Path $tr)) { throw "$Ep 还没有逐字稿（$tr）——阶段 0 跑完了吗？" }

    $argv = @($DigestScript, 'ep', $Ep, '--vault', $Vault)
    if ($Again) { $argv += '--force' }
    Write-Log "$Ep 整理：无头 Claude Code，整集一次 + 每章一次，要跑十几分钟，别关窗口" Cyan
    $prevEap = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        & $LocalPy @argv 2>&1 | ForEach-Object { Write-Host "    $_" }
        $rc = $LASTEXITCODE
    }
    finally { $ErrorActionPreference = $prevEap }
    # 退出码：1 = 某层不过，已落 _failed/ 且笔记打了 整理: failed；2 = 输入缺失
    if ($rc -ne 0) { throw "$Ep 整理失败（退出码 $rc），详情看上面的日志" }
    Write-Log "$Ep 整理完成——整理稿已写进 EP 笔记，点时间戳可跳播" Green
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
        # 没有 diar.json 也照跑：点名会被 Resolve-Speakers 跳过，但状态条该补还得补
        $diar = Join-Path $AssetsDir "$ep.diar.json"
        $diarAt = if (Test-Path $diar) { (Get-Item $diar).LastWriteTimeUtc.Ticks } else { 0 }

        $stamp = "$($f.LastWriteTimeUtc.Ticks)/$diarAt"
        if (-not $Only -and $script:NamedAt[$f.FullName] -eq $stamp) { continue }
        try {
            if (Sync-EpisodeSpeakers -NotePath $f.FullName -Ep $ep) {
                Write-Log "$ep 笔记已回填（点名／状态条）" Green
            }
            # 自己刚写过就要重新取修改时间，否则下一轮又跑一遍
            $script:NamedAt[$f.FullName] =
                "$((Get-Item $f.FullName).LastWriteTimeUtc.Ticks)/$diarAt"
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
            $row.Fields['失败于'] = ''
            Save-Row $row
            if ($row.Fields['阶段'] -eq '完成') {
                Write-Log "$ep 全流程完成 ✓" Green
            }
        }
        catch {
            # 把摔在哪一步记进队列。少了这个字段，「失败」就抹掉了唯一能推断
            # 重跑起点的信息，人只剩 -Reset 可用——那是从下载重来，等于把已经
            # 跑完的转写和分离（几十分钟）白扔一遍。
            $row.Fields['阶段'] = '失败'
            $row.Fields['进度'] = ''
            $row.Fields['失败于'] = $stage
            $row.Fields['错误'] = ("$_" -replace '[\[\]\r\n]', ' ').Trim()
            Save-Row $row
            Write-Log "$ep 在「$stage」失败：$_" Red
            Write-Log "  接着这一步重跑： .\scripts\worker.ps1 -Retry $ep   （或把 [阶段:: 失败] 手改回 $stage）" DarkYellow
            Write-Log "  -Reset $ep 是从下载整条重来，一般不需要" DarkGray
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
            $row.Fields['失败于'] = ''
            Save-Row $row
            Write-Log "$Reset 已重置为「待下载」（整条重来）" Green
            exit 0
        }
    }
    throw "队列里没有 $Reset"
}

if ($Retry) {
    # 只把阶段挪回摔倒的那一步。前面几步的产物都还在暂存区和 _assets/ 里，
    # 各步自己也都是幂等的（音频按字节数判重、embedding 有缓存），所以重跑很便宜。
    foreach ($row in @(Read-Queue)) {
        if (-not ($row.Fields.Contains('ep') -and $row.Fields['ep'] -eq $Retry)) { continue }
        $at = if ($row.Fields.Contains('失败于')) { $row.Fields['失败于'] } else { '' }
        if (-not $FLOW.Contains($at)) {
            throw "$Retry 没有可重跑的失败步骤（[失败于:: $at]）。" +
                  "要整条重来用 -Reset $Retry，或直接把 [阶段:: …] 改成想跑的那一步。"
        }
        $row.Fields['阶段'] = $at
        $row.Fields['进度'] = ''
        $row.Fields['错误'] = ''
        $row.Fields['失败于'] = ''
        Save-Row $row
        Write-Log "$Retry 打回「$at」，前面几步的产物保留" Green
        exit 0
    }
    throw "队列里没有 $Retry"
}

if ($Name) {
    Invoke-NamingPass -Only $Name
    Write-Log "$Name 点名回填完毕" Green
    exit 0
}

if ($Extract) {
    Invoke-Extract -Ep $Extract -Again:$Redo
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
