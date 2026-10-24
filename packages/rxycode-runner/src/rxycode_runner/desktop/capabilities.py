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


_RELEASE_PLATFORMS = ("windows", "macos", "linux")


def support_matrix(
    system: str,
    *,
    accessibility: bool = False,
    wayland: bool = False,
) -> dict[str, str]:
    """Platform facts. Unverified desktops are not reported as available."""
    if system in {"Windows", "win32"} and not wayland:
        return {
            "desktop_input": "available",
            "conpty": "available",
            "local_full": "available",
            "click": "available",
        }
    if system in {"Darwin", "macOS"}:
        return {
            "desktop_input": "unsupported",
            "conpty": "unsupported",
            "local_full": "unverified",
            "click": "unsupported",
            "accessibility": "granted" if accessibility else "missing",
        }
    if system == "Linux":
        return {
            "desktop_input": "unsupported",
            "conpty": "unsupported",
            "local_full": "unverified",
            "click": "unsupported",
            "wayland": "yes" if wayland else "no",
        }
    return {
        "desktop_input": "unsupported",
        "conpty": "unsupported",
        "local_full": "unverified",
        "click": "unsupported",
    }


def release_status(verified_platforms: set[str]) -> dict[str, str]:
    """Only platforms with a real run are supported. The others stay unverified."""
    verified = {item.casefold() for item in verified_platforms}
    return {
        name: "supported" if name in verified else "unverified"
        for name in _RELEASE_PLATFORMS
    }


def connect_main() -> None:
    """Installed console entry. It opens the outbound device socket."""
    import argparse
    import asyncio

    from rxycode_runner.remote.client import _one_session, reset_stop

    parser = argparse.ArgumentParser(prog="rxycode-connect")
    parser.add_argument("command", choices=["connect"])
    parser.add_argument("--url", required=True)
    parser.add_argument("--code", default="")
    parser.add_argument("--device-id", required=True)
    parser.add_argument("--os-name", default="Windows")
    parser.add_argument("--capability", action="append", default=[])
    parser.add_argument("--heartbeat-seconds", type=float, default=15.0)
    import sys

    value_options = {
        "--url",
        "--code",
        "--device-id",
        "--os-name",
        "--capability",
        "--heartbeat-seconds",
    }
    known_options = value_options | {"-h", "--help"}
    argv = sys.argv[1:]
    merged: list[str] = []
    index = 0
    while index < len(argv):
        token = argv[index]
        nxt = argv[index + 1] if index + 1 < len(argv) else ""
        if token in value_options and nxt.startswith("-") and nxt not in known_options:
            merged.append(f"{token}={nxt}")
            index += 2
        else:
            merged.append(token)
            index += 1
    args = parser.parse_args(merged)
    reset_stop()
    asyncio.run(
        _one_session(
            url=args.url,
            device_id=args.device_id,
            os_name=args.os_name,
            capabilities=list(args.capability or ["click"]),
            pairing_code=args.code,
            protocol_version="1.1.0",
            heartbeat_seconds=args.heartbeat_seconds,
            state={"token": "", "scope": "device"},
        )
    )
