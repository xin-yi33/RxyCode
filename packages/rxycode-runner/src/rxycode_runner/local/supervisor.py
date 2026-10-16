"""Track a local process tree so an emergency stop can end it. Not a sandbox."""

from __future__ import annotations

import ctypes
import subprocess
from dataclasses import dataclass
from pathlib import Path

_CREATE_SUSPENDED = 0x00000004
_JOB_OBJECT_EXTENDED_LIMIT = 9
_KILL_ON_JOB_CLOSE = 0x2000


class _StartupInfo(ctypes.Structure):
    _fields_ = [
        ("cb", ctypes.c_uint),
        ("lpReserved", ctypes.c_wchar_p),
        ("lpDesktop", ctypes.c_wchar_p),
        ("lpTitle", ctypes.c_wchar_p),
        ("dwX", ctypes.c_uint),
        ("dwY", ctypes.c_uint),
        ("dwXSize", ctypes.c_uint),
        ("dwYSize", ctypes.c_uint),
        ("dwXCountChars", ctypes.c_uint),
        ("dwYCountChars", ctypes.c_uint),
        ("dwFillAttribute", ctypes.c_uint),
        ("dwFlags", ctypes.c_uint),
        ("wShowWindow", ctypes.c_ushort),
        ("cbReserved2", ctypes.c_ushort),
        ("lpReserved2", ctypes.c_void_p),
        ("hStdInput", ctypes.c_void_p),
        ("hStdOutput", ctypes.c_void_p),
        ("hStdError", ctypes.c_void_p),
    ]


class _ProcessInfo(ctypes.Structure):
    _fields_ = [
        ("hProcess", ctypes.c_void_p),
        ("hThread", ctypes.c_void_p),
        ("dwProcessId", ctypes.c_uint),
        ("dwThreadId", ctypes.c_uint),
    ]


class _BasicLimits(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_longlong),
        ("PerJobUserTimeLimit", ctypes.c_longlong),
        ("LimitFlags", ctypes.c_uint),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", ctypes.c_uint),
        ("Affinity", ctypes.c_size_t),
        ("PriorityClass", ctypes.c_uint),
        ("SchedulingClass", ctypes.c_uint),
    ]


class _IoCounters(ctypes.Structure):
    _fields_ = [(f"c{i}", ctypes.c_ulonglong) for i in range(6)]


class _ExtendedLimits(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", _BasicLimits),
        ("IoInfo", _IoCounters),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


@dataclass
class SpawnResult:
    started: bool
    pid: int | None = None


def _kernel32() -> ctypes.WinDLL:
    library = ctypes.WinDLL("kernel32", use_last_error=True)
    library.CreateProcessW.argtypes = [
        ctypes.c_wchar_p,
        ctypes.c_wchar_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_int,
        ctypes.c_uint,
        ctypes.c_void_p,
        ctypes.c_wchar_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
    ]
    library.CreateProcessW.restype = ctypes.c_int
    library.CreateJobObjectW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p]
    library.CreateJobObjectW.restype = ctypes.c_void_p
    library.SetInformationJobObject.argtypes = [
        ctypes.c_void_p,
        ctypes.c_int,
        ctypes.c_void_p,
        ctypes.c_uint,
    ]
    library.SetInformationJobObject.restype = ctypes.c_int
    library.AssignProcessToJobObject.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    library.AssignProcessToJobObject.restype = ctypes.c_int
    library.TerminateJobObject.argtypes = [ctypes.c_void_p, ctypes.c_uint]
    library.TerminateJobObject.restype = ctypes.c_int
    library.ResumeThread.argtypes = [ctypes.c_void_p]
    library.ResumeThread.restype = ctypes.c_ulong
    library.CloseHandle.argtypes = [ctypes.c_void_p]
    library.CloseHandle.restype = ctypes.c_int
    library.TerminateProcess.argtypes = [ctypes.c_void_p, ctypes.c_uint]
    library.TerminateProcess.restype = ctypes.c_int
    return library


class ProcessSupervisor:
    """One job per spawn. TerminateJobObject ends the parent and its children."""

    def __init__(self) -> None:
        self._stopped = False
        self._jobs: list[int] = []

    def spawn(self, argv: list[str], cwd: Path) -> SpawnResult:
        if self._stopped:
            return SpawnResult(started=False)
        kernel = _kernel32()
        startup = _StartupInfo()
        startup.cb = ctypes.sizeof(startup)
        info = _ProcessInfo()
        command = subprocess.list2cmdline(argv)
        created = kernel.CreateProcessW(
            None,
            command,
            None,
            None,
            0,
            _CREATE_SUSPENDED,
            None,
            str(cwd),
            ctypes.byref(startup),
            ctypes.byref(info),
        )
        if not created:
            raise OSError(ctypes.get_last_error())
        job = kernel.CreateJobObjectW(None, None)
        if not job:
            kernel.TerminateProcess(info.hProcess, 1)
            kernel.CloseHandle(info.hThread)
            kernel.CloseHandle(info.hProcess)
            raise OSError(ctypes.get_last_error())
        limits = _ExtendedLimits()
        limits.BasicLimitInformation.LimitFlags = _KILL_ON_JOB_CLOSE
        kernel.SetInformationJobObject(
            job,
            _JOB_OBJECT_EXTENDED_LIMIT,
            ctypes.byref(limits),
            ctypes.sizeof(limits),
        )
        if not kernel.AssignProcessToJobObject(job, info.hProcess):
            kernel.CloseHandle(job)
            kernel.ResumeThread(info.hThread)
            raise OSError(ctypes.get_last_error())
        kernel.ResumeThread(info.hThread)
        kernel.CloseHandle(info.hThread)
        self._jobs.append(job)
        return SpawnResult(started=True, pid=int(info.dwProcessId))

    def kill_tree(self) -> None:
        self._stopped = True
        kernel = _kernel32()
        for job in self._jobs:
            kernel.TerminateJobObject(job, 1)
            kernel.CloseHandle(job)
        self._jobs.clear()
