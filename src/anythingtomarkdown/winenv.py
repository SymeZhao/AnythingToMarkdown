"""Windows 进程环境探测：权限级别、是否提权、父进程。

排查「同一个程序在 PowerShell 里能写文件、从右键菜单启动却处处被拒绝」
这类问题时，关键指标是进程的完整性级别（Integrity Level）：

  Medium（0x2000） 正常用户进程，可写自己的 AppData / 用户目录
  Low   （0x1000） 被沙箱化的进程，只能读，几乎所有位置都写不了
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes

_INTEGRITY_NAMES = {
    0x0000: "Untrusted",
    0x1000: "Low",
    0x2000: "Medium",
    0x3000: "High",
    0x4000: "System",
}


def integrity_level() -> tuple[int | None, str]:
    """返回 (数值, 名称)。取不到时返回 (None, '未知')。"""
    TOKEN_QUERY = 0x0008
    TOKEN_INTEGRITY_LEVEL = 25
    try:
        advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

        # 64 位下必须声明类型，否则句柄会被截断成 32 位导致调用失败
        kernel32.GetCurrentProcess.restype = wintypes.HANDLE
        kernel32.GetCurrentProcess.argtypes = []
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL

        advapi32.OpenProcessToken.argtypes = [
            wintypes.HANDLE,
            wintypes.DWORD,
            ctypes.POINTER(wintypes.HANDLE),
        ]
        advapi32.OpenProcessToken.restype = wintypes.BOOL
        advapi32.GetTokenInformation.argtypes = [
            wintypes.HANDLE,
            ctypes.c_int,
            ctypes.c_void_p,
            wintypes.DWORD,
            ctypes.POINTER(wintypes.DWORD),
        ]
        advapi32.GetTokenInformation.restype = wintypes.BOOL
        advapi32.GetSidSubAuthorityCount.argtypes = [ctypes.c_void_p]
        advapi32.GetSidSubAuthorityCount.restype = ctypes.POINTER(ctypes.c_ubyte)
        advapi32.GetSidSubAuthority.argtypes = [ctypes.c_void_p, wintypes.DWORD]
        advapi32.GetSidSubAuthority.restype = ctypes.POINTER(wintypes.DWORD)

        token = wintypes.HANDLE()
        if not advapi32.OpenProcessToken(
            kernel32.GetCurrentProcess(), TOKEN_QUERY, ctypes.byref(token)
        ):
            err = ctypes.get_last_error()
            return None, f"未知（OpenProcessToken 失败，错误码 {err}）"

        try:
            size = wintypes.DWORD(0)
            advapi32.GetTokenInformation(
                token, TOKEN_INTEGRITY_LEVEL, None, 0, ctypes.byref(size)
            )
            if size.value == 0:
                return None, "未知（无完整性信息）"

            buf = ctypes.create_string_buffer(size.value)
            if not advapi32.GetTokenInformation(
                token,
                TOKEN_INTEGRITY_LEVEL,
                buf,
                size,
                ctypes.byref(size),
            ):
                return None, "未知（GetTokenInformation 失败）"

            # TOKEN_MANDATORY_LABEL = { SID_AND_ATTRIBUTES { PSID Sid; DWORD Attributes } }
            sid = ctypes.cast(buf, ctypes.POINTER(ctypes.c_void_p))[0]
            sub_count = advapi32.GetSidSubAuthorityCount(sid)[0]
            level = advapi32.GetSidSubAuthority(sid, sub_count - 1)[0]
        finally:
            kernel32.CloseHandle(token)

        return level, _INTEGRITY_NAMES.get(level, f"未知（0x{level:04X}）")
    except Exception as exc:  # pragma: no cover
        return None, f"未知（{exc}）"


def is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:  # pragma: no cover
        return False


def parent_process() -> str:
    """返回父进程名称与 PID，例如 'explorer.exe (pid 4321)'。"""
    TH32CS_SNAPPROCESS = 0x00000002
    INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value

    class PROCESSENTRY32W(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD),
            ("cntUsage", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD),
            ("th32DefaultHeapID", ctypes.POINTER(wintypes.ULONG)),
            ("th32ModuleID", wintypes.DWORD),
            ("cntThreads", wintypes.DWORD),
            ("th32ParentProcessID", wintypes.DWORD),
            ("pcPriClassBase", ctypes.c_long),
            ("dwFlags", wintypes.DWORD),
            ("szExeFile", wintypes.WCHAR * 260),
        ]

    try:
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
        k32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
        k32.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
        k32.Process32FirstW.restype = wintypes.BOOL
        k32.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
        k32.Process32NextW.restype = wintypes.BOOL
        k32.CloseHandle.argtypes = [wintypes.HANDLE]

        snapshot = k32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
        if not snapshot or snapshot == INVALID_HANDLE_VALUE:
            return "未知"

        try:
            entry = PROCESSENTRY32W()
            entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
            table: dict[int, tuple[int, str]] = {}
            if k32.Process32FirstW(snapshot, ctypes.byref(entry)):
                while True:
                    table[entry.th32ProcessID] = (
                        entry.th32ParentProcessID,
                        entry.szExeFile,
                    )
                    entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
                    if not k32.Process32NextW(snapshot, ctypes.byref(entry)):
                        break
        finally:
            k32.CloseHandle(snapshot)

        me = ctypes.windll.kernel32.GetCurrentProcessId()
        info = table.get(me)
        if not info:
            return "未知"
        ppid = info[0]
        parent = table.get(ppid)
        name = parent[1] if parent else "?"
        return f"{name}（pid {ppid}）"
    except Exception as exc:  # pragma: no cover
        return f"未知（{exc}）"


def describe() -> list[str]:
    """返回可直接打印的环境说明行。"""
    level, name = integrity_level()
    lines = [
        f"完整性级别: {name}" + (f"（0x{level:04X}）" if level is not None else ""),
        f"管理员权限: {'是' if is_admin() else '否'}",
        f"父进程    : {parent_process()}",
    ]
    if level == 0x1000:
        lines.append(
            "  ⚠ 进程运行在 Low 级别，这是被沙箱化的标志："
            "只能读取，几乎所有位置都无法写入。"
        )
    return lines
