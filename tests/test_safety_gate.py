"""Integration tests for the safety gate in
execution/tool_orchestrator.py — policy classification, path whitelist,
dry-run and approval flow, all with a mocked tool (no real LLM).
"""
import asyncio
import time
from pathlib import Path

import pytest
from unittest.mock import MagicMock

from RxyCode.RxyCode1_1_0.core.safety.approval import (
    ApprovalDecision, SseApproval, set_approval_broker,
)
from RxyCode.RxyCode1_1_0.core.safety.audit import AuditLogger
from RxyCode.RxyCode1_1_0.execution.tool_orchestrator import ToolOrchestrator


@pytest.fixture(autouse=True)
def _reset_broker():
    set_approval_broker(None)
    yield
    set_approval_broker(None)


def _make_tool(name="mytool", ret="done"):
    tool = MagicMock()
    tool.name = name
    tool.description = "test tool"
    tool.invoke = MagicMock(return_value=ret)
    return tool


def _make_write_tool():
    tool = _make_tool("write")

    def write_file(args):
        Path(args["filePath"]).write_text(args["content"], encoding="utf-8")
        return "done"

    tool.invoke.side_effect = write_file
    return tool


class TestGateDisabled:
    @pytest.mark.asyncio
    async def test_passthrough_when_disabled_is_still_audited(
        self, tmp_path, monkeypatch
    ):
        import json

        monkeypatch.chdir(tmp_path)
        audit_path = tmp_path / "audit.jsonl"
        orch = ToolOrchestrator()
        tool = _make_tool()
        orch.register("mytool", tool)
        orch.set_audit_logger(AuditLogger(path=audit_path))
        cfg = {"safety": {"enabled": False}}
        result = await orch.execute_tool("mytool", {"x": 1}, config=cfg)
        assert result == "done"
        tool.invoke.assert_called_once()
        record = json.loads(audit_path.read_text(encoding="utf-8"))
        assert record["tool"] == "mytool"
        assert record["risk"] == "WRITE"
        assert record["approval"] == "safety_disabled"


class TestPolicyGate:
    @pytest.mark.asyncio
    async def test_read_tool_no_approval_needed(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        orch = ToolOrchestrator()
        tool = _make_tool("read")
        orch.register("read", tool)
        cfg = {"safety": {"enabled": True}}
        result = await orch.execute_tool("read", {"filePath": "a.txt"}, config=cfg)
        assert result == "done"

    @pytest.mark.asyncio
    async def test_write_outside_whitelist_rejected(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        orch = ToolOrchestrator()
        tool = _make_write_tool()
        orch.register("write", tool)
        cfg = {"safety": {"enabled": True}}
        result = await orch.execute_tool(
            "write", {"filePath": "/etc/passwd", "content": "x"}, config=cfg)
        assert "blocked" in result.lower() or "not allowed" in result.lower()
        tool.invoke.assert_not_called()

    @pytest.mark.asyncio
    async def test_download_save_path_outside_whitelist_rejected(
        self, tmp_path, monkeypatch
    ):
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        monkeypatch.chdir(workspace)
        orch = ToolOrchestrator()
        tool = _make_tool("download_file")
        orch.register("download_file", tool)
        cfg = {
            "safety": {
                "enabled": True,
                "auto_approve": ["write"],
                "allowed_write_paths": [str(workspace)],
            }
        }

        result = await orch.execute_tool(
            "download_file",
            {
                "url": "https://example.test/archive.zip",
                "save_path": str(tmp_path / "outside" / "archive.zip"),
            },
            config=cfg,
        )

        assert "blocked" in result.lower() or "not allowed" in result.lower()
        tool.invoke.assert_not_called()

    @pytest.mark.asyncio
    async def test_write_inside_cwd_allowed_with_approval(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        orch = ToolOrchestrator()
        tool = _make_write_tool()
        orch.register("write", tool)

        broker = SseApproval(timeout=5)
        events = []
        broker.set_event_sink(events.append)
        set_approval_broker(broker)

        cfg = {"safety": {"enabled": True}}

        async def respond():
            await asyncio.sleep(0.02)
            broker.resolve(events[0]["approval_id"], "approved")

        result, _ = await asyncio.gather(
            orch.execute_tool("write", {"filePath": str(tmp_path / "f.txt"), "content": "x"}, config=cfg),
            respond(),
        )
        assert result == "done"
        tool.invoke.assert_called_once()

    @pytest.mark.asyncio
    async def test_rejection_returns_message(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        orch = ToolOrchestrator()
        tool = _make_tool("write")
        orch.register("write", tool)

        broker = SseApproval(timeout=5)
        events = []
        broker.set_event_sink(events.append)
        set_approval_broker(broker)
        cfg = {"safety": {"enabled": True}}

        async def respond():
            await asyncio.sleep(0.02)
            broker.resolve(events[0]["approval_id"], "rejected")

        result, _ = await asyncio.gather(
            orch.execute_tool("write", {"filePath": str(tmp_path / "f.txt"), "content": "x"}, config=cfg),
            respond(),
        )
        assert "rejected" in result.lower()
        tool.invoke.assert_not_called()

    @pytest.mark.asyncio
    async def test_dangerous_bash_command_flagged_danger(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        orch = ToolOrchestrator()
        tool = _make_tool("bash")
        orch.register("bash", tool)

        broker = SseApproval(timeout=5)
        events = []
        broker.set_event_sink(events.append)
        set_approval_broker(broker)
        cfg = {"safety": {"enabled": True}}

        async def respond():
            await asyncio.sleep(0.02)
            assert events[0]["risk"] == "DANGER"
            broker.resolve(events[0]["approval_id"], "rejected")

        result, _ = await asyncio.gather(
            orch.execute_tool("bash", {"command": "rm -rf /"}, config=cfg),
            respond(),
        )
        assert "rejected" in result.lower()
        tool.invoke.assert_not_called()

    @pytest.mark.asyncio
    async def test_auto_approve_write_level(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        orch = ToolOrchestrator()
        tool = _make_write_tool()
        orch.register("write", tool)
        # No broker at all — auto_approve must let it through
        cfg = {"safety": {"enabled": True, "auto_approve": ["write"]}}
        result = await orch.execute_tool(
            "write", {"filePath": str(tmp_path / "f.txt"), "content": "x"}, config=cfg)
        assert result == "done"

    @pytest.mark.asyncio
    async def test_no_broker_defaults_rejected(self, tmp_path, monkeypatch):
        """Fail-closed: WRITE tool without any broker must not execute."""
        monkeypatch.chdir(tmp_path)
        orch = ToolOrchestrator()
        tool = _make_tool("write")
        orch.register("write", tool)
        cfg = {"safety": {"enabled": True}}
        result = await orch.execute_tool(
            "write", {"filePath": str(tmp_path / "f.txt"), "content": "x"}, config=cfg)
        assert "rejected" in result.lower() or "no approval" in result.lower()
        tool.invoke.assert_not_called()

    @pytest.mark.parametrize(
        ("name", "operation"),
        [
            ("memory", "search"),
            ("memory", "list"),
            ("task", "list"),
            ("task", "get"),
            ("workflow", "status"),
            ("workflow", "wait"),
        ],
    )
    @pytest.mark.asyncio
    async def test_readonly_composite_operations_execute_without_approval(
        self, name, operation
    ):
        orch = ToolOrchestrator()
        tool = _make_tool(name)
        orch.register(name, tool)

        result = await orch.execute_tool(
            name,
            {"operation": operation},
            config={"safety": {"enabled": True}},
        )

        assert result == "done"
        tool.invoke.assert_called_once()

    @pytest.mark.parametrize(
        ("name", "operation"),
        [
            ("memory", "add"),
            ("memory", "remove"),
            ("task", "create"),
            ("task", "done"),
            ("workflow", "cancel"),
            ("workflow", "run"),
            ("workflow", "future_action"),
        ],
    )
    @pytest.mark.asyncio
    async def test_mutating_composite_operations_cannot_bypass_approval(
        self, name, operation
    ):
        orch = ToolOrchestrator()
        tool = _make_tool(name)
        orch.register(name, tool)

        result = await orch.execute_tool(
            name,
            {"operation": operation},
            config={"safety": {"enabled": True}},
        )

        assert "rejected" in result.lower() or "no approval" in result.lower()
        tool.invoke.assert_not_called()

    @pytest.mark.asyncio
    async def test_workflow_run_requests_danger_approval(self):
        orch = ToolOrchestrator()
        tool = _make_tool("workflow")
        orch.register("workflow", tool)
        broker = SseApproval(timeout=5)
        events = []
        broker.set_event_sink(events.append)
        set_approval_broker(broker)

        async def respond():
            await asyncio.sleep(0.02)
            assert events[0]["risk"] == "DANGER"
            broker.resolve(events[0]["approval_id"], "rejected")

        result, _ = await asyncio.gather(
            orch.execute_tool(
                "workflow",
                {"operation": "run", "name": "build"},
                config={"safety": {"enabled": True}},
            ),
            respond(),
        )

        assert "rejected" in result.lower()
        tool.invoke.assert_not_called()


class TestDryRunGate:
    @pytest.mark.asyncio
    async def test_dry_run_returns_simulated(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("RXYCODE_DRY_RUN", "1")
        orch = ToolOrchestrator()
        tool = _make_tool("write")
        orch.register("write", tool)
        cfg = {"safety": {"enabled": True}}
        result = await orch.execute_tool(
            "write", {"filePath": str(tmp_path / "f.txt"), "content": "x"}, config=cfg)
        assert "[dry-run]" in result
        tool.invoke.assert_not_called()

    @pytest.mark.asyncio
    async def test_dry_run_does_not_apply_to_read(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("RXYCODE_DRY_RUN", "1")
        orch = ToolOrchestrator()
        tool = _make_tool("read")
        orch.register("read", tool)
        cfg = {"safety": {"enabled": True}}
        result = await orch.execute_tool("read", {"filePath": "a.txt"}, config=cfg)
        assert result == "done"


class TestSafeToolProxies:
    @pytest.mark.asyncio
    async def test_llm_proxy_cannot_bypass_rejected_write(self, tmp_path):
        from langchain_core.tools import StructuredTool
        from pydantic import BaseModel

        class WriteArgs(BaseModel):
            path: str
            content: str

        calls = []
        raw = StructuredTool.from_function(
            func=lambda path, content: calls.append((path, content)) or "written",
            name="write",
            description="Write a file",
            args_schema=WriteArgs,
        )
        class RejectBroker:
            async def request_approval(self, _request):
                return ApprovalDecision.REJECTED

        orch = ToolOrchestrator()
        orch.register("write", raw)
        set_approval_broker(RejectBroker())
        cfg = {
            "safety": {
                "enabled": True,
                "allowed_write_paths": [str(tmp_path)],
            }
        }

        proxies = orch.select_safe_tools(["write"], cfg)
        result = await proxies[0].ainvoke({"path": str(tmp_path / "x.txt"), "content": "data"})

        assert "rejected" in result
        assert calls == []

    @pytest.mark.asyncio
    async def test_graph_proxy_enforces_timeout_and_emits_one_failed_lifecycle(
        self, tmp_path
    ):
        import json

        from langchain_core.tools import StructuredTool

        started = asyncio.Event()
        cancelled = asyncio.Event()

        async def wait_forever(filePath: str) -> str:
            started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                cancelled.set()
                raise
            return filePath

        raw = StructuredTool.from_function(
            coroutine=wait_forever,
            name="read",
            description="Cancellable graph read",
        )
        audit_path = tmp_path / "audit.jsonl"
        orch = ToolOrchestrator()
        orch.register("read", raw)
        orch.set_audit_logger(AuditLogger(path=audit_path))
        cfg = {
            "execution": {"tool_timeout_seconds": 0.01},
            "safety": {"enabled": True},
        }
        events = []

        class EventSink:
            def write_tool_call(self, name, args, call_id=None):
                events.append(("call", call_id, name, args))
                return call_id

            def write_tool_result(self, result, status, call_id=None):
                events.append(("result", call_id, status, result))

        event_token = orch.bind_event_tui(EventSink())
        evidence_token = orch.begin_evidence_capture()
        try:
            proxy = orch.select_safe_tools(["read"], cfg)[0]
            result = await proxy.ainvoke({"filePath": "a.txt"})
        finally:
            evidence = orch.end_evidence_capture(evidence_token)
            orch.reset_event_tui(event_token)

        expected = "[error: tool 'read' timed out after 0.01s]"
        assert started.is_set()
        assert cancelled.is_set()
        assert result == expected
        assert len(events) == 2
        assert events[0][0] == "call"
        assert events[0][1]
        assert events[1] == ("result", events[0][1], "timeout", expected)
        assert len(evidence) == 1
        assert evidence[0].status == "failed"
        assert evidence[0].executed is True
        assert evidence[0].detail == expected
        records = [
            json.loads(line)
            for line in audit_path.read_text(encoding="utf-8").splitlines()
        ]
        assert len(records) == 1
        assert records[0]["approval"] == "auto"
        assert records[0]["result"] == expected


class TestEvidenceCapture:
    @pytest.mark.asyncio
    async def test_write_evidence_contains_verified_artifact_hash(self, tmp_path):
        target = tmp_path / "artifact.txt"

        def write_file(path: str, content: str):
            Path(path).write_text(content, encoding="utf-8")
            return f"written: {path}"

        from langchain_core.tools import StructuredTool
        from pydantic import BaseModel

        class WriteArgs(BaseModel):
            path: str
            content: str

        orch = ToolOrchestrator()
        orch.register("write", StructuredTool.from_function(
            func=write_file,
            name="write",
            description="Write a file",
            args_schema=WriteArgs,
        ))
        cfg = {"safety": {"enabled": False}}
        token = orch.begin_evidence_capture()
        await orch.execute_tool("write", {"path": str(target), "content": "verified"}, cfg)
        evidence = orch.end_evidence_capture(token)

        assert len(evidence) == 1
        assert evidence[0].passed is True
        assert evidence[0].artifacts[0].exists is True
        assert evidence[0].artifacts[0].size == len(b"verified")
        assert len(evidence[0].artifacts[0].sha256) == 64

    @pytest.mark.asyncio
    async def test_invalid_html_artifact_fails_evidence(self, tmp_path):
        target = tmp_path / "broken.html"

        def write_file(path: str, content: str):
            Path(path).write_text(content, encoding="utf-8")
            return f"written: {path}"

        from langchain_core.tools import StructuredTool
        from pydantic import BaseModel

        class WriteArgs(BaseModel):
            path: str
            content: str

        orch = ToolOrchestrator()
        orch.register("write", StructuredTool.from_function(
            func=write_file,
            name="write",
            description="Write a file",
            args_schema=WriteArgs,
        ))
        token = orch.begin_evidence_capture()
        result = await orch.execute_tool(
            "write",
            {"path": str(target), "content": "<div>not a complete document</div>"},
            {"safety": {"enabled": False}},
        )
        evidence = orch.end_evidence_capture(token)

        assert result.startswith("[evidence failed:")
        assert str(target.resolve()) in result
        assert evidence[0].status == "failed"
        assert evidence[0].artifacts[0].media_type == "text/html"
        assert evidence[0].artifacts[0].valid is False

    @pytest.mark.asyncio
    async def test_parallel_evidence_capture_is_context_isolated(self):
        orch = ToolOrchestrator()
        orch.register("read", _make_tool("read", ret="ok"))
        cfg = {"safety": {"enabled": False}}

        async def capture(label: str):
            token = orch.begin_evidence_capture()
            await orch.execute_tool("read", {"label": label}, cfg)
            records = orch.end_evidence_capture(token)
            return records

        first, second = await asyncio.gather(capture("first"), capture("second"))
        assert len(first) == 1
        assert len(second) == 1
        assert first is not second

    @pytest.mark.asyncio
    async def test_nested_capture_propagates_to_run_scope(self):
        orch = ToolOrchestrator()
        orch.register("read", _make_tool("read", ret="ok"))
        cfg = {"safety": {"enabled": False}}

        outer = orch.begin_evidence_capture()
        inner = orch.begin_evidence_capture()
        await orch.execute_tool("read", {}, cfg)
        inner_records = orch.end_evidence_capture(inner)
        outer_records = orch.end_evidence_capture(outer)

        assert [record.tool for record in inner_records] == ["read"]
        assert [record.tool for record in outer_records] == ["read"]


class TestAsyncExecution:
    @pytest.mark.asyncio
    async def test_sync_tool_does_not_block_event_loop(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        orch = ToolOrchestrator()
        tool = _make_tool("read")
        tool.invoke = MagicMock(side_effect=lambda _args: (time.sleep(0.1), "done")[1])
        orch.register("read", tool)

        execution = asyncio.create_task(
            orch.execute_tool("read", {"filePath": "a.txt"}, config={"safety": {"enabled": False}})
        )
        await asyncio.sleep(0.02)
        assert not execution.done()
        assert await execution == "done"

    @pytest.mark.asyncio
    async def test_cancelled_native_tool_is_recorded_in_audit(
        self, tmp_path, monkeypatch
    ):
        from langchain_core.tools import StructuredTool

        monkeypatch.chdir(tmp_path)
        started = asyncio.Event()

        async def wait_forever(filePath: str) -> str:
            started.set()
            await asyncio.Event().wait()
            return filePath

        tool = StructuredTool.from_function(
            coroutine=wait_forever,
            name="read",
            description="cancellable read",
        )
        audit_path = tmp_path / "audit.jsonl"
        orch = ToolOrchestrator()
        orch.register("read", tool)
        orch.set_audit_logger(AuditLogger(path=audit_path))

        execution = asyncio.create_task(
            orch.execute_tool(
                "read",
                {"filePath": "a.txt"},
                config={"safety": {"enabled": True}},
            )
        )
        await started.wait()
        execution.cancel()
        with pytest.raises(asyncio.CancelledError):
            await execution

        import json
        record = json.loads(audit_path.read_text(encoding="utf-8").strip())
        assert record["tool"] == "read"
        assert record["approval"] == "auto"
        assert record["result"].startswith("[cancelled:")


class TestAuditIntegration:
    @pytest.mark.asyncio
    async def test_explicit_command_is_gated_and_audited_without_broker(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.chdir(tmp_path)
        audit_path = tmp_path / "audit.jsonl"
        orch = ToolOrchestrator()
        tool = _make_tool("download_skill")
        orch.register("download_skill", tool)
        orch.set_audit_logger(AuditLogger(path=audit_path))

        result = await orch.execute_tool(
            "download_skill",
            {"name": "demo", "operation": "remove"},
            config={"safety": {"enabled": True}},
            approval_source="explicit_command",
            mode="build",
        )

        assert result == "done"
        tool.invoke.assert_called_once()
        import json
        record = json.loads(audit_path.read_text(encoding="utf-8").strip())
        assert record["risk"] == "DANGER"
        assert record["approval"] == "explicit_command"

    @pytest.mark.asyncio
    async def test_plan_mode_blocks_explicit_command_even_if_gate_disabled(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.chdir(tmp_path)
        audit_path = tmp_path / "audit.jsonl"
        orch = ToolOrchestrator()
        tool = _make_tool("download_mcp")
        orch.register("download_mcp", tool)
        orch.set_audit_logger(AuditLogger(path=audit_path))

        result = await orch.execute_tool(
            "download_mcp",
            {"name": "demo", "operation": "remove"},
            config={"safety": {"enabled": False}},
            approval_source="explicit_command",
            mode="plan",
        )

        assert result.startswith("[blocked:")
        tool.invoke.assert_not_called()

    @pytest.mark.asyncio
    async def test_decisions_written_to_audit(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        audit_path = tmp_path / "audit.jsonl"
        orch = ToolOrchestrator()
        tool = _make_tool("read")
        orch.register("read", tool)
        orch.set_audit_logger(AuditLogger(path=audit_path))
        cfg = {"safety": {"enabled": True}}
        await orch.execute_tool("read", {"filePath": "a.txt"}, config=cfg)
        import json
        rec = json.loads(audit_path.read_text(encoding="utf-8").strip())
        assert rec["tool"] == "read"
        assert rec["approval"] == "auto"

    @pytest.mark.asyncio
    async def test_tool_not_found(self):
        orch = ToolOrchestrator()
        result = await orch.execute_tool("ghost", {}, config={"safety": {"enabled": True}})
        assert "not found" in result
