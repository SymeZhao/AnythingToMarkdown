"""写入能力自测：判断「写不了文件」到底是环境问题还是本程序被拦截。

同一个测试既可以通过 Python 运行，也可以由打包后的 exe 运行
（exe 用 `--writetest`）。对比两者结果即可定位问题：

  - 两者都能写            → 环境没问题
  - Python 能写、exe 不能 → 安全软件针对 exe 拦截，把 exe 加白名单
  - 两者都不能写          → 系统级权限/策略问题
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path


def _candidate_dirs() -> list[Path]:
    """列出要测试写入的位置（覆盖常见可写区域）。"""
    out: list[Path] = []
    for env, sub in (
        ("LOCALAPPDATA", ("AnythingToMarkdown", "writetest")),
        ("APPDATA", ("AnythingToMarkdown", "writetest")),
        ("USERPROFILE", ("AnythingToMarkdown-writetest",)),
        ("TEMP", ("AnythingToMarkdown-writetest",)),
        ("PUBLIC", ("AnythingToMarkdown-writetest",)),
    ):
        raw = os.environ.get(env)
        if raw:
            out.append(Path(raw).joinpath(*sub))
    out.append(Path.cwd() / "writetest-tmp")
    return out


def _test_dir(target: Path) -> tuple[bool, str]:
    probe_file: Path | None = None
    try:
        target.mkdir(parents=True, exist_ok=True)
        probe_file = target / f"probe-{os.getpid()}.txt"
        probe_file.write_text("ok", encoding="utf-8")
        content = probe_file.read_text(encoding="utf-8")
        probe_file.unlink()
        try:
            target.rmdir()
        except OSError:
            pass
        if content != "ok":
            return False, "写入后读回内容不一致"
        return True, "可写"
    except Exception as exc:
        if probe_file is not None:
            try:
                probe_file.unlink(missing_ok=True)
            except OSError:
                pass
        return False, f"{exc.__class__.__name__}: {exc}"


def run_writetest() -> int:
    """执行写入自测并打印报告，返回退出码：0 全通过 / 1 部分 / 2 全部失败。"""
    frozen = bool(getattr(sys, "frozen", False))
    label = "打包后的 exe" if frozen else "Python 解释器"

    print("=" * 62)
    print(f" 写入测试（{label}）")
    print("=" * 62)
    print(f" 可执行文件: {sys.executable}")
    print(f" 进程用户  : {os.environ.get('USERNAME', '?')}")
    print(f" 当前目录  : {Path.cwd()}")
    print()

    ok_count = 0
    total = 0
    for target in _candidate_dirs():
        total += 1
        ok, msg = _test_dir(target)
        if ok:
            ok_count += 1
        print(f" [{'OK' if ok else 'XX'}] {target}")
        if not ok:
            print(f"        {msg}")

    # tempfile.mkdtemp：pip 等工具依赖，值得单独测
    total += 1
    try:
        d = tempfile.mkdtemp(prefix="atm-wt-")
        try:
            with open(os.path.join(d, "x.txt"), "w", encoding="utf-8") as fh:
                fh.write("ok")
            print(f" [OK] tempfile.mkdtemp: {d}")
            ok_count += 1
        finally:
            shutil.rmtree(d, ignore_errors=True)
    except Exception as exc:
        print(f" [XX] tempfile.mkdtemp → {exc.__class__.__name__}: {exc}")

    print()
    print("-" * 62)
    print(f" 结果：{ok_count}/{total} 个位置可写")
    print("-" * 62)

    if ok_count == total:
        print(" 结论：写入正常，没有拦截。")
        return 0
    if ok_count == 0:
        print(" 结论：所有位置都写不了 —— 系统级限制，或被安全软件整体拦截。")
        print("       请把本程序加入白名单：")
        print("         · 火绒：防护中心 → 系统防护 → 自定义规则 / 文件实时监控 → 添加信任")
        print("         · Windows：安全中心 → 病毒和威胁防护 → 勒索软件防护 → 受控文件夹访问")
        return 2
    print(" 结论：部分位置可写 —— 是特定文件夹的权限问题。")
    return 1
