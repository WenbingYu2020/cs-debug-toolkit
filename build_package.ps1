# build_package.ps1 — 从 cs-cli 单源组装 cs-debug-toolkit 分发包
# 用法: powershell -ExecutionPolicy Bypass -File .\build_package.ps1 [-SkipZip] [-Strict]
param([switch]$SkipZip, [switch]$Strict)
$ErrorActionPreference = 'Stop'
$src   = Split-Path -Parent $MyInvocation.MyCommand.Path        # cs-cli 功能区根目录
$stage = Join-Path $src 'dist\cs-debug-toolkit'
$zip   = Join-Path $src 'dist\cs-debug-toolkit.zip'

Write-Host "== 组装 CS-Debug-Toolkit ==" -ForegroundColor Cyan
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

# 1. 根文件（README/setup 用 pack/ 里的分发版）
Copy-Item (Join-Path $src 'pack\README.md')     (Join-Path $stage 'README.md')
Copy-Item (Join-Path $src 'pack\setup.ps1')     (Join-Path $stage 'setup.ps1')
Copy-Item (Join-Path $src 'requirements.txt')   $stage

# 2. scripts/ —— 只要 py + 采集器(.ps1) + 配置模板；channels.json(密钥)/leak_patterns.json/legacy/__pycache__ 永不入包
New-Item -ItemType Directory -Force -Path (Join-Path $stage 'scripts') | Out-Null
Copy-Item (Join-Path $src 'scripts\*.py')                   (Join-Path $stage 'scripts')
Copy-Item (Join-Path $src 'scripts\*.ps1')                  (Join-Path $stage 'scripts')
Copy-Item (Join-Path $src 'scripts\channels.example.json')  (Join-Path $stage 'scripts')
Copy-Item (Join-Path $src 'scripts\leak_patterns.example.json')  (Join-Path $stage 'scripts')

# 2b. cli/ 目录 —— bin（csdbg入口） + lib（ECD SDK与host-runner）
New-Item -ItemType Directory -Force -Path (Join-Path $stage 'cli') | Out-Null
Copy-Item -Recurse (Join-Path $src 'cli\bin')  (Join-Path $stage 'cli\bin')
Copy-Item -Recurse (Join-Path $src 'cli\lib')  (Join-Path $stage 'cli\lib')

# 3. skill/ —— 所有含 SKILL.md 的技能目录（含 references）
New-Item -ItemType Directory -Force -Path (Join-Path $stage 'skill') | Out-Null
$skillCount = 0
Get-ChildItem -Directory (Join-Path $src 'skill') | Where-Object {
  Test-Path (Join-Path $_.FullName 'SKILL.md')
} | ForEach-Object {
  Copy-Item -Recurse $_.FullName (Join-Path $stage 'skill')
  $skillCount++
}

# 4. templates/ 与 temp/ 骨架
Copy-Item -Recurse (Join-Path $src 'templates') $stage
New-Item -ItemType Directory -Force -Path (Join-Path $stage 'temp') | Out-Null
New-Item -ItemType File -Force -Path (Join-Path $stage 'temp\.gitkeep') | Out-Null

# 4b. docs/（排障文档，随包分发便于新手自助）
New-Item -ItemType Directory -Force -Path (Join-Path $stage 'docs') | Out-Null
Copy-Item (Join-Path $src 'docs\troubleshooting.md') (Join-Path $stage 'docs')

# 5. 质量门：语法编译 + 配置模板可解析 + 无个人路径/密钥泄漏
$py = $null
foreach ($c in @('python', 'py')) { if (Get-Command $c -ErrorAction SilentlyContinue) { $py = $c; break } }
if ($py) {
  $pys = Get-ChildItem -Recurse -Filter *.py $stage | ForEach-Object { $_.FullName }
  & $py -m py_compile @pys
  if ($LASTEXITCODE -ne 0) { throw "py_compile 失败，终止打包" }
  & $py -c "import json,glob; [json.load(open(f, encoding='utf-8')) for f in glob.glob(r'$stage\scripts\*.json')]; print('json OK')"
  if ($LASTEXITCODE -ne 0) { throw "channels.example.json 解析失败，终止打包" }
} else {
  Write-Host "⚠ 未找到 python，跳过编译自检" -ForegroundColor Yellow
}

# 质量门 B2：冒烟测试（功能级回归，不依赖网络/AK；pytest 缺失时降级为离线自检）
if ($py) {
  & $py -c "import pytest" 2>$null
  if ($LASTEXITCODE -eq 0) {
    & $py -m pytest (Join-Path $src 'tests') -q --tb=short
    if ($LASTEXITCODE -ne 0) { throw "冒烟测试(pytest)失败，终止打包" }
    Write-Host "冒烟测试: pytest 全量通过" -ForegroundColor Green
  } else {
    Write-Host "⚠ pytest 未安装，降级运行离线自检 selftest.py" -ForegroundColor Yellow
    & $py (Join-Path $src 'scripts\selftest.py')
    if ($LASTEXITCODE -ne 0) { throw "离线自检失败，终止打包" }
  }
} else {
  Write-Host "⚠ 未找到 python，跳过冒烟测试" -ForegroundColor Yellow
}

# 质量门 C：动态泄漏检测（从源 leak_patterns.json 读）
$leakCfgPath = Join-Path $src 'scripts\leak_patterns.json'
if (-not (Test-Path $leakCfgPath)) {
  throw "缺少 scripts\leak_patterns.json（从 .example 模板创建并填入个人模式）"
}
$leakCfg = Get-Content -Raw -Encoding UTF8 $leakCfgPath | ConvertFrom-Json
$patterns = $leakCfg.patterns -join '|'
$exts = $leakCfg.extensions
$leak = Get-ChildItem -Recurse -File $stage | Where-Object {
  $exts -contains $_.Extension
} | Select-String -Pattern $patterns -List
if ($leak) { $leak | ForEach-Object { Write-Host "⚠ 泄漏嫌疑: $($_.Path):$($_.LineNumber)" -ForegroundColor Red } }
if ($leak) { throw "包内发现个人路径/AK 痕迹，终止打包" }

# 6. 清理质量门/源目录带入的 __pycache__
Get-ChildItem -Recurse -Directory -Filter '__pycache__' $stage | Remove-Item -Recurse -Force

# 7. 打 zip（-Path * 不含隐藏文件属正常：temp/.gitkeep 只是骨架占位）
if (-not $SkipZip) {
  if (Test-Path $zip) { Remove-Item -Force $zip }
  Compress-Archive -Path (Join-Path $stage '*') -DestinationPath $zip
}

Write-Host ""
Write-Host "== 完成 ==" -ForegroundColor Green
Write-Host "技能数: $skillCount"
Write-Host "目录: $stage"
if (-not $SkipZip) { Write-Host "压缩包: $zip" }
