"""图形界面：拖放文件、显示进度、查看结果。

只依赖标准库 tkinter，不引入额外 GUI 框架，打包体积小。
拖放功能基于 tkdnd（tkinter 自带的 dnd 支持），窗口创建失败时降级为选择文件。
"""
from __future__ import annotations

import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from . import __app_name__, __version__
from .converter import (
    SUPPORTED_EXTENSIONS,
    BatchResult,
    ConversionResult,
    collect_files,
    convert_file,
    engine_status,
)


class ConverterGUI:
    def __init__(self) -> None:
        self.root = tk.Tk()
        self.root.title(f"{__app_name__} {__version__}")
        self.root.geometry("760x560")
        self.root.minsize(620, 460)

        self.files: list[Path] = []
        self.queue: queue.Queue = queue.Queue()
        self.worker: threading.Thread | None = None
        self.results: list[ConversionResult] = []

        self.use_out_dir = tk.BooleanVar(value=False)
        self.out_dir = tk.StringVar(value="")
        self.status = tk.StringVar(value="拖入文件，或点击“添加文件”")
        self.overwrite = tk.BooleanVar(value=False)

        self._build_ui()
        self._poll_queue()

    # ------------------------------------------------------------ UI

    def _build_ui(self) -> None:
        style = ttk.Style()
        try:
            style.theme_use("vista")
        except tk.TclError:
            pass

        outer = ttk.Frame(self.root, padding=12)
        outer.pack(fill="both", expand=True)

        # 拖放区
        self.drop_area = tk.Text(
            outer, height=8, wrap="none", relief="flat",
            background="#f5f5f5", foreground="#333333",
            font=("Microsoft YaHei UI", 10),
        )
        self.drop_area.pack(fill="both", expand=True)
        self.drop_area.insert(
            "1.0",
            "\n  把文件拖到这里\n\n"
            "  支持 PDF、Word、Excel、PowerPoint、HTML、EPUB、CSV、JSON、ZIP 等\n"
            f"  （共 {len(SUPPORTED_EXTENSIONS)} 种格式）\n",
        )
        self.drop_area.configure(state="disabled")
        self._enable_drop()

        # 按钮栏
        bar = ttk.Frame(outer)
        bar.pack(fill="x", pady=(10, 0))

        ttk.Button(bar, text="添加文件", command=self.choose_files).pack(side="left")
        ttk.Button(bar, text="添加文件夹", command=self.choose_folder).pack(side="left", padx=(6, 0))
        ttk.Button(bar, text="清空", command=self.clear_files).pack(side="left", padx=(6, 0))

        ttk.Checkbutton(
            bar, text="覆盖已有 .md", variable=self.overwrite
        ).pack(side="left", padx=(18, 0))

        # 输出目录
        out_row = ttk.Frame(outer)
        out_row.pack(fill="x", pady=(8, 0))
        ttk.Checkbutton(
            out_row, text="输出到指定目录", variable=self.use_out_dir,
            command=self._toggle_out_dir,
        ).pack(side="left")
        self.out_entry = ttk.Entry(out_row, textvariable=self.out_dir, state="disabled")
        self.out_entry.pack(side="left", fill="x", expand=True, padx=(8, 6))
        self.out_btn = ttk.Button(
            out_row, text="选择…", command=self.choose_out_dir, state="disabled"
        )
        self.out_btn.pack(side="left")

        # 操作按钮
        actions = ttk.Frame(outer)
        actions.pack(fill="x", pady=(10, 0))
        self.convert_btn = ttk.Button(
            actions, text="开始转换", command=self.start_convert
        )
        self.convert_btn.pack(side="left")
        self.open_btn = ttk.Button(
            actions, text="打开输出目录", command=self.open_output, state="disabled"
        )
        self.open_btn.pack(side="left", padx=(8, 0))

        # 进度条
        self.progress = ttk.Progressbar(outer, mode="determinate")
        self.progress.pack(fill="x", pady=(10, 4))

        # 日志/结果
        self.log = tk.Text(
            outer, height=9, wrap="word", relief="sunken", borderwidth=1,
            font=("Consolas", 9), state="disabled",
        )
        self.log.pack(fill="both", expand=True)

        # 状态栏
        ttk.Label(outer, textvariable=self.status, anchor="w").pack(
            fill="x", pady=(6, 0)
        )

        ok, msg = engine_status()
        self._append_log(("✓ " if ok else "✗ ") + msg)

    def _toggle_out_dir(self) -> None:
        state = "normal" if self.use_out_dir.get() else "disabled"
        self.out_entry.configure(state=state)
        self.out_btn.configure(state=state)

    # ------------------------------------------------------------ 拖放

    def _enable_drop(self) -> None:
        """尝试启用拖放；tkdnd 不可用时静默降级。"""
        try:
            self.root.tk.call("package", "require", "tkdnd")
            self.drop_area.tk.call(
                "tkdnd::drop_target", "register", self.drop_area._w, "DND_Files"
            )
            self.drop_area.bind("<<Drop>>", self._on_drop)
        except Exception:
            # 没有 tkdnd：改用点击提示
            self.drop_area.configure(cursor="hand2")
            self.drop_area.bind("<Button-1>", lambda e: self.choose_files())

    def _on_drop(self, event) -> None:  # pragma: no cover - 需要真实拖放
        raw = event.data
        try:
            items = self.root.tk.splitlist(raw)
        except Exception:
            items = [raw]
        self.add_paths([Path(p) for p in items])

    # ------------------------------------------------------------ 文件管理

    def add_paths(self, paths: list[Path]) -> None:
        added = collect_files(paths, recursive=True)
        if not added:
            self.status.set("没有找到支持的文件")
            return

        existing = {p.resolve() for p in self.files}
        fresh = [p for p in added if p.resolve() not in existing]
        self.files.extend(fresh)
        self._refresh_file_list()
        self.status.set(f"已添加 {len(fresh)} 个文件，共 {len(self.files)} 个")

    def choose_files(self) -> None:
        patterns = " ".join(f"*.{e}" for e in sorted(SUPPORTED_EXTENSIONS))
        chosen = filedialog.askopenfilenames(
            title="选择要转换的文件",
            filetypes=[("支持的文件", patterns), ("所有文件", "*.*")],
        )
        if chosen:
            self.add_paths([Path(p) for p in chosen])

    def choose_folder(self) -> None:
        folder = filedialog.askdirectory(title="选择要转换的文件夹")
        if folder:
            self.add_paths([Path(folder)])

    def choose_out_dir(self) -> None:
        folder = filedialog.askdirectory(title="选择输出目录")
        if folder:
            self.out_dir.set(folder)

    def clear_files(self) -> None:
        self.files.clear()
        self.results.clear()
        self._refresh_file_list()
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")
        self.progress["value"] = 0
        self.status.set("已清空")

    def _refresh_file_list(self) -> None:
        self.drop_area.configure(state="normal")
        self.drop_area.delete("1.0", "end")
        if not self.files:
            self.drop_area.insert("1.0", "\n  把文件拖到这里\n")
        else:
            self.drop_area.insert("1.0", f"待转换（{len(self.files)} 个）：\n\n")
            for f in self.files[:200]:
                self.drop_area.insert("end", f"  {f.name}\n")
            if len(self.files) > 200:
                self.drop_area.insert("end", f"  …还有 {len(self.files) - 200} 个\n")
        self.drop_area.configure(state="disabled")

    # ------------------------------------------------------------ 转换

    def start_convert(self) -> None:
        if self.worker and self.worker.is_alive():
            return
        if not self.files:
            messagebox.showinfo("提示", "请先添加要转换的文件")
            return

        out_dir: Path | None = None
        if self.use_out_dir.get():
            raw = self.out_dir.get().strip()
            if not raw:
                messagebox.showwarning("提示", "请选择输出目录")
                return
            out_dir = Path(raw)
            try:
                out_dir.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                messagebox.showerror("错误", f"无法创建输出目录：{exc}")
                return

        self.convert_btn.configure(state="disabled")
        self.open_btn.configure(state="disabled")
        self.results.clear()
        self.progress.configure(maximum=len(self.files), value=0)
        self._append_log(f"\n开始转换 {len(self.files)} 个文件…")

        files = list(self.files)
        overwrite = self.overwrite.get()
        self.worker = threading.Thread(
            target=self._convert_worker,
            args=(files, out_dir, overwrite),
            daemon=True,
        )
        self.worker.start()

    def _convert_worker(
        self, files: list[Path], out_dir: Path | None, overwrite: bool
    ) -> None:
        for index, f in enumerate(files, start=1):
            try:
                result = convert_file(f, out_dir=out_dir, overwrite=overwrite)
            except Exception as exc:  # 线程内兜底，防止界面卡死
                result = ConversionResult(source=f, error=f"未预期错误：{exc}")
            self.queue.put(("item", index, len(files), result))
        self.queue.put(("done", len(files), len(files), None))

    def _poll_queue(self) -> None:
        try:
            while True:
                kind, index, total, payload = self.queue.get_nowait()
                if kind == "item" and payload is not None:
                    self.results.append(payload)
                    self._append_log(payload.describe())
                    self.progress["value"] = index
                    self.status.set(f"正在转换 {index}/{total}")
                elif kind == "done":
                    self._on_done()
        except queue.Empty:
            pass
        self.root.after(120, self._poll_queue)

    def _on_done(self) -> None:
        self.convert_btn.configure(state="normal")
        batch = BatchResult(items=list(self.results))
        ok_count = len(batch.succeeded)
        fail_count = len(batch.failed)
        self.status.set(batch.summary())
        if ok_count:
            self.open_btn.configure(state="normal")
        self._append_log(f"\n{batch.summary()}")
        if fail_count and not ok_count:
            messagebox.showwarning("转换失败", batch.summary())

    def open_output(self) -> None:
        if not self.results:
            return
        last = next(
            (r for r in reversed(self.results) if r.ok and r.output), None
        )
        if last and last.output:
            try:
                import subprocess

                subprocess.Popen(["explorer", "/select,", str(last.output)])
            except Exception:
                pass

    # ------------------------------------------------------------ 杂项

    def _append_log(self, text: str) -> None:
        self.log.configure(state="normal")
        self.log.insert("end", text + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def run(self) -> int:
        self.root.mainloop()
        return 0


def run_gui() -> int:
    try:
        app = ConverterGUI()
    except tk.TclError as exc:
        print(f"无法启动图形界面：{exc}", file=__import__("sys").stderr)
        return 1
    return app.run()


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(run_gui())
