"""Streaming shell capture contracts: bounded previews, exact artifacts, cleanup."""

from __future__ import annotations

import asyncio
import hashlib
import sys
import uuid
from pathlib import Path

import psutil
import pytest

from RxyCode.RxyCode1_1_0.core.session_runtime import bind_session, reset_session_binding
from RxyCode.RxyCode1_1_0.tools.bash import MAX_OUTPUT_CHARS, SPILL_PATH_PREFIX, _format_result
from RxyCode.RxyCode1_1_0.utils import output_capture as capture_module
from RxyCode.RxyCode1_1_0.utils import shell as shell_module
from RxyCode.RxyCode1_1_0.utils.output_capture import (
    CAPTURE_PREVIEW_BYTES_PER_STREAM,
    CAPTURE_READ_CHUNK_BYTES,
    BoundedOutputCapture,
)
from RxyCode.RxyCode1_1_0.utils.shell import ShellExecutor


@pytest.fixture
def isolated_shell(tmp_path, monkeypatch):
    session = f"capture-{uuid.uuid4().hex}"
    binding = bind_session(session)
    data_dir = tmp_path / "private-data"
    workdir = tmp_path / "workspace"
    workdir.mkdir()
    monkeypatch.setattr(
        shell_module,
        "load_config",
        lambda: {
            "execution": {
                "sandbox_mode": "host",
                "max_memory_mb": 0,
                "max_processes": 0,
            }
        },
    )
    monkeypatch.setattr(capture_module, "get_data_dir", lambda: data_dir)
    executor = object.__new__(ShellExecutor)
    executor.os_name = sys.platform
    executor.shell_type = "bash"
    executor.user_home = ""
    executor.desktop_path = ""
    executor.watchdog_checkpoints = ()
    executor.watchdog_idle_cpu_percent = shell_module.WATCHDOG_IDLE_CPU_PERCENT
    executor.watchdog_idle_kill_after = shell_module.WATCHDOG_IDLE_KILL_AFTER
    executor.watchdog_observe_seconds = shell_module.WATCHDOG_OBSERVE_SECONDS
    try:
        yield executor, data_dir, session, workdir
    finally:
        reset_session_binding(binding)


def _python_argv(code: str) -> list[str]:
    return [sys.executable, "-c", code]


def _digest_file(path: Path) -> tuple[int, str]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as source:
        while chunk := source.read(256 * 1024):
            size += len(chunk)
            digest.update(chunk)
    return size, digest.hexdigest()


@pytest.mark.asyncio
async def test_small_stdout_stderr_and_exit_contract_are_unchanged(isolated_shell):
    executor, _data_dir, _session, workdir = isolated_shell
    code = (
        "import os; "
        "os.write(1, '小输出'.encode('utf-8')); "
        "os.write(2, 'stderr-测'.encode('utf-8'))"
    )

    result = await executor.execute_argv_async(_python_argv(code), workdir=str(workdir))

    assert result["stdout"] == "小输出"
    assert result["stderr"] == "stderr-测"
    assert result["exit_code"] == 0
    assert result["success"] is True
    assert result["stdout_bytes"] == len("小输出".encode("utf-8"))
    assert result["stderr_bytes"] == len("stderr-测".encode("utf-8"))
    assert result["stdout_artifact"] is None
    assert result["stderr_artifact"] is None
    assert result["capture_error"] is None
    assert _format_result(result) == "小输出\nstderr-测"


@pytest.mark.asyncio
async def test_two_large_streams_are_bounded_and_artifacts_match_exact_bytes(isolated_shell, monkeypatch):
    executor, data_dir, session, workdir = isolated_shell
    payload = b"0123456789abcdef" * 1024
    iterations = 1536  # 24 MiB per stream, interleaved by the child process.
    expected = hashlib.sha256()
    for _ in range(iterations):
        expected.update(payload)
    expected_hash = expected.hexdigest()
    code = (
        "import os\n"
        f"payload = {payload!r}\n"
        f"for _ in range({iterations}):\n"
        "    for fd in (1, 2):\n"
        "        view = memoryview(payload)\n"
        "        while view:\n"
        "            view = view[os.write(fd, view):]\n"
    )

    result = await executor.execute_argv_async(_python_argv(code), workdir=str(workdir), timeout=45)

    expected_size = len(payload) * iterations
    assert result["success"] is True
    assert result["stdout_bytes"] == expected_size
    assert result["stderr_bytes"] == expected_size
    assert result["stdout_sha256"] == expected_hash
    assert result["stderr_sha256"] == expected_hash
    assert result["stdout_truncated"] is True
    assert result["stderr_truncated"] is True
    assert len(result["stdout"].encode("utf-8")) <= CAPTURE_PREVIEW_BYTES_PER_STREAM + 128
    assert len(result["stderr"].encode("utf-8")) <= CAPTURE_PREVIEW_BYTES_PER_STREAM + 128
    for stream in ("stdout", "stderr"):
        path = Path(result[f"{stream}_artifact"])
        assert path.parent == data_dir / "spill" / session
        assert _digest_file(path) == (expected_size, expected_hash)

    # bash formats the bounded previews and metadata only; it never opens or
    # concatenates the complete artifact back into memory.
    def forbidden_read_bytes(_path):
        raise AssertionError("bash formatter must not read full spill files")

    with monkeypatch.context() as context:
        context.setattr(Path, "read_bytes", forbidden_read_bytes)
        text = _format_result(result)
    assert len(text) < MAX_OUTPUT_CHARS + 1024
    assert text.count(SPILL_PATH_PREFIX) == 2


def test_utf8_split_across_capture_chunks_and_windows_locale(isolated_shell, monkeypatch):
    _executor, _data_dir, _session, _workdir = isolated_shell
    monkeypatch.setattr(capture_module.locale, "getpreferredencoding", lambda _do_setlocale=False: "cp936")
    capture = BoundedOutputCapture()
    prefix = b"x" * (capture_module.CAPTURE_SPILL_THRESHOLD_BYTES + 1)
    capture.feed("stdout", prefix)
    capture.feed("stdout", b"\xe6")
    capture.feed("stdout", b"\xb5\x8b\xe8")
    capture.feed("stdout", b"\xaf\x95")
    capture.feed("stderr", bytes.fromhex("e6b5"))
    capture.feed("stderr", b"\x8b-err")
    capture.end_stream("stdout")
    capture.end_stream("stderr")

    result = capture.finish()

    assert result["stdout"].endswith("测试")
    assert result["stderr"] == "测-err"
    assert Path(result["stdout_artifact"]).read_bytes() == prefix + "测试".encode("utf-8")
    assert Path(result["stderr_artifact"]).read_bytes() == "测-err".encode("utf-8")


def test_tail_guard_tracks_the_secret_redactor_marker_vocabulary():
    from RxyCode.RxyCode1_1_0.tools.secret_text import _REDACTION_MARKERS

    assert set(capture_module._REDACTION_MARKER_BYTES) == {
        marker.encode("ascii") for marker in _REDACTION_MARKERS
    }


def test_disk_failure_is_explicit_and_keeps_a_bounded_preview(isolated_shell, monkeypatch):
    executor, _data_dir, _session, workdir = isolated_shell
    monkeypatch.setattr(
        capture_module,
        "_open_capture_artifact",
        lambda _path: (_ for _ in ()).throw(OSError("disk full")),
    )
    code = "import sys; sys.stdout.write('A' * 100000); sys.stderr.write('E' * 100000)"

    result = asyncio.run(executor.execute_argv_async(_python_argv(code), workdir=str(workdir), timeout=15))

    assert result["success"] is True
    assert result["capture_error"]
    assert "OSError" in result["capture_error"]
    assert result["stdout_artifact"] is None
    assert result["stderr_artifact"] is None
    assert len(result["stdout"].encode("utf-8")) <= CAPTURE_PREVIEW_BYTES_PER_STREAM + 128
    assert len(result["stderr"].encode("utf-8")) <= CAPTURE_PREVIEW_BYTES_PER_STREAM + 128
    formatted = _format_result(result)
    assert "spill write failed" in formatted
    assert SPILL_PATH_PREFIX not in formatted


def test_spill_refuses_to_write_under_an_active_workspace(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    data_dir = workspace / "configured-data"
    workspace.mkdir()
    monkeypatch.setattr(capture_module, "get_data_dir", lambda: data_dir)
    capture = BoundedOutputCapture(forbidden_roots=(workspace,))
    capture.feed("stdout", b"x" * (capture_module.CAPTURE_SPILL_THRESHOLD_BYTES + 1))
    capture.end_stream("stdout")
    capture.end_stream("stderr")

    result = capture.finish()

    assert "overlaps the active workspace" in result["capture_error"]
    assert result["stdout_artifact"] is None
    assert not data_dir.exists()


def test_truncated_tail_is_omitted_when_a_redaction_marker_was_seen(
    isolated_shell,
):
    _executor, data_dir, session, _workdir = isolated_shell
    from RxyCode.RxyCode1_1_0.execution.tool_orchestrator import ToolOrchestrator

    raw = (
        b"prefix\n"
        + b"P" * 50000
        + b'\napi_key="SENSITIVE_SECRET_VALUE_CANARY"'
        + b"T" * (CAPTURE_PREVIEW_BYTES_PER_STREAM // 2 - len(b"SENSITIVE_SECRET_VALUE_CANARY") + 8)
    )
    capture = BoundedOutputCapture()
    marker_start = raw.index(b"api_key")
    split_at = marker_start + 3
    capture.feed("stdout", raw[:split_at])
    for offset in range(split_at, len(raw), 8192):
        capture.feed("stdout", raw[offset : offset + 8192])
    capture.end_stream("stdout")
    capture.end_stream("stderr")
    result = {
        **capture.finish(),
        "success": True,
        "exit_code": 0,
        "error_type": None,
    }

    preview = _format_result(result)
    cleaned = ToolOrchestrator._clean_tool_output(
        result["stdout"], {"context": {"max_tool_output_chars": 64000}}
    )

    assert "SECRET_VALUE_CANARY" not in preview
    assert "SECRET_VALUE_CANARY" not in cleaned
    assert "tail omitted for secret safety" in result["stdout"]
    assert Path(result["stdout_artifact"]).read_bytes() == raw
    assert Path(result["stdout_artifact"]).parent == data_dir / "spill" / session


def _matching_pids(marker: str) -> set[int]:
    matches: set[int] = set()
    for process in psutil.process_iter(["pid", "cmdline"]):
        try:
            command_line = " ".join(process.info.get("cmdline") or [])
            if marker in command_line:
                matches.add(int(process.info["pid"]))
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue
    return matches


def _handle_count() -> int | None:
    # psutil.process_iter caches per-process Windows handles. The preceding
    # marker scan must not make this resource assertion count its own cache.
    clear_process_cache = getattr(psutil.process_iter, "cache_clear", None)
    if clear_process_cache is not None:
        clear_process_cache()
    process = psutil.Process()
    try:
        return process.num_fds()
    except (AttributeError, psutil.Error):
        try:
            return process.num_handles()
        except (AttributeError, psutil.Error):
            return None


@pytest.mark.asyncio
async def test_pipe_read_failure_kills_blocked_writer_without_waiting_for_timeout(
    isolated_shell, monkeypatch
):
    executor, data_dir, session, workdir = isolated_shell
    marker = f"rxycode-pipe-read-failure-{uuid.uuid4().hex}"
    code = (
        "import os, time\n"
        f"marker = {marker!r}\n"
        "payload = b'x' * 65536\n"
        "while True:\n"
        "    for fd in (1, 2):\n"
        "        view = memoryview(payload)\n"
        "        while view:\n"
        "            view = view[os.write(fd, view):]\n"
        "    time.sleep(0.001)\n"
    )
    original_reader = shell_module._read_output_pipe

    class _BrokenPipe:
        def __init__(self, pipe):
            self.pipe = pipe
            self.read_once = False

        async def read(self, _size):
            if not self.read_once:
                self.read_once = True
                return await self.pipe.read(_size)
            raise OSError("C:\\private\\do-not-leak")

    async def fail_stdout_reader(pipe, capture, stream_name):
        if stream_name == "stdout":
            await asyncio.sleep(0.15)
            return await original_reader(_BrokenPipe(pipe), capture, stream_name)
        return await original_reader(pipe, capture, stream_name)

    monkeypatch.setattr(shell_module, "_read_output_pipe", fail_stdout_reader)
    spawned = []
    original_create = asyncio.create_subprocess_exec

    async def track_process(*args, **kwargs):
        process = await original_create(*args, **kwargs)
        if args and str(args[0]) == sys.executable:
            spawned.append(process)
        return process

    monkeypatch.setattr(asyncio, "create_subprocess_exec", track_process)
    before_tasks = set(asyncio.all_tasks())
    before_pids = _matching_pids(marker)

    result = await asyncio.wait_for(
        executor.execute_argv_async(
            _python_argv(code), workdir=str(workdir), timeout=60
        ),
        timeout=10,
    )

    assert result["success"] is False
    assert result["error_type"] == "execution_error"
    assert "stdout pipe read failed" in result["stderr"]
    assert "execution status unknown" in result["stderr"]
    assert "do-not-leak" not in result["stderr"]
    assert "stdout pipe read failed (OSError)" == result["capture_error"]
    assert result["stdout_bytes"] > 0
    assert result["stdout_artifact"] is None
    await asyncio.sleep(0.1)
    assert not (_matching_pids(marker) - before_pids)
    pending = [
        task
        for task in asyncio.all_tasks() - before_tasks
        if not task.done() and task is not asyncio.current_task()
    ]
    assert not pending, f"pipe failure left tasks pending: {pending}"
    spill_dir = data_dir / "spill" / session
    assert not spill_dir.exists() or not list(spill_dir.iterdir())
    assert len(spawned) == 1
    assert spawned[0].returncode is not None
    process_transport = spawned[0]._transport
    for fd in (1, 2):
        pipe_transport = process_transport.get_pipe_transport(fd)
        assert pipe_transport is not None and pipe_transport.is_closing()
        if sys.platform == "win32":
            assert pipe_transport._sock is None
        else:
            pipe = pipe_transport.get_extra_info("pipe")
            assert pipe is None or pipe.fileno() == -1


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel", [False, True], ids=["timeout", "cancel"])
async def test_large_output_timeout_and_cancel_reap_children_tasks_and_pipes(isolated_shell, cancel):
    executor, data_dir, session, workdir = isolated_shell
    marker = f"rxycode-output-cleanup-{uuid.uuid4().hex}"
    code = (
        "import os, time\n"
        f"marker = {marker!r}  # keep a unique marker in the child command line\n"
        "payload = b'z' * 65536\n"
        "for _ in range(64):\n"
        "    for fd in (1, 2):\n"
        "        view = memoryview(payload)\n"
        "        while view:\n"
        "            view = view[os.write(fd, view):]\n"
        "time.sleep(30)\n"
    )
    before_tasks = set(asyncio.all_tasks())
    before_handles = _handle_count()
    before_pids = _matching_pids(marker)

    if cancel:
        task = asyncio.create_task(
            executor.execute_argv_async(_python_argv(code), workdir=str(workdir), timeout=30)
        )
        await asyncio.sleep(0.2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, timeout=12)
    else:
        result = await asyncio.wait_for(
            executor.execute_argv_async(_python_argv(code), workdir=str(workdir), timeout=0.4),
            timeout=12,
        )
        assert result["error_type"] == "timeout"

    await asyncio.sleep(0.15)
    assert not (_matching_pids(marker) - before_pids)
    pending = [
        task
        for task in asyncio.all_tasks() - before_tasks
        if not task.done() and task is not asyncio.current_task()
    ]
    assert not pending, f"capture/reader tasks were left pending: {pending}"
    spill_dir = data_dir / "spill" / session
    assert not spill_dir.exists() or not list(spill_dir.iterdir())
    after_handles = _handle_count()
    if before_handles is not None and after_handles is not None:
        assert after_handles <= before_handles + 3
