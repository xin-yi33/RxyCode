"""WEB-W1-C03. MCP hints cannot lower the existing WRITE gate."""
from __future__ import annotations

import os
import subprocess
import sys
import venv
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
_SRC = REPO / "packages" / "rxycode-core" / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))


def _tool(name: str, annotations: dict[str, bool]):
    from langchain_core.tools import StructuredTool

    called = {"n": 0}

    async def body() -> str:
        called["n"] += 1
        return "ran"

    tool = StructuredTool.from_function(coroutine=body, name=name, description="mcp tool")
    tool.metadata = {"annotations": annotations}
    return tool, called


async def test_w1_c03_integration():
    """readOnlyHint stays WRITE; destructiveHint can only raise the risk."""
    from execution.tool_orchestrator import ToolOrchestrator

    readonly, readonly_called = _tool("mcp_widget", {"readOnlyHint": True})
    destructive, destructive_called = _tool("mcp_wipe", {"destructiveHint": True, "readOnlyHint": True})
    orchestrator = ToolOrchestrator()
    orchestrator.register("mcp_widget", readonly)
    orchestrator.register("mcp_wipe", destructive)
    config = {"safety": {"enabled": True}}
    readonly_result = await orchestrator.execute_tool("mcp_widget", {}, config=config)
    destructive_result = await orchestrator.execute_tool("mcp_wipe", {}, config=config)
    assert readonly_called["n"] == 0
    assert destructive_called["n"] == 0
    assert "WRITE" in readonly_result
    assert "no approval broker" in readonly_result
    assert "DANGER" in destructive_result
    assert "no approval broker" in destructive_result
    assert "READ" not in readonly_result


def test_w1_c03_installed_port(tmp_path: Path):
    """The runtime port imports from the wheel, not from a src path insert."""
    wheel_dir = tmp_path / "wheel"
    wheel_dir.mkdir()
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    env.pop("PYTHONHOME", None)
    build = subprocess.run(
        [sys.executable, "-m", "pip", "wheel", "--no-deps", "-w", str(wheel_dir), str(REPO)],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )
    assert build.returncode == 0, build.stderr
    wheels = list(wheel_dir.glob("rxycode-*.whl"))
    assert len(wheels) == 1
    env_dir = tmp_path / "venv"
    venv.create(env_dir, with_pip=True, system_site_packages=True)
    python = env_dir / "Scripts" / "python.exe" if os.name == "nt" else env_dir / "bin" / "python"
    install = subprocess.run(
        [str(python), "-m", "pip", "install", "--no-deps", str(wheels[0])],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )
    assert install.returncode == 0, install.stderr
    probe = subprocess.run(
        [
            str(python),
            "-c",
            "from pathlib import Path\n"
            "from rxycode_core.runtime.execution_port import ExecutionPort, ToolSpec\n"
            "from rxycode_protocol.tool_rpc import ToolCall\n"
            "port = ExecutionPort()\n"
            "assert ToolSpec(name='screenshot', version=1, required_capability='desktop').allows_execute() is False\n"
            "call = ToolCall(name='screenshot', target_id='phone', arguments={}, version=1)\n"
            "assert call.version == 1\n"
            "print(Path(port.__class__.__module__ and __import__('rxycode_core.runtime.execution_port', fromlist=['ExecutionPort']).__file__).resolve())\n"
            "print('installed-port-ok')\n",
        ],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )
    assert probe.returncode == 0, probe.stderr
    assert "installed-port-ok" in probe.stdout
    origin = next(line for line in probe.stdout.splitlines() if line.strip() and line.strip() != "installed-port-ok")
    assert str(env_dir.resolve()).casefold() in origin.casefold()
    assert str(REPO.resolve()).casefold() not in origin.casefold()
