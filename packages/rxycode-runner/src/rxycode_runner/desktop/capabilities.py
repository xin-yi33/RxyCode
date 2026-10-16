"""Desktop capability facts. Non-Windows platforms stay unavailable."""

from __future__ import annotations


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
