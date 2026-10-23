"""WEB-W4-C07. macOS without Accessibility does not advertise desktop input."""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
SRC = REPO / "packages" / "rxycode-runner" / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def test_w4_c07_integration() -> None:
    """Darwin without an Accessibility grant is not desktop-input available."""
    from rxycode_runner.desktop.capabilities import support_matrix

    matrix = support_matrix("Darwin", accessibility=False, wayland=False)
    assert matrix["desktop_input"] != "available"
    assert matrix["desktop_input"] == "unsupported"
    assert matrix["click"] != "available"
    granted = support_matrix("Darwin", accessibility=True, wayland=False)
    assert granted["desktop_input"] != "available"
    assert granted["click"] != "available"
    assert granted["accessibility"] == "granted"
    wayland = support_matrix("Linux", accessibility=False, wayland=True)
    assert wayland["desktop_input"] == "unsupported"
    windows = support_matrix("Windows", accessibility=False, wayland=False)
    assert windows["desktop_input"] == "available"
    assert windows["conpty"] == "available"
    assert windows["local_full"] == "available"
