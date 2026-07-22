# setup-5070-pc.ps1 — 5070 主机（转写 PC）一次性初始化
# 用途：启用 OpenSSH 服务端 + 授权笔记本密钥 + 安装 Tailscale
# 用法：在 PC 上以【管理员身份】打开 PowerShell，执行：
#   irm https://raw.githubusercontent.com/kildren-coder/story-machine/main/scripts/setup-5070-pc.ps1 -OutFile setup-5070-pc.ps1
#   Set-ExecutionPolicy -Scope Process Bypass -Force
#   .\setup-5070-pc.ps1
# 全程幂等，重复执行安全。

$ErrorActionPreference = 'Stop'

# ---- 0. 管理员检查 ----
if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Error "请以管理员身份运行本脚本（右键 PowerShell → 以管理员身份运行）"
}

# ---- 1. OpenSSH 服务端 ----
Write-Host "`n[1/4] 启用 OpenSSH 服务端..." -ForegroundColor Cyan
$cap = Get-WindowsCapability -Online -Name 'OpenSSH.Server*'
if ($cap.State -ne 'Installed') {
    Add-WindowsCapability -Online -Name $cap.Name
}
Set-Service sshd -StartupType Automatic
Start-Service sshd
# 防火墙放行（通常安装时自动创建，兜底确保）
if (-not (Get-NetFirewallRule -Name 'OpenSSH-Server-In-TCP' -ErrorAction SilentlyContinue)) {
    New-NetFirewallRule -Name 'OpenSSH-Server-In-TCP' -DisplayName 'OpenSSH Server (sshd)' `
        -Enabled True -Direction Inbound -Protocol TCP -Action Allow -LocalPort 22 | Out-Null
}
# SSH 登录后默认进 PowerShell 而非 cmd
New-Item -Path 'HKLM:\SOFTWARE\OpenSSH' -Force | Out-Null
New-ItemProperty -Path 'HKLM:\SOFTWARE\OpenSSH' -Name DefaultShell `
    -Value 'C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe' -PropertyType String -Force | Out-Null

# ---- 2. 授权笔记本的公钥（免密登录）----
Write-Host "[2/4] 写入笔记本公钥..." -ForegroundColor Cyan
$pubkey = 'ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAINaNaWOdgKUOOzJglC3eSYRoHQa217S1mr1uYc4iE0RX kildren@bytevirt'
# 管理员账号走 administrators_authorized_keys（Windows OpenSSH 的特殊规则）
$adminKeys = 'C:\ProgramData\ssh\administrators_authorized_keys'
if (-not (Test-Path $adminKeys) -or -not (Select-String -Path $adminKeys -SimpleMatch $pubkey -Quiet)) {
    Add-Content -Path $adminKeys -Value $pubkey
}
icacls $adminKeys /inheritance:r /grant 'Administrators:F' /grant 'SYSTEM:F' | Out-Null
# 普通账号路径也写一份（兜底，两种账号类型都覆盖）
$userKeys = "$env:USERPROFILE\.ssh\authorized_keys"
New-Item -ItemType Directory -Force -Path "$env:USERPROFILE\.ssh" | Out-Null
if (-not (Test-Path $userKeys) -or -not (Select-String -Path $userKeys -SimpleMatch $pubkey -Quiet)) {
    Add-Content -Path $userKeys -Value $pubkey
}

# ---- 3. Tailscale ----
Write-Host "[3/4] 安装 Tailscale..." -ForegroundColor Cyan
$ts = 'C:\Program Files\Tailscale\tailscale.exe'
if (-not (Test-Path $ts)) {
    try {
        winget install --id Tailscale.Tailscale --accept-source-agreements --accept-package-agreements
    } catch {
        Write-Warning "winget 安装失败，请手动到 https://tailscale.com/download/windows 下载安装后重跑本脚本"
        throw
    }
}
# 登录（会打开浏览器，用与笔记本相同的账号登录）
& $ts up

# ---- 4. 汇报信息 ----
Write-Host "`n[4/4] 完成。请把下面几行信息发回给笔记本侧：" -ForegroundColor Green
Write-Host ("  用户名   : {0}\{1}" -f $env:COMPUTERNAME, $env:USERNAME)
Write-Host ("  主机名   : {0}" -f (& $ts status --json | ConvertFrom-Json).Self.DNSName)
Write-Host ("  Tailscale IPv4: {0}" -f (& $ts ip -4))
Write-Host ("  sshd 状态: {0}" -f (Get-Service sshd).Status)
