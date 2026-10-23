"""Regression tests for the fifth audit round (3 P1 + 1 P2 against 614d805d).

These are NEW findings, not the previous round's list:

* P1-a: ``$()`` inside DOUBLE quotes was masked as literal data, so
  ``echo "$(Set-Content marker x)"`` passed ``is_read_only_command`` and the
  read-only child could write a file.  ``git diff --output=<file>`` did the same
  through a whitelisted command's *arguments*.
* P1-b: the diagnostics trust gate read the global ``permission_mode`` and
  ignored the request-level override, so a prompt narrowed to ``auto_edit``
  still executed the project's ESLint config under a global ``full_auto``.
* P1-c: the gate only looked for a config in ``node_root``; ESLint resolves
  upward, so a nested package inherited and executed the parent's config.
* P2: commented (JSONC) tsconfig was parsed with plain ``json.loads``, failed,
  was judged non-composite, and got ``--incremental false`` -> TS6379 on a
  project where tsc originally exited 0.
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
    """Scratch directory INSIDE the execution workspace (sandbox boundary)."""
    root = Path(os.getcwd()) / f"_round5_ws_{uuid.uuid4().hex[:8]}"
    root.mkdir()
    try:
        yield root
    finally:
        shutil.rmtree(root, ignore_errors=True)


class _CheckerSpy:
    def __init__(self, result=(0, "", "", False)):
        self.calls: list[list[str]] = []
        self._result = result

    async def __call__(self, argv, cwd, *, timeout=0.0):
        self.calls.append(list(argv))
        return self._result


# ---------------------------------------------------------------------------
# P1-a · double quotes are NOT literal: $() / backticks still execute
# ---------------------------------------------------------------------------

class TestDoubleQuoteInterpolation:
    @pytest.mark.parametrize(
        "command",
        [
            'echo "$(Set-Content C:/tmp/pwn.txt pwned)"',
            'echo "$(rm -rf data)"',
            'cat "$(whoami)"',
            'grep "$(rm x)" file.txt',
            'ls "$(Remove-Item C:/tmp/x -Force)"',
            "echo \"`whoami`\"",
            'git status "$(touch pwned)"',
            'echo "${env:PATH}"',
            # Braced expansions can hide a command substitution in bash
            # (``${x:-$(cmd)}``): cannot prove it is data, so refuse.
            'echo "${HOME}"',
        ],
    )
    def test_executable_inside_double_quotes_is_rejected(self, command: str) -> None:
        assert is_read_only_command(command) is False, command

    @pytest.mark.parametrize(
        "command",
        [
            'grep "[0-9]" file.txt',
            "grep -E '^(Name|Version)' file.txt",
            'cat "file with spaces.txt"',
            "git log --format='%H %s'",
            # Single quotes are literal in bash and PowerShell: $() inside them
            # is data, not a command substitution.
            "echo '$(rm -rf x)'",
        ],
    )
    def test_literal_quoted_data_is_still_allowed(self, command: str) -> None:
        assert is_read_only_command(command) is True, command


# ---------------------------------------------------------------------------
# P1-a · a whitelisted command's ARGUMENTS must not write / execute
# ---------------------------------------------------------------------------

class TestArgumentsCannotWrite:
    @pytest.mark.parametrize(
        "command",
        [
            "git diff --no-index --output=stolen.txt a b",
            "git diff --output stolen.txt a b",
            "git log --output=out.txt",
            "git show --output=out.txt HEAD",
            "find . -name '*.py' -delete",
            "find . -name '*.py' -exec rm {} ;",
            "find . -fprint out.txt",
            "env rm -rf data",
            "rg --pre ./pre.sh pattern",
            "git -c core.pager=rm log",
            "git --config-env=diff.external=EVIL diff",
            "git diff --ext-diff",
        ],
    )
    def test_write_or_execute_arguments_are_rejected(self, command: str) -> None:
        assert is_read_only_command(command) is False, command

    @pytest.mark.parametrize(
        "command",
        [
            "git diff --stat",
            "git log -p",
            "git log --color=always",
            "grep -o pattern file.txt",
            "find . -name '*.py'",
            "ls -la",
            "echo hi",
            "env",
        ],
    )
    def test_harmless_arguments_stay_allowed(self, command: str) -> None:
        assert is_read_only_command(command) is True, command


# ---------------------------------------------------------------------------
# P1-b · the trust gate uses the EFFECTIVE (request-level) permission mode
# ---------------------------------------------------------------------------

class TestRequestLevelPermissionMode:
    @staticmethod
    def _global_config(monkeypatch, permission_mode: str):
        import importlib

        settings = importlib.import_module("RxyCode.RxyCode1_1_0.config.settings")
        monkeypatch.setattr(
            settings,
            "load_config",
            lambda: {"safety": {"permission_mode": permission_mode}},
        )

    def test_request_override_downgrade_beats_global_full_auto(self, monkeypatch):
        from RxyCode.RxyCode1_1_0.execution.tool_orchestrator import (
            permission_mode_override,
        )

        self._global_config(monkeypatch, "full_auto")
        with permission_mode_override("auto_edit"):
            assert diag.project_config_execution_allowed() is False, (
                "a request narrowed to auto_edit inherited full_auto trust"
            )

    def test_request_override_upgrade_grants_trust(self, monkeypatch):
        from RxyCode.RxyCode1_1_0.execution.tool_orchestrator import (
            permission_mode_override,
        )

        self._global_config(monkeypatch, "confirm_all")
        with permission_mode_override("full_auto"):
            assert diag.project_config_execution_allowed() is True

    def test_global_mode_is_used_without_an_override(self, monkeypatch):
        self._global_config(monkeypatch, "full_auto")
        assert diag.project_config_execution_allowed() is True
        self._global_config(monkeypatch, "auto_edit")
        assert diag.project_config_execution_allowed() is False

    async def test_downgraded_request_does_not_execute_eslint(
        self, monkeypatch, tmp_path: Path
    ):
        from RxyCode.RxyCode1_1_0.execution.tool_orchestrator import (
            permission_mode_override,
        )

        root = tmp_path / "proj"
        (root / "node_modules" / ".bin").mkdir(parents=True)
        (root / "node_modules" / ".bin" / "eslint").write_text("", encoding="utf-8")
        (root / "eslint.config.js").write_text("module.exports = [];\n", encoding="utf-8")
        target = root / "a.js"
        target.write_text("const x = 1;\n", encoding="utf-8")
        spy = _CheckerSpy((0, "[]", "", False))
        monkeypatch.setattr(diag, "_run_checker", spy)
        monkeypatch.setattr(diag.shutil, "which", lambda name: None)
        self._global_config(monkeypatch, "full_auto")

        with permission_mode_override("auto_edit"):
            report = await diag.check_js_ts(
                target, target.read_text(encoding="utf-8"),
                fingerprint="fp", operation="edit", node_root=root,
            )

        assert report.status == "not_checked"
        assert all("eslint" not in Path(argv[0]).name.lower() for argv in spy.calls)


# ---------------------------------------------------------------------------
# P1-c · ESLint resolves config UPWARD; the gate must follow
# ---------------------------------------------------------------------------

class TestUpwardEslintConfig:
    def test_parent_executable_config_is_found(self, ws_dir: Path):
        parent = ws_dir / "parent"
        nested = parent / "packages" / "app"
        nested.mkdir(parents=True)
        (nested / "package.json").write_text("{}", encoding="utf-8")
        assert diag.find_executable_eslint_config(nested) is None
        (parent / "eslint.config.js").write_text("module.exports = [];\n", encoding="utf-8")
        found = diag.find_executable_eslint_config(nested)
        assert found is not None and found.name == "eslint.config.js"

    def test_data_only_parent_config_does_not_hide_nothing(self, ws_dir: Path):
        parent = ws_dir / "data-parent"
        nested = parent / "nested"
        nested.mkdir(parents=True)
        (parent / ".eslintrc.json").write_text("{}", encoding="utf-8")
        # A JSON config is data, not executable code: the safe checks may run.
        assert diag.find_executable_eslint_config(nested) is None

    async def test_untrusted_nested_project_does_not_run_parent_eslint(
        self, monkeypatch, ws_dir: Path
    ):
        parent = ws_dir / "mono"
        nested = parent / "packages" / "app"
        bin_dir = nested / "node_modules" / ".bin"
        bin_dir.mkdir(parents=True)
        (bin_dir / "eslint").write_text("", encoding="utf-8")
        (nested / "package.json").write_text("{}", encoding="utf-8")
        (parent / "eslint.config.js").write_text("module.exports = [];\n", encoding="utf-8")
        target = nested / "a.js"
        target.write_text("const x = 1;\n", encoding="utf-8")

        spy = _CheckerSpy((0, "[]", "", False))
        monkeypatch.setattr(diag, "_run_checker", spy)
        monkeypatch.setattr(diag.shutil, "which", lambda name: None)
        monkeypatch.setattr(diag, "project_config_execution_allowed", lambda *a, **k: False)

        report = await diag.check_js_ts(
            target, target.read_text(encoding="utf-8"),
            fingerprint="fp", operation="edit", node_root=nested,
        )

        assert report.status == "not_checked"
        assert report.checker == "eslint"
        assert all("eslint" not in Path(argv[0]).name.lower() for argv in spy.calls), (
            "the parent ESLint config was executed without trust"
        )

    @pytest.mark.skipif(
        shutil.which("node") is None, reason="a real node runtime is required"
    )
    async def test_real_parent_config_execution_is_gated(self, monkeypatch, ws_dir: Path):
        """The parent config is REAL code: prove it runs only when trusted."""
        parent = ws_dir / "real-mono"
        nested = parent / "packages" / "app"
        bin_dir = nested / "node_modules" / ".bin"
        bin_dir.mkdir(parents=True)
        marker = parent / "parent_config_ran.txt"
        (parent / "eslint.config.js").write_text(
            "require('fs').writeFileSync(%s, 'loaded');\nmodule.exports = [];\n"
            % json.dumps(str(marker).replace("\\", "/")),
            encoding="utf-8",
        )
        fake = nested / "fake-eslint.js"
        fake.write_text(
            "require(process.cwd() + '/../../eslint.config.js');\n"
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
        target = nested / "a.js"
        target.write_text("const x = 1;\n", encoding="utf-8")
        content = target.read_text(encoding="utf-8")

        monkeypatch.setattr(diag, "project_config_execution_allowed", lambda *a, **k: False)
        await diag.check_js_ts(
            target, content, fingerprint="fp", operation="edit", node_root=nested
        )
        assert not marker.exists(), "the parent ESLint config executed without trust"

        monkeypatch.setattr(diag, "project_config_execution_allowed", lambda *a, **k: True)
        await diag.check_js_ts(
            target, content, fingerprint="fp", operation="edit", node_root=nested
        )
        assert marker.exists(), (
            "test harness broken: the trusted run never loaded the parent config"
        )


# ---------------------------------------------------------------------------
# P1-a · the REAL child permission chain refuses both bypass shapes
# ---------------------------------------------------------------------------

class TestReadOnlyChildChainRound5:
    @staticmethod
    def _child():
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

    def test_double_quote_substitution_is_refused(self):
        from RxyCode.RxyCode1_1_0.core.subagents.workspace import NoWorkspaceScopeError

        runtime = self._child()
        assert runtime.check_tool("bash", {"command": "ls -la"}) is True
        with pytest.raises(NoWorkspaceScopeError):
            runtime.check_tool(
                "bash", {"command": 'echo "$(Set-Content C:/tmp/pwn.txt pwned)"'}
            )

    def test_output_argument_is_refused(self):
        from RxyCode.RxyCode1_1_0.core.subagents.workspace import NoWorkspaceScopeError

        runtime = self._child()
        with pytest.raises(NoWorkspaceScopeError):
            runtime.check_tool(
                "bash",
                {"command": "git diff --no-index --output=stolen.txt a b"},
            )


# ---------------------------------------------------------------------------
# P2 · JSONC tsconfig (comments / trailing commas) must still be understood
# ---------------------------------------------------------------------------
JSONC_COMPOSITE = """{
  // composite project: TS6379 if --incremental false is added
  "compilerOptions": {
    "composite": true,
    "target": "es2020", // trailing comma below
  },
}
"""


class TestJsoncTsconfig:
    def test_commented_composite_is_detected(self, tmp_path: Path):
        tsconfig = tmp_path / "tsconfig.json"
        tsconfig.write_text(JSONC_COMPOSITE, encoding="utf-8")
        assert diag._tsconfig_is_composite(tsconfig) is True

    def test_commented_non_composite_is_not_composite(self, tmp_path: Path):
        tsconfig = tmp_path / "tsconfig.json"
        tsconfig.write_text(
            '{\n  // plain project\n  "compilerOptions": {"target": "es2020",},\n}\n',
            encoding="utf-8",
        )
        assert diag._tsconfig_is_composite(tsconfig) is False

    def test_extends_chain_is_followed(self, tmp_path: Path):
        base = tmp_path / "tsconfig.base.json"
        base.write_text(
            '{\n  // base\n  "compilerOptions": {"composite": true},\n}\n',
            encoding="utf-8",
        )
        child = tmp_path / "tsconfig.json"
        child.write_text(
            '{\n  "extends": "./tsconfig.base.json",\n  "include": ["src"],\n}\n',
            encoding="utf-8",
        )
        assert diag._tsconfig_is_composite(child) is True

    def test_unparseable_config_is_treated_as_composite(self, tmp_path: Path):
        tsconfig = tmp_path / "tsconfig.json"
        tsconfig.write_text("{ this is not json at all ", encoding="utf-8")
        assert diag._tsconfig_is_composite(tsconfig) is True, (
            "unknown must not re-enable --incremental false (TS6379)"
        )

    def test_plugins_in_extended_base_are_detected(self, tmp_path: Path):
        base = tmp_path / "tsconfig.base.json"
        base.write_text(
            '{\n  "compilerOptions": {"plugins": [{"name": "ts-plugin"}]},\n}\n',
            encoding="utf-8",
        )
        child = tmp_path / "tsconfig.json"
        child.write_text(
            '{ "extends": "./tsconfig.base.json" }\n', encoding="utf-8"
        )
        assert diag._tsconfig_loads_plugins(child) is True

    async def test_commented_composite_project_keeps_working_argv(
        self, monkeypatch, tmp_path: Path
    ):
        root = tmp_path / "jsonc-proj"
        (root / "node_modules" / ".bin").mkdir(parents=True)
        (root / "node_modules" / ".bin" / "tsc").write_text("", encoding="utf-8")
        (root / "tsconfig.json").write_text(JSONC_COMPOSITE, encoding="utf-8")
        target = root / "a.ts"
        target.write_text("export const a: number = 1;\n", encoding="utf-8")
        spy = _CheckerSpy((0, "", "", False))
        monkeypatch.setattr(diag, "_run_checker", spy)
        monkeypatch.setattr(diag, "project_config_execution_allowed", lambda *a, **k: True)

        async def fake_includes(*args, **kwargs):
            return True

        monkeypatch.setattr(diag, "_tsc_includes", fake_includes)

        report = await diag.check_js_ts(
            target, target.read_text(encoding="utf-8"),
            fingerprint="fp", operation="edit", node_root=root,
        )

        assert report.status == "pass"
        assert spy.calls
        assert "--incremental" not in spy.calls[0], (
            "TS6379: a composite project may not disable incremental compilation"
        )
