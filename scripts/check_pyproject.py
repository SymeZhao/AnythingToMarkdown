"""校验 pyproject.toml 是否为合法且真正可用的 PEP 621 配置。

单独拆成一个文件，是因为这段最早出过事故：文件名是 pyproject.toml，
内容却是 setup.py 的 setup() 调用 —— 长得像，但 `pip install -e .` 必失败。
"""
from __future__ import annotations

import sys
import tomllib
from pathlib import Path


def main() -> int:
    root = Path(__file__).resolve().parent.parent
    pyproject = root / "pyproject.toml"

    if not pyproject.is_file():
        print(f"[XX] 找不到 {pyproject}")
        return 1

    raw = pyproject.read_text(encoding="utf-8", errors="replace")

    # 最直接的那个坑：把 setup.py 的内容写进了 pyproject.toml
    if "setup(" in raw:
        print("[XX] pyproject.toml 里出现了 setup() 调用 —— 这像是把 setup.py 的内容写错了")
        return 1

    try:
        data = tomllib.loads(raw)
    except Exception as exc:
        print(f"[XX] 不是合法 TOML：{exc}")
        return 1

    project = data.get("project") or {}
    build = data.get("build-system") or {}
    problems: list[str] = []

    if not project.get("name"):
        problems.append("缺少 project.name")
    if not project.get("version"):
        problems.append("缺少 project.version")
    if not project.get("requires-python"):
        problems.append("缺少 project.requires-python")

    scripts = project.get("scripts") or {}
    if scripts.get("atm") != "anythingtomarkdown.cli:main":
        problems.append("project.scripts.atm 未指向 anythingtomarkdown.cli:main")

    if build.get("build-backend") != "setuptools.build_meta":
        problems.append("build-system.build-backend 不是 setuptools.build_meta")

    if (data.get("tool", {}).get("setuptools", {}).get("package-dir", {}).get("") != "src"):
        problems.append("tool.setuptools.package-dir 未指向 src")

    if problems:
        for p in problems:
            print(f"[XX] {p}")
        return 1

    print(f"[OK] pyproject.toml: {project['name']} {project['version']}")
    print("PYPROJECT_OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
