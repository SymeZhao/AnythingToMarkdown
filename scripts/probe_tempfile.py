"""探测 tempfile 是否可用。

pip / venv / PyInstaller 都依赖 tempfile.mkdtemp，受限环境里它会在
创建出的目录内禁止写入，导致这些工具全部失败。本脚本用于提前判定。

退出码：0 = 可用，1 = 不可用
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile


def _setup_stdout() -> None:
    """匹配父进程（PowerShell 5.1）的解码方式，避免中文乱码。

    PowerShell 5.1 用控制台代码页（简体中文系统通常是 GBK/936）解码子进程输出。
    这里优先用 UTF-8（PS7/新版终端），失败则退回 ANSI 代码页。
    """
    for enc in ("utf-8", "gbk"):
        try:
            sys.stdout.reconfigure(encoding=enc, errors="replace")
            sys.stderr.reconfigure(encoding=enc, errors="replace")
            return
        except Exception:
            continue


def main() -> int:
    _setup_stdout()
    try:
        d = tempfile.mkdtemp(prefix="atm-tf-")
    except Exception as exc:
        print(f"mkdtemp 失败: {exc.__class__.__name__}: {exc}")
        return 1

    try:
        probe = os.path.join(d, "x.txt")
        try:
            with open(probe, "w", encoding="utf-8") as fh:
                fh.write("ok")
        except Exception as exc:
            print(f"mkdtemp 目录内写入失败: {exc.__class__.__name__}: {exc}")
            print(f"目录: {d}")
            return 1

        print("TEMPfile_OK")

        # 附带报告当前用户名与目录模式，便于排查
        try:
            print(f"目录模式: {oct(os.stat(d).st_mode)}")
            print(f"临时目录根: {tempfile.gettempdir()}")
        except Exception:
            pass
        return 0
    finally:
        shutil.rmtree(d, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
