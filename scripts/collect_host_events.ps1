# collect_host_events.ps1 — 采集主机本地 Windows 事件日志（四方排查第④源）
# 用法: powershell -ExecutionPolicy Bypass -File collect_host_events.ps1 [startTime] [endTime]
#       startTime/endTime 格式: "2026-09-18 10:00:00"（留空则取最近 48 小时）
param(
    [string]$StartTime = "",
    [string]$EndTime = ""
)

$ErrorActionPreference = "Continue"

# 时间窗口
if ($StartTime -eq "") {
    $start = (Get-Date).AddHours(-48)
} else {
    $start = [DateTime]::Parse($StartTime)
}
if ($EndTime -eq "") {
    $end = Get-Date
} else {
    $end = [DateTime]::Parse($EndTime)
}

Write-Host "=== Host Event Collection ===" -ForegroundColor Cyan
Write-Host "Hostname: $env:COMPUTERNAME"
Write-Host "TimeRange: $($start.ToString('yyyy-MM-dd HH:mm:ss')) ~ $($end.ToString('yyyy-MM-dd HH:mm:ss'))"
Write-Host ""

# 事件类型映射：EventID → 分类
$signatures = @{
    # 电源事件
    42   = "power"       # 系统进入睡眠
    1    = "power"       # 系统从睡眠恢复（Kernel-Power）
    107  = "power"       # 系统从休眠恢复
    # 重启/关机
    1074 = "restart"     # 用户启动的重启/关机
    1076 = "restart"     # 重启原因
    6005 = "restart"     # EventLog 服务启动（开机）
    6006 = "restart"     # EventLog 服务停止（关机）
    6008 = "restart"     # 意外关机
    41   = "restart"     # 系统未正常关机（Kernel-Power）
    # 崩溃
    1000 = "crash"       # Application Error（应用崩溃）
    1002 = "crash"       # Application Hang（应用挂起）
    1001 = "crash-wer"   # Windows Error Reporting
    # 网络
    4202 = "network"     # TCP/IP 无法访问 DHCP 服务器
    4201 = "network"     # 网络适配器检测到连接丢失
}

$filterXml = @"
<QueryList>
  <Query Id="0" Path="System">
    <Select Path="System">
      *[System[(EventID=42 or EventID=1 or EventID=107 or EventID=1074 or EventID=1076 or EventID=6005 or EventID=6006 or EventID=6008 or EventID=41) 
         and TimeCreated[@SystemTime&gt;='$($start.ToUniversalTime().ToString('o'))' and @SystemTime&lt;='$($end.ToUniversalTime().ToString('o'))']]]
    </Select>
  </Query>
  <Query Id="1" Path="Application">
    <Select Path="Application">
      *[System[(EventID=1000 or EventID=1002 or EventID=1001) 
         and TimeCreated[@SystemTime&gt;='$($start.ToUniversalTime().ToString('o'))' and @SystemTime&lt;='$($end.ToUniversalTime().ToString('o'))']]]
    </Select>
  </Query>
  <Query Id="2" Path="Microsoft-Windows-Tcpip/Operational">
    <Select Path="Microsoft-Windows-Tcpip/Operational">
      *[System[(EventID=4202 or EventID=4201) 
         and TimeCreated[@SystemTime&gt;='$($start.ToUniversalTime().ToString('o'))' and @SystemTime&lt;='$($end.ToUniversalTime().ToString('o'))']]]
    </Select>
  </Query>
</QueryList>
"@

try {
    $events = Get-WinEvent -FilterXml $filterXml -ErrorAction SilentlyContinue
} catch {
    Write-Host "Warning: Get-WinEvent failed: $_" -ForegroundColor Yellow
    $events = @()
}

if ($events.Count -eq 0) {
    Write-Host "No events found in time range." -ForegroundColor Yellow
    exit 0
}

# 输出 CSV 格式（与 collect_rpa_logs.ps1 兼容，cross_analysis.py 能直接解析）
Write-Host "TimeCreated,Level,EventID,Source,Message"
foreach ($evt in ($events | Sort-Object TimeCreated)) {
    $time = $evt.TimeCreated.ToString("yyyy-MM-dd HH:mm:ss")
    $level = $evt.LevelDisplayName
    $id = $evt.Id
    $source = $evt.ProviderName
    $msg = ($evt.Message -replace "`r`n", " " -replace "`n", " " -replace '"', '""').Substring(0, [Math]::Min(200, $evt.Message.Length))
    
    # 添加分类标签
    $cat = if ($signatures.ContainsKey($id)) { $signatures[$id] } else { "other" }
    
    Write-Host "`"$time`",`"$level`",`"$id`",`"$source`",`"[$cat] $msg`""
}

Write-Host ""
Write-Host "Total: $($events.Count) events" -ForegroundColor Green
