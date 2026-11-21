# =====================================================================
# IT 运维工单台 - 终端合规巡检代理（Windows）
# 用法（管理员 PowerShell）：
#   .\ComplianceAgent.ps1 -Server "http://192.168.1.100:8300" -ApiKey "<compliance.agent_api_key>" -AssetTag "PC-0001"
# 可配合计划任务每日执行；AssetTag 需先在「资产管理」登记。
# 上报项：杀毒软件（Defender）、系统补丁、BitLocker —— 对应管理台 method=agent 的巡检项 key。
# =====================================================================
param(
    [Parameter(Mandatory = $true)][string]$Server,
    [Parameter(Mandatory = $true)][string]$ApiKey,
    [string]$AssetTag = $env:COMPUTERNAME
)

$ErrorActionPreference = 'Stop'
$Results = @()

# ---------- 1. 杀毒软件（Defender） ----------
try {
    $av = Get-MpComputerStatus -ErrorAction Stop
    if ($av.AntivirusEnabled -and $av.AntivirusSignatureAge -le 7) {
        $Results += @{ key = 'antivirus'; result = '合规'; detail = "Defender 已启用，病毒库 $($av.AntivirusSignatureLastUpdated)（$($av.AntivirusSignatureAge) 天前）" }
    } elseif ($av.AntivirusEnabled) {
        $Results += @{ key = 'antivirus'; result = '不合规'; detail = "病毒库已 $($av.AntivirusSignatureAge) 天未更新" }
    } else {
        $Results += @{ key = 'antivirus'; result = '不合规'; detail = 'Defender 未启用' }
    }
} catch {
    $Results += @{ key = 'antivirus'; result = '不合规'; detail = "未检测到 Defender 或查询失败：$($_.Exception.Message)" }
}

# ---------- 2. 系统补丁（60 天内有更新） ----------
try {
    $latest = Get-HotFix | Where-Object { $_.InstalledOn } | Sort-Object InstalledOn -Descending | Select-Object -First 1
    if ($latest -and ((Get-Date) - $latest.InstalledOn).TotalDays -le 60) {
        $Results += @{ key = 'patch'; result = '合规'; detail = "最新补丁 $($latest.HotFixID) 安装于 $($latest.InstalledOn.ToString('yyyy-MM-dd'))" }
    } elseif ($latest) {
        $age = [int]((Get-Date) - $latest.InstalledOn).TotalDays
        $Results += @{ key = 'patch'; result = '不合规'; detail = "最新补丁已 $age 天未更新（$($latest.InstalledOn.ToString('yyyy-MM-dd'))）" }
    } else {
        $Results += @{ key = 'patch'; result = '不合规'; detail = '未查询到补丁记录' }
    }
} catch {
    $Results += @{ key = 'patch'; result = '不合规'; detail = "补丁查询失败：$($_.Exception.Message)" }
}

# ---------- 3. BitLocker（系统盘） ----------
try {
    $bl = Get-BitLockerVolume -MountPoint $env:SystemDrive -ErrorAction Stop
    if ($bl.ProtectionStatus -eq 'On') {
        $Results += @{ key = 'bitlocker'; result = '合规'; detail = "系统盘已加密（$($bl.EncryptionPercentage)%）" }
    } else {
        $Results += @{ key = 'bitlocker'; result = '不合规'; detail = "系统盘未启用 BitLocker（ProtectionStatus=$($bl.ProtectionStatus)）" }
    }
} catch {
    $Results += @{ key = 'bitlocker'; result = '不合规'; detail = "BitLocker 查询失败（可能不支持）：$($_.Exception.Message)" }
}

# ---------- 上报 ----------
$Body = @{
    asset_tag = $AssetTag
    results   = $Results
} | ConvertTo-Json -Depth 5 -Compress

try {
    $resp = Invoke-RestMethod -Method Post `
        -Uri "$Server/api/compliance/agent-report" `
        -ContentType 'application/json; charset=utf-8' `
        -Headers @{ 'X-API-Token' = $ApiKey } `
        -Body $Body
    Write-Host "上报成功：终端 $($resp.asset_tag)，接受 $($resp.accepted) 项结果"
    exit 0
} catch {
    Write-Error "上报失败：$($_.Exception.Message)"
    exit 1
}
