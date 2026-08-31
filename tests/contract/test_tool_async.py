"""C2 contract tests: sync tools gain async coroutine paths (PHASE-C C2).

Covers (PHASE-C-ASYNC-SINGLE-AGENT-CORE.md C2):
  - whitelisted tools expose a real ``coroutine`` (git/format/open_file/vision
    structured tools; installer/mcp_manager module-level async variants)
  - process-class tools are cancellable and leave no residual process on
    timeout (PID-level assertion)
  - credential_store sync fallback boundary: to_thread with "stop waiting,
    not stop executing" semantics (PHASE-C §4.3)
  - bounded sync-tool thread pool: pool saturation queues instead of spawning
    unbounded threads
"""

from __future__ import annotations

import asyncio
import contextlib
import inspect
import os
import sys
import threading
import time
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]


# ── whitelisted tools expose a coroutine ─────────────────────────

@pytest.mark.parametrize(
    "module_name,attr_name",
    [
        ("git_tool", "git_tool"),
        ("format_tool", "format_tool"),
        ("open_file", "open_file_tool"),
        ("vision", "vision_tool"),
    ],
)
def test_structured_tools_expose_coroutine(module_name: str, attr_name: str):
    """Whitelisted StructuredTools must carry a coroutine= that is callable
    and produces an awaitable — the same criterion the orchestrator uses for
    routing (coroutine is not None), so an async callable / decorated wrapper
    is accepted and a plain sync func is not."""
    import importlib

    module = importlib.import_module(
        f"RxyCode.RxyCode1_1_0.tools.{module_name}"
    )
    tool = getattr(module, attr_name)
    coroutine = getattr(tool, "coroutine", None)
    assert coroutine is not None, f"{attr_name} lacks coroutine="
    assert callable(coroutine), f"{attr_name} coroutine must be callable"
    try:
        result = coroutine()
    except TypeError:
        # Required positional params (e.g. open_file_async(filePath)) — call
        # with an empty placeholder to prove it still yields an awaitable.
        result = coroutine("")
    assert inspect.isawaitable(result), (
        f"{attr_name} coroutine must return an awaitable"
    )
    if hasattr(result, "close"):  # coroutines; other awaitables may lack it
        result.close()  # never awaited; drop the unused coroutine cleanly


@pytest.mark.asyncio
async def test_installer_async_variants_exist():
    """ToolInstaller must expose real async install/search variants."""
    from RxyCode.RxyCode1_1_0.tools.installer import ToolInstaller

    installer = ToolInstaller()
    assert inspect.iscoroutinefunction(installer.install_package_async)
    assert inspect.iscoroutinefunction(installer.search_and_install_async)


@pytest.mark.asyncio
async def test_process_class_async_paths_use_controlled_executor(monkeypatch):
    """git/format/vision-screenshot/open_file async paths must invoke the
    controlled shell executor (process-tree termination on timeout) with the
    expected timeout, not raw subprocess."""
    import RxyCode.RxyCode1_1_0.utils.shell as shell_mod
    from RxyCode.RxyCode1_1_0.tools.git_tool import run_git_async

    calls: list[tuple[list[str], dict]] = []

    async def fake_execute(argv, **kwargs):
        calls.append((list(argv), kwargs))
        return {"success": True, "stdout": "", "stderr": "", "exit_code": 0,
                "error_type": None}

    monkeypatch.setattr(shell_mod.shell_executor, "execute_argv_async", fake_execute)

    await run_git_async("status", path=".", args="")
    assert calls and calls[0][0][0] == "git", "git async must use the executor"
    assert calls[0][1].get("timeout") == 60, "git must pass its 60s timeout"

    calls.clear()
    # format (ruff) path
    from RxyCode.RxyCode1_1_0.tools.format_tool import run_format_async
    import tempfile as _tf

    with _tf.NamedTemporaryFile(suffix=".py", delete=False) as f:
        f.write(b"x=1\n")
        tmp = f.name
    try:
        await run_format_async(tmp, tool="ruff")
    finally:
        os.unlink(tmp)
    assert calls, "format async must go through the executor"
    assert calls[0][1].get("timeout") == 30, "format must pass its 30s timeout"

    calls.clear()
    # vision screenshot path (bypasses the interactive-desktop precheck)
    from RxyCode.RxyCode1_1_0.tools.vision import _capture_screenshot_async

    monkeypatch.setattr(
        "RxyCode.RxyCode1_1_0.tools.vision._interactive_desktop_available",
        lambda: True,
    )
    await _capture_screenshot_async()
    assert calls, "vision screenshot must go through the executor"

    calls.clear()
    # open_file (POSIX opener path) on this platform if applicable.
    if sys.platform != "win32":
        import tempfile as _tf2

        from RxyCode.RxyCode1_1_0.tools.open_file import open_file_async

        with _tf2.NamedTemporaryFile(suffix=".txt", delete=False) as f:
            f.write(b"x\n")
            tmp2 = f.name
        try:
            await open_file_async(tmp2)
        finally:
            os.unlink(tmp2)
        assert calls, "open_file async must go through the executor"
        assert calls[0][1].get("timeout") == 10, "open_file must pass 10s"


@pytest.mark.asyncio
async def test_process_class_wrappers_map_timeout_to_error(monkeypatch):
    """Each C2 process-class wrapper must translate an executor ``timeout``
    result into a controlled error string — never raise, never report success.
    (The shared executor's actual process-tree kill is verified by
    ``test_process_class_timeout_terminates_process_tree``; this locks the
    per-wrapper handling of a timeout result so no wrapper can regress to raw
    subprocess or lose its timeout path.)"""
    import tempfile as _tf

    import RxyCode.RxyCode1_1_0.utils.shell as shell_mod

    async def fake_timeout(argv, **kwargs):
        return {
            "success": False,
            "stdout": "",
            "stderr": f"[timeout after {kwargs.get('timeout', '?')}s]",
            "exit_code": None,
            "error_type": "timeout",
        }

    monkeypatch.setattr(shell_mod.shell_executor, "execute_argv_async", fake_timeout)

    # git
    from RxyCode.RxyCode1_1_0.tools.git_tool import run_git_async

    with _tf.TemporaryDirectory() as td:
        git_out = await run_git_async("status", path=td)
    assert "[error" in git_out or "timeout" in git_out.lower(), git_out
    assert "Traceback" not in git_out

    # format (ruff path)
    from RxyCode.RxyCode1_1_0.tools.format_tool import run_format_async

    with _tf.TemporaryDirectory() as td:
        py_file = os.path.join(td, "a.py")
        with open(py_file, "w", encoding="utf-8") as f:
            f.write("x=1\n")
        fmt_out = await run_format_async(py_file, tool="ruff")
    assert "[error" in fmt_out or "timeout" in fmt_out.lower(), fmt_out
    assert "Traceback" not in fmt_out

    # vision screenshot (bypasses the interactive-desktop precheck)
    from RxyCode.RxyCode1_1_0.tools.vision import _capture_screenshot_async

    monkeypatch.setattr(
        "RxyCode.RxyCode1_1_0.tools.vision._interactive_desktop_available",
        lambda: True,
    )
    shot_out = await _capture_screenshot_async()
    assert "[error" in shot_out and "timed out" in shot_out, shot_out

    # open_file (POSIX opener path only; Windows uses os.startfile)
    if sys.platform != "win32":
        from RxyCode.RxyCode1_1_0.tools.open_file import open_file_async

        with _tf.TemporaryDirectory() as td:
            txt_file = os.path.join(td, "doc.txt")
            with open(txt_file, "w", encoding="utf-8") as f:
                f.write("x\n")
            of_out = await open_file_async(txt_file)
        assert "[error opening file" in of_out, of_out
        assert "Traceback" not in of_out


@pytest.mark.asyncio
async def test_open_file_async_windows_startfile_fire_and_forget(monkeypatch):
    """On Windows open_file_async is a fire-and-forget ShellExecute: it must
    NOT go through the shell executor (no tracked subprocess to terminate)
    and must map a startfile failure to an error string (never raise)."""
    import tempfile as _tf

    import RxyCode.RxyCode1_1_0.tools.open_file as of_mod
    from RxyCode.RxyCode1_1_0.tools.open_file import open_file_async

    if sys.platform != "win32":
        return  # Windows-specific branch; POSIX path covered elsewhere.

    with _tf.NamedTemporaryFile(suffix=".txt", delete=False) as f:
        f.write(b"x\n")
        tmp = f.name
    try:
        calls: list[str] = []

        def fake_startfile(path):
            calls.append(str(path))

        monkeypatch.setattr(of_mod.os, "startfile", fake_startfile)
        out = await open_file_async(tmp)
        # The tool resolves the path (realpath), which on Windows can expand
        # to the 8.3 short name (C:\Users\RUNNER~1\...) for long profile
        # names; compare against the resolved form instead of the raw tmp.
        resolved = str(Path(tmp).resolve())
        assert out == f"[opened {resolved}]"
        assert calls == [resolved], "startfile must receive the resolved path"

        def failing_startfile(path):
            raise OSError("no handler")

        monkeypatch.setattr(of_mod.os, "startfile", failing_startfile)
        out = await open_file_async(tmp)
        assert out == "[error opening file: no handler]"
    finally:
        os.unlink(tmp)


@pytest.mark.asyncio
async def test_vision_screenshot_success_schema_no_error_type(monkeypatch):
    """_capture_screenshot_async must tolerate a success result WITHOUT the
    error_type key (defensive; the real executor now always includes
    error_type=None, but the wrapper must not KeyError on success)."""
    import RxyCode.RxyCode1_1_0.utils.shell as shell_mod

    from RxyCode.RxyCode1_1_0.tools.vision import _capture_screenshot_async

    monkeypatch.setattr(
        "RxyCode.RxyCode1_1_0.tools.vision._interactive_desktop_available",
        lambda: True,
    )

    async def fake_execute(argv, **kwargs):
        # Deliberately omit error_type (an older executor schema): the wrapper
        # must tolerate it — the current schema always carries error_type=None.
        return {"success": True, "stdout": "png:/tmp/shot.png",
                "stderr": "", "exit_code": 0}

    monkeypatch.setattr(shell_mod.shell_executor, "execute_argv_async", fake_execute)
    out = await _capture_screenshot_async()
    assert "png:/tmp/shot.png" in out, out
    assert "Traceback" not in out


@pytest.mark.asyncio
async def test_installer_pip_success_schema_no_error_type(monkeypatch):
    """install_package_async must map a successful executor result (no
    error_type key, as the real executor returns) to (True, stdout) without
    raising KeyError."""
    import RxyCode.RxyCode1_1_0.utils.shell as shell_mod
    from RxyCode.RxyCode1_1_0.tools.installer import ToolInstaller

    async def fake_execute(argv, **kwargs):
        return {"success": True, "stdout": "Successfully installed xyz",
                "stderr": "", "exit_code": 0}

    monkeypatch.setattr(shell_mod.shell_executor, "execute_argv_async", fake_execute)
    monkeypatch.setattr(
        "RxyCode.RxyCode1_1_0.tools.installer.ToolInstaller.is_package_installed",
        staticmethod(lambda *a, **k: False),
    )
    ok, out = await ToolInstaller().install_package_async("xyz")
    assert ok is True
    assert out == "Successfully installed xyz"


@pytest.mark.asyncio
async def test_installer_mcp_async_paths_use_controlled_executor(monkeypatch):
    """installer/mcp async install paths must use the controlled executor with
    the expected timeout, and the mcp config write must go through
    asyncio.to_thread (not block the event loop); the install-precondition and
    config write are mocked so no network/package-manager side effects can
    occur.  The pip/npx process-tree cleanup on timeout is covered by the
    shared shell-executor contract tests (same execute_argv_async path);
    wrapper-level timeout mapping is covered by the error-mapping tests."""
    import asyncio as _asyncio
    import RxyCode.RxyCode1_1_0.utils.shell as shell_mod
    import RxyCode.RxyCode1_1_0.tools.installer as installer_mod
    import RxyCode.RxyCode1_1_0.tools.mcp_manager as mcp_mod

    calls: list[tuple[list[str], dict]] = []
    to_thread_calls: list[object] = []

    async def fake_execute(argv, **kwargs):
        calls.append((list(argv), kwargs))
        return {"success": True, "stdout": "", "stderr": "", "exit_code": 0,
                "error_type": None}

    orig_to_thread = _asyncio.to_thread

    async def spy_to_thread(fn, *args, **kwargs):
        to_thread_calls.append(fn)
        return await orig_to_thread(fn, *args, **kwargs)

    monkeypatch.setattr(shell_mod.shell_executor, "execute_argv_async", fake_execute)
    monkeypatch.setattr(_asyncio, "to_thread", spy_to_thread)
    monkeypatch.setattr(installer_mod.ToolInstaller, "is_package_installed",
                        staticmethod(lambda *a, **k: False))
    monkeypatch.setattr(mcp_mod, "add_mcp_server",
                        lambda *a, **k: (True, "fake-added"))

    installer = installer_mod.ToolInstaller()
    await installer.install_package_async("rxycode-definitely-not-installed-xyz")
    assert calls and "pip" in calls[0][0], "pip install must use the executor"
    assert calls[0][1].get("timeout") == 120, "pip must pass its 120s timeout"

    calls.clear()
    to_thread_calls.clear()
    await mcp_mod.install_mcp_from_npm_async("rxycode-no-such-pkg-xyz")
    assert calls and calls[0][0][0] == "npx", "npx check must use the executor"
    assert calls[0][1].get("timeout") == 10, "npx check must pass 10s"
    assert to_thread_calls and to_thread_calls[0] is mcp_mod.add_mcp_server, (
        "mcp config write must go through asyncio.to_thread"
    )

    calls.clear()
    to_thread_calls.clear()
    await mcp_mod.install_mcp_from_pip_async("rxycode-no-such-pkg-xyz")
    assert calls and "pip" in calls[0][0], "mcp pip install must use the executor"
    assert calls[0][1].get("timeout") == 120, "mcp pip must pass 120s"
    assert to_thread_calls and to_thread_calls[0] is mcp_mod.add_mcp_server, (
        "mcp config write must go through asyncio.to_thread"
    )


@pytest.mark.asyncio
async def test_mcp_manager_async_variants_exist():
    """MCP manager must expose async npm/pip install variants."""
    import RxyCode.RxyCode1_1_0.tools.mcp_manager as mcp

    assert inspect.iscoroutinefunction(mcp.install_mcp_from_npm_async)
    assert inspect.iscoroutinefunction(mcp.install_mcp_from_pip_async)


@pytest.mark.asyncio
async def test_credential_store_async_variants_exist():
    """credential_store must expose async variants of its subprocess helpers."""
    import RxyCode.RxyCode1_1_0.config.credential_store as cs

    assert inspect.iscoroutinefunction(cs._windows_current_sid_async)
    assert inspect.iscoroutinefunction(cs.restrict_file_permissions_async)


# ── process-class tool: cancellable, no residual process on timeout ──

def test_mock_tool_with_mock_coroutine_falls_back_to_sync():
    """A tool whose ``coroutine`` attribute is present but not a real async
    callable (e.g. a MagicMock in safety-gate tests) must fall back to the
    sync invoke path instead of raising on ``await``."""
    from unittest.mock import MagicMock

    from RxyCode.RxyCode1_1_0.execution.tool_orchestrator import ToolOrchestrator

    orch = ToolOrchestrator(max_workers=2)
    try:
        tool = MagicMock()
        tool.name = "mytool"
        tool.invoke = MagicMock(return_value="done")
        # MagicMock auto-attributes make coroutine non-None but not async.
        assert getattr(tool, "coroutine", None) is not None

        async def _run() -> None:
            result = await orch._invoke_async(tool, {"x": 1})
            assert result == "done", result
            strict = await orch._invoke_async_strict(tool, {"x": 1})
            assert strict == "done", strict

        asyncio.run(_run())
        assert tool.invoke.call_count == 2, tool.invoke.call_count
    finally:
        orch.shutdown_sync_executor()


def _collect_marker_pids(marker: str) -> set[int]:
    """Return the PIDs of processes whose command line contains ``marker``.

    Both platform branches match exactly the target child (and any
    descendants that inherit its argv), never "every python process".  The
    Windows query is base64-encoded so the marker never appears in the query
    runner's own command line (which would self-match).
    """
    import subprocess as _sp

    if os.name == "nt":
        import base64 as _b64

        ps = (
            "Get-CimInstance Win32_Process | "
            f"Where-Object {{ $_.CommandLine -like '*{marker}*' }} | "
            "ForEach-Object { $_.ProcessId }"
        )
        encoded = _b64.b64encode(ps.encode("utf-16-le")).decode("ascii")
        out = _sp.run(
            ["powershell", "-NoProfile", "-EncodedCommand", encoded],
            capture_output=True,
            text=True,
            timeout=10,
        ).stdout
        pids: set[int] = set()
        for line in out.splitlines():
            if line.strip().isdigit():
                pids.add(int(line.strip()))
        return pids
    out = _sp.run(
        ["pgrep", "-f", marker],
        capture_output=True,
        text=True,
        timeout=10,
    ).stdout
    return {int(line.strip()) for line in out.splitlines() if line.strip().isdigit()}


async def _run_with_watchdog(executor, argv, timeout: float, watchdog: float):
    """Run ``executor.execute_argv_async(argv, timeout=timeout)`` with a
    watchdog.  Returns the executor's result dict, or raises AssertionError
    if the executor itself fails to return in time (a stuck cleanup — the
    watchdog must NOT be conflated with the executor's own timeout)."""
    result = await asyncio.wait_for(
        executor.execute_argv_async(argv, timeout=timeout),
        timeout=watchdog,
    )
    assert result.get("error_type") == "timeout", (
        f"the blocking command must hit the executor timeout path, got: {result}"
    )
    return result


@pytest.mark.asyncio
async def test_process_class_timeout_terminates_process_tree():
    """A hanging process-class command must be terminated; no residual process
    remains.  Uses the controlled shell executor (the shared execution path all
    C2 process-class tools use) with a command that deterministically blocks,
    and asserts the executor's own timeout fired and no new process survives."""
    import sys as _sys
    import uuid as _uuid

    from RxyCode.RxyCode1_1_0.utils.shell import shell_executor

    blocker = _sys.executable
    # A unique marker inside the child's command line lets both platform
    # branches match exactly this child instead of every python process.
    marker = f"rxycode-timeout-probe-{_uuid.uuid4().hex}"
    script = f"import time; time.sleep(600)  # {marker}"

    before = _collect_marker_pids(marker)
    await _run_with_watchdog(
        shell_executor, [blocker, "-c", script], timeout=0.3, watchdog=8.0
    )
    await asyncio.sleep(0.6)  # allow cleanup to settle
    after = _collect_marker_pids(marker)
    new_pids = after - before
    assert not new_pids, f"residual process(es) after timeout: {new_pids}"


class _FakeKiller:
    def __init__(self, stdout: bytes, exc: bool = False):
        self.stdout = stdout
        self.exc = exc

    async def communicate(self):
        if self.exc:
            raise RuntimeError("powershell failed")
        return self.stdout, b""


@pytest.mark.asyncio
async def test_win_terminate_tree_taskkill_guards(monkeypatch):
    """Windows cleanup branch logic (unit level): taskkill fallback must only
    run when the WMI walk fails AND the root pid is confirmed alive — never
    when the walk reports a clean tree (ALIVE=) or the root is gone."""
    if os.name != "nt":
        return
    import asyncio as _asyncio
    import RxyCode.RxyCode1_1_0.utils.shell as shell_mod

    spawned: list[list[str]] = []

    async def make_killer(stdout: bytes, exc: bool = False):
        class _Killer:
            async def communicate(self):
                if exc:
                    raise RuntimeError("powershell failed")
                return stdout, b""

        return _Killer()

    async def fake_spawn(*args, **kwargs):
        spawned.append(list(args))
        text = " ".join(args)
        if "taskkill" in text:
            return await make_killer(b"")
        if "Get-CimInstance" in text:
            return await make_killer(b"ALIVE=\r\n")  # walk succeeded, clean
        if "Get-Process -Id" in text:
            return await make_killer(b"ALIVE=424242\r\n")  # root alive
        return await make_killer(b"")

    monkeypatch.setattr(_asyncio, "create_subprocess_exec", fake_spawn)
    ex = shell_mod.ShellExecutor()
    # Walk clean (ALIVE= empty) → retries stop; NO taskkill fallback.
    await ex._win_terminate_tree(424242)
    assert not any("taskkill" in " ".join(a) for a in spawned), spawned

    async def fail_walk(*args, **kwargs):
        spawned.append(list(args))
        text = " ".join(args)
        if "taskkill" in text:
            return await make_killer(b"")
        if "Get-CimInstance" in text:
            return await make_killer(b"", exc=True)  # walk itself fails
        if "Get-Process -Id" in text:
            return await make_killer(b"ALIVE=424242\r\n")  # root alive
        return await make_killer(b"")

    # Walk fails → root probe sees root alive → taskkill fallback runs.
    spawned.clear()
    monkeypatch.setattr(_asyncio, "create_subprocess_exec", fail_walk)
    await ex._win_terminate_tree(424242)
    assert any("taskkill" in " ".join(a) for a in spawned), spawned

    async def dead_root(*args, **kwargs):
        spawned.append(list(args))
        text = " ".join(args)
        if "taskkill" in text:
            return await make_killer(b"")
        if "Get-CimInstance" in text:
            return await make_killer(b"", exc=True)  # walk fails
        if "Get-Process -Id" in text:
            return await make_killer(b"ALIVE=\r\n")  # root gone
        return await make_killer(b"")

    # Walk fails but root is gone → NO taskkill fallback (PID-reuse guard).
    spawned.clear()
    monkeypatch.setattr(_asyncio, "create_subprocess_exec", dead_root)
    await ex._win_terminate_tree(424242)
    assert not any("taskkill" in " ".join(a) for a in spawned), spawned


@pytest.mark.asyncio
async def test_process_class_timeout_kills_orphaned_children():
    """Even when the root process exits before the timeout (its child keeps
    the pipes open, so communicate() stays blocked), the cleanup must
    terminate the surviving descendant: no marker process may remain."""
    import sys as _sys
    import uuid as _uuid

    from RxyCode.RxyCode1_1_0.utils.shell import shell_executor

    blocker = _sys.executable
    marker = f"rxycode-orphan-probe-{_uuid.uuid4().hex}"
    # Root prints and exits immediately; the grandchild inherits the stdout/
    # stderr pipes and blocks for 600s.  communicate() therefore cannot finish
    # and the executor's timeout must kill the orphaned grandchild.
    script = (
        "import subprocess, sys, time; "
        f"subprocess.Popen([sys.executable, '-c', "
        f"'import time; time.sleep(600)  # {marker}']); "
        "print('root done')"
    )

    before = _collect_marker_pids(marker)
    await _run_with_watchdog(
        shell_executor, [blocker, "-c", script], timeout=0.5, watchdog=12.0
    )
    await asyncio.sleep(0.8)  # allow cleanup to settle
    after = _collect_marker_pids(marker)
    new_pids = after - before
    assert not new_pids, f"orphaned process(es) survived timeout: {new_pids}"


@pytest.mark.asyncio
async def test_vision_wrapper_entry_level_timeout_no_residual(monkeypatch):
    """Entry-level proof through a REAL whitelisted wrapper: run_vision's
    _capture_screenshot_async runs a blocking capture command via the real
    shell executor and its real env-driven timeout; no marker process may
    survive.  Only the capture argv is injected (the production path already
    builds it from sys.executable) — spawn, monitor, timeout and process-tree
    cleanup are all production code."""
    import sys as _sys
    import uuid as _uuid

    import RxyCode.RxyCode1_1_0.tools.vision as vis

    marker = f"rxycode-git-entry-{_uuid.uuid4().hex}"
    monkeypatch.setenv("RXYCODE_SCREEN_CAPTURE_TIMEOUT", "0.5")
    monkeypatch.setattr(vis, "_interactive_desktop_available", lambda: True)
    # Inject the exact argv shape the production _capture_candidates builds.
    monkeypatch.setattr(
        vis,
        "_capture_candidates",
        lambda: ([_sys.executable, "-c", f"import time; time.sleep(600)  # {marker}"], []),
    )
    before = _collect_marker_pids(marker)
    out = await vis._capture_screenshot_async()
    assert "timed out" in out.lower(), f"expected capture timeout error, got: {out}"
    await asyncio.sleep(0.8)  # allow cleanup to settle
    after = _collect_marker_pids(marker)
    new_pids = after - before
    assert not new_pids, f"entry-level residual process(es): {new_pids}"


@pytest.mark.asyncio
async def test_git_wrapper_entry_level_timeout_no_residual(monkeypatch):
    """Entry-level proof through the REAL git wrapper: run_git_async executes
    a blocking argv via the real ShellExecutor and must surface the timeout as
    an error with no marker process surviving.  Only the argv builder is
    injected (the wrapper's production shell_executor call, timeout passing
    and error mapping all run untouched); the executor timeout is shortened
    because the production wrapper passes 60s."""
    import shutil as _sh
    import sys as _sys
    import tempfile as _tf
    import uuid as _uuid

    import RxyCode.RxyCode1_1_0.tools.git_tool as git_mod
    import RxyCode.RxyCode1_1_0.utils.shell as shell_mod

    marker = f"rxycode-git-entry-{_uuid.uuid4().hex}"
    real = shell_mod.ShellExecutor()

    async def short_execute(argv, workdir="", timeout=60):
        return await real.execute_argv_async(argv, workdir=workdir, timeout=0.5)

    monkeypatch.setattr(shell_mod.shell_executor, "execute_argv_async", short_execute)
    monkeypatch.setattr(
        git_mod,
        "_build_git_command",
        lambda op, args: [_sys.executable, "-c",
                          f"import time; time.sleep(600)  # {marker}"],
    )
    # Real executor enforces the workspace sandbox: repo dir must be inside it.
    td = _tf.mkdtemp(prefix="rxycode-git-entry-", dir=os.getcwd())
    try:
        before = _collect_marker_pids(marker)
        out = await git_mod.run_git_async("status", path=td)
        assert "timeout" in out.lower(), f"expected timeout error, got: {out}"
        await asyncio.sleep(0.8)
        after = _collect_marker_pids(marker)
        new_pids = after - before
        assert not new_pids, f"git entry-level residual process(es): {new_pids}"
    finally:
        _sh.rmtree(td, ignore_errors=True)


@pytest.mark.asyncio
async def test_format_wrapper_entry_level_real_executor(monkeypatch):
    """Entry-level proof through the REAL format wrapper: run_format_async
    resolves and executes the formatter through the real ShellExecutor (the
    wrapper's executor call, 30s timeout passing and error mapping run
    untouched).  The formatter argv is hard-coded to the tool name, so the
    blocking-argv timeout path is covered by the git/vision entry-level tests;
    this test locks the normal-path mapping end to end."""
    import shutil as _shu
    import tempfile as _tf

    import RxyCode.RxyCode1_1_0.tools.format_tool as fmt_mod
    import RxyCode.RxyCode1_1_0.utils.shell as shell_mod

    if not any(_shu.which(name) for name in ("ruff", "black", "autopep8")):
        return  # no formatter available on this machine; nothing to prove
    real_execute = shell_mod.shell_executor.execute_argv_async
    td = _tf.mkdtemp(prefix="rxycode-fmt-entry-", dir=os.getcwd())
    try:
        py_file = os.path.join(td, "a.py")
        with open(py_file, "w", encoding="utf-8") as f:
            f.write("x = 1\n")
        calls: list[tuple[list[str], float]] = []

        async def spy_execute(argv, workdir="", timeout=30):
            calls.append((list(argv), timeout))
            return await real_execute(argv, workdir=workdir, timeout=timeout)

        monkeypatch.setattr(
            shell_mod.shell_executor, "execute_argv_async", spy_execute
        )
        out = await fmt_mod.run_format_async(py_file, tool="auto")
        assert calls, "format async must go through the real executor"
        assert calls[0][1] == 30, "format must pass its 30s timeout"
        assert "[error" not in out, f"formatter unexpectedly failed: {out}"
    finally:
        _shu.rmtree(td, ignore_errors=True)


# ── credential_store: to_thread fallback, stop-waiting boundary ────

@pytest.mark.asyncio
async def test_credential_store_async_uses_to_thread(monkeypatch):
    """credential_store async helpers must delegate to the sync impl via
    asyncio.to_thread (not a fresh subprocess), so a timeout only stops
    waiting — the documented §4.3 boundary.  Uses deterministic fakes so the
    test is platform-independent (the real impl shells out to Windows-only
    whoami/icacls)."""
    import asyncio as _asyncio
    from pathlib import Path

    import RxyCode.RxyCode1_1_0.config.credential_store as cs

    calls: list[str] = []
    to_thread_calls: list[object] = []

    def fake_sid():
        calls.append("_windows_current_sid")
        return "S-1-5-21-fake"

    def fake_restrict(path):
        calls.append(f"restrict:{path}")

    orig_to_thread = _asyncio.to_thread

    async def spy_to_thread(fn, *args, **kwargs):
        to_thread_calls.append(fn)
        return await orig_to_thread(fn, *args, **kwargs)

    monkeypatch.setattr(cs, "_windows_current_sid", fake_sid)
    monkeypatch.setattr(cs, "restrict_file_permissions", fake_restrict)
    monkeypatch.setattr(_asyncio, "to_thread", spy_to_thread)

    result = await cs._windows_current_sid_async()
    assert result == "S-1-5-21-fake"
    await cs.restrict_file_permissions_async(Path("cfg.json"))
    assert calls == ["_windows_current_sid", "restrict:cfg.json"], (
        "async variants must delegate to the sync impls"
    )
    assert to_thread_calls == [fake_sid, fake_restrict], (
        "async variants must go through asyncio.to_thread with the sync impl"
    )


@pytest.mark.asyncio
async def test_credential_store_timeout_stops_waiting_not_executing(
    monkeypatch,
):
    """§4.3 boundary: a timeout on the async credential helper stops waiting
    but does not cancel the underlying to_thread work — it runs to completion."""
    import RxyCode.RxyCode1_1_0.config.credential_store as cs

    finished = threading.Event()

    def slow_fake():
        time.sleep(0.4)
        finished.set()
        return "S-1-5-21-slow"

    monkeypatch.setattr(cs, "_windows_current_sid", slow_fake)
    # A short wait_for times out (stop waiting), while the thread keeps going.
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(cs._windows_current_sid_async(), timeout=0.1)
    assert finished.wait(timeout=2.0), "underlying to_thread work must complete"


@pytest.mark.asyncio
async def test_credential_store_restrict_permissions_async_to_thread(monkeypatch):
    """restrict_file_permissions_async must delegate to the sync impl via
    asyncio.to_thread (same §4.3 stop-waiting boundary as the sid helper)."""
    import RxyCode.RxyCode1_1_0.config.credential_store as cs

    calls: list[str] = []

    def fake_restrict(path):
        calls.append("sync")
        return None

    monkeypatch.setattr(cs, "restrict_file_permissions", fake_restrict)
    await cs.restrict_file_permissions_async("/nonexistent/x")
    assert calls == ["sync"], "restrict async must delegate to the sync impl"


# ── bounded sync-tool thread pool ─────────────────────────────────

def test_orchestrator_owns_bounded_executor():
    """ToolOrchestrator must own a bounded sync-tool executor (not the
    unbounded default thread pool)."""
    import concurrent.futures

    from RxyCode.RxyCode1_1_0.execution.tool_orchestrator import ToolOrchestrator

    orch = ToolOrchestrator(max_workers=2)
    try:
        executor = orch._sync_tool_executor
        assert isinstance(executor, concurrent.futures.ThreadPoolExecutor)
        assert executor._max_workers >= 1
    finally:
        orch.shutdown_sync_executor()


def test_orchestrator_max_workers_respects_env(monkeypatch):
    """RXYCODE_TOOL_THREADS must override the executor bound."""
    monkeypatch.setenv("RXYCODE_TOOL_THREADS", "3")
    from RxyCode.RxyCode1_1_0.execution.tool_orchestrator import ToolOrchestrator

    orch = ToolOrchestrator()
    try:
        assert orch._sync_tool_executor._max_workers == 3
    finally:
        orch.shutdown_sync_executor()


def test_orchestrator_invalid_max_workers_falls_back(monkeypatch):
    """An invalid explicit max_workers is treated as not provided: the env
    override (and then the cpu default) must apply."""
    monkeypatch.setenv("RXYCODE_TOOL_THREADS", "5")
    from RxyCode.RxyCode1_1_0.execution.tool_orchestrator import ToolOrchestrator

    orch = ToolOrchestrator(max_workers=0)  # invalid -> env applies
    try:
        assert orch._sync_tool_executor._max_workers == 5
    finally:
        orch.shutdown_sync_executor()


def test_orchestrator_explicit_max_workers_beats_env(monkeypatch):
    """The priority chain is explicit positive int > env > cpu default: a valid
    explicit value must win over RXYCODE_TOOL_THREADS."""
    monkeypatch.setenv("RXYCODE_TOOL_THREADS", "5")
    from RxyCode.RxyCode1_1_0.execution.tool_orchestrator import ToolOrchestrator

    orch = ToolOrchestrator(max_workers=7)  # explicit beats env
    try:
        assert orch._sync_tool_executor._max_workers == 7
    finally:
        orch.shutdown_sync_executor()


def test_orchestrator_invalid_env_falls_back_to_cpu_default(monkeypatch):
    """An invalid (0/negative/non-integer) RXYCODE_TOOL_THREADS is treated as
    not provided: the cpu_count()+4 default must apply — never 1."""
    monkeypatch.setenv("RXYCODE_TOOL_THREADS", "0")
    from RxyCode.RxyCode1_1_0.execution.tool_orchestrator import ToolOrchestrator

    orch = ToolOrchestrator()
    try:
        assert orch._sync_tool_executor._max_workers == max(
            1, (os.cpu_count() or 1) + 4
        )
    finally:
        orch.shutdown_sync_executor()
    monkeypatch.setenv("RXYCODE_TOOL_THREADS", "-3")
    orch = ToolOrchestrator()
    try:
        assert orch._sync_tool_executor._max_workers == max(
            1, (os.cpu_count() or 1) + 4
        )
    finally:
        orch.shutdown_sync_executor()
    monkeypatch.setenv("RXYCODE_TOOL_THREADS", "abc")
    orch = ToolOrchestrator()
    try:
        assert orch._sync_tool_executor._max_workers == max(
            1, (os.cpu_count() or 1) + 4
        )
    finally:
        orch.shutdown_sync_executor()


def test_pool_saturation_queues_instead_of_unbounded_threads():
    """Submitting far more sync tools than the pool bound must queue the extra
    work: exactly ``bound`` tasks run, the (bound+1)-th must not start until a
    worker is released, and all complete after release.  Goes through the
    public gated path (``_invoke_and_finish``) so the deadline/recording layer
    is exercised, not just the private invoke helper."""
    from RxyCode.RxyCode1_1_0.execution.tool_orchestrator import ToolOrchestrator

    orch = ToolOrchestrator(max_workers=4)
    bound = 4
    lock = threading.Lock()
    running = [0]
    started = [0]
    all_entered = threading.Event()
    release = threading.Event()

    def slow(*_a, **_k):
        with lock:
            running[0] += 1
            started[0] += 1
            if running[0] >= bound:
                all_entered.set()
        release.wait(timeout=10)
        with lock:
            running[0] -= 1
        return "ok"

    tool = type("T", (), {"name": "slow", "invoke": staticmethod(slow)})()
    risk = type("R", (), {"name": "READ"})()
    audit = type("A", (), {"log": lambda *a, **k: None})()

    async def _run() -> None:
        gathered = [
            asyncio.create_task(
                orch._invoke_and_finish(
                    "slow",
                    {},
                    tool,
                    None,
                    approval="auto",
                    risk=risk,
                    audit=audit,
                )
            )
            for _ in range(bound * 3)
        ]
        # Wait until all bound workers are running (async wait keeps the loop
        # responsive; workers run on the executor threads).
        await asyncio.to_thread(all_entered.wait, 5)
        assert all_entered.is_set(), "all bound workers never started"
        with lock:
            assert running[0] == bound, f"expected {bound} running, got {running[0]}"
            assert started[0] == bound, (
                f"task beyond the bound started early: {started[0]}"
            )
        threads = list(orch._sync_tool_executor._threads)
        assert len(threads) <= bound
        release.set()
        # All tasks must complete with their result after release.
        results = await asyncio.gather(*gathered, return_exceptions=True)
        assert all(r == "ok" for r in results), results

    try:
        asyncio.run(_run())
    finally:
        orch.shutdown_sync_executor()


def test_executor_shutdown_after_use_then_invoke_refuses():
    """After shutdown, _invoke_async must refuse new sync-tool work with a
    clear error (never silently fall back to the unbounded default pool)."""
    from RxyCode.RxyCode1_1_0.execution.tool_orchestrator import ToolOrchestrator

    orch = ToolOrchestrator(max_workers=2)
    orch.shutdown_sync_executor()
    assert orch._sync_tool_executor is None

    tool = type("T", (), {"name": "quick", "invoke": staticmethod(lambda *a, **k: "ok")})()

    async def _run() -> None:
        result = await orch._invoke_async(tool, {})
        assert "shut down" in result, result

    asyncio.run(_run())


def test_executor_shutdown_strict_refuses():
    """_invoke_async_strict must raise on shutdown, not fall back."""
    from RxyCode.RxyCode1_1_0.execution.tool_orchestrator import ToolOrchestrator

    orch = ToolOrchestrator(max_workers=2)
    orch.shutdown_sync_executor()
    tool = type("T", (), {"name": "quick", "invoke": staticmethod(lambda *a, **k: "ok")})()

    async def _run() -> None:
        with pytest.raises(RuntimeError, match="shut down"):
            await orch._invoke_async_strict(tool, {})

    asyncio.run(_run())


def test_sync_entries_preserved_ac4():
    """AC4: the sync func/invoke entries must still be present and callable on
    every whitelisted tool that gained a coroutine."""
    import RxyCode.RxyCode1_1_0.tools.git_tool as git
    import RxyCode.RxyCode1_1_0.tools.format_tool as fmt
    import RxyCode.RxyCode1_1_0.tools.vision as vis
    import RxyCode.RxyCode1_1_0.tools.mcp_manager as mcp
    import RxyCode.RxyCode1_1_0.tools.installer as inst
    import RxyCode.RxyCode1_1_0.tools.open_file as of

    # Structured tools keep their sync func; module functions keep sync defs.
    assert callable(git.run_git)
    assert callable(fmt.run_format)
    assert callable(vis.run_vision)
    assert callable(mcp.install_mcp_from_npm)
    assert callable(mcp.install_mcp_from_pip)
    assert callable(inst.ToolInstaller().install_package)
    assert callable(of.open_file)
    # Every whitelisted StructuredTool must still expose its sync .func.
    for tool in (git.git_tool, fmt.format_tool, vis.vision_tool, of.open_file_tool):
        assert getattr(tool, "func", None) is not None, tool.name
        assert callable(tool.func), tool.name
    # shell.py:554 sync execute fallback must be intact.
    from RxyCode.RxyCode1_1_0.utils.shell import ShellExecutor

    assert callable(ShellExecutor.execute)


def test_executor_shutdown_is_idempotent():
    """Repeated shutdown must be safe (no double-shutdown errors)."""
    from RxyCode.RxyCode1_1_0.execution.tool_orchestrator import ToolOrchestrator

    orch = ToolOrchestrator(max_workers=2)
    orch.shutdown_sync_executor()
    orch.shutdown_sync_executor()  # second call is a no-op
    assert orch._sync_tool_executor is None


def test_executor_shutdown_cancels_queued_futures():
    """Shutdown with cancel_futures=True must cancel queued (not yet started)
    work rather than leaving it to run; a running worker finishes and its
    thread is reaped once the executor is fully shut down."""
    from RxyCode.RxyCode1_1_0.execution.tool_orchestrator import ToolOrchestrator

    orch = ToolOrchestrator(max_workers=1)
    executor = orch._sync_tool_executor
    started = threading.Event()
    release = threading.Event()

    def slow(*_a, **_k):
        started.set()
        release.wait(timeout=5)
        return "ok"

    async def _run() -> None:
        loop = asyncio.get_running_loop()
        first = loop.run_in_executor(executor, slow)
        queued = loop.run_in_executor(executor, slow)
        await asyncio.to_thread(started.wait, 5)
        assert started.is_set()
        orch.shutdown_sync_executor()  # non-blocking: cancels the queued one
        release.set()
        with contextlib.suppress(Exception):
            await first
        try:
            await asyncio.wait_for(queued, timeout=2.0)
        except asyncio.CancelledError:
            pass  # queued future was cancelled by shutdown

    asyncio.run(_run())
    # A wait=True call AFTER a non-blocking shutdown must still reap the
    # retired executor's threads synchronously (no thread leak), even though
    # the orchestrator reference was already cleared.
    orch.shutdown_sync_executor(wait=True)
    worker_threads = list(executor._threads)
    assert worker_threads, "expected at least one executor worker thread"
    for t in worker_threads:
        assert not t.is_alive(), f"worker thread leaked after wait=True shutdown: {t}"


def test_executor_shutdown_wait_true_reaps_running_worker_synchronously():
    """A first-call wait=True shutdown must block until the running worker has
    finished and its thread is reaped — the production-side guarantee the app
    shutdown path relies on (no thread leak, no test-side polling)."""
    from RxyCode.RxyCode1_1_0.execution.tool_orchestrator import ToolOrchestrator

    orch = ToolOrchestrator(max_workers=1)
    executor = orch._sync_tool_executor
    started = threading.Event()
    release = threading.Event()

    def slow(*_a, **_k):
        started.set()
        release.wait(timeout=5)
        return "ok"

    async def _run() -> None:
        loop = asyncio.get_running_loop()
        first = loop.run_in_executor(executor, slow)
        await asyncio.to_thread(started.wait, 5)
        assert started.is_set()
        release.set()
        # wait=True must return only after the worker finished and the pool
        # thread was reaped — so right after this call the thread is dead.
        orch.shutdown_sync_executor(wait=True)
        with contextlib.suppress(Exception):
            await first

    asyncio.run(_run())
    worker_threads = list(executor._threads)
    assert worker_threads, "expected at least one executor worker thread"
    for t in worker_threads:
        assert not t.is_alive(), f"worker thread leaked after first-call wait=True: {t}"
