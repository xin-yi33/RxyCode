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
    # PowerShell recursive/force deletes — often used for destructive probes
    r"\bRemove-Item\b[^\n]*(-(Recurse|Force)\b)[^\n]*(-(Recurse|Force)\b)",
    r"\bri\b[^\n]*(-(Recurse|Force)\b)[^\n]*(-(Recurse|Force)\b)",
]

_COMPILED_PATTERNS = [re.compile(p, re.IGNORECASE) for p in DANGEROUS_COMMAND_PATTERNS]

# A deliberately small allow-list for shell probes that have no filesystem,
# process, package, network, or repository side effect.  Bash itself remains
# WRITE by default; only a command made entirely from these segments can be
# downgraded to READ.  Keeping this list narrow is important because an
# arbitrary shell command must never become auto-approved merely because it
# happens to contain a read-looking verb.
_READ_ONLY_BASH_SEGMENTS = [
    re.compile(r"^(?:pwd|Get-Location)\s*$", re.IGNORECASE),
    re.compile(
        r"^(?:ls|ls\.exe|dir|Get-ChildItem)(?:\s+-[\w-]+)*"
        r"(?:\s+(?:['\"][^'\"<>|]+['\"]|[A-Za-z0-9_.:/\\~-]+))?\s*$",
        re.IGNORECASE,
    ),
    re.compile(r"^(?:echo|Write-Output)(?:\s+[^<>|]+)?$", re.IGNORECASE),
    re.compile(r'^"[^"<>|]+"$'),
    re.compile(r"^(?:where|where\.exe)\s+[A-Za-z0-9_.-]+\s*$", re.IGNORECASE),
    re.compile(
        r"^(?:node|python3?|py|java|javac|npm)(?:\.exe|\.cmd)?\s+"
        r"(?:--version|-version|-V)\s*$",
        re.IGNORECASE,
    ),
    re.compile(
        r"^pip(?:3)?(?:\.exe)?\s+show(?:\s+[A-Za-z0-9_.\-]+)+\s*$",
        re.IGNORECASE,
    ),
    re.compile(
        r"^grep(?:\.[A-Za-z]+)?(?:\s+-\w+)*\s+(?:-E\s+)?['\"][^'\"]+['\"]\s*$",
        re.IGNORECASE,
    ),
    re.compile(
        r"^node(?:\.exe|\.cmd)?\s+--check\s+[A-Za-z0-9_./\\-]+\.(?:js|mjs|cjs)\s*$",
        re.IGNORECASE,
    ),
    re.compile(
        r"^git\s+(?:status(?:\s+--[\w-]+)*|log(?:\s+[^<>|]+)?)\s*$",
        re.IGNORECASE,
    ),
    re.compile(r"^(?:cmd(?:\.exe)?\s+/c\s+)?ver\s*$", re.IGNORECASE),
]

# Stderr-only redirects are not filesystem writes. Agents routinely append
# ``2>&1`` to version probes; treating ``>`` as a write would force those
# probes through WRITE approval and then fail the whole task when a missing
# Windows alias such as ``python3`` returns exit 1.
_STDERR_ONLY_REDIRECT_RE = re.compile(
    r"(?:2>&1|2>\s*/dev/null|2>\s*nul|2>\s*\$null)\s*",
    re.IGNORECASE,
)


def _is_read_only_bash_probe(command: str) -> bool:
    """Return true only for a complete, known-safe environment probe.

    Splitting on shell control/pipeline separators is intentionally simple and
    conservative.  Any segment not in the explicit allow-list keeps the
    command at WRITE, while dangerous-pattern matching still runs first.
    """
    if not command:
        return False
    normalized = _STDERR_ONLY_REDIRECT_RE.sub(" ", command)
    if any(token in normalized for token in (">", "<", "`", "$(", "${")):
        return False
    # ``pip show … | grep -E "^(Name|Version)"`` is an env probe. The grep
    # pattern contains ``|``, which would otherwise split the quoted string
    # and keep the command at WRITE.
    if re.search(r"\bpip(?:3)?(?:\.exe)?\s+show\b", normalized, re.I) and not re.search(
        r"\b(?:pip\s+install|npm\s+install|python3?\s+\S+\.py|Set-Content|Out-File|rm\s+)\b",
        normalized,
        re.I,
    ):
        return True
    segments = re.split(r"(?:&&|\|\||[;&|])", normalized)
    return bool(segments) and all(
        any(pattern.fullmatch(segment.strip()) for pattern in _READ_ONLY_BASH_SEGMENTS)
        for segment in segments
        if segment.strip()
    )


def classify_bash_command(cmd: str) -> RiskLevel:
    """Dynamically classify a shell command.

    Destructive patterns escalate to DANGER.  A narrow set of complete,
    read-only environment probes is READ so normal startup inspection does not
    block the user on an approval dialog.  Unknown shell remains WRITE.
    """
    if not cmd:
        return RiskLevel.WRITE
    for pat in _COMPILED_PATTERNS:
        if pat.search(cmd):
            return RiskLevel.DANGER
    if _is_read_only_bash_probe(cmd):
        return RiskLevel.READ
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
        command_risk = classify_bash_command(str(args.get("command", "")))
        # Bash is statically WRITE, but a complete, allow-listed probe is
        # explicitly READ.  Unknown commands retain the static fail-closed
        # WRITE level; dangerous patterns still escalate to DANGER.
        if command_risk is RiskLevel.READ:
            return RiskLevel.READ
        return max(risk, command_risk)
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
    from ..session_runtime import current_working_directory

    safety = (config or {}).get("safety", {}) or {}
    allowed_extra = safety.get("allowed_write_paths", []) or []

    # Windows drive paths (``C:\\...`` / ``C:/...``) are absolute on Windows but
    # NOT on POSIX: Path("C:\\x").is_absolute() is False on Linux, so
    # resolve_session_path would wrongly treat them as relative to the cwd and
    # report them as "inside the workspace". On non-Windows hosts, treat any
    # drive-prefixed path as an escape unless it is explicitly whitelisted
    # (safety fix S12, Luna rev). On Windows this is already handled by
    # Path.is_absolute(), so only apply when the platform does not see it as
    # absolute.
    drive_path = re.match(r"(?i)^[a-z]:[\\/]", path)
    if drive_path and not Path(path).is_absolute():
        for extra in allowed_extra:
            try:
                if _resolve(extra) == _resolve(path):
                    return True
            except Exception:
                continue
        return False

    try:
        target = _resolve(path)
    except Exception:
        return False

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

    for extra in allowed_extra:
        try:
            roots.append(_resolve(extra))
        except Exception:
            continue

    execution = (config or {}).get("execution", {}) or {}
    root_value = execution.get("workspace_root")
    if root_value:
        try:
            roots.append(_resolve(str(root_value)))
        except Exception:
            pass

    return any(_is_within(target, root) for root in roots)


# Absolute path literals that often appear in shell write/delete probes.
_ABS_PATH_RE = re.compile(
    r"(?P<path>"
    r"[A-Za-z]:[\\/][^\s'\"|;>&]+"  # Windows drive path
    r"|/(?:Users|home|tmp|var|etc|root)[^\s'\"|;>&]*"  # common Unix abs roots
    r")"
)
# Mutating verbs / redirects whose *target path* must stay inside the whitelist.
# Paths that only appear inside -Value / here-string report bodies are ignored
# by scanning verb-local windows instead of the whole command.
_BASH_MUTATING_TARGET_RE = re.compile(
    r"(?ix)"
    r"(?:"
    r"(?:Remove-Item|ri|Set-Content|Add-Content|Out-File|New-Item|Copy-Item|Move-Item|"
    r"del|erase|rmdir|rd|rm|mv|cp|tee|touch|install)"
    r"[^\n;|&]{0,200}?"
    r"(?:-(?:Literal)?Path\s+|-(?:File)?Path\s+|)"
    r"['\"]?(?P<path>[A-Za-z]:[\\/][^\s'\"|;>&]+|/(?:Users|home|tmp|var|etc|root)[^\s'\"|;>&]*)"
    r"|"
    r"(?:^|[^>])>{1,2}\s*['\"]?(?P<redir>[A-Za-z]:[\\/][^\s'\"|;>&]+|/(?:Users|home|tmp|var|etc|root)[^\s'\"|;>&]*)"
    r")"
)


def find_bash_disallowed_write_paths(cmd: str, config: dict) -> list[str]:
    """Return absolute mutating target paths outside the write whitelist.

    Workspace sandbox only constrains cwd; without this check, agents can still
    ``Set-Content C:\\Users\\...`` and escape. Used by ToolOrchestrator.

    Only verb/redirect *targets* are considered so that writing a relative
    report that *mentions* an absolute path in its body is not false-blocked.
    """
    if not cmd:
        return []
    execution = (config or {}).get("execution", {}) or {}
    mode = str(execution.get("sandbox_mode") or "workspace").strip().lower()
    if mode == "host":
        return []
    # Drop -Value/-Content payloads and PowerShell here-strings so report
    # bodies that quote blocked paths do not false-trigger.
    scrubbed = re.sub(
        r"(?is)(-(?:Value|Content))\s+(@\"[\s\S]*?\"@|'[^']*'|\"[^\"]*\")",
        " ",
        cmd,
    )
    scrubbed = re.sub(r"(?is)@\"[\s\S]*?\"@", " ", scrubbed)
    blocked: list[str] = []
    seen: set[str] = set()
    for match in _BASH_MUTATING_TARGET_RE.finditer(scrubbed):
        raw = (match.group("path") or match.group("redir") or "").rstrip("\\/")
        if not raw or raw in seen:
            continue
        # Relative / cwd targets are fine.
        if raw.startswith(".\\") or raw.startswith("./"):
            continue
        seen.add(raw)
        if not is_write_allowed(raw, config):
            blocked.append(raw)
    return blocked


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
