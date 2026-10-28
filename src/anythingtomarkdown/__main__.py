"""打包入口：PyInstaller 从这里启动。

保持极简，避免在启动路径上引入多余导入拖慢冷启动。
"""
from __future__ import annotations

import multiprocessing
import sys


def main() -> int:
    from anythingtomarkdown.cli import main as cli_main

    return cli_main()


if __name__ == "__main__":
    # PyInstaller 打包后若用到多进程需要此行，提前调用无副作用
    multiprocessing.freeze_support()
    sys.exit(main())
