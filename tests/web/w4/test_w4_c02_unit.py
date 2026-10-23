"""WEB-W4-C02. DPI coordinates are converted, and a missing capability does not click."""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
_RUNNER = REPO / "packages" / "rxycode-runner" / "src"
if str(_RUNNER) not in sys.path:
    sys.path.insert(0, str(_RUNNER))


def test_w4_c02_contract() -> None:
    """A logical point on the second monitor becomes the physical click point."""
    from rxycode_runner.desktop.capabilities import bind_task_capabilities
    from rxycode_runner.desktop.windows_adapter import Monitor, click

    bind_task_capabilities("task-c02", frozenset({"click"}))
    monitors = (
        Monitor(x=0, y=0, width=1920, height=1080, dpi=96),
        Monitor(x=1920, y=0, width=2560, height=1440, dpi=144),
    )
    sent: list[tuple[int, int]] = []
    result = click(
        task_id="task-c02",
        capabilities=frozenset({"click"}),
        monitors=monitors,
        monitor_index=1,
        logical_x=100,
        logical_y=200,
        send=sent.append,
        system="Windows",
        locked=False,
        wayland=False,
    )
    assert result.ok is True
    assert sent == [(2070, 300)]


def test_w4_c02_negative() -> None:
    """Lock screen and Wayland refuse the click and do not call another tool."""
    from rxycode_runner.desktop.capabilities import bind_task_capabilities
    from rxycode_runner.desktop.windows_adapter import Monitor, click

    bind_task_capabilities("task-c02", frozenset({"click"}))
    bind_task_capabilities("other-task", frozenset({"click"}))
    monitors = (Monitor(x=0, y=0, width=1920, height=1080, dpi=96),)
    sent: list[tuple[int, int]] = []
    locked = click(
        task_id="task-c02",
        capabilities=frozenset({"click"}),
        monitors=monitors,
        monitor_index=0,
        logical_x=10,
        logical_y=10,
        send=sent.append,
        system="Windows",
        locked=True,
        wayland=False,
    )
    wayland = click(
        task_id="task-c02",
        capabilities=frozenset({"click"}),
        monitors=monitors,
        monitor_index=0,
        logical_x=10,
        logical_y=10,
        send=sent.append,
        system="Linux",
        locked=False,
        wayland=True,
    )
    unbound = click(
        task_id="task-c02",
        capabilities=frozenset(),
        monitors=monitors,
        monitor_index=0,
        logical_x=10,
        logical_y=10,
        send=sent.append,
        system="Windows",
        locked=False,
        wayland=False,
    )
    forged = click(
        task_id="task-not-granted",
        capabilities=frozenset({"click"}),
        monitors=monitors,
        monitor_index=0,
        logical_x=10,
        logical_y=10,
        send=sent.append,
        system="Windows",
        locked=False,
        wayland=False,
    )
    assert locked.code == "CAPABILITY_UNAVAILABLE"
    assert wayland.code == "CAPABILITY_UNAVAILABLE"
    assert unbound.code == "CAPABILITY_UNAVAILABLE"
    assert forged.code == "CAPABILITY_UNAVAILABLE"
    assert sent == []
