<#
  jm_host_cache_diag.ps1
  京麦客户端（jdm_dd_workbench / JMWorkStation）进程与缓存目录诊断脚本
  用途：在 RPA 主机 DESKTOP-0G61IMR（或任意京麦客服主机）上以当前用户运行，
        输出：①京麦相关进程及内存占用 ②京麦缓存/安装目录大小 ③最大子目录 ④最大文件。
  背景：设备 a728303767f142a3a1cda63fa7432023 账号 斑头雁-韦丹华 2026-09-23 早间
        启动失败复盘 —— 京麦启动自检命中"缓存超载提醒"，自动清理耗时约 24 秒，
        主窗口延迟出现导致 RPA 30 秒探测超时反复重启。本脚本用于钉死缓存实际规模。
  用法（在主机上运行）：
    powershell -NoProfile -ExecutionPolicy Bypass -File jm_host_cache_diag.ps1
  输出：桌面 jm_diag_<时间戳>/jm_diag.txt（同时打印到屏幕），请把 jm_diag.txt 内容回传。
#>
$ErrorActionPreference = 'SilentlyContinue'
$ProgressPreference    = 'SilentlyContinue'

$out = Join-Path ([Environment]::GetFolderPath('Desktop')) ("jm_diag_{0}" -f (Get-Date -Format 'yyyyMMdd_HHmmss'))
New-Item -ItemType Directory -Force -Path $out | Out-Null
$lines = New-Object System.Collections.Generic.List[string]

$lines.Add('========== 京麦相关进程（当前运行） ==========')
$procs = @(Get-Process | Where-Object { $_.ProcessName -match 'jdm_dd_workbench|JMWorkStation|JDWorkStation|JingDong|jdwb' })
if ($procs.Count -eq 0) {
  $lines.Add('(未发现京麦相关进程)')
} else {
  foreach ($p in $procs) {
    $path = ''; try { $path = $p.Path } catch {}
    $start = ''; try { $start = $p.StartTime.ToString('yyyy-MM-dd HH:mm:ss') } catch {}
    $lines.Add(('{0,-24} PID={1,-7} 内存(WS)={2,8:N1} MB  CPU累计={3,7:N0}s  启动={4}  路径={5}' -f $p.ProcessName, $p.Id, ($p.WorkingSet64/1MB), $p.CPU, $start, $path))
  }
}

$dirs = @(
  (Join-Path $env:USERPROFILE 'Documents\JingDong'),
  (Join-Path $env:USERPROFILE 'AppData\Local\JDWorkStation'),
  (Join-Path $env:USERPROFILE 'AppData\Local\jingdong'),
  (Join-Path $env:USERPROFILE 'AppData\Local\JingDong'),
  (Join-Path $env:USERPROFILE 'AppData\Roaming\JingDong'),
  (Join-Path $env:USERPROFILE 'AppData\Roaming\JDWorkStation'),
  'C:\JDWorkStation'
)

$lines.Add('')
$lines.Add('========== 京麦缓存/安装目录总大小 ==========')
foreach ($d in $dirs) {
  if (Test-Path $d) {
    $sz = (Get-ChildItem $d -Recurse -File -ErrorAction SilentlyContinue | Measure-Object -Property Length -Sum).Sum
    $lines.Add(('{0,-72} {1,10:N1} MB' -f $d, ($sz/1MB)))
  } else {
    $lines.Add(('{0,-72} (不存在)' -f $d))
  }
}

$lines.Add('')
$lines.Add('========== Documents\JingDong 下最大的 20 个子目录 ==========')
$jdRoot = Join-Path $env:USERPROFILE 'Documents\JingDong'
if (Test-Path $jdRoot) {
  $subs = Get-ChildItem $jdRoot -Directory -ErrorAction SilentlyContinue | ForEach-Object {
    $sz = (Get-ChildItem $_.FullName -Recurse -File -ErrorAction SilentlyContinue | Measure-Object -Property Length -Sum).Sum
    [pscustomobject]@{ Dir = $_.Name; MB = [math]::Round($sz/1MB,1) }
  } | Sort-Object MB -Descending | Select-Object -First 20
  if ($subs) { foreach ($s in $subs) { $lines.Add(('{0,-60} {1,10:N1} MB' -f $s.Dir, $s.MB)) } } else { $lines.Add('(无子目录)') }
}

$lines.Add('')
$lines.Add('========== 京麦相关目录下最大的 30 个文件 ==========')
$topFiles = New-Object System.Collections.Generic.List[object]
foreach ($d in $dirs) {
  if (Test-Path $d) {
    Get-ChildItem $d -Recurse -File -ErrorAction SilentlyContinue | ForEach-Object {
      if ($topFiles.Count -lt 60) { $topFiles.Add($_) } 
    }
  }
}
$topFiles | Sort-Object Length -Descending | Select-Object -First 30 | ForEach-Object {
  $lines.Add(('{0,10:N1} MB  {1}' -f ($_.Length/1MB), $_.FullName))
}

$outFile = Join-Path $out 'jm_diag.txt'
$lines | Out-File -FilePath $outFile -Encoding UTF8

Write-Host '========== 京麦进程/缓存诊断结果 =========='
$lines | ForEach-Object { Write-Host $_ }
Write-Host ''
Write-Host ("结果已保存: {0}" -f $outFile)
Write-Host '请把 jm_diag.txt 的内容回传给我继续分析。'
