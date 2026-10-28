"""转换核心：把任意支持的文件转换为 Markdown。

这一层不依赖任何 GUI，可被命令行、右键菜单、图形界面共用。
设计要点：
- 懒加载 MarkItDown 实例（首次转换才导入，加快启动）
- 单个文件失败不影响批量任务
- 输出文件名冲突时自动去重
- 对所有可预期错误给出中文说明
"""
from __future__ import annotations

import os
import re
import shutil
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable, Sequence

#: 进度回调签名：(当前序号, 总数, 当前文件)
ProgressCallback = Callable[[int, int, Path], None]

# ---------------------------------------------------------------- 常量

#: 支持的扩展名（不含点，小写）。图片与音视频第一版暂不开放。
SUPPORTED_EXTENSIONS: frozenset[str] = frozenset({
    # Office
    "docx", "doc", "xlsx", "xls", "pptx", "ppt", "msg", "eml",
    # 文档
    "pdf", "epub", "ipynb",
    # 网页与数据
    # 注意：md / markdown 有意不列入，见 UNSUPPORTED_HINTS 中的说明。
    # 否则「文件夹递归转换」会把上次生成的 .md 再转一遍，产出 .md.md，
    # 每转一次多一批文件，形成无限膨胀。
    "html", "htm", "xhtml", "csv", "json", "jsonl", "xml", "rss", "atom",
    "txt",
    # 压缩包
    "zip",
})

#: 明确不支持、需要提示说明的扩展名 -> 说明文案
UNSUPPORTED_HINTS: dict[str, str] = {
    "md": "这已经是 Markdown 格式，无需转换",
    "markdown": "这已经是 Markdown 格式，无需转换",
    "doc": "旧版 .doc 需要另外安装 LibreOffice 才能转换，建议先另存为 .docx",
    "ppt": "旧版 .ppt 需要另外安装 LibreOffice 才能转换，建议先另存为 .pptx",
    "xls": "旧版 .xls 需要 xlrd 依赖，若失败请另存为 .xlsx",
    "jpg": "图片转换（OCR / AI 描述）尚未开放，将在后续版本支持",
    "jpeg": "图片转换（OCR / AI 描述）尚未开放，将在后续版本支持",
    "png": "图片转换（OCR / AI 描述）尚未开放，将在后续版本支持",
    "gif": "图片转换（OCR / AI 描述）尚未开放，将在后续版本支持",
    "webp": "图片转换（OCR / AI 描述）尚未开放，将在后续版本支持",
    "bmp": "图片转换（OCR / AI 描述）尚未开放，将在后续版本支持",
    "tif": "图片转换（OCR / AI 描述）尚未开放，将在后续版本支持",
    "tiff": "图片转换（OCR / AI 描述）尚未开放，将在后续版本支持",
    "mp3": "音频转写尚未开放，将在后续版本支持",
    "wav": "音频转写尚未开放，将在后续版本支持",
    "m4a": "音频转写尚未开放，将在后续版本支持",
    "mp4": "视频转写尚未开放，将在后续版本支持",
}

_OUTPUT_SUFFIX = ".md"
_MAX_NAME_ATTEMPTS = 999


# ---------------------------------------------------------------- 结果类型


@dataclass
class ConversionResult:
    """单个文件的转换结果。"""

    source: Path
    output: Path | None = None
    ok: bool = False
    error: str | None = None
    elapsed: float = 0.0
    chars: int = 0
    #: 成功但有额外说明（例如原目录不可写，改存到了备用目录）
    note: str | None = None

    @property
    def name(self) -> str:
        return self.source.name

    def describe(self) -> str:
        if self.ok:
            assert self.output is not None
            text = f"✓ {self.name} → {self.output.name}（{self.chars} 字符，{self.elapsed:.1f}s）"
            if self.note:
                text += f"\n   注意：{self.note}"
            return text
        return f"✗ {self.name}：{self.error}"


@dataclass
class BatchResult:
    """批量转换汇总。"""

    items: list[ConversionResult] = field(default_factory=list)

    @property
    def succeeded(self) -> list[ConversionResult]:
        return [r for r in self.items if r.ok]

    @property
    def failed(self) -> list[ConversionResult]:
        return [r for r in self.items if not r.ok]

    @property
    def total(self) -> int:
        return len(self.items)

    def summary(self) -> str:
        if not self.items:
            return "没有可转换的文件"
        if not self.failed:
            return f"全部成功：{len(self.succeeded)} 个文件"
        return (
            f"完成 {self.total} 个：成功 {len(self.succeeded)}，"
            f"失败 {len(self.failed)}"
        )


class ConversionError(Exception):
    """可预期的转换错误，消息为面向用户的中文说明。"""


# ---------------------------------------------------------------- 引擎


class _Engine:
    """MarkItDown 的懒加载包装，屏蔽导入失败并给出友好提示。"""

    _instance = None
    _import_error: str | None = None

    @classmethod
    def get(cls):
        if cls._instance is not None:
            return cls._instance
        if cls._import_error is not None:
            raise ConversionError(cls._import_error)

        try:
            from markitdown import MarkItDown
        except ImportError as exc:  # pragma: no cover - 依赖缺失时的兜底
            cls._import_error = (
                "转换引擎未安装。请先运行 setup.ps1 完成环境安装。\n"
                f"（底层错误：{exc}）"
            )
            raise ConversionError(cls._import_error) from exc

        try:
            # enable_plugins=False：离线场景下不加载外部插件，行为可预测
            cls._instance = MarkItDown(enable_plugins=False)
        except TypeError:
            # 兼容旧版 markitdown 的构造签名
            cls._instance = MarkItDown()
        except Exception as exc:
            cls._import_error = f"转换引擎初始化失败：{exc}"
            raise ConversionError(cls._import_error) from exc

        return cls._instance


# ---------------------------------------------------------------- 工具函数


def normalize_ext(path: Path) -> str:
    """返回小写扩展名（不含点）。无扩展名返回空串。"""
    return path.suffix.lower().lstrip(".")


def is_supported(path: Path) -> bool:
    return normalize_ext(path) in SUPPORTED_EXTENSIONS


def describe_unsupported(path: Path) -> str:
    """对不支持的文件给出具体原因。"""
    ext = normalize_ext(path)
    if ext in UNSUPPORTED_HINTS:
        return UNSUPPORTED_HINTS[ext]
    if not ext:
        return "文件没有扩展名，无法判断格式"
    return f"不支持 .{ext} 格式"


def unique_output_path(source: Path, out_dir: Path | None = None) -> Path:
    """生成不覆盖已有文件的输出路径。

    命名策略：
      1. 首选 ``a.docx`` -> ``a.md``（简洁，符合直觉）
      2. 若 ``a.md`` 已存在，且旁边还有同名的其它格式文件（如 a.xlsx、a.pptx），
         说明它们会互相踩踏，改用 ``a.docx.md`` 加以区分
      3. 仍然冲突则追加序号 ``a (1).md``
    """
    target_dir = out_dir if out_dir is not None else source.parent
    stem = source.stem or source.name

    # 首选：a.md
    candidate = target_dir / f"{stem}{_OUTPUT_SUFFIX}"
    if not candidate.exists():
        return candidate

    # 该位置已被占用。若同名源文件存在多种格式，带上扩展名以免歧义
    ext = normalize_ext(source)
    if ext and _has_sibling_formats(source, target_dir):
        disambiguated = target_dir / f"{stem}.{ext}{_OUTPUT_SUFFIX}"
        if not disambiguated.exists():
            return disambiguated
        stem = f"{stem}.{ext}"

    for i in range(1, _MAX_NAME_ATTEMPTS + 1):
        candidate = target_dir / f"{stem} ({i}){_OUTPUT_SUFFIX}"
        if not candidate.exists():
            return candidate
    raise ConversionError(f"目标目录中同名文件过多：{stem}")


def _has_sibling_formats(source: Path, target_dir: Path) -> bool:
    """判断输出目录中是否已存在由其它格式同名文件生成的 .md。

    例如要转换 a.docx，而目录里已有 a.md（可能来自 a.xlsx），
    此时返回 True，提示需要带扩展名区分。
    """
    try:
        stem = source.stem
        if not stem:
            return False

        # 目录里是否存在同名的其它受支持格式源文件
        for sibling in target_dir.iterdir():
            if not sibling.is_file():
                continue
            if sibling.name == source.name:
                continue
            sib_ext = normalize_ext(sibling)
            if sib_ext in SUPPORTED_EXTENSIONS and sibling.stem == stem:
                return True
    except OSError:
        return False
    return False


def make_disambiguated_paths(
    files: Sequence[Path],
    out_dir: Path | None = None,
    *,
    overwrite: bool = False,
) -> dict[Path, Path]:
    """为一组文件预先规划输出路径，保证同名不同格式不会互相覆盖。

    返回 {源文件: 输出路径}。判断是否重名时同时考虑两个来源：
      1. 本批次内部的重名（如同时转换 a.docx 与 a.xlsx）
      2. 输出目录里已存在的 .md（避免覆盖上一次的结果）

    overwrite=True 时按覆盖处理，不做避让。
    """
    # 按 (输出目录, 主名) 分组
    groups: dict[tuple[str, str], list[Path]] = {}
    for f in files:
        src = Path(f)
        target_dir = Path(out_dir) if out_dir is not None else src.parent
        key = (str(target_dir).lower(), src.stem.lower())
        groups.setdefault(key, []).append(src)

    plan: dict[Path, Path] = {}
    for (dir_key, stem), members in groups.items():
        target_dir = Path(dir_key)
        exts = {normalize_ext(m) for m in members}
        # 本批次内存在同名不同格式
        batch_conflict = len(members) > 1 and len(exts) > 1

        # 输出目录里是否已经有对应的 .md（排除本批次自己的源文件）
        existing_md: set[str] = set()
        try:
            if target_dir.is_dir():
                existing_md = {
                    p.name.lower() for p in target_dir.iterdir()
                    if p.is_file() and p.suffix.lower() == _OUTPUT_SUFFIX
                }
        except OSError:
            existing_md = set()

        for src in members:
            ext = normalize_ext(src)
            simple_name = f"{src.stem}{_OUTPUT_SUFFIX}"
            simple_path = target_dir / simple_name

            # 需要带扩展名区分的两种情况
            needed = batch_conflict or (
                not overwrite and simple_name.lower() in existing_md
            )

            if needed:
                name = f"{src.stem}.{ext}{_OUTPUT_SUFFIX}"
                candidate = target_dir / name
                # 带扩展名后仍冲突，追加序号
                if not overwrite and candidate.exists():
                    for i in range(1, _MAX_NAME_ATTEMPTS + 1):
                        alt = target_dir / f"{src.stem}.{ext} ({i}){_OUTPUT_SUFFIX}"
                        if not alt.exists():
                            candidate = alt
                            break
                plan[src] = candidate
            else:
                plan[src] = simple_path

    return plan


def _fallback_output_dir() -> Path:
    """备用输出目录：本工具在用户本地应用数据下的专属文件夹。"""
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("TEMP") or str(Path.home())
    return Path(base) / "AnythingToMarkdown" / "output"


def _fallback_candidates() -> list[Path]:
    """按优先级列出可选的备用输出目录。

    桌面/文档/下载常被 Windows「受控文件夹访问」保护，
    这些位置都不受该保护，因此能作为兜底。
    """
    candidates: list[Path] = []
    for env, sub in (
        ("LOCALAPPDATA", ("AnythingToMarkdown", "output")),
        ("APPDATA", ("AnythingToMarkdown", "output")),
        ("USERPROFILE", ("AnythingToMarkdown-md",)),
        ("TEMP", ("AnythingToMarkdown-md",)),
    ):
        raw = os.environ.get(env)
        if raw:
            candidates.append(Path(raw).joinpath(*sub))
    return candidates


def _write_to_fallback(filename: str, content: str) -> tuple[Path | None, list[str]]:
    """原目录写不进去时，尝试写到备用目录。

    返回 (成功路径 或 None, 各候选目录的失败原因)。失败原因用于排障：
    如果所有位置都写不了，通常说明有安全软件整体拦截了本程序的写操作。
    """
    errors: list[str] = []
    for target_dir in _fallback_candidates():
        try:
            target_dir.mkdir(parents=True, exist_ok=True)
            target = target_dir / filename
            # 避免覆盖备用目录里的旧文件
            if target.exists():
                for i in range(1, _MAX_NAME_ATTEMPTS + 1):
                    candidate = target_dir / f"{Path(filename).stem} ({i}){_OUTPUT_SUFFIX}"
                    if not candidate.exists():
                        target = candidate
                        break
            with open(target, "w", encoding="utf-8", newline="\n") as fh:
                fh.write(content)
                if not content.endswith("\n"):
                    fh.write("\n")
            return target, errors
        except Exception as exc:
            errors.append(f"{target_dir} → {exc.__class__.__name__}: {exc}")
            continue
    return None, errors


def _describe_permission(exc: PermissionError, path: Path, *, reading: bool) -> str:
    """针对权限错误给出可操作的具体说明（区分读/写、带上路径）。"""
    windex = getattr(exc, "winerror", None)
    errno = getattr(exc, "errno", None)
    detail = f"WinError {windex}" if windex else (f"errno {errno}" if errno else "")

    if reading:
        msg = f"无法读取源文件：{path}"
        msg += "\n  可能原因：文件被其他程序独占打开（如 PDF 阅读器、Word），或安全软件阻止了访问"
    else:
        parent = path.parent
        msg = f"无法写入输出文件：{path}"
        msg += f"\n  输出目录：{parent}"
        msg += "\n  可能原因："
        msg += "\n    1. 文件夹只读，或当前账户没有写入权限（例如 Program Files、系统盘根目录）"
        msg += "\n    2. 同名 .md 正被其他程序打开"
        msg += "\n    3. 安全软件（如火绒、360、Defender 受控文件夹访问）拦截了写入"

    if detail:
        msg += f"\n  系统错误：{detail}"
    return msg


def _humanize_error(exc: Exception, source: Path) -> str:
    """把底层异常翻译成用户能看懂的话。"""
    ext = normalize_ext(source)
    text = f"{exc.__class__.__name__}: {exc}"
    low = text.lower()

    if isinstance(exc, PermissionError):
        return _describe_permission(exc, source, reading=True)
    if isinstance(exc, FileNotFoundError):
        return "文件不存在或路径无法访问"
    if "encrypted" in low or "password" in low:
        return "文件已加密，需要先解除密码保护"
    if "unsupported" in low or "no converter" in low or "not supported" in low:
        return f"该 {ext or '未知'} 格式没有可用的转换器"
    if isinstance(exc, MemoryError):
        return "文件过大，内存不足"
    if "timeout" in low or "timed out" in low:
        return "转换超时，文件可能过大或结构异常"
    if ext == "pdf" and ("corrupt" in low or "invalid" in low or "eof" in low):
        return "PDF 文件损坏或结构异常，无法解析"
    # 兜底：保留原始类型与信息，便于用户反馈
    return text


# ---------------------------------------------------------------- 转换入口


def convert_file(
    source: Path,
    *,
    out_dir: Path | None = None,
    overwrite: bool = False,
    output_path: Path | None = None,
) -> ConversionResult:
    """转换单个文件并写出 Markdown。

    参数:
        source: 源文件路径
        out_dir: 输出去向，默认与源文件同目录
        overwrite: 为真时覆盖同名 .md，否则自动改名
        output_path: 直接指定输出文件路径（批量转换时由调用方预先规划）
    """
    source = Path(source)
    started = time.perf_counter()
    result = ConversionResult(source=source)

    if not source.exists():
        result.error = "文件不存在"
        result.elapsed = time.perf_counter() - started
        return result
    if source.is_dir():
        result.error = "这是一个文件夹，请用批量转换"
        result.elapsed = time.perf_counter() - started
        return result

    ext = normalize_ext(source)
    if ext not in SUPPORTED_EXTENSIONS:
        result.error = describe_unsupported(source)
        result.elapsed = time.perf_counter() - started
        return result

    # ---- 第一步：读取并转换 ----
    # 单独捕获，便于区分「读不了源文件」和「写不了输出文件」，
    # 这两类的处置方式完全不同，混在一起会让用户无从下手。
    try:
        engine = _Engine.get()
        # zip 作为容器转换时返回的是内部各文件的 Markdown 汇总
        conversion = engine.convert(str(source))
        text = (getattr(conversion, "text_content", "") or "").strip()
    except ConversionError as exc:
        result.error = str(exc)
        result.elapsed = time.perf_counter() - started
        return result
    except PermissionError as exc:
        result.error = _describe_permission(exc, source, reading=True)
        result.elapsed = time.perf_counter() - started
        return result
    except Exception as exc:
        result.error = _humanize_error(exc, source)
        result.elapsed = time.perf_counter() - started
        return result

    if not text:
        result.error = "转换结果为空（文件可能是空白、纯图片，或已是 Markdown）"
        result.elapsed = time.perf_counter() - started
        return result

    # ---- 第二步：决定输出路径并写入 ----
    target_dir = Path(out_dir) if out_dir is not None else source.parent
    if output_path is not None:
        output = Path(output_path)
    elif overwrite:
        output = target_dir / f"{source.stem}{_OUTPUT_SUFFIX}"
    else:
        output = unique_output_path(source, target_dir)

    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    try:
        output.parent.mkdir(parents=True, exist_ok=True)
        with open(output, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(normalized)
            if not normalized.endswith("\n"):
                fh.write("\n")
    except PermissionError as exc:
        # 原目录写不进去（常见于桌面/文档被「受控文件夹访问」保护，
        # 或安全软件拦截）。退一步存到本工具的专用目录，尽量让用户拿到结果。
        fallback, fb_errors = _write_to_fallback(output.name, normalized)
        if fallback is not None:
            result.output = fallback
            result.ok = True
            result.chars = len(normalized)
            result.note = (
                f"原目录无法写入（{output.parent}），已改存到：{fallback.parent}"
            )
            result.elapsed = time.perf_counter() - started
            return result

        result.error = _describe_permission(exc, output, reading=False)
        if fb_errors:
            result.error += "\n  备用目录也写入失败："
            for line in fb_errors:
                result.error += f"\n    {line}"
            result.error += (
                "\n  所有位置都写不进去，基本可以确定是有安全软件在拦截本程序。"
                "\n  请把 AnythingToMarkdown.exe 加入白名单（火绒／360／Defender）。"
            )
        result.elapsed = time.perf_counter() - started
        return result
    except OSError as exc:
        result.error = f"无法写入 {output}：{exc.strerror or exc}"
        result.elapsed = time.perf_counter() - started
        return result

    result.output = output
    result.ok = True
    result.chars = len(normalized)
    result.elapsed = time.perf_counter() - started
    return result


def collect_files(paths: Iterable[str | os.PathLike[str]], *, recursive: bool = True) -> list[Path]:
    """把命令行传入的路径展开成待转换文件列表。

    - 文件直接加入
    - 目录则按需递归收集其中支持的文件
    - 结果去重并保持稳定顺序
    """
    found: list[Path] = []
    seen: set[str] = set()

    def _add(p: Path) -> None:
        key = str(p.resolve()).lower()
        if key not in seen:
            seen.add(key)
            found.append(p)

    for raw in paths:
        p = Path(raw)
        if p.is_dir():
            iterator = p.rglob("*") if recursive else p.glob("*")
            for child in sorted(iterator):
                if child.is_file() and is_supported(child):
                    _add(child)
        else:
            # 单个文件即使不支持也加入，以便在结果里给出原因
            _add(p)

    return found


def convert_many(
    files: Sequence[Path],
    *,
    out_dir: Path | None = None,
    overwrite: bool = False,
    progress: ProgressCallback | None = None,
) -> BatchResult:
    """顺序转换多个文件，单个失败不影响其余。

    先整体规划输出路径，避免 a.docx / a.xlsx 这类同名不同格式互相覆盖。
    """
    batch = BatchResult()
    total = len(files)
    plan = make_disambiguated_paths(
        [Path(f) for f in files], out_dir, overwrite=overwrite
    )

    for index, f in enumerate(files, start=1):
        src = Path(f)
        if progress is not None:
            progress(index, total, src)
        planned = plan.get(src)
        batch.items.append(
            convert_file(
                src,
                out_dir=out_dir,
                overwrite=overwrite,
                output_path=planned,
            )
        )
    return batch


# ---------------------------------------------------------------- 诊断


def diagnose_file(source: Path, *, out_dir: Path | None = None) -> list[str]:
    """逐项检查一个文件的转换链路，返回人类可读的诊断报告。

    用于排查「为什么这个文件转不了」：读权限、写权限、引擎、转换本身。
    """
    import traceback

    src = Path(source)
    lines: list[str] = []

    def add(flag: str, text: str) -> None:
        lines.append(f"[{flag}] {text}")

    add("..", f"目标文件: {src}")
    add("..", f"输出目录: {Path(out_dir) if out_dir else src.parent}")
    add("..", f"当前工作目录: {Path.cwd()}")
    import os

    add("..", f"进程用户: {os.environ.get('USERNAME', '?')}")
    add("..", f"是否打包运行: {bool(getattr(__import__('sys'), 'frozen', False))}")
    lines.append("")

    # 1. 存在性
    if not src.exists():
        add("XX", "文件不存在")
        return lines
    add("OK", "文件存在")

    # 2. 大小与属性
    try:
        st = src.stat()
        add("OK", f"大小 {st.st_size} 字节")
        if st.st_size == 0:
            add("!!", "文件是空的（0 字节）")
        if st.st_file_attributes & 0x1:  # FILE_ATTRIBUTE_READONLY
            add("!!", "文件带「只读」属性")
    except OSError as exc:
        add("XX", f"读取文件属性失败：{exc}")

    # 3. 读权限
    try:
        with open(src, "rb") as fh:
            head = fh.read(8)
        add("OK", f"可读取（文件头 {head!r}）")
    except PermissionError as exc:
        add("XX", f"无法读取：{exc}")
        add("!!", "文件被占用或权限不足。请关闭正在打开它的程序，或检查文件夹权限。")
        return lines
    except OSError as exc:
        add("XX", f"读取异常：{exc}")
        return lines

    # 4. 目标目录写权限（实际试写）
    target_dir = Path(out_dir) if out_dir else src.parent
    probe = None
    target_ok = True
    try:
        target_dir.mkdir(parents=True, exist_ok=True)
        probe = target_dir / f".atm-write-probe-{os.getpid()}.tmp"
        probe.write_text("probe", encoding="utf-8")
        probe.unlink()
        add("OK", f"输出目录可写：{target_dir}")
    except PermissionError as exc:
        target_ok = False
        add("XX", f"输出目录不可写：{exc}")
        add("!!", "换一个输出目录试试（--out 参数），或检查安全软件的文件夹保护。")
        if probe is not None:
            try:
                probe.unlink(missing_ok=True)
            except OSError:
                pass
    except OSError as exc:
        target_ok = False
        add("XX", f"输出目录异常：{exc}")

    # 4b. 逐个试写备用目录——判断是「这个文件夹的问题」还是「整体被拦截」
    lines.append("")
    add("..", "备用目录写入测试：")
    any_fallback_ok = False
    for cand in _fallback_candidates():
        probe_c = None
        try:
            cand.mkdir(parents=True, exist_ok=True)
            probe_c = cand / f".atm-probe-{os.getpid()}.tmp"
            probe_c.write_text("probe", encoding="utf-8")
            probe_c.unlink()
            add("OK", f"可写 {cand}")
            any_fallback_ok = True
        except Exception as exc:
            add("XX", f"不可写 {cand} → {exc.__class__.__name__}: {exc}")
            if probe_c is not None:
                try:
                    probe_c.unlink(missing_ok=True)
                except OSError:
                    pass

    if not target_ok:
        lines.append("")
        if any_fallback_ok:
            add("!!", "结论：只有源文件夹写不进去，其他地方正常。")
            add("!!", "      多半是该文件夹权限受限，或安全软件只保护了这个位置。")
            add("!!", "      转换时会自动改存到可写的备用目录。")
        else:
            add("!!", "结论：所有位置都写不进去，说明有安全软件在整体拦截本程序。")
            add("!!", "      请把 AnythingToMarkdown.exe 加入白名单：")
            add("!!", "        · 火绒：防护中心 → 系统防护 → 文件实时监控 / 自定义规则 → 添加信任")
            add("!!", "        · Windows：安全中心 → 病毒和威胁防护 → 勒索软件防护 → 受控文件夹访问")
            add("!!", "      也可能是文件夹本身只读（右键属性 → 取消只读）。")
        return lines

    lines.append("")

    # 5. 引擎
    ok, msg = engine_status()
    add("OK" if ok else "XX", f"引擎：{msg}")
    if not ok:
        return lines

    # 6. 实际转换
    try:
        engine = _Engine.get()
        conversion = engine.convert(str(src))
        text = (getattr(conversion, "text_content", "") or "").strip()
        if text:
            preview = text[:200].replace("\n", " ⏎ ")
            add("OK", f"转换成功，得到 {len(text)} 字符")
            add("..", f"内容预览：{preview}")
        else:
            add("!!", "转换结果为空（可能是扫描版 PDF 或纯图片文档）")
    except Exception as exc:
        add("XX", f"转换失败：{exc.__class__.__name__}: {exc}")
        add("..", "完整堆栈：")
        for line in traceback.format_exc().splitlines():
            lines.append("    " + line)

    return lines


# ---------------------------------------------------------------- 自检


def engine_status() -> tuple[bool, str]:
    """返回 (是否可用, 说明)，供界面显示引擎状态。"""
    try:
        _Engine.get()
    except ConversionError as exc:
        return False, str(exc)
    except Exception as exc:  # pragma: no cover
        return False, f"引擎异常：{exc}"

    try:
        import markitdown  # type: ignore

        ver = getattr(markitdown, "__version__", "未知版本")
    except Exception:
        ver = "未知版本"
    return True, f"MarkItDown 引擎就绪（{ver}）"
