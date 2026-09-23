"""E2E: Card C tool-latency seams through bash + appserver stdio."""

from __future__ import annotations

import json
from inspect import signature

import pytest

from tests.test_appserver.test_stdio_integration import (
    PROJECT_ROOT,
    AppserverClient,
    _appserver_env,
    _appserver_proc_with_env,
)


def test_e2e_bash_default_timeout_runs_echo():
    from RxyCode.RxyCode1_1_0.tools.bash import run_bash
    from RxyCode.RxyCode1_1_0.utils.shell import ShellExecutor

    assert signature(run_bash).parameters["timeout"].default == 1800
    assert signature(ShellExecutor.execute).parameters["timeout"].default == 1800
    assert signature(ShellExecutor.execute_async).parameters["timeout"].default == 1800
    assert signature(ShellExecutor.execute_argv_async).parameters["timeout"].default == 1800
    out = run_bash("echo card_c_latency")
    assert "card_c_latency" in out


@pytest.mark.asyncio
async def test_e2e_shell_execute_async_short_command():
    from RxyCode.RxyCode1_1_0.utils.shell import shell_executor

    result = await shell_executor.execute_async("echo card_c_shell")
    assert result["success"] is True
    assert "card_c_shell" in (result.get("stdout") or "")


def test_e2e_appserver_silent_prompt_still_succeeds_after_tool_latency_changes():
    env = _appserver_env()
    env["RXYCODE_APPSERVER_STALL_SECONDS"] = "2"
    env["RXYCODE_APPSERVER_HEARTBEAT_SECONDS"] = "1"
    env["RXYCODE_APPSERVER_WORKER_HEARTBEAT_SECONDS"] = "0.5"
    proc = _appserver_proc_with_env(env)
    try:
        client = AppserverClient(proc)
        client.request(
            "initialize",
            {
                "client_name": "pytest",
                "client_version": "0.0.0",
                "protocol_version": "1.0.0",
            },
        )
        session = client.request("session/new", {"workspace_root": str(PROJECT_ROOT)})
        result = client.request(
            "session/prompt",
            {"session_id": session["session_id"], "text": "silent:3"},
            timeout=10.0,
        )
        assert result["status"] == "succeeded"
        assert result["text"] == "stub:silent-complete"
    finally:
        if proc.poll() is None:
            try:
                if proc.stdin:
                    proc.stdin.write(
                        json.dumps({"jsonrpc": "2.0", "id": 99, "method": "shutdown"})
                        + "\n"
                    )
                    proc.stdin.flush()
            except Exception:
                pass
            proc.terminate()
            proc.wait(timeout=10)
