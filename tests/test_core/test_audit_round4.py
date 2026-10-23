"""Regression tests for the fourth audit round (P1-03/04, P2-01..P2-07).

Each class pins one concrete finding so it cannot silently come back.  The
audit was reproduced before any fix: these tests are the reproduction, kept as
a guard (a test that fails on the pre-fix code and passes on the fixed code).
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import sys
import types
import uuid
from pathlib import Path

import pytest

from RxyCode.RxyCode1_1_0.core import persistent_shell as ps
from RxyCode.RxyCode1_1_0.core import post_write_diagnostics as diag

WINDOWS = os.name == "nt"


@pytest.fixture
def ws_dir():
    """Scratch directory INSIDE the execution workspace.

    Checkers run through the controlled execution entry, whose sandbox refuses
    a cwd outside ``execution.workspace_root``; a pytest temp dir would make
    every real run "unavailable".
    """
    root = Path(os.getcwd()) / f"_round4_ws_{uuid.uuid4().hex[:8]}"
    root.mkdir()
    try:
        yield root
    finally:
        shutil.rmtree(root, ignore_errors=True)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _node_project(
    root: Path,
    *,
    eslint: bool = False,
    tsc: bool = False,
    eslint_config: str | None = None,
    tsconfig: dict | None = None,
) -> Path:
    """Build a minimal JS/TS project layout with optional local binaries."""
    bin_dir = root / "node_modules" / ".bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    if eslint:
        (bin_dir / "eslint").write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    if tsc:
        (bin_dir / "tsc").write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    if eslint_config is not None:
        (root / eslint_config).write_text("module.exports = [];\n", encoding="utf-8")
    if tsconfig is not None:
        (root / "tsconfig.json").write_text(json.dumps(tsconfig), encoding="utf-8")
    return root


class _CheckerSpy:
    """Records ``_run_checker`` calls and answers with a fixed result."""

    def __init__(self, result=(0, "", "", False)):
        self.calls: list[list[str]] = []
        self._result = result

    async def __call__(self, argv, cwd, *, timeout=0.0):
        self.calls.append(list(argv))
        return self._result


# ---------------------------------------------------------------------------
# P1-03 · executable project config requires explicit execution trust
# ---------------------------------------------------------------------------

class TestProjectConfigTrust:
    @staticmethod
    def _trust(monkeypatch, config: dict) -> bool:
        import importlib

        settings = importlib.import_module("RxyCode.RxyCode1_1_0.config.settings")
        monkeypatch.setattr(settings, "load_config", lambda: config)
        return diag.project_config_execution_allowed()

    def test_confirm_all_does_not_grant_execution_trust(self, monkeypatch):
        assert self._trust(
            monkeypatch, {"safety": {"permission_mode": "confirm_all"}}
        ) is False

    def test_auto_edit_does_not_grant_execution_trust(self, monkeypatch):
        # auto_edit only consented to file edits, never to running project code.
        assert self._trust(
            monkeypatch, {"safety": {"permission_mode": "auto_edit"}}
        ) is False

    def test_full_auto_grants_execution_trust(self, monkeypatch):
        assert self._trust(
            monkeypatch, {"safety": {"permission_mode": "full_auto"}}
        ) is True

    def test_explicit_diagnostics_opt_in_grants_trust(self, monkeypatch):
        assert self._trust(
            monkeypatch,
            {
                "safety": {"permission_mode": "confirm_all"},
                "diagnostics": {"run_project_config_checkers": True},
            },
        ) is True

    def test_auto_approve_danger_grants_trust(self, monkeypatch):
        assert self._trust(
            monkeypatch,
            {
                "safety": {
                    "permission_mode": "confirm_all",
                    "auto_approve": ["danger"],
                }
            },
        ) is True

    def test_executable_config_detection(self, tmp_path: Path):
        root = _node_project(tmp_path, eslint_config="eslint.config.mjs")
        found = diag.executable_config_present(root)
        assert found is not None and found.name == "eslint.config.mjs"

        plain = tmp_path / "plain"
        plain.mkdir()
        (plain / "tsconfig.json").write_text("{}", encoding="utf-8")
        assert diag.executable_config_present(plain) is None


class TestExecutableConfigGating:
    async def test_untrusted_eslint_config_is_not_executed(
        self, monkeypatch, tmp_path: Path
    ):
        root = _node_project(
            tmp_path / "proj", eslint=True, eslint_config="eslint.config.js"
        )
        target = root / "a.js"
        target.write_text("const x = 1;\n", encoding="utf-8")
        spy = _CheckerSpy((0, "[]", "", False))
        monkeypatch.setattr(diag, "_run_checker", spy)
        monkeypatch.setattr(diag, "project_config_execution_allowed", lambda: False)
        # No safe fallback available: nothing ran, so the honest answer is
        # "not checked" with the trust reason -- never "pass".
        monkeypatch.setattr(diag.shutil, "which", lambda name: None)

        report = await diag.check_js_ts(
            target, target.read_text(encoding="utf-8"),
            fingerprint="fp", operation="edit", node_root=root,
        )

        assert report.status == "not_checked"
        assert report.checker == "eslint"
        assert "executable JavaScript" in report.note
        assert spy.calls == [], "eslint config was executed without trust"

    async def test_untrusted_eslint_config_still_falls_through_to_tsc(
        self, monkeypatch, tmp_path: Path
    ):
        """The trust gate must skip ONLY the config-executing checker.

        Returning ``not_checked`` for the whole file would silently drop type
        checking in every project that ships an ESLint flat config (the common
        Next.js/Vite layout), which is not what the audit asked for.
        """
        root = _node_project(
            tmp_path / "proj-ts",
            eslint=True,
            eslint_config="eslint.config.js",
            tsc=True,
            tsconfig={"compilerOptions": {"target": "es2020"}},
        )
        target = root / "d.ts"
        target.write_text("export const d: number = 4;\n", encoding="utf-8")
        spy = _CheckerSpy((0, "", "", False))
        monkeypatch.setattr(diag, "_run_checker", spy)
        monkeypatch.setattr(diag, "project_config_execution_allowed", lambda: False)

        async def fake_includes(*args, **kwargs):
            return True

        monkeypatch.setattr(diag, "_tsc_includes", fake_includes)

        report = await diag.check_js_ts(
            target, target.read_text(encoding="utf-8"),
            fingerprint="fp", operation="edit", node_root=root,
        )

        assert report.status == "pass"
        assert report.checker == "tsc"
        assert spy.calls, "the safe checker never ran after the config checker was skipped"
        ran = [Path(argv[0]).name.lower() for argv in spy.calls]
        assert all("eslint" not in name for name in ran), "eslint config was executed"

    async def test_trusted_eslint_config_runs(
        self, monkeypatch, tmp_path: Path
    ):
        root = _node_project(
            tmp_path / "proj2", eslint=True, eslint_config="eslint.config.js"
        )
        target = root / "b.js"
        target.write_text("const y = 2;\n", encoding="utf-8")
        spy = _CheckerSpy((0, "[]", "", False))
        monkeypatch.setattr(diag, "_run_checker", spy)
        monkeypatch.setattr(diag, "project_config_execution_allowed", lambda: True)

        report = await diag.check_js_ts(
            target, target.read_text(encoding="utf-8"),
            fingerprint="fp", operation="edit", node_root=root,
        )

        assert report.status == "pass"
        assert report.checker == "eslint"
        assert spy.calls, "trusted eslint never ran"

    @pytest.mark.skipif(
        shutil.which("node") is None, reason="a real node runtime is required"
    )
    async def test_real_eslint_config_is_not_executed_without_trust(
        self, monkeypatch, ws_dir: Path
    ):
        """End-to-end: the project config is REAL code that writes a file.

        Proves both directions: without trust the config never runs; with trust
        the same harness does run it (so the negative result is the gate, not a
        broken fake checker).
        """
        root = ws_dir
        bin_dir = root / "node_modules" / ".bin"
        bin_dir.mkdir(parents=True)
        marker = root / "config_ran.txt"
        (root / "eslint.config.js").write_text(
            "require('fs').writeFileSync(%s, 'config-loaded');\n"
            "module.exports = [];\n"
            % json.dumps(str(marker).replace("\\", "/")),
            encoding="utf-8",
        )
        fake = root / "fake-eslint.js"
        fake.write_text(
            "require(process.cwd() + '/eslint.config.js');\n"
            "process.stdout.write('[]');\n",
            encoding="utf-8",
        )
        if WINDOWS:
            (bin_dir / "eslint.cmd").write_text(
                '@echo off\r\nnode "%~dp0..\\..\\fake-eslint.js" %*\r\n',
                encoding="ascii",
            )
        else:
            shim = bin_dir / "eslint"
            shim.write_text(
                "#!/usr/bin/env node\n" + fake.read_text(encoding="utf-8"),
                encoding="utf-8",
            )
            shim.chmod(0o755)
        target = root / "a.js"
        target.write_text("const x = 1;\n", encoding="utf-8")
        content = target.read_text(encoding="utf-8")

        monkeypatch.setattr(diag, "project_config_execution_allowed", lambda: False)
        untrusted = await diag.check_js_ts(
            target, content, fingerprint="fp", operation="edit", node_root=root
        )
        assert not marker.exists(), "the ESLint config executed without trust"

        monkeypatch.setattr(diag, "project_config_execution_allowed", lambda: True)
        trusted = await diag.check_js_ts(
            target, content, fingerprint="fp", operation="edit", node_root=root
        )
        assert marker.exists(), (
            "test harness broken: the trusted run never loaded the ESLint config "
            f"(untrusted={untrusted.status}, trusted={trusted.status}/{trusted.note})"
        )

    async def test_tsconfig_compiler_plugins_require_trust(
        self, monkeypatch, tmp_path: Path
    ):
        root = _node_project(
            tmp_path / "proj3",
            tsc=True,
            tsconfig={"compilerOptions": {"plugins": [{"name": "ts-plugin"}]}},
        )
        target = root / "c.ts"
        target.write_text("export const c: number = 3;\n", encoding="utf-8")
        spy = _CheckerSpy((0, "", "", False))
        monkeypatch.setattr(diag, "_run_checker", spy)
        monkeypatch.setattr(diag, "project_config_execution_allowed", lambda: False)

        report = await diag.check_js_ts(
            target, target.read_text(encoding="utf-8"),
            fingerprint="fp", operation="edit", node_root=root,
        )

        assert report.status == "not_checked"
        assert report.checker == "tsc"
        assert "plugins" in report.note
        assert spy.calls == [], "tsconfig plugins were loaded without trust"


# ---------------------------------------------------------------------------
# P2-2 · machine output is parsed from the full artifact, not the preview
# ---------------------------------------------------------------------------

class TestCheckerOutputFidelity:
    async def test_full_artifact_is_parsed_not_the_preview(
        self, monkeypatch, tmp_path: Path
    ):
        from RxyCode.RxyCode1_1_0.utils.shell import shell_executor

        payload = [
            {
                "code": "E501",
                "message": "line too long " + "x" * 40000,
                "location": {"row": 3, "column": 80},
                "filename": "a.py",
            }
        ]
        full = json.dumps(payload)
        artifact = tmp_path / "ruff.json"
        artifact.write_text(full, encoding="utf-8")

        async def fake_execute(argv, workdir="", timeout=0.0):
            return {
                "success": True,
                "exit_code": 0,
                "stdout": full[:400] + "...[truncated]",
                "stdout_artifact": str(artifact),
                "stderr": "",
                "error_type": None,
            }

        monkeypatch.setattr(shell_executor, "execute_argv_async", fake_execute)

        rc, out, err, timed_out = await diag._run_checker(["ruff", "check"], tmp_path)

        assert rc == 0
        assert timed_out is False
        assert out == full, "the checker's output came back pre-truncated"
        issues = diag._parse_ruff_json(out)
        assert issues is not None and len(issues) == 1

    def test_captured_text_falls_back_to_preview(self, tmp_path: Path):
        assert diag._captured_text({"stdout": "preview"}, "stdout") == "preview"
        missing = tmp_path / "does-not-exist.txt"
        assert (
            diag._captured_text(
                {"stdout": "preview", "stdout_artifact": str(missing)}, "stdout"
            )
            == "preview"
        )


# ---------------------------------------------------------------------------
# P2-1 · all three file operations trigger diagnostics, with the right name
# ---------------------------------------------------------------------------

class TestEditDiagnosticsCoverage:
    async def test_three_operations_report_the_right_operation(
        self, monkeypatch, tmp_path: Path
    ):
        from RxyCode.RxyCode1_1_0.tools import edit as edit_mod
        from RxyCode.RxyCode1_1_0.tools import write as write_mod

        recorded: list[tuple[str, str]] = []

        async def fake_report(path, content, *, operation="edit"):
            recorded.append((Path(path).name, operation))
            return "\n[diag: ok]"

        monkeypatch.setattr(write_mod, "post_write_report", fake_report)

        files = {}
        for name in ("replace.py", "write.py", "patch.py"):
            p = tmp_path / name
            p.write_text("x = 1\n", encoding="utf-8")
            files[name] = str(p)

        await edit_mod._attach_diagnostics(
            f"[edited {files['replace.py']} - 1#### -> 1]",
            files["replace.py"],
        )
        await edit_mod._attach_diagnostics(f"[wrote {files['write.py']}]", files["write.py"])
        await edit_mod._attach_diagnostics(
            f"Patch applied to {files['patch.py']}", files["patch.py"]
        )

        assert recorded == [
            ("replace.py", "edit"),
            ("write.py", "write"),
            ("patch.py", "patch"),
        ]

    async def test_failed_edit_does_not_run_diagnostics(
        self, monkeypatch, tmp_path: Path
    ):
        from RxyCode.RxyCode1_1_0.tools import edit as edit_mod
        from RxyCode.RxyCode1_1_0.tools import write as write_mod

        called: list[str] = []

        async def fake_report(path, content, *, operation="edit"):
            called.append(str(path))
            return ""

        monkeypatch.setattr(write_mod, "post_write_report", fake_report)

        result = await edit_mod._attach_diagnostics(
            "[error editing file: oldString not found]", str(tmp_path / "nope.py")
        )

        assert result == "[error editing file: oldString not found]"
        assert called == []


# ---------------------------------------------------------------------------
# P2-3a · a parent-relative checker path is not mangled into a project path
# ---------------------------------------------------------------------------

class TestPathAttribution:
    def test_parent_relative_path_is_resolved_not_stripped(self, tmp_path: Path):
        root = tmp_path / "proj"
        (root / "src").mkdir(parents=True)
        (root / "lib").mkdir()
        outside = tmp_path / "src" / "a.ts"
        outside.parent.mkdir(parents=True)
        outside.write_text("export const a = 1;\n", encoding="utf-8")

        target_key = diag._normalise_path_key(outside, root)

        # ``../src/a.ts`` IS the target (the checker reported it from the
        # project root).  ``lstrip("./")`` used to rewrite it to ``src/a.ts``.
        assert diag._same_file("../src/a.ts", target_key, root) is True
        assert diag._same_file("../lib/a.ts", target_key, root) is False

    def test_nested_same_name_files_never_collide(self, tmp_path: Path):
        root = tmp_path / "proj4"
        a = root / "src" / "a.ts"
        b = root / "lib" / "a.ts"
        for path in (a, b):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("export const x = 1;\n", encoding="utf-8")

        key = diag._normalise_path_key(a, root)
        assert diag._same_file("src/a.ts", key, root) is True
        assert diag._same_file("lib/a.ts", key, root) is False
        assert diag._same_file("a.ts", key, root) is False


# ---------------------------------------------------------------------------
# P2-3b · composite projects must not be given --incremental false (TS6379)
# ---------------------------------------------------------------------------

class TestTscArgv:
    async def _run(self, monkeypatch, root: Path, target: Path) -> list[str]:
        spy = _CheckerSpy((0, "", "", False))
        monkeypatch.setattr(diag, "_run_checker", spy)
        monkeypatch.setattr(diag, "project_config_execution_allowed", lambda: True)

        async def fake_includes(*args, **kwargs):
            return True

        monkeypatch.setattr(diag, "_tsc_includes", fake_includes)
        report = await diag.check_js_ts(
            target, target.read_text(encoding="utf-8"),
            fingerprint="fp", operation="edit", node_root=root,
        )
        assert report.status == "pass", report.note
        assert spy.calls, "tsc never ran"
        return spy.calls[0]

    async def test_composite_project_omits_incremental_flag(
        self, monkeypatch, tmp_path: Path
    ):
        root = _node_project(
            tmp_path / "composite",
            tsc=True,
            tsconfig={"compilerOptions": {"composite": True}},
        )
        target = root / "a.ts"
        target.write_text("export const a: number = 1;\n", encoding="utf-8")

        argv = await self._run(monkeypatch, root, target)

        assert "--noEmit" in argv
        assert "--incremental" not in argv, "TS6379: composite projects may not disable incremental"

    async def test_non_composite_project_still_disables_incremental(
        self, monkeypatch, tmp_path: Path
    ):
        root = _node_project(
            tmp_path / "plain-ts",
            tsc=True,
            tsconfig={"compilerOptions": {"target": "es2020"}},
        )
        target = root / "b.ts"
        target.write_text("export const b: number = 2;\n", encoding="utf-8")

        argv = await self._run(monkeypatch, root, target)

        assert "--incremental" in argv
        assert argv[argv.index("--incremental") + 1] == "false"


# ---------------------------------------------------------------------------
# P2-5 · sandbox per-spawn temp files are consumed, never leaked
# ---------------------------------------------------------------------------

class TestSandboxCleanupConsumption:
    async def test_cleanup_files_removed_when_shell_closes(self):
        leftover = Path(os.getcwd()) / f"_round4_cleanup_{uuid.uuid4().hex}.tmp"
        leftover.write_text("seatbelt profile", encoding="utf-8")

        def wrapper(argv, cwd):
            return ps.ShellSandboxPlan(argv=list(argv), cleanup=(leftover,))

        await ps.release_all()
        shell = await ps.acquire_shell(
            identity="round4-cleanup-close", cwd=os.getcwd(), sandbox_command=wrapper
        )
        try:
            await shell.ensure_started()
            assert leftover.exists(), "cleanup file disappeared before the shell closed"
            await shell.close()
            assert not leftover.exists(), "sandbox temp file leaked after shell close"
        finally:
            await ps.release_all()
            leftover.unlink(missing_ok=True)

    async def test_cleanup_files_removed_when_startup_fails(self):
        leftover = Path(os.getcwd()) / f"_round4_cleanup_{uuid.uuid4().hex}.tmp"
        leftover.write_text("seatbelt profile", encoding="utf-8")

        def wrapper(argv, cwd):
            return ps.ShellSandboxPlan(
                argv=["rxy-round4-definitely-not-a-real-binary"], cleanup=(leftover,)
            )

        await ps.release_all()
        shell = await ps.acquire_shell(
            identity="round4-cleanup-fail", cwd=os.getcwd(), sandbox_command=wrapper
        )
        try:
            with pytest.raises(ps.ShellStartupError):
                await shell.ensure_started()
            assert not leftover.exists(), "sandbox temp file leaked on startup failure"
        finally:
            await ps.release_all()
            leftover.unlink(missing_ok=True)

    async def test_cleanup_files_removed_by_close_even_when_never_started(self):
        leftover = Path(os.getcwd()) / f"_round4_cleanup_{uuid.uuid4().hex}.tmp"
        leftover.write_text("seatbelt profile", encoding="utf-8")

        await ps.release_all()
        shell = await ps.acquire_shell(identity="round4-cleanup-unstarted", cwd=os.getcwd())
        try:
            shell._sandbox_cleanup = (leftover,)
            await shell.close()
            assert not leftover.exists()
        finally:
            await ps.release_all()
            leftover.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# P2-6 · a cancelled spawn must not leak the Windows Job handle
# ---------------------------------------------------------------------------

class TestJobHandleOwnership:
    async def test_cancelled_spawn_closes_the_job_handle(self, monkeypatch):
        plan = ps.ShellSandboxPlan(
            argv=["fake-shell"], wrapped=types.SimpleNamespace(job_plan=object())
        )
        closed: list[int] = []

        async def boom(*args, **kwargs):
            raise asyncio.CancelledError()

        monkeypatch.setattr(asyncio, "create_subprocess_exec", boom)
        monkeypatch.setattr(ps, "_close_sandbox_job", lambda handle: closed.append(handle))

        import importlib

        manager = importlib.import_module("RxyCode.RxyCode1_1_0.core.sandbox.manager")
        monkeypatch.setattr(manager, "open_sandbox_job", lambda wrapped: 4242)

        await ps.release_all()
        shell = await ps.acquire_shell(
            identity="round4-job-cancel",
            cwd=os.getcwd(),
            sandbox_command=lambda argv, cwd: plan,
        )
        try:
            with pytest.raises(asyncio.CancelledError):
                await shell.ensure_started()
            assert closed == [4242], "Job handle leaked when the spawn was cancelled"
            assert shell._job_handle == 0
            assert shell._process is None
        finally:
            await ps.release_all()

    @pytest.mark.skipif(not WINDOWS, reason="Job objects are Windows-only")
    async def test_successful_spawn_transfers_job_ownership_to_close(self, monkeypatch):
        plan = ps.ShellSandboxPlan(
            argv=[sys.executable, "-c", "import time; time.sleep(30)"],
            wrapped=types.SimpleNamespace(job_plan=object()),
        )
        closed: list[int] = []

        monkeypatch.setattr(ps, "_close_sandbox_job", lambda handle: closed.append(handle))

        import importlib

        manager = importlib.import_module("RxyCode.RxyCode1_1_0.core.sandbox.manager")
        monkeypatch.setattr(manager, "open_sandbox_job", lambda wrapped: 777)
        monkeypatch.setattr(manager, "bind_spawned_process", lambda handle, pid: None)

        await ps.release_all()
        shell = await ps.acquire_shell(
            identity="round4-job-owned",
            cwd=os.getcwd(),
            sandbox_command=lambda argv, cwd: plan,
        )
        try:
            await shell.ensure_started()
            assert closed == [], "close() must own the handle after a successful spawn"
            await shell.close()
            assert closed == [777], "the owned Job handle was never closed"
        finally:
            await ps.release_all()


# ---------------------------------------------------------------------------
# P2-4 / P2-7 · sub-agents release their shell and inherit the parent cwd
# ---------------------------------------------------------------------------

@pytest.fixture
def child_runtime():
    """A read-only ChildRuntime whose child agent is a scripted fake."""
    from RxyCode.RxyCode1_1_0.core.subagents.runtime import create_child_runtime
    from RxyCode.RxyCode1_1_0.core.subagents.sessions import create_child_session
    from RxyCode.RxyCode1_1_0.protocol.subagents import (
        AgentDefinition,
        AgentMode,
        EffectiveTaskPolicy,
        PermissionSpec,
        PermissionVerdict,
        TaskPermissionSpec,
        TaskRequest,
        ToolPermission,
        TriggerKind,
        WorkspaceMode,
        WorkspaceScope,
    )

    class FakeChildAgent:
        def __init__(self) -> None:
            self.session_id = ""
            self.effect = ""

        def set_session(self, session_id: str) -> str:
            self.session_id = session_id
            return session_id

        async def run(self, prompt: str, *, mode: str = "build", effect: str = "auto") -> str:
            self.effect = effect
            return "child done"

        def cancel(self) -> bool:
            return True

    definition = AgentDefinition(
        id="general",
        description="test child",
        mode=AgentMode.SUBAGENT,
        prompt="You are an isolated read-only specialist.",
        permission=PermissionSpec(
            read=ToolPermission.from_raw("allow"),
            edit=ToolPermission.from_raw("deny"),
            bash=ToolPermission.from_raw("deny"),
        ),
        task_permission=TaskPermissionSpec(default_verdict=PermissionVerdict.DENY),
        workspace_scope=WorkspaceMode.READ_ONLY,
    )
    request = TaskRequest(
        parent_session_id="primary",
        agent_id="general",
        prompt="inspect only",
        trigger=TriggerKind.AUTOMATIC,
    )
    session = create_child_session(
        request,
        EffectiveTaskPolicy(
            permission=definition.permission,
            workspace=WorkspaceScope(mode=WorkspaceMode.READ_ONLY),
        ),
        definition=definition,
    )
    runtime = create_child_runtime(definition, session)
    agent = FakeChildAgent()
    runtime.set_agent_factory(lambda _model: agent)
    runtime._fake_agent = agent  # test-side handle
    return runtime


class TestChildWorkingDirectoryBinding:
    async def test_child_executes_in_the_parent_cwd(self, child_runtime, tmp_path: Path):
        from RxyCode.RxyCode1_1_0.core.session_runtime import (
            bind_session,
            current_working_directory,
            reset_session_binding,
            set_working_directory,
        )

        parent_dir = tmp_path / "parent-cwd"
        parent_dir.mkdir()
        assert parent_dir.resolve() != Path.cwd().resolve()
        parent_session = f"round4-parent-{uuid.uuid4().hex}"

        token = bind_session(parent_session)
        try:
            set_working_directory(parent_dir)
            result = await child_runtime.execute("inspect only")
        finally:
            reset_session_binding(token)

        from RxyCode.RxyCode1_1_0.protocol.subagents import ChildStatus

        assert result.status is ChildStatus.COMPLETED

        # The child's session-scoped cwd is the parent's cwd, not the process
        # cwd that `current_working_directory()` would have returned after the
        # child session binding replaced the parent's.
        child_token = bind_session(child_runtime.session_id)
        try:
            assert current_working_directory().resolve() == parent_dir.resolve()
        finally:
            reset_session_binding(child_token)


class TestSubagentShellReclaim:
    async def test_release_reclaims_the_child_shell(self, child_runtime):
        from RxyCode.RxyCode1_1_0.core.session_runtime import (
            bind_session,
            reset_session_binding,
        )

        await ps.release_all()
        token = bind_session(child_runtime.session_id)
        try:
            identity = ps.state_identity()
            await ps.acquire_shell(identity=identity, cwd=os.getcwd())
            assert identity in ps.active_identities()

            child_runtime.release()
            assert identity not in ps.active_identities(), "normal completion kept the shell"

            # Idempotent: a second release must be a no-op, not an error.
            child_runtime.release()
        finally:
            reset_session_binding(token)
            await asyncio.sleep(0.2)
            await ps.release_all()

    def test_manager_releases_child_runtime_after_success(self, monkeypatch):
        from RxyCode.RxyCode1_1_0.core.subagents.builtin_agents import load_builtin_agents
        from RxyCode.RxyCode1_1_0.core.subagents.manager import ChildSessionManager
        from RxyCode.RxyCode1_1_0.core.subagents.modes import (
            SubagentConfig,
            SubagentFeatureFlags,
        )
        from RxyCode.RxyCode1_1_0.protocol.subagents import (
            AgentDefinition,
            AgentMode,
            ChildStatus,
            PermissionVerdict,
            TaskPermissionSpec,
            TaskRequest,
            TaskResult,
            TriggerKind,
        )

        released: list[str] = []

        class FakeChild:
            def __init__(self, definition, session, *args, **kwargs):
                self.session = session

            async def execute(self, task_prompt: str):
                return TaskResult(
                    request_id="",
                    child_session_id=self.session.session_id,
                    status=ChildStatus.COMPLETED,
                    summary="ok",
                )

            def shutdown(self):
                return None

            def cancel(self):
                return True

            def release(self):
                released.append(self.session.session_id)

        def factory(definition, session, *args, **kwargs):
            child = FakeChild(definition, session)
            session._cancel_callback = child.cancel
            return child

        monkeypatch.setattr(
            "RxyCode.RxyCode1_1_0.core.subagents.manager.create_child_runtime", factory
        )

        registry = load_builtin_agents()
        registry.register_builtin(
            AgentDefinition(
                id="primary",
                description="主入口",
                mode=AgentMode.PRIMARY,
                task_permission=TaskPermissionSpec(
                    allowed_agents=("explore", "reviewer", "general"),
                    default_verdict=PermissionVerdict.DENY,
                ),
            )
        )
        manager = ChildSessionManager(
            registry=registry,
            config=SubagentConfig(
                flags=SubagentFeatureFlags(
                    subagents_enabled=True,
                    subagents_task=True,
                    subagents_mention=True,
                    subagents_child_tasks=True,
                )
            ),
        )
        request = TaskRequest(
            parent_session_id="ses_primary_1",
            agent_id="explore",
            prompt="探索 core/",
            trigger=TriggerKind.AUTOMATIC,
        )

        result = asyncio.run(manager.dispatch(request))

        assert result.status is ChildStatus.COMPLETED
        assert released == [result.child_session_id], (
            "a successful child never released its runtime resources"
        )

    async def test_manager_releases_the_real_child_shell_after_success(
        self, monkeypatch
    ):
        """The real Manager -> ChildRuntime -> ManagedShell chain must reap.

        Audit (round 4): the shell survived a *completed* child because only
        ``shutdown()`` reclaimed it and shutdown only ran on cancellation.  This
        drives the real runtime and acquires a real shell inside the child,
        then asserts the registry is empty after dispatch returns.
        """
        from RxyCode.RxyCode1_1_0.core.subagents.builtin_agents import load_builtin_agents
        from RxyCode.RxyCode1_1_0.core.subagents.manager import ChildSessionManager
        from RxyCode.RxyCode1_1_0.core.subagents.modes import (
            SubagentConfig,
            SubagentFeatureFlags,
        )
        from RxyCode.RxyCode1_1_0.core.subagents.runtime import create_child_runtime
        from RxyCode.RxyCode1_1_0.protocol.subagents import (
            AgentDefinition,
            AgentMode,
            ChildStatus,
            PermissionVerdict,
            TaskPermissionSpec,
            TaskRequest,
            TriggerKind,
        )

        class ShellAgent:
            """Stands in for AgentV2: acquires the child's shell, then answers."""

            def __init__(self) -> None:
                self.session_id = ""
                self.shell_identity = ""

            def set_session(self, session_id: str) -> str:
                self.session_id = session_id
                return session_id

            async def run(self, prompt: str, *, mode: str = "build", effect: str = "auto"):
                self.shell_identity = ps.state_identity()
                await ps.acquire_shell(identity=self.shell_identity, cwd=os.getcwd())
                return "shell acquired"

            def cancel(self) -> bool:
                return True

        def factory(definition, session, *args, **kwargs):
            runtime = create_child_runtime(definition, session, *args, **kwargs)
            runtime.set_agent_factory(lambda _model: ShellAgent())
            return runtime

        monkeypatch.setattr(
            "RxyCode.RxyCode1_1_0.core.subagents.manager.create_child_runtime", factory
        )

        registry = load_builtin_agents()
        registry.register_builtin(
            AgentDefinition(
                id="primary",
                description="主入口",
                mode=AgentMode.PRIMARY,
                task_permission=TaskPermissionSpec(
                    allowed_agents=("explore", "reviewer", "general"),
                    default_verdict=PermissionVerdict.DENY,
                ),
            )
        )
        manager = ChildSessionManager(
            registry=registry,
            config=SubagentConfig(
                flags=SubagentFeatureFlags(
                    subagents_enabled=True,
                    subagents_task=True,
                    subagents_mention=True,
                    subagents_child_tasks=True,
                )
            ),
        )
        request = TaskRequest(
            parent_session_id="ses_primary_real",
            agent_id="explore",
            prompt="探索 core/",
            trigger=TriggerKind.AUTOMATIC,
        )

        await ps.release_all()
        try:
            result = await manager.dispatch(request)

            assert result.status is ChildStatus.COMPLETED
            await asyncio.sleep(0.2)  # let the scheduled tree shutdown run
            leftovers = [
                identity
                for identity in ps.active_identities()
                if identity == result.child_session_id
                or identity.startswith(f"{result.child_session_id}::")
            ]
            assert leftovers == [], "a completed child kept its managed shell"
        finally:
            await ps.release_all()


class TestReadOnlyChildBashChain:
    """P1-04 through the REAL child permission chain, not the helper alone."""

    async def test_executable_expression_is_blocked_for_read_only_child(self):
        from RxyCode.RxyCode1_1_0.core.subagents.runtime import create_child_runtime
        from RxyCode.RxyCode1_1_0.core.subagents.sessions import create_child_session
        from RxyCode.RxyCode1_1_0.core.subagents.workspace import NoWorkspaceScopeError
        from RxyCode.RxyCode1_1_0.protocol.subagents import (
            AgentDefinition,
            AgentMode,
            EffectiveTaskPolicy,
            PermissionSpec,
            PermissionVerdict,
            TaskPermissionSpec,
            TaskRequest,
            ToolPermission,
            TriggerKind,
            WorkspaceMode,
            WorkspaceScope,
        )

        definition = AgentDefinition(
            id="general",
            description="read-only child",
            mode=AgentMode.SUBAGENT,
            prompt="read only",
            permission=PermissionSpec(
                read=ToolPermission.from_raw("allow"),
                bash=ToolPermission.from_raw("allow"),
                edit=ToolPermission.from_raw("deny"),
            ),
            task_permission=TaskPermissionSpec(default_verdict=PermissionVerdict.DENY),
            workspace_scope=WorkspaceMode.READ_ONLY,
        )
        session = create_child_session(
            TaskRequest(
                parent_session_id="primary",
                agent_id="general",
                prompt="read only",
                trigger=TriggerKind.AUTOMATIC,
            ),
            EffectiveTaskPolicy(
                permission=definition.permission,
                workspace=WorkspaceScope(mode=WorkspaceMode.READ_ONLY),
            ),
            definition=definition,
        )
        runtime = create_child_runtime(definition, session)

        # A real read-only probe still passes ...
        assert runtime.check_tool("bash", {"command": "ls -la"}) is True
        # ... while an executable expression is refused by the workspace gate.
        with pytest.raises(NoWorkspaceScopeError):
            runtime.check_tool(
                "bash",
                {"command": 'echo ([IO.File]::WriteAllText("C:/tmp/pwn.txt","x"))'},
            )

