<#
.SYNOPSIS
    AnythingToMarkdown 自检：把 README 里承诺的事情变成可执行断言。

.DESCRIPTION
    改完脚本、发版前，或者遇到「别人那儿能用我这儿不行」时跑一遍。
    这里验的不是功能本身，而是那些「文档写了但没人真跑过」的约定：

      1. .ps1 脚本必须带回 BOM 的 UTF-8 + CRLF，并且能被 PowerShell 解析
         （没有 BOM 时 PowerShell 5.1 按 GBK 解析，中文会被打乱）
      2. pyproject.toml 必须是合法的 PEP 621 配置，而不是误放的 setup.py
      3. .\install.ps1 -UsePython 必须能真的注册成功
         （进程被降权时只会报 WinError 5，光读代码看不出来）
      4. samples 里每个样例都必须能转出非空的 Markdown
      5. 工作区必须干净（抓行尾漂移和生成物污染）

    用法：
        .\scripts\selfcheck.ps1              全跑（会重写右键菜单，幂等）
        .\scripts\selfcheck.ps1 -SkipMenu    不碰注册表
        .\scripts\selfcheck.ps1 -StrictGit   工作区不干净就算失败（CI 用）

    退出码：0 全部通过，1 有失败项。
#>
#Requires -Version 5.1

param(
    [switch]$SkipMenu,
    [switch]$SkipConvert,
    [switch]$StrictGit
)

$ErrorActionPreference = 'Stop'

try {
    [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
    $OutputEncoding = [System.Text.Encoding]::UTF8
} catch { }

$Root    = Split-Path -Parent $PSScriptRoot
$AtmPy   = Join-Path $Root 'atm.py'
$Samples = Join-Path $Root 'samples'
$Menu    = Join-Path $Root 'install.ps1'

$script:Passed = 0
$script:Failed = 0

function Write-Head {
    param([string]$Text)
    Write-Host ''
    Write-Host "== $Text" -ForegroundColor Cyan
}

function Write-Ok {
    param([string]$Text)
    $script:Passed++
    Write-Host "    [OK] $Text" -ForegroundColor Green
}

function Write-Bad {
    param([string]$Text, [string]$Hint = '')
    $script:Failed++
    Write-Host "    [XX] $Text" -ForegroundColor Red
    if ($Hint) { Write-Host "         $Hint" -ForegroundColor DarkGray }
}

function Write-Note {
    param([string]$Text)
    Write-Host "    [..] $Text" -ForegroundColor Yellow
}

function Assert-True {
    param([bool]$Condition, [string]$Text, [string]$Hint = '')
    if ($Condition) { Write-Ok $Text } else { Write-Bad $Text $Hint }
}

# 找出创建虚拟环境时用的系统 Python。
# 不能用 .venv\Scripts\python.exe —— 那个副本可能被降权到 Low 完整性级别，
# 连输出文件都写不了。这里只做探测，不修改任何东西。
function Test-UsablePython {
    param([string]$Path)

    if (-not $Path) { return $false }
    if ($Path -match '\.venv') { return $false }

    # Windows 应用商店的提示占位符：0 字节的重解析点，
    # 存在但运行时报「系统找不到指定的路径」，必须排除。
    if ($Path -match '\\WindowsApps\\') { return $false }

    if (-not (Test-Path -LiteralPath $Path)) { return $false }
    try {
        if ((Get-Item -LiteralPath $Path -Force).Length -lt 1024) { return $false }
    }
    catch { return $false }

    return $true
}

function Get-BasePython {
    param([string]$ProjectRoot)

    $cfg = Join-Path $ProjectRoot '.venv\pyvenv.cfg'
    if (Test-Path $cfg) {
        foreach ($line in Get-Content -Path $cfg -ErrorAction SilentlyContinue) {
            if ($line -match '^\s*home\s*=\s*(.+?)\s*$') {
                $candidate = Join-Path $Matches[1] 'python.exe'
                if (Test-UsablePython $candidate) { return $candidate }
            }
        }
    }

    $c = Get-Command python -ErrorAction SilentlyContinue
    if ($c -and (Test-UsablePython $c.Source)) { return $c.Source }

    $py = Get-Command py -ErrorAction SilentlyContinue
    if ($py -and (Test-UsablePython $py.Source)) { return $py.Source }

    foreach ($guess in @(
        'D:\Python\python.exe',
        "$env:LOCALAPPDATA\Programs\Python\Python313\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe",
        'C:\Python313\python.exe',
        'C:\Python312\python.exe'
    )) {
        if (Test-UsablePython $guess) { return $guess }
    }

    return $null
}

Write-Host ''
Write-Host ('=' * 60) -ForegroundColor DarkGray
Write-Host '  AnythingToMarkdown 自检' -ForegroundColor White
Write-Host ('=' * 60) -ForegroundColor DarkGray

$BasePy = Get-BasePython -ProjectRoot $Root
if ($BasePy) {
    Write-Host "    系统 Python: $BasePy" -ForegroundColor Gray
}
else {
    Write-Host '    系统 Python: 未找到' -ForegroundColor Yellow
}

# ============================================================
#  1. 脚本编码与语法
# ============================================================
Write-Head '1. 脚本编码与语法'

$scriptsToCheck = @(
    'install.ps1',
    'package.ps1',
    'setup.ps1',
    'scripts\selfcheck.ps1'
)

foreach ($rel in $scriptsToCheck) {
    $path = Join-Path $Root $rel
    if (-not (Test-Path $path)) {
        Write-Bad "找不到 $rel"
        continue
    }

    $bytes = [System.IO.File]::ReadAllBytes($path)
    $hasBom = ($bytes.Length -ge 3 -and $bytes[0] -eq 0xEF -and $bytes[1] -eq 0xBB -and $bytes[2] -eq 0xBF)
    Assert-True $hasBom "$rel 带 UTF-8 BOM" 'PowerShell 5.1 对无 BOM 的脚本按 GBK 解析，中文会乱'

    $text = [System.Text.Encoding]::UTF8.GetString($bytes)
    $bareLf = ([regex]::Matches($text, "(?<!\r)\n")).Count
    Assert-True ($bareLf -eq 0) "$rel 使用 CRLF 行尾" "发现 $bareLf 处裸 LF，与 .gitattributes 的 eol=crlf 不一致"

    $parseErrors = $null
    [void][System.Management.Automation.Language.Parser]::ParseFile($path, [ref]$null, [ref]$parseErrors)
    $messages = ($parseErrors | ForEach-Object { $_.Message }) -join '; '
    Assert-True ($parseErrors.Count -eq 0) "$rel 语法解析通过" $messages
}

# ============================================================
#  2. pyproject.toml
# ============================================================
Write-Head '2. pyproject.toml'

$checkPyproject = Join-Path $Root 'scripts\check_pyproject.py'
if (-not $BasePy) {
    Write-Bad '没有可用的 Python，无法校验 pyproject.toml'
}
else {
    & $BasePy $checkPyproject
    Assert-True ($LASTEXITCODE -eq 0) 'pyproject.toml 是合法 PEP 621 配置' 'pip install -e . 会失败'
}

# ============================================================
#  3. 右键菜单注册
# ============================================================
Write-Head '3. 右键菜单注册'

if ($SkipMenu) {
    Write-Note '已按 -SkipMenu 跳过'
}
else {
    $installOut = & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $Menu -UsePython 2>&1
    $installCode = $LASTEXITCODE
    $installText = ($installOut | Out-String)

    Assert-True ($installCode -eq 0 -and $installText -match 'MENU_RESULT=ok') `
        'install.ps1 -UsePython 注册成功' `
        (($installOut | Select-Object -Last 4) -join ' | ')

    $statusOut = & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $Menu -Status 2>&1
    $statusText = ($statusOut | Out-String)
    Assert-True ($statusText -match '已安装') '注册状态回读为已安装' $statusText.Trim()
}

# ============================================================
#  4. 样例转换
# ============================================================
Write-Head '4. 样例转换'

if ($SkipConvert) {
    Write-Note '已按 -SkipConvert 跳过'
}
elseif (-not $BasePy) {
    Write-Bad '没有可用的 Python，无法转换'
}
elseif (-not (Test-Path (Join-Path $Root '.venv'))) {
    Write-Bad '.venv 不存在，请先运行 .\setup.ps1'
}
else {
    # 输出目录必须在仓库之外，否则会污染 git status
    $tmpRoot = [System.IO.Path]::GetTempPath()
    if ($tmpRoot -and $tmpRoot.StartsWith($Root, [System.StringComparison]::OrdinalIgnoreCase)) {
        $tmpRoot = Join-Path $env:LOCALAPPDATA 'Temp'
    }
    $outDir = Join-Path $tmpRoot ('atm-selfcheck-' + [guid]::NewGuid().ToString('N').Substring(0, 8))
    New-Item -ItemType Directory -Path $outDir -Force | Out-Null

    try {
        $files = @(Get-ChildItem -Path $Samples -File -ErrorAction Stop |
            Where-Object { $_.Extension -ne '.md' })
        Assert-True ($files.Count -gt 0) "找到 $($files.Count) 个样例" "样例目录：$Samples"

        foreach ($f in $files) {
            # 每个样例单独一个目录：demo.docx / demo.pdf / demo.pptx / demo.xlsx
            # 共用词干，放同一目录会互相覆盖成同一个 demo.md
            $sub = Join-Path $outDir ($f.Name -replace '[^\w\.\-]', '_')
            New-Item -ItemType Directory -Path $sub -Force | Out-Null

            & $BasePy $AtmPy -f --out $sub $f.FullName 2>&1 | Out-Null
            $code = $LASTEXITCODE

            $nonEmpty = @(Get-ChildItem -Path $sub -Filter *.md -File -ErrorAction SilentlyContinue |
                Where-Object { $_.Length -ge 10 })
            Assert-True ($code -eq 0 -and $nonEmpty.Count -ge 1) "$($f.Name) 转换成功" "退出码 $code"
        }

        $produced = @(Get-ChildItem -Path $outDir -Recurse -Filter *.md -File)
        $empty = @($produced | Where-Object { $_.Length -lt 10 })
        Assert-True ($empty.Count -eq 0) '所有产物都非空' (($empty | ForEach-Object { $_.Name }) -join ', ')

        # 深一层：中文正文必须完好，能抓到编码/换行类退化
        $hasWord = $false
        $docxDir = Join-Path $outDir 'demo.docx'
        foreach ($m in @(Get-ChildItem -Path $docxDir -Filter *.md -File -ErrorAction SilentlyContinue)) {
            $content = Get-Content -Path $m.FullName -Raw -Encoding UTF8
            if ($content -match 'Word 测试文档') { $hasWord = $true; break }
        }
        Assert-True $hasWord 'docx 产物含预期中文正文（未乱码）' '检查 demo.docx 的转换结果'
    }
    catch {
        Write-Bad "转换阶段异常：$($_.Exception.Message)"
    }
    finally {
        Remove-Item -Path $outDir -Recurse -Force -ErrorAction SilentlyContinue
    }
}

# ============================================================
#  5. 工作区状态
# ============================================================
Write-Head '5. 工作区状态'

if (-not (Test-Path (Join-Path $Root '.git'))) {
    Write-Note '不是 git 仓库，跳过'
}
elseif (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    # 没装 git 的机器（或 git 不在 PATH）不应让自检失败，
    # 这项只是锦上添花的工作区卫生检查。
    Write-Note '未找到 git 命令，跳过工作区检查'
}
else {
    $dirty = @(& git -C $Root status --porcelain 2>&1 | Where-Object { $_ -and $_.Trim() })
    if ($dirty.Count -eq 0) {
        Write-Ok '工作区干净'
    }
    elseif ($StrictGit) {
        Write-Bad "工作区有 $($dirty.Count) 项未提交改动" ($dirty -join ' | ')
    }
    else {
        Write-Note "工作区有 $($dirty.Count) 项未提交改动（加 -StrictGit 视为失败）"
    }
}

# ============================================================
#  汇总
# ============================================================
Write-Host ''
Write-Host ('=' * 60) -ForegroundColor DarkGray
if ($script:Failed -eq 0) {
    Write-Host ("  自检通过：{0} 项断言全部成立" -f $script:Passed) -ForegroundColor Green
    Write-Host ''
    exit 0
}

Write-Host ("  自检失败：{0} 项通过，{1} 项失败" -f $script:Passed, $script:Failed) -ForegroundColor Red
Write-Host '  逐条修复上面标 [XX] 的项；每一条都对应 README 里的一个承诺。' -ForegroundColor DarkGray
Write-Host ''
exit 1
