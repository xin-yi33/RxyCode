"""Real AgentV2 worker lifecycle; only provider responses are scripted."""
from __future__ import annotations

import asyncio
import json
import psutil
import pytest


@pytest.mark.asyncio
async def test_idle_recycle_preserves_real_agent_session_prefix(tmp_path, monkeypatch):
    from RxyCode.RxyCode1_1_0.appserver.server import AppServer
    from RxyCode.RxyCode1_1_0.appserver.idle_policy import IdleWorkerPolicy

    runtime = tmp_path / "runtime"
    runtime.mkdir()
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setenv("RXYCODE_DATA_DIR", str(runtime))
    monkeypatch.setenv("RXYCODE_V2_CONFIG_DIR", str(runtime))
    monkeypatch.setenv("RXYCODE_APPSERVER_MULTI", "1")
    monkeypatch.setenv("RXYCODE_APPSERVER_STUB", "0")
    monkeypatch.setenv("RXYCODE_SUBAGENTS", "0")
    monkeypatch.setenv("RXYCODE_SUBAGENTS_TASK", "0")
    monkeypatch.setenv("RXYCODE_SUBAGENTS_MENTION", "0")
    monkeypatch.setenv("RXYCODE_COMPUTER_USE", "0")
    monkeypatch.setenv("RXYCODE_E2E_TEST_API_KEY", "synthetic-test-only")
    monkeypatch.setenv("RXYCODE_RUNTIME_PROBE", "0")
    (runtime / "config.yaml").write_text(json.dumps({
        "active_model": "memory-scripted",
        "models": {"memory-scripted": {
            "provider_id": "openai_compatible", "model_name": "memory-scripted-model",
            "base_url": "https://127.0.0.1:1/v1", "api_key_env": "RXYCODE_E2E_TEST_API_KEY",
        }},
        "agents": {"enabled": False, "route_mode": "auto", "multi_model": {"enabled": False}},
        "mcp_servers": {}, "computer_use": {"enabled": False},
    }), encoding="utf-8")
    responses = tmp_path / "responses.json"
    responses.write_text(json.dumps([{"kind": "say", "text": "最终结果：已记录 BLUE_MEMORY_MARKER"}]), encoding="utf-8")
    monkeypatch.setenv("RXYCODE_SCRIPTED_AGENT_REPLIES", str(responses))
    monkeypatch.setenv("RXYCODE_SCRIPTED_AGENT_CAPTURE", str(tmp_path / "first-prompt.txt"))
    server = AppServer(stub=False)
    server._worker_idle_policy = IdleWorkerPolicy(idle_seconds=0, max_idle_workers=0)
    emitted = []
    responses_by_id = {}
    async def collect_response(request_id, result):
        responses_by_id[request_id] = result
    monkeypatch.setattr(server, "_respond", collect_response)
    monkeypatch.setattr(server, "_schedule_notification", emitted.append)
    owned = []
    try:
        record = server._sessions.create(workspace, model_id="memory-scripted")
        first = await server._host_for_session(record.session_id)
        owned.append(first)
        await first.ensure_bootstrapped(timeout=90)
        first_pid = first.pid
        await server._run_prompt(
            session_id=record.session_id,
            text="记住合成标记 BLUE_MEMORY_MARKER，并回答你已记录。",
            request_id=1, job_id="memory-first", timeout_seconds=30,
            mode="build", permission_mode="full_auto",
        )
        result = responses_by_id[1]
        assert result["status"] == "succeeded"
        assert "BLUE_MEMORY_MARKER" in result["text"]
        # Prewarm and completed-turn teardown can finish after prompt response.
        retired = []
        for _ in range(100):
            retired = await server._reap_idle_workers_once()
            if retired:
                break
            await asyncio.sleep(.05)
        assert retired == [record.session_id], "real worker must become recyclable after its turn"
        assert not psutil.pid_exists(first_pid)
        assert record.session_id not in server._session_hosts
        assert server._sessions.get(record.session_id).model_id == "memory-scripted"

        capture = tmp_path / "restored-prompt.txt"
        monkeypatch.setenv("RXYCODE_SCRIPTED_AGENT_CAPTURE", str(capture))
        responses.write_text(json.dumps([{"kind": "say", "text": "最终结果：继续处理"}]), encoding="utf-8")
        second = await server._host_for_session(record.session_id)
        owned.append(second)
        assert second is not first and second.pid != first_pid
        await second.ensure_bootstrapped(timeout=90)
        await server._run_prompt(
            session_id=record.session_id,
            text="继续上一轮；这条新消息不重复那个标记。",
            request_id=2, job_id="memory-second", timeout_seconds=30,
            mode="build", permission_mode="full_auto",
        )
        resumed = responses_by_id[2]
        assert resumed["status"] == "succeeded"
        assert resumed["text"] == "最终结果：继续处理"
        assert "BLUE_MEMORY_MARKER" in capture.read_text(encoding="utf-8")
        assert any(event.get("method") == "event/final" for event in emitted)
        assert not second.degraded
        assert not server._watchdog.degraded
    finally:
        for host in owned:
            await host.kill_async()
        server._instance_lock.release()
        await server._task_store.flush_pending(timeout=2)
        assert all(not host.alive() for host in owned)
