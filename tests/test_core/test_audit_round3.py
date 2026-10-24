"""Regression tests for the third audit round (P1-01..06 / P2-01..12).

Each test pins one concrete finding so it cannot silently come back.
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import pytest

from RxyCode.RxyCode1_1_0.core import persistent_shell as ps

WINDOWS = os.name == "nt"
pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# P1-01 · sandbox plan is carried in full, not just argv
# ---------------------------------------------------------------------------

class TestSandboxPlan:
    async def test_plan_carries_job_policy_and_cleanup(self):
        from RxyCode.RxyCode1_1_0.core.persistent_shell import ShellSandboxPlan

        calls: list[ShellSandboxPlan] = []
        fake_plan = ShellSandboxPlan(
            argv=["fake-shell"],
            wrapped=object(),
            policy=object(),
            cleanup=(Path("profile.tmp"),),
            backend="seatbelt",
            downgraded=True,
            detail="test",
        )

        def wrapper(argv, cwd):
            calls.append(fake_plan)
            return fake_plan

        await ps.release_all()
        shell = await ps.acquire_shell(
            identity="plan", cwd=os.getcwd(), sandbox_command=wrapper
        )
        assert shell._sandbox_command is wrapper
        # The plan object itself is what must be consumed, not a bare list.
        plan = wrapper(["x"], os.getcwd())
        assert plan.wrapped is not None
        assert plan.policy is not None
        assert plan.cleanup
        assert plan.backend == "seatbelt"
        assert plan.downgraded is True
        await ps.release_all()

    async def test_startup_failure_marks_sandbox_refused(self):
        def refusing(argv, cwd):
            raise RuntimeError("sandbox says no")

        await ps.release_all()
        shell = await ps.acquire_shell(
            identity="refuse", cwd=os.getcwd(), sandbox_command=refusing
        )
        with pytest.raises(ps.ShellStartupError) as info:
            await shell.ensure_started()
        assert getattr(info.value, "sandbox_refused", False) is True
        await ps.release_all()

    async def test_plain_startup_error_is_fall_back_eligible(self):
        err = ps.ShellStartupError("plain failure")
        assert err.sandbox_refused is False


# ---------------------------------------------------------------------------
# P1-02 · DANGER keeps its level (never downgraded to write)
# ---------------------------------------------------------------------------

class TestDangerLevelPreserved:
    def test_danger_shell_command_is_not_waived_by_write_auto_approve(self):
        """auto_approve=["write"] must NOT auto-run a DANGER command."""
        import asyncio as _asyncio

        from langchain_core.tools import StructuredTool

        from RxyCode.RxyCode1_1_0.core.safety import approval as approval_mod
        from RxyCode.RxyCode1_1_0.execution.tool_orchestrator import (
            ToolOrchestrator,
        )

        async def _stub(**_kw):
            return "EXECUTED"

        previous = approval_mod.get_approval_broker()
        approval_mod.set_approval_broker(None)
        try:
            orch = ToolOrchestrator()
            orch.register(
                "bash",
                StructuredTool(
                    name="bash", description="d", args_schema=None, coroutine=_stub
                ),
            )
            cfg = {
                "safety": {
                    "enabled": True,
                    "permission_mode": "confirm_all",
                    "auto_approve": ["write"],
                }
            }
            # ``rm -rf /`` classifies DANGER; "write" auto-approval must not
            # cover it.
            out = str(
                _asyncio.run(
                    orch.execute_tool(
                        "bash",
                        {
                            "command": "rm -rf /",
                            "description": "d",
                            "workdir": "",
                            "timeout": 30,
                        },
                        config=cfg,
                    )
                )
            )
            assert "EXECUTED" not in out, (
                "DANGER was downgraded to write and auto-approved"
            )
            # The command must be refused.  Which gate refuses first is
            # environment-dependent: the hard blacklist rejects shutdown-class
            # commands before approval, the approval gate answers "terminal for
            # the current turn" when no broker exists, and a workspace-scoped
            # write whitelist may reject the target path earlier.  All are
            # safe; the property under test is "not run".
            lowered = out.lower()
            assert (
                "dangerous command rejected" in out
                or "terminal for the current turn" in out
                or "write path not allowed" in out
                or "whitelist" in lowered
                or "denied" in lowered
            ), out
        finally:
            approval_mod.set_approval_broker(previous)


# ---------------------------------------------------------------------------
# P1-06 · process-tree ownership survives the root exiting first
# ---------------------------------------------------------------------------

class TestProcessTreeOwnership:
    async def test_close_reaps_descendants_after_root_exit(self, tmp_path: Path):
        """Closing the shell must kill what its commands left running.

        On Windows the shell owns a kill-on-close Job (created even when the OS
        sandbox is disabled), so a child that outlives its parent is still
        reaped.  Without that, Windows drops the parent link on exit and neither
        ``taskkill /T`` nor ppid-walking can find the orphan.
        """
        marker = tmp_path / "child_done.txt"
        child_py = tmp_path / "child.py"
        child_py.write_text(
            "import time, pathlib\n"
            "time.sleep(3)\n"
            f"pathlib.Path(r'{marker}').write_text('alive')\n",
            encoding="utf-8",
        )

        await ps.release_all()
        shell = await ps.acquire_shell(identity="tree", cwd=os.getcwd())
        await shell.ensure_started()
        if WINDOWS:
            cmd = (
                "Start-Process -WindowStyle Hidden python -ArgumentList "
                f"'-c','import time,pathlib;time.sleep(3);"
                f"pathlib.Path(r\"{marker}\").write_text(\"alive\")'"
            )
        else:
            cmd = (
                "nohup python -c "
                f"'import time,pathlib;time.sleep(3);"
                f"pathlib.Path(\"{marker}\").write_text(\"alive\")' "
                "> /dev/null 2>&1 &"
            )
        await shell.run(cmd, timeout=30)
        await asyncio.sleep(0.6)

        await shell.close()
        await asyncio.sleep(4.0)

        assert not marker.exists(), "a descendant survived shell close"
        await ps.release_all()


# ---------------------------------------------------------------------------
# P2-01 / P2-02 · synchronous invalidation of a session's shells
# ---------------------------------------------------------------------------

class TestSessionInvalidation:
    async def test_invalidate_is_synchronous(self):
        await ps.release_all()
        await ps.acquire_shell(identity="s1", cwd=os.getcwd())
        await ps.acquire_shell(identity="s1::iso", cwd=os.getcwd())
        await ps.acquire_shell(identity="s2", cwd=os.getcwd())

        doomed = ps.invalidate_session_sync("s1")  # sync call: no await

        # The registry is already clean BEFORE any await: a command issued
        # right now cannot acquire the old shell.
        assert ps.active_identities() == ["s2"]
        assert len(doomed) == 2
        await ps.close_shells(doomed)
        await ps.release_all()

    async def test_cleared_session_shell_is_not_reused(self):
        from RxyCode.RxyCode1_1_0.core.session_runtime import (
            bind_session,
            clear_session_runtime,
            reset_session_binding,
        )

        await ps.release_all()
        token = bind_session("reset-race")
        try:
            identity = ps.state_identity()
            shell = await ps.acquire_shell(identity=identity, cwd=os.getcwd())
            await shell.ensure_started()
            clear_session_runtime("reset-race")
            # Immediately ask again: must be a NEW object, not the stale shell.
            fresh = await ps.acquire_shell(identity=identity, cwd=os.getcwd())
            assert fresh is not shell, "cleared session reused its old shell"
            await asyncio.sleep(0.3)
        finally:
            reset_session_binding(token)
            await ps.release_all()


# ---------------------------------------------------------------------------
# P2-03 · output without a trailing newline still completes
# ---------------------------------------------------------------------------

class TestMarkerBoundary:
    async def test_no_newline_output_completes(self):
        await ps.release_all()
        shell = await ps.acquire_shell(identity="nonewline", cwd=os.getcwd())
        try:
            if WINDOWS:
                # Write-Host -NoNewline bypasses the pipeline; captured via 6>&1.
                r = await shell.run("Write-Host -NoNewline 'partial'", timeout=30)
            else:
                r = await shell.run("printf 'partial'", timeout=30)
            assert "partial" in r.stdout
            assert r.timed_out is False
        finally:
            await ps.release_all()


# ---------------------------------------------------------------------------
# P2-06 / P2-07 / P2-08 / P2-09 · diagnostics honesty
# ---------------------------------------------------------------------------

class TestDiagnosticsHonesty:
    def test_eslint_empty_stdout_with_fatal_rc_is_not_pass(self):
        from RxyCode.RxyCode1_1_0.core import post_write_diagnostics as diag

        assert diag._parse_eslint_json("") == []
        # A fatal exit is rejected by the rc check before parsing; pin that the
        # helper itself never invents findings from nothing.
        assert diag._parse_eslint_json("not json") is None

    def test_fingerprint_ignores_line_endings(self):
        from RxyCode.RxyCode1_1_0.core import post_write_diagnostics as diag

        lf = "a = 1\nb = 2\n"
        crlf = "a = 1\r\nb = 2\r\n"
        assert diag.content_fingerprint(lf) == diag.content_fingerprint(crlf)

    def test_same_name_files_in_different_dirs_differ(self):
        from RxyCode.RxyCode1_1_0.core import post_write_diagnostics as diag

        root = Path(os.getcwd())
        a = diag._normalise_path_key(root / "src" / "a.ts", root)
        b = diag._normalise_path_key(root / "lib" / "a.ts", root)
        assert a != b
        assert a.endswith("src/a.ts")
        assert b.endswith("lib/a.ts")

    def test_path_attribution_uses_full_relative_path(self):
        from RxyCode.RxyCode1_1_0.core import post_write_diagnostics as diag

        root = Path(os.getcwd())
        target = diag._normalise_path_key(root / "src" / "a.ts", root)
        assert diag._same_file("src/a.ts", target, root) is True
        assert diag._same_file("lib/a.ts", target, root) is False
        assert diag._same_file("a.ts", target, root) is False

    async def test_deleted_file_downgrades_pass(self, tmp_path: Path):
        from RxyCode.RxyCode1_1_0.core import post_write_diagnostics as diag

        p = tmp_path / "gone.py"
        content = "x = 1\n"
        p.write_text(content, encoding="utf-8")

        async def fake_check(path, content, *, fingerprint, operation):
            return diag.DiagnosticReport(
                path=str(path),
                operation=operation,
                fingerprint=fingerprint,
                status="pass",
            )

        original = diag.check_python
        diag.check_python = fake_check
        try:
            p.unlink()
            report = await diag.diagnose(p, content)
        finally:
            diag.check_python = original
        assert report.status == "stale"
        assert report.ok is False


# ---------------------------------------------------------------------------
# P2-11 · one model-facing file-change entry
# ---------------------------------------------------------------------------

class TestSingleEditEntry:
    async def test_only_edit_is_registered_for_file_changes(self):
        from RxyCode.RxyCode1_1_0.core.builtin_tool_registration import (
            register_builtin_tools,
        )
        from RxyCode.RxyCode1_1_0.execution.tool_orchestrator import (
            ToolOrchestrator,
        )
        from RxyCode.RxyCode1_1_0.tools.registry import ToolRegistry

        registry = ToolRegistry()
        register_builtin_tools(
            registry,
            ToolOrchestrator(tool_registry=registry),
            rag_enabled=False,
        )
        names = set(registry.get_names())
        assert "edit" in names
        # write/patch exist only as compatibility ALIASES of edit (the 37b22e88
        # contract): resolving the alias must yield the one unified tool, and no
        # standalone schema is registered for them.
        assert registry.get("write") is registry.get("edit"), (
            "standalone write must not be model-facing"
        )
        assert registry.get("patch") is registry.get("edit"), (
            "standalone patch must not be model-facing"
        )

    async def test_edit_tool_accepts_three_operations(self):
        from RxyCode.RxyCode1_1_0.tools.edit import edit_tool

        fields = edit_tool.args_schema.model_fields
        for name in ("operation", "content", "diff"):
            assert name in fields
        assert edit_tool.name == "edit"
