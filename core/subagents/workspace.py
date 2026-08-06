"""WorkspaceScope enforcement and write lease management.

B10 · Three workspace isolation modes for parallel children:
  - read_only:         read + whitelisted read-only commands only
  - leased_write:      must acquire a directory/file lease before writing;
                       lease released before another child may write
  - isolated_worktree: write in an independent worktree; results returned
                       as artifact/diff, never auto-written back

Stable error codes:
  - ``workspace.conflict``     — two leased_write children on same file
  - ``workspace.no_scope``     — child edits without declared WorkspaceScope
  - ``workspace.outside_path`` — write to a path outside the scope
  - ``workspace.lease_expired`` — writing after lease expiry
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence
from uuid import uuid4

from protocol.subagents import WorkspaceMode, WorkspaceScope


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

class WorkspaceError(Exception):
    """Base class for workspace violations."""

    CODE = "workspace.error"

    def __init__(self, message: str, *, code: str | None = None):
        super().__init__(message)
        self.code = code or self.CODE


class LeaseConflictError(WorkspaceError):
    """Two children tried to hold the same file/directory lease."""

    CODE = "workspace.conflict"

    def __init__(self, path: str, holder_session_id: str):
        super().__init__(
            f"Workspace lease conflict: '{path}' is held by '{holder_session_id}'",
            code=self.CODE,
        )
        self.path = path
        self.holder_session_id = holder_session_id


class NoWorkspaceScopeError(WorkspaceError):
    """A child attempted to edit without a declared write scope."""

    CODE = "workspace.no_scope"

    def __init__(self, session_id: str, tool: str):
        super().__init__(
            f"Session '{session_id}' attempted '{tool}' without write "
            f"WorkspaceScope (leased_write or isolated_worktree required)",
            code=self.CODE,
        )
        self.session_id = session_id
        self.tool = tool


class OutsidePathError(WorkspaceError):
    """A child attempted to write outside its workspace scope."""

    CODE = "workspace.outside_path"

    def __init__(self, path: str, scope_mode: WorkspaceMode):
        super().__init__(
            f"Path '{path}' is outside the '{scope_mode.value}' workspace scope",
            code=self.CODE,
        )
        self.path = path
        self.scope_mode = scope_mode


class LeaseExpiredError(WorkspaceError):
    """A child attempted to write after its lease expired."""

    CODE = "workspace.lease_expired"

    def __init__(self, path: str, lease_id: str):
        super().__init__(
            f"Write to '{path}' rejected: lease '{lease_id}' has expired",
            code=self.CODE,
        )
        self.path = path
        self.lease_id = lease_id


# ---------------------------------------------------------------------------
# Workspace scope validation
# ---------------------------------------------------------------------------

# Read-only whitelist for bash commands
_READ_ONLY_COMMANDS: tuple[str, ...] = (
    "ls", "cat", "head", "tail", "grep", "rg", "find", "wc",
    "python -m pytest --collect-only", "git status", "git diff", "git log",
    "git show", "pwd", "echo", "whoami", "env",
)


def is_read_only_command(command: str) -> bool:
    """Check whether a bash command is whitelisted as read-only."""
    cmd = command.strip()
    return any(cmd.startswith(prefix) for prefix in _READ_ONLY_COMMANDS)


class WorkspaceValidator:
    """Validates tool operations against a WorkspaceScope."""

    def __init__(self, scope: WorkspaceScope, root: Path | None = None):
        self.scope = scope
        self.root = root

    # -- edit ----------------------------------------------------------------

    def check_edit(self, session_id: str, path: str, lease_manager: "LeaseManager | None" = None) -> None:
        """Validate an edit operation.

        Raises NoWorkspaceScopeError, OutsidePathError, or LeaseConflictError.
        """
        # read_only cannot edit
        if self.scope.mode == WorkspaceMode.READ_ONLY:
            raise NoWorkspaceScopeError(session_id, "edit")

        # Paths outside the scope are rejected first (most fundamental violation)
        self._check_path_in_scope(path, self.scope.mode)

        # isolated_worktree edits go to the worktree, not the Primary workspace
        if self.scope.mode == WorkspaceMode.ISOLATED_WORKTREE:
            return

        # leased_write must hold a lease on the path
        if self.scope.mode == WorkspaceMode.LEASED_WRITE:
            if lease_manager is None:
                raise NoWorkspaceScopeError(session_id, "edit")
            holder = lease_manager.holder(path)
            if holder is None or holder.session_id != session_id:
                raise NoWorkspaceScopeError(
                    session_id,
                    f"edit (no lease on '{path}')",
                )
            return

        raise NoWorkspaceScopeError(session_id, "edit")

    # -- bash ----------------------------------------------------------------

    def check_bash(self, session_id: str, command: str) -> None:
        """Validate a bash command.

        read_only may only run whitelisted read-only commands.
        """
        if self.scope.mode == WorkspaceMode.READ_ONLY:
            if not is_read_only_command(command):
                raise NoWorkspaceScopeError(session_id, f"bash: {command[:40]}")

    # -- external path -------------------------------------------------------

    def _check_path_in_scope(self, path: str, mode: WorkspaceMode) -> None:
        """Reject paths outside the workspace scope."""
        if self.root is None:
            return

        p = Path(path)
        if not p.is_absolute():
            return  # relative paths are within the workspace

        try:
            resolved = p.resolve()
            root_resolved = self.root.resolve()
        except OSError:
            raise OutsidePathError(path, mode) from None

        if resolved != root_resolved and root_resolved not in resolved.parents:
            raise OutsidePathError(path, mode)


# ---------------------------------------------------------------------------
# Lease manager
# ---------------------------------------------------------------------------

@dataclass
class Lease:
    """A write lease over a path held by a child session."""

    lease_id: str = field(default_factory=lambda: str(uuid4()))
    session_id: str = ""
    path: str = ""
    acquired_at: float = field(default_factory=time.time)
    expires_at: float = 0.0          # 0 = no expiry
    _released: bool = field(default=False, repr=False)

    @property
    def is_expired(self) -> bool:
        if self._released:
            return True
        if self.expires_at <= 0:
            return False
        return time.time() > self.expires_at

    @property
    def is_active(self) -> bool:
        return not self._released and not self.is_expired


@dataclass
class LeaseManager:
    """Manages write leases across parallel children.

    A path can be leased to at most one child at a time. Leases are
    released on complete/fail/cancel/timeout, or recycled by crash recovery.
    """

    default_lease_ttl_seconds: float = 300.0
    # path → Lease (active leases)
    _leases: dict[str, Lease] = field(default_factory=dict)

    # -- acquisition ---------------------------------------------------------

    def acquire(
        self,
        session_id: str,
        paths: Sequence[str],
        *,
        ttl_seconds: float | None = None,
    ) -> Lease:
        """Acquire a lease over one or more paths.

        Raises LeaseConflictError if any path is already held by another child.
        """
        # Normalize to stable keys
        norm_paths = [self._normalize(p) for p in paths]

        # Conflict check
        for norm in norm_paths:
            existing = self._leases.get(norm)
            if existing is not None and existing.is_active and existing.session_id != session_id:
                raise LeaseConflictError(norm, existing.session_id)

        ttl = ttl_seconds if ttl_seconds is not None else self.default_lease_ttl_seconds
        # ttl <= 0 means no expiry
        expires_at = 0.0 if ttl <= 0 else time.time() + ttl
        lease = Lease(
            session_id=session_id,
            path=norm_paths[0] if norm_paths else "",
            expires_at=expires_at,
        )

        # Store lease under every path it covers
        for norm in norm_paths:
            self._leases[norm] = lease
        return lease

    # -- queries -------------------------------------------------------------

    def is_held_by(self, lease_id: str, path: str) -> bool:
        """Check whether a path is held by the given lease id."""
        norm = self._normalize(path)
        existing = self._leases.get(norm)
        return existing is not None and existing.lease_id == lease_id and existing.is_active

    def holder(self, path: str) -> Lease | None:
        """Return the active lease holder for a path, or None."""
        existing = self._leases.get(self._normalize(path))
        if existing is not None and existing.is_active:
            return existing
        return None

    # -- release -------------------------------------------------------------

    def release(self, lease_id: str) -> None:
        """Release a lease (idempotent)."""
        for norm, lease in list(self._leases.items()):
            if lease.lease_id == lease_id:
                lease._released = True
                del self._leases[norm]

    def release_all_for_session(self, session_id: str) -> int:
        """Release all leases held by a session; returns count released."""
        released = 0
        for norm, lease in list(self._leases.items()):
            if lease.session_id == session_id:
                lease._released = True
                del self._leases[norm]
                released += 1
        return released

    # -- crash recovery ------------------------------------------------------

    def recover_expired(self) -> int:
        """Recycle expired leases; returns count recycled.

        Called at dispatch time and on a background sweep. Expired leases
        are released so other children can acquire them.
        """
        recycled = 0
        for norm, lease in list(self._leases.items()):
            if lease.is_expired:
                lease._released = True
                del self._leases[norm]
                recycled += 1
        return recycled

    def _normalize(self, path: str) -> str:
        """Normalize a path to a stable lease key."""
        p = Path(path)
        try:
            return str(p.resolve())
        except OSError:
            return str(p.absolute())


# ---------------------------------------------------------------------------
# Convenience factory
# ---------------------------------------------------------------------------

def make_validator(scope: WorkspaceScope, root: Path | None = None) -> WorkspaceValidator:
    """Build a WorkspaceValidator from a scope."""
    return WorkspaceValidator(scope=scope, root=root)
