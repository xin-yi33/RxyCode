"""Safety policy: risk levels, tool classification, write-path whitelist
and dry-run detection.

Adapted from OpenHands (MIT) openhands/security/ — the three-tier
SecurityRisk model (LOW/MEDIUM/HIGH mapped to READ/WRITE/DANGER) and the
confirmation-policy concept. Only the design is ported; no code is
vendored.
"""

from __future__ import annotations

import os
import re
from enum import IntEnum
from pathlib import Path
from typing import Any


class RiskLevel(IntEnum):
    """Three-tier tool risk model (OpenHands SecurityRisk LOW/MEDIUM/HIGH)."""

    READ = 0    # OpenHands LOW — inspection only, no side effects
    WRITE = 1   # OpenHands MEDIUM — modifies files / runs commands
    DANGER = 2  # OpenHands HIGH — potentially destructive / irreversible


#: Static risk table for built-in tools. Missing entries default to WRITE
#: (fail-safe: unknown tools are treated as side-effecting).
TOOL_RISK_TABLE: dict[str, RiskLevel] = {
    # READ — pure inspection
    "read": RiskLevel.READ,
    "view": RiskLevel.READ,
    "grep": RiskLevel.READ,
    "glob": RiskLevel.READ,
    "ls": RiskLevel.READ,
    "webfetch": RiskLevel.READ,
    "websearch": RiskLevel.READ,
    "datetime": RiskLevel.READ,
    "history": RiskLevel.READ,
    "diagnostics": RiskLevel.READ,
    "vision": RiskLevel.READ,
    "question": RiskLevel.READ,
    "skill": RiskLevel.READ,
    # WRITE — side effects, reversible
    "write": RiskLevel.WRITE,
    "edit": RiskLevel.WRITE,
    "patch": RiskLevel.WRITE,
    "open_file": RiskLevel.WRITE,
    "bash": RiskLevel.WRITE,  # escalated to DANGER dynamically by classify_bash_command
    "format": RiskLevel.WRITE,
    "change_directory": RiskLevel.WRITE,
    # Installing external instructions or executable server definitions is
    # high risk even when the operation only writes configuration files.
    "download_skill": RiskLevel.DANGER,
    "download_mcp": RiskLevel.DANGER,
    "download_file": RiskLevel.WRITE,
    "file_download": RiskLevel.WRITE,
    # Stateful multi-operation tools default to a mutating classification.
    # ``classify_tool_risk`` only downgrades explicitly read-only operations.
    "memory": RiskLevel.WRITE,
    "task": RiskLevel.WRITE,
    # DANGER — installs packages / touches git remotes & history
    "installer": RiskLevel.DANGER,
    "git": RiskLevel.DANGER,
    "workflow": RiskLevel.DANGER,
}


def register_tool_risk(name: str, level: RiskLevel) -> None:
    """Register/override the static risk level for a tool name."""
    TOOL_RISK_TABLE[name] = level


def get_tool_risk(name: str) -> RiskLevel:
    """Return the static risk level for a tool; unknown tools default WRITE."""
    return TOOL_RISK_TABLE.get(name, RiskLevel.WRITE)


#: Dangerous shell command patterns (case-insensitive regex). Keep this an
#: easily-extensible plain list — add new entries at the end.
#: Adapted from OpenHands (MIT) openhands/security/ dangerous-command
#: heuristics, extended with Windows patterns (reg delete / format).
DANGEROUS_COMMAND_PATTERNS: list[str] = [
    r"\brm\s+(-[a-zA-Z]*r[a-zA-Z]*f|-[a-zA-Z]*f[a-zA-Z]*r)\s+(/\*|/|~)(?=\s|$)",  # rm -rf / | /* | ~
    r"\bsudo\s+rm\s+-[a-zA-Z]*r",                                          # sudo rm -r...
    r"\bmkfs(\.\w+)?\s",                                                   # mkfs / mkfs.ext4
    r"\bdd\s+.*\bof=/dev/",                                                # dd of=/dev/sda
    r"\bcurl\b[^|]*\|\s*(sudo\s+)?(ba)?sh\b",                              # curl ... | sh
    r"\bwget\b[^|]*\|\s*(sudo\s+)?(ba)?sh\b",                              # wget ... | sh
    r"\bgit\s+push\b.*\s(--force|-f)\b",                                   # git push --force / -f
    r"\bchmod\s+(-[a-zA-Z]*R[a-zA-Z]*\s+)?777\s+/\s*$",                    # chmod -R 777 /
    r">\s*/dev/sd[a-z]",                                                   # > /dev/sda
    r"\bshutdown\b",                                                       # shutdown ...
    r"\breboot\b",                                                         # reboot
    r"\breg\s+delete\b",                                                   # reg delete (Windows)
    r"\bformat\s+[a-zA-Z]:",                                               # format C: (Windows)
]

_COMPILED_PATTERNS = [re.compile(p, re.IGNORECASE) for p in DANGEROUS_COMMAND_PATTERNS]


def classify_bash_command(cmd: str) -> RiskLevel:
    """Dynamically classify a shell command. Any dangerous-pattern hit
    escalates to DANGER; otherwise shell execution is WRITE level."""
    if not cmd:
        return RiskLevel.WRITE
    for pat in _COMPILED_PATTERNS:
        if pat.search(cmd):
            return RiskLevel.DANGER
    return RiskLevel.WRITE


def classify_tool_risk(name: str, args: Any = None) -> RiskLevel:
    """Classify one invocation using both its tool name and arguments.

    Multi-operation tools fail closed: only known read-only operations are
    downgraded. Missing or future operations retain the conservative static
    WRITE/DANGER classification.
    """
    operation = ""
    if isinstance(args, dict):
        operation = str(args.get("operation", "")).strip().lower()

    if name == "memory" and operation in {"search", "list"}:
        return RiskLevel.READ
    if name == "download_skill":
        return RiskLevel.DANGER
    if name == "download_mcp":
        return RiskLevel.DANGER
    if name == "task" and operation in {"list", "get"}:
        return RiskLevel.READ
    if name == "workflow":
        if operation in {"status", "wait"}:
            return RiskLevel.READ
        if operation == "cancel":
            return RiskLevel.WRITE
        return RiskLevel.DANGER

    risk = get_tool_risk(name)
    if name == "bash" and isinstance(args, dict):
        return max(risk, classify_bash_command(str(args.get("command", ""))))
    return risk


def _resolve(path: str) -> Path:
    from ..session_runtime import resolve_session_path

    return resolve_session_path(path)



def _is_within(target: Path, base: Path) -> bool:
    """Prefix check on resolved paths (guards against ../ escapes and
    sibling-prefix confusion like /tmp/work2 vs /tmp/work)."""
    try:
        target.relative_to(base)
        return True
    except ValueError:
        return False


def is_write_allowed(path: str, config: dict) -> bool:
    """Whitelist check for write targets. Allowed roots:
    - the current working directory
    - the RxyCode output dir (~/.rxycode/output/ or RXYCODE_OUTPUT_DIR)
    - every entry of config ``safety.allowed_write_paths``
    """
    try:
        target = _resolve(path)
    except Exception:
        return False

    from ..session_runtime import current_working_directory

    roots: list[Path] = [current_working_directory().resolve()]
    try:
        # Import from the concrete package module, not sys.modules lookup,
        # so tests that stub config.settings in sys.modules don't break us.
        import importlib
        _settings = importlib.import_module("RxyCode.RxyCode1_1_0.config.settings")
        _get_output_dir = getattr(_settings, "get_output_dir", None)
        if _get_output_dir is None:
            raise AttributeError("get_output_dir missing")
        dated_output = _get_output_dir().resolve()
        roots.extend((dated_output, dated_output.parent))
    except Exception:
        pass

    safety = (config or {}).get("safety", {}) or {}
    for extra in safety.get("allowed_write_paths", []) or []:
        try:
            roots.append(_resolve(extra))
        except Exception:
            continue

    return any(_is_within(target, root) for root in roots)


def is_dry_run(config: dict) -> bool:
    """Dry-run is on when config ``safety.dry_run`` is true or the
    RXYCODE_DRY_RUN env var holds a truthy value."""
    env = os.environ.get("RXYCODE_DRY_RUN", "")
    if env.strip().lower() in ("1", "true", "yes", "on"):
        return True
    safety = (config or {}).get("safety", {}) or {}
    return bool(safety.get("dry_run", False))


def summarize_args(args: Any, max_chars: int = 200) -> Any:
    """Produce a compact, truncated representation of tool args for
    approval prompts and audit logs."""
    if isinstance(args, dict):
        out = {}
        for k, v in args.items():
            s = v if isinstance(v, str) else repr(v)
            if len(s) > max_chars:
                s = s[:max_chars] + "..."
            out[k] = s
        return out
    s = args if isinstance(args, str) else repr(args)
    return s[:max_chars] + "..." if len(s) > max_chars else s
