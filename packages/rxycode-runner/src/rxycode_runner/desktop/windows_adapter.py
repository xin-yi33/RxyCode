"""Windows screenshot, window id, and DPI click points."""

from __future__ import annotations

import ctypes
import os
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from .capabilities import click_allowed, task_capabilities

_SRCCOPY = 0x00CC0020
_WM_CLOSE = 0x0010
_BROWSERS = {"chrome.exe", "msedge.exe", "firefox.exe", "chrome", "msedge", "firefox"}
_OPENED: dict[int, subprocess.Popen[bytes]] = {}


@dataclass(frozen=True)
class Monitor:
    x: int
    y: int
    width: int
    height: int
    dpi: int


@dataclass(frozen=True)
class ClickResult:
    ok: bool
    code: str


@dataclass(frozen=True)
class Screenshot:
    width: int
    height: int
    pixels: bytes


def physical_point(monitor: Monitor, logical_x: int, logical_y: int) -> tuple[int, int]:
    return (
        monitor.x + logical_x * monitor.dpi // 96,
        monitor.y + logical_y * monitor.dpi // 96,
    )


def click(
    *,
    task_id: str,
    capabilities: frozenset[str],
    monitors: tuple[Monitor, ...],
    monitor_index: int,
    logical_x: int,
    logical_y: int,
    send,
    system: str,
    locked: bool,
    wayland: bool,
) -> ClickResult:
    requested = frozenset(capabilities)
    granted = task_capabilities(task_id)
    if not requested <= granted or not click_allowed(
        system=system,
        locked=locked,
        wayland=wayland,
        capabilities=requested,
    ):
        return ClickResult(ok=False, code="CAPABILITY_UNAVAILABLE")
    point = physical_point(monitors[monitor_index], logical_x, logical_y)
    send(point)
    return ClickResult(ok=True, code="OK")


def capture_screen() -> Screenshot:
    user32, gdi32 = _gdi()
    target = _capture_target(user32)
    if target is None:
        raise OSError("CAPABILITY_UNAVAILABLE")
    hwnd, width, height = target
    source = user32.GetWindowDC(hwnd)
    memory = gdi32.CreateCompatibleDC(source)
    bitmap = gdi32.CreateCompatibleBitmap(source, width, height)
    old = gdi32.SelectObject(memory, bitmap)
    try:
        if not user32.PrintWindow(hwnd, memory, 2):
            raise OSError("PrintWindow failed")
        header = _bitmap_header(width, height)
        buffer = ctypes.create_string_buffer(width * height * 4)
        rows = gdi32.GetDIBits(memory, bitmap, 0, height, buffer, ctypes.byref(header), 0)
        if rows == 0:
            raise OSError("GetDIBits failed")
        return Screenshot(width=width, height=height, pixels=buffer.raw)
    finally:
        gdi32.SelectObject(memory, old)
        gdi32.DeleteObject(bitmap)
        gdi32.DeleteDC(memory)
        user32.ReleaseDC(hwnd, source)


def open_app(executable: str) -> int:
    name = Path(executable).name.casefold()
    if name in _BROWSERS:
        raise PermissionError("CAPABILITY_UNAVAILABLE")
    proc = subprocess.Popen([_windows_executable(executable)])
    for _ in range(50):
        hwnd = _visible_window(proc.pid)
        if hwnd:
            _OPENED[hwnd] = proc
            return hwnd
        if proc.poll() is not None:
            break
        time.sleep(0.1)
    proc.terminate()
    raise OSError(f"no window appeared for {executable}")


def _windows_executable(executable: str) -> str:
    if Path(executable).name.casefold() != "notepad.exe":
        return executable
    root = os.environ.get("SystemRoot", r"C:\Windows")
    candidate = Path(root) / "System32" / "notepad.exe"
    if candidate.is_file():
        return str(candidate)
    return executable


def close_window(hwnd: int) -> None:
    ctypes.windll.user32.PostMessageW(hwnd, _WM_CLOSE, 0, 0)
    proc = _OPENED.pop(hwnd, None)
    if proc is None:
        return
    try:
        proc.wait(timeout=2)
    except subprocess.TimeoutExpired:
        proc.terminate()


def _visible_window(pid: int) -> int:
    user32 = ctypes.windll.user32
    found: list[int] = []

    def visit(hwnd, _lparam) -> bool:
        owner = ctypes.c_ulong()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if int(owner.value) == pid and user32.IsWindowVisible(hwnd):
            found.append(int(hwnd))
            return False
        return True

    callback = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)(visit)
    user32.EnumWindows(callback, 0)
    return found[0] if found else 0


class _BitmapHeader(ctypes.Structure):
    _fields_ = [
        ("biSize", ctypes.c_uint32),
        ("biWidth", ctypes.c_int32),
        ("biHeight", ctypes.c_int32),
        ("biPlanes", ctypes.c_uint16),
        ("biBitCount", ctypes.c_uint16),
        ("biCompression", ctypes.c_uint32),
        ("biSizeImage", ctypes.c_uint32),
        ("biXPelsPerMeter", ctypes.c_int32),
        ("biYPelsPerMeter", ctypes.c_int32),
        ("biClrUsed", ctypes.c_uint32),
        ("biClrImportant", ctypes.c_uint32),
    ]


def _gdi():
    user32 = ctypes.windll.user32
    gdi32 = ctypes.windll.gdi32
    void = ctypes.c_void_p
    user32.GetDC.restype = void
    user32.GetDC.argtypes = [void]
    user32.ReleaseDC.argtypes = [void, void]
    gdi32.CreateCompatibleDC.restype = void
    gdi32.CreateCompatibleDC.argtypes = [void]
    gdi32.CreateCompatibleBitmap.restype = void
    gdi32.CreateCompatibleBitmap.argtypes = [void, ctypes.c_int, ctypes.c_int]
    gdi32.SelectObject.restype = void
    gdi32.SelectObject.argtypes = [void, void]
    gdi32.DeleteObject.argtypes = [void]
    gdi32.DeleteDC.argtypes = [void]
    gdi32.BitBlt.restype = ctypes.c_int
    gdi32.BitBlt.argtypes = [
        void, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
        void, ctypes.c_int, ctypes.c_int, ctypes.c_uint32,
    ]
    gdi32.GetDIBits.restype = ctypes.c_int
    gdi32.GetDIBits.argtypes = [
        void, void, ctypes.c_uint, ctypes.c_uint, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint,
    ]
    hwnd = ctypes.c_void_p
    user32.GetWindowDC.argtypes = [hwnd]
    user32.GetWindowDC.restype = void
    user32.ReleaseDC.argtypes = [hwnd, void]
    user32.PrintWindow.argtypes = [hwnd, void, ctypes.c_uint]
    user32.PrintWindow.restype = ctypes.c_int
    user32.IsWindowVisible.argtypes = [hwnd]
    user32.GetWindowRect.argtypes = [hwnd, ctypes.c_void_p]
    return user32, gdi32


class _Rect(ctypes.Structure):
    _fields_ = [
        ("left", ctypes.c_long),
        ("top", ctypes.c_long),
        ("right", ctypes.c_long),
        ("bottom", ctypes.c_long),
    ]


def _capture_target(user32):
    chosen: list[tuple[int, int, int]] = []

    def visit(hwnd, _lparam) -> bool:
        if not user32.IsWindowVisible(hwnd):
            return True
        rect = _Rect()
        user32.GetWindowRect(hwnd, ctypes.byref(rect))
        width = int(rect.right - rect.left)
        height = int(rect.bottom - rect.top)
        if width >= 32 and height >= 32:
            chosen.append((int(hwnd), min(width, 640), min(height, 480)))
            return False
        return True

    callback = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)(visit)
    user32.EnumWindows(callback, 0)
    return chosen[0] if chosen else None


def _bitmap_header(width: int, height: int) -> _BitmapHeader:
    header = _BitmapHeader()
    header.biSize = ctypes.sizeof(_BitmapHeader)
    header.biWidth = width
    header.biHeight = -height
    header.biPlanes = 1
    header.biBitCount = 32
    header.biCompression = 0
    return header
