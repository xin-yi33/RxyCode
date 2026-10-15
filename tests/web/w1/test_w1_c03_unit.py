"""WEB-W1-C03. The unified gate owns capability checks and the native backend."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
for _rel in (
    Path("packages") / "rxycode-core" / "src",
    Path("packages") / "rxycode-protocol" / "src",
):
    _src = REPO / _rel
    if _src.is_dir() and str(_src) not in sys.path:
        sys.path.insert(0, str(_src))


async def test_w1_c03_contract():
    """A target without desktop capability cannot take a screenshot."""
    from langchain_core.tools import StructuredTool

    from execution.tool_orchestrator import ToolOrchestrator
    from rxycode_core.runtime.execution_port import (
        Capabilities,
        ExecutionPort,
        NativeBackend,
        ToolEvent,
        ToolSpec,
        bind_execution_port,
        reset_execution_port,
    )
    from rxycode_protocol.tool_rpc import ToolCall

    called = {"n": 0}

    async def screenshot(target: str) -> str:
        called["n"] += 1
        return f"png:{target}"

    orchestrator = ToolOrchestrator()
    orchestrator.register(
        "screenshot",
        StructuredTool.from_function(
            coroutine=screenshot,
            name="screenshot",
            description="capture the target screen",
        ),
    )
    port = ExecutionPort()
    port.register_target("phone", Capabilities(frozenset()))
    port.register_spec(
        ToolSpec(name="screenshot", version=1, required_capability="desktop")
    )
    spec = port.specs["screenshot"]
    assert spec.allows_execute() is False
    assert ToolSpec.from_dict(spec.to_dict()) == spec
    capabilities = Capabilities(frozenset({"desktop"}))
    assert Capabilities.from_dict(capabilities.to_dict()) == capabilities
    with pytest.raises(ValueError):
        ToolSpec(name="screenshot", version=0, required_capability="desktop")
    call = ToolCall(name="screenshot", target_id="phone", arguments={"target": "phone"}, version=1)
    assert ToolCall.from_dict(call.to_dict()) == call
    token = bind_execution_port(port)
    try:
        result = await orchestrator.execute_tool(
            "screenshot",
            {"target": "phone"},
            config={"safety": {"enabled": False}},
        )
    finally:
        reset_execution_port(token)
    assert called["n"] == 0
    assert "lacks capability desktop" in result
    assert "phone" in result

    allowed = ExecutionPort()
    allowed.register_target("desktop-1", Capabilities(frozenset({"desktop"})))
    allowed.register_spec(
        ToolSpec(name="screenshot", version=1, required_capability="desktop")
    )

    async def screenshot_with_backend(target: str) -> str:
        from rxycode_core.runtime.execution_port import NativeBackend, ToolEvent
        from rxycode_protocol.tool_rpc import ToolCall

        event = NativeBackend().invoke(
            ToolCall(name="screenshot", target_id=target, arguments={"target": target}, version=1),
            lambda: ToolEvent(
                ok=True,
                status="OK",
                tool="screenshot",
                target_id=target,
                text=f"png:{target}",
                version=1,
            ),
        )
        called["n"] += 1
        return event.text

    allowed_orchestrator = ToolOrchestrator()
    allowed_orchestrator.register(
        "screenshot",
        StructuredTool.from_function(
            coroutine=screenshot_with_backend,
            name="screenshot",
            description="capture the target screen",
        ),
    )
    allowed_token = bind_execution_port(allowed)
    try:
        allowed_result = await allowed_orchestrator.execute_tool(
            "screenshot",
            {"target": "desktop-1"},
            config={"safety": {"enabled": False}},
        )
    finally:
        reset_execution_port(allowed_token)
    assert called["n"] == 1
    assert allowed_result == "png:desktop-1"

    leaked: list[str] = []
    release = asyncio.Event()

    async def read_file(filePath: str) -> str:
        async def after_return() -> None:
            await release.wait()
            late = NativeBackend().invoke(
                ToolCall(name="read", target_id="local", arguments={}, version=1),
                lambda: ToolEvent(ok=True, status="OK", tool="read", target_id="local", text="late", version=1),
            )
            leaked.append(late.status)

        asyncio.create_task(after_return())
        return f"body:{filePath}"

    read_orchestrator = ToolOrchestrator()
    read_orchestrator.register(
        "read",
        StructuredTool.from_function(coroutine=read_file, name="read", description="read a file"),
    )
    read_result = await read_orchestrator.execute_tool(
        "read",
        {"filePath": "notes.txt"},
        config={"safety": {"enabled": False}},
    )
    assert read_result == "body:notes.txt"
    release.set()
    await asyncio.sleep(0)
    assert leaked == ["BLOCKED"]

    def sync_probe(filePath: str) -> str:
        event = NativeBackend().invoke(
            ToolCall(name="sync_probe", target_id="local", arguments={"filePath": filePath}, version=1),
            lambda: ToolEvent(
                ok=True,
                status="OK",
                tool="sync_probe",
                target_id="local",
                text=f"edited:{filePath}",
                version=1,
            ),
        )
        return event.text

    sync_port = ExecutionPort()
    sync_port.register_spec(ToolSpec(name="sync_probe", version=1, required_capability="fs"))
    sync_port.register_target("local", Capabilities(frozenset({"fs"})))
    edit_orchestrator = ToolOrchestrator()
    edit_orchestrator.register(
        "sync_probe",
        StructuredTool.from_function(func=sync_probe, name="sync_probe", description="sync probe"),
    )
    sync_token = bind_execution_port(sync_port)
    try:
        edit_result = await edit_orchestrator.execute_tool(
            "sync_probe",
            {"filePath": "notes.txt", "target": "local"},
            config={"safety": {"enabled": False}},
        )
    finally:
        reset_execution_port(sync_token)
    assert edit_result == "edited:notes.txt"


def test_w1_c03_negative():
    """NativeBackend refuses a call that did not come from ToolOrchestrator."""
    from rxycode_core.runtime.execution_port import NativeBackend, ToolEvent
    from rxycode_protocol.tool_rpc import ToolCall

    called = {"n": 0}

    def runner() -> ToolEvent:
        called["n"] += 1
        return ToolEvent(ok=True, status="OK", tool="bash", target_id="local", text="ran", version=1)

    event = NativeBackend().invoke(
        ToolCall(name="bash", target_id="local", arguments={"command": "echo hi"}, version=1),
        runner,
    )
    assert event.status == "BLOCKED"
    assert event.ok is False
    assert called["n"] == 0
    with pytest.raises(ValueError):
        ToolCall.from_dict(
            {
                "name": "bash",
                "target_id": "local",
                "arguments": {},
                "version": 0,
                "call_id": "x",
            }
        )
