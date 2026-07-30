"""Real-process cancellation contract for the Bash tool."""

import asyncio
from contextlib import suppress
import os
from pathlib import Path
import shlex
import sys

import psutil
import pytest

from RxyCode.RxyCode1_1_0.execution.tool_orchestrator import ToolOrchestrator
from RxyCode.RxyCode1_1_0.tools.bash import bash_tool
from RxyCode.RxyCode1_1_0.tools.file_download import file_download_tool


pytestmark = pytest.mark.system


def _python_command(script: Path, ready_file: Path) -> str:
    if os.name == "nt":
        executable = sys.executable.replace("'", "''")
        script_arg = str(script).replace("'", "''")
        ready_arg = str(ready_file).replace("'", "''")
        return f"& '{executable}' '{script_arg}' '{ready_arg}'"
    return " ".join(
        shlex.quote(part) for part in (sys.executable, str(script), str(ready_file))
    )


async def _wait_for_pid(path: Path) -> int:
    while True:
        if path.exists():
            value = path.read_text(encoding="utf-8").strip()
            if value:
                return int(value)
        await asyncio.sleep(0.01)


@pytest.mark.asyncio
async def test_cancelling_bash_kills_its_real_child_process(tmp_path, monkeypatch):
    from RxyCode.RxyCode1_1_0.utils import shell as shell_module

    monkeypatch.setattr(
        shell_module,
        "load_config",
        lambda: {
            "execution": {
                "sandbox_mode": "workspace",
                "workspace_root": str(tmp_path),
                "max_memory_mb": 0,
                "max_processes": 0,
            }
        },
    )
    script = tmp_path / "long_running.py"
    ready_file = tmp_path / "child.pid"
    script.write_text(
        "import os, sys, time\n"
        "from pathlib import Path\n"
        "Path(sys.argv[1]).write_text(str(os.getpid()), encoding='utf-8')\n"
        "time.sleep(30)\n",
        encoding="utf-8",
    )

    orchestrator = ToolOrchestrator()
    orchestrator.register("bash", bash_tool)
    invocation = asyncio.create_task(
        orchestrator.execute_tool(
            "bash",
            {
                "command": _python_command(script, ready_file),
                "workdir": str(tmp_path),
                "timeout": 60,
            },
            config={"safety": {"enabled": False}},
        )
    )
    child_pid = None
    pid_waiter = asyncio.create_task(_wait_for_pid(ready_file))
    try:
        done, _pending = await asyncio.wait(
            {pid_waiter, invocation},
            timeout=10,
            return_when=asyncio.FIRST_COMPLETED,
        )
        if invocation in done:
            pytest.fail(
                "bash invocation completed before its child started: "
                f"{invocation.result()}"
            )
        if pid_waiter not in done:
            pytest.fail("bash child did not start within 10 seconds")
        child_pid = pid_waiter.result()
        assert psutil.pid_exists(child_pid)

        invocation.cancel()
        with pytest.raises(asyncio.CancelledError):
            await invocation

        process = psutil.Process(child_pid) if psutil.pid_exists(child_pid) else None
        if process is not None:
            await asyncio.to_thread(process.wait, 5)
        assert not psutil.pid_exists(child_pid)
    finally:
        if not pid_waiter.done():
            pid_waiter.cancel()
            with suppress(asyncio.CancelledError):
                await pid_waiter
        if not invocation.done():
            invocation.cancel()
            with suppress(asyncio.CancelledError):
                await invocation
        if child_pid is not None and psutil.pid_exists(child_pid):
            process = psutil.Process(child_pid)
            for child in process.children(recursive=True):
                with suppress(psutil.Error):
                    child.kill()
            with suppress(psutil.Error):
                process.kill()


@pytest.mark.asyncio
async def test_cancelling_download_removes_partial_file(tmp_path, monkeypatch):
    from RxyCode.RxyCode1_1_0.utils import safe_http

    first_chunk_sent = asyncio.Event()
    release_server = asyncio.Event()

    async def serve_slow_download(reader, writer):
        try:
            await reader.readuntil(b"\r\n\r\n")
            writer.write(
                b"HTTP/1.1 200 OK\r\n"
                b"Content-Length: 1048576\r\n"
                b"Connection: close\r\n\r\n"
                b"partial-data"
            )
            await writer.drain()
            first_chunk_sent.set()
            await release_server.wait()
        except (asyncio.IncompleteReadError, ConnectionError):
            pass
        finally:
            writer.close()
            with suppress(ConnectionError):
                await writer.wait_closed()

    server = await asyncio.start_server(serve_slow_download, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]

    async def resolve_test_address(_hostname, _port):
        return ["127.0.0.1"]

    monkeypatch.setattr(safe_http, "resolve_public_addresses", resolve_test_address)
    monkeypatch.setattr(safe_http, "is_public_address", lambda _address: True)
    target = tmp_path / "download.bin"
    orchestrator = ToolOrchestrator()
    orchestrator.register("download_file", file_download_tool)
    invocation = asyncio.create_task(
        orchestrator.execute_tool(
            "download_file",
            {"url": f"http://public.test:{port}/slow", "save_path": str(target)},
            config={"safety": {"enabled": False}},
        )
    )
    try:
        await asyncio.wait_for(first_chunk_sent.wait(), timeout=5)
        invocation.cancel()
        with pytest.raises(asyncio.CancelledError):
            await invocation

        assert not target.exists()
        assert list(tmp_path.glob("*.part")) == []
    finally:
        release_server.set()
        server.close()
        await server.wait_closed()
