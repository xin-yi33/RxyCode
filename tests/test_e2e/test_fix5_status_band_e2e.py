"""E-F5-E2E-01 / 02. Scripted model, real AgentV2, real tasks.json."""
from __future__ import annotations

import asyncio
import contextlib
import json
import uuid
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from langchain_core.messages import HumanMessage, SystemMessage

from RxyCode.RxyCode1_1_0.core.status_band import HEADER
from RxyCode.RxyCode1_1_0.appserver.lifecycle import _terminate_pid_tree


def _band_messages(messages) -> list:
    return [
        message
        for message in messages
        if isinstance(message, HumanMessage) and str(message.content).startswith(HEADER)
    ]


def _joined(messages) -> str:
    return "\n".join(str(getattr(message, "content", "") or "") for message in messages)


def _agent(session_id: str):
    from RxyCode.RxyCode1_1_0.config.model_capabilities import DEFAULT_CAPABILITIES
    from RxyCode.RxyCode1_1_0.core.agent_v2 import AgentV2
    from RxyCode.RxyCode1_1_0.core.builtin_tool_registration import register_builtin_tools
    from RxyCode.RxyCode1_1_0.execution.tool_orchestrator import ToolOrchestrator
    from RxyCode.RxyCode1_1_0.tools.registry import ToolRegistry

    registry = ToolRegistry()
    orchestrator = ToolOrchestrator(tool_registry=registry)
    register_builtin_tools(registry, orchestrator, rag_enabled=False)
    agent = AgentV2.__new__(AgentV2)
    agent._session_loaded = True
    agent._session_id = session_id
    agent._memory = SimpleNamespace(
        get_context_for_prompt=lambda _q, **_k: "",
        add_interaction=lambda *_a, **_k: None,
        save_session=lambda: None,
        compress_if_needed=lambda _sid: None,
        flush_before_compaction=lambda _messages: None,
        _rag_enabled=False,
    )
    agent._cfg = {"execution": {"max_tool_rounds": 4, "tool_parallel_enabled": False}}
    agent.model_config = {
        "base_url": "https://api.example.test/v1",
        "model_name": "test-model",
        "effort": "balanced",
    }
    agent._capabilities = DEFAULT_CAPABILITIES
    agent._resolved_limits = None
    agent._keep_alive_state = None
    agent._tokenizer = "tiktoken:o200k_base"
    agent._tool_tracer = None
    agent._tool_orchestrator = orchestrator
    agent._last_thinking = ""
    agent._thinking_history = []
    agent._agent_prefix_messages = None
    agent._provider = None
    agent._git_snapshot = None
    agent._prompt_variant = lambda: "default"
    agent._get_core_tools = lambda: []
    agent._capture_git_snapshot_async = lambda: _async_none()
    agent._has_creation_product_intent = lambda _t: False
    agent._is_social_chat = lambda _t: False
    agent._should_emit_analyze_progress = lambda _t: False
    agent._memory_ctx_for_turn = lambda _t: ""
    agent._turn_context_suffix = lambda: ""
    agent._effort_for = lambda _mode, _text: "balanced"
    agent._application_cache_namespace = lambda: "ns-e2e-band"
    agent._side_effecting_tool_attempted = False
    return agent


async def _async_none():
    return None


class _Script:
    def __init__(self) -> None:
        self.captured: list[list] = []
        self.pending: list[tuple] = []

    def tool(self, todos: list[dict], call_id: str) -> None:
        self.pending.append(("tool", todos, call_id))

    def say(self, text: str) -> None:
        self.pending.append(("say", text, ""))

    async def stream(self, messages, tools=None, **_kwargs):
        self.captured.append(list(messages))
        kind, payload, call_id = self.pending.pop(0)
        if kind == "tool":
            arguments = json.dumps({"todos": payload, "merge": True}, ensure_ascii=False)
            delta = SimpleNamespace(
                content="",
                tool_calls=[
                    SimpleNamespace(
                        index=0,
                        id=call_id,
                        function=SimpleNamespace(name="todo_write", arguments=arguments),
                    )
                ],
            )
        else:
            delta = SimpleNamespace(content=payload, tool_calls=None)
        yield SimpleNamespace(choices=[SimpleNamespace(delta=delta)], usage=None)


@pytest.mark.asyncio
async def test_e_f5_e2e_01_status_band_round_trip(tmp_path, monkeypatch):
    """E-F5-E2E-01 注入、零字节 diff、压缩后全量，fast 与 graph 同一渲染器。"""
    from RxyCode.RxyCode1_1_0.config import settings
    from RxyCode.RxyCode1_1_0.core.graph import _TrackingLLM
    from RxyCode.RxyCode1_1_0.core.session_runtime import bind_session, reset_session_binding
    from RxyCode.RxyCode1_1_0.core.status_band import bind_status_band, reset_status_band
    from RxyCode.RxyCode1_1_0.execution.tool_orchestrator import permission_mode_override
    from RxyCode.RxyCode1_1_0.tools.todo_write import todo_summary_llm_calls, todo_write

    monkeypatch.setattr(settings, "get_data_dir", lambda: tmp_path)
    token = bind_session("e2e-band")
    try:
        agent = _agent("e2e-band")
        script = _Script()
        agent._raw_stream = script.stream
        created = [
            {"id": "t1", "content": "搭骨架", "status": "in_progress"},
            {"id": "t2", "content": "装依赖", "status": "pending"},
            {"id": "t3", "content": "写测试", "status": "pending"},
        ]
        script.tool(created, "call-create")
        script.say("最终结果：清单已建")
        with permission_mode_override("full_auto"):
            first = await agent._fast_reply_with_tools("建三步清单", mode="build")
        assert first == "最终结果：清单已建"
        assert isinstance(script.captured[0][0], SystemMessage)
        carried = _joined(script.captured[-1])
        assert "搭骨架" in carried
        assert "装依赖" in carried
        assert "写测试" in carried
        assert "fp=" in carried
        created_bands = _band_messages(script.captured[-1])
        assert len(created_bands) == 1
        assert "cwd:" in created_bands[-1].content

        for prompt in ("原样再看一眼", "清单没有变化"):
            script.say("最终结果：继续")
            seen = len(script.captured)
            with permission_mode_override("full_auto"):
                await agent._fast_reply_with_tools(prompt, mode="build")
            assert len(script.captured) == seen + 1
            assert len(_band_messages(script.captured[-1])) == 1

        script.tool([{"id": "t1", "content": "搭骨架", "status": "completed"}], "call-done")
        script.say("最终结果：第一步完成")
        with permission_mode_override("full_auto"):
            updated = await agent._fast_reply_with_tools("第一步做完了", mode="build")
        assert updated == "最终结果：第一步完成"
        updated_text = _joined(script.captured[-1])
        assert "completed" in updated_text
        assert "装依赖" in updated_text

        async def _no_summary(_messages):
            return None

        agent._prefetch_compaction_summary = _no_summary
        agent._capabilities = SimpleNamespace(
            context_window=128,
            tokenizer="tiktoken:o200k_base",
        )
        before_compact = list(agent._agent_prefix_messages)
        await agent._maybe_compress_context(agent._agent_prefix_messages, force=True)
        assert agent._band_full_on_next is True
        assert len(agent._agent_prefix_messages) >= 1
        script.say("最终结果：压缩后继续")
        with permission_mode_override("full_auto"):
            await agent._fast_reply_with_tools("压缩后接着做", mode="build")
        restored = _band_messages(script.captured[-1])
        assert before_compact
        assert len(restored) == 1
        assert "still active" in restored[-1].content
        assert "装依赖" in restored[-1].content
        assert _joined(restored).count("cwd:") <= 1

        class _GraphModel:
            def __init__(self) -> None:
                self.seen: list[list] = []

            async def ainvoke(self, msgs, config=None, **_kwargs):
                self.seen.append(list(msgs))
                return SimpleNamespace(content="最终结果：graph")

        graph_model = _GraphModel()
        tracker = SimpleNamespace(
            guidance_notes=[],
            _guidance_sent=0,
            heartbeat=lambda: None,
            record_error=lambda _exc: None,
        )
        wrapped = _TrackingLLM(graph_model, tracker)
        band_token = bind_status_band(agent)
        try:
            await wrapped.ainvoke([SystemMessage(content="S1")])
            first_revision = _joined(graph_model.seen[-1])
            todo_write(
                [{"id": "t2", "status": "completed"}, {"id": "t3", "status": "in_progress"}],
                merge=True,
                session_id="e2e-band",
            )
            await wrapped.ainvoke([SystemMessage(content="S1")])
            second_revision = _joined(graph_model.seen[-1])
        finally:
            reset_status_band(band_token)
        assert graph_model.seen[-1][0].content == "S1"
        assert "revision=" in first_revision
        assert "revision=" in second_revision
        assert first_revision != second_revision
        assert "cwd:" not in second_revision
        assert "写测试" in second_revision
        assert "2 completed" in second_revision
        assert todo_summary_llm_calls == 0
    finally:
        reset_session_binding(token)


def test_e_f5_e2e_02_uses_explicit_runtime_root(tmp_path, monkeypatch):
    """The worker E2E must not fall back to ambient developer data."""
    monkeypatch.delenv("RXYCODE_DATA_DIR", raising=False)
    monkeypatch.delenv("RXYCODE_V2_CONFIG_DIR", raising=False)
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    monkeypatch.setenv("RXYCODE_DATA_DIR", str(runtime))
    monkeypatch.setenv("RXYCODE_V2_CONFIG_DIR", str(runtime))

    from RxyCode.RxyCode1_1_0.config import settings

    assert settings.get_data_dir() == runtime
    assert Path(os.environ["RXYCODE_V2_CONFIG_DIR"]) == runtime


@pytest.mark.asyncio
async def _worker(repo: Path, env: dict, stderr_path: Path):
    from appserver.agent_host import WORKER_STDIO_LIMIT_BYTES, AsyncRpcPipe

    err = stderr_path.open("w", encoding="utf-8", errors="replace")
    proc = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "appserver.agent_worker",
        cwd=str(repo),
        env=env,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=err,
        limit=WORKER_STDIO_LIMIT_BYTES,
        start_new_session=(os.name != "nt"),
    )
    pipe = AsyncRpcPipe(proc.stdin, proc.stdout)
    await pipe.start()
    return proc, pipe


async def _kill_worker_tree(proc):
    """Use the shared platform-aware tree killer for this test-owned worker."""
    if proc.returncode is None:
        await asyncio.to_thread(_terminate_pid_tree, proc.pid)
    await asyncio.wait_for(proc.wait(), timeout=10)


async def test_e_f5_e2e_02_killed_worker_model_continues(tmp_path, monkeypatch):
    """E-F5-E2E-02 第一个 worker 写清单后被杀，新 worker 经 prompt 接着做。"""
    monkeypatch.delenv("RXYCODE_DATA_DIR", raising=False)
    monkeypatch.delenv("RXYCODE_V2_CONFIG_DIR", raising=False)
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    monkeypatch.setenv("RXYCODE_DATA_DIR", str(runtime))
    monkeypatch.setenv("RXYCODE_V2_CONFIG_DIR", str(runtime))
    from RxyCode.RxyCode1_1_0.config import settings
    from RxyCode.RxyCode1_1_0.tools.todo_events import read_todo_snapshot
    from RxyCode.RxyCode1_1_0.tools.todo_write import todo_summary_llm_calls

    repo = Path(__file__).resolve().parents[2]
    nonce = uuid.uuid4().hex[:8]
    session_id = f"e2e-kill-{nonce}"
    created = tmp_path / "created.json"
    created.write_text(
        json.dumps(
            [
                {
                    "kind": "tool",
                    "id": "call-create",
                    "todos": [
                        {"id": "t1", "content": "准备", "status": "completed"},
                        {"id": "t2", "content": "停在第二步", "status": "in_progress"},
                        {"id": "t3", "content": "收尾", "status": "pending"},
                    ],
                },
                {"kind": "say", "text": "最终结果：清单已建"},
            ]
        ),
        encoding="utf-8",
    )
    resumed = tmp_path / "resumed.json"
    resumed.write_text(
        json.dumps(
            [
                {"kind": "say", "text": "最终结果：从第二步继续"},
                {
                    "kind": "tool",
                    "id": "call-resume",
                    "todos": [
                        {"id": "t2", "status": "completed"},
                        {"id": "t3", "content": "收尾", "status": "in_progress"},
                    ],
                },
                {"kind": "say", "text": "最终结果：第三步开始"},
            ]
        ),
        encoding="utf-8",
    )
    capture = tmp_path / "capture.txt"
    # Keep the worker hermetic: this E2E must never inherit the developer's
    # active provider, credentials, or team-routing choice.  The scripted
    # stream is installed at prompt time, while bootstrap still needs a
    # syntactically valid model entry to construct a real AgentV2.
    (runtime / "config.yaml").write_text(
        json.dumps(
            {
                "active_model": "e2e-scripted",
                "models": {
                    "e2e-scripted": {
                        "provider_id": "openai_compatible",
                        "model_name": "e2e-scripted-model",
                        "base_url": "https://127.0.0.1:1/v1",
                        "api_key_env": "RXYCODE_E2E_TEST_API_KEY",
                    }
                },
                "agents": {
                    "enabled": False,
                    "route_mode": "auto",
                    "multi_model": {"enabled": False},
                },
            }
        ),
        encoding="utf-8",
    )
    base_env = dict(os.environ)
    base_env["RXYCODE_DATA_DIR"] = str(runtime)
    base_env["RXYCODE_V2_CONFIG_DIR"] = str(runtime)
    base_env["PYTHONPATH"] = str(repo)
    base_env["RXYCODE_E2E_TEST_API_KEY"] = "test-only-key"
    base_env["RXYCODE_SUBAGENTS"] = "0"
    base_env["RXYCODE_SUBAGENTS_TASK"] = "0"
    base_env["RXYCODE_SUBAGENTS_MENTION"] = "0"

    first_env = dict(base_env)
    first_env["RXYCODE_SCRIPTED_AGENT_REPLIES"] = str(created)
    first_env["RXYCODE_SCRIPTED_AGENT_CAPTURE"] = str(tmp_path / "create-capture.txt")
    proc, pipe = await _worker(repo, first_env, tmp_path / "worker1.err")
    writing = None
    try:
        started = await pipe.request(
            "bootstrap",
            {"stub": False, "workspace_root": str(tmp_path / "workspace"), "session_id": session_id},
            timeout=90,
        )
        assert started["ok"] is True
        writing = asyncio.create_task(
            pipe.request(
                "prompt",
                {
                    "session_id": session_id,
                    "text": f"建三步清单并开始做 {nonce}",
                    "mode": "build",
                    "permission_mode": "full_auto",
                    "run_id": "run-create",
                },
                timeout=60,
            )
        )
        stored = None
        for _ in range(100):
            snap = read_todo_snapshot(session_id)
            if snap.revision >= 1 and any(item.status == "in_progress" for item in snap.items):
                stored = snap
                break
            await asyncio.sleep(0.1)
        assert stored is not None
        assert stored.revision == 1
        await _kill_worker_tree(proc)
        assert proc.returncode is not None
        writing.cancel()
    finally:
        if writing is not None:
            if not writing.done():
                writing.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await writing
        await pipe.close()
        if proc.returncode is None:
            await _kill_worker_tree(proc)

    second_env = dict(base_env)
    second_env["RXYCODE_SCRIPTED_AGENT_REPLIES"] = str(resumed)
    second_env["RXYCODE_SCRIPTED_AGENT_CAPTURE"] = str(capture)
    proc2, pipe2 = await _worker(repo, second_env, tmp_path / "worker2.err")
    try:
        started = await pipe2.request(
            "bootstrap",
            {"stub": False, "workspace_root": str(tmp_path / "workspace"), "session_id": session_id},
            timeout=90,
        )
        assert started["ok"] is True
        continued = await pipe2.request(
            "prompt",
            {
                "session_id": session_id,
                "text": f"继续未完成的清单 {nonce}",
                "mode": "build",
                "permission_mode": "full_auto",
                "run_id": "run-continue",
            },
            timeout=60,
        )
        assert continued["text"] == "最终结果：从第二步继续"
        seen = capture.read_text(encoding="utf-8")
        assert "停在第二步" in seen
        assert f"revision={stored.revision}" in seen
        finished = await pipe2.request(
            "prompt",
            {
                "session_id": session_id,
                "text": f"沿用原来的编号往下做 {nonce}",
                "mode": "build",
                "permission_mode": "full_auto",
                "run_id": "run-update",
            },
            timeout=60,
        )
        assert finished["text"] == "最终结果：第三步开始"
        latest = read_todo_snapshot(session_id)
        assert [item.id for item in latest.items] == ["t1", "t2", "t3"]
        assert latest.revision == stored.revision + 1
        assert latest.items[2].status == "in_progress"
        assert todo_summary_llm_calls == 0
    finally:
        await pipe2.close()
        if proc2.returncode is None:
            await _kill_worker_tree(proc2)
        folder = settings.get_data_dir() / "tasks" / session_id
        if folder.exists():
            import shutil
            shutil.rmtree(folder, ignore_errors=True)
