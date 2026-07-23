# dl-audio.ps1 — 给 B 站链接，让 5070 主机下载音频到 E:\asr\audio\
# 用法（笔记本上执行）：
#   .\scripts\dl-audio.ps1 "https://www.bilibili.com/video/BV1xx411c7mD"
#   .\scripts\dl-audio.ps1 "https://b23.tv/abc123"          # 短链自动展开
#   .\scripts\dl-audio.ps1 BV1xx411c7mD                     # 裸 BV 号也行
# 说明：只抓音频流（m4a，不下视频）；多 P 录播默认全部下载；
#       URL 带 ?p=N 时只下载第 N 个分 P。流量走 PC 侧网络。

param(
    [Parameter(Mandatory = $true)]
    [string]$Url
)

$ErrorActionPreference = 'Stop'

# ---- 1. 归一化：短链展开 + 提取 BV 号 ----
$target = $Url
if ($target -notmatch 'BV[0-9A-Za-z]{10}') {
    # b23.tv 等短链：跟随重定向拿最终地址
    $resp = Invoke-WebRequest -Uri $target -Method Head -UseBasicParsing
    $target = $resp.BaseResponse.RequestMessage.RequestUri.AbsoluteUri
}
if ($target -match '(BV[0-9A-Za-z]{10})') {
    $bv = $Matches[1]
} else {
    throw "无法从输入中识别 BV 号：$Url"
}

$clean = "https://www.bilibili.com/video/$bv"
$extra = ''
if ($target -match '[?&]p=(\d+)') {
    # 指定分 P：只下这一个
    $clean += "?p=$($Matches[1])"
    $extra = '--no-playlist'
}

Write-Host "下载目标: $clean" -ForegroundColor Cyan

# ---- 2. 让 PC 执行 yt-dlp（只抓音频流）----
ssh pc-5070 "C:\asr\venv\Scripts\yt-dlp.exe -f ba -N 4 $extra -o 'E:\asr\audio\%(title)s [%(id)s].%(ext)s' '$clean'"
if ($LASTEXITCODE -ne 0) { throw "yt-dlp 下载失败（exit $LASTEXITCODE）" }

# ---- 3. 显示结果 ----
Write-Host "`nE:\asr\audio\ 最新文件：" -ForegroundColor Green
ssh pc-5070 "Get-ChildItem E:\asr\audio -File | Sort-Object LastWriteTime -Descending | Select-Object -First 5 @{n='MB';e={[math]::Round(`$_.Length/1MB,1)}}, Name | Format-Table -AutoSize"
