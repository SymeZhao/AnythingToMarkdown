<#
.SYNOPSIS
    注册 / 移除 AnythingToMarkdown 的右键菜单

.DESCRIPTION
    全部写入 HKEY_CURRENT_USER，不需要管理员权限。

      .\install.ps1            注册右键菜单（使用打包的 exe）
      .\install.ps1 -UsePython 改用 Python 解释器运行（绕开安全软件对 exe 的拦截）
      .\install.ps1 -Uninstall 移除右键菜单
      .\install.ps1 -Status    查看当前状态

    如果右键转换时报「无法写入输出文件」且所有位置都失败，
    通常是安全软件拦截了未签名的 exe。此时用 -UsePython 注册即可绕过：
    Python 解释器一般不会被拦，功能和 exe 完全一致。
#>

param(
    [switch]$Uninstall,
    [switch]$Status,
    [switch]$UsePython
)

$ErrorActionPreference = 'Continue'

try {
    [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
    $OutputEncoding = [System.Text.Encoding]::UTF8
} catch { }

$Root   = $PSScriptRoot
$VenvPy = Join-Path $Root '.venv\Scripts\python.exe'
$Helper = Join-Path $Root 'scripts\manage_menu.py'

# 自动识别打包产物：优先目录模式，其次单文件
$ExeSingle = Join-Path $Root 'dist\AnythingToMarkdown.exe'
$ExeDirMode = Join-Path $Root 'dist\AnythingToMarkdown\AnythingToMarkdown.exe'
$Exe = if (Test-Path $ExeDirMode) { $ExeDirMode }
       elseif (Test-Path $ExeSingle) { $ExeSingle }
       else { $ExeSingle }

function Show-Header {
    Write-Host ''
    Write-Host ('=' * 58) -ForegroundColor DarkGray
    Write-Host '  AnythingToMarkdown 右键菜单' -ForegroundColor White
    Write-Host ('=' * 58) -ForegroundColor DarkGray
}

Write-Host ''
if (-not (Test-Path $VenvPy)) {
    Write-Host '[XX] 虚拟环境不存在，请先运行 .\setup.ps1' -ForegroundColor Red
    exit 1
}
if (-not (Test-Path $Helper)) {
    Write-Host "[XX] 找不到辅助脚本：$Helper" -ForegroundColor Red
    exit 1
}

Show-Header

# ---------- 查看状态 ----------
if ($Status) {
    & $VenvPy $Helper status
    exit $LASTEXITCODE
}

# ---------- 移除 ----------
if ($Uninstall) {
    Write-Host '[..] 移除右键菜单...' -ForegroundColor Cyan
    & $VenvPy $Helper uninstall
    if ($LASTEXITCODE -eq 0) {
        Write-Host ''
        Write-Host '[OK] 右键菜单已移除' -ForegroundColor Green
    }
    else {
        Write-Host '[XX] 移除失败，请查看上方信息' -ForegroundColor Red
    }
    exit $LASTEXITCODE
}

# ---------- 注册 ----------
if ($UsePython) {
    # Python 模式：绕开安全软件对未签名 exe 的写入拦截
    $atmPy = Join-Path $Root 'atm.py'
    if (-not (Test-Path $VenvPy)) {
        Write-Host '[XX] 找不到虚拟环境里的 Python，请先运行 .\setup.ps1' -ForegroundColor Red
        exit 1
    }
    if (-not (Test-Path $atmPy)) {
        Write-Host "[XX] 找不到启动脚本：$atmPy" -ForegroundColor Red
        exit 1
    }

    Write-Host '[..] 注册方式：Python 解释器（绕过 exe 写入拦截）' -ForegroundColor Cyan
    Write-Host "     Python: $VenvPy" -ForegroundColor Gray
    Write-Host "     脚本  : $atmPy" -ForegroundColor Gray
    & $VenvPy $Helper install-python

    if ($LASTEXITCODE -eq 0) {
        Write-Host ''
        Write-Host '[OK] 右键菜单注册完成（Python 模式）' -ForegroundColor Green
        Write-Host ''
        Write-Host '说明：右键菜单现在调用 Python 而不是 exe。' -ForegroundColor Gray
        Write-Host '      功能完全一致，但不受安全软件对未签名 exe 的写入限制。' -ForegroundColor Gray
        Write-Host '      这个模式下请勿删除 .venv 目录。' -ForegroundColor Gray
    }
    else {
        Write-Host ''
        Write-Host '[XX] 注册失败，请查看上方信息' -ForegroundColor Red
    }
    exit $LASTEXITCODE
}

if (-not (Test-Path $Exe)) {
    Write-Host '[!!] 还没找到打包好的程序' -ForegroundColor Yellow
    Write-Host "     已查找: $ExeDirMode" -ForegroundColor Gray
    Write-Host "              $ExeSingle" -ForegroundColor Gray
    Write-Host ''
    Write-Host '     请先运行 .\package.ps1 完成打包。' -ForegroundColor Gray
    Write-Host '     或者用 -UsePython 直接注册 Python 版本：' -ForegroundColor Gray
    Write-Host '       .\install.ps1 -UsePython' -ForegroundColor White
    exit 1
}

$modeLabel = if ($Exe -eq $ExeDirMode) { '目录模式' } else { '单文件' }
Write-Host "[..] 程序位置: $Exe（$modeLabel）" -ForegroundColor Cyan
& $VenvPy $Helper install $Exe

if ($LASTEXITCODE -eq 0) {
    Write-Host ''
    Write-Host '[OK] 右键菜单注册完成' -ForegroundColor Green
    Write-Host ''
    Write-Host '用法：' -ForegroundColor White
    Write-Host '  文件上右键   → “转为 Markdown”' -ForegroundColor Gray
    Write-Host '  文件夹上右键 → “将本文件夹转为 Markdown”' -ForegroundColor Gray
    Write-Host ''
    Write-Host '若菜单未立刻出现，重启资源管理器或注销重登即可。' -ForegroundColor DarkGray
}
else {
    Write-Host ''
    Write-Host '[XX] 注册失败，请查看上方信息' -ForegroundColor Red
}

exit $LASTEXITCODE
