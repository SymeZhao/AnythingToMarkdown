"""写入能力自测（源码版入口）。

用法：
    .\\.venv\\Scripts\\python.exe scripts\\writetest.py

与 exe 的 `--writetest` 是同一套逻辑：两边各跑一次，对比结果即可
判断是环境问题还是打包后的 exe 被安全软件拦截。
"""
from __future__ import annotations

import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parent.parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from anythingtomarkdown.writetest import run_writetest  # noqa: E402


def _setup_stdout() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
        except Exception:
            pass


if __name__ == "__main__":
    _setup_stdout()
    sys.exit(run_writetest())
