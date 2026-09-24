<#
  host-events.ps1
  Extract Windows event log entries for cross-analysis.
  Minimal script for ECD remote execution (RunCommand has 24KB output cap; this produces ~5-15KB).

  定位: 第④源「主机事件日志」的 ECD 极简采集脚本（RunCommand 24KB 输出上限优化版）。
        scripts/collect_host_events.ps1 是更完整的采集器（含 CSV 工件 + summary）；
        本脚本输出更精简，适合经 ECD 远程拉起后直接喂 cross_analysis --host-bundle。
        注意: 本文件位于 cli/templates/，不随 npm/zip 分发包复制（打包只带根 templates/ 的
        rpa_log_report.html）；需要时从源码目录手动拷贝，或直接用 scripts/collect_host_events.ps1
        （该文件会进包）。host_events_query.py 的 parse_ecd_text() 同时兼容两种输出格式。

  Outputs structured text lines (one event per line) parseable by cross_analysis.py --host-bundle:
    2026-09-18 10:35:12  ID=6005 [Microsoft-Windows-EventLog] 信息 The Event log service was started.
    2026-09-18 23:15:00  ID=42   [Microsoft-Windows-Kernel-Power] 信息 The system is entering sleep ...

  Usage (local test):
    powershell -NoProfile -ExecutionPolicy Bypass -File host-events.ps1 -Days 7
  Usage (ECD remote — recommended):
    csdbg host-pull <desktopId> <本脚本完整路径> [timeoutSec] [--save host.txt]
    （csdbg host-pull 的参数为 <desktopId> <scriptPath.ps1> [timeout] [--save]；
       -Days / FocusStart / FocusEnd 需在脚本顶部 param 中调整）
#>
[CmdletBinding()]
param(
  [int]$Days = 7,
  [string]$FocusStart = '',
  [string]$FocusEnd = ''
)
$ErrorActionPreference = 'SilentlyContinue'
$ProgressPreference    = 'SilentlyContinue'
$since = (Get-Date).AddDays(-$Days)

function Emit($e) {
  $t   = $e.TimeCreated.ToString('yyyy-MM-dd HH:mm:ss')
  $id  = $e.Id
  $prov= $e.ProviderName
  $lvl = $e.LevelDisplayName
  $msg = if ($e.Message) { ($e.Message -replace '\s+', ' ').Substring(0, [Math]::Min(120, $e.Message.Length)) } else { '' }
  Write-Output "$t  ID=$id [$prov] $lvl $msg"
}

Write-Output "# host-events.ps1 @ $env:COMPUTERNAME  user=$env:USERNAME  collected=$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
Write-Output "# os uptime since: $((Get-CimInstance Win32_OperatingSystem).LastBootUpTime)"
Write-Output "# days scanned: $Days (since $since)"
if ($FocusStart -and $FocusEnd) {
  Write-Output "# focus window: $FocusStart ~ $FocusEnd"
}
Write-Output ""

# [1] System log: power/boot + network + service crash
Write-Output "# === SYSTEM LOG ==="
$sysEv = @(Get-WinEvent -MaxEvents 50000 -FilterHashtable @{LogName='System'; StartTime=$since})

$powerProv = @('Microsoft-Windows-Kernel-Power','Microsoft-Windows-Power-Troubleshooter','User32','EventLog','Microsoft-Windows-Kernel-General','Microsoft-Windows-Kernel-Boot')
$powerIds  = @(41,42,84,86,107,125,130,131, 1, 1074,6005,6006,6008,6013, 12,13, 27,32)
$netProv   = @('Microsoft-Windows-Dhcp-Client','Microsoft-Windows-TCPIP','Microsoft-Windows-NetworkProfile','Microsoft-Windows-NlaSvc','e1dexpress','rt640x64','igcc','NetBT','NDIS','Microsoft-Windows-WLAN-AutoConfig')
$svcIds    = @(7000,7009,7011,7022,7023,7031,7034,7036,7045)

$QPats = "qianniu|aliworkbench|wangwang|aliim|workbench"
$RPats = "rpa|robot|bty|betteryeah|csagent|agent-client"
$AllPats = "$QPats|$RPats"

$power   = @($sysEv | Where-Object { ($powerProv -contains $_.ProviderName -or $_.ProviderName -like '*Power*') -and ($powerIds -contains $_.Id) })
$network = @($sysEv | Where-Object { ($netProv -contains $_.ProviderName -or $_.ProviderName -like '*Tcpip*' -or $_.ProviderName -like '*Dhcp*' -or $_.ProviderName -like '*WLAN*') })
$services= @($sysEv | Where-Object { $_.ProviderName -eq 'Service Control Manager' -and ($svcIds -contains $_.Id) -and ($_.Message -match $AllPats) })

Write-Output "# power/boot events (sleep/wake=42/107, reboot=6005/6006/6008/1074/41): n=$($power.Count)"
$power   | Sort-Object TimeCreated | ForEach-Object { Emit $_ }
Write-Output "# network events (NIC/dhcp/wlan): n=$($network.Count)"
$network | Sort-Object TimeCreated | ForEach-Object { Emit $_ }
Write-Output "# qianniu/rpa service crash: n=$($services.Count)"
$services| Sort-Object TimeCreated | ForEach-Object { Emit $_ }

# [2] Application log: crash/hang
Write-Output ""
Write-Output "# === APPLICATION LOG ==="
$appEv    = @(Get-WinEvent -MaxEvents 50000 -FilterHashtable @{LogName='Application'; StartTime=$since})
$appProv  = @('Application Error','Application Hang','Windows Error Reporting','.NET Runtime')
$crashAll = @($appEv | Where-Object { $appProv -contains $_.ProviderName })
$crashHit = @($crashAll | Where-Object { $_.Message -match $AllPats })

Write-Output "# app crash (all procs): n=$($crashAll.Count)"
$crashAll | Sort-Object TimeCreated | ForEach-Object { Emit $_ }
Write-Output "# app crash (qianniu/rpa only): n=$($crashHit.Count)"
$crashHit | Sort-Object TimeCreated | ForEach-Object { Emit $_ }

# [3] Focus window dump (if requested)
if ($FocusStart -and $FocusEnd) {
  try {
    $f0 = [datetime]::Parse($FocusStart)
    $f1 = [datetime]::Parse($FocusEnd)
    Write-Output ""
    Write-Output "# === FOCUS WINDOW raw events ==="
    $fw = @($sysEv + $appEv) | Where-Object { $_.TimeCreated -ge $f0 -and $_.TimeCreated -le $f1 } | Sort-Object TimeCreated
    Write-Output "# events in focus window: n=$($fw.Count)"
    $fw | ForEach-Object { Emit $_ }
  } catch {
    Write-Output "# focus window parse failed: $_"
  }
}

Write-Output ""
Write-Output "# END host-events.ps1"
