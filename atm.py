r"""右键菜单用的启动器（不经过打包的 exe）。

为什么不直接用 .venv\Scripts\python.exe？
    该文件是创建虚拟环境时从系统 Python 复制出来的副本。部分安全软件
    按文件特征放行已知解释器，副本不被识别，会被降级到 Low 完整性级别
    运行 —— 结果是能读文件、但任何位置都写不进去。

本脚本的做法：
    用系统 Python 启动，但把 .venv 的包目录加进 sys.path，
    这样既能用到已安装的依赖，又避开被降权的副本。

用法：
    D:\Python\python.exe atm.py -q -f --pause "%1"
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
_SRC = _ROOT / "src"
_VENV_SITE = _ROOT / ".venv" / "Lib" / "site-packages"


def _bootstrap_paths() -> None:
    """把项目源码和虚拟环境的包目录加入搜索路径。

    顺序很重要：源码在前，依赖在后。
    """
    for candidate in (_SRC, _VENV_SITE):
        text = str(candidate)
        if candidate.is_dir() and text not in sys.path:
            sys.path.insert(0, text)


_bootstrap_paths()

from anythingtomarkdown.cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
