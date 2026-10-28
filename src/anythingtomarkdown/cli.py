"""命令行入口：被右键菜单和图形界面调用。

用法示例：
    atm file.docx                 转换单个文件
    atm a.pdf b.xlsx c.pptx       批量转换
    atm "D:\\资料"                 转换整个文件夹
    atm --out D:\\md reports.xlsx  指定输出目录
    atm --gui                     打开图形界面
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from . import __version__
from .converter import (
    BatchResult,
    collect_files,
    convert_many,
    diagnose_file,
    engine_status,
)


def _setup_console() -> None:
    """Windows 控制台默认 GBK，统一切到 UTF-8 以免中文乱码。"""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
        except Exception:
            pass


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="atm",
        description="把任何格式的文件一键转换为 Markdown（离线）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例：\n"
            "  atm 报告.docx               转换后在旁边生成 报告.md\n"
            "  atm a.pdf b.xlsx            批量转换\n"
            "  atm \"D:\\资料\" --recursive   转换文件夹内所有支持的文件\n"
            "  atm 报告.docx --out \"D:\\md\" 指定输出目录\n"
        ),
    )
    parser.add_argument("paths", nargs="*", help="要转换的文件或文件夹")
    parser.add_argument("-o", "--out", default=None, help="输出目录（默认与源文件同目录）")
    parser.add_argument(
        "-r", "--recursive", action="store_true", help="递归处理文件夹内的文件"
    )
    parser.add_argument(
        "-f", "--force", action="store_true", help="覆盖已存在的 .md 文件"
    )
    parser.add_argument("--gui", action="store_true", help="打开图形界面")
    parser.add_argument(
        "--check", action="store_true", help="检查转换引擎是否可用"
    )
    parser.add_argument(
        "--diagnose",
        action="store_true",
        help="排查某个文件为什么转不了（检查读/写权限与转换过程）",
    )
    parser.add_argument(
        "--writetest",
        action="store_true",
        help="测试本程序能否写入各个位置（判断是否被安全软件拦截）",
    )
    parser.add_argument(
        "-q", "--quiet", action="store_true", help="只输出结果摘要"
    )
    parser.add_argument(
        "--pause",
        action="store_true",
        help="结束后等待按键（供右键菜单使用，便于查看结果）",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return parser


def _print_batch(batch: BatchResult, quiet: bool) -> None:
    for item in batch.items:
        if item.ok:
            if not quiet:
                print(item.describe())
        else:
            # 失败信息无论 quiet 与否都输出
            print(item.describe(), file=sys.stderr)

    if quiet:
        # 安静模式（右键菜单）：只给一行结论，并列出产出文件名
        if batch.succeeded:
            names = "、".join(r.output.name for r in batch.succeeded if r.output)
            if len(names) > 120:
                names = names[:117] + "…"
            print(f"转换完成：{len(batch.succeeded)} 个文件 → {names}")
            # 有备用目录等额外说明时一定要显示，否则用户找不到文件
            for r in batch.succeeded:
                if r.note:
                    print(f"  注意：{r.name}：{r.note}")
        if batch.failed:
            print(f"失败 {len(batch.failed)} 个", file=sys.stderr)
            _print_runtime_info()
        return

    if batch.total > 1 or batch.failed:
        print()
        print(batch.summary())

    if batch.succeeded:
        print(f"输出目录：{batch.succeeded[0].output.parent}")  # type: ignore[union-attr]

    if batch.failed:
        _print_runtime_info()


def _print_runtime_info() -> None:
    """失败时打印运行环境，便于判断是 exe 还是 Python 在跑、权限是否被降级。"""
    import os

    from .winenv import describe as describe_winenv

    frozen = bool(getattr(sys, "frozen", False))
    print("", file=sys.stderr)
    print("--- 运行环境 ---", file=sys.stderr)
    print(f"执行程序: {sys.executable}", file=sys.stderr)
    print(f"运行方式: {'打包的 exe' if frozen else 'Python 解释器'}", file=sys.stderr)
    print(f"Python  : {sys.version.split()[0]}", file=sys.stderr)
    print(f"工作目录: {os.getcwd()}", file=sys.stderr)
    print(f"进程用户: {os.environ.get('USERNAME', '?')}", file=sys.stderr)
    print(f"参数    : {sys.argv[1:]}", file=sys.stderr)
    for line in describe_winenv():
        print(line, file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    _setup_console()
    args = build_parser().parse_args(argv)

    # --check：自检模式
    if args.check:
        ok, message = engine_status()
        print(("✓ " if ok else "✗ ") + message)
        return 0 if ok else 1

    # --writetest：写入能力自测
    if args.writetest:
        from .writetest import run_writetest

        code = run_writetest()
        if args.pause:
            _wait_for_key()
        return code

    # --diagnose：排查单个文件为什么转不了
    if args.diagnose:
        targets = collect_files(args.paths, recursive=False)
        if not targets:
            print("请指定要诊断的文件", file=sys.stderr)
            if args.pause:
                _wait_for_key()
            return 1
        out_dir = Path(args.out) if args.out else None
        for target in targets:
            for line in diagnose_file(target, out_dir=out_dir):
                print(line)
            print()
        if args.pause:
            _wait_for_key()
        return 0

    # --gui 或完全没给参数：打开图形界面
    if args.gui or (not args.paths and not args.check):
        try:
            from .gui import run_gui
        except Exception as exc:
            print(f"无法打开图形界面：{exc}", file=sys.stderr)
            print("可以直接把文件拖到 atm.exe 上，或用命令行传入文件路径。", file=sys.stderr)
            return 1
        return run_gui()

    # 收集文件
    files = collect_files(args.paths, recursive=args.recursive)
    if not files:
        print("没有找到可转换的文件", file=sys.stderr)
        return 1

    out_dir = Path(args.out) if args.out else None
    if out_dir is not None:
        try:
            out_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            print(f"无法创建输出目录 {out_dir}：{exc}", file=sys.stderr)
            return 1

    def _progress(index: int, total: int, current: Path) -> None:
        if total > 1 and not args.quiet:
            print(f"[{index}/{total}] {current.name}", flush=True)

    batch = convert_many(
        files,
        out_dir=out_dir,
        overwrite=args.force,
        progress=_progress,
    )
    _print_batch(batch, args.quiet)

    # 右键菜单场景：失败时停住让用户看清原因，成功且仅单个文件时静默退出
    if args.pause and batch.failed:
        _wait_for_key()

    return 0 if not batch.failed else 1


def _wait_for_key() -> None:
    """等待用户按键，避免窗口一闪而过看不到错误。"""
    try:
        input("\n按回车键关闭…")
    except (EOFError, KeyboardInterrupt, RuntimeError):
        pass


if __name__ == "__main__":
    sys.exit(main())
