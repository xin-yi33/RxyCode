"""E4/E5: live tool dedup and read path contract."""
import pytest

from RxyCode.RxyCode1_1_0.execution.tool_orchestrator import ToolOrchestrator
from RxyCode.RxyCode1_1_0.tools.read import read_file


def test_read_rejects_glob_wildcard():
    out = read_file("foo/*.log")
    assert "error" in out.lower()
    assert "glob" in out.lower() or "通配" in out


def test_read_rejects_directory_with_hint(tmp_path):
    d = tmp_path / "subdir"
    d.mkdir()
    out = read_file(str(d))
    assert "error" in out.lower()
    assert "ls" in out.lower() or "glob" in out.lower() or "目录" in out


@pytest.mark.asyncio
async def test_execute_tool_skips_identical_args():
    orch = ToolOrchestrator()
    calls = {"n": 0}

    async def gated(name, args, config, **kw):
        calls["n"] += 1
        return f"result-{calls['n']}"

    orch._execute_tool_gated = gated  # type: ignore
    ToolOrchestrator.clear_live_dedup()
    r1 = await orch.execute_tool("read", {"filePath": "a.py", "offset": 1})
    r2 = await orch.execute_tool("read", {"filePath": "a.py", "offset": 1})
    assert calls["n"] == 1
    assert r1 == "result-1"
    assert "重复" in r2 or "跳过" in r2
