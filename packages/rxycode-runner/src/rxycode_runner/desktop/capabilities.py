"""Desktop capability facts. Non-Windows platforms stay unavailable."""

from __future__ import annotations

_TASK_CAPABILITIES: dict[str, frozenset[str]] = {}


def bind_task_capabilities(task_id: str, capabilities: frozenset[str]) -> None:
    """Record the capabilities that belong to this task. A later click cannot borrow another task's grant."""
    if not task_id:
        raise ValueError("task_id required")
    _TASK_CAPABILITIES[task_id] = frozenset(capabilities)


def task_capabilities(task_id: str) -> frozenset[str]:
    return _TASK_CAPABILITIES.get(task_id, frozenset())


def click_allowed(
    *,
    system: str,
    locked: bool,
    wayland: bool,
    capabilities: frozenset[str],
) -> bool:
    if "click" not in capabilities:
        return False
    if locked or wayland:
        return False
    return system in {"Windows", "win32"}


def describe_platform(
    system: str,
    *,
    locked: bool = False,
    wayland: bool = False,
) -> dict[str, str]:
    if system in {"Windows", "win32"} and not locked:
        return {
            "screenshot": "available",
            "sendinput": "available",
            "window": "available",
            "click": "available",
        }
    return {
        "screenshot": "unavailable",
        "sendinput": "unavailable",
        "window": "unavailable",
        "click": "CAPABILITY_UNAVAILABLE",
    }
