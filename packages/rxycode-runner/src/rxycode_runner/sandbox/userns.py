"""In-container user-namespace sandbox for the shared drain worker.

The compose worker must isolate tenant turns without a docker socket
(W5-C02 forbids exposing it). On a Linux runtime that permits unprivileged
user namespaces — inside a container that needs ``seccomp=unconfined`` for
``unshare``/``mount`` — ``bubblewrap`` gives a real kernel boundary:

* ``--unshare-user --uid 0 --gid 0`` remaps the caller to a private uid map;
  host identity outside the map is a different, unprivileged user.
* ``--unshare-pid`` gives the turn its own PID namespace; killing the bwrap
  supervisor (or the namespace init dying) SIGKILLs the whole tree —
  ``--die-with-parent`` additionally reaps the child if the drain dies.
* Only the mounts listed are visible: system paths read-only, the run's own
  workspace read-write, a private tmpfs ``/tmp``. Sibling workspaces and the
  worker's data dir are simply not mounted.
* ``--clearenv`` + an explicit ``--setenv`` passlist decides which
  environment reaches the turn; nothing else is inherited.
* The network namespace is intentionally NOT unshared: the turn must reach
  Postgres (journal/steer commands) and the configured LLM endpoint over
  the compose network. Egress policy is the egress.py seam, not this layer.

This is the execution boundary the public stack calls its cloud sandbox:
every accepted target (``cloud:{tenant}:{workspace}``) is created through
``UsernsSandboxProvider.create`` bound to its tenant and executed confined.
A host where bwrap/userns is unavailable makes ``available()`` return
False and callers fail closed — nothing ever falls back to running the
turn on the worker host.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any, Mapping, Sequence

from .provider import AttachRefused, ExecResult, IsolationUnavailable, SandboxHandle

RUNTIME = "userns-bwrap"

# System paths shared read-only into the confined root. Only paths that
# exist are bound; the list is a superset for distro variance. ``/usr/local``
# is separate from ``/usr`` on Debian-slim images — that is where the Python
# interpreter and its site-packages actually live.
_DEFAULT_RO_BINDS = ("/usr", "/usr/local", "/bin", "/sbin", "/lib", "/lib64", "/etc", "/opt")

#: Probe result cache — a real unshare probe costs ~50ms once per process.
_AVAILABLE: bool | None = None


def userns_available(*, force: bool = False) -> bool:
    """Real probe: spawn a confined ``true``. False is fail-closed — callers
    must raise ``IsolationUnavailable``, never fall back to host execution."""
    global _AVAILABLE
    if _AVAILABLE is not None and not force:
        return _AVAILABLE
    bwrap = shutil.which("bwrap")
    if not bwrap:
        _AVAILABLE = False
        return False
    argv = [bwrap, "--unshare-user", "--uid", "0", "--gid", "0", "--unshare-pid"]
    # A dynamically linked binary needs its loader: bind the same system
    # paths the real turn gets, so the probe proves the REAL boundary.
    for path in _DEFAULT_RO_BINDS:
        if Path(path).exists():
            argv += ["--ro-bind", path, path]
    argv += [
        "--die-with-parent",
        "--new-session",
        "--dev",
        "/dev",
        "--tmpfs",
        "/tmp",
        "--chdir",
        "/tmp",
        "/bin/true",
    ]
    try:
        done = subprocess.run(argv, capture_output=True, check=False, timeout=15)
        _AVAILABLE = done.returncode == 0
    except Exception:
        _AVAILABLE = False
    return _AVAILABLE


def build_sandbox_argv(
    *,
    workdir: Path,
    argv: Sequence[str],
    env: Mapping[str, str],
    ro_binds: Sequence[str] = _DEFAULT_RO_BINDS,
) -> list[str]:
    """Build the bwrap argv for one confined execution.

    Pure function — the shape is unit-testable without a namespace-capable
    host. ``workdir`` is the ONLY writable path besides the private /tmp.
    """
    bwrap = shutil.which("bwrap") or "bwrap"
    workdir = Path(workdir).resolve()
    out: list[str] = [
        bwrap,
        "--unshare-user",
        "--uid",
        "0",
        "--gid",
        "0",
        "--unshare-pid",
        "--unshare-ipc",
        "--unshare-uts",
        "--die-with-parent",
        "--new-session",
        "--clearenv",
    ]
    # Namespace-private mounts come FIRST: /dev and the private /tmp tmpfs
    # must precede EVERY bind — a ro-bind or workdir under /tmp (the drain's
    # default root puts workspaces AND the .sandboxes config dir there) would
    # be shadowed by a later tmpfs and either break --chdir or hide the
    # config source (audit r4/r5-F5).
    out += ["--dev", "/dev", "--tmpfs", "/tmp"]
    # The base system root is always bound; `ro_binds` only ADDS code paths —
    # a caller can never accidentally drop the interpreter's own mount.
    for path in dict.fromkeys([*_DEFAULT_RO_BINDS, *ro_binds]):
        if Path(path).exists():
            out += ["--ro-bind", str(path), str(path)]
    out += [
        "--bind",
        str(workdir),
        str(workdir),
        "--chdir",
        str(workdir),
    ]
    for key, value in env.items():
        out += ["--setenv", str(key), str(value)]
    out += ["--"]
    out += [str(part) for part in argv]
    return out


class UsernsSandboxProvider:
    """SandboxProvider over bwrap userns — per-run boundary inside the worker.

    Sandboxes are records under ``state_root`` plus a workspace dir under
    ``workspaces_root``. There is no daemon: ``exec``/``spawn_argv`` wrap
    argv directly. Records carry tenant_id so ``attach``/``exec`` refuse
    cross-tenant use with ``AttachRefused``.
    """

    def __init__(self, workspaces_root: Path, state_root: Path | None = None) -> None:
        self.workspaces_root = Path(workspaces_root)
        self.state_root = Path(state_root) if state_root else self.workspaces_root / ".sandboxes"

    # -- record helpers -------------------------------------------------

    def _record_path(self, sandbox_id: str) -> Path:
        return self.state_root / f"{sandbox_id}.json"

    def _workdir(self, tenant_id: str, workspace_id: str) -> Path:
        # Per-tenant workspace root: the only writable path the sandbox sees.
        return self.workspaces_root / str(tenant_id) / str(workspace_id)

    def _load(self, sandbox_id: str, tenant_id: str) -> dict[str, Any]:
        path = self._record_path(sandbox_id)
        if not path.is_file():
            raise AttachRefused(sandbox_id, tenant_id)
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            raise AttachRefused(sandbox_id, tenant_id) from None
        if str(record.get("tenant_id") or "") != str(tenant_id):
            raise AttachRefused(sandbox_id, tenant_id)
        return record

    def _write(self, sandbox_id: str, record: Mapping[str, Any]) -> None:
        path = self._record_path(sandbox_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(dict(record), sort_keys=True) + "\n", encoding="utf-8")
        tmp.replace(path)

    # -- provider contract ------------------------------------------------

    def create(
        self,
        *,
        tenant_id: str,
        workspace_id: str,
        retain: bool = True,
    ) -> SandboxHandle:
        """Mint a sandbox record + its private workspace. No Run is opened."""
        if not userns_available():
            raise IsolationUnavailable(RUNTIME, "bwrap/userns unavailable on this host")
        sandbox_id = f"userns-{uuid.uuid4().hex[:16]}"
        workdir = self._workdir(tenant_id, workspace_id)
        workdir.mkdir(parents=True, exist_ok=True)
        self._write(
            sandbox_id,
            {
                "sandbox_id": sandbox_id,
                "tenant_id": str(tenant_id),
                "workspace_id": str(workspace_id),
                "runtime": RUNTIME,
                "retain": bool(retain),
                "status": "created",
                "workdir": str(workdir),
                "created_at": time.time(),
                "pid": None,
            },
        )
        return SandboxHandle(
            sandbox_id=sandbox_id,
            container_id="",
            tenant_id=str(tenant_id),
            workspace_id=str(workspace_id),
            runtime=RUNTIME,
            retain=retain,
            status="created",
        )

    def attach(self, sandbox_id: str, *, tenant_id: str) -> SandboxHandle:
        record = self._load(sandbox_id, tenant_id)
        return SandboxHandle(
            sandbox_id=sandbox_id,
            container_id="",
            tenant_id=str(tenant_id),
            workspace_id=str(record.get("workspace_id") or ""),
            runtime=RUNTIME,
            retain=bool(record.get("retain")),
            status=str(record.get("status") or "created"),
        )

    def stop(self, sandbox_id: str, *, tenant_id: str) -> SandboxHandle:
        record = self._load(sandbox_id, tenant_id)
        pid = record.get("pid")
        if isinstance(pid, int) and pid > 0:
            try:
                os.kill(pid, 9)
            except (OSError, ProcessLookupError):
                pass
        record["status"] = "stopped"
        self._write(sandbox_id, record)
        return self.attach(sandbox_id, tenant_id=tenant_id)

    def destroy(self, sandbox_id: str, *, tenant_id: str) -> None:
        record = self._load(sandbox_id, tenant_id)
        record["status"] = "destroyed"
        self._write(sandbox_id, record)

    def health(self, sandbox_id: str, *, tenant_id: str) -> dict[str, str]:
        record = self._load(sandbox_id, tenant_id)
        return {
            "sandbox_id": sandbox_id,
            "runtime": RUNTIME,
            "status": str(record.get("status") or ""),
            "workdir": str(record.get("workdir") or ""),
        }

    def spawn_argv(
        self,
        sandbox_id: str,
        *,
        tenant_id: str,
        argv: Sequence[str],
        env: Mapping[str, str],
        ro_binds: Sequence[str] = _DEFAULT_RO_BINDS,
    ) -> list[str]:
        """bwrap argv for one confined command — the async-spawn surface the
        drain uses. The sandbox record must exist and belong to the tenant.
        ``ro_binds`` extends the system mounts with this host's code paths."""
        record = self._load(sandbox_id, tenant_id)
        workdir = Path(str(record.get("workdir") or "")) or self._workdir(
            tenant_id, str(record.get("workspace_id") or "")
        )
        workdir.mkdir(parents=True, exist_ok=True)
        return build_sandbox_argv(workdir=workdir, argv=argv, env=env, ro_binds=ro_binds)

    def exec(
        self,
        sandbox_id: str,
        *,
        tenant_id: str,
        argv: list[str],
        timeout: float = 60,
    ) -> ExecResult:
        """Synchronous confined execution. Never runs argv on the bare host:
        every command is wrapped by ``build_sandbox_argv`` — a spawn failure
        raises ``IsolationUnavailable`` instead of running unconfined."""
        wrapped = self.spawn_argv(sandbox_id, tenant_id=tenant_id, argv=argv, env={})
        try:
            done = subprocess.run(
                wrapped,
                capture_output=True,
                check=False,
                timeout=timeout,
            )
        except OSError as exc:
            raise IsolationUnavailable(sandbox_id, str(exc)) from exc
        record = self._load(sandbox_id, tenant_id)
        record["status"] = "exited"
        record["exit_code"] = done.returncode
        self._write(sandbox_id, record)
        return ExecResult(
            sandbox_id=sandbox_id,
            container_id="",
            exit_code=int(done.returncode),
            stdout=done.stdout.decode("utf-8", "replace"),
            stderr=done.stderr.decode("utf-8", "replace"),
        )
