"""Computer Use enablement. Default off. Env is the operator override."""

from __future__ import annotations

import os
from typing import Any


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _section(config: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(config, dict):
        return {}
    section = config.get("computer_use")
    return section if isinstance(section, dict) else {}


def is_enabled(config: dict[str, Any] | None = None) -> bool:
    """True when the operator turned Computer Use on.

    Default off (ARCH-003 / PP42). ``RXYCODE_COMPUTER_USE=1`` is the
    documented try-path and does not write config.
    """
    env = os.environ.get("RXYCODE_COMPUTER_USE")
    if env is not None and str(env).strip() != "":
        return _truthy(env)
    return _truthy(_section(config).get("enabled"))


def is_approved(config: dict[str, Any] | None = None) -> bool:
    """First-run approval. Env ``RXYCODE_COMPUTER_USE_APPROVED`` or config.

    ``RXYCODE_COMPUTER_USE=1`` also counts as approval so a one-shot try
    path actually binds action tools.
    """
    approved_env = os.environ.get("RXYCODE_COMPUTER_USE_APPROVED")
    if approved_env is not None and str(approved_env).strip() != "":
        return _truthy(approved_env)
    if _truthy(os.environ.get("RXYCODE_COMPUTER_USE")):
        return True
    return _truthy(_section(config).get("approved"))


def browser_enabled(config: dict[str, Any] | None = None) -> bool:
    section = _section(config)
    if "browser" in section:
        return _truthy(section.get("browser"))
    return True


def configured_command(config: dict[str, Any] | None = None) -> tuple[str, list[str]] | None:
    section = _section(config)
    command = section.get("command")
    if not isinstance(command, str) or not command.strip():
        return None
    args = section.get("args")
    if args is None:
        args = ["mcp"]
    if not isinstance(args, list) or not all(isinstance(item, str) for item in args):
        return None
    return command.strip(), list(args)
