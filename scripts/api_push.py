"""通过 GitHub REST API 推送本地 git 仓库（绕过 git 命令行）。

背景：某些受限环境不允许 git 创建子进程管道，导致 push 失败，
但 Python 的 urllib 仍可正常访问 GitHub API。

实现思路：复用本地已提交的 git 对象，走 Git Data API：
  1. 为每个文件创建 blob
  2. 创建 tree（保留完整目录结构）
  3. 创建 commit
  4. 更新 main 分支引用

用法：
    python scripts/api_push.py <token> [owner/repo]
"""
from __future__ import annotations

import base64
import json
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

GIT = r"C:\ucrt64\bin\git.exe"
API = "https://api.github.com"


def read_repo_meta(root: Path) -> dict[str, str]:
    """直接读取 .git 下的文件，不使用子进程。

    受限环境禁止创建管道，subprocess 调用 git 会失败，
    因此这里改为解析 git 的元数据文件。
    """
    git_dir = root / ".git"
    if not git_dir.is_dir():
        raise RuntimeError(f"不是 git 仓库：{root}")

    # 当前分支：.git/HEAD 内容形如 "ref: refs/heads/main"
    head = (git_dir / "HEAD").read_text(encoding="utf-8").strip()
    if head.startswith("ref:"):
        ref = head.split(":", 1)[1].strip()
        branch = ref.rsplit("/", 1)[-1]
        ref_file = git_dir / ref.replace("/", "\\")
        commit_sha = ref_file.read_text(encoding="utf-8").strip() if ref_file.exists() else ""
    else:
        branch = "main"
        commit_sha = head

    # 配置：从 .git/config 找 user 信息
    name, email = "Unknown", "unknown@example.com"
    cfg = git_dir / "config"
    if cfg.exists():
        section = ""
        for line in cfg.read_text(encoding="utf-8", errors="replace").splitlines():
            s = line.strip()
            if s.startswith("[") and s.endswith("]"):
                section = s[1:-1].strip().lower()
            elif "=" in s and section == "user":
                k, _, v = s.partition("=")
                k, v = k.strip(), v.strip()
                if k == "name":
                    name = v
                elif k == "email":
                    email = v

    return {
        "branch": branch,
        "commit": commit_sha,
        "author_name": name,
        "author_email": email,
    }


def commit_message() -> str:
    """从第一次提交的 message 文件读取（本仓库只有一个初始提交）。"""
    return (
        "feat: 任意格式文件一键转 Markdown（Windows 右键菜单）\n\n"
        "基于 Microsoft MarkItDown 的离线转换工具，为 Windows 补齐右键菜单集成。\n\n"
        "## 功能\n"
        "- 支持 docx/xlsx/xls/pptx/pdf/html/csv/json/xml/epub/ipynb/zip/txt 等格式\n"
        "- 文件右键、多选、文件夹右键均可转换\n"
        "- 输出到源文件旁同名 .md，重复转换刷新而非堆副本\n"
        "- 同名不同格式自动区分（demo.docx.md / demo.xlsx.md）\n"
        "- tkinter 图形界面，支持拖放与批量\n"
        "- 全中文错误提示，可读性优先\n\n"
        "## 工程要点\n"
        "- 转换核心与 UI 解耦，CLI / GUI / 右键菜单共用\n"
        "- 输出路径冲突检测，避免互相覆盖\n"
        "- 提供 --diagnose / --writetest 排障命令\n"
        "- 识别进程完整性级别，辅助排查权限问题\n\n"
        "## 已知问题\n"
        "- Windows 11 新菜单不显示传统 shell 项，需在「显示更多选项」中使用\n"
        "- venv 内的 python.exe 副本可能被安全软件降权，提供系统 Python 模式规避"
    )


def list_tracked_files(root: Path) -> list[str]:
    """读取 .git/index 得到被跟踪的文件列表。

    index 是二进制格式，这里用最简方式解析：扫描其中的路径字符串。
    更稳妥的做法是读暂存区，但受限环境下这是可行方案。
    """
    index_path = root / ".git" / "index"
    if not index_path.exists():
        raise RuntimeError("找不到 .git/index，请先 git add")

    data = index_path.read_bytes()
    if data[:4] != b"DIRC":
        raise RuntimeError("无法识别的 git index 格式")

    version = int.from_bytes(data[4:8], "big")
    count = int.from_bytes(data[8:12], "big")

    files: list[str] = []
    pos = 12
    for _ in range(count):
        if pos + 62 > len(data):
            break
        # 每项固定 62 字节头部（v2），之后是路径 + NUL 填充
        flags = int.from_bytes(data[pos + 60 : pos + 62], "big")
        name_len = flags & 0x0FFF
        entry_start = pos
        pos += 62

        if version >= 4:
            # v4 有前缀压缩，遇到就退回扫描式解析
            break

        if name_len < 0x0FFF and name_len > 0:
            raw = data[pos : pos + name_len]
            name = raw.decode("utf-8", "replace")
            pos += name_len
        else:
            end = data.index(b"\0", pos)
            name = data[pos:end].decode("utf-8", "replace")
            pos = end

        # 路径以 NUL 结尾并填充到 8 字节对齐
        entry_len = (pos - entry_start + 8) & ~7
        pos = entry_start + entry_len

        files.append(name)

    return files


class GitHub:
    def __init__(self, token: str) -> None:
        self.token = token

    def call(self, method: str, path: str, payload: dict | None = None) -> dict:
        url = API + path if path.startswith("/") else path
        data = json.dumps(payload).encode() if payload is not None else None
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("Authorization", "token " + self.token)
        req.add_header("Accept", "application/vnd.github+json")
        req.add_header("User-Agent", "atm-push")
        if data is not None:
            req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                body = resp.read().decode()
                return json.loads(body) if body else {}
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:500]
            raise RuntimeError(f"HTTP {exc.code} {method} {path}\n{detail}") from exc


def main(argv: list[str]) -> int:
    if len(argv) < 1:
        print("用法: python scripts/api_push.py <token> [owner/repo]", file=sys.stderr)
        return 2

    token = argv[0]
    repo = argv[1] if len(argv) > 1 else "SymeZhao/AnythingToMarkdown"
    root = Path(__file__).resolve().parent.parent

    gh = GitHub(token)

    print(f"仓库: {repo}")

    # ---- 读取本地仓库信息（不调用子进程）----
    meta = read_repo_meta(root)
    branch = meta["branch"]
    author_name = meta["author_name"]
    author_email = meta["author_email"]
    message = commit_message()

    print(f"分支: {branch}")
    print(f"作者: {author_name} <{author_email}>")

    # ---- 项目文件清单（跳过 git 忽略的）----
    skip_dirs = {
        ".git", ".venv", "dist", "build", "__pycache__", "out",
        ".build", ".probe", ".runtmp", ".runplain",
    }
    skip_files = {"进度存档.md"}
    skip_suffix = {".pyc", ".pyo", ".spec"}
    skip_sample_md = {
        "demo.md", "demo.docx.md", "demo.xlsx.md", "demo.pptx.md",
        "demo.pdf.md", "page.md", "data.md", "config.md", "feed.md", "plain.md",
    }

    files: list[str] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(root)
        parts = rel.parts
        if any(p in skip_dirs for p in parts):
            continue
        if rel.name in skip_files or rel.suffix in skip_suffix:
            continue
        if parts[0] == "samples" and rel.name in skip_sample_md:
            continue
        files.append(rel.as_posix())

    print(f"文件数: {len(files)}")

    # ---- 0. 空仓库限制：Git Data API 无法在空仓库上创建 blob ----
    # 先用 Contents API 创建一个占位文件作为初始提交，之后就正常了。
    repo_info = gh.call("GET", f"/repos/{repo}")
    branch = repo_info.get("default_branch") or branch
    if repo_info.get("size", 0) == 0:
        print("空仓库，先创建初始占位提交…")
        gh.call(
            "PUT",
            f"/repos/{repo}/contents/.gitkeep",
            {
                "message": "chore: 初始化仓库",
                "content": base64.b64encode(b"# placeholder\n").decode("ascii"),
                "branch": branch,
            },
        )
        print("  初始提交已创建")

    # ---- 1. 上传 blob ----
    tree_items: list[dict] = []
    for idx, rel in enumerate(files, 1):
        full = root / rel
        content = full.read_bytes()
        is_text = not any(
            rel.endswith(ext)
            for ext in (".docx", ".xlsx", ".pptx", ".pdf", ".zip",
                        ".png", ".jpg", ".ico", ".exe")
        )
        if is_text:
            blob = {
                "content": content.decode("utf-8"),
                "encoding": "utf-8",
            }
        else:
            blob = {
                "content": base64.b64encode(content).decode("ascii"),
                "encoding": "base64",
            }
        resp = gh.call("POST", f"/repos/{repo}/git/blobs", blob)
        tree_items.append(
            {
                "path": rel.replace("\\", "/"),
                "mode": "100755" if rel.endswith((".ps1", ".sh")) else "100644",
                "type": "blob",
                "sha": resp["sha"],
            }
        )
        if idx % 10 == 0 or idx == len(files):
            print(f"  已上传 {idx}/{len(files)}")

    # ---- 2. 创建 tree ----
    tree_resp = gh.call("POST", f"/repos/{repo}/git/trees", {"tree": tree_items})
    tree_sha = tree_resp["sha"]
    print(f"tree: {tree_sha}")

    # ---- 3. 创建 commit（若已有初始提交，则以它为父）----
    parents: list[str] = []
    try:
        ref_info = gh.call("GET", f"/repos/{repo}/git/ref/heads/{branch}")
        parents = [ref_info["object"]["sha"]]
        print(f"父提交: {parents[0][:12]}")
    except RuntimeError:
        print("无父提交（首个提交）")

    commit_resp = gh.call(
        "POST",
        f"/repos/{repo}/git/commits",
        {
            "message": message,
            "tree": tree_sha,
            "parents": parents,
            "author": {"name": author_name, "email": author_email},
            "committer": {"name": author_name, "email": author_email},
        },
    )
    commit_sha = commit_resp["sha"]
    print(f"commit: {commit_sha}")

    # ---- 4. 创建/更新分支引用 ----
    try:
        gh.call(
            "POST",
            f"/repos/{repo}/git/refs",
            {"ref": f"refs/heads/{branch}", "sha": commit_sha},
        )
        print(f"已创建分支 {branch}")
    except RuntimeError:
        # 已存在则强制更新
        gh.call(
            "PATCH",
            f"/repos/{repo}/git/refs/heads/{branch}",
            {"sha": commit_sha, "force": True},
        )
        print(f"已更新分支 {branch}")

    print()
    print(f"完成: https://github.com/{repo}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
