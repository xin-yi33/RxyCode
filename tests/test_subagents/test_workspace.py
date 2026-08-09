"""B10 · WorkspaceScope, write leases, and concurrency conflict tests."""

from __future__ import annotations

import time
import pytest

from protocol.subagents import WorkspaceMode, WorkspaceScope
from core.subagents.workspace import (
    Lease,
    LeaseConflictError,
    LeaseExpiredError,
    LeaseManager,
    NoWorkspaceScopeError,
    OutsidePathError,
    WorkspaceError,
    WorkspaceValidator,
    is_read_only_command,
)


# ============================================================================
# Read-only command whitelist
# ============================================================================

class TestReadOnlyCommands:
    """Bash whitelist for read_only scope."""

    def test_read_only_commands_allowed(self):
        for cmd in ["ls -la", "cat file.py", "grep -r auth core", "git status", "pwd"]:
            assert is_read_only_command(cmd), cmd

    def test_write_commands_not_allowed(self):
        for cmd in ["rm file.py", "mv a b", "git push origin", "python setup.py install"]:
            assert not is_read_only_command(cmd), cmd


# ============================================================================
# WorkspaceValidator
# ============================================================================

class TestWorkspaceValidator:
    """Scope enforcement for edit and bash."""

    def test_read_only_cannot_edit(self):
        scope = WorkspaceScope(mode=WorkspaceMode.READ_ONLY)
        validator = WorkspaceValidator(scope)
        with pytest.raises(NoWorkspaceScopeError, match="without write"):
            validator.check_edit("ses_child_1", "src/auth.py")

    def test_read_only_blocks_write_bash(self):
        scope = WorkspaceScope(mode=WorkspaceMode.READ_ONLY)
        validator = WorkspaceValidator(scope)
        with pytest.raises(NoWorkspaceScopeError, match="bash"):
            validator.check_bash("ses_child_1", "rm -rf /tmp")

    def test_read_only_allows_read_bash(self):
        scope = WorkspaceScope(mode=WorkspaceMode.READ_ONLY)
        validator = WorkspaceValidator(scope)
        validator.check_bash("ses_child_1", "cat file.py")  # Does not raise

    def test_leased_write_edit_requires_lease(self):
        scope = WorkspaceScope(mode=WorkspaceMode.LEASED_WRITE, lease_id="lease_1")
        validator = WorkspaceValidator(scope)
        leases = LeaseManager()

        # No lease held → denied
        with pytest.raises(NoWorkspaceScopeError, match="no lease"):
            validator.check_edit("ses_child_1", "src/auth.py", leases)

        # Acquire lease → allowed (the session now holds the lease)
        leases.acquire("ses_child_1", ["src/auth.py"])
        validator.check_edit("ses_child_1", "src/auth.py", leases)  # Does not raise

        # Another session holding the lease → denied
        with pytest.raises(NoWorkspaceScopeError, match="no lease"):
            validator.check_edit("ses_child_2", "src/auth.py", leases)

    def test_isolated_worktree_edit_allowed_in_scope(self):
        scope = WorkspaceScope(mode=WorkspaceMode.ISOLATED_WORKTREE)
        validator = WorkspaceValidator(scope)
        validator.check_edit("ses_child_1", "src/auth.py")  # Does not raise

    def test_edit_error_code_is_stable(self):
        scope = WorkspaceScope(mode=WorkspaceMode.READ_ONLY)
        validator = WorkspaceValidator(scope)
        with pytest.raises(WorkspaceError) as exc_info:
            validator.check_edit("ses_child_1", "x.py")
        assert exc_info.value.code == "workspace.no_scope"


# ============================================================================
# Lease acquisition and conflicts
# ============================================================================

class TestLeaseManager:
    """Lease lifecycle and concurrency conflicts."""

    def test_acquire_lease(self):
        leases = LeaseManager()
        lease = leases.acquire("child_a", ["src/auth.py"])
        assert lease.lease_id != ""
        assert lease.session_id == "child_a"
        assert leases.holder("src/auth.py").session_id == "child_a"

    def test_same_file_conflict_stable_code(self):
        leases = LeaseManager()
        leases.acquire("child_a", ["src/auth.py"])
        with pytest.raises(LeaseConflictError) as exc_info:
            leases.acquire("child_b", ["src/auth.py"])
        assert exc_info.value.code == "workspace.conflict"
        assert exc_info.value.holder_session_id == "child_a"
        assert exc_info.value.path.replace("\\", "/").endswith("src/auth.py")

    def test_same_child_release_then_acquire(self):
        leases = LeaseManager()
        lease_a = leases.acquire("child_a", ["src/auth.py"])
        leases.release(lease_a.lease_id)

        # Now child_b can acquire
        lease_b = leases.acquire("child_b", ["src/auth.py"])
        assert lease_b.session_id == "child_b"

    def test_release_clears_holder(self):
        leases = LeaseManager()
        lease = leases.acquire("child_a", ["src/auth.py"])
        assert leases.holder("src/auth.py") is not None
        leases.release(lease.lease_id)
        assert leases.holder("src/auth.py") is None

    def test_release_all_for_session(self):
        leases = LeaseManager()
        leases.acquire("child_a", ["f1.py", "f2.py"])
        count = leases.release_all_for_session("child_a")
        assert count == 2
        assert leases.holder("f1.py") is None
        assert leases.holder("f2.py") is None

    def test_different_files_no_conflict(self):
        leases = LeaseManager()
        leases.acquire("child_a", ["a.py"])
        lease_b = leases.acquire("child_b", ["b.py"])  # No conflict
        assert lease_b.session_id == "child_b"

    def test_is_held_by(self):
        leases = LeaseManager()
        lease = leases.acquire("child_a", ["src/auth.py"])
        assert leases.is_held_by(lease.lease_id, "src/auth.py") is True
        assert leases.is_held_by("wrong_id", "src/auth.py") is False


# ============================================================================
# Lease expiry
# ============================================================================

class TestLeaseExpiry:
    """Lease expiry and crash recovery."""

    def test_lease_expires_after_ttl(self):
        leases = LeaseManager()
        lease = leases.acquire("child_a", ["src/auth.py"], ttl_seconds=0.1)
        assert not lease.is_expired
        time.sleep(0.2)
        assert lease.is_expired

    def test_holder_returns_none_after_expiry(self):
        leases = LeaseManager()
        leases.acquire("child_a", ["src/auth.py"], ttl_seconds=0.1)
        time.sleep(0.2)
        assert leases.holder("src/auth.py") is None

    def test_recover_expired_recycles(self):
        leases = LeaseManager()
        leases.acquire("child_a", ["f.py"], ttl_seconds=0.1)
        time.sleep(0.2)
        recycled = leases.recover_expired()
        assert recycled == 1

        # After recovery, another child can acquire
        lease = leases.acquire("child_b", ["f.py"])
        assert lease.session_id == "child_b"

    def test_no_expiry_when_ttl_zero(self):
        leases = LeaseManager()
        lease = leases.acquire("child_a", ["f.py"], ttl_seconds=0)
        assert not lease.is_expired

    def test_lease_expired_error_code_exists(self):
        """LeaseExpiredError carries the stable code."""
        err = LeaseExpiredError("path.py", "lease_1")
        assert err.code == "workspace.lease_expired"


# ============================================================================
# Outside path rejection
# ============================================================================

class TestOutsidePath:
    """Paths outside the workspace root are rejected."""

    def test_absolute_outside_path_rejected(self, tmp_path):
        workspace_root = tmp_path / "workspace"
        workspace_root.mkdir(exist_ok=True)
        outside = tmp_path / "outside" / "file.py"
        scope = WorkspaceScope(mode=WorkspaceMode.LEASED_WRITE, lease_id="l1")
        validator = WorkspaceValidator(scope, root=workspace_root)
        leases = LeaseManager()
        # Acquire the lease first so the outside-path check fires, not no_scope
        leases.acquire("child", [str(workspace_root / "src" / "auth.py")])

        with pytest.raises(OutsidePathError) as exc_info:
            validator.check_edit("child", str(outside), leases)

        assert exc_info.value.code == "workspace.outside_path"

    def test_relative_path_accepted(self, tmp_path):
        workspace_root = tmp_path / "workspace"
        workspace_root.mkdir(exist_ok=True)
        scope = WorkspaceScope(mode=WorkspaceMode.LEASED_WRITE, lease_id="l1")
        validator = WorkspaceValidator(scope, root=workspace_root)
        leases = LeaseManager()
        leases.acquire("child", ["src/auth.py"])

        # Relative path inside workspace passes outside-path check and lease check
        validator.check_edit("child", "src/auth.py", leases)  # Does not raise

    def test_relative_path_missing_lease_raises_no_scope(self, tmp_path):
        """A relative path without a lease is a scope violation, not outside-path."""
        scope = WorkspaceScope(mode=WorkspaceMode.LEASED_WRITE, lease_id="l1")
        validator = WorkspaceValidator(scope, root=tmp_path / "workspace")
        with pytest.raises(NoWorkspaceScopeError, match="no lease"):
            validator.check_edit("child", "src/auth.py", LeaseManager())


# ============================================================================
# WorkspaceError hierarchy
# ============================================================================

class TestWorkspaceErrorHierarchy:
    """All workspace errors share a stable code namespace."""

    def test_all_codes(self):
        assert LeaseConflictError.CODE == "workspace.conflict"
        assert NoWorkspaceScopeError.CODE == "workspace.no_scope"
        assert OutsidePathError.CODE == "workspace.outside_path"
        assert LeaseExpiredError.CODE == "workspace.lease_expired"

    def test_all_are_workspace_errors(self):
        assert issubclass(LeaseConflictError, WorkspaceError)
        assert issubclass(NoWorkspaceScopeError, WorkspaceError)
        assert issubclass(OutsidePathError, WorkspaceError)
        assert issubclass(LeaseExpiredError, WorkspaceError)

    def test_default_workspace_error_code(self):
        err = WorkspaceError("generic")
        assert err.code == "workspace.error"
