# CS-Debug-Toolkit 一键初始化
# 用法: powershell -ExecutionPolicy Bypass -File .\setup.ps1
$ErrorActionPreference = 'Continue'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Write-Host "== CS-Debug-Toolkit 初始化 -> $root ==" -ForegroundColor Cyan

# 1. 环境变量 CS_TOOLKIT_HOME（skill 里的 <TOOLKIT> 指向这里）
[Environment]::SetEnvironmentVariable('CS_TOOLKIT_HOME', $root, 'User')
$env:CS_TOOLKIT_HOME = $root
Write-Host "[1/6] 已设置用户环境变量 CS_TOOLKIT_HOME=$root" -ForegroundColor Green

# 2. Python 依赖
$py = $null
foreach ($c in @('python', 'py')) { if (Get-Command $c -ErrorAction SilentlyContinue) { $py = $c; break } }
if ($py) {
  & $py -m pip install -r (Join-Path $root 'requirements.txt') --quiet
  if ($LASTEXITCODE -eq 0) { Write-Host "[2/6] Python 依赖安装完成 (aliyun-log-python-sdk)" -ForegroundColor Green }
  else { Write-Host "[2/6] pip 安装失败，请手动执行: $py -m pip install -r requirements.txt" -ForegroundColor Yellow }
} else {
  Write-Host "[2/6] 未找到 python/py，请先安装 Python 3.9+ 并加入 PATH" -ForegroundColor Yellow
}

# 3. cs-cli (BetterYeah 客服平台 CLI)
if (Get-Command cs-cli -ErrorAction SilentlyContinue) {
  Write-Host "[3/6] cs-cli 已安装" -ForegroundColor Green
} elseif (Get-Command npm -ErrorAction SilentlyContinue) {
  npm install -g @bty/customer-service-cli
  Write-Host "[3/6] cs-cli 安装完成（未登录的话下一步处理）" -ForegroundColor Green
} else {
  Write-Host "[3/6] 未找到 npm，请先安装 Node.js，再手动执行: npm install -g @bty/customer-service-cli" -ForegroundColor Yellow
}

# 3b. csdbg 入口（cli/bin/csdbg 软链到 PATH；Windows 用批处理 wrapper）
$csdbgBat = Join-Path $root 'cli\bin\csdbg.cmd'
$userBin = Join-Path $HOME 'bin'
if (-not (Test-Path $userBin)) { New-Item -ItemType Directory -Force -Path $userBin | Out-Null }
$wrapperPath = Join-Path $userBin 'csdbg.cmd'
@"
@echo off
set CSDBG_HOME=$root
set CSDBG_ECD_CONFIG=$root\scripts\ecd.json
node "$root\cli\bin\csdbg.js" %*
"@ | Out-File -Encoding ASCII $wrapperPath
$currentPath = [Environment]::GetEnvironmentVariable('Path', 'User')
if ($currentPath -notlike "*$userBin*") {
  [Environment]::SetEnvironmentVariable('Path', "$userBin;$currentPath", 'User')
  $env:Path = "$userBin;$env:Path"
  Write-Host "[3b/6] csdbg 已加入 PATH ($userBin)" -ForegroundColor Green
} else {
  Write-Host "[3b/6] csdbg 已在 PATH" -ForegroundColor Green
}

# 4. SLS 配置骨架（模板 -> channels.json，密钥需自己填）
$cfg = Join-Path $root 'scripts\channels.json'
if (-not (Test-Path $cfg)) {
  Copy-Item (Join-Path $root 'scripts\channels.example.json') $cfg
  Write-Host "[4/6] 已生成 scripts\channels.json —— 请填入你的 SLS 只读 AK（需 log:GetLogStoreLogs 权限）" -ForegroundColor Yellow
  notepad $cfg
} else {
  Write-Host "[4/6] scripts\channels.json 已存在，跳过（注意：含密钥，勿外传）" -ForegroundColor Green
}

# 4b. ECD 配置骨架（远程拉起主机日志时用；可选，与 SLS AK 分开管理）
$ecdCfg = Join-Path $root 'scripts\ecd.json'
if (-not (Test-Path $ecdCfg)) {
  @'
{
  "_comment": "ECD 远程执行 AK，需 ecd:RunCommand / ecd:DescribeInvocations 权限；与 SLS 只读 AK 分开管理，勿外传",
  "access_key_id": "YOUR_ECD_ACCESS_KEY_ID",
  "access_key_secret": "YOUR_ECD_ACCESS_KEY_SECRET",
  "region": "cn-hangzhou"
}
'@ | Out-File -Encoding UTF8 $ecdCfg
  Write-Host "[4b/6] 已生成 scripts\ecd.json —— 若需 csdbg host-pull 远程拉起主机日志，请填入 ECD AK（可选）" -ForegroundColor Yellow
} else {
  Write-Host "[4b/6] scripts\ecd.json 已存在" -ForegroundColor Green
}

New-Item -ItemType Directory -Force -Path (Join-Path $root 'temp') | Out-Null

# 5. 安装全部 agent skill（skill/ 下每个含 SKILL.md 的目录）
$skillsRoot = Join-Path $root 'skill'
$targets = @()
foreach ($dir in @("$HOME\.agents\skills", "$HOME\.claude\skills")) {
  if (Test-Path $dir) { $targets += $dir }
}
if (-not $targets) { $targets = @("$HOME\.agents\skills"); New-Item -ItemType Directory -Force -Path $targets[0] | Out-Null }
Get-ChildItem -Directory $skillsRoot | ForEach-Object {
  if (Test-Path (Join-Path $_.FullName 'SKILL.md')) {
    foreach ($t in $targets) {
      Copy-Item -Recurse -Force $_.FullName (Join-Path $t $_.Name)
    }
    Write-Host "[5/6] 技能已安装 -> $($targets -join ' 和 ')\$($_.Name)" -ForegroundColor Green
  }
}

# 6. 自检
Write-Host "[6/6] 自检:" -ForegroundColor Cyan
if ($py) { & $py (Join-Path $root 'scripts\rpa_log_query.py') --check }
& cs-cli auth whoami

Write-Host ""
Write-Host "== 剩下两件手动的事 ==" -ForegroundColor Cyan
Write-Host "  1) cs-cli 登录:  cs-cli auth login      （用你自己的 BetterYeah 账号）"
Write-Host "  2) 填好 channels.json 后验证:  python scripts\rpa_log_query.py --check"
Write-Host "可选: e-chat-trace 技能读环境变量 ALIYUN_ACCESS_KEY_ID / ALIYUN_ACCESS_KEY_SECRET，"
Write-Host "      如需用它请把只读 AK 写入这两个用户环境变量。"
Write-Host "完成后重启 agent 会话，直接说「结合多方日志分析 <会话ID> 这个问题」即可。"
