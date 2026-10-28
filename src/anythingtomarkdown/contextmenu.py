"""右键菜单注册 / 卸载。

全部写入 HKEY_CURRENT_USER，不需要管理员权限。
注册的位置：
  1. 文件右键：所有受支持扩展名 → "转为 Markdown"
  2. 文件夹右键：转换整个文件夹
  3. 多选文件右键：批量转换

卸载时按同样的清单逐项删除，不留残渣。
"""
from __future__ import annotations

import os
import subprocess
import sys
import winreg
from pathlib import Path

from .converter import SUPPORTED_EXTENSIONS  # noqa: F401  (保留：菜单覆盖范围与支持格式保持一致)

#: 右键菜单显示文字
MENU_TEXT = "转为 Markdown"
MENU_TEXT_FOLDER = "将本文件夹转为 Markdown"

#: 顶层菜单键名（用固定标识，便于卸载时精确定位）
_ROOT_FILE = r"Software\Classes\*\shell\AnythingToMarkdown"
_ROOT_FOLDER = r"Software\Classes\Directory\shell\AnythingToMarkdown"
_ROOT_FOLDER_BG = r"Software\Classes\Directory\Background\shell\AnythingToMarkdown"


class RegistryError(Exception):
    """注册表操作失败。"""


# ---------------------------------------------------------------- 注册表工具


def _run(method: Callable[..., object], *args, **kwargs) -> bool:
    """统一处理 winreg 抛出的 PermissionError / OSError。"""
    try:
        method(*args, **kwargs)
        return True
    except PermissionError as exc:
        raise RegistryError(
            "没有权限修改注册表。请检查是否被安全软件拦截。"
        ) from exc
    except OSError as exc:
        raise RegistryError(f"注册表操作失败：{exc}") from exc


def _set_value(key_path: str, name: str | None, value: str) -> None:
    with winreg.CreateKeyEx(
        winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_WRITE
    ) as key:
        if name is None:
            _run(winreg.SetValueEx, key, "", 0, winreg.REG_SZ, value)
        else:
            _run(winreg.SetValueEx, key, name, 0, winreg.REG_SZ, value)


def _delete_tree(root: str) -> bool:
    """递归删除注册表键，键不存在时返回 False。"""
    try:
        winreg.OpenKey(winreg.HKEY_CURRENT_USER, root).Close()
    except FileNotFoundError:
        return False
    except OSError:
        return False

    def _recursive(path: str) -> None:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, path, 0, winreg.KEY_READ | winreg.KEY_WRITE
        ) as key:
            while True:
                try:
                    sub = winreg.EnumKey(key, 0)
                except OSError:
                    break
                _recursive(f"{path}\\{sub}")
                try:
                    winreg.DeleteKey(key, sub)
                except OSError:
                    pass
        try:
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, path)
        except OSError:
            pass

    try:
        _recursive(root)
        return True
    except PermissionError as exc:
        raise RegistryError("删除右键菜单需要权限，可能被安全软件拦截。") from exc


# ---------------------------------------------------------------- 命令构造


def _quote(path: str) -> str:
    return f'"{path}"'


def build_command(exe_path: Path, *, folder: bool = False, background: bool = False) -> str:
    """构造右键菜单调用的命令行。

    - 文件：atm.exe -q -f --pause "%1"
    - 文件夹：atm.exe -q -r -f --pause "%1"
    - 文件夹空白处：atm.exe -q -r -f --pause "%V"

    -q      简洁输出（只报结论）
    -f      覆盖已有 .md，使重复转换「刷新」结果而不是堆出一堆副本
            （如 demo.docx 反复转换始终更新 demo.md）
    --pause 失败时停住，让用户看清原因，而不是窗口一闪而过
    """
    exe = _quote(str(exe_path))
    if background:
        return f"{exe} -q -r -f --pause \"%V\""
    if folder:
        return f"{exe} -q -r -f --pause \"%1\""
    return f"{exe} -q -f --pause \"%1\""


def _register_key(
    root: str,
    menu_text: str,
    command: str,
    *,
    extended: bool = False,
) -> None:
    _set_value(root, None, menu_text)
    _set_value(f"{root}\\command", None, command)
    if extended:
        # Extended 表示按住 Shift 才显示，避免污染主菜单
        _set_value(root, "Extended", "")
    # 指定图标，让菜单项更易识别
    ico = Path(command.strip('"').split('"')[0])
    if ico.exists():
        _set_value(root, "Icon", str(ico))


def _reg_entries(exe_path: Path) -> list[tuple[str, str, str, bool]]:
    """返回 (键路径, 菜单文字, 命令, 是否 extended)。"""
    entries: list[tuple[str, str, str, bool]] = [
        (_ROOT_FILE, MENU_TEXT, build_command(exe_path), False),
        (_ROOT_FOLDER, MENU_TEXT_FOLDER, build_command(exe_path, folder=True), False),
        (
            _ROOT_FOLDER_BG,
            MENU_TEXT_FOLDER,
            build_command(exe_path, background=True),
            True,
        ),
    ]
    return entries


# ---------------------------------------------------------------- 对外接口


def exe_path_for_registration() -> Path:
    """决定注册到右键菜单的可执行文件路径。

    - 打包后的 exe：直接用自身
    - 源码运行时：找不到 exe 就报错，提示先打包
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve()

    # 源码运行：尝试使用项目根目录下 dist 里的 exe
    here = Path(__file__).resolve()
    for parent in here.parents:
        # 优先目录模式产物
        dir_mode = parent / "dist" / "AnythingToMarkdown" / "AnythingToMarkdown.exe"
        if dir_mode.exists():
            return dir_mode.resolve()
        # 其次单文件产物
        single = parent / "dist" / "AnythingToMarkdown.exe"
        if single.exists():
            return single.resolve()

    raise RegistryError(
        "还没打包。请先运行 package.ps1 生成程序，再注册右键菜单。"
    )


def build_python_command(
    python_exe: Path, launcher: Path, *, folder: bool = False, background: bool = False
) -> str:
    """用 Python 解释器 + 启动脚本构造命令（绕开安全软件对 exe 的拦截）。

    形式：python.exe "atm.py" -q -f --pause "%1"
    """
    py = _quote(str(python_exe))
    script = _quote(str(launcher))
    if background:
        return f"{py} {script} -q -r -f --pause \"%V\""
    if folder:
        return f"{py} {script} -q -r -f --pause \"%1\""
    return f"{py} {script} -q -f --pause \"%1\""


def install_python_mode(python_exe: Path, launcher: Path) -> list[str]:
    """以「Python 解释器 + atm.py」方式注册右键菜单。

    部分安全软件会拦截未签名的 exe 写文件，但不会拦截 Python，
    因此这条路径能绕过该限制。
    """
    if not Path(python_exe).exists():
        raise RegistryError(f"找不到 Python：{python_exe}")
    if not Path(launcher).exists():
        raise RegistryError(f"找不到启动脚本：{launcher}")

    entries = [
        (_ROOT_FILE, MENU_TEXT, build_python_command(python_exe, launcher), False),
        (
            _ROOT_FOLDER,
            MENU_TEXT_FOLDER,
            build_python_command(python_exe, launcher, folder=True),
            False,
        ),
        (
            _ROOT_FOLDER_BG,
            MENU_TEXT_FOLDER,
            build_python_command(python_exe, launcher, background=True),
            True,
        ),
    ]

    done: list[str] = []
    for key, text, command, extended in entries:
        _register_key(key, text, command, extended=extended)
        done.append(f"已注册（Python 模式）：{text}")
    return done


def install(exe_path: Path | None = None) -> list[str]:
    """注册右键菜单，返回执行过的操作说明。"""
    exe = Path(exe_path) if exe_path else exe_path_for_registration()
    if not exe.exists():
        raise RegistryError(f"找不到程序文件：{exe}")

    done: list[str] = []
    for key, text, command, extended in _reg_entries(exe):
        _register_key(key, text, command, extended=extended)
        done.append(f"已注册：{text}")
    return done


def uninstall() -> list[str]:
    """移除全部右键菜单项。"""
    done: list[str] = []
    for key in (_ROOT_FILE, _ROOT_FOLDER, _ROOT_FOLDER_BG):
        if _delete_tree(key):
            done.append(f"已移除：{key}")
    if not done:
        done.append("没有找到已注册的右键菜单项")
    return done


def is_installed() -> bool:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _ROOT_FILE):
            return True
    except OSError:
        return False


def notify_shell() -> None:
    """通知资源管理器刷新，让右键菜单立刻生效。"""
    try:
        import ctypes

        # SHCNE_ASSOCCHANGED = 0x08000000, SHCNF_IDLIST = 0x0000
        ctypes.windll.shell32.SHChangeNotify(0x08000000, 0x0000, None, None)
    except Exception:
        pass


def open_in_explorer(path: Path) -> None:
    """在资源管理器中定位文件。"""
    try:
        subprocess.Popen(["explorer", "/select,", str(path)])
    except Exception:
        pass


def open_path(path: Path) -> None:
    """用默认程序打开。"""
    try:
        os.startfile(str(path))  # type: ignore[attr-defined]
    except Exception:
        pass


# ---------------------------------------------------------------- 自检入口

if __name__ == "__main__":  # pragma: no cover
    if len(sys.argv) > 1 and sys.argv[1] == "install":
        print("\n".join(install()))
    elif len(sys.argv) > 1 and sys.argv[1] == "uninstall":
        print("\n".join(uninstall()))
    else:
        print(f"已安装：{is_installed()}")
