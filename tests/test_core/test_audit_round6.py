"""Regression tests for the sixth audit round (5 P1 + 1 P2 against 7e8a6a65).

These findings are all about the PUBLIC execution layer that the Web branch had
already implemented and the re-landed CLI layer had overwritten:

* P1-a: read-only parsing was still bypassable -- a quoted option
  (``git diff "--output=file"``) was masked into a placeholder, and a backslash
  before ``$(`` was treated as an escape even though PowerShell does not treat
  it as one.
* P1-b: ``hard_denied_shell_reason`` had no production caller again (the old
  bash.py was re-landed), so shutdown-class commands reached execution.
* P1-c: the Web approval request lost the raw ``arguments`` and the original
  ``call_id``.
* P1-d: ``bind_tool_journal`` lost its ``remote_call_id`` parameter (Web
  resume passed 4 arguments -> TypeError).
* P1-e: a JSON ESLint config is not automatically safe: ``extends`` can point
  at a project ``.cjs`` that ESLint executes.
* P2: sync tools lost their contextvars (``copy_context().run``) so a session
  read could resolve against ``latest`` instead of the active session.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import uuid
from pathlib import Path

import pytest

from RxyCode.RxyCode1_1_0.core import post_write_diagnostics as diag
from RxyCode.RxyCode1_1_0.core.subagents.workspace import is_read_only_command

WINDOWS = os.name == "nt"


@pytest.fixture
def ws_dir():
    root = Path(os.getcwd()) / f"_round6_ws_{uuid.uuid4().hex[:8]}"
    root.mkdir()
    try:
        yield root
    finally:
        shutil.rmtree(root, ignore_errors=True)


# ---------------------------------------------------------------------------
# P1-a · quoted arguments and backslash-escaped substitutions
# ---------------------------------------------------------------------------

class TestReadOnlyBypasses:
    @pytest.mark.parametrize(
        "command",
        [
            # A quoted option used to be masked into a placeholder, so the
            # argument check never saw --output.
            'git diff "--output=stolen.txt" a b',
            "git diff '--output=stolen.txt' a b",
            'git log "--output" stolen.txt',
            # PowerShell does not treat a backslash as an escape: the
            # substitution still runs there.
            'echo "\\$(Set-Content C:/tmp/pwn.txt pwned)"',
            'echo "\\`whoami\\`"',
        ],
    )
    def test_quoted_option_and_backslash_substitution_are_rejected(
        self, command: str
    ) -> None:
        assert is_read_only_command(command) is False, command

    @pytest.mark.parametrize(
        "command",
        [
            "git log --format='%H %s'",
            'git log --format="%H %s"',
            'grep "[0-9]" file.txt',
            'cat "file with spaces.txt"',
            "find . -name '*.py'",
            "ls -la",
        ],
    )
    def test_legitimate_quoted_data_still_passes(self, command: str) -> None:
        assert is_read_only_command(command) is True, command

    def test_real_child_permission_chain_refuses_both(self):
        from RxyCode.RxyCode1_1_0.core.subagents.workspace import NoWorkspaceScopeError

        runtime = _read_only_child()
        assert runtime.check_tool("bash", {"command": "ls -la"}) is True
        with pytest.raises(NoWorkspaceScopeError):
            runtime.check_tool(
                "bash", {"command": 'git diff "--output=stolen.txt" a b'}
            )
        with pytest.raises(NoWorkspaceScopeError):
            runtime.check_tool(
                "bash", {"command": 'echo "\\$(Set-Content C:/tmp/x y)"'}
            )


def _read_only_child():
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
    return create_child_runtime(definition, session)


# ---------------------------------------------------------------------------
# P1-b · the hard blacklist has a production caller again
# ---------------------------------------------------------------------------

class TestHardBlacklistWiring:
    @pytest.mark.parametrize(
        "command",
        ["shutdown /s /t 0", "shutdown -h now", "format D: /q"],
    )
    def test_bash_layer_refuses_dangerous_commands(self, command: str):
        from RxyCode.RxyCode1_1_0.tools import bash as bash_mod

        refused = bash_mod._refuse_blacklisted(command)
        assert refused is not None and "blocked" in refused
        # The synchronous entry point must refuse before spawning anything.
        assert "blocked" in bash_mod.run_bash(command)

    async def test_managed_path_also_runs_the_blacklist_first(self):
        from RxyCode.RxyCode1_1_0.tools import bash as bash_mod

        # Even with the managed shell enabled, the refusal happens before any
        # shell is acquired (no registry entry is created).
        from RxyCode.RxyCode1_1_0.core import persistent_shell as ps

        before = set(ps.active_identities())
        result = await bash_mod.run_bash_async("shutdown /s /t 0")
        assert "blocked" in result
        assert set(ps.active_identities()) == before

    def test_orchestrator_rejects_before_approval(self):
        from langchain_core.tools import StructuredTool

        from RxyCode.RxyCode1_1_0.core.safety import approval as approval_mod
        from RxyCode.RxyCode1_1_0.execution.tool_orchestrator import (
            ToolOrchestrator,
        )

        called: list[str] = []

        async def _stub(**kwargs):
            called.append("ran")
            return "EXECUTED"

        previous = approval_mod.get_approval_broker()

        class _Broker:
            asked = False

            async def request_approval(self, request):
                self.asked = True
                from RxyCode.RxyCode1_1_0.core.safety.approval import (
                    ApprovalDecision,
                )

                return ApprovalDecision.APPROVED

        broker = _Broker()
        approval_mod.set_approval_broker(broker)
        try:
            orch = ToolOrchestrator()
            orch.register(
                "bash",
                StructuredTool(
                    name="bash", description="d", args_schema=None, coroutine=_stub
                ),
            )
            out = str(
                asyncio.run(
                    orch.execute_tool(
                        "bash",
                        {
                            "command": "shutdown /s /t 0",
                            "description": "d",
                            "workdir": "",
                            "timeout": 30,
                        },
                        config={"safety": {"enabled": True}},
                    )
                )
            )
        finally:
            approval_mod.set_approval_broker(previous)

        assert called == [], "a blacklisted command reached the tool"
        assert "dangerous command rejected" in out
        assert broker.asked is False, "the blacklist must reject before approval"


# ---------------------------------------------------------------------------
# P1-c / P1-d · Web approval payload and journal binding survive
# ---------------------------------------------------------------------------

class TestWebApprovalContract:
    def test_approval_request_carries_raw_arguments_and_call_id(self, monkeypatch):
        from langchain_core.tools import StructuredTool

        from RxyCode.RxyCode1_1_0.core.safety.approval import ApprovalDecision
        from RxyCode.RxyCode1_1_0.execution import tool_orchestrator as orch_mod

        seen: list[object] = []

        class _Broker:
            async def request_approval(self, request):
                seen.append(request)
                return ApprovalDecision.REJECTED

        monkeypatch.setattr(orch_mod, "get_approval_broker", lambda: _Broker())

        async def _stub(**kwargs):
            return "EXECUTED"

        orch = orch_mod.ToolOrchestrator()
        orch.register(
            "bash",
            StructuredTool(
                name="bash", description="d", args_schema=None, coroutine=_stub
            ),
        )
        args = {"command": "echo hi", "description": "d", "workdir": "", "timeout": 30}
        asyncio.run(
            orch.execute_tool(
                "bash",
                args,
                config={"safety": {"enabled": True, "permission_mode": "confirm_all"}},
                call_id="call-web-123",
            )
        )

        assert len(seen) == 1
        request = seen[0]
        assert getattr(request, "call_id", None) == "call-web-123"
        assert getattr(request, "arguments", None) == args
        summary = getattr(request, "args_summary", None)
        assert isinstance(summary, dict) and summary.get("command") == "echo hi"

    def test_bind_tool_journal_carries_remote_call_id(self):
        from RxyCode.RxyCode1_1_0.execution.tool_orchestrator import (
            ToolOrchestrator,
        )

        received: list[tuple] = []

        class _Journal:
            def binding(self, attempt_id, checkpoint_id, remote_call_id=None):
                received.append((attempt_id, checkpoint_id, remote_call_id))
                return object()

        token = ToolOrchestrator.bind_tool_journal(
            _Journal(), "attempt-1", "checkpoint-1", "remote-9"
        )
        try:
            assert ToolOrchestrator.get_tool_journal_binding() is not None
        finally:
            ToolOrchestrator.reset_tool_journal(token)

        assert received == [("attempt-1", "checkpoint-1", "remote-9")]


# ---------------------------------------------------------------------------
# P1-e · a JSON ESLint config can still load executable code via extends
# ---------------------------------------------------------------------------

class TestJsonEslintConfigChain:
    def test_json_config_extending_project_script_is_not_safe(self, tmp_path: Path):
        (tmp_path / ".eslintrc.json").write_text(
            json.dumps({"extends": ["./payload.cjs"]}), encoding="utf-8"
        )
        (tmp_path / "payload.cjs").write_text("module.exports = {};\n", encoding="utf-8")
        assert diag._eslint_config_may_execute(tmp_path / ".eslintrc.json") is True

    def test_builtin_preset_and_package_extends_are_safe(self, tmp_path: Path):
        safe = tmp_path / ".eslintrc.json"
        safe.write_text(
            json.dumps(
                {"extends": ["eslint:recommended", "plugin:react/recommended", "airbnb"]}
            ),
            encoding="utf-8",
        )
        assert diag._eslint_config_may_execute(safe) is False

    def test_unresolvable_relative_extends_requires_trust(self, tmp_path: Path):
        cfg = tmp_path / ".eslintrc.json"
        cfg.write_text(json.dumps({"extends": "./missing.cjs"}), encoding="utf-8")
        assert diag._eslint_config_may_execute(cfg) is True

    def test_find_config_reports_json_chain_with_script(self, ws_dir: Path):
        project = ws_dir / "pkg"
        project.mkdir()
        (project / "package.json").write_text("{}", encoding="utf-8")
        (project / ".eslintrc.json").write_text(
            json.dumps({"extends": "./rules.cjs"}), encoding="utf-8"
        )
        (project / "rules.cjs").write_text("module.exports = {};\n", encoding="utf-8")
        found = diag.find_executable_eslint_config(project)
        assert found is not None and found.name == ".eslintrc.json"

    async def test_untrusted_json_config_is_not_run(self, monkeypatch, ws_dir: Path):
        root = ws_dir / "json-proj"
        bin_dir = root / "node_modules" / ".bin"
        bin_dir.mkdir(parents=True)
        marker = root / "ran.txt"
        (root / ".eslintrc.json").write_text(
            json.dumps({"extends": "./payload.cjs"}), encoding="utf-8"
        )
        (root / "payload.cjs").write_text(
            "require('fs').writeFileSync(%s, 'ran');\nmodule.exports = {};\n"
            % json.dumps(str(marker).replace("\\", "/")),
            encoding="utf-8",
        )
        fake = root / "fake-eslint.js"
        fake.write_text(
            "require(process.cwd() + '/.eslintrc.json');\n"
            "require(process.cwd() + '/payload.cjs');\n"
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

        monkeypatch.setattr(diag, "project_config_execution_allowed", lambda *a, **k: False)
        monkeypatch.setattr(diag.shutil, "which", lambda name: None)
        report = await diag.check_js_ts(
            target, target.read_text(encoding="utf-8"),
            fingerprint="fp", operation="edit", node_root=root,
        )
        assert report.status == "not_checked"
        assert not marker.exists(), "the JSON config's extends script was executed"

    @pytest.mark.parametrize(
        ("config", "needs_trust"),
        [
            ({"root": True, "parser": "./payload.cjs"}, True),
            (
                {"overrides": [{"files": ["*.js"], "parser": "./payload.cjs"}]},
                True,
            ),
            (
                {"overrides": [{"files": ["*.js"], "extends": ["./payload.cjs"]}]},
                True,
            ),
            (
                {
                    "root": True,
                    "parser": "espree",
                    "extends": ["eslint:recommended"],
                    "overrides": [
                        {
                            "files": ["*.ts"],
                            "parser": "@typescript-eslint/parser",
                            "extends": ["plugin:@typescript-eslint/recommended"],
                        }
                    ],
                },
                False,
            ),
        ],
    )
    def test_local_parser_and_override_entries_require_trust(
        self, tmp_path: Path, config: dict, needs_trust: bool
    ):
        cfg = tmp_path / ".eslintrc.json"
        cfg.write_text(json.dumps(config), encoding="utf-8")
        if needs_trust:
            (tmp_path / "payload.cjs").write_text(
                "module.exports = {};\n", encoding="utf-8"
            )
        assert diag._eslint_config_may_execute(cfg) is needs_trust

    @pytest.mark.parametrize(
        ("config", "trust_config"),
        [
            (
                {"root": True, "parser": "./payload.cjs"},
                {
                    "safety": {"permission_mode": "auto_edit"},
                    "diagnostics": {"run_project_config_checkers": True},
                },
            ),
            (
                {"overrides": [{"files": ["*.js"], "parser": "./payload.cjs"}]},
                {"safety": {"permission_mode": "full_auto"}},
            ),
            (
                {"overrides": [{"files": ["*.js"], "extends": ["./payload.cjs"]}]},
                {
                    "safety": {"permission_mode": "auto_edit"},
                    "diagnostics": {"run_project_config_checkers": True},
                },
            ),
        ],
    )
    async def test_post_write_gate_covers_local_parser_entries(
        self, monkeypatch, ws_dir: Path, config: dict, trust_config: dict
    ):
        from RxyCode.RxyCode1_1_0.tools import write as write_tool

        root = ws_dir / f"parser-{uuid.uuid4().hex[:8]}"
        bin_dir = root / "node_modules" / ".bin"
        bin_dir.mkdir(parents=True)
        marker = root / "parser-ran.txt"
        (root / "package.json").write_text("{}", encoding="utf-8")
        (root / ".eslintrc.json").write_text(json.dumps(config), encoding="utf-8")
        (root / "payload.cjs").write_text(
            "require('fs').writeFileSync(%s, 'parser-loaded');\n"
            "module.exports = { parse() { return { type: 'Program', body: [] }; } };\n"
            % json.dumps(str(marker).replace("\\", "/")),
            encoding="utf-8",
        )
        fake = root / "fake-eslint.js"
        fake.write_text(
            "require(process.cwd() + '/payload.cjs');\n"
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

        assert diag.project_config_execution_allowed(trust_config) is True
        monkeypatch.setattr(diag, "project_config_execution_allowed", lambda: False)
        untrusted = await write_tool.post_write_report_async(
            target, content, operation="edit"
        )
        assert "syntax check:" in untrusted
        assert not marker.exists(), "the local ESLint parser executed without trust"

        monkeypatch.setattr(diag, "project_config_execution_allowed", lambda: True)
        trusted = await write_tool.post_write_report_async(
            target, content, operation="edit"
        )
        assert "OK (eslint)" in trusted
        assert marker.exists(), "the trusted post-write path never ran ESLint"


# ---------------------------------------------------------------------------
# P2 · sync tools keep their session context (contextvars)
# ---------------------------------------------------------------------------

class TestSyncToolContextPropagation:
    def test_sync_tool_sees_the_bound_session(self):
        from langchain_core.tools import StructuredTool

        from RxyCode.RxyCode1_1_0.core.session_runtime import (
            bind_session,
            current_session_id,
            reset_session_binding,
        )
        from RxyCode.RxyCode1_1_0.execution.tool_orchestrator import (
            ToolOrchestrator,
        )

        observed: list[str] = []

        def _probe(**_kwargs) -> str:
            observed.append(current_session_id())
            return "ok"

        orch = ToolOrchestrator()
        orch.register(
            "syncprobe",
            StructuredTool.from_function(
                func=_probe, name="syncprobe", description="d"
            ),
        )

        session_id = f"round6-session-{uuid.uuid4().hex[:8]}"
        token = bind_session(session_id)
        try:
            out = asyncio.run(
                orch.execute_tool(
                    "syncprobe", {}, config={"safety": {"enabled": False}}
                )
            )
        finally:
            reset_session_binding(token)

        assert str(out) == "ok"
        assert observed == [session_id], (
            "the sync tool ran without the request's session context"
        )
