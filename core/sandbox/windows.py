"""Windows 沙箱后端（v1.4.1）——仿 Codex Windows 路线：Job Object + 受限令牌。

两档原语：

1. **Job Object**（异步接线形态，接入 utils/shell.py spawn 后）：
   内核强制 ``KILL_ON_JOB_CLOSE``（句柄全关 = 整棵树连坐回收）+
   ``ACTIVE_PROCESS`` / ``PROCESS_MEMORY`` 限额。替代 psutil 轮询的
   监督式软限（50ms 竞态窗）为内核硬限。
2. **受限令牌 + 低完整性**（同步原语 ``spawn_restricted_sync``）：
   ``CreateRestrictedToken``（DISABLE_MAX_PRIVILEGE | LUA）+ Low IL
   （S-1-16-4096）→ ``CreateProcessWithTokenW``（CREATE_SUSPENDED）
   → 可挂 Job → ResumeThread。

诚实边界（v1.4.1）：
- 受限令牌约束的是**特权与完整性级别**，不做按路径的文件 ACL 精细
  域（Codex 的 deny-SID/能力 SID 那层留给后续卡）；write/edit/patch
  工具仍由 core/safety/policy.py 写白名单管（软件闸）。
- **Job-only 形态落实不了 mode/network/deny_read_globs**：
  ``plan_windows_command`` 经 ``unenforced_constraints`` 如实列出落空
  约束——fail_closed 拒绝执行，downgrade 响亮降级（``downgraded=True``
  + detail 列明），绝不返回仿佛全策略已落实的结果（2026-10-07 审计修）。
- ``spawn_restricted_sync`` 是同步原语，尚未接入 shell.py 的异步
  spawn 链（asyncio 无法直接注入令牌；v1.4.2 接缝，见 manager 注释）。

全部被调失败一律 ``SandboxUnavailableError`` 并带 ``GetLastError`` 上下文——
绝不静默 unsandbox（local-agent-process-isolation 纪律）。
"""

from __future__ import annotations

import ctypes
import logging
from ctypes import wintypes
from dataclasses import dataclass
from typing import Any

from .errors import SandboxUnavailableError
from .types import JobPlan, WrappedCommand
from .policy import SandboxPolicy

_logger = logging.getLogger(__name__)

kernel32 = ctypes.windll.kernel32
advapi32 = ctypes.windll.advapi32

# 64 位 HANDLE 安全：不显式签名时 ctypes 默认 restype/argtype=c_int，64 位
# 句柄会在边界被截断（INVALID_HANDLE）。统一在此声明全部用到的签名。
_H = wintypes.HANDLE
_PVOID = ctypes.c_void_p
kernel32.GetCurrentProcess.restype = _H
kernel32.GetCurrentProcess.argtypes = []
kernel32.CreateJobObjectW.restype = _H
kernel32.CreateJobObjectW.argtypes = [_PVOID, wintypes.LPCWSTR]
kernel32.SetInformationJobObject.restype = wintypes.BOOL
kernel32.SetInformationJobObject.argtypes = [_H, ctypes.c_int, _PVOID, wintypes.DWORD]
kernel32.QueryInformationJobObject.restype = wintypes.BOOL
kernel32.QueryInformationJobObject.argtypes = [
    _H, ctypes.c_int, _PVOID, wintypes.DWORD, _PVOID]
kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
kernel32.AssignProcessToJobObject.argtypes = [_H, _H]
kernel32.OpenProcess.restype = _H
kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
kernel32.CloseHandle.restype = wintypes.BOOL
kernel32.CloseHandle.argtypes = [_H]
kernel32.TerminateProcess.restype = wintypes.BOOL
kernel32.TerminateProcess.argtypes = [_H, wintypes.UINT]
kernel32.WaitForSingleObject.restype = wintypes.DWORD
kernel32.WaitForSingleObject.argtypes = [_H, wintypes.DWORD]
kernel32.GetExitCodeProcess.restype = wintypes.BOOL
kernel32.GetExitCodeProcess.argtypes = [_H, ctypes.POINTER(wintypes.DWORD)]
kernel32.ResumeThread.restype = wintypes.DWORD
kernel32.ResumeThread.argtypes = [_H]

advapi32.OpenProcessToken.restype = wintypes.BOOL
advapi32.OpenProcessToken.argtypes = [_H, wintypes.DWORD, ctypes.POINTER(_H)]
advapi32.CreateRestrictedToken.restype = wintypes.BOOL
advapi32.CreateRestrictedToken.argtypes = [
    _H, wintypes.DWORD, wintypes.DWORD, _PVOID,
    wintypes.DWORD, _PVOID, wintypes.DWORD, _PVOID, ctypes.POINTER(_H)]
advapi32.SetTokenInformation.restype = wintypes.BOOL
advapi32.SetTokenInformation.argtypes = [
    _H, ctypes.c_int, _PVOID, wintypes.DWORD]
advapi32.GetTokenInformation.restype = wintypes.BOOL
advapi32.GetTokenInformation.argtypes = [
    _H, ctypes.c_int, _PVOID, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
advapi32.ConvertStringSidToSidW.restype = wintypes.BOOL
advapi32.ConvertStringSidToSidW.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(_PVOID)]
advapi32.ConvertSidToStringSidW.restype = wintypes.BOOL
advapi32.ConvertSidToStringSidW.argtypes = [
    _PVOID, ctypes.POINTER(ctypes.c_wchar_p)]
kernel32.InitializeProcThreadAttributeList.restype = wintypes.BOOL
kernel32.InitializeProcThreadAttributeList.argtypes = [
    _PVOID, wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(ctypes.c_size_t)]
kernel32.UpdateProcThreadAttribute.restype = wintypes.BOOL
kernel32.UpdateProcThreadAttribute.argtypes = [
    _PVOID, wintypes.DWORD, wintypes.DWORD, _PVOID, ctypes.c_size_t, _PVOID, _PVOID]
kernel32.DeleteProcThreadAttributeList.restype = None
kernel32.DeleteProcThreadAttributeList.argtypes = [_PVOID]
kernel32.LocalFree.restype = _H
kernel32.LocalFree.argtypes = [_PVOID]

advapi32.CreateProcessWithTokenW.restype = wintypes.BOOL
advapi32.CreateProcessWithTokenW.argtypes = [
    _H, wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
    _PVOID, wintypes.LPCWSTR, _PVOID, _PVOID]

# ---- Job Object 常量 -------------------------------------------------------
_JOB_NAME = None
JobObjectExtendedLimitInformation = 9
JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
JOB_OBJECT_LIMIT_ACTIVE_PROCESS = 0x00000008
JOB_OBJECT_LIMIT_PROCESS_MEMORY = 0x00000100

# ---- 令牌 / 进程常量 --------------------------------------------------------
TOKEN_DUPLICATE = 0x0002
TOKEN_QUERY = 0x0008
TOKEN_ASSIGN_PRIMARY = 0x0001
DISABLE_MAX_PRIVILEGE = 0x1
LUA_TOKEN = 0x4
CREATE_SUSPENDED = 0x00000004
CREATE_UNICODE_ENVIRONMENT = 0x00000400
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
PROCESS_SET_QUOTA = 0x0100
PROCESS_TERMINATE = 0x0001
TokenIntegrityLevel = 25
SE_GROUP_INTEGRITY = 0x00000020
LOW_INTEGRITY_SID = "S-1-16-4096"       # Low Mandatory Level
RESTRICTED_GROUP_SID = "S-1-5-12"        # NT AUTHORITY\RESTRICTED


class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", wintypes.LARGE_INTEGER),
        ("PerJobUserTimeLimit", wintypes.LARGE_INTEGER),
        ("LimitFlags", wintypes.DWORD),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", wintypes.DWORD),
        ("Affinity", ctypes.c_size_t),
        ("PriorityClass", wintypes.DWORD),
        ("SchedulingClass", wintypes.DWORD),
    ]


class IO_COUNTERS(ctypes.Structure):
    _fields_ = [(name, ctypes.c_uint64) for name in (
        "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
        "ReadTransferCount", "WriteTransferCount", "OtherTransferCount",
    )]


class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", JOBOBJECT_BASIC_LIMIT_INFORMATION),
        ("IoInfo", IO_COUNTERS),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


class TOKEN_MANDATORY_LABEL(ctypes.Structure):
    _fields_ = [("Label", ctypes.c_void_p), ("Attributes", wintypes.DWORD)]


class STARTUPINFOW(ctypes.Structure):
    _fields_ = [
        ("cb", wintypes.DWORD), ("lpReserved", wintypes.LPWSTR),
        ("lpDesktop", wintypes.LPWSTR), ("lpTitle", wintypes.LPWSTR),
        ("dwX", wintypes.DWORD), ("dwY", wintypes.DWORD),
        ("dwXSize", wintypes.DWORD), ("dwYSize", wintypes.DWORD),
        ("dwXCountChars", wintypes.DWORD), ("dwYCountChars", wintypes.DWORD),
        ("dwFillAttribute", wintypes.DWORD), ("dwFlags", wintypes.DWORD),
        ("wShowWindow", wintypes.WORD), ("cbReserved2", wintypes.WORD),
        ("lpReserved2", ctypes.c_void_p),
        ("hStdInput", wintypes.HANDLE), ("hStdOutput", wintypes.HANDLE),
        ("hStdError", wintypes.HANDLE),
    ]


class PROCESS_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("hProcess", wintypes.HANDLE), ("hThread", wintypes.HANDLE),
        ("dwProcessId", wintypes.DWORD), ("dwThreadId", wintypes.DWORD),
    ]


class STARTUPINFOEXW(ctypes.Structure):
    _fields_ = [("StartupInfo", STARTUPINFOW), ("lpAttributeList", ctypes.c_void_p)]


EXTENDED_STARTUPINFO_PRESENT = 0x00080000
PROC_THREAD_ATTRIBUTE_MANDATORY_LABEL = 0x00020003


def _win_err(context: str) -> SandboxUnavailableError:
    return SandboxUnavailableError(f"{context}（GetLastError={ctypes.GetLastError()}）")


def _close_handle(handle: int) -> None:
    if handle:
        kernel32.CloseHandle(wintypes.HANDLE(handle))


def _create_job(plan: JobPlan) -> int:
    flags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    if plan.max_processes > 0:
        flags |= JOB_OBJECT_LIMIT_ACTIVE_PROCESS
    if plan.max_memory_bytes > 0:
        flags |= JOB_OBJECT_LIMIT_PROCESS_MEMORY
    info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
    info.BasicLimitInformation.LimitFlags = flags
    info.BasicLimitInformation.ActiveProcessLimit = plan.max_processes
    info.ProcessMemoryLimit = plan.max_memory_bytes
    handle = kernel32.CreateJobObjectW(None, _JOB_NAME)
    if not handle:
        raise _win_err("CreateJobObjectW 失败")
    ok = kernel32.SetInformationJobObject(
        wintypes.HANDLE(handle),
        JobObjectExtendedLimitInformation,
        ctypes.byref(info),
        ctypes.sizeof(info),
    )
    if not ok:
        _close_handle(handle)
        raise _win_err("SetInformationJobObject 失败（Job 限额设置）")
    return handle


def apply_job_to_pid(pid: int, plan: JobPlan) -> int:
    """把 pid 指派的进程塞进新建 Job（内核限额 + kill-on-close）。

    语义：返回 Job 句柄——**调用方持有**，全部关闭时整棵树连坐。
    """
    handle = _create_job(plan)
    try:
        assign_pid_to_job_handle(handle, pid)
    except BaseException:
        _close_handle(handle)
        raise
    return handle


def open_job(plan: JobPlan) -> int:
    """创建 Job 但不指派（spawn_restricted_sync 用；调用方持有句柄）。"""
    return _create_job(plan)


def assign_pid_to_job_handle(job_handle: int, pid: int) -> None:
    proc = kernel32.OpenProcess(
        PROCESS_SET_QUOTA | PROCESS_TERMINATE | PROCESS_QUERY_LIMITED_INFORMATION,
        False, pid,
    )
    if not proc:
        raise _win_err(f"OpenProcess 失败（pid={pid}）")
    try:
        if not kernel32.AssignProcessToJobObject(
                wintypes.HANDLE(job_handle), wintypes.HANDLE(proc)):
            raise _win_err(f"AssignProcessToJobObject 失败（pid={pid}）")
    finally:
        kernel32.CloseHandle(wintypes.HANDLE(proc))


class _PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("cntUsage", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD),
        ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
        ("th32DefaultModuleID", wintypes.DWORD),
        ("cntThreads", wintypes.DWORD),
        ("th32ParentProcessID", wintypes.DWORD),
        ("pcPriClassBase", ctypes.c_long),
        ("dwFlags", wintypes.DWORD),
        ("szExeFile", wintypes.WCHAR * 260),
    ]


def _descendants(root_pid: int) -> list[int]:
    """Toolhelp 快照求 root_pid 的全部子孙 pid（require-free，替代 psutil 依赖）。"""
    snapshot = kernel32.CreateToolhelp32Snapshot(0x00000002, 0)  # TH32CS_SNAPPROCESS
    if not snapshot or snapshot == ctypes.c_void_p(-1).value:
        return []
    try:
        entry = _PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(_PROCESSENTRY32W)
        pairs: list[tuple[int, int]] = []
        ok = kernel32.Process32FirstW(snapshot, ctypes.byref(entry))
        while ok:
            pairs.append((entry.th32ProcessID, entry.th32ParentProcessID))
            ok = kernel32.Process32NextW(snapshot, ctypes.byref(entry))
    finally:
        _close_handle(snapshot)
    kids = [root_pid]
    result: list[int] = []
    while kids:
        parent = kids.pop()
        for pid, ppid in pairs:
            if ppid == parent and pid not in result and pid != root_pid:
                result.append(pid)
                kids.append(pid)
    return result


kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
kernel32.Process32FirstW.restype = wintypes.BOOL
kernel32.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(_PROCESSENTRY32W)]
kernel32.Process32NextW.restype = wintypes.BOOL
kernel32.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(_PROCESSENTRY32W)]


# ---- 线程快照（CREATE_SUSPENDED 出生即绑定用） -------------------------------
class THREADENTRY32(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("cntUsage", wintypes.DWORD),
        ("th32ThreadID", wintypes.DWORD),
        ("th32OwnerProcessID", wintypes.DWORD),
        ("tpBasePri", wintypes.LONG),
        ("tpDeltaPri", wintypes.LONG),
        ("dwFlags", wintypes.DWORD),
    ]


TH32CS_SNAPTHREAD = 0x00000004
THREAD_SUSPEND_RESUME = 0x0002

kernel32.OpenThread.restype = _H
kernel32.OpenThread.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
kernel32.Thread32First.restype = wintypes.BOOL
kernel32.Thread32First.argtypes = [_H, ctypes.POINTER(THREADENTRY32)]
kernel32.Thread32Next.restype = wintypes.BOOL
kernel32.Thread32Next.argtypes = [_H, ctypes.POINTER(THREADENTRY32)]


def assign_job_to_tree(pid: int, plan: JobPlan) -> int:
    """新建 Job 并指派 pid **及其全部现存子孙**（后补枚举原语）。

    Job 语义：只有**指派后**诞生的子孙才自动入 Job——已存在的子孙必须逐个
    指派，否则 kill-on-close 会漏杀（2026-10-06 实测：晚 0.5s 指派，
    cmd 死了、ping 活着）。spawn 后立刻调用本函数。

    **适用范围（2026-10-07 验收修）**：仅用于已知兼容场景（子孙不自建
    Job）。venv launcher 等自建 Job 的程序会把孙进程放进自己的 Job，
    后补指派 = 跨 Job 层级重归属 → ERROR_ACCESS_DENIED(GetLastError=5)。
    生产执行面已改出生即绑定（open_sandbox_job + CREATE_SUSPENDED +
    bind_spawned_process），本函数不再被生产调用，仅留测试与兼容场景。
    """
    targets = [pid] + _descendants(pid)
    handle = _create_job(plan)
    try:
        for target in targets:
            assign_pid_to_job_handle(handle, target)
    except BaseException:
        _close_handle(handle)
        raise
    return handle


def resume_process_main_thread(pid: int) -> int:
    """恢复 CREATE_SUSPENDED 出生进程的主线程；返回恢复的线程数（新生儿应为 1）。

    为什么不是 CreateProcess 返回的线程句柄：asyncio/subprocess 的 Popen
    在创建后立即关闭主线程句柄，无法直接 ResumeThread——经 Toolhelp 线程
    快照按 owner==pid 重新定位（suspended 新生儿恰有且只有一个线程）。
    """
    snapshot = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPTHREAD, 0)
    if not snapshot or snapshot == ctypes.c_void_p(-1).value:
        raise _win_err(f"CreateToolhelp32Snapshot(线程) 失败（pid={pid}）")
    tids: list[int] = []
    try:
        entry = THREADENTRY32()
        entry.dwSize = ctypes.sizeof(THREADENTRY32)
        ok = kernel32.Thread32First(snapshot, ctypes.byref(entry))
        while ok:
            if entry.th32OwnerProcessID == pid:
                tids.append(int(entry.th32ThreadID))
            ok = kernel32.Thread32Next(snapshot, ctypes.byref(entry))
    finally:
        _close_handle(snapshot)
    if not tids:
        raise SandboxUnavailableError(f"pid={pid} 无线程可恢复（进程可能已退出）")
    resumed = 0
    for tid in tids:
        handle = kernel32.OpenThread(THREAD_SUSPEND_RESUME, False, tid)
        if not handle:
            raise _win_err(f"OpenThread 失败（tid={tid}）")
        try:
            # ResumeThread 失败返回 0xFFFFFFFF（DWORD，Python 真值）——
            # 必须显式比较（2026-10-07 审计修的同一坑，禁止裸真值判定）。
            suspend_count = kernel32.ResumeThread(wintypes.HANDLE(handle))
            if suspend_count == 0xFFFFFFFF:
                raise _win_err(f"ResumeThread 失败（tid={tid}）")
            resumed += 1
        finally:
            _close_handle(handle)
    return resumed


def query_job_limits(job_handle: int) -> tuple[int, int, int]:
    """(limit_flags, active_process_limit, process_memory_limit)——测试复核面。"""
    info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
    ok = kernel32.QueryInformationJobObject(
        wintypes.HANDLE(job_handle),
        JobObjectExtendedLimitInformation,
        ctypes.byref(info),
        ctypes.sizeof(info),
        None,
    )
    if not ok:
        raise _win_err("QueryInformationJobObject 失败")
    return (
        info.BasicLimitInformation.LimitFlags,
        info.BasicLimitInformation.ActiveProcessLimit,
        info.ProcessMemoryLimit,
    )


def unenforced_constraints(policy: SandboxPolicy) -> list[str]:
    """列出 Windows Job-only 形态**无法落实**的策略约束（诚实清单）。

    Job Object 管进程树连坐回收 + 进程数/内存限额；它不管文件路径写域、
    网络、读遮蔽（Codex 的 deny-SID/能力 SID 层留待 v1.4.2 接缝）。调用方
    必须据此 fail_closed 拒绝或响亮降级——绝不返回仿佛全策略已落实的结果。
    """
    missing: list[str] = []
    if policy.mode == "read-only":
        missing.append("mode=read-only（全文件系统禁写）")
    else:
        missing.append("mode=workspace（写域收窄 workspace/extra_write_roots）")
    if policy.network == "none":
        missing.append("network=none（禁网）")
    if policy.deny_read_globs:
        missing.append("deny_read_globs（敏感路径读遮蔽）")
    return missing


def plan_windows_command(
    policy: SandboxPolicy, argv: list[str], cwd: Any
) -> WrappedCommand:
    """v1.4.1 接线形态：argv 原样（PowerShell 包装在 shell.py 完成），
    Job 计划从 policy 生成；禁止 I/O（能力是运行期再证）。

    能力诚实（2026-10-07 审计修）：Job-only 只落实限额 + kill-on-close；
    落空约束按 policy 语义处置——fail_closed 抛 SandboxUnavailableError，
    downgrade 响亮降级（logger.warning + downgraded=True + detail 列明），
    绝不返回仿佛全部策略已落实的 applied=True。"""
    del cwd
    missing = unenforced_constraints(policy)
    if missing and policy.on_missing_capability == "fail_closed":
        raise SandboxUnavailableError(
            "os_sandbox fail_closed：Windows Job-only 后端无法落实 "
            + "、".join(missing)
            + "。放宽约束改用 on_missing_capability=downgrade（显式降级），"
            "或迁往 bwrap/seatbelt 宿主。"
        )
    plan = JobPlan(
        max_memory_bytes=policy.max_memory_mb * 1024 * 1024,
        max_processes=policy.max_processes,
        kill_on_close=True,
    )
    detail = "Windows Job Object（限额 + kill-on-close）"
    if missing:
        detail += "；未落实：" + "、".join(missing)
        _logger.warning(
            "os_sandbox 显式降级：Windows Job-only 后端未落实 %s——本次命令"
            "仅受 Job 限额 + kill-on-close 约束。要拒绝请设 "
            "execution.os_sandbox.on_missing_capability=fail_closed。",
            "、".join(missing),
        )
    return WrappedCommand(
        argv=list(argv),
        job_plan=plan,
        backend="job+token",
        applied=True,
        downgraded=bool(missing),
        detail=detail,
    )


@dataclass
class RestrictedProcess:
    """受限令牌 spawn 的句柄束（调用方持有，负责 wait/close）。"""

    pid: int
    process_handle: int
    thread_handle: int
    job_handle: int = 0
    token_handle: int = 0
    detail: str = ""           # "low-il" | "restricted-only (IL unsupported: ...)"

    def wait(self, timeout_ms: int = 15000) -> int:
        waited = kernel32.WaitForSingleObject(
            wintypes.HANDLE(self.process_handle), timeout_ms)
        if waited != 0:  # WAIT_OBJECT_0
            kernel32.TerminateProcess(wintypes.HANDLE(self.process_handle), 1)
            kernel32.WaitForSingleObject(wintypes.HANDLE(self.process_handle), 3000)
        code = wintypes.DWORD(0)
        kernel32.GetExitCodeProcess(
            wintypes.HANDLE(self.process_handle), ctypes.byref(code))
        return int(code.value)

    def close(self) -> None:
        _close_handle(self.thread_handle)
        _close_handle(self.process_handle)
        if self.job_handle:
            _close_handle(self.job_handle)  # kill-on-close 生效
        if self.token_handle:
            _close_handle(self.token_handle)


def _sid_for(sid_text: str) -> ctypes.c_void_p:
    sid = ctypes.c_void_p()
    if not advapi32.ConvertStringSidToSidW(sid_text, ctypes.byref(sid)):
        raise _win_err(f"ConvertStringSidToSid 失败（{sid_text}）")
    return sid


def _create_low_integrity_restricted_token() -> int:
    current = wintypes.HANDLE()
    access = TOKEN_DUPLICATE | TOKEN_QUERY | TOKEN_ASSIGN_PRIMARY
    if not advapi32.OpenProcessToken(
            kernel32.GetCurrentProcess(), access, ctypes.byref(current)):
        raise _win_err("OpenProcessToken 失败")
    try:
        new_token = wintypes.HANDLE()
        if not advapi32.CreateRestrictedToken(
                current, DISABLE_MAX_PRIVILEGE | LUA_TOKEN,
                0, None, 0, None, 0, None, ctypes.byref(new_token)):
            raise _win_err("CreateRestrictedToken 失败（DISABLE_MAX_PRIVILEGE|LUA）")
        return new_token.value
    finally:
        _close_handle(current.value)


def _new_low_il_attribute_list() -> tuple[ctypes.Array, ctypes.c_void_p]:
    """构造 Low IL 的 STARTUPINFOEX 属性表（SetTokenInformation 需
    SE_TCB_PRIVILEGE、未提权进程不可用——PROC_THREAD_ATTRIBUTE_MANDATORY_LABEL
    是创建期降级完整性级别的免特权路径）。返回 (list_buf, label_sid)；
    list_buf 在进程创建完成前必须存活，随后 DeleteProcThreadAttributeList +
    LocalFree(label_sid)。"""
    size = ctypes.c_size_t(0)
    kernel32.InitializeProcThreadAttributeList(None, 1, 0, ctypes.byref(size))
    buf = ctypes.create_string_buffer(size.value)
    if not kernel32.InitializeProcThreadAttributeList(buf, 1, 0, ctypes.byref(size)):
        raise _win_err("InitializeProcThreadAttributeList 失败")
    label_sid = _sid_for(LOW_INTEGRITY_SID)
    label = TOKEN_MANDATORY_LABEL(Label=label_sid.value, Attributes=SE_GROUP_INTEGRITY)
    if not kernel32.UpdateProcThreadAttribute(
            buf, 0, PROC_THREAD_ATTRIBUTE_MANDATORY_LABEL,
            ctypes.byref(label), ctypes.sizeof(label), None, None):
        kernel32.DeleteProcThreadAttributeList(buf)
        kernel32.LocalFree(label_sid)
        raise _win_err("UpdateProcThreadAttribute 失败（Low IL 属性）")
    return buf, label_sid


def spawn_restricted_sync(
    argv: list[str],
    cwd: str,
    policy: SandboxPolicy,
) -> RestrictedProcess:
    """Codex 路线同步原语：受限令牌 + Low IL + 可挂 Job + ResumeThread。

    返回 ``RestrictedProcess``（调用方持有，wait/close 自查）。
    cmdline 首个拼接带引号；argv[0] 必须是可执行文件全名（cmd.exe 等）。
    """
    if not argv:
        raise ValueError("argv 为空")
    missing = unenforced_constraints(policy)
    if missing and policy.on_missing_capability == "fail_closed":
        raise SandboxUnavailableError(
            "os_sandbox fail_closed：受限令牌原语同样无法落实 "
            + "、".join(missing)
            + "（Low IL 是粗粒度整体性约束，不是按路径的策略域）。"
        )
    token = _create_low_integrity_restricted_token()
    cmdline = " ".join(
        f'"{part}"' if " " in part else part for part in argv
    )
    detail = "low-il"
    flags = CREATE_SUSPENDED | CREATE_UNICODE_ENVIRONMENT
    attr_buf, label_sid = None, None
    info = STARTUPINFOEXW()
    info.StartupInfo.cb = ctypes.sizeof(STARTUPINFOEXW)
    try:
        attr_buf, label_sid = _new_low_il_attribute_list()
        info.lpAttributeList = ctypes.cast(attr_buf, ctypes.c_void_p)
        flags |= EXTENDED_STARTUPINFO_PRESENT
    except SandboxUnavailableError as exc:
        # 低完整性是尽力而为能力：宿主不支持（如服务器 SKU/策略限制）时
        # 显式降级为受限令牌单用并如实记录——绝不静默也绝不硬失败。
        detail = f"restricted-only (IL structure unsupported: {exc})"
        attr_buf, label_sid = None, None
    pi = PROCESS_INFORMATION()
    try:
        created = advapi32.CreateProcessWithTokenW(
            wintypes.HANDLE(token),
            0,
            None,
            cmdline,
            flags,
            None,
            str(cwd),
            ctypes.byref(info),
            ctypes.byref(pi),
        )
        if not created and flags & EXTENDED_STARTUPINFO_PRESENT:
            # 带属性创建被拒（部分宿主不支持 MANDATORY_LABEL 属性）→ 降级重试
            detail = "restricted-only (IL attribute rejected)"
            info = STARTUPINFOEXW()
            info.StartupInfo.cb = ctypes.sizeof(STARTUPINFOEXW)
            flags &= ~EXTENDED_STARTUPINFO_PRESENT
            created = advapi32.CreateProcessWithTokenW(
                wintypes.HANDLE(token),
                0,
                None,
                cmdline,
                flags,
                None,
                str(cwd),
                ctypes.byref(info),
                ctypes.byref(pi),
            )
    finally:
        if attr_buf is not None:
            kernel32.DeleteProcThreadAttributeList(attr_buf)
        if label_sid is not None:
            kernel32.LocalFree(label_sid)
    if not created:
        _close_handle(token)
        raise _win_err("CreateProcessWithTokenW 失败（受限令牌 spawn）")

    job = 0
    try:
        if policy.max_memory_mb > 0 or policy.max_processes > 0:
            job = open_job(JobPlan(
                max_memory_bytes=policy.max_memory_mb * 1024 * 1024,
                max_processes=policy.max_processes,
                kill_on_close=True,
            ))
            assign_pid_to_job_handle(job, pi.dwProcessId)
        # ResumeThread 失败返回 0xFFFFFFFF（DWORD）——Python 里它是真值，
        # 废弃代码（2026-10-06 版）：if not kernel32.ResumeThread(...) 会把
        # 失败当成成功放行。必须与 0xFFFFFFFF 显式比较（MSDN 返值契约）。
        suspend_count = kernel32.ResumeThread(wintypes.HANDLE(pi.hThread))
        if suspend_count == 0xFFFFFFFF:
            raise _win_err("ResumeThread 失败")
        return RestrictedProcess(
            pid=int(pi.dwProcessId),
            process_handle=int(pi.hProcess),
            thread_handle=int(pi.hThread),
            job_handle=job,
            token_handle=token,
            detail=detail,
        )
    except BaseException:
        kernel32.TerminateProcess(wintypes.HANDLE(pi.hProcess), 1)
        kernel32.WaitForSingleObject(wintypes.HANDLE(pi.hProcess), 3000)
        _close_handle(pi.hThread)
        _close_handle(pi.hProcess)
        if job:
            _close_handle(job)
        _close_handle(token)
        raise


def query_token_integrity(pid: int) -> str:
    """读子进程令牌的完整性级别 SID 文本（测试复核面：应恒 Low IL）。"""
    proc = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not proc:
        raise _win_err(f"OpenProcess 失败（pid={pid}）")
    try:
        token = wintypes.HANDLE()
        if not advapi32.OpenProcessToken(
                wintypes.HANDLE(proc), TOKEN_QUERY, ctypes.byref(token)):
            raise _win_err("OpenProcessToken(子进程) 失败")
        try:
            size = wintypes.DWORD(0)
            advapi32.GetTokenInformation(token, TokenIntegrityLevel, None, 0,
                                         ctypes.byref(size))
            buf = ctypes.create_string_buffer(size.value)
            if not advapi32.GetTokenInformation(
                    token, TokenIntegrityLevel, buf, size, ctypes.byref(size)):
                raise _win_err("GetTokenInformation(Integrity) 失败")
            label = ctypes.cast(buf, ctypes.POINTER(TOKEN_MANDATORY_LABEL)).contents
            text = ctypes.c_wchar_p()
            if not advapi32.ConvertSidToStringSidW(
                    label.Label, ctypes.byref(text)):
                raise _win_err("ConvertSidToStringSid 失败")
            return str(text.value or "")
        finally:
            _close_handle(token.value)
    finally:
        _close_handle(proc)


class _SID_AND_ATTRIBUTES(ctypes.Structure):
    _fields_ = [("Sid", ctypes.c_void_p), ("Attributes", wintypes.DWORD)]


def token_group_has(pid: int, sid_text: str) -> bool:
    """子进程令牌组里是否含指定 SID（如 RESTRICTED_GROUP_SID S-1-5-12）——测试复核面。"""
    proc = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not proc:
        raise _win_err(f"OpenProcess 失败（pid={pid}）")
    try:
        token = wintypes.HANDLE()
        if not advapi32.OpenProcessToken(
                wintypes.HANDLE(proc), TOKEN_QUERY, ctypes.byref(token)):
            raise _win_err("OpenProcessToken(子进程) 失败")
        try:
            size = wintypes.DWORD(0)
            token_groups = 2  # TokenGroups
            advapi32.GetTokenInformation(token, token_groups, None, 0,
                                         ctypes.byref(size))
            buf = ctypes.create_string_buffer(size.value)
            if size.value == 0 or not advapi32.GetTokenInformation(
                    token, token_groups, buf, size, ctypes.byref(size)):
                raise _win_err("GetTokenInformation(Groups) 失败")
            count = int.from_bytes(buf.raw[:4], "little")
            entry = _SID_AND_ATTRIBUTES()
            # x64: DWORD GroupCount + 4 padding → 首条 SID_AND_ATTRIBUTES 在偏移 8，
            # 步长 sizeof(_SID_AND_ATTRIBUTES)=16（指针 8 对齐）。步长/基址错一位
            # 就整列解析失败（实测 16 组只解析出 4 条）。
            for index in range(count):
                ctypes.memmove(
                    ctypes.byref(entry),
                    ctypes.addressof(buf.raw) + 8 + index * ctypes.sizeof(entry),
                    ctypes.sizeof(entry),
                )
                text = ctypes.c_wchar_p()
                if advapi32.ConvertSidToStringSidW(
                        entry.Sid, ctypes.byref(text)) and text.value == sid_text:
                    return True
            return False
        finally:
            _close_handle(token.value)
    finally:
        _close_handle(proc)
