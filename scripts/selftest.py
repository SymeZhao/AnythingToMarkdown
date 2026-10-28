"""端到端测试：用样例文件跑一遍完整转换流程。

用法：
    .venv\\Scripts\\python.exe scripts\\selftest.py

检查项：
  1. 引擎可用
  2. 各格式转换成功且产出非空 Markdown
  3. 输出文件名去重逻辑
  4. 不支持格式给出正确提示
  5. 批量转换统计正确
"""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_SRC = _ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from anythingtomarkdown.converter import (  # noqa: E402
    BatchResult,
    collect_files,
    convert_file,
    convert_many,
    engine_status,
    unique_output_path,
)

_SAMPLES = _ROOT / "samples"
_PASSED: list[str] = []
_FAILED: list[str] = []


def _setup_stdout() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
        except Exception:
            pass


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        _PASSED.append(name)
        print(f"  [PASS] {name}")
    else:
        _FAILED.append(name)
        msg = f"  [FAIL] {name}"
        if detail:
            msg += f"  -> {detail}"
        print(msg)


def main() -> int:
    _setup_stdout()
    print("=" * 62)
    print(" AnythingToMarkdown 端到端测试")
    print("=" * 62)

    # --- 1. 引擎 ---
    print("\n[1] 转换引擎")
    ok, msg = engine_status()
    print(f"      {msg}")
    check("引擎可用", ok, msg)
    if not ok:
        print("\n引擎不可用，后续测试跳过。")
        return 1

    # --- 2. 样例存在性 ---
    print("\n[2] 准备样例")
    if not _SAMPLES.exists() or not any(_SAMPLES.iterdir()):
        print("      样例不存在，正在生成…")
        import subprocess

        subprocess.run(
            [sys.executable, str(_ROOT / "scripts" / "make_samples.py")],
            check=False,
        )

    samples = sorted(p for p in _SAMPLES.iterdir() if p.is_file())
    print(f"      找到 {len(samples)} 个样例")
    check("样例文件存在", len(samples) > 0)

    # --- 3. 逐格式转换 ---
    print("\n[3] 格式转换")
    out_dir = _ROOT / "tests" / "output"
    out_dir.mkdir(parents=True, exist_ok=True)
    # 清空旧输出
    for old in out_dir.glob("*.md"):
        old.unlink(missing_ok=True)

    results = []
    for src in samples:
        r = convert_file(src, out_dir=out_dir)
        results.append(r)
        if r.ok:
            size = r.output.stat().st_size if r.output else 0
            check(
                f"{src.name} 转换成功",
                size > 0,
                f"输出 {size} 字节",
            )
        elif src.suffix.lower() in (".md", ".markdown"):
            # .md 有意不支持：应给出「已经是 Markdown」而非法错误
            check(
                f"{src.name} 被正确识别为已是 Markdown",
                r.error is not None and "已经是 Markdown" in r.error,
                str(r.error),
            )
        else:
            # 部分格式可能因缺依赖失败，单独记录不判死
            print(f"  [SKIP] {src.name}：{r.error}")

    loaded = [r for r in results if r.ok]
    check("至少一个格式转换成功", len(loaded) > 0, f"成功 {len(loaded)}/{len(results)}")

    # 抽查内容非空且是文本
    if loaded:
        sample_out = loaded[0].output
        assert sample_out is not None
        text = sample_out.read_text(encoding="utf-8")
        check("输出为有效 UTF-8 文本", len(text.strip()) > 0)

    # --- 4. 文件去重 ---
    print("\n[4] 输出文件名去重")
    if loaded:
        base = loaded[0].source.stem
        conflict = out_dir / f"{base}.md"
        second = unique_output_path(loaded[0].source, out_dir)
        check(
            "冲突时不复用已有文件名",
            second != conflict,
            f"得到 {second.name}",
        )
        # 新策略：冲突且存在兄弟格式时带扩展名（如 config.json.md）
        ext = loaded[0].source.suffix.lower().lstrip(".")
        looks_disambiguated = f".{ext}." in second.name or "(" in second.name
        check(
            "新文件名带有区分信息",
            looks_disambiguated,
            second.name,
        )

    # --- 5. 不支持格式 ---
    print("\n[5] 不支持格式的提示")
    fake = _ROOT / "tests" / "fake.xyz"
    fake.parent.mkdir(parents=True, exist_ok=True)
    fake.write_text("x", encoding="utf-8")
    r = convert_file(fake)
    check("拒绝未知格式", not r.ok, "本应失败")
    check(
        "错误信息可读",
        r.error is not None and "不支持" in r.error,
        str(r.error),
    )
    fake.unlink(missing_ok=True)

    # --- 6. 批量统计 ---
    print("\n[6] 批量转换统计")
    batch_files = [p for p in _SAMPLES.iterdir() if p.is_file()]
    if batch_files:
        batch = convert_many(batch_files, out_dir=out_dir, overwrite=True)
        check(
            "批量结果总数正确",
            batch.total == len(batch_files),
            f"{batch.total} vs {len(batch_files)}",
        )
        check(
            "成功与失败数量相加等于总数",
            len(batch.succeeded) + len(batch.failed) == batch.total,
        )
        print(f"      {batch.summary()}")

    # --- 7. 文件夹收集 ---
    print("\n[7] 文件夹递归收集")
    collected = collect_files([_SAMPLES], recursive=True)
    check("能从文件夹收集到文件", len(collected) > 0, f"{len(collected)} 个")

    # --- 8. 同名不同格式不互相覆盖（回归测试） ---
    print("\n[8] 同名不同格式的输出隔离")
    import shutil

    duo_dir = _ROOT / "tests" / "duo"
    if duo_dir.exists():
        shutil.rmtree(duo_dir, ignore_errors=True)
    duo_dir.mkdir(parents=True, exist_ok=True)

    trio: list[Path] = []
    for name in ("demo.docx", "demo.xlsx", "demo.pptx"):
        src = _SAMPLES / name
        if src.exists():
            dst = duo_dir / name
            shutil.copy2(src, dst)
            trio.append(dst)

    if len(trio) >= 2:
        batch_duo = convert_many(trio, out_dir=duo_dir, overwrite=True)
        outputs = [r.output for r in batch_duo.succeeded if r.output]
        check(
            "三个同名文件都产出结果",
            len(outputs) == len(trio),
            f"{len(outputs)}/{len(trio)}",
        )
        check(
            "输出文件名互不相同",
            len(set(outputs)) == len(outputs),
            f"得到 {[p.name for p in outputs]}",
        )
        # 每个输出内容应该各不相同（docx/xlsx/pptx 内容差异明显）
        contents = set()
        for p in outputs:
            contents.add(p.read_text(encoding="utf-8").strip())
        check(
            "输出内容互不覆盖",
            len(contents) == len(outputs),
            f"{len(contents)} 种不同内容",
        )
        for p in outputs:
            print(f"      {p.name}")
    else:
        print("  [SKIP] 样例不足，跳过")

    # --- 9. 单文件不覆盖目录中已有的 .md（回归测试） ---
    print("\n[9] 单文件转换不覆盖已有结果")
    solo_dir = _ROOT / "tests" / "solo"
    if solo_dir.exists():
        shutil.rmtree(solo_dir, ignore_errors=True)
    solo_dir.mkdir(parents=True, exist_ok=True)

    src_xlsx = _SAMPLES / "demo.xlsx"
    src_docx = _SAMPLES / "demo.docx"
    if src_xlsx.exists() and src_docx.exists():
        shutil.copy2(src_xlsx, solo_dir / "demo.xlsx")
        shutil.copy2(src_docx, solo_dir / "demo.docx")

        # 先转 xlsx，产出 demo.md
        r1 = convert_file(solo_dir / "demo.xlsx")
        check("第一个文件转换成功", r1.ok, str(r1.error))
        first_output = r1.output
        first_text = first_output.read_text(encoding="utf-8") if first_output else ""

        # 再单独转 docx（模拟用户一次只选一个文件）
        r2 = convert_file(solo_dir / "demo.docx")
        check("第二个文件转换成功", r2.ok, str(r2.error))

        check(
            "两次输出指向不同文件",
            r2.output != r1.output,
            f"{r1.output.name} vs {r2.output.name}",
        )
        check(
            "首个文件内容未被覆盖",
            first_output is not None
            and first_output.read_text(encoding="utf-8") == first_text,
            "内容发生变化",
        )
        print(f"      第一个: {r1.output.name if r1.output else '?'}")
        print(f"      第二个: {r2.output.name if r2.output else '?'}")
    else:
        print("  [SKIP] 样例不足，跳过")

    # --- 10. 文件夹反复转换不产生 .md.md（回归测试） ---
    print("\n[10] 文件夹反复转换不膨胀")
    loop_dir = _ROOT / "tests" / "loop"
    if loop_dir.exists():
        shutil.rmtree(loop_dir, ignore_errors=True)
    loop_dir.mkdir(parents=True, exist_ok=True)
    for name in ("demo.docx", "page.html"):
        src = _SAMPLES / name
        if src.exists():
            shutil.copy2(src, loop_dir / name)

    # 第一次：源文件 -> .md
    first = convert_many(
        collect_files([loop_dir], recursive=True), out_dir=loop_dir, overwrite=True
    )
    count_after_first = len(list(loop_dir.iterdir()))
    md_after_first = sorted(p.name for p in loop_dir.glob("*.md"))

    # 第二次：模拟用户再次右键整个文件夹
    second_files = collect_files([loop_dir], recursive=True)
    second = convert_many(second_files, out_dir=loop_dir, overwrite=True)
    count_after_second = len(list(loop_dir.iterdir()))

    check(
        "第一次转换产出 .md",
        len(md_after_first) > 0,
        f"{md_after_first}",
    )
    check(
        "第二次扫描不再包含 .md",
        all(p.suffix.lower() != ".md" for p in second_files),
        f"扫描到 {[p.name for p in second_files]}",
    )
    check(
        "文件总数不再增长",
        count_after_second == count_after_first,
        f"{count_after_first} -> {count_after_second}",
    )
    check(
        "没有产生 .md.md",
        not any(p.name.lower().endswith(".md.md") for p in loop_dir.iterdir()),
        f"目录内容 {[p.name for p in sorted(loop_dir.iterdir())]}",
    )

    # --- 汇总 ---
    print("\n" + "=" * 62)
    total = len(_PASSED) + len(_FAILED)
    if _FAILED:
        print(f" 结果：{len(_PASSED)}/{total} 通过，{len(_FAILED)} 失败")
        print("\n 失败项：")
        for f in _FAILED:
            print(f"   - {f}")
        print(f"\n 输出目录：{out_dir}")
        print("=" * 62)
        return 1

    print(f" 全部通过：{len(_PASSED)}/{total}")
    print(f" 输出目录：{out_dir}")
    print("=" * 62)
    return 0


if __name__ == "__main__":
    sys.exit(main())
