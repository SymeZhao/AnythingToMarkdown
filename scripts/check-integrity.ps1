<#
.SYNOPSIS
    对比检测：不同程序的完整性级别与实际写入能力

.DESCRIPTION
    用同一个 PowerShell 窗口启动几个不同的程序，看它们是 High/Medium/Low，
    以及能否写到 C:\Users 下。用来判断「降权」是只针对 Python，还是全局。

    请在普通（非管理员）PowerShell 里运行：
        .\scripts\check-integrity.ps1
#>

$ErrorActionPreference = 'Continue'

try {
    [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
    $OutputEncoding = [System.Text.Encoding]::UTF8
} catch { }

$Root = Join-Path (Split-Path $PSScriptRoot -Parent) ''
$VenvPy = Join-Path $Root '.venv\Scripts\python.exe'
$BasePy = $null
if (Test-Path $VenvPy) {
    # venv 的 python.exe 指向的基础解释器
    $cfg = Join-Path $Root '.venv\pyvenv.cfg'
    if (Test-Path $cfg) {
        $line = Get-Content $cfg | Where-Object { $_ -match '^home\s*=' }
        if ($line) {
            $homeDir = ($line -split '=', 2)[1].Trim()
            $cand = Join-Path $homeDir 'python.exe'
            if (Test-Path $cand) { $BasePy = $cand }
        }
    }
}

function Show-Title($t) {
    Write-Host ''
    Write-Host ('=' * 64) -ForegroundColor DarkGray
    Write-Host " $t" -ForegroundColor White
    Write-Host ('=' * 64) -ForegroundColor DarkGray
}

Show-Title '本会话自身'

Write-Host "PowerShell 进程级别："
$me = whoami /groups | Select-String -Pattern 'Mandatory Label'
Write-Host "  $($me -replace '\s+', ' ')"

Write-Host ''
Write-Host "PowerShell 能否写 C:\Users\$env:USERNAME ？"
$probe = Join-Path $env:USERPROFILE "ps-writetest-$(Get-Random).tmp"
try {
    Set-Content -LiteralPath $probe -Value 'ok' -ErrorAction Stop
    Remove-Item -LiteralPath $probe -Force -ErrorAction SilentlyContinue
    Write-Host '  [OK] 可以写' -ForegroundColor Green
}
catch {
    Write-Host "  [XX] 不能写：$($_.Exception.Message)" -ForegroundColor Red
}

Show-Title '各个 Python 解释器的进程级别'

$probePy = @'
import os, sys

# 复用项目里已经验证可用的探测实现，避免重复踩 ctypes 类型声明的坑
_here = os.path.dirname(os.path.abspath(__file__))
for cand in (
    r"__SRC__",
    os.path.join(os.path.dirname(_here), "src"),
):
    if os.path.isdir(cand) and cand not in sys.path:
        sys.path.insert(0, cand)

def integrity():
    try:
        from anythingtomarkdown.winenv import integrity_level
        return integrity_level()[1]
    except Exception as e:
        return "未知(%s)" % type(e).__name__

def canwrite():
    p = os.path.join(os.environ.get("USERPROFILE", ""), "py-writetest.tmp")
    try:
        with open(p, "w") as fh:
            fh.write("ok")
        os.remove(p)
        return "可写"
    except Exception as e:
        return "不可写(%s)" % type(e).__name__

print("%-14s %-10s %s" % (integrity(), canwrite(), sys.executable))
'@

# 把项目 src 路径注入探测脚本，确保能 import 到 winenv
$probePy = $probePy -replace '__SRC__', (Join-Path $Root 'src')

$tmpPy = Join-Path $env:TEMP "atm_probe_$((Get-Random)).py"
try {
    Set-Content -Path $tmpPy -Value $probePy -Encoding UTF8 -ErrorAction Stop
}
catch {
    Write-Host "  [!!] 无法写临时探测脚本到 TEMP：$($_.Exception.Message)" -ForegroundColor Yellow
    Write-Host "       改用项目目录" -ForegroundColor Yellow
    $tmpPy = Join-Path $Root "atm_probe_$((Get-Random)).py"
    Set-Content -Path $tmpPy -Value $probePy -Encoding UTF8
}

$targets = @(
    @{ Name = 'venv python'; Path = $VenvPy },
    @{ Name = '基础 python'; Path = $BasePy },
    @{ Name = 'PY 启动器';   Path = (Get-Command py -ErrorAction SilentlyContinue).Source }
) | Where-Object { $_.Path -and (Test-Path $_.Path) }

Write-Host '  级别        写入       解释器'
Write-Host '  ----------  ---------  --------'
foreach ($t in $targets) {
    $out = & $t.Path $tmpPy 2>&1
    if ($LASTEXITCODE -eq 0 -and $out) {
        Write-Host "  $out"
        Write-Host "              ↑ $($t.Name)" -ForegroundColor DarkGray
    }
    else {
        Write-Host "  [失败] $($t.Name) -> $out" -ForegroundColor Red
    }
}

Remove-Item $tmpPy -Force -ErrorAction SilentlyContinue

Show-Title '结论怎么看'
Write-Host ' · 所有 Python 都是 Low  → 解释器被系统/安全软件降权'
Write-Host ' · 只有 venv 的是 Low    → venv 里的 python.exe 被标记，换基础解释器即可'
Write-Host ' · 都显示 Medium 但写不了 → 是 C:\Users 的权限问题'
Write-Host ''
