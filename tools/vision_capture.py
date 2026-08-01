"""Standalone screen-capture worker for the vision tool.

Runs as a subprocess (``python -m tools.vision_capture <output_dir>``) so a
blocked native capture (locked session, RDP disconnect, no interactive
desktop) can be killed by the parent process instead of hanging the agent.

This module intentionally imports nothing from the project: the worker must
start instantly and never drag the parent's runtime into the capture path.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def _new_mss():
    """Return an mss screen-capture instance.

    ``mss.mss()`` is deprecated in recent mss releases; prefer ``mss.MSS``
    when available and fall back otherwise.
    """
    import mss

    if hasattr(mss, "MSS"):
        return mss.MSS()
    return mss.mss()


def main() -> int:
    if len(sys.argv) < 2:
        print("error: usage: python -m tools.vision_capture <output_dir>",
              file=sys.stderr)
        return 2

    output_dir = Path(sys.argv[1])
    output_dir.mkdir(parents=True, exist_ok=True)

    with _new_mss() as sct:
        monitors = sct.monitors
        screenshots: list[str] = []

        # Capture all monitors (skip monitor 0, the all-in-one virtual one).
        for idx, _monitor in enumerate(monitors[1:], 1):
            filename = f"screenshot_monitor_{idx}.png"
            filepath = output_dir / filename
            sct.shot(mon=idx, output=str(filepath))

            from PIL import Image

            with Image.open(filepath) as img:
                w, h = img.size
            size_kb = os.path.getsize(filepath) / 1024
            screenshots.append(
                f"  Monitor {idx}: {w}x{h}px, {size_kb:.0f}KB -> {filepath}"
            )

    result = [f"Captured {len(screenshots)} screenshot(s):"]
    result.extend(screenshots)
    result.append(f"\nSaved to: {output_dir}")
    print("\n".join(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
