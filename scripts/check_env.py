"""环境自检：确认本机 Python 与依赖状态。不依赖任何第三方库，可直接运行。"""
from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
import tempfile
import traceback

OK = "OK"
WARN = "!!"
BAD = "XX"


def _fix_console_encoding() -> None:
    """Windows 控制台默认 GBK，强制 UTF-8 以免中文乱码。"""
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def line(flag: str, text: str) -> None:
    print(f"[{flag}] {text}")


def check_python() -> bool:
    v = sys.version_info
    line(OK, f"Python {platform.python_version()} ({platform.architecture()[0]})")
    line(OK, f"解释器路径: {sys.executable}")
    if v < (3, 10):
        line(BAD, "需要 Python 3.10 或更高版本")
        return False
    return True


def check_write(dirpath: str, label: str) -> bool:
    try:
        os.makedirs(dirpath, exist_ok=True)
        probe = os.path.join(dirpath, "write-probe.tmp")
        with open(probe, "w", encoding="utf-8") as fh:
            fh.write("ok")
        os.remove(probe)
        line(OK, f"可写: {label} -> {dirpath}")
        return True
    except Exception as exc:
        line(BAD, f"不可写: {label} -> {dirpath} ({exc.__class__.__name__})")
        return False


def check_tempfile() -> bool:
    """tempfile 是否可用——pip / venv / PyInstaller 都依赖它。"""
    try:
        d = tempfile.mkdtemp(prefix="atm-probe-")
        try:
            with open(os.path.join(d, "probe.txt"), "w", encoding="utf-8") as fh:
                fh.write("ok")
            line(OK, f"tempfile.mkdtemp 可用: {d}")
            return True
        finally:
            shutil.rmtree(d, ignore_errors=True)
    except Exception as exc:
        line(BAD, f"tempfile 不可用: {exc.__class__.__name__}: {exc}")
        line(WARN, "pip / venv / PyInstaller 都将失败，请换一个普通命令行窗口再试")
        return False


def check_package(name: str, label: str) -> bool:
    try:
        mod = __import__(name)
    except Exception as exc:
        line(BAD, f"缺少 {label} ({name}): {exc.__class__.__name__}")
        return False
    version = getattr(mod, "__version__", "?")
    line(OK, f"{label} {version}")
    return True


def check_markitdown_convert() -> bool:
    """实跑一次转换，确认引擎真的能用。"""
    try:
        from markitdown import MarkItDown
    except Exception as exc:
        line(BAD, f"无法导入 markitdown: {exc.__class__.__name__}: {exc}")
        return False

    try:
        d = tempfile.mkdtemp(prefix="atm-conv-")
        try:
            src = os.path.join(d, "demo.html")
            with open(src, "w", encoding="utf-8") as fh:
                fh.write("<html><body><h1>Hello</h1><p>World</p></body></html>")
            result = MarkItDown().convert(src)
            text = (result.text_content or "").strip()
            if "Hello" in text:
                line(OK, f"MarkItDown 转换成功: {text!r}")
                return True
            line(WARN, f"MarkItDown 返回内容异常: {text!r}")
            return False
        finally:
            shutil.rmtree(d, ignore_errors=True)
    except Exception as exc:
        line(BAD, f"MarkItDown 转换失败: {exc.__class__.__name__}: {exc}")
        traceback.print_exc()
        return False


def check_optional_deps() -> None:
    for mod, label in (
        ("mammoth", "Word .docx 支持"),
        ("openpyxl", "Excel .xlsx 支持"),
        ("xlrd", "Excel .xls 支持"),
        ("pptx", "PowerPoint .pptx 支持"),
        ("pdfminer", "PDF 支持"),
        ("olefile", "Outlook .msg 支持"),
    ):
        check_package(mod, label)


def main() -> int:
    _fix_console_encoding()
    print("=" * 62)
    print(" AnythingToMarkdown 环境自检")
    print("=" * 62)

    ok = check_python()
    if not ok:
        return 2

    print("-" * 62)
    check_write(os.getcwd(), "当前目录")
    check_write(tempfile.gettempdir(), "系统临时目录")

    print("-" * 62)
    temp_ok = check_tempfile()

    print("-" * 62)
    md_ok = check_package("markitdown", "markitdown")

    print("-" * 62)
    if md_ok:
        check_optional_deps()
        print("-" * 62)
        conv_ok = check_markitdown_convert()
    else:
        conv_ok = False
        line(WARN, "跳过转换测试（markitdown 未安装）")

    print("=" * 62)
    if temp_ok and md_ok and conv_ok:
        print("结论: 环境就绪，可以开始构建。")
        return 0
    if not temp_ok:
        print("结论: tempfile 不可用，请换个普通命令行窗口重新运行。")
        return 3
    print("结论: 环境不完整，请按提示安装缺失依赖。")
    return 1


if __name__ == "__main__":
    sys.exit(main())
