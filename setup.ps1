<#
.SYNOPSIS
    AnythingToMarkdown 环境安装（PowerShell 版）

.DESCRIPTION
    创建虚拟环境、安装 MarkItDown 转换依赖、下载 PyInstaller，最后自检。
    用法：右键“使用 PowerShell 运行”，或在 PowerShell 中：
        .\setup.ps1

    如果提示“禁止运行脚本”，先执行一次：
        Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
#>

#Requires -Version 5.1

param(
    [string]$IndexUrl = '',
    [string]$ProxyUrl = ''
)

$ErrorActionPreference = 'Stop'

# ---------- 控制台编码 ----------
try {
    [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
    $OutputEncoding = [System.Text.Encoding]::UTF8
} catch { }

$Script:Root    = $PSScriptRoot
$Script:Venv    = Join-Path $Root '.venv'
$Script:Vendor  = Join-Path $Root 'vendor'
$Script:StepNo  = 0

# ---------- pip 额外参数（镜像源 / 代理） ----------
$Script:PipExtra = @()
if ($IndexUrl) {
    $Script:PipExtra += @('-i', $IndexUrl, '--trusted-host', ([uri]$IndexUrl).Host)
}
if ($ProxyUrl) {
    $Script:PipExtra += @('--proxy', $ProxyUrl)
}

function Write-Step {
    param([string]$Text)
    $Script:StepNo++
    Write-Host ''
    Write-Host ("[{0}] {1}" -f $Script:StepNo, $Text) -ForegroundColor Cyan
}

function Write-Ok {
    param([string]$Text)
    Write-Host "    [OK] $Text" -ForegroundColor Green
}

function Write-Warn {
    param([string]$Text)
    Write-Host "    [!!] $Text" -ForegroundColor Yellow
}

function Write-Fail {
    param([string]$Text)
    Write-Host "    [XX] $Text" -ForegroundColor Red
}

function Write-Banner {
    param([string]$Text)
    Write-Host ''
    Write-Host ('=' * 62) -ForegroundColor DarkGray
    Write-Host "  $Text" -ForegroundColor White
    Write-Host ('=' * 62) -ForegroundColor DarkGray
}

# ---------- 失败诊断 ----------
function Show-Diagnosis {
    param(
        [string]$StepName,
        [System.Management.Automation.ErrorRecord]$ErrorRecord
    )

    Write-Host ''
    Write-Host ('=' * 62) -ForegroundColor DarkGray
    Write-Fail "步骤失败：$StepName"
    Write-Host ''
    Write-Host "错误信息：" -ForegroundColor White
    Write-Host "  $($ErrorRecord.Exception.Message)" -ForegroundColor Red
    if ($ErrorRecord.Exception.InnerException) {
        Write-Host "  内层原因：" -ForegroundColor White
        Write-Host "  $($ErrorRecord.Exception.InnerException.Message)" -ForegroundColor Red
    }

    $msg = "$($ErrorRecord.Exception.Message) $($ErrorRecord.Exception.InnerException.Message)"

    Write-Host ''
    Write-Host "可能的原因与处理：" -ForegroundColor White

    if ($msg -match 'Permission denied|拒绝访问|Errno 13') {
        Write-Host "  · 临时目录不可写。这类受限环境会让 pip 失败。" -ForegroundColor Yellow
        Write-Host "    请在普通的 PowerShell 窗口（不是受限终端）中重新运行本脚本。" -ForegroundColor Yellow
    }
    elseif ($msg -match 'SSL|TLS|certificate|证书|Connection|网络|proxy|proxy') {
        Write-Host "  · 网络或证书问题，可能是公司代理/防火墙。" -ForegroundColor Yellow
        Write-Host "    如果公司有代理，先设置：" -ForegroundColor Yellow
        Write-Host '      $env:HTTPS_PROXY = "http://你的代理地址:端口"' -ForegroundColor Gray
        Write-Host "    或换用国内镜像源（见脚本末尾提示）。" -ForegroundColor Yellow
    }
    elseif ($msg -match 'No matching distribution|Could not find a version') {
        Write-Host "  · 包名或版本在当前 Python 版本下不可用。" -ForegroundColor Yellow
        Write-Host "    脚本会在失败时打印实际使用的 Python 版本，请一并反馈。" -ForegroundColor Yellow
    }
    elseif ($msg -match 'is not recognized|找不到|CommandNotFound') {
        Write-Host "  · 命令不存在，通常是 Python 未安装或未加入 PATH。" -ForegroundColor Yellow
    }
    else {
        Write-Host "  · 请把上面的完整错误信息发给我。" -ForegroundColor Yellow
    }

    Write-Host ''
    Write-Host "环境信息（反馈时请一并附上）：" -ForegroundColor White
    Write-Host "  PowerShell : $($PSVersionTable.PSVersion)" -ForegroundColor Gray
    Write-Host "  操作系统   : $([System.Environment]::OSVersion.VersionString)" -ForegroundColor Gray
    Write-Host "  脚本目录   : $Script:Root" -ForegroundColor Gray
    Write-Host "  临时目录   : $([System.IO.Path]::GetTempPath())" -ForegroundColor Gray

    try {
        $tmpProbe = Join-Path ([System.IO.Path]::GetTempPath()) ("atm-probe-" + [guid]::NewGuid().ToString('N').Substring(0,8))
        New-Item -ItemType Directory -Path $tmpProbe -Force | Out-Null
        Set-Content -Path (Join-Path $tmpProbe 'x.txt') -Value 'ok' -ErrorAction Stop
        Remove-Item $tmpProbe -Recurse -Force -ErrorAction SilentlyContinue
        Write-Host "  临时目录可写: 是" -ForegroundColor Gray
    }
    catch {
        Write-Host "  临时目录可写: 否  <- 这很可能就是失败原因" -ForegroundColor Red
    }

    Write-Host ('=' * 62) -ForegroundColor DarkGray
}

# ---------- 找 Python ----------
function Find-Python {
    $candidates = @()

    # 1. py launcher
    $pyCmd = Get-Command py -ErrorAction SilentlyContinue
    if ($pyCmd) {
        try {
            $paths = & py -0p 2>$null
            foreach ($l in $paths) {
                if ($l -match '^\s*-V:(\S+)\s+\*?\s*(.+\.exe)\s*$') {
                    $candidates += [pscustomobject]@{ Exe = $Matches[2]; Label = "py -$($Matches[1])" }
                }
            }
        } catch { }
    }

    # 2. PATH 里的 python
    foreach ($name in @('python', 'python3')) {
        $c = Get-Command $name -ErrorAction SilentlyContinue
        if ($c) { $candidates += [pscustomobject]@{ Exe = $c.Source; Label = $name } }
    }

    # 3. 常见安装位置
    $globs = @(
        "$env:LOCALAPPDATA\Programs\Python\Python3*\python.exe",
        "C:\Python3*\python.exe",
        "D:\Python\python.exe",
        "D:\Python3*\python.exe"
    )
    foreach ($g in $globs) {
        Get-ChildItem $g -ErrorAction SilentlyContinue | ForEach-Object {
            $candidates += [pscustomobject]@{ Exe = $_.FullName; Label = $_.FullName }
        }
    }

    # 排除 WindowsApps 的占位 exe
    $candidates = $candidates | Where-Object { $_.Exe -notmatch 'WindowsApps' }

    foreach ($c in $candidates) {
        try {
            $ver = & $c.Exe -c "import sys;print('%d.%d.%d' % sys.version_info[:3])" 2>$null
            if ($LASTEXITCODE -eq 0 -and $ver) {
                $parts = $ver.Split('.')
                if ([int]$parts[0] -ge 3 -and [int]$parts[1] -ge 10) {
                    return [pscustomobject]@{ Exe = $c.Exe; Version = $ver; Label = $c.Label }
                }
            }
        } catch { }
    }
    return $null
}

# ---------- 实时运行子进程 ----------
function Invoke-Native {
    param(
        [string]$Exe,
        [string[]]$Arguments,
        [string]$StepName
    )
    $old = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        & $Exe @Arguments
        $code = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $old
    }
    if ($code -ne 0) {
        throw "命令退出码 $code ：$Exe $($Arguments -join ' ')"
    }
}

# ============================================================
#  主流程
# ============================================================
$currentStep = '初始化'

try {
    Write-Banner 'AnythingToMarkdown 安装'

    # --- 找 Python ---
    $currentStep = '定位 Python'
    Write-Step '定位 Python 解释器'
    $py = Find-Python
    if (-not $py) {
        Write-Fail '未找到 Python 3.10 或更高版本'
        Write-Host ''
        Write-Host '请安装 Python：https://www.python.org/downloads/' -ForegroundColor Yellow
        Write-Host '安装时务必勾选 "Add python.exe to PATH"。' -ForegroundColor Yellow
        Write-Host ''
        Write-Host '已搜索位置：py 启动器 / PATH / LOCALAPPDATA / C:\Python3* / D:\Python' -ForegroundColor Gray
        exit 1
    }
    Write-Ok "找到 Python $($py.Version)"
    Write-Host "         $($py.Exe)" -ForegroundColor Gray
    Write-Host "         来源：$($py.Label)" -ForegroundColor Gray

    # --- 检查基础环境 ---
    $currentStep = '检查临时目录'
    Write-Step '检查运行环境'
    $tmp = [System.IO.Path]::GetTempPath()
    Write-Host "    临时目录: $tmp" -ForegroundColor Gray

    try {
        $probeDir = Join-Path $tmp ("atm-probe-" + [guid]::NewGuid().ToString('N').Substring(0,8))
        New-Item -ItemType Directory -Path $probeDir -Force | Out-Null
        Set-Content -Path (Join-Path $probeDir 'x.txt') -Value 'ok' -ErrorAction Stop
        Remove-Item $probeDir -Recurse -Force -ErrorAction SilentlyContinue
        Write-Ok '临时目录普通写入正常'
    }
    catch {
        Write-Fail "临时目录不可写：$($_.Exception.Message)"
        Write-Host '    pip 和打包都需要临时目录，请换一个不受限的 PowerShell 窗口。' -ForegroundColor Yellow
        exit 1
    }

    # 关键：tempfile.mkdtemp（pip / venv / PyInstaller 都依赖它）
    # 注意：PowerShell 5.1 向原生程序传参时会吞掉内联双引号，
    #       所以这里写入临时 .py 文件再执行，避免引号转义问题。
    Write-Host '    测试 tempfile.mkdtemp（pip/venv 依赖）...' -ForegroundColor Gray
    $tfScript = Join-Path $Root 'scripts\probe_tempfile.py'
    if (-not (Test-Path $tfScript)) { throw "找不到探测脚本：$tfScript" }
    $tfOut = & $py.Exe $tfScript 2>&1
    if ($LASTEXITCODE -ne 0 -or ("$tfOut" -notmatch 'TEMPfile_OK')) {
        Write-Fail 'tempfile 不可用'
        foreach ($l in $tfOut) { Write-Host ('    ' + $l) -ForegroundColor Gray }
        Write-Host ''
        Write-Host '    这个环境限制了临时目录的创建方式，pip / venv / PyInstaller 都会失败。' -ForegroundColor Yellow
        Write-Host '    请在一个普通的 PowerShell 窗口重新运行本脚本。' -ForegroundColor Yellow
        exit 1
    }
    Write-Ok 'tempfile 可用'

    # --- 创建虚拟环境 ---
    $currentStep = '创建虚拟环境'
    Write-Step '创建虚拟环境'
    $venvPy = Join-Path $Venv 'Scripts\python.exe'
    if (Test-Path $venvPy) {
        Write-Ok "已存在，复用：$venvPy"
    }
    else {
        if (Test-Path $Venv) {
            Write-Warn '发现不完整的 .venv，清理后重建'
            Remove-Item $Venv -Recurse -Force -ErrorAction SilentlyContinue
        }
        Write-Host '    正在创建（约 10 秒）...' -ForegroundColor Gray
        Invoke-Native -Exe $py.Exe -Arguments @('-m', 'venv', $Venv) -StepName $currentStep
        if (-not (Test-Path $venvPy)) { throw "虚拟环境创建后找不到 $venvPy" }
        Write-Ok '虚拟环境创建完成'
    }

    # --- 升级 pip ---
    $currentStep = '升级 pip'
    Write-Step '升级 pip'
    Invoke-Native -Exe $venvPy -Arguments (@(
        '-m','pip','install','--upgrade','pip','--quiet','--disable-pip-version-check'
    ) + $Script:PipExtra) -StepName $currentStep
    $pipVer = & $venvPy -m pip --version
    Write-Ok $pipVer

    # --- 安装运行时依赖 ---
    $currentStep = '安装 MarkItDown 依赖'
    Write-Step '安装 MarkItDown 与转换依赖（可能需要几分钟）'
    Write-Host '    markitdown[docx,xlsx,xls,pptx,pdf,outlook]' -ForegroundColor Gray
    Invoke-Native -Exe $venvPy -Arguments (@(
        '-m','pip','install','markitdown[docx,xlsx,xls,pptx,pdf,outlook]',
        '--disable-pip-version-check'
    ) + $Script:PipExtra) -StepName $currentStep
    Write-Ok '运行时依赖安装完成'

    # --- 下载 PyInstaller ---
    $currentStep = '下载 PyInstaller'
    Write-Step '下载 PyInstaller 到 vendor（隔离，不污染全局）'
    if (-not (Test-Path $Vendor)) { New-Item -ItemType Directory -Path $Vendor -Force | Out-Null }
    Invoke-Native -Exe $venvPy -Arguments (@(
        '-m','pip','install','pyinstaller',
        '--target', $Vendor, '--upgrade', '--disable-pip-version-check'
    ) + $Script:PipExtra) -StepName $currentStep
    Write-Ok 'PyInstaller 就绪'

    # --- 自检 ---
    $currentStep = '环境自检'
    Write-Step '运行环境自检'
    $checkScript = Join-Path $Root 'scripts\check_env.py'
    if (-not (Test-Path $checkScript)) { throw "找不到自检脚本：$checkScript" }
    Invoke-Native -Exe $venvPy -Arguments @($checkScript) -StepName $currentStep

    # --- 完成 ---
    Write-Banner '安装完成'
    Write-Host ''
    Write-Host '下一步：' -ForegroundColor White
    Write-Host '  .\package.ps1    打包成单文件 exe' -ForegroundColor Gray
    Write-Host '  .\install.ps1    注册右键菜单' -ForegroundColor Gray
    Write-Host ''
}
catch {
    Show-Diagnosis -StepName $currentStep -ErrorRecord $_
    Write-Host ''
    Write-Host '如果提示是网络问题，可尝试国内镜像源：' -ForegroundColor Yellow
    Write-Host '  .\setup.ps1 -IndexUrl https://pypi.tuna.tsinghua.edu.cn/simple' -ForegroundColor Gray
    Write-Host ''
    exit 1
}
