"""Post-write diagnostics shared by every file-mutating tool.

Design
------
A write and the check of that write are **different facts** and are reported
separately: ``written: true`` plus ``diagnostics.status: problems`` is a
normal, honest outcome (the file IS on disk; its content has a syntax error).

Scope rules:

* Python — real ``compile()`` syntax check (never executes the file) and, when
  the project ships Ruff, a bounded read-only ``ruff check`` on that one file.
* JS/JSX/TS/TSX — a real parser/linter from the project's own toolchain when
  one is present (``eslint``, ``tsc``); JSX/TSX use the matching parser mode.
  Nothing is installed on demand.
* Anything without a usable checker reports ``unavailable`` / ``not_checked``,
  which never counts as a pass.  Bracket counting is NOT used: it was a fake
  "syntax OK" signal in ``tools/write.py`` and could not see real errors.

This module runs checkers as separate processes so a slow lint never blocks
the agent's interactive shell or the event loop.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

#: Machine-readable status.  Only ``pass`` counts as a successful check.
DiagnosticStatus = Literal[
    "pass",
    "problems",
    "unavailable",
    "timeout",
    "cancelled",
    "stale",
    "not_checked",
]

#: Per-checker wall-clock cap.  The task-level budget stays with the harness.
CHECK_TIMEOUT = 20.0

#: Cap on issues carried back to the model (rest are counted, not shown).
MAX_ISSUES = 20

PYTHON_SUFFIXES = frozenset({".py"})
JS_SUFFIXES = frozenset({".js", ".jsx", ".mjs", ".cjs"})
TS_SUFFIXES = frozenset({".ts", ".tsx", ".mts", ".cts"})
CHECKABLE_SUFFIXES = PYTHON_SUFFIXES | JS_SUFFIXES | TS_SUFFIXES


@dataclass
class DiagnosticIssue:
    """One finding, with the position the checker actually reported."""

    line: int | None = None
    column: int | None = None
    code: str = ""
    message: str = ""
    level: str = "error"


@dataclass
class DiagnosticReport:
    """Outcome of checking ONE version of ONE file."""

    path: str
    operation: str = "write"
    #: Fingerprint of the content that was checked (not mtime).
    fingerprint: str = ""
    #: The write itself succeeded regardless of what the checker found.
    written: bool = True
    status: DiagnosticStatus = "not_checked"
    checker: str = ""
    checker_version: str = ""
    scope: str = "file"
    duration_ms: int = 0
    issues: list[DiagnosticIssue] = field(default_factory=list)
    truncated: bool = False
    note: str = ""

    @property
    def ok(self) -> bool:
        """Only an executed check that found nothing counts as a pass."""
        return self.status == "pass"

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "operation": self.operation,
            "fingerprint": self.fingerprint,
            "written": self.written,
            "status": self.status,
            "checker": self.checker,
            "checker_version": self.checker_version,
            "scope": self.scope,
            "duration_ms": self.duration_ms,
            "truncated": self.truncated,
            "note": self.note,
            "issues": [
                {
                    "line": issue.line,
                    "column": issue.column,
                    "code": issue.code,
                    "message": issue.message,
                    "level": issue.level,
                }
                for issue in self.issues
            ],
        }

    def render(self) -> str:
        """Compact, model-facing one-block summary."""
        if self.status == "pass":
            extra = f" ({self.checker})" if self.checker else ""
            return f"\n[syntax check: OK{extra}]"
        if self.status == "problems":
            head = (
                f"\n[syntax check: {len(self.issues)} problem(s) via "
                f"{self.checker}]"
            )
            lines = [head]
            for issue in self.issues[:8]:
                where = ""
                if issue.line is not None:
                    where = f" line {issue.line}"
                    if issue.column is not None:
                        where += f":{issue.column}"
                code = f" [{issue.code}]" if issue.code else ""
                lines.append(f"  {where.strip()}{code} {issue.message}".rstrip())
            if len(self.issues) > 8:
                lines.append(f"  ... ({len(self.issues) - 8} more)")
            return "\n".join(lines)
        if self.status == "unavailable":
            return f"\n[syntax check: unavailable — {self.note or 'no checker for this file type'}]"
        if self.status == "timeout":
            return f"\n[syntax check: timed out after {self.duration_ms}ms]"
        if self.status == "cancelled":
            return "\n[syntax check: cancelled]"
        if self.status == "stale":
            return "\n[syntax check: stale — the file changed while it was being checked]"
        return f"\n[syntax check: not checked — {self.note or 'no applicable checker'}]"


def content_fingerprint(content: str) -> str:
    """Stable fingerprint of the checked content.

    Line endings are normalised first: the same file read back with CRLF vs LF
    (a Windows checkout or an editor that rewrites endings) must not be
    reported as a different version (audit P2-08).
    """
    normalized = content.replace("\r\n", "\n").replace("\r", "\n")
    return hashlib.sha256(normalized.encode("utf-8", errors="replace")).hexdigest()[:16]


def _language(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in PYTHON_SUFFIXES:
        return "python"
    if suffix in JS_SUFFIXES:
        return "js"
    if suffix in TS_SUFFIXES:
        return "ts"
    return ""


def _python_syntax(content: str, path: Path) -> tuple[list[DiagnosticIssue], str]:
    try:
        compile(content, str(path), "exec")
    except SyntaxError as exc:
        return (
            [
                DiagnosticIssue(
                    line=exc.lineno,
                    column=exc.offset,
                    code="syntax",
                    message=exc.msg or "syntax error",
                )
            ],
            "python:compile",
        )
    except ValueError as exc:
        return (
            [DiagnosticIssue(code="syntax", message=str(exc))],
            "python:compile",
        )
    return [], "python:compile"


async def _run_checker(
    argv: list[str],
    cwd: Path,
    *,
    timeout: float = CHECK_TIMEOUT,
) -> tuple[int | None, str, str, bool]:
    """Run an external checker through the CONTROLLED execution entry.

    Audit P1-03: checkers used to be spawned with a bare
    ``create_subprocess_exec``.  That bypassed the sandbox/policy layer even
    though checkers execute project code by design (ESLint configs are
    JavaScript; plugins run on load).  Routing through
    ``ShellExecutor.execute_argv_async`` applies the same sandbox, resource
    limits, audit and cleanup as any other tool-spawned process, and keeps the
    checker off the agent's interactive shell.

    Returns ``(rc, stdout, stderr, timed_out)``.  ``rc is None`` means the
    checker could not be run at all, which callers must report as
    ``unavailable`` -- never as a pass.
    """
    try:
        from ..utils.shell import shell_executor

        result = await shell_executor.execute_argv_async(
            list(argv),
            workdir=str(cwd),
            timeout=float(timeout),
        )
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        return None, "", f"{type(exc).__name__}: {exc}", False

    if not isinstance(result, dict):
        return None, "", "checker runner returned no result", False

    # Audit P2 (round 4): ``execute_argv_async`` returns a *preview* plus an
    # artifact path.  Parsing the preview silently truncated machine output
    # (a real Ruff run produced 180 findings -> ~48 KiB preview -> "invalid
    # JSON" -> "unavailable", losing every diagnostic).  Machine protocols are
    # parsed from the complete artifact; only the model-facing summary is
    # compressed.
    stdout_full = _captured_text(result, "stdout")
    stderr_full = _captured_text(result, "stderr")

    error_type = str(result.get("error_type") or "")
    if error_type in {"sandbox_error", "timeout"} or result.get("timed_out"):
        # The sandbox refused, or the run hit its cap: the checker did not
        # produce a verdict.
        return (
            None,
            stdout_full,
            stderr_full or error_type,
            error_type == "timeout" or bool(result.get("timed_out")),
        )

    rc_raw = result.get("exit_code")
    try:
        rc = int(rc_raw) if rc_raw is not None else None
    except (TypeError, ValueError):
        rc = None
    if not result.get("success") and rc is None:
        return None, stdout_full, stderr_full, False
    return rc, stdout_full, stderr_full, False


def _captured_text(result: dict, stream: str) -> str:
    """Full captured text for one stream: artifact when present, else preview."""
    artifact = result.get(f"{stream}_artifact")
    if artifact:
        try:
            return Path(str(artifact)).read_text(encoding="utf-8", errors="replace")
        except OSError:
            pass
    return str(result.get(stream) or "")


#: Project config files that are EXECUTABLE code, not data.
_EXECUTABLE_CONFIG_NAMES = (
    "eslint.config.js",
    "eslint.config.mjs",
    "eslint.config.cjs",
    "eslint.config.ts",
    "eslint.config.mts",
    "eslint.config.cts",
    ".eslintrc.js",
    ".eslintrc.cjs",
    ".eslintrc.mjs",
    ".eslintrc.ts",
)


def project_config_execution_allowed(config: dict | None = None) -> bool:
    """May diagnostics execute the project's own checker configuration?

    Audit P1-03 (round 4): routing checkers through the controlled execution
    entry applies the sandbox but **not approval**.  An ESLint flat config is
    JavaScript, so "check this file" can run arbitrary project code and write
    anywhere the process can reach -- under ``auto_edit`` the user only
    consented to file edits, not code execution.

    Audit P1 (round 5): the mode must be the EFFECTIVE mode for this request,
    not the global config.  A prompt that narrowed itself to ``auto_edit`` while
    the global config says ``full_auto`` must not inherit execution trust.

    Trust therefore has to be explicit:
      * ``diagnostics.run_project_config_checkers: true``, or
      * a permission mode that already grants unapproved execution
        (``full_auto``/``full``), or
      * ``safety.auto_approve`` already covering ``danger``.

    Without trust the safe checks still run (Python ``compile``, ``node
    --check``, plugin-free tsc); only config-executing checkers are skipped and
    reported honestly as not checked.
    """
    cfg: dict = {}
    try:
        if isinstance(config, dict) and isinstance(config.get("safety"), dict):
            cfg = config
        else:
            from ..config.settings import load_config

            cfg = load_config() or {}
    except Exception:
        cfg = {}
    diagnostics_cfg = cfg.get("diagnostics") or {}
    if diagnostics_cfg.get("run_project_config_checkers") is True:
        return True
    safety = cfg.get("safety") or {}
    mode = ""
    try:
        from ..execution.tool_orchestrator import current_permission_mode

        mode = current_permission_mode(cfg or None)
    except Exception:
        mode = str(safety.get("permission_mode") or "confirm_all").strip().lower()
    if mode in {"full_auto", "full"}:
        return True
    auto_levels = {str(level).lower() for level in (safety.get("auto_approve") or [])}
    return "danger" in auto_levels


def executable_config_present(root: Path) -> Path | None:
    """Return the project's executable checker config, if it has one."""
    for name in _EXECUTABLE_CONFIG_NAMES:
        candidate = root / name
        if candidate.is_file():
            return candidate
    return None


#: Config files that are DATA (not executable) but can still import code
#: through ``extends``.
_DATA_CONFIG_NAMES = (
    ".eslintrc.json",
    ".eslintrc",
    ".eslintrc.yaml",
    ".eslintrc.yml",
)

#: Suffixes that mean "loading this file runs code".
_EXECUTABLE_CONFIG_SUFFIXES = frozenset({".js", ".cjs", ".mjs", ".ts", ".mts", ".cts"})

_ESLINT_CONFIG_CHAIN_MAX_DEPTH = 8


def _resolve_eslint_extends(config_path: Path, spec: str) -> Path | None:
    """Resolve a relative ``extends`` entry to a file, or ``None``."""
    candidate = Path(spec)
    base = candidate if candidate.is_absolute() else config_path.parent / candidate
    options = [base]
    if base.suffix == "":
        for suffix in (".js", ".cjs", ".mjs", ".json"):
            options.append(base.with_name(base.name + suffix))
    options.extend([base / "index.js", base / "index.cjs"])
    for option in options:
        if option.is_file():
            return option
    return None


def _eslint_config_may_execute(config_path: Path, _depth: int = 0) -> bool:
    """True when this ESLint config can end up loading executable code.

    Audit P1 (round 5): a JSON config is not automatically safe -- its
    ``extends`` can point at a project file (``./payload.cjs``) that ESLint will
    ``require``.  Relative/absolute ``extends`` targets are resolved and
    inspected recursively; an unresolvable one is treated as executable
    ("cannot prove safe -> require trust").  Package extends and the built-in
    ``eslint:``/``plugin:`` presets are dependency code, not project code.
    """
    suffix = config_path.suffix.lower()
    if suffix in _EXECUTABLE_CONFIG_SUFFIXES:
        return True
    if _depth > _ESLINT_CONFIG_CHAIN_MAX_DEPTH:
        return True
    payload = _parse_jsonc_file(config_path) if suffix in {"", ".json"} else None
    if payload is None:
        # YAML / unparsable: cannot prove the extends chain is data-only.
        return True
    if config_path.name == "package.json":
        payload = payload.get("eslintConfig")
        if not isinstance(payload, dict):
            return False
    extends = payload.get("extends")
    specs = extends if isinstance(extends, list) else ([extends] if extends else [])
    for spec in specs:
        text = str(spec).strip()
        if not text:
            continue
        if text.startswith(("eslint:", "plugin:")):
            continue
        if not (text.startswith(".") or Path(text).is_absolute()):
            continue
        resolved = _resolve_eslint_extends(config_path, text)
        if resolved is None:
            return True
        if _eslint_config_may_execute(resolved, _depth + 1):
            return True
    return False


def find_executable_eslint_config(start: Path) -> Path | None:
    """Find the ESLint config that would ACTUALLY be resolved and may run code.

    Audit P1 (round 5): checking only ``node_root`` misses the real resolution
    chain.  ESLint walks up from the working directory -- a nested package
    without its own config inherits the parent directory's
    ``eslint.config.js`` and executes that JavaScript.

    Data configs are not automatically safe either: ``.eslintrc.json`` can
    ``extends`` a project ``.cjs`` file, which ESLint will execute.  This walk
    therefore returns the nearest config whose EFFECTIVE chain may load code.
    """
    try:
        current = start.resolve()
    except OSError:
        current = start
    seen: set[Path] = set()
    while True:
        if current not in seen:
            seen.add(current)
            for name in _EXECUTABLE_CONFIG_NAMES:
                candidate = current / name
                if candidate.is_file() and _eslint_config_may_execute(candidate):
                    return candidate
            for name in _DATA_CONFIG_NAMES:
                candidate = current / name
                if candidate.is_file() and _eslint_config_may_execute(candidate):
                    return candidate
            package_json = current / "package.json"
            if package_json.is_file() and _eslint_config_may_execute(package_json):
                return package_json
        parent = current.parent
        if parent == current:
            return None
        current = parent


_TSCONFIG_MAX_EXTENDS_DEPTH = 8


def _strip_jsonc(text: str) -> str:
    """Strip ``//`` / ``/* */`` comments and trailing commas (tsconfig is JSONC)."""
    out: list[str] = []
    i = 0
    length = len(text)
    in_string = False
    while i < length:
        char = text[i]
        if in_string:
            out.append(char)
            if char == "\\" and i + 1 < length:
                out.append(text[i + 1])
                i += 2
                continue
            if char == '"':
                in_string = False
            i += 1
            continue
        if char == '"':
            in_string = True
            out.append(char)
            i += 1
            continue
        if char == "/" and i + 1 < length and text[i + 1] == "/":
            while i < length and text[i] not in "\r\n":
                i += 1
            continue
        if char == "/" and i + 1 < length and text[i + 1] == "*":
            i += 2
            while i + 1 < length and not (text[i] == "*" and text[i + 1] == "/"):
                i += 1
            i += 2
            continue
        out.append(char)
        i += 1
    return re.sub(r",(\s*[}\]])", r"\1", "".join(out))


def _parse_jsonc_file(path: Path) -> dict | None:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    try:
        payload = json.loads(_strip_jsonc(text))
    except (json.JSONDecodeError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def _resolve_tsconfig_extends(base: Path, spec: str) -> Path | None:
    """Resolve one ``extends`` entry the way tsc would (relative or package)."""
    spec = str(spec or "").strip()
    if not spec:
        return None
    target = Path(spec)
    candidates: list[Path] = []
    if target.is_absolute():
        candidates.append(target)
    elif spec.startswith("."):
        candidates.append(base.parent / target)
    else:
        # Bare package spec: node_modules/<pkg>[/<subpath>] from any ancestor.
        for ancestor in base.parents:
            candidates.append(ancestor / "node_modules" / target)
        candidates.append(base.parent / target)
    for candidate in candidates:
        if candidate.suffix == "":
            for option in (candidate.with_name(candidate.name + ".json"), candidate):
                if option.is_file():
                    return option
        elif candidate.is_file():
            return candidate
    return None


def _tsconfig_compiler_options(
    tsconfig: Path, _depth: int = 0
) -> dict | None:
    """Effective ``compilerOptions`` for a tsconfig, following ``extends``.

    Returns ``None`` when the config cannot be understood confidently (invalid
    JSONC, unresolvable ``extends`` chain, too deep).  Callers must treat
    ``None`` as "unknown", never as "empty".
    """
    payload = _parse_jsonc_file(tsconfig)
    if payload is None:
        return None
    merged: dict = {}
    extends = payload.get("extends")
    specs = extends if isinstance(extends, list) else [extends]
    for spec in specs:
        if not spec:
            continue
        if _depth >= _TSCONFIG_MAX_EXTENDS_DEPTH:
            return None
        base = _resolve_tsconfig_extends(tsconfig, str(spec))
        if base is None:
            return None
        base_options = _tsconfig_compiler_options(base, _depth + 1)
        if base_options is None:
            return None
        merged.update(base_options)
    options = payload.get("compilerOptions")
    if isinstance(options, dict):
        merged.update(options)
    return merged


def _tsconfig_loads_plugins(tsconfig: Path) -> bool:
    """True when tsconfig declares compiler plugins (they load arbitrary code).

    Unknown config is treated as "may load code": without trust the tsc check is
    skipped rather than executing something we could not inspect.
    """
    options = _tsconfig_compiler_options(tsconfig)
    if options is None:
        return True
    plugins = options.get("plugins")
    return isinstance(plugins, list) and bool(plugins)


def _tsconfig_is_composite(tsconfig: Path) -> bool:
    """True when the project uses composite project references.

    Unknown config is treated as composite so ``--incremental false`` is NOT
    added: TS6379 (composite may not disable incremental compilation) would make
    every composite project's type check fail.  A JSONC config with comments
    used to parse as "not composite" and hit exactly that (audit P2, round 5).
    """
    options = _tsconfig_compiler_options(tsconfig)
    if options is None:
        return True
    return bool(options.get("composite"))


async def check_python(
    path: Path, content: str, *, fingerprint: str, operation: str
) -> DiagnosticReport:
    started = time.perf_counter()
    quality_issues, checker = _python_syntax(content, path)
    issues = list(quality_issues)
    versions: list[str] = []
    #: Set when a checker ran but could not produce a trustworthy verdict.
    checker_error = ""

    ruff = shutil.which("ruff")
    if ruff:
        rc, out, err, timed_out = await _run_checker(
            [ruff, "check", "--output-format", "json", "--no-cache", str(path)],
            path.parent,
        )
        if timed_out:
            checker_error = "ruff timed out"
        elif rc is None:
            checker_error = f"ruff could not run: {err.strip()[:120] or 'unknown error'}"
        else:
            parsed = _parse_ruff_json(out)
            if parsed is None:
                # rc 2 (or any non-0/1) with unparsable output means the
                # CHECKER failed -- broken config, bad flags, missing plugin.
                # That is NOT "no problems", and must never be reported as a
                # pass: the file simply was not verified.
                checker_error = (
                    f"ruff exited {rc} without valid JSON"
                    + (f": {err.strip()[:120]}" if err.strip() else "")
                )
            else:
                issues.extend(parsed)
                versions.append("ruff")
    else:
        # Syntax passed but lint never ran; say so instead of implying full
        # verification.
        checker_error = ""

    duration = int((time.perf_counter() - started) * 1000)
    if checker_error:
        report = DiagnosticReport(
            path=str(path),
            operation=operation,
            fingerprint=fingerprint,
            status="unavailable",
            checker=checker,
            scope="file",
            duration_ms=duration,
            issues=issues[:MAX_ISSUES],
            truncated=len(issues) > MAX_ISSUES,
            note=checker_error,
        )
        return report
    report = DiagnosticReport(
        path=str(path),
        operation=operation,
        fingerprint=fingerprint,
        status="problems" if issues else "pass",
        checker="+".join([checker, *versions]),
        scope="file",
        duration_ms=duration,
        issues=issues[:MAX_ISSUES],
        truncated=len(issues) > MAX_ISSUES,
    )
    if not issues and not ruff:
        # Syntax passed but lint never ran; say so instead of implying full
        # verification.
        report.note = "ruff not installed; syntax only"
    return report


def _parse_ruff_json(out: str) -> list[DiagnosticIssue] | None:
    """Parse ``ruff check --output-format json``.

    Returns ``None`` when the output is not the expected JSON array, which is
    how a crashed/misconfigured ruff (exit code 2, plain-text complaint on
    stderr) presents itself.  Callers must treat ``None`` as "checker failed",
    never as "no issues".
    """
    text = (out or "").strip()
    if not text:
        # ruff prints ``[]`` when clean; an EMPTY stdout means it never got to
        # the reporting stage (bad config, bad flags).  Returning [] here was
        # the audit's false "pass"--ruff exits 2 with nothing on stdout.
        return None
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, list):
        return None
    issues: list[DiagnosticIssue] = []
    for item in payload:
        if not isinstance(item, dict):
            return None
        loc = item.get("location") or {}
        issues.append(
            DiagnosticIssue(
                line=loc.get("row"),
                column=loc.get("column"),
                code=str(item.get("code") or ""),
                message=str(item.get("message") or ""),
                level="error",
            )
        )
    return issues


def _parse_eslint_json(out: str) -> list[DiagnosticIssue] | None:
    """Parse eslint's JSON format.  ``None`` = the checker did not report."""
    text = (out or "").strip()
    if not text:
        return []
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, list):
        return None
    issues: list[DiagnosticIssue] = []
    for file_result in payload:
        if not isinstance(file_result, dict):
            return None
        for message in file_result.get("messages") or []:
            issues.append(
                DiagnosticIssue(
                    line=message.get("line"),
                    column=message.get("column"),
                    code=str(message.get("ruleId") or ""),
                    message=str(message.get("message") or ""),
                    level=(
                        "error"
                        if str(message.get("severity")) in {"2", "error"}
                        else "warning"
                    ),
                )
            )
    return issues


def _normalise_path_key(path: Path, root: Path) -> str:
    """Project-relative, slash-separated, case-folded key for comparison."""
    try:
        resolved = path.resolve()
    except OSError:
        resolved = path
    try:
        root_resolved = root.resolve()
    except OSError:
        root_resolved = root
    try:
        relative = resolved.relative_to(root_resolved)
    except ValueError:
        relative = resolved
    key = str(relative).replace("\\", "/")
    if os.name == "nt":
        key = key.casefold()
    # Only a leading "./" is noise; a leading "../" is a REAL different path and
    # must never be stripped (audit P2, round 4).
    while key.startswith("./"):
        key = key[2:]
    return key


def _same_file(reported: str, target_key: str, root: Path) -> bool:
    """True when a checker-reported path refers to the target file.

    Comparison is by RESOLVED path, never by stripping characters.  Audit P2
    (round 4): ``reported.lstrip("./")`` turned a parent-relative
    ``../src/a.ts`` into ``src/a.ts`` and mis-attributed another directory's
    diagnostics to the checked file.  ``src/a.ts`` and ``lib/a.ts`` must also
    never collide (earlier finding P2-09).
    """
    reported = reported.strip().strip('"')
    if not reported:
        return False
    candidate = Path(reported)
    if not candidate.is_absolute():
        candidate = root / reported
    try:
        return _normalise_path_key(candidate, root) == target_key
    except OSError:
        return False


async def _tsc_includes(
    tsc: str, tsconfig: Path, root: Path, path: Path
) -> bool | None:
    """Did the project program actually include ``path``?

    ``True``/``False`` when tsc answered, ``None`` when the probe itself could
    not run (callers then keep the type-check verdict instead of inventing a
    failure).
    """
    rc, out, err, timed_out = await _run_checker(
        [tsc, "--listFilesOnly", "--pretty", "false", "--project", str(tsconfig)],
        root,
        timeout=min(CHECK_TIMEOUT, 15.0),
    )
    if timed_out or rc is None:
        return None
    target_key = _normalise_path_key(path, root)
    listed = (out or "") + "\n" + (err or "")
    for line in listed.splitlines():
        if _same_file(line.strip(), target_key, root):
            return True
    return False


async def check_js_ts(
    path: Path, content: str, *, fingerprint: str, operation: str, node_root: Path
) -> DiagnosticReport:
    """Check JS/TS with the project's own toolchain, never a bracket counter."""
    started = time.perf_counter()
    ts_like = path.suffix.lower() in TS_SUFFIXES

    # Audit P1-03 (round 4): an executable checker config (ESLint flat config
    # is JS) runs project code.  Without explicit trust, skip THAT checker
    # instead of executing it behind the user's back -- but keep the safe
    # parser checks below running.  Returning ``not_checked`` for the whole
    # file would silently drop type checking in every project that ships an
    # ESLint flat config (the common Next.js/Vite layout).
    #
    # Audit P1 (round 5): resolve the config the way ESLint does (walking up),
    # not just the local directory: a nested package inherits the parent's
    # executable config and executes it.
    executable_config = find_executable_eslint_config(node_root)
    trusted = project_config_execution_allowed()
    skipped_checker_note = ""

    eslint = _find_local_bin(node_root, "eslint")
    if eslint and executable_config is not None and not trusted:
        skipped_checker_note = (
            f"the resolved ESLint config ({executable_config.name}) is executable "
            "JavaScript; it was not run because this session has not granted "
            "code-execution trust (auto_edit/confirm_all). Set "
            "diagnostics.run_project_config_checkers: true or use a full-auto "
            "mode to enable it"
        )
        eslint = None
    if eslint:
        rc, out, err, timed_out = await _run_checker(
            [str(eslint), "--format", "json", str(path)],
            node_root,
        )
        if timed_out:
            return DiagnosticReport(
                path=str(path),
                operation=operation,
                fingerprint=fingerprint,
                status="timeout",
                checker="eslint",
                duration_ms=int((time.perf_counter() - started) * 1000),
            )
        if rc is None:
            return DiagnosticReport(
                path=str(path),
                operation=operation,
                fingerprint=fingerprint,
                status="unavailable",
                checker="eslint",
                duration_ms=int((time.perf_counter() - started) * 1000),
                note=f"eslint could not run: {err.strip()[:120] or 'unknown error'}",
            )
        # eslint exit codes are part of the protocol: 0 = no findings,
        # 1 = lint findings, 2 = fatal/config/plugin failure.  Audit P2-06: a
        # fatal exit with empty stdout used to parse as "[]" and be reported as
        # a pass.  Validate the code first, then the payload.
        if rc not in (0, 1):
            return DiagnosticReport(
                path=str(path),
                operation=operation,
                fingerprint=fingerprint,
                status="unavailable",
                checker="eslint",
                duration_ms=int((time.perf_counter() - started) * 1000),
                note=(
                    f"eslint exited {rc} (fatal/config error)"
                    + (f": {err.strip()[:120]}" if err.strip() else "")
                ),
            )
        parsed = _parse_eslint_json(out)
        if parsed is None:
            return DiagnosticReport(
                path=str(path),
                operation=operation,
                fingerprint=fingerprint,
                status="unavailable",
                checker="eslint",
                duration_ms=int((time.perf_counter() - started) * 1000),
                note=(
                    f"eslint exited {rc} without valid JSON"
                    + (f": {err.strip()[:120]}" if err.strip() else "")
                ),
            )
        if rc == 1 and not parsed and not out.strip():
            # "Reported findings" but produced no payload: not a pass.
            return DiagnosticReport(
                path=str(path),
                operation=operation,
                fingerprint=fingerprint,
                status="unavailable",
                checker="eslint",
                duration_ms=int((time.perf_counter() - started) * 1000),
                note="eslint exited 1 without any report payload",
            )
        issues: list[DiagnosticIssue] = parsed
        return DiagnosticReport(
            path=str(path),
            operation=operation,
            fingerprint=fingerprint,
            status="problems" if issues else "pass",
            checker="eslint",
            scope="file",
            duration_ms=int((time.perf_counter() - started) * 1000),
            issues=issues[:MAX_ISSUES],
            truncated=len(issues) > MAX_ISSUES,
            )

    tsc = _find_local_bin(node_root, "tsc")
    if tsc and ts_like:
        # Use the PROJECT's compiler options.  Passing ad-hoc --jsx flags
        # ignored tsconfig and produced false type errors (the audit saw a
        # valid Promise-using file flagged because lib/target came from
        # defaults).  tsc resolves its own tsconfig when run from the project
        # root; when there is no tsconfig we fall through to "unavailable"
        # rather than inventing compiler settings.
        tsconfig = node_root / "tsconfig.json"
        if not tsconfig.is_file():
            return DiagnosticReport(
                path=str(path),
                operation=operation,
                fingerprint=fingerprint,
                status="unavailable",
                checker="tsc",
                duration_ms=int((time.perf_counter() - started) * 1000),
                note="no tsconfig.json in the project; project type checking skipped",
            )
        # tsc plugins load arbitrary modules at startup, so they need the same
        # trust gate as an executable ESLint config (audit P1-03).  An
        # unreadable config is treated as "may load code" (audit P1, round 5:
        # a JSONC config used to be mis-parsed and silently ignored).
        tsconfig_options = _tsconfig_compiler_options(tsconfig)
        if tsconfig_options is None and not trusted:
            return DiagnosticReport(
                path=str(path),
                operation=operation,
                fingerprint=fingerprint,
                status="not_checked",
                checker="tsc",
                duration_ms=int((time.perf_counter() - started) * 1000),
                note=(
                    "the project tsconfig could not be parsed confidently "
                    "(JSONC/extends); tsc was not run because it may load "
                    "project code and this session has not granted "
                    "code-execution trust"
                ),
            )
        if _tsconfig_loads_plugins(tsconfig) and not trusted:
            return DiagnosticReport(
                path=str(path),
                operation=operation,
                fingerprint=fingerprint,
                status="not_checked",
                checker="tsc",
                duration_ms=int((time.perf_counter() - started) * 1000),
                note=(
                    "the project tsconfig declares compiler plugins, which load "
                    "executable code; it was not run because this session has "
                    "not granted code-execution trust"
                ),
            )
        # ``--noEmit`` keeps this read-only.  ``--incremental false`` stops tsc
        # writing .tsbuildinfo -- but it is ILLEGAL for composite projects
        # (TS6379: "Composite projects may not disable incremental
        # compilation"), so it is only added when the project is not composite
        # (audit P2, round 4).
        argv = [
            str(tsc),
            "--noEmit",
            "--pretty",
            "false",
        ]
        if not _tsconfig_is_composite(tsconfig):
            argv += ["--incremental", "false"]
        argv += ["--project", str(tsconfig)]
        rc, out, err, timed_out = await _run_checker(argv, node_root)
        if timed_out:
            return DiagnosticReport(
                path=str(path),
                operation=operation,
                fingerprint=fingerprint,
                status="timeout",
                checker="tsc",
                duration_ms=int((time.perf_counter() - started) * 1000),
            )
        if rc is None:
            return DiagnosticReport(
                path=str(path),
                operation=operation,
                fingerprint=fingerprint,
                status="unavailable",
                checker="tsc",
                duration_ms=int((time.perf_counter() - started) * 1000),
                note=f"tsc could not run: {err.strip()[:120] or 'unknown error'}",
            )

        # Audit P2-07: a file EXCLUDED by the project tsconfig produces a clean
        # exit with no diagnostics -- reporting that as a pass claims a check
        # that never happened.  Confirm the target is actually in the program.
        included = await _tsc_includes(tsc, tsconfig, node_root, path)
        if included is False:
            return DiagnosticReport(
                path=str(path),
                operation=operation,
                fingerprint=fingerprint,
                status="not_checked",
                checker="tsc",
                duration_ms=int((time.perf_counter() - started) * 1000),
                note=(
                    "the project tsconfig excludes this file; project type "
                    "checking did not cover it"
                ),
            )

        combined = (out or "") + "\n" + (err or "")
        issues = []
        # tsc prints paths RELATIVE to the project root.  Match on a normalised
        # path (audit P2-09): matching only the bare file name mis-attributed
        # errors when two directories held same-named files.
        target_key = _normalise_path_key(path, node_root)
        for line in combined.splitlines():
            if "error TS" not in line:
                continue
            head = line.split("(", 1)[0].replace("\\", "/").strip()
            if not _same_file(head, target_key, node_root):
                continue
            parts = line.split("(", 1)
            loc = parts[1].split(")", 1)[0] if len(parts) > 1 else ""
            lno, _, col = loc.partition(",")
            code = ""
            if "error TS" in line:
                code = "TS" + line.split("error TS", 1)[1].split(":", 1)[0].strip()
            issues.append(
                DiagnosticIssue(
                    line=int(lno) if lno.strip().isdigit() else None,
                    column=int(col) if col.strip().isdigit() else None,
                    code=code,
                    message=line.strip()[:300],
                )
            )
        # tsc exit codes: 0 clean, 1/2 errors reported (older/newer versions
        # differ -- the repo's Bun-provided tsc returns 2 for type errors), and
        # 3+ for config/internal failure.  Treat "has diagnostics" as
        # authoritative; only an rc with NO diagnostics is a checker failure.
        if not issues and rc not in (0,):
            return DiagnosticReport(
                path=str(path),
                operation=operation,
                fingerprint=fingerprint,
                status="unavailable",
                checker="tsc",
                duration_ms=int((time.perf_counter() - started) * 1000),
                note=(
                    f"tsc exited {rc} without usable diagnostics"
                    + (f": {err.strip()[:120]}" if err.strip() else "")
                ),
            )
        return DiagnosticReport(
            path=str(path),
            operation=operation,
            fingerprint=fingerprint,
            status="problems" if issues else "pass",
            checker="tsc",
            scope="file",
            duration_ms=int((time.perf_counter() - started) * 1000),
            issues=issues[:MAX_ISSUES],
            truncated=len(issues) > MAX_ISSUES,
        )

    node = shutil.which("node")
    if node and not ts_like and path.suffix.lower() not in {".jsx", ".tsx"}:
        # Plain JS can be parsed for real by node itself.  JSX/TSX are NOT
        # valid JS, so ``node --check`` would report a bogus syntax error on
        # perfectly good JSX -- exclude them and report unavailable instead.
        rc, out, err, timed_out = await _run_checker(
            [node, "--check", str(path)], node_root
        )
        if timed_out:
            return DiagnosticReport(
                path=str(path),
                operation=operation,
                fingerprint=fingerprint,
                status="timeout",
                checker="node --check",
                duration_ms=int((time.perf_counter() - started) * 1000),
            )
        if rc is not None:
            # node --check: 0 = parsed, 1 = syntax error, anything else = the
            # runtime itself failed (cannot judge the file).
            if rc not in (0, 1):
                return DiagnosticReport(
                    path=str(path),
                    operation=operation,
                    fingerprint=fingerprint,
                    status="unavailable",
                    checker="node --check",
                    duration_ms=int((time.perf_counter() - started) * 1000),
                    note=f"node exited {rc} without a syntax verdict",
                )
            issues = (
                [DiagnosticIssue(code="syntax", message=(err or out).strip()[:300])]
                if rc != 0
                else []
            )
            return DiagnosticReport(
                path=str(path),
                operation=operation,
                fingerprint=fingerprint,
                status="problems" if issues else "pass",
                checker="node --check",
                scope="file",
                duration_ms=int((time.perf_counter() - started) * 1000),
                issues=issues,
            )

    fallback_note = (
        "no local eslint/tsc for this file type"
        if ts_like
        else "no local eslint/node available"
    )
    if skipped_checker_note:
        # Nothing safe ran, but the reason is the trust gate, not a missing
        # checker: say exactly that instead of a generic "unavailable".
        return DiagnosticReport(
            path=str(path),
            operation=operation,
            fingerprint=fingerprint,
            status="not_checked",
            checker="eslint",
            duration_ms=int((time.perf_counter() - started) * 1000),
            note=skipped_checker_note,
        )
    return DiagnosticReport(
        path=str(path),
        operation=operation,
        fingerprint=fingerprint,
        status="unavailable",
        duration_ms=int((time.perf_counter() - started) * 1000),
        note=fallback_note,
    )


def _find_local_bin(node_root: Path, name: str) -> Path | None:
    """Prefer the project's own bin, never a global install."""
    candidates = [
        node_root / "node_modules" / ".bin" / f"{name}.cmd",
        node_root / "node_modules" / ".bin" / name,
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    found = shutil.which(name)
    return Path(found) if found else None


def project_root_for(path: Path) -> Path:
    """Walk up to the nearest directory that looks like a project root."""
    for parent in (path.parent, *path.parents):
        if any(
            (parent / marker).exists()
            for marker in ("package.json", "tsconfig.json", "pyproject.toml")
        ):
            return parent
    return path.parent


async def diagnose(
    path: Path,
    content: str,
    *,
    operation: str = "write",
    written: bool = True,
) -> DiagnosticReport:
    """Check one saved version of ``path`` and return an honest report."""
    fingerprint = content_fingerprint(content)
    language = _language(path)
    if not language:
        return DiagnosticReport(
            path=str(path),
            operation=operation,
            fingerprint=fingerprint,
            written=written,
            status="not_checked",
            note=f"no checker for {path.suffix or 'this file type'}",
        )
    try:
        if language == "python":
            report = await check_python(
                path, content, fingerprint=fingerprint, operation=operation
            )
        else:
            report = await check_js_ts(
                path,
                content,
                fingerprint=fingerprint,
                operation=operation,
                node_root=project_root_for(path),
            )
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # a broken checker must not look like a write failure
        report = DiagnosticReport(
            path=str(path),
            operation=operation,
            fingerprint=fingerprint,
            written=written,
            status="unavailable",
            note=f"checker failed to run: {type(exc).__name__}",
        )
    report.written = written
    # Re-read the file and compare fingerprints.  A checker can take long
    # enough for another write to land; a pass for version A must never be
    # shown as a pass for version B.
    #
    # Audit P2-08: a DELETED file used to keep its "pass" because the re-read
    # was skipped when the path no longer existed.  A pass is only valid while
    # the exact checked content is on disk.
    try:
        if path.is_file():
            on_disk = path.read_text(encoding="utf-8", errors="replace")
            report = mark_stale(report, content_fingerprint(on_disk))
        else:
            report.status = "stale"
            report.note = (
                "the file no longer exists; the earlier check is not evidence "
                "for the current state"
            )
    except OSError:
        report.status = "stale"
        report.note = "the file could not be re-read; its version cannot be verified"
    return report


def mark_stale(report: DiagnosticReport, current_fingerprint: str) -> DiagnosticReport:
    """Downgrade a report whose file version has since been overwritten."""
    if report.fingerprint and report.fingerprint != current_fingerprint:
        report.status = "stale"
        report.note = "file changed after this check started; result is not evidence for the current content"
    return report
