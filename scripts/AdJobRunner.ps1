# AdJobRunner.ps1 — AD 联动任务代理（v2.2）
# 部署在装有 AD 模块（RSAT）的域内机器上，计划任务定期执行：
#   powershell -ExecutionPolicy Bypass -File AdJobRunner.ps1 -Server "http://工单台IP:8300" -ApiKey "你的令牌" -ScriptDir "C:\itops-ad-scripts"
# 行为：拉取待执行任务 -> 在 ScriptDir 内找到同名 .ps1 执行（参数 -TicketNo/-CustomFields）-> 回传结果。
param(
    [Parameter(Mandatory = $true)][string]$Server,
    [Parameter(Mandatory = $true)][string]$ApiKey,
    [Parameter(Mandatory = $true)][string]$ScriptDir
)

$ErrorActionPreference = "Stop"
$headers = @{ "X-API-Token" = $ApiKey }

function Get-PendingJobs {
    $resp = Invoke-RestMethod -Uri "$Server/api/ad/jobs/pending" -Headers $headers -Method Get
    return @($resp.items)
}

function Invoke-AdJob($job) {
    $scriptPath = Join-Path $ScriptDir $job.script
    if (-not (Test-Path $scriptPath)) {
        return @{ success = $false; output = "脚本不存在: $scriptPath" }
    }
    $payload = $job.payload
    try {
        $out = & $scriptPath -TicketNo $payload.ticket_no -CustomFields ($payload.custom_fields | ConvertTo-Json -Compress) 2>&1
        return @{ success = $true; output = ($out | Out-String) }
    } catch {
        return @{ success = $false; output = ($_ | Out-String) }
    }
}

function Send-Result($jobId, $result) {
    $body = @{ success = [bool]$result.success; output = ($result.output | Out-String) } | ConvertTo-Json
    Invoke-RestMethod -Uri "$Server/api/ad/jobs/$jobId/result" -Headers $headers -Method Post -Body $body -ContentType "application/json; charset=utf-8" | Out-Null
}

$jobs = Get-PendingJobs
foreach ($job in $jobs) {
    Write-Host ("处理 AD 任务 #{0}（{1}）" -f $job.id, $job.script)
    $result = Invoke-AdJob $job
    Send-Result $job.id $result
    Write-Host ("任务 #{0} 完成：{1}" -f $job.id, $result.success)
}
Write-Host ("本轮处理 {0} 个任务" -f $jobs.Count)
