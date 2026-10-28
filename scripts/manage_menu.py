"""右键菜单管理入口（供 PowerShell 脚本调用，避免引号转义问题）。

用法：
    python manage_menu.py install
    python manage_menu.py uninstall
    python manage_menu.py status
"""
from __future__ import annotations

import sys
from pathlib import Path

# 允许直接从源码目录运行
_SRC = Path(__file__).resolve().parent.parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from anythingtomarkdown import contextmenu as cm  # noqa: E402


def _setup_stdout() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
        except Exception:
            pass


def _base_python(root: Path) -> Path | None:
    """找出创建虚拟环境时用的那个系统 Python。

    优先读 .venv/pyvenv.cfg 里记录的 home，其次用 PATH 中的 python。
    刻意避开 .venv\\Scripts\\python.exe —— 该副本可能被安全软件降权。
    """
    # 1. pyvenv.cfg 的 home 字段
    cfg = root / ".venv" / "pyvenv.cfg"
    if cfg.exists():
        try:
            for line in cfg.read_text(encoding="utf-8", errors="replace").splitlines():
                if line.strip().lower().startswith("home"):
                    _, _, value = line.partition("=")
                    candidate = Path(value.strip()) / "python.exe"
                    if candidate.exists():
                        return candidate
        except OSError:
            pass

    # 2. PATH 中的 python.exe（排除 venv 自己）
    import shutil

    found = shutil.which("python")
    if found:
        p = Path(found)
        if p.exists() and ".venv" not in str(p).lower():
            return p

    return None


def main(argv: list[str]) -> int:
    _setup_stdout()
    action = argv[0].lower() if argv else "status"

    try:
        if action == "install":
            exe = Path(argv[1]) if len(argv) > 1 else None
            for line in cm.install(exe):
                print(line)
            cm.notify_shell()
            print("MENU_RESULT=ok")
            return 0

        if action == "install-python":
            # 用「系统 Python + atm.py」注册。
            # 注意：不能用 .venv\Scripts\python.exe —— 那个副本可能被安全软件
            # 降级到 Low 完整性级别，导致任何位置都写不进去。
            root = Path(__file__).resolve().parent.parent
            python_exe = _base_python(root)
            launcher = root / "atm.py"

            if python_exe is None:
                print(
                    "错误：找不到可用的系统 Python。\n"
                    "请确认 Python 安装在 PATH 或 pyvenv.cfg 记录的 home 目录下。",
                    file=sys.stderr,
                )
                print("MENU_RESULT=fail")
                return 1

            print(f"使用解释器：{python_exe}")
            for line in cm.install_python_mode(python_exe, launcher):
                print(line)
            cm.notify_shell()
            print("MENU_RESULT=ok")
            return 0

        if action == "uninstall":
            for line in cm.uninstall():
                print(line)
            cm.notify_shell()
            print("MENU_RESULT=ok")
            return 0

        if action == "status":
            print("已安装" if cm.is_installed() else "未安装")
            return 0

        print(f"未知操作：{action}", file=sys.stderr)
        return 2
    except cm.RegistryError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        print("MENU_RESULT=fail")
        return 1
    except Exception as exc:  # pragma: no cover
        print(f"未预期错误：{exc.__class__.__name__}: {exc}", file=sys.stderr)
        print("MENU_RESULT=fail")
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
