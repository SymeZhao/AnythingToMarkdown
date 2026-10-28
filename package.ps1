<#
.SYNOPSIS
    打包 AnythingToMarkdown

.DESCRIPTION
    默认打单文件 exe（产物 dist\AnythingToMarkdown.exe）。

    加 -DirMode 则打成目录模式（产物 dist\AnythingToMarkdown\ 文件夹）：
    目录模式启动更快，且不需要运行时解压到 %TEMP%，在受限环境中更稳。

    示例：
      .\package.ps1              单文件 exe
      .\package.ps1 -DirMode     目录模式
      .\package.ps1 -Clean       先清理再打包
#>

param(
    [switch]$Clean,
    [switch]$DirMode
)

$ErrorActionPreference = 'Continue'

try {
    [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
    $OutputEncoding = [System.Text.Encoding]::UTF8
} catch { }

$Root    = $PSScriptRoot
$VenvPy  = Join-Path $Root '.venv\Scripts\python.exe'
$Vendor  = Join-Path $Root 'vendor'
$Entry   = Join-Path $Root 'src\anythingtomarkdown\__main__.py'
$DistDir = Join-Path $Root 'dist'
$BuildDir = Join-Path $Root 'build'

function Show-Header {
    Write-Host ''
    Write-Host ('=' * 58) -ForegroundColor DarkGray
    Write-Host '  AnythingToMarkdown 打包' -ForegroundColor White
    Write-Host ('=' * 58) -ForegroundColor DarkGray
}

Show-Header

# ---------- 前置检查 ----------
Write-Host '[1] 检查环境' -ForegroundColor Cyan
if (-not (Test-Path $VenvPy)) {
    Write-Host '    [XX] 虚拟环境不存在，请先运行 .\setup.ps1' -ForegroundColor Red
    exit 1
}
if (-not (Test-Path $Entry)) {
    Write-Host "    [XX] 找不到入口文件：$Entry" -ForegroundColor Red
    exit 1
}

# PyInstaller：优先用虚拟环境里装的，其次 vendor 目录
$pyiProbe = & $VenvPy -c "import PyInstaller;print(PyInstaller.__version__)" 2>$null
if ($LASTEXITCODE -ne 0) {
    if (Test-Path $Vendor) {
        Write-Host '    [..] 虚拟环境中无 PyInstaller，改用 vendor 目录（setup.ps1 默认装在这里）' -ForegroundColor Yellow
    }
    else {
        Write-Host '    [XX] 未安装 PyInstaller' -ForegroundColor Red
        Write-Host '         请执行：.\.venv\Scripts\python.exe -m pip install pyinstaller' -ForegroundColor Gray
        exit 1
    }
}
else {
    Write-Host "    [OK] PyInstaller $pyiProbe" -ForegroundColor Green
}
Write-Host '    [OK] 环境检查通过' -ForegroundColor Green

# ---------- 清理 ----------
if ($Clean) {
    Write-Host '[2] 清理旧产物' -ForegroundColor Cyan
    Remove-Item $BuildDir -Recurse -Force -ErrorAction SilentlyContinue
    Remove-Item $DistDir -Recurse -Force -ErrorAction SilentlyContinue
    Write-Host '    [OK] 已清理' -ForegroundColor Green
}

# ---------- 生成 spec ----------
Write-Host '[2] 生成打包配置' -ForegroundColor Cyan
$specPath = Join-Path $Root 'AnythingToMarkdown.spec'
$template = Join-Path $Root 'packaging\app.spec.template'

if (-not (Test-Path $template)) {
    Write-Host "    [XX] 找不到 spec 模板：$template" -ForegroundColor Red
    exit 1
}

$mode = if ($DirMode) { 'dir' } else { 'single' }
Write-Host "    [..] 打包模式: $(if($DirMode){'目录模式'}else{'单文件'})" -ForegroundColor Gray

try {
    $spec = Get-Content $template -Raw -Encoding UTF8
    $spec = $spec.Replace('__BUILD_MODE__', $mode)
    $spec = $spec.Replace('__ENTRY__', (Join-Path $Root 'src\anythingtomarkdown\__main__.py'))
    $spec = $spec.Replace('__SRC__', (Join-Path $Root 'src'))
    Set-Content -Path $specPath -Value $spec -Encoding UTF8 -ErrorAction Stop
    Write-Host "    [OK] 已生成 $specPath" -ForegroundColor Green
}
catch {
    Write-Host "    [XX] 生成配置失败：$($_.Exception.Message)" -ForegroundColor Red
    exit 1
}

# ---------- 执行打包 ----------
Write-Host '[3] 开始打包（首次约需 1-3 分钟）' -ForegroundColor Cyan
Write-Host ''

# 把源码目录加入 PYTHONPATH；若使用了 vendor 隔离安装，一并加入
$env:PYTHONPATH = "$Root\src"
if (Test-Path $Vendor) {
    $env:PYTHONPATH = "$Vendor;$env:PYTHONPATH"
}

$sw = [System.Diagnostics.Stopwatch]::StartNew()
& $VenvPy -m PyInstaller $specPath --noconfirm --distpath $DistDir --workpath $BuildDir
$code = $LASTEXITCODE
$sw.Stop()

Write-Host ''
if ($code -ne 0) {
    Write-Host '[XX] 打包失败' -ForegroundColor Red
    Write-Host ''
    Write-Host '常见原因：' -ForegroundColor Yellow
    Write-Host '  · 某个依赖包导入失败 → 检查上方 traceback' -ForegroundColor Gray
    Write-Host '  · 磁盘空间不足' -ForegroundColor Gray
    Write-Host '  · 杀毒软件锁定了输出文件' -ForegroundColor Gray
    exit $code
}

# ---------- 验证产物 ----------
if ($DirMode) {
    $exe = Join-Path (Join-Path $DistDir 'AnythingToMarkdown') 'AnythingToMarkdown.exe'
}
else {
    $exe = Join-Path $DistDir 'AnythingToMarkdown.exe'
}

if (-not (Test-Path $exe)) {
    Write-Host '[XX] 打包声称成功但找不到 exe' -ForegroundColor Red
    Write-Host "     期望位置: $exe" -ForegroundColor Gray
    exit 1
}

if ($DirMode) {
    $dir = Split-Path $exe -Parent
    $sizeMb = [math]::Round(
        ((Get-ChildItem $dir -Recurse -File | Measure-Object Length -Sum).Sum / 1MB), 1
    )
    $sizeLabel = '整个目录'
}
else {
    $sizeMb = [math]::Round((Get-Item $exe).Length / 1MB, 1)
    $sizeLabel = '单文件'
}

Write-Host ('=' * 58) -ForegroundColor DarkGray
Write-Host '  打包完成' -ForegroundColor Green
Write-Host ('=' * 58) -ForegroundColor DarkGray
Write-Host ''
Write-Host "  模式: $(if($DirMode){'目录模式'}else{'单文件'})" -ForegroundColor White
Write-Host "  产物: $exe" -ForegroundColor White
Write-Host "  大小: $sizeMb MB（$sizeLabel）" -ForegroundColor White
Write-Host "  耗时: $([math]::Round($sw.Elapsed.TotalSeconds,1)) 秒" -ForegroundColor White
Write-Host ''
Write-Host '  冒烟测试...' -ForegroundColor Cyan

$checkOut = & $exe --check 2>&1
$checkCode = $LASTEXITCODE
foreach ($l in $checkOut) { Write-Host "    $l" -ForegroundColor Gray }

if ($checkCode -ne 0) {
    Write-Host ''
    Write-Host '[!!] 冒烟测试未通过。' -ForegroundColor Yellow
    if ($checkOut -match '_MEI|extract|temporary directory') {
        Write-Host '     这是 PyInstaller 单文件的运行时解压问题（常见于受限/沙盒环境）。' -ForegroundColor Yellow
        Write-Host '     改用目录模式打包通常可以解决：' -ForegroundColor Gray
        Write-Host '       .\package.ps1 -DirMode' -ForegroundColor White
    }
    else {
        Write-Host '     exe 可能缺少依赖，请把上面的输出发给我。' -ForegroundColor Gray
    }
    exit 1
}

Write-Host ''
Write-Host '  下一步：.\install.ps1 注册右键菜单' -ForegroundColor White
Write-Host ''
exit 0
