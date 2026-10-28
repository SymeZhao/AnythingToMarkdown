<#
.SYNOPSIS
    复现「右键菜单转换失败」的场景

.DESCRIPTION
    用与右键菜单完全相同的方式调用（同一个 Python、同一个 atm.py、同样的参数），
    但由 PowerShell 启动而不是资源管理器。

    对比目的：
      · 这里能成功、右键失败  → 是资源管理器启动的程序被安全软件限制
      · 这里也失败            → 可以直接排查，与启动方式无关

.PARAMETER File
    要测试的文件路径（可选）。不给则只做写入自测。

.EXAMPLE
    .\repro-contextmenu.ps1
    .\repro-contextmenu.ps1 -File "D:\资料\报告.docx"
#>

param(
    [string]$File = ''
)

$ErrorActionPreference = 'Continue'

try {
    [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
    $OutputEncoding = [System.Text.Encoding]::UTF8
} catch { }

$Root = Split-Path $PSScriptRoot -Parent
$Py   = Join-Path $Root 'atm.py'

Write-Host ''
Write-Host ('=' * 62)
Write-Host ' 复现测试：与右键菜单完全相同的调用'
Write-Host ('=' * 62)
Write-Host " 项目: $Root"

if (-not (Test-Path $Py)) {
    Write-Host '[XX] 找不到 atm.py' -ForegroundColor Red
    exit 1
}

# 用 pyvenv.cfg 里的系统解释器（.venv 的副本可能被降权）
$Python = $null
$cfg = Join-Path $Root '.venv\pyvenv.cfg'
if (Test-Path $cfg) {
    $line = Get-Content $cfg | Where-Object { $_ -match '^home\s*=' }
    if ($line) {
        $homeDir = ($line -split '=', 2)[1].Trim()
        $cand = Join-Path $homeDir 'python.exe'
        if (Test-Path $cand) { $Python = $cand }
    }
}
if (-not $Python) {
    $found = (Get-Command python -ErrorAction SilentlyContinue).Source
    if ($found) { $Python = $found }
}
if (-not $Python) {
    Write-Host '[XX] 找不到可用的 Python，请先运行 setup.ps1' -ForegroundColor Red
    exit 1
}

Write-Host " Python: $Python"
Write-Host " 脚本  : $Py"
Write-Host ''

# --- 有目标文件：在该文件所在目录执行同样的转换 ---
if ($File) {
    if (-not (Test-Path -LiteralPath $File)) {
        Write-Host "[!!] 文件不存在：$File" -ForegroundColor Yellow
    }
    else {
        $full = (Resolve-Path -LiteralPath $File).Path
        $dir  = Split-Path $full -Parent
        $name = Split-Path $full -Leaf

        Write-Host '--- 第 1 步：以该文件所在目录为工作目录，执行转换 ---' -ForegroundColor Cyan
        Push-Location -LiteralPath $dir
        try {
            Write-Host "当前目录: $(Get-Location)" -ForegroundColor Gray
            & $Python $Py -q -f $name
            Write-Host "退出码: $LASTEXITCODE"
        }
        finally {
            Pop-Location
        }
        Write-Host ''
    }
}

# --- 写入自测 ---
Write-Host '--- 写入自测 ---' -ForegroundColor Cyan
& $Python $Py --writetest
Write-Host ''

# --- 用 --out 指定一个已知可写的位置 ---
if ($File -and (Test-Path -LiteralPath $File)) {
    Write-Host '--- 用 --out 指定项目内的输出目录 ---' -ForegroundColor Cyan
    $outDir = Join-Path $Root 'out'
    if (-not (Test-Path $outDir)) { New-Item -ItemType Directory -Path $outDir -Force | Out-Null }
    & $Python $Py -q -f --out $outDir $File
    Write-Host "输出目录: $outDir"
    Write-Host ''
}

Write-Host ('=' * 62)
