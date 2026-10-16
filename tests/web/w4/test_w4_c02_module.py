"""WEB-W4-C02. A Windows desktop screenshot and notepad window are real."""

from __future__ import annotations

import ctypes
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
_RUNNER = REPO / "packages" / "rxycode-runner" / "src"
if str(_RUNNER) not in sys.path:
    sys.path.insert(0, str(_RUNNER))


def test_w4_c02_integration() -> None:
    """Screenshot pixels and a notepad window id come from this desktop."""
    from rxycode_runner.desktop.windows_adapter import capture_screen, close_window, open_app

    shot = capture_screen()
    assert shot.width > 0
    assert shot.height > 0
    assert len(shot.pixels) >= shot.width * shot.height * 3
    assert any(shot.pixels)

    hwnd = open_app("notepad.exe")
    try:
        assert hwnd > 0
        assert ctypes.windll.user32.IsWindow(hwnd)
    finally:
        close_window(hwnd)
