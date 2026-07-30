"""E4/E5 expanded: live tool dedup, canonical args, cooldown matrices."""

from __future__ import annotations

import itertools
import json

import pytest

from RxyCode.RxyCode1_1_0.execution.tool_orchestrator import (
    ToolOrchestrator,
    _canonical_tool_args,
)


_TOOLS = (
    "read", "grep", "glob", "ls", "view", "write", "edit", "bash",
    "websearch", "webfetch", "datetime", "memory", "patch", "git", "open_file",
)

_PATHS = (
    "src/main.py",
    "tests/test_api.py",
    "README.md",
    "core/agent_v2.py",
    "tools/read.py",
)

_OFFSETS = (1, 5, 10, 100)
_LIMITS = (50, 200, 800)


def _args_variants(tool: str) -> list[dict]:
    if tool in {"read", "view"}:
        return [
            {"filePath": path, "offset": off, "limit": lim}
            for path, off, lim in itertools.product(_PATHS[:3], _OFFSETS[:2], _LIMITS[:2])
        ]
    if tool == "grep":
        return [{"pattern": pat, "path": path} for pat, path in itertools.product(("error", "def "), _PATHS[:2])]
    if tool == "glob":
        return [{"pattern": pat} for pat in ("**/*.py", "**/test_*.py", "*.md")]
    if tool == "ls":
        return [{"path": path} for path in _PATHS[:3]]
    if tool == "write":
        return [{"filePath": path, "content": "x"} for path in _PATHS[:2]]
    return [{"query": f"q-{tool}-{idx}"} for idx in range(3)]


_DEDUP_CASES = [
    (tool, args)
    for tool in _TOOLS
    for args in _args_variants(tool)[:5]
]


@pytest.mark.parametrize(("tool", "args"), _DEDUP_CASES)
def test_dedup_key_stable_for_same_args(tool: str, args: dict):
    orch = ToolOrchestrator()
    k1 = orch._dedup_key(tool, args)
    k2 = orch._dedup_key(tool, args)
    assert k1 == k2
    assert tool.lower() in k1


@pytest.mark.parametrize(("tool", "args"), _DEDUP_CASES)
def test_dedup_key_differs_when_args_change(tool: str, args: dict):
    orch = ToolOrchestrator()
    base = orch._dedup_key(tool, args)
    mutated = dict(args)
    if "offset" in mutated:
        mutated["offset"] = int(mutated["offset"]) + 1
    elif "filePath" in mutated:
        mutated["filePath"] = str(mutated["filePath"]) + ".bak"
    elif "pattern" in mutated:
        mutated["pattern"] = str(mutated["pattern"]) + "X"
    elif "query" in mutated:
        mutated["query"] = str(mutated["query"]) + "-alt"
    else:
        mutated["_extra"] = "1"
    assert orch._dedup_key(tool, mutated) != base


@pytest.mark.parametrize("payload", _DEDUP_CASES[:20])
def test_canonical_tool_args_json_roundtrip(payload):
    _tool, args = payload
    raw = _canonical_tool_args(args)
    assert json.loads(raw) == args


@pytest.mark.asyncio
@pytest.mark.parametrize(("tool", "args"), _DEDUP_CASES[:25])
async def test_execute_tool_skips_identical_live_calls(tool: str, args: dict):
    orch = ToolOrchestrator()
    calls = {"n": 0}

    async def gated(name, inner_args, config, **kw):
        del name, config, kw
        calls["n"] += 1
        return f"ok-{calls['n']}"

    orch._execute_tool_gated = gated  # type: ignore[method-assign]
    ToolOrchestrator.clear_live_dedup()
    first = await orch.execute_tool(tool, args)
    second = await orch.execute_tool(tool, args)
    assert calls["n"] == 1
    assert "重复" in second or "跳过" in second
    assert first.startswith("ok-")


@pytest.mark.asyncio
@pytest.mark.parametrize("tool", _TOOLS)
async def test_different_tools_with_same_payload_not_deduped(tool: str):
    orch = ToolOrchestrator()
    calls: list[str] = []

    async def gated(name, args, config, **kw):
        del args, config, kw
        calls.append(name)
        return name

    orch._execute_tool_gated = gated  # type: ignore[method-assign]
    ToolOrchestrator.clear_live_dedup()
    shared = {"filePath": "same.py", "offset": 1, "limit": 10}
    await orch.execute_tool("read", shared)
    await orch.execute_tool(tool, shared)
    if tool == "read":
        assert len(calls) == 1
    else:
        assert len(calls) == 2
