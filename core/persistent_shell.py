"""Managed persistent shell for the agent's interactive ``bash`` tool.

Why this exists
---------------
``bash`` used to spawn a brand-new shell for every call, so ``export``
disappeared, ``cd`` was reverted, a venv activated in one call was gone the
next, and every call paid process-startup cost.  This module keeps ONE
long-lived shell per (session, isolation) identity and streams commands into
it.

Design constraints learned from the first audit round (2026-10-23)
-----------------------------------------------------------------
The first implementation kept state correctly but broke four things that must
never regress.  Each is enforced structurally here:

1. **Same process protection as the one-shot path.**  The shell is created
   through ``ShellExecutor``'s own policy/sandbox machinery, not a bare
   ``create_subprocess_exec``.  OS sandbox + resource limits apply to the
   shell and everything it spawns.
2. **Real exit codes.**  Each command reports its OWN exit status.  A stale
   ``$LASTEXITCODE`` from the previous round is cleared, and PowerShell's
   error stream is surfaced instead of being silently reported as success.
3. **A protocol that cannot hang or crash.**  Output is read in bounded
   chunks (not ``readline()``), so a line without a trailing newline still
   completes, and a multi-megabyte single line cannot trip the stream
   separator limit.  Output is capped while streaming.
4. **Cancel kills the whole process tree.**  A failing/incomplete command
   destroys the shell (and its descendants); it is never left half-alive.

State lives in memory only (env can hold credentials); nothing is serialized.
"""

from __future__ import annotations

import asyncio
import base64
import codecs
import logging
import os
import secrets
import shlex
import shutil
import signal
import subprocess
import sys
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .sandbox import manager as sandbox_manager
from .sandbox.types import JobPlan
from .session_runtime import current_session_id
from ..utils import shell as shell_module

_logger = logging.getLogger(__name__)

#: How long to wait for the shell to become usable after spawn.
STARTUP_TIMEOUT = 30.0

#: Default per-command cap when the caller does not pass one.
DEFAULT_COMMAND_TIMEOUT = 1800.0

#: Hard cap on bytes retained from one command's stdout (the rest is dropped
#: with a marker).  BoundedOutputCapture downstream does the real preview /
#: spill work; this only stops us from holding an unbounded string first.
MAX_CAPTURE_BYTES = 4 * 1024 * 1024

#: Read chunk size.  Chunked reads are what make newline-free output safe.
READ_CHUNK = 64 * 1024

#: Random per-process marker seed so output text cannot spoof completion.
_MARKER_SEED = uuid.uuid4().hex[:12]


class ShellStartupError(RuntimeError):
    """The managed shell could not be started.

    ``sandbox_refused`` marks the subset of failures where the *sandbox* said
    no.  Callers must not downgrade those into an unsandboxed fallback (audit
    P2-12); an ordinary startup failure may fall back to the one-shot path.
    """

    def __init__(self, message: str, *, sandbox_refused: bool = False) -> None:
        super().__init__(message)
        self.sandbox_refused = sandbox_refused


class ShellLostError(RuntimeError):
    """The shell died, or its state can no longer be trusted.

    A reaped process can supply exit evidence, but never a completion receipt.
    Timeout/cancel cleanup must not supply the return code of its own kill.
    """

    def __init__(
        self,
        message: str,
        *,
        exit_code: int | None = None,
        stdout: str = "",
        truncated: bool = False,
    ) -> None:
        super().__init__(message)
        self.exit_code = exit_code
        self.stdout = stdout
        self.truncated = truncated


class ShellLivenessStop(ShellLostError):
    """The current command was cancelled by one explicit liveness decision."""

    def __init__(self, note: str) -> None:
        super().__init__(f"liveness stop: {note}")
        self.note = note


@dataclass
class CommandOutcome:
    """Result of one command executed in a managed shell."""

    stdout: str
    exit_code: int | None
    cwd_after: str | None = None
    timed_out: bool = False
    error: str | None = None
    cancelled: bool = False
    truncated: bool = False
    stderr_errors: str = ""

    @property
    def success(self) -> bool:
        return (
            not self.timed_out
            and not self.cancelled
            and self.error is None
            and self.exit_code == 0
        )


# ---------------------------------------------------------------------------
# Shell selection
# ---------------------------------------------------------------------------

def default_shell_argv() -> list[str]:
    """Interactive shell for this platform.

    Mirrors what ``ShellExecutor`` chooses so behaviour stays familiar.
    ``-NoProfile``/``-NoLogo`` keep startup cheap and banner-free; ``-Command
    -`` reads the command stream from stdin.
    """
    if sys.platform == "win32":
        executable = shutil.which("powershell.exe") or shutil.which("powershell")
        if executable:
            return [
                executable,
                "-NoLogo",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                "-",
            ]
        return ["cmd.exe", "/Q"]
    for candidate in ("/bin/bash", "/usr/bin/bash", "/bin/sh"):
        if Path(candidate).is_file():
            return [candidate]
    return ["/bin/sh"]


def _is_powershell(argv: list[str]) -> bool:
    return bool(argv) and "powershell" in Path(argv[0]).name.lower()


def _is_cmd(argv: list[str]) -> bool:
    return bool(argv) and Path(argv[0]).name.lower() in {"cmd", "cmd.exe"}


@dataclass
class _MarkerProtocol:
    token: str
    begin: str
    end: str
    rc_file_path: str = ""
    err_file_path: str = ""
    cwd_file_path: str = ""
    out_file_path: str = ""


def _marker_protocol(workdir: str = "") -> _MarkerProtocol:
    """Build a per-command protocol with unique sentinels and temp files.

    Exit status and the error message travel through temp files (not the
    merged stdout stream) so PowerShell's output/error interleaving cannot
    corrupt the framing.
    """
    token = f"{_MARKER_SEED}{uuid.uuid4().hex[:16]}"
    base = Path(workdir) if workdir else Path.cwd()
    rc_file = base / f".rxy_rc_{token}.tmp"
    err_file = base / f".rxy_err_{token}.tmp"
    cwd_file = base / f".rxy_cwd_{token}.tmp"
    out_file = base / f".rxy_out_{token}.tmp"
    return _MarkerProtocol(
        token=token,
        begin=f"__RXY_BEGIN_{token}__",
        end=f"__RXY_END_{token}__",
        rc_file_path=str(rc_file),
        err_file_path=str(err_file),
        cwd_file_path=str(cwd_file),
        out_file_path=str(out_file),
    )


def _ps_quote(text: str) -> str:
    """Single-quoted PowerShell literal."""
    return "'" + text.replace("'", "''") + "'"


def _read_and_remove(path_text: str) -> str:
    """Read a temp file the wrapper wrote, then delete it.  Missing = empty."""
    if not path_text:
        return ""
    path = Path(path_text)
    try:
        text = path.read_text(encoding="utf-8-sig", errors="replace").strip()
    except OSError:
        return ""
    finally:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass
    return text


def _protocol_files(protocol: _MarkerProtocol) -> list[str]:
    """Every temp file this command's wrapper may write."""
    return [
        path
        for path in (
            protocol.rc_file_path,
            protocol.err_file_path,
            protocol.cwd_file_path,
            protocol.out_file_path,
        )
        if path
    ]


def _read_int_file(path_text: str) -> int | None:
    """Read one integer the wrapper wrote, then delete the file."""
    text = _read_and_remove(path_text)
    if not text:
        return None
    try:
        return int(text.splitlines()[0].strip())
    except (ValueError, IndexError):
        return None


def _read_capped(path_text: str) -> tuple[str, bool]:
    """Read a captured-output file with a hard byte cap (legacy helper).

    Kept as the bounded fallback for callers that cannot stream.  The live
    PowerShell path now uses :func:`_feed_file`, which streams the file into
    the shared capture without an intermediate capped string (audit P2-04).
    """
    if not path_text:
        return "", False
    path = Path(path_text)
    if not path.exists():
        return "", False
    truncated = False
    try:
        size = path.stat().st_size
        if size > MAX_CAPTURE_BYTES:
            truncated = True
            with path.open("rb") as handle:
                raw = handle.read(MAX_CAPTURE_BYTES)
        else:
            raw = path.read_bytes()
    except OSError:
        return "", False
    finally:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass
    return raw.decode("utf-8-sig", errors="replace"), truncated


def _feed_file(path_text: str, capture: Any, chunks: list[str]) -> bool:
    """Stream a captured-output file into the shared bounded capture.

    Returns whether the payload was truncated for the caller's own reporting.
    The file is read in chunks so a multi-megabyte capture never materialises
    as one string before the bounded-capture stage sees it (audit P2-04).
    """
    if not path_text:
        return False
    path = Path(path_text)
    if not path.exists():
        return False
    truncated = False
    try:
        with path.open("rb") as handle:
            first = True
            while True:
                block = handle.read(READ_CHUNK)
                if not block:
                    break
                if first:
                    first = False
                    # Strip a UTF-8 BOM written by Out-File.
                    if block.startswith(codecs.BOM_UTF8):
                        block = block[len(codecs.BOM_UTF8) :]
                text = block.decode("utf-8", errors="replace")
                if capture is not None:
                    try:
                        capture.feed("stdout", text.encode("utf-8", errors="replace"))
                    except Exception:
                        pass
                else:
                    chunks.append(text)
    except OSError:
        return False
    finally:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass
    return truncated


# ---------------------------------------------------------------------------
# Command protocol
# ---------------------------------------------------------------------------

def _build_wrapped_command(
    command: str,
    protocol: _MarkerProtocol,
    *,
    powershell: bool,
    workdir: str = "",
    cmd_shell: bool = False,
) -> str:
    """Wrap ``command`` so its own exit code and real cwd come back.

    Contract:
      * ``BEGIN`` marker is written before anything runs.
      * If ``workdir`` is given and cannot be entered, the command MUST NOT
        run; a ``workdir_failed`` trailer is emitted instead.
      * ``END rc=<n>`` carries THIS command's exit status only.
      * ``CWD<token> <path>`` carries the confirmed directory.
      * ``ERR<token>`` block carries PowerShell's error stream (if any), so a
        failing cmdlet is not reported as success.

    ``workdir`` scopes ONLY the directory.  It deliberately does not use a
    subshell, because that would isolate variables and functions too.
    """
    if powershell:
        # Exit status is passed through a temp file rather than parsed out of
        # the merged stdout stream: PowerShell mixes cmdlet output, host
        # output and error records in ways that make in-band framing fragile.
        # The file also lets us distinguish "command ran, rc=N" from
        # "command never ran" without guessing.
        #
        # WHY A SINGLE LINE: ``powershell -Command -`` reads stdin ONE COMMAND
        # AT A TIME and stops at an incomplete block.  A multi-line wrapper
        # (``if (...) {`` on its own line) therefore never executes the body --
        # that is exactly what hung the first audit round.  Everything below is
        # emitted as ONE statement line so the interactive parser always sees a
        # complete command.
        #
        # WHY BASE64: user commands legitimately contain newlines (function
        # definitions, heredoc-ish blocks).  Embedding them literally would
        # split them across the parser's command boundaries again, so the user
        # text travels as base64 and is rebuilt into a ScriptBlock.
        user_b64 = base64.b64encode(command.encode("utf-8", errors="replace")).decode("ascii")
        rc_file = protocol.rc_file_path
        err_file = protocol.err_file_path
        cwd_file = protocol.cwd_file_path

        loc_ok = "$__rxy_ok = $true"
        if workdir:
            set_loc = (
                "$__rxy_prev = (Get-Location).Path; "
                "try { Set-Location -LiteralPath "
                + _ps_quote(workdir)
                + " -ErrorAction Stop } catch { $__rxy_ok = $false }"
            )
        else:
            set_loc = "$__rxy_prev = $null"

        # Runs the user command, captures its OWN exit status and error text.
        run_body = (
            "$__rxy_err = $null; "
            "$__rxy_rc = 0; "
            "$global:LASTEXITCODE = $null; "
            # $Error accumulates across the whole session; clear it so a
            # PREVIOUS command's error cannot fail this one.
            "$Error.Clear(); "
            "try { "
            # DOT-SOURCE, not '&': dot-sourcing runs the block in the session
            # scope, so variables/functions the command defines survive into
            # the next call.  Calling it with '&' silently made every
            # assignment local, which is what lost state in the audit.
            # Output is captured with a pipeline (not '*>'), because '*>'
            # redirects the dot-source stream itself and swallowed output.
            # '6>&1' also folds the information stream in, so Write-Host
            # output (including -NoNewline) is captured instead of bypassing
            # the pipeline straight to the console.
            "(. $__rxy_sb) 6>&1 | Out-File -FilePath "
            + _ps_quote(protocol.out_file_path)
            + " -Encoding utf8; "
            # A native command sets $LASTEXITCODE; a cmdlet does not.  Treat
            # "no native command ran" as success only if no error was recorded.
            "if ($null -ne $LASTEXITCODE) { $__rxy_rc = $LASTEXITCODE } "
            "if ($Error.Count -gt 0) { "
            "$__rxy_err = $Error[0].ToString(); "
            "if ($__rxy_rc -eq 0) { $__rxy_rc = 1 } } "
            "} catch { $__rxy_rc = 1; $__rxy_err = $_.Exception.Message }"
        )

        restore = (
            "if ($__rxy_prev) { Set-Location -LiteralPath $__rxy_prev "
            "-ErrorAction SilentlyContinue }; "
            if workdir
            else ""
        )

        # Success path: run, restore, record rc/err/cwd, emit END.
        success_path = (
            run_body
            + "; Set-Content -LiteralPath "
            + _ps_quote(rc_file)
            + " -Value ([string]$__rxy_rc) -Encoding utf8; "
            + "if ($__rxy_err) { Set-Content -LiteralPath "
            + _ps_quote(err_file)
            + " -Value ([string]$__rxy_err) -Encoding utf8 }; "
            + restore
            + "Set-Content -LiteralPath "
            + _ps_quote(cwd_file)
            + " -Value ([string](Get-Location).Path) -Encoding utf8"
        )
        fail_path = (
            "Set-Content -LiteralPath "
            + _ps_quote(rc_file)
            + " -Value '126' -Encoding utf8; "
            + "Set-Content -LiteralPath "
            + _ps_quote(err_file)
            + " -Value 'workdir_failed' -Encoding utf8; "
            + "Set-Content -LiteralPath "
            + _ps_quote(cwd_file)
            + " -Value ([string]$__rxy_prev) -Encoding utf8"
        )

        statement = (
            "$__rxy_sb = [ScriptBlock]::Create("
            "[Text.Encoding]::UTF8.GetString([Convert]::FromBase64String("
            + _ps_quote(user_b64)
            + "))); "
            + loc_ok
            + "; "
            + set_loc
            + "; if ($__rxy_ok) { "
            + success_path
            + " } else { "
            + fail_path
            + " }"
        )
        # BEGIN must be flushed before the statement runs so a crash inside the
        # statement still leaves the reader in "collecting" state.  The END
        # marker is written on its own statement line, so a command whose last
        # output has no trailing newline cannot glue itself to the marker.
        return (
            "Write-Output " + _ps_quote(protocol.begin) + "\n"
            + statement + "\n"
            + "Write-Output " + _ps_quote(protocol.end + " done") + "\n"
        )

    if cmd_shell:
        # cmd.exe has no functions/venv story worth preserving; keep it simple.
        parts = [f"echo {protocol.begin}"]
        if workdir:
            quoted = workdir.replace('"', '""')
            parts.append(
                f'cd /d "{quoted}" || (echo {protocol.end} workdir_failed & exit /b 126)'
            )
        parts.append(command)
        parts.append(f"echo {protocol.end} rc=%ERRORLEVEL%")
        parts.append("cd")
        return "\r\n".join(parts) + "\r\n"

    # POSIX: scope only the directory; never a subshell (variables must live).
    rc_file = shlex.quote(protocol.rc_file_path)
    err_file = shlex.quote(protocol.err_file_path)
    cwd_file = shlex.quote(protocol.cwd_file_path)
    parts = [f"printf '%s\\n' '{protocol.begin}'"]
    if workdir:
        parts.append("__rxy_prev=$PWD")
        parts.append(
            f"if ! cd {shlex.quote(workdir)} 2>/dev/null; then "
            f"printf '126' > {rc_file}; "
            f"printf 'workdir_failed' > {err_file}; "
            f"printf '%s' \"$__rxy_prev\" > {cwd_file}; "
            f"printf '%s\\n' '{protocol.end} done'; exit 0; fi"
        )
    parts.append(command)
    parts.append("__rxy_rc=$?")
    parts.append(f"printf '%s' \"$__rxy_rc\" > {rc_file}")
    if workdir:
        parts.append('[ -n "$__rxy_prev" ] && cd "$__rxy_prev" 2>/dev/null')
    parts.append(f"printf '%s' \"$PWD\" > {cwd_file}")
    # The END marker is preceded by a newline so a command whose last output
    # has no trailing newline cannot glue itself to the marker (audit P2-03).
    parts.append(f"printf '\\n%s\\n' '{protocol.end} done'")
    return "\n".join(parts) + "\n"


# ---------------------------------------------------------------------------
# Sandbox plan
# ---------------------------------------------------------------------------

@dataclass
class ShellSandboxPlan:
    """Everything the sandbox layer produced for one shell spawn.

    Audit P1-01: the first implementation received only the wrapped argv and
    silently dropped the rest of the plan -- the Windows Job (memory/process
    caps, kill-on-close), the resource policy, and the temp-file cleanup list.
    Carrying the whole plan is what makes the persistent shell as constrained
    as a one-shot command.
    """

    argv: list[str]
    #: ``core.sandbox.types.WrappedCommand`` when OS wrapping applied.
    wrapped: Any = None
    #: ``utils.shell._ExecutionPolicy`` -- source of memory/process limits.
    policy: Any = None
    #: Temp files the sandbox backend created (e.g. a macOS seatbelt profile).
    cleanup: tuple[Any, ...] = ()
    backend: str = "none"
    downgraded: bool = False
    detail: str = ""


# ---------------------------------------------------------------------------
# ManagedShell
# ---------------------------------------------------------------------------

class ManagedShell:
    """One long-lived shell process bound to a single state identity."""

    def __init__(
        self,
        *,
        identity: str,
        cwd: str,
        argv: list[str] | None = None,
        env: dict[str, str] | None = None,
        sandbox_command: Any | None = None,
    ) -> None:
        self.identity = identity
        self.argv = argv or default_shell_argv()
        self._powershell = _is_powershell(self.argv)
        self._cmd = _is_cmd(self.argv)
        self._initial_cwd = cwd
        self._env = env
        self._sandbox_command = sandbox_command
        self._process_registration_key = secrets.token_hex(32)
        self._process: asyncio.subprocess.Process | None = None
        #: The event loop that spawned the process.  asyncio transports and
        #: StreamReaders bind to it forever; a shell reused from another loop
        #: (a fresh pytest-asyncio loop, a second worker loop) fails deep in
        #: ``stdout.read`` with "Future attached to a different loop".
        self._loop: asyncio.AbstractEventLoop | None = None
        self._lock = asyncio.Lock()
        self._start_lock = asyncio.Lock()
        self._closed = False
        self.confirmed_cwd: str | None = None
        self._stderr_task: asyncio.Task | None = None
        self._stderr_buffer: list[str] = []
        #: Windows Job handle: kept for the shell's whole lifetime so the job
        #: (and its kill-on-close) covers every descendant.
        self._job_handle: int = 0
        #: Resource-limit watcher (memory / process count).
        self._monitor_task: asyncio.Task | None = None
        #: Set when the sandbox killed the shell for exceeding a limit.
        self.violation: str = ""
        #: Temp files the sandbox backend created for THIS spawn (e.g. a macOS
        #: seatbelt profile).  Audit P2 (round 4): this was carried in the plan
        #: but never consumed, so the files survived shell shutdown.  They are
        #: removed on close, on startup failure and on cancellation.
        self._sandbox_cleanup: tuple[Any, ...] = ()
        #: Temp files belonging to a command that has not reported back yet.
        #: Cleared on a normal trailer; swept on close() so a cancelled or
        #: killed command cannot leave one file per call in the workspace.
        self._pending_artifacts: list[str] = []

    # -- lifecycle ------------------------------------------------------

    def _loop_is_foreign(self) -> bool:
        """True when the process belongs to a different (possibly dead) loop."""
        if self._loop is None:
            return False
        try:
            return asyncio.get_running_loop() is not self._loop
        except RuntimeError:
            # No running loop: any async use would bind wrong — treat foreign.
            return True

    @property
    def alive(self) -> bool:
        return (
            not self._closed
            and self._process is not None
            and self._process.returncode is None
        )

    @property
    def pid(self) -> int | None:
        return self._process.pid if self._process is not None else None

    @property
    def started(self) -> bool:
        return self._process is not None

    async def ensure_started(self) -> None:
        """Start the process exactly once, even under concurrent callers."""
        async with self._start_lock:
            if self._closed:
                raise ShellLostError("managed shell was closed")
            if self._process is not None and self._process.returncode is None:
                return
            await self._spawn()

    async def _spawn(self) -> None:
        cwd = self._initial_cwd or None
        if cwd and not Path(cwd).is_dir():
            cwd = None

        spawn_argv = list(self.argv)
        try:
            spawn_argv = shell_module.wrap_process_argv(
                spawn_argv,
                process_key=self._process_registration_key,
            )
        except Exception:
            pass
        plan = ShellSandboxPlan(argv=spawn_argv)
        if self._sandbox_command is not None:
            # Reuse ShellExecutor's sandbox/policy wrapping so the persistent
            # shell is protected exactly like a one-shot command.
            try:
                plan = self._sandbox_command(list(spawn_argv), cwd)
            except Exception as exc:
                raise ShellStartupError(
                    f"sandbox refused to wrap the managed shell: {exc}",
                    sandbox_refused=True,
                ) from exc
            if not isinstance(plan, ShellSandboxPlan):  # defensive
                plan = ShellSandboxPlan(argv=list(plan))

        argv = list(plan.argv)
        env = dict(self._env or os.environ)
        if self._powershell:
            # Deterministic UTF-8 in both directions; see the encoding note in
            # docs/modules/core.md.
            env["PYTHONIOENCODING"] = "utf-8"
            env.setdefault("POWERSHELL_TELEMETRY_OPTOUT", "1")

        kwargs = self._process_kwargs()
        # Windows Job must be bound BEFORE the shell runs any code, otherwise
        # descendants it spawns first escape the memory/process caps.  Mirror
        # the one-shot path: open an empty job, spawn suspended, assign, resume.
        job_handle = 0
        wrapped = plan.wrapped
        if wrapped is not None and getattr(wrapped, "job_plan", None) is not None:
            try:
                job_handle = sandbox_manager.open_sandbox_job(wrapped)
            except Exception as exc:
                raise ShellStartupError(
                    f"sandbox job could not be created: {exc}",
                    sandbox_refused=True,
                ) from exc

        if sys.platform == "win32" and not job_handle:
            # Audit P1-06: reliable tree ownership must NOT depend on the OS
            # sandbox being enabled.  A plain kill-on-close Job means the
            # shell's whole descendant tree dies with it even when the root has
            # already exited (Windows drops the parent link on exit, so
            # ppid-walking and `taskkill /T` both miss orphans).
            try:
                from .sandbox.windows import _create_job

                job_handle = _create_job(JobPlan(kill_on_close=True))
            except Exception:
                job_handle = 0

        if job_handle:
            # CREATE_SUSPENDED (winbase.h) has no subprocess constant.
            kwargs["creationflags"] = kwargs.get("creationflags", 0) | 0x00000004

        # Audit P2 (round 4): a cancellation while awaiting spawn/bind used to
        # leak the Job handle, because only the success path recorded it.  The
        # handle is owned by this local from the moment it exists, and every
        # exit path below releases it.
        try:
            self._loop = asyncio.get_running_loop()
            try:
                self._process = await asyncio.create_subprocess_exec(
                    *argv,
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=cwd,
                    env=env,
                    **kwargs,
                )
            except (OSError, ValueError) as exc:
                raise ShellStartupError(f"could not start {argv[0]}: {exc}") from exc

            if job_handle:
                try:
                    sandbox_manager.bind_spawned_process(
                        job_handle, self._process.pid
                    )
                except Exception as exc:
                    # Fail closed: the suspended root never ran, so killing it
                    # reaps the whole (still empty) tree.
                    await _terminate_process_tree(self._process)
                    self._process = None
                    raise ShellStartupError(
                        f"sandbox could not bind the managed shell: {exc}",
                        sandbox_refused=True,
                    ) from exc
            # Ownership transferred: close() is responsible from here on.
            self._job_handle = job_handle
            job_handle = 0
            # The sandbox's temp files belong to this live shell now; close()
            # removes them.
            self._sandbox_cleanup = tuple(plan.cleanup or ())
        finally:
            if job_handle:
                _close_sandbox_job(job_handle)
            if self._process is None:
                # Startup failed: nothing owns the sandbox temp files yet.
                _remove_sandbox_cleanup(plan.cleanup)

        self.confirmed_cwd = cwd or os.getcwd()
        # PowerShell writes decoding errors to stderr; drain it so the process
        # never blocks on a full stderr pipe.
        if self._process.stderr is not None:
            self._stderr_task = asyncio.create_task(self._drain_stderr())

        # Apply the resource limits (memory / process count) to the shell and
        # everything it spawns.  The one-shot path does this per command; a
        # persistent shell must do it once for its lifetime.
        policy = plan.policy
        if policy is not None and (
            getattr(policy, "max_memory_mb", 0) or getattr(policy, "max_processes", 0)
        ):
            self._monitor_task = asyncio.create_task(self._watch_limits(policy))

        if self._powershell:
            # Force UTF-8 output regardless of the console code page.
            self._process.stdin.write(
                b"$OutputEncoding = [Console]::OutputEncoding = "
                b"[System.Text.UTF8Encoding]::new($false)\n"
            )
            await self._process.stdin.drain()

    @staticmethod
    def _process_kwargs() -> dict[str, Any]:
        kwargs: dict[str, Any] = {}
        if sys.platform == "win32":
            kwargs["creationflags"] = getattr(
                subprocess, "CREATE_NEW_PROCESS_GROUP", 0
            )
        else:
            kwargs["start_new_session"] = True
        return kwargs

    async def _drain_stderr(self) -> None:
        process = self._process
        if process is None or process.stderr is None:
            return
        try:
            while True:
                chunk = await process.stderr.read(READ_CHUNK)
                if not chunk:
                    return
                text = chunk.decode("utf-8", errors="replace")
                self._stderr_buffer.append(text)
                if len(self._stderr_buffer) > 64:
                    del self._stderr_buffer[:32]
        except (asyncio.CancelledError, OSError):
            return

    async def _watch_limits(self, policy: Any) -> None:
        """Kill the shell if it exceeds the configured memory/process limits.

        Reuses ``ShellExecutor``'s sampler so the persistent shell obeys the
        same limits a one-shot command would (audit P1-01).
        """
        process = self._process
        if process is None:
            return
        try:
            from ..utils.shell import shell_executor

            violation = await shell_executor._monitor_process_tree(process, policy)
        except asyncio.CancelledError:
            return
        except Exception:
            return
        if violation is None:
            return
        message = str(getattr(violation, "message", violation))
        self.violation = message
        self._closed = True
        await _terminate_process_tree(process)

    async def close(self) -> None:
        """Terminate the shell and its whole process tree.  Idempotent."""
        self._closed = True
        registration_key = self._process_registration_key
        self._process_registration_key = ""
        if registration_key:
            try:
                cleanup = asyncio.create_task(
                    shell_module.release_process_observation(registration_key)
                )

                def consume_cleanup(task: asyncio.Task[Any]) -> None:
                    if not task.cancelled():
                        task.exception()

                cleanup.add_done_callback(consume_cleanup)
            except Exception:
                pass
        process = self._process
        self._process = None
        if self._stderr_task is not None:
            try:
                self._stderr_task.cancel()
            except RuntimeError:
                # Task belongs to a loop that is already closed.
                pass
            self._stderr_task = None
        if self._monitor_task is not None:
            try:
                self._monitor_task.cancel()
            except RuntimeError:
                pass
            self._monitor_task = None
        # A cancelled/killed command never reaches the normal trailer, so its
        # temp files would otherwise leak into the workspace one per command.
        for path in self._pending_artifacts:
            try:
                Path(path).unlink(missing_ok=True)
            except OSError:
                pass
        self._pending_artifacts.clear()
        # Audit P2 (round 4): the sandbox's per-spawn temp files were never
        # removed, so they outlived the shell that owned them.
        if self._sandbox_cleanup:
            _remove_sandbox_cleanup(self._sandbox_cleanup)
            self._sandbox_cleanup = ()
        if process is None:
            if self._job_handle:
                _close_sandbox_job(self._job_handle)
                self._job_handle = 0
            return
        await _terminate_process_tree(process)
        # Closing the Job handle after the tree is gone is what guarantees
        # kill-on-close semantics for anything that outlived the root.
        if self._job_handle:
            _close_sandbox_job(self._job_handle)
            self._job_handle = 0
        for stream in (process.stdin, process.stdout, process.stderr):
            if stream is None:
                continue
            try:
                if not stream.is_closing():
                    stream.close()
            except (OSError, RuntimeError, AttributeError):
                pass

    def _query_cwd(self, protocol: _MarkerProtocol) -> str | None:
        """Read the directory the shell itself reported for this command."""
        text = _read_and_remove(protocol.cwd_file_path)
        if not text:
            return None
        candidate = text.strip()
        try:
            if candidate and Path(candidate).is_dir():
                return candidate
        except OSError:
            return None
        # Report it anyway when it exists but cannot be inspected; the caller
        # decides whether to commit.
        return candidate or None

    def take_stderr(self) -> str:
        """Return and clear buffered stderr text from the shell itself."""
        text = "".join(self._stderr_buffer)
        self._stderr_buffer.clear()
        return text

    # -- command execution ---------------------------------------------

    async def run(
        self,
        command: str,
        *,
        timeout: float = DEFAULT_COMMAND_TIMEOUT,
        workdir: str = "",
        capture: Any = None,
    ) -> CommandOutcome:
        """Run one command, serialized against other commands on this shell.

        ``capture`` (a ``BoundedOutputCapture``) receives output AS IT ARRIVES.
        Audit P2-04: the first version accumulated a capped string here and
        only then handed it to the capture, so the spill artifact held a
        pre-truncated copy instead of the complete output.  Streaming straight
        into the shared capture keeps one truncation point and one artifact.
        """
        if self._closed:
            raise ShellLostError("managed shell was closed")
        if self._loop_is_foreign():
            # The registry should have evicted this shell before it reached
            # run(); a direct caller hit it anyway — mark it lost so the next
            # acquire respawns on this loop.
            self._closed = True
            raise ShellLostError(
                "managed shell belongs to a different event loop"
            )
        async with self._lock:
            await self.ensure_started()
            try:
                if timeout and timeout > 0:
                    return await asyncio.wait_for(
                        self._run_locked(
                            command, timeout=timeout, workdir=workdir, capture=capture
                        ),
                        timeout=timeout + 5.0,
                    )
                return await self._run_locked(
                    command, timeout=timeout, workdir=workdir, capture=capture
                )
            except asyncio.TimeoutError:
                # The command is still inside the shell; its stream position is
                # unknown, so this shell can never be trusted again.
                self._closed = True
                await self.close()
                raise ShellLostError(
                    f"command exceeded the {timeout}s cap and was abandoned"
                ) from None
            except asyncio.CancelledError:
                # Cancellation MUST stop the tree, not just the reader.
                self._closed = True
                await self.close()
                raise
            except ShellLostError:
                await self.close()
                raise

    async def _run_locked(
        self,
        command: str,
        *,
        timeout: float,
        workdir: str,
        capture: Any = None,
    ) -> CommandOutcome:
        process = self._process
        if process is None or process.stdin is None or process.stdout is None:
            raise ShellLostError("managed shell has no usable stdio pipes")
        if process.returncode is not None:
            raise ShellLostError(
                f"managed shell exited with code {process.returncode}"
            )

        # The initial controlled workspace is visible to the sandbox. Neither
        # the host process cwd nor a one-call workdir is a safe protocol root.
        protocol = _marker_protocol(self._initial_cwd)
        payload = _build_wrapped_command(
            command,
            protocol,
            powershell=self._powershell,
            workdir=workdir,
            cmd_shell=self._cmd,
        )
        # Register before running: if this command is cancelled or the shell
        # dies, close() must still be able to sweep its temp files.
        self._pending_artifacts = _protocol_files(protocol)

        try:
            process.stdin.write(payload.encode("utf-8", errors="replace"))
            await process.stdin.drain()
        except (BrokenPipeError, ConnectionResetError, OSError) as exc:
            self._closed = True
            raise ShellLostError("managed shell pipe closed") from exc

        result = await self._collect(
            process,
            protocol,
            timeout=timeout,
            capture=capture,
        )
        # A completed command already consumed its files.
        self._pending_artifacts = []
        if result.cwd_after:
            self.confirmed_cwd = result.cwd_after
        return result

    async def _collect(
        self,
        process: asyncio.subprocess.Process,
        protocol: _MarkerProtocol,
        capture: Any = None,
        *,
        timeout: float = DEFAULT_COMMAND_TIMEOUT,
    ) -> CommandOutcome:
        """Read until the end marker, streaming payload into ``capture``.

        Marker detection is byte-oriented and independent of newlines (audit
        P2-03): a command whose last line lacks a trailing newline used to glue
        itself to the trailer and hang until timeout.  Payload is fed to the
        shared ``BoundedOutputCapture`` as it arrives (audit P2-04), so the
        spill artifact holds the complete output instead of a pre-truncated
        copy, and there is exactly one truncation point.
        """
        assert process.stdout is not None
        decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        buf = ""
        chunks: list[str] = []
        emitted = 0
        truncated = False
        state = "before_begin"
        begin_marker = protocol.begin
        end_marker = protocol.end
        started = time.monotonic()
        deadlines = shell_module.process_probe_deadlines(
            started,
            timeout,
            getattr(
                shell_module.shell_executor,
                "watchdog_checkpoints",
                shell_module.WATCHDOG_CHECKPOINTS,
            ),
        )
        pending_read: asyncio.Task[bytes] | None = None
        probe_task: asyncio.Task[Any] | None = None
        command_done = asyncio.Event()

        def emit(text: str) -> None:
            nonlocal emitted, truncated
            if not text:
                return
            if capture is not None:
                try:
                    capture.feed("stdout", text.encode("utf-8", errors="replace"))
                except Exception:
                    pass
            else:
                if emitted < MAX_CAPTURE_BYTES:
                    chunks.append(text)
                else:
                    truncated = True
            emitted += len(text)

        try:
            while True:
                if probe_task is not None and probe_task.done():
                    probe = await probe_task
                    probe_task = None
                    if probe is not None and probe.action == "stop":
                        raise ShellLivenessStop(probe.note)
                now = time.monotonic()
                if (
                    probe_task is None
                    and deadlines
                    and now + 0.05 >= deadlines[0]
                ):
                    deadlines.pop(0)
                    probe_task = asyncio.create_task(
                        shell_module.run_process_probe(
                            process.pid,
                            elapsed_seconds=now - started,
                            completion=command_done,
                            process_key=self._process_registration_key,
                        )
                    )
                if pending_read is None:
                    pending_read = asyncio.create_task(
                        process.stdout.read(READ_CHUNK)
                    )
                wait_timeout = None
                if deadlines and probe_task is None:
                    wait_timeout = max(0.0, deadlines[0] - time.monotonic())
                waiters: set[asyncio.Future[Any]] = {pending_read}
                if probe_task is not None:
                    waiters.add(probe_task)
                done, _ = await asyncio.wait(
                    waiters,
                    timeout=wait_timeout,
                    return_when=asyncio.FIRST_COMPLETED,
                )
                if not done:
                    continue
                if pending_read not in done:
                    # A probe task completed while stdin/stdout stayed open.
                    # Handle its verdict at the top of the next iteration.
                    continue
                raw = pending_read.result()
                pending_read = None
                if not raw:
                    if state == "done":
                        break
                    if state == "collecting":
                        # The retained tail is payload now, not a split END marker.
                        emit(buf + decoder.decode(b"", final=True))
                    # stdout EOF alone is not proof of process exit. Reap through
                    # the existing command timeout/cancellation boundary, before
                    # close() can replace natural exit evidence with our own kill.
                    if process.returncode is None:
                        await process.wait()
                    if self._powershell:
                        truncated = (
                            _feed_file(protocol.out_file_path, capture, chunks)
                            or truncated
                        )
                    raise ShellLostError(
                        "managed shell exited before the command reported completion",
                        exit_code=process.returncode if state == "collecting" else None,
                        stdout="" if capture is not None else "".join(chunks),
                        truncated=truncated,
                    )
                buf += decoder.decode(raw)

                if state == "before_begin":
                    idx = buf.find(begin_marker)
                    if idx == -1:
                        # Keep only enough tail to catch a marker split across reads.
                        keep = len(begin_marker) - 1
                        if len(buf) > keep:
                            buf = buf[-keep:] if keep else ""
                        continue
                    buf = buf[idx + len(begin_marker) :]
                    state = "collecting"
                    # Drop the newline the wrapper wrote after BEGIN.
                    if buf.startswith("\r\n"):
                        buf = buf[2:]
                    elif buf.startswith("\n"):
                        buf = buf[1:]

                if state == "collecting":
                    idx = buf.find(end_marker)
                    if idx == -1:
                        # Emit everything except a tail that could be a partial
                        # marker; this keeps memory bounded without losing bytes.
                        keep = len(end_marker) - 1
                        if len(buf) > keep:
                            emit(buf[:-keep] if keep else buf)
                            buf = buf[-keep:] if keep else ""
                        continue
                    emit(buf[:idx])
                    buf = buf[idx + len(end_marker) :]
                    state = "done"
                    command_done.set()
                    break
        finally:
            command_done.set()
            if probe_task is not None and not probe_task.done():
                probe_task.cancel()
            if probe_task is not None:
                await asyncio.gather(probe_task, return_exceptions=True)
            if pending_read is not None and not pending_read.done():
                pending_read.cancel()
                await asyncio.gather(pending_read, return_exceptions=True)

        # Exit status and error text come from the temp files the wrapper
        # wrote, not from parsing interleaved console output.
        exit_code = _read_int_file(protocol.rc_file_path)
        stderr_errors = _read_and_remove(protocol.err_file_path) or ""
        cwd_after = self._query_cwd(protocol)
        if self._powershell:
            # PowerShell mixes the echoed input and cmdlet records into the
            # console stream, so its real output is taken from the file the
            # wrapper wrote.  Stream that file into the same capture.
            file_truncated = _feed_file(protocol.out_file_path, capture, chunks)
            truncated = truncated or file_truncated

        if stderr_errors.strip() == "workdir_failed":
            return CommandOutcome(
                stdout="",
                exit_code=126,
                cwd_after=cwd_after,
                error="workdir could not be entered; the command was NOT run",
            )
        return CommandOutcome(
            stdout="" if capture is not None else "".join(chunks),
            exit_code=exit_code,
            cwd_after=cwd_after,
            truncated=truncated,
            stderr_errors=stderr_errors.strip(),
        )


# ---------------------------------------------------------------------------
# Process tree termination (shared with lifecycle)
# ---------------------------------------------------------------------------

def _optional_psutil():
    """Load the optional process dependency only when tree inspection runs."""
    try:
        import psutil
    except Exception:  # pragma: no cover - psutil is a hard dependency
        return None
    return psutil


def _collect_descendants(root_pid: int) -> list[int]:
    """Every live descendant of ``root_pid``, found by walking parent links.

    Called BEFORE the root is killed.  Windows keeps a process's parent PID
    after the parent exits, so this also finds children orphaned when the root
    died first (audit P1-06) -- ``taskkill /T`` alone cannot.
    """
    psutil = _optional_psutil()
    if psutil is None:
        return []
    try:
        pairs = [
            (proc.info.get("pid"), proc.info.get("ppid"))
            for proc in psutil.process_iter(["pid", "ppid"])
        ]
    except Exception:
        return []
    by_parent: dict[int, list[int]] = {}
    for child_pid, parent_pid in pairs:
        if child_pid is None or parent_pid is None:
            continue
        by_parent.setdefault(int(parent_pid), []).append(int(child_pid))
    found: list[int] = []
    seen: set[int] = set()
    stack = [int(root_pid)]
    while stack:
        current = stack.pop()
        for child in by_parent.get(current, ()):
            if child in seen:
                continue
            seen.add(child)
            found.append(child)
            stack.append(child)
    return found


async def _terminate_process_tree(process: asyncio.subprocess.Process) -> None:
    """Kill a process AND every descendant, then wait for the root to exit.

    Audit P1-06: the first version returned immediately when the root had
    already exited, so descendants it had spawned kept running (the classic
    "shell exited, children orphaned" leak).  Tree ownership must be enforced
    whether or not the root is still alive; only the *reaping* of the root is
    skipped in that case.

    Boundaries: on Windows this uses ``taskkill /T`` because the sandbox Job is
    owned by the sandbox layer, not by this module; on POSIX it signals the
    process group created by ``start_new_session``.  Neither is a security
    boundary -- the sandbox/policy gate still decides what may run.
    """
    pid = process.pid
    # Snapshot descendants FIRST: once the root dies Windows loses nothing, but
    # a group leader that exits can make a later group kill a no-op, and the
    # sandbox Job may be absent when the policy is disabled.
    descendants = _collect_descendants(pid)
    # Always attempt the tree kill.  ``taskkill /T`` and ``killpg`` both work
    # on a dead root's surviving descendants when the tree is still known.
    if sys.platform == "win32":
        try:
            killer = await asyncio.create_subprocess_exec(
                "taskkill",
                "/F",
                "/T",
                "/PID",
                str(pid),
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await asyncio.wait_for(killer.wait(), timeout=10)
        except (OSError, asyncio.TimeoutError):
            pass
    else:
        try:
            os.killpg(os.getpgid(pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError, OSError):
            pass

    if process.returncode is not None:
        # Root already reaped; the descendants snapshot is the only handle on
        # what it left behind, so it MUST be killed explicitly here.
        _kill_pids(descendants)
        return
    try:
        process.kill()
    except (ProcessLookupError, OSError):
        pass
    try:
        await asyncio.wait_for(process.wait(), timeout=10)
    except RuntimeError:
        # The process's transport belongs to another (usually dead) event
        # loop — wait() cannot run here. The kill above already fired; the
        # pid sweep below covers survivors.
        pass
    except asyncio.TimeoutError:
        _logger.warning("managed shell pid=%s did not exit after kill", pid)
    # Sweep anything that outlived the tree kill (e.g. a grandchild that
    # re-parented itself during shutdown).
    _kill_pids(descendants)


def _kill_pids(pids: list[int]) -> None:
    """Best-effort kill of already-identified descendant PIDs."""
    if not pids:
        return
    psutil = _optional_psutil()
    if psutil is None:
        return
    for target in pids:
        try:
            proc = psutil.Process(target)
            proc.kill()
        except Exception:
            continue


def _close_sandbox_job(handle: int) -> None:
    """Close a Windows Job handle, which also kills anything still inside it."""
    if not handle:
        return
    try:
        from .sandbox.windows import _close_handle

        _close_handle(handle)
    except Exception:
        # Non-Windows hosts (or a job that was never created) are not an error.
        pass


def _remove_sandbox_cleanup(leftovers: Any) -> None:
    """Delete temp files a sandbox backend created for one spawn.

    Audit P2 (round 4): ``ShellSandboxPlan.cleanup`` was produced and carried
    but never consumed, so every managed spawn on a backend that materialises
    a profile file (macOS seatbelt) leaked one file per shell.  The one-shot
    path already does this in ``utils.shell``; mirror it here.  Best-effort:
    a leftover we cannot remove must never mask the original error.
    """
    for leftover in leftovers or ():
        try:
            Path(leftover).unlink(missing_ok=True)
        except (OSError, TypeError, ValueError):
            pass


# ---------------------------------------------------------------------------
# Registry: identity -> shell (lazy, per-identity, concurrency-safe)
# ---------------------------------------------------------------------------

#: All shells by identity, including NOT-YET-STARTED ones.  Keeping pending
#: entries is what makes one identity mean one shell under concurrent first
#: use (the audit caught two PIDs for one session).
_SHELLS: dict[str, ManagedShell] = {}
#: ``threading.Lock``, not ``asyncio.Lock`` — an asyncio lock binds to the
#: first loop that awaits it, and shells outlive individual loops (each
#: pytest-asyncio test, each worker task gets a fresh loop).  The critical
#: sections are synchronous dict mutations only; any ``close()`` is awaited
#: AFTER the lock is released.
_REGISTRY_LOCK = threading.Lock()
#: Identities whose shell is currently being started.
_STARTING: set[str] = set()


def state_identity(
    *,
    session_id: str | None = None,
    isolation: str | None = None,
) -> str:
    """Build the state identity for a shell.

    Derived from the TRUSTED session binding, never caller text.  ``isolation``
    separates parallel/sub-agent work that must not share mutable state while
    still starting in the same approved directory.
    """
    if session_id is None:
        session_id = current_session_id()
    base = str(session_id or "latest")
    if isolation:
        return f"{base}::{isolation}"
    return base


async def acquire_shell(
    *,
    identity: str,
    cwd: str,
    argv: list[str] | None = None,
    env: dict[str, str] | None = None,
    sandbox_command: Any | None = None,
) -> ManagedShell:
    """Return the shell for ``identity``, creating it on first use.

    The registry entry is created under the lock BEFORE any await, so two
    concurrent first callers always observe the same object.  The eviction
    ``close()`` is awaited after the lock is released — it may target a
    shell owned by a dead loop, which must not serialize into the lock.
    """
    evict: ManagedShell | None = None
    with _REGISTRY_LOCK:
        existing = _SHELLS.get(identity)
        if (
            existing is not None
            and not existing._closed
            and not existing._loop_is_foreign()
        ):
            return existing
        if existing is not None:
            _SHELLS.pop(identity, None)
            evict = existing
        shell = ManagedShell(
            identity=identity,
            cwd=cwd,
            argv=argv,
            env=env,
            sandbox_command=sandbox_command,
        )
        # Registered before returning: a second caller sees this instance even
        # though it has not spawned yet.
        _SHELLS[identity] = shell
    if evict is not None:
        try:
            await evict.close()
        except Exception:
            pass
    return shell


async def release_shell(identity: str) -> bool:
    with _REGISTRY_LOCK:
        shell = _SHELLS.pop(identity, None)
    if shell is None:
        return False
    try:
        await shell.close()
    except Exception:
        pass
    return True


async def release_all() -> int:
    with _REGISTRY_LOCK:
        shells = list(_SHELLS.values())
        _SHELLS.clear()
    for shell in shells:
        try:
            await shell.close()
        except Exception:
            pass
    return len(shells)


def active_identities() -> list[str]:
    """Identities holding a shell object (started or pending)."""
    with _REGISTRY_LOCK:
        return [name for name, shell in _SHELLS.items() if not shell._closed]


def started_identities() -> list[str]:
    """Identities whose shell process is actually running."""
    with _REGISTRY_LOCK:
        return [name for name, shell in _SHELLS.items() if shell.alive]


def invalidate_session_sync(session_id: str) -> list["ManagedShell"]:
    """Remove and close-mark one session's shells WITHOUT awaiting.

    Callers are synchronous (``clear_session_runtime``, subagent
    ``shutdown()``), but the registry must stop handing out the old shell
    before they return: a command issued immediately afterwards must not reuse
    the previous environment (audit P2-01).  The removed shells are returned so
    the caller can hand them to :func:`close_shells` for process reaping.
    """
    base = str(session_id or "")
    if not base:
        return []
    prefix = f"{base}::"
    doomed: list[ManagedShell] = []
    # threading.Lock is safe here too: no awaits inside, works with or
    # without a running loop.
    with _REGISTRY_LOCK:
        for name in [
            n for n in list(_SHELLS) if n == base or n.startswith(prefix)
        ]:
            shell = _SHELLS.pop(name, None)
            if shell is None:
                continue
            shell._closed = True
            doomed.append(shell)
    return doomed


async def close_shells(shells: list["ManagedShell"]) -> None:
    """Reap shells produced by :func:`invalidate_session_sync`."""
    for shell in shells:
        try:
            await shell.close()
        except Exception:
            pass


async def release_for_session(session_id: str) -> int:
    """Close every shell owned by one session (sync invalidation + reap)."""
    shells = invalidate_session_sync(session_id)
    await close_shells(shells)
    return len(shells)
