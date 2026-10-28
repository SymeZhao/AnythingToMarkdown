# AnythingToMarkdown

把任何格式的文件一键转换为 Markdown，**完全离线**。装好后在文件上右键即可转换。

## ⚠️ Windows 11 用户请先读这里

Windows 11 的新版右键菜单**只显示微软内置项，以及带 MSIX 包身份的扩展**。
本工具的菜单项会出现在**「显示更多选项」**里（右键菜单最底部那一项，或按 `Shift + F10`）。

这是 Windows 11 的既定设计，不是安装失败。7-Zip、VS Code 的「通过 Code 打开」在 Win11 上同样被折叠在这里。

如果你想让它直接出现在第一层菜单，需要把整个右键菜单恢复成经典样式：

```powershell
# 恢复经典右键菜单（全局生效，可随时撤销）
New-Item -Path "HKCU:\Software\Classes\CLSID\{86ca1aa0-34aa-4e8b-a509-50c905bae2a2}\InprocServer32" -Force | Out-Null
# 然后重启资源管理器
```

撤销方法：删掉 `HKCU\Software\Classes\CLSID\{86ca1aa0-34aa-4e8b-a509-50c905bae2a2}` 这个键，再重启资源管理器。

## 现在能做什么

在任意文件上右键 →「显示更多选项」→ **转为 Markdown**，结果 `文件名.md` 就出现在原文件旁边。

| 场景 | 操作 |
|---|---|
| 单个文件 | 文件右键 → 显示更多选项 → 转为 Markdown |
| 多个文件 | 选中多个 → 右键 → 显示更多选项 → 转为 Markdown（每个文件分别转换） |
| 整个文件夹 | 文件夹右键 → 显示更多选项 → 将本文件夹转为 Markdown |
| 打开图形界面 | 双击 `AnythingToMarkdown.exe` |
| 最快方式 | 按 `Shift + F10` 直接呼出经典菜单 |

## 支持格式

| 类别 | 格式 |
|---|---|
| Office | `.docx` `.xlsx` `.xls` `.pptx` `.msg` `.eml` |
| 文档 | `.pdf` `.epub` `.ipynb` |
| 网页与数据 | `.html` `.htm` `.csv` `.json` `.jsonl` `.xml` `.rss` `.atom` |
| 文本 | `.txt` |
| 压缩包 | `.zip`（解出内部各文件的 Markdown 汇总） |

**暂不支持**（会给出明确提示，不会静默失败）：
- `.md` / `.markdown` —— 已经是 Markdown，无需转换（也避免文件夹转换时反复产生 `.md.md`）
- 图片 `.jpg` `.png` 等 —— 需要 OCR 或 AI 描述，计划下一版
- 音视频 —— 需要语音转写，计划后续版本
- 旧版 `.doc` `.ppt` —— 需要 LibreOffice，建议先另存为新格式

## 快速开始

克隆到任意目录，进入后执行：

```powershell
git clone https://github.com/SymeZhao/AnythingToMarkdown.git
cd AnythingToMarkdown

# 1. 装依赖
.\setup.ps1

# 2. 打包
.\package.ps1 -DirMode

# 3. 注册右键菜单
.\install.ps1
```

菜单立刻生效。想撤掉：

```powershell
.\install.ps1 -Uninstall
```

## 从零构建

顺序执行，每一步都检查输出：

```powershell
cd AnythingToMarkdown

# 1. 装依赖（创建 .venv，安装 MarkItDown 与 PyInstaller）
.\setup.ps1

# 2. 打包（两种模式任选）
.\package.ps1 -DirMode     # 目录模式（推荐：启动快，不需要临时目录）
.\package.ps1              # 单文件模式（便于拷贝，但启动时需解压到 %TEMP%）

# 3. 注册右键菜单（自动识别上面的产物）
.\install.ps1
```

### 两种打包模式怎么选

| | 目录模式 `-DirMode` | 单文件模式（默认） |
|---|---|---|
| 产物 | `dist\AnythingToMarkdown\` 文件夹 | `dist\AnythingToMarkdown.exe` |
| 大小 | 约 166 MB（整个目录） | 约 77 MB |
| 启动速度 | 快（无需解压） | 慢几秒（每次解压到 %TEMP%） |
| 临时目录依赖 | **不需要** | 需要可写的 %TEMP% |
| 拷给别人 | 需整个文件夹 | 单个 exe 即可 |

**推荐目录模式**：更稳、更快。如果只在固定电脑上用，没有理由选单文件。

> 首次遇到“禁止运行脚本”时，先执行一次：
> `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass`
> 这个设置只对当前窗口有效，不改系统策略。

安装慢的话加国内镜像：

```powershell
.\setup.ps1 -IndexUrl https://pypi.tuna.tsinghua.edu.cn/simple
```

公司网络需要代理时：

```powershell
.\setup.ps1 -ProxyUrl http://代理地址:端口
```

## 命令行用法

打包后的 exe 也可以直接命令行调用：

```powershell
.\dist\AnythingToMarkdown.exe 报告.docx
.\dist\AnythingToMarkdown.exe a.pdf b.xlsx c.pptx
.\dist\AnythingToMarkdown.exe "D:\资料" -r
.\dist\AnythingToMarkdown.exe 报告.docx --out "D:\markdown"
.\dist\AnythingToMarkdown.exe --check     # 检查引擎是否正常
```

单个文件失败不影响批量中的其他文件，失败原因会写清楚。

### 关于重复转换

右键菜单默认带 `-f`（覆盖），含义是：**再次转换同一个文件会刷新它的 `.md`**，而不是生成
`xxx (1).md` 一堆副本。

如果你手改过某个 `.md` 想保留，有两个办法：
- 先把它改名；
- 或改用命令行、不带 `-f` 运行，这样会生成带序号的新文件。

## 自检与测试

```powershell
# 环境自检（检查 Python、依赖、转换引擎）
.\.venv\Scripts\python.exe scripts\check_env.py

# 生成样例文件（含 Word/Excel/PPT/PDF）
.\.venv\Scripts\python.exe scripts\make_samples.py

# 端到端测试
.\.venv\Scripts\python.exe scripts\selftest.py
```

### 一键自检（推荐）

上面三条验的是「功能能不能用」，下面这条验的是**「README 里的承诺还成不成立」**：

```powershell
.\scripts\selfcheck.ps1
```

它跑 27 项断言，覆盖的都是曾经真出过事、但肉眼看不出来的地方：

| 检查项 | 守的是什么 |
|---|---|
| `.ps1` 带 BOM + CRLF + 语法可解析 | 没有 BOM 时 PowerShell 5.1 按 GBK 解析，中文全乱且报假语法错 |
| `pyproject.toml` 是合法 PEP 621 | 曾经这里放的是 `setup.py` 的 `setup()` 代码，`pip install -e .` 必失败 |
| `install.ps1 -UsePython` 真的能注册 | 进程被降权到 Low 时只报 `WinError 5`，读代码看不出来 |
| 9 个样例都能转出非空 Markdown | 抓转换退化，并断言 docx 的中文正文未乱码 |
| 工作区干净 | 抓行尾漂移和生成物污染 |

参数：

```powershell
.\scripts\selfcheck.ps1 -SkipMenu      # 不碰注册表
.\scripts\selfcheck.ps1 -SkipConvert   # 不跑转换（没装依赖时）
.\scripts\selfcheck.ps1 -StrictGit     # 工作区不干净也算失败（CI 用）
```

CI 在 `.github/workflows/ci.yml` 里跑同一套断言，Windows runner，`push`/`PR` 都触发。

## 项目结构

```
AnythingToMarkdown/
├── setup.ps1              安装依赖
├── package.ps1            打包 exe
├── install.ps1            右键菜单注册/移除
├── src/anythingtomarkdown/
│   ├── converter.py       转换核心（格式判断、错误处理、输出去重）
│   ├── cli.py             命令行入口
│   ├── contextmenu.py     右键菜单（HKCU 注册表）
│   ├── gui.py             图形界面（tkinter 拖放）
│   └── __main__.py        打包入口
├── scripts/
│   ├── check_env.py       环境自检
│   ├── make_samples.py    生成测试样例
│   ├── selftest.py        端到端测试
│   ├── manage_menu.py     右键菜单辅助脚本
│   └── probe_tempfile.py  临时目录探测
├── samples/               测试样例
└── dist/                  打包产物
```

## 卸载

```powershell
.\install.ps1 -Uninstall    # 移除右键菜单
# 然后删掉整个项目目录即可
```

右键菜单只写入 `HKEY_CURRENT_USER`，不需要管理员权限，卸载后不留残留。

## 常见问题

**右键菜单没出现？**
Windows 11 会把它折叠进「显示更多选项」（见文首说明）。若那里也没有，重启资源管理器：任务管理器 → 找到「Windows 资源管理器」→ 重启。

**报「无法写入输出文件」且所有位置都失败？**

这通常是**进程被降权**（完整性级别变成 Low）：能读文件，但任何位置都写不了。
本项目实际踩过这个坑，见下面的「已知坑」一节。

先跑写入自测，看是「只有某个文件夹不行」还是「整体被拦截」：

```powershell
.\.venv\Scripts\python.exe scripts\writetest.py        # Python 直接写
.\dist\AnythingToMarkdown\AnythingToMarkdown.exe --writetest   # exe 写
```

如果是整体拦截，改用 Python 模式注册右键菜单：

```powershell
.\install.ps1 -UsePython
```

该模式调用的是**系统 Python**（不是 `.venv` 里的副本），并自动加载 `.venv` 的依赖。
请注意别删除 `.venv`。想换回 exe 模式，重跑 `.\install.ps1` 即可。

**报「无法写入输出文件」/「没有权限」？**

先跑诊断，它会指出到底卡在哪一步：

```powershell
.\dist\AnythingToMarkdown\AnythingToMarkdown.exe --diagnose "完整路径\文件.pdf"
```

最常见的两个原因：

1. **Windows「受控文件夹访问」**（勒索软件防护）默认保护桌面、文档、下载等文件夹，
   未签名的程序往里写文件会被拒绝。
   关闭或放行：Windows 安全中心 → 病毒和威胁防护 → 勒索软件防护 → 受控文件夹访问
   → 把 `AnythingToMarkdown.exe` 加入允许列表。
2. **杀毒软件（火绒 / 360）的文件保护**拦截写入。把程序目录加入信任区。

程序已内置兜底：原目录写不进去时会改存到
`%LOCALAPPDATA%\AnythingToMarkdown\output`，并在结果里告诉你实际位置。

也可以直接指定输出到不受保护的位置：

```powershell
.\dist\AnythingToMarkdown\AnythingToMarkdown.exe "文件.pdf" --out "D:\markdown"
```

**转换出来是空的？**
文件可能是扫描版 PDF（纯图片）或空白文档。扫描件需要 OCR，当前版本不支持。

**PDF 转换结果乱？**
MarkItDown 优先提取文本层，排版复杂的 PDF 效果有限。可以试试先把 PDF 转成 Word 再转。

**杀毒软件报警？**
exe 由 PyInstaller 打包且未签名，部分杀软会误报。可以只在自己信任的机器上用，或者把项目目录加入白名单。

## 已知坑：进程被降权导致全盘拒写

**症状**：转换时报「无法写入输出文件」，且备用目录 `%TEMP%`、`AppData` 全部
`WinError 5 拒绝访问`。但同一个程序在 PowerShell 里手跑却完全正常。

**根因**：`.venv\Scripts\python.exe` 是创建虚拟环境时从系统 Python **复制出来的副本**。
安全软件的放行名单按文件特征识别，认原始解释器、不认副本，于是把副本降级到
**Low 完整性级别**运行。Low 级别进程只能读、不能写任何位置。

判断方法（本项目内置）：

```powershell
.\.venv\Scripts\python.exe -c "import sys; sys.path.insert(0,'src'); from anythingtomarkdown.winenv import describe; [print(l) for l in describe()]"
```

输出 `完整性级别: Low（0x1000）` 就是它。对照：

```text
.venv\Scripts\python.exe  →  Low     全盘拒写
D:\Python\python.exe      →  Medium  正常
```

**解决**：用系统 Python 运行，`atm.py` 会自动把 `.venv` 的依赖目录加入 `sys.path`：

```powershell
.\install.ps1 -UsePython
```

该命令会读 `.venv\pyvenv.cfg` 的 `home` 字段找到真正的系统解释器，
避开被降权的副本。

> 注：注册右键菜单若报 `WinError 5`，请用**管理员** PowerShell 执行。

## 技术说明

转换引擎用微软开源的 [MarkItDown](https://github.com/microsoft/markitdown)（MIT 协议），它覆盖格式最广，也是“任意格式转 Markdown”事实上的标准。

本项目在它之上补了三块它没有的东西：**Windows 右键菜单集成**、**图形界面**、**中文错误提示与输出去重**。

提供两种运行形态：

| 形态 | 说明 |
|---|---|
| 打包 exe（目录模式） | 自包含，换台没装 Python 的电脑也能跑 |
| Python 模式 | 调用系统 Python，不受「副本被降权」影响 |
