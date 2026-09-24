# build_cli.ps1 — 从 cs-cli 单源组装 npm 包 (cs-debug-toolkit) 并产 tgz
# 用法: powershell -ExecutionPolicy Bypass -File .\build_cli.ps1 [-SkipPack] [-Strict]
# 产物: dist\npm\  (包目录)  +  dist\cs-debug-toolkit-<version>.tgz
param([switch]$SkipPack, [switch]$Strict)
$ErrorActionPreference = 'Stop'
$src   = Split-Path -Parent $MyInvocation.MyCommand.Path        # cs-cli 功能区根目录
$stage = Join-Path $src 'dist\npm'
$dist  = Join-Path $src 'dist'

Write-Host "== 组装 npm 包 cs-debug-toolkit ==" -ForegroundColor Cyan
Write-Host "源: $src"

# 0a. git 未提交检测：产物可能不含最新内容（警告不阻断；-Strict 可阻断）
$gitDirty = $false
if (Test-Path (Join-Path $src '.git')) {
  $gitStatus = & git -C $src status --porcelain 2>$null
  if ($LASTEXITCODE -eq 0 -and $gitStatus) {
    $gitDirty = $true
    Write-Host "⚠ git 工作区有未提交改动（$($gitStatus.Count) 项），产物可能不含最新内容" -ForegroundColor Yellow
  }
}
if ($gitDirty -and $Strict) { throw "检测到未提交改动且指定 -Strict，终止打包" }

# 0. 清空暂存区
if (Test-Path $stage) { Remove-Item -Recurse -Force $stage }
New-Item -ItemType Directory -Force -Path $stage | Out-Null

# 1. CLI 骨架（package.json / bin / lib / README）
Copy-Item (Join-Path $src 'cli\package.json') $stage
Copy-Item (Join-Path $src 'cli\README.md')    $stage
Copy-Item -Recurse (Join-Path $src 'cli\bin') $stage
Copy-Item -Recurse (Join-Path $src 'cli\lib') $stage

# 2. scripts/ —— 只要 py + 采集器(.ps1) + 配置模板；channels.json(密钥)/leak_patterns.json(个人模式)/legacy/__pycache__ 永不入包
New-Item -ItemType Directory -Force -Path (Join-Path $stage 'scripts') | Out-Null
Copy-Item (Join-Path $src 'scripts\*.py')                       (Join-Path $stage 'scripts')
Copy-Item (Join-Path $src 'scripts\*.ps1')                      (Join-Path $stage 'scripts')
Copy-Item (Join-Path $src 'scripts\channels.example.json')      (Join-Path $stage 'scripts')
Copy-Item (Join-Path $src 'scripts\leak_patterns.example.json') (Join-Path $stage 'scripts')

# 3. skill/ —— 所有含 SKILL.md 的技能目录（含 references）
New-Item -ItemType Directory -Force -Path (Join-Path $stage 'skill') | Out-Null
$skillCount = 0
Get-ChildItem -Directory (Join-Path $src 'skill') | Where-Object {
  Test-Path (Join-Path $_.FullName 'SKILL.md')
} | ForEach-Object {
  Copy-Item -Recurse $_.FullName (Join-Path $stage 'skill')
  $skillCount++
}

# 4. templates/（HTML 报告模板）
Copy-Item -Recurse (Join-Path $src 'templates') $stage

# 4b. docs/（排障文档等，随包分发便于新手自助）
New-Item -ItemType Directory -Force -Path (Join-Path $stage 'docs') | Out-Null
Copy-Item (Join-Path $src 'docs\troubleshooting.md') (Join-Path $stage 'docs')

# 5. 质量门 A：package.json 结构 + bin 目标存在
#    (显式 -Encoding UTF8：package.json 无 BOM，PS 5.1 默认按 ANSI 读会把中文读乱)
$pkg = Get-Content (Join-Path $stage 'package.json') -Raw -Encoding UTF8 | ConvertFrom-Json
if (-not $pkg.name -or -not $pkg.version) { throw "package.json 缺少 name/version" }
$binFile = Join-Path $stage ($pkg.bin.csdbg)
if (-not (Test-Path $binFile)) { throw "package.json bin 指向的文件不存在: $($pkg.bin.csdbg)" }
Write-Host "包名: $($pkg.name)@$($pkg.version)  bin: csdbg -> $($pkg.bin.csdbg)"

# 6. 质量门 B：Python 语法编译 + JSON 模板可解析
$py = $null
foreach ($c in @('python', 'py')) { if (Get-Command $c -ErrorAction SilentlyContinue) { $py = $c; break } }
if ($py) {
  $args = @()
  if ($py -eq 'py') { $args += '-3' }
  $pys = Get-ChildItem -Recurse -Filter *.py $stage | ForEach-Object { $_.FullName }
  & $py @args -m py_compile @pys
  if ($LASTEXITCODE -ne 0) { throw "py_compile 失败，终止打包" }
  & $py @args -c "import json,glob; [json.load(open(f, encoding='utf-8')) for f in glob.glob(r'$stage\scripts\*.json')]; print('json OK')"
  if ($LASTEXITCODE -ne 0) { throw "channels.example.json 解析失败，终止打包" }
} else {
  Write-Host "⚠ 未找到 python，跳过编译自检" -ForegroundColor Yellow
}

# 6b. 质量门 B2：冒烟测试（功能级回归，不依赖网络/AK；pytest 缺失时降级为离线自检）
if ($py) {
  $args2 = @()
  if ($py -eq 'py') { $args2 += '-3' }
  & $py @args2 -c "import pytest" 2>$null
  if ($LASTEXITCODE -eq 0) {
    & $py @args2 -m pytest (Join-Path $src 'tests') -q --tb=short
    if ($LASTEXITCODE -ne 0) { throw "冒烟测试(pytest)失败，终止打包" }
    Write-Host "冒烟测试: pytest 全量通过" -ForegroundColor Green
  } else {
    Write-Host "⚠ pytest 未安装，降级运行离线自检 selftest.py" -ForegroundColor Yellow
    & $py @args2 (Join-Path $src 'scripts\selftest.py')
    if ($LASTEXITCODE -ne 0) { throw "离线自检失败，终止打包" }
  }
} else {
  Write-Host "⚠ 未找到 python，跳过冒烟测试" -ForegroundColor Yellow
}

# 7. 质量门 C：无个人路径/密钥泄漏（含 .js/.md/.json，npm 包会公开分发）
#    从 leak_patterns.json 读取检测规则（仅实际包，不含原始源）
$leakConfigPath = Join-Path $src 'scripts\leak_patterns.json'
if (Test-Path $leakConfigPath) {
  $leakConfig = Get-Content $leakConfigPath -Raw -Encoding UTF8 | ConvertFrom-Json
  $patterns = $leakConfig.patterns -join '|'
  $extensions = $leakConfig.extensions
  
  $leak = Get-ChildItem -Recurse -File $stage |
    Where-Object { $_.Extension -in $extensions } |
    Select-String -Pattern $patterns -List
  if ($leak) {
    $leak | ForEach-Object { Write-Host "⚠ 泄漏嫌疑: $($_.Path):$($_.LineNumber)" -ForegroundColor Red }
    throw "包内发现个人路径/AK 痕迹，终止打包"
  }
} else {
  Write-Host "⚠ 未找到 leak_patterns.json，跳过泄漏检测（不建议）" -ForegroundColor Yellow
}

# 8. 清理质量门带入的 __pycache__
Get-ChildItem -Recurse -Directory -Filter '__pycache__' $stage | Remove-Item -Recurse -Force

# 9. npm pack 产 tgz
if (-not $SkipPack) {
  Get-ChildItem $dist -Filter 'cs-debug-toolkit-*.tgz' -ErrorAction SilentlyContinue | Remove-Item -Force
  Push-Location $stage
  try {
    $out = & npm pack --silent 2>&1
    if ($LASTEXITCODE -ne 0) { throw "npm pack 失败: $out" }
    $tgz = ($out | Where-Object { $_ -match '\.tgz$' } | Select-Object -Last 1).Trim()
    Move-Item (Join-Path $stage $tgz) $dist -Force
    Write-Host "压缩包: $(Join-Path $dist $tgz)" -ForegroundColor Green
  } finally { Pop-Location }
}

Write-Host ""
Write-Host "== 完成 ==" -ForegroundColor Green
Write-Host "技能数: $skillCount"
Write-Host "包目录: $stage"
Write-Host "安装:   npm install -g <tgz 路径>"
