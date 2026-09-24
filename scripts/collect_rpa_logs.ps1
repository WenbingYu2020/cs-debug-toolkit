<#
  collect_rpa_logs.ps1
  Collect last N days of evidence from the customer-service RPA host:
    [1] Windows System event log  : sleep/wake, shutdown/boot, NIC/network, service crash
    [2] Windows Application log   : Application Error / Hang / WER (.dmp pointers), esp. Qianniu & RPA procs
    [3] Qianniu client logs       : copied from detected install dirs
    [4] RPA connector logs        : copied from detected install dirs (keyword-prescreened)
    [5] summary.txt + focus-window extraction + final zip
  Run on the RPA host bound to the affected account (hostname/equipment id from SLS
  robot-health-report lines). Admin not required for
  System/Application logs; recommended for full Program Files coverage.

  Usage:
    powershell -NoProfile -ExecutionPolicy Bypass -File collect_rpa_logs.ps1
    powershell ... -File collect_rpa_logs.ps1 -Days 7 -FocusStart "2026-09-18 10:30" -FocusEnd "2026-09-18 11:45"
  Send back:  the produced  RpaLogCollect_*.zip
#>
[CmdletBinding()]
param(
  [int]$Days = 7,
  [string]$FocusStart = '',
  [string]$FocusEnd = '',
  [string]$OutDir = '',
  [switch]$SkipFiles,                       # event-log-only quick run
  [string[]]$ExtraDir = @(),                # manually append app install/log dirs
  [int]$MaxFileMB  = 50,                    # per-file copy cap
  [int]$TotalCapMB = 800                    # total copy cap
)
$ErrorActionPreference = 'SilentlyContinue'
$ProgressPreference    = 'SilentlyContinue'
$since = (Get-Date).AddDays(-$Days)

# Chinese tokens are built via unescape so this file stays pure ASCII
# (PS 5.1 reads BOM-less .ps1 as ANSI; embedded Chinese would garble in patterns)
$CN_QIANNIU = [regex]::Unescape('\u5343\u725b')           # qianniu
$CN_BTY     = [regex]::Unescape('\u6591\u5934\u96c1')     # vendor name
$CN_JIEDAI  = [regex]::Unescape('\u63a5\u5f85')           # reception
$CN_LOG     = [regex]::Unescape('\u65e5\u5fd7')           # logs
$CN_DISCONN = [regex]::Unescape('\u65ad\u5f00|\u6389\u7ebf|\u91cd\u8fde')  # disconnect|dropped|reconnect
$CN_TIMEOUT = [regex]::Unescape('\u8d85\u65f6')           # timeout

$QPats  = "qianniu|aliworkbench|wangwang|aliim|workbench|$CN_QIANNIU"
$RPats  = "rpa|robot|bty|betteryeah|$CN_BTY|$CN_JIEDAI|csagent|agent-client"
$AllPats = "$QPats|$RPats"

if (-not $OutDir) {
  $OutDir = Join-Path ([Environment]::GetFolderPath('Desktop')) ("RpaLogCollect_{0}" -f (Get-Date -Format 'yyyyMMdd_HHmmss'))
}
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
$logStaging = Join-Path $OutDir 'collected_logs'
New-Item -ItemType Directory -Force -Path $logStaging | Out-Null

$fFocus = $null
if ($FocusStart -and $FocusEnd) {
  try { $fFocus = @([datetime]::Parse($FocusStart), [datetime]::Parse($FocusEnd)) } catch { Write-Host "focus window parse failed: $_" }
}

function EvRow($e, $maxLen) {
  $msg = if ($e.Message) { $e.Message -replace '\s+', ' ' } else { '' }
  if ($msg.Length -gt $maxLen) { $msg = $msg.Substring(0, $maxLen) + '...' }
  [pscustomobject]@{ Time=$e.TimeCreated; Id=$e.Id; Provider=$e.ProviderName; Level=$e.LevelDisplayName; Message=$msg }
}

Write-Host "[1/5] Reading System event log since $since ..."
$sysEv = @(Get-WinEvent -MaxEvents 300000 -FilterHashtable @{LogName='System'; StartTime=$since} )

$powerProv = @('Microsoft-Windows-Kernel-Power','Microsoft-Windows-Power-Troubleshooter','User32','EventLog','Microsoft-Windows-Kernel-General','Microsoft-Windows-Kernel-Boot')
$powerIds  = @(41,42,84,86,107,125,130,131, 1, 1074,6005,6006,6008,6013, 12,13, 27,32)
$netProv   = @('Microsoft-Windows-Dhcp-Client','Microsoft-Windows-TCPIP','Microsoft-Windows-NetworkProfile','Microsoft-Windows-NlaSvc','e1dexpress','rt640x64','igcc','NetBT','NDIS','Microsoft-Windows-WLAN-AutoConfig')
$svcIds    = @(7000,7009,7011,7022,7023,7031,7034,7036,7045)

$power  = @($sysEv | Where-Object { ($powerProv -contains $_.ProviderName -or $_.ProviderName -like '*Power*' -or $_.ProviderName -eq 'User32') -and ($powerIds -contains $_.Id) })
$network= @($sysEv | Where-Object { ($netProv -contains $_.ProviderName -or $_.ProviderName -like '*Tcpip*' -or $_.ProviderName -like '*Dhcp*' -or $_.ProviderName -like '*NetworkProfile*' -or $_.ProviderName -like '*WLAN*') })
$services=@($sysEv | Where-Object { $_.ProviderName -eq 'Service Control Manager' -and ($svcIds -contains $_.Id) -and ($_.Message -match $AllPats) })
$allSvc  = @($sysEv | Where-Object { $_.ProviderName -eq 'Service Control Manager' -and (7031,7034,7000,7009,7011,7022 -contains $_.Id) })

$power   | ForEach-Object { EvRow $_ 300 } | Sort-Object Time | Export-Csv (Join-Path $OutDir '01_system_power_boot.csv')   -NoTypeInformation -Encoding UTF8
$network | ForEach-Object { EvRow $_ 300 } | Sort-Object Time | Export-Csv (Join-Path $OutDir '02_system_network.csv')      -NoTypeInformation -Encoding UTF8
$services| ForEach-Object { EvRow $_ 300 } | Sort-Object Time | Export-Csv (Join-Path $OutDir '03_system_service_rpa_qn.csv') -NoTypeInformation -Encoding UTF8
$allSvc  | ForEach-Object { EvRow $_ 300 } | Sort-Object Time | Export-Csv (Join-Path $OutDir '03b_system_service_all_crash.csv') -NoTypeInformation -Encoding UTF8

Write-Host "[2/5] Reading Application event log ..."
$appEv  = @(Get-WinEvent -MaxEvents 300000 -FilterHashtable @{LogName='Application'; StartTime=$since})
$appProv= @('Application Error','Application Hang','Windows Error Reporting','.NET Runtime','Windows Error Reporting')
$crashAll = @($appEv | Where-Object { $appProv -contains $_.ProviderName })
$crashHit = @($crashAll | Where-Object { $_.Message -match $AllPats })
$crashAll | ForEach-Object { EvRow $_ 400 } | Sort-Object Time | Export-Csv (Join-Path $OutDir '04_app_crash_all.csv')    -NoTypeInformation -Encoding UTF8
$crashHit | ForEach-Object { EvRow $_ 400 } | Sort-Object Time | Export-Csv (Join-Path $OutDir '04b_app_crash_qianniu_rpa.csv') -NoTypeInformation -Encoding UTF8

# uptime / sleep gap reconstruction helper
$boots = @($power | Where-Object { ($_.Id -in 6005,12,27) -or ($_.ProviderName -eq 'EventLog' -and $_.Id -eq 6005) })
$power | ForEach-Object { EvRow $_ 200 } | Sort-Object Time | Select-Object -Last 60 |
  Export-Csv (Join-Path $OutDir '05_power_recent60.csv') -NoTypeInformation -Encoding UTF8

$foundDirs = New-Object System.Collections.Generic.List[string]
$dirSource = New-Object System.Collections.Generic.List[string]
$procHints = @()
$lnkReport = @()
if (-not $SkipFiles) {
  Write-Host "[3/5] Resolving RPA / Qianniu install dirs (desktop shortcuts -> registry -> procs -> pattern scan) ..."
  function Add-Dir($dir, $why) {
    if ($dir -and (Test-Path $dir)) {
      $norm = (Resolve-Path $dir).Path.TrimEnd('\')
      if ($norm -and -not $foundDirs.Contains($norm)) {
        $foundDirs.Add($norm) | Out-Null
        $dirSource.Add("  $norm  <- $why") | Out-Null
      }
    }
  }

  # hint 0: operator-supplied dirs
  foreach ($e in $ExtraDir) { Add-Dir $e "manual -ExtraDir" }

  # hint 1: DESKTOP SHORTCUTS — ground truth even when install path moved / app renamed.
  $shell = New-Object -ComObject WScript.Shell
  $desktopPaths = @([Environment]::GetFolderPath('Desktop'),
                    [Environment]::GetFolderPath('CommonDesktopDirectory'),
                    (Join-Path $env:USERPROFILE 'OneDrive\Desktop'),
                    (Join-Path $env:USERPROFILE 'OneDrive\桌面'))
  foreach ($dp in ($desktopPaths | Where-Object { Test-Path $_ } | Select-Object -Unique)) {
    foreach ($lnk in (Get-ChildItem $dp -Filter *.lnk -EA SilentlyContinue)) {
      $sc = $shell.CreateShortcut($lnk.FullName)
      $tp = $sc.TargetPath; $wd = $sc.WorkingDirectory
      $lnkReport += "  [$($lnk.DirectoryName)] $($lnk.BaseName) -> '$tp' (workdir='$wd')"
      $hit = ($lnk.BaseName -match $AllPats) -or ($tp -match $AllPats) -or ($wd -match $AllPats)
      if ($hit) {
        if ($tp -and (Test-Path $tp)) {
          Add-Dir (Split-Path $tp -Parent) "desktop shortcut '$($lnk.BaseName)'"
          # Electron / packaged apps keep data in %APPDATA%\%LOCALAPPDATA% named after the exe
          $exeName = [IO.Path]::GetFileNameWithoutExtension($tp)
          Add-Dir (Join-Path $env:APPDATA $exeName)     "appdata by exe name ($exeName)"
          Add-Dir (Join-Path $env:LOCALAPPDATA $exeName) "localappdata by exe name ($exeName)"
        }
        if ($wd) { Add-Dir $wd "shortcut working dir '$($lnk.BaseName)'" }
      }
    }
  }
  # also: any shortcut whose target EXE sits in a dir with 'log' subdir (name-blind catch)
  foreach ($dp in ($desktopPaths | Where-Object { Test-Path $_ } | Select-Object -Unique)) {
    foreach ($lnk in (Get-ChildItem $dp -Filter *.lnk -EA SilentlyContinue)) {
      $sc = $shell.CreateShortcut($lnk.FullName)
      if ($sc.TargetPath -and (Test-Path $sc.TargetPath)) {
        $d = Split-Path $sc.TargetPath -Parent
        if (Test-Path (Join-Path $d 'logs') -PathType Container -EA SilentlyContinue) {
          # only if dir also looks like an app root (has exe siblings), to avoid office-style dirs
          $exes = @(Get-ChildItem $d -Filter *.exe -EA SilentlyContinue | Where-Object { $_.Name -match $AllPats })
          if ($exes.Count -gt 0) { Add-Dir $d "desktop shortcut with sibling app exe + logs/ ($($exes[0].Name))" }
        }
      }
    }
  }

  # hint 2: uninstall registry InstallLocation
  $regPaths = 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*',
              'HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*',
              'HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*'
  foreach ($rp in $regPaths) {
    Get-ItemProperty $rp -EA SilentlyContinue | ForEach-Object {
      if (($_.DisplayName -match $AllPats -or $_.Publisher -match $AllPats) -and $_.InstallLocation) {
        Add-Dir $_.InstallLocation "registry uninstall entry '$($_.DisplayName)'"
      }
    }
  }

  # hint 3: live processes and services reveal install paths
  $procHints = @(Get-Process | Where-Object { $_.Path -or $_.Name -match $AllPats } |
                 Where-Object { $_.Name -match $AllPats } |
                 Select-Object Name, Id, @{n='Path';e={$_.Path}} | Format-Table -AutoSize | Out-String)
  foreach ($p in (Get-Process -EA SilentlyContinue | Where-Object { $_.Name -match $AllPats -and $_.Path })) {
    Add-Dir (Split-Path $p.Path -Parent) "live process '$($p.Name)'"
  }
  $svcHints = @(Get-CimInstance Win32_Service -EA SilentlyContinue |
                Where-Object { $_.Name -match $AllPats -or $_.DisplayName -match $AllPats } |
                Select-Object Name, State, StartName, PathName | Format-Table -AutoSize -Wrap | Out-String)
  foreach ($s in (Get-CimInstance Win32_Service -EA SilentlyContinue | Where-Object { $_.PathName -match $AllPats })) {
    $m = [regex]::Match($s.PathName, '"?([^"]+\.exe)"?')
    if ($m.Success -and (Test-Path $m.Groups[1].Value)) { Add-Dir (Split-Path $m.Groups[1].Value -Parent) "service '$($s.Name)' binary" }
  }

  # fallback hint 4: candidate roots, directory-name pattern match (depth 2, cheap)
  $roots = @($env:APPDATA, $env:LOCALAPPDATA, $env:ProgramData,
             ${env:ProgramFiles}, ${env:ProgramFiles(x86)}, 'C:\', 'D:\', 'E:\')
  foreach ($r in $roots) {
    if (-not (Test-Path $r)) { continue }
    try {
      $depth = if ($r -in @('C:\','D:\','E:\')) { 1 } else { 2 }
      Get-ChildItem -Path $r -Directory -Depth $depth -EA Stop |
        Where-Object { $_.FullName -notmatch 'Windows\\|Package Cache' -and ($_.Name -match $AllPats) } |
        ForEach-Object { Add-Dir $_.FullName "name pattern scan under $r" }
    } catch {}
  }

  # collect *.log|txt|json|csv|dmp modified within window from log-ish subdirs
  $totalBytes = 0; $capBytes = $TotalCapMB * 1MB; $copied = 0
  foreach ($d in $foundDirs) {
    $cand = @()
    try {
      $cand = Get-ChildItem -Path $d -Recurse -File -EA Stop |
              Where-Object { ($_.Extension -match '^\.(log|txt|json|csv|dmp)$') -and $_.LastWriteTime -ge $since }
    } catch {}
    foreach ($f in $cand) {
      if ($f.Length -gt ($MaxFileMB*1MB)) { continue }
      if (($totalBytes + $f.Length) -gt $capBytes) { Write-Host "  total cap ${TotalCapMB}MB reached, stop copying"; break }
      $flat = ($f.FullName -replace '[:\\]','-' )
      Copy-Item $f.FullName -Destination (Join-Path $logStaging $flat)
      $totalBytes += $f.Length; $copied++
    }
  }
  # user crash dumps
  foreach ($cd in @((Join-Path $env:LOCALAPPDATA 'CrashDumps'), (Join-Path $env:APPDATA "$CN_QIANNIU\crash"), (Join-Path $env:APPDATA 'AliWorkbench'))) {
    if (Test-Path $cd) {
      Get-ChildItem $cd -Recurse -File -EA SilentlyContinue | Where-Object { $_.LastWriteTime -ge $since -and $_.Length -lt ($MaxFileMB*1MB) } |
        ForEach-Object { Copy-Item $_.FullName -Destination (Join-Path $logStaging ('crashdump-' + ($_.FullName -replace '[:\\]','-'))); $copied++ }
    }
  }
  Write-Host "  found dirs: $($foundDirs.Count), copied files: $copied"

  Write-Host "[4/5] Keyword pre-screen on collected logs ..."
  $kwPattern = "disconnect|reconnect|offline|online|heartbeat|timeout|error|exception|fail|retries|retry|login|logout|closed|socket|$CN_DISCONN|$CN_TIMEOUT"
  $hits = @()
  $logFiles = Get-ChildItem $logStaging -File | Where-Object { $_.Extension -ne '.dmp' }
  foreach ($f in $logFiles) {
    $m = Select-String -Path $f.FullName -Pattern $kwPattern -AllMatches -EA SilentlyContinue |
         Select-Object -First 400
    foreach ($x in $m) {
      $line = $x.Line -replace '\s+',' '
      if ($line.Length -gt 240) { $line = $line.Substring(0,240) }
      $hits += [pscustomobject]@{ File=$f.Name; LineNo=$x.LineNumber; Text=$line }
    }
  }
  $hits | Export-Csv (Join-Path $OutDir '06_log_keyword_hits.csv') -NoTypeInformation -Encoding UTF8
}

Write-Host "[5/5] Writing summary ..."
$sb = New-Object System.Text.StringBuilder
[void]$sb.AppendLine("host            : $env:COMPUTERNAME  user: $env:USERNAME  collected: $(Get-Date)")
[void]$sb.AppendLine("os uptime since : $((Get-CimInstance Win32_OperatingSystem).LastBootUpTime)   (if within window and focus gap predates boot -> host rebooted)")
[void]$sb.AppendLine("days scanned    : $Days (since $since)")
if ($fFocus) { [void]$sb.AppendLine("focus window    : $($fFocus[0]) ~ $($fFocus[1])") }
[void]$sb.AppendLine("")
[void]$sb.AppendLine("== power/boot events by day (sleep=42/107, reboot=6005/6006/6008/1074/41) ==")
$power | Group-Object { $_.TimeCreated.ToString('yyyy-MM-dd') } | Sort-Object Name |
  ForEach-Object { [void]$sb.AppendLine(("{0}  n={1}" -f $_.Name, $_.Count)) }
[void]$sb.AppendLine("")
[void]$sb.AppendLine("== network events by day (NIC/dhcp/wlan drop&renew) ==")
$network | Group-Object { $_.TimeCreated.ToString('yyyy-MM-dd') } | Sort-Object Name |
  ForEach-Object { [void]$sb.AppendLine(("{0}  n={1}" -f $_.Name, $_.Count)) }
[void]$sb.AppendLine("")
[void]$sb.AppendLine("== qianniu/rpa crash events by day (Application Error/Hang/WER) ==")
$crashHit | Group-Object { $_.TimeCreated.ToString('yyyy-MM-dd') } | Sort-Object Name |
  ForEach-Object { [void]$sb.AppendLine(("{0}  n={1}" -f $_.Name, $_.Count)) }
[void]$sb.AppendLine("")
if (-not $SkipFiles) {
  [void]$sb.AppendLine("== desktop shortcuts (all, for manual cross-check) ==")
  $lnkReport | ForEach-Object { [void]$sb.AppendLine($_) }
  [void]$sb.AppendLine("")
  [void]$sb.AppendLine("== resolved install/log dirs and why ==")
  $dirSource | ForEach-Object { [void]$sb.AppendLine($_) }
  [void]$sb.AppendLine("")
  [void]$sb.AppendLine("== live procs ==");  [void]$sb.AppendLine($procHints -join "`n")
  [void]$sb.AppendLine("== rpa/qianniu services =="); [void]$sb.AppendLine($svcHints -join "`n")
}
if ($fFocus) {
  [void]$sb.AppendLine("== FOCUS WINDOW raw event dump ==")
  $fw = @($sysEv + $appEv) | Where-Object { $_.TimeCreated -ge $fFocus[0] -and $_.TimeCreated -le $fFocus[1] } | Sort-Object TimeCreated
  foreach ($e in $fw) {
    $msg = if ($e.Message) { ($e.Message -replace '\s+',' ').Substring(0, [Math]::Min(160, ($e.Message -replace '\s+',' ').Length)) } else { '' }
    [void]$sb.AppendLine(("{0} [{1}/{2}] {3}" -f $e.TimeCreated.ToString('MM-dd HH:mm:ss'), $e.ProviderName, $e.Id, $msg))
  }
  [void]$sb.AppendLine("== FOCUS WINDOW log-line hits ==")
  if (Test-Path (Join-Path $OutDir '06_log_keyword_hits.csv')) {
    $fd0 = $fFocus[0].ToString('yyyy-MM-dd'); $fd1 = $fFocus[1].ToString('yyyy-MM-dd')
    Import-Csv (Join-Path $OutDir '06_log_keyword_hits.csv') | ForEach-Object {
      $dm = [regex]::Match($_.Text, '\d{4}[-/]\d{2}[-/]\d{2}')
      if ($dm.Success) {
        $d = $dm.Value -replace '/', '-'
        if ($d -ge $fd0 -and $d -le $fd1) { [void]$sb.AppendLine(("{0}:{1} {2}" -f $_.File, $_.LineNo, $_.Text)) }
      }
    }
  }
}
$sumFile = Join-Path $OutDir 'summary.txt'
[System.IO.File]::WriteAllText($sumFile, $sb.ToString(), [System.Text.Encoding]::UTF8)

$zip = "$OutDir.zip"
if (Test-Path $zip) { Remove-Item $zip -Force }
Compress-Archive -Path (Join-Path $OutDir '*') -DestinationPath $zip

Write-Host ""
Write-Host "DONE. package: $zip" -ForegroundColor Green
Write-Host "Send this zip back to the analysis side." 
