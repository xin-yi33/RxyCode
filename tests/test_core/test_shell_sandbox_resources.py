"""Contracts for command sandboxing and process-tree resource limits."""

from __future__ import annotations

import asyncio
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from RxyCode.RxyCode1_1_0.utils import shell as shell_module
from RxyCode.RxyCode1_1_0.utils.shell import ShellExecutor


class _CompletedProcess:
    def __init__(
        self,
        *,
        returncode: int = 0,
        stdout: bytes = b"ok",
        stderr: bytes = b"",
    ) -> None:
        self.pid = 4100
        self.returncode = returncode
        self._stdout = stdout
        self._stderr = stderr

    async def communicate(self):
        return self._stdout, self._stderr

    async def wait(self):
        return self.returncode

    def kill(self):
        self.returncode = -9

    def terminate(self):
        self.returncode = -15


class _BlockingProcess(_CompletedProcess):
    def __init__(self) -> None:
        super().__init__(returncode=0)
        self.returncode = None

    async def communicate(self):
        await asyncio.Event().wait()


@pytest.fixture
def executor() -> ShellExecutor:
    instance = object.__new__(ShellExecutor)
    instance.os_name = "linux"
    instance.shell_type = "bash"
    instance.user_home = ""
    instance.desktop_path = ""
    instance.watchdog_checkpoints = shell_module.WATCHDOG_CHECKPOINTS
    instance.watchdog_idle_cpu_percent = shell_module.WATCHDOG_IDLE_CPU_PERCENT
    instance.watchdog_idle_kill_after = shell_module.WATCHDOG_IDLE_KILL_AFTER
    instance.watchdog_observe_seconds = shell_module.WATCHDOG_OBSERVE_SECONDS
    return instance


def _configure(monkeypatch, execution: dict) -> None:
    monkeypatch.setattr(
        shell_module, "load_config", lambda: {"execution": execution}
    )


def test_generated_default_config_reaches_real_shell_policy(
    executor, isolated_runtime, monkeypatch
):
    isolated_runtime.config_path.unlink()
    monkeypatch.chdir(isolated_runtime.workspace)

    policy = executor._execution_policy("")

    assert policy.mode == "workspace"
    assert policy.workspace_root == isolated_runtime.workspace.resolve()
    assert policy.cwd == isolated_runtime.workspace.resolve()
    assert policy.max_memory_mb == 4096
    assert policy.max_processes == 128

    with pytest.raises(ValueError, match="escapes"):
        executor._execution_policy(str(isolated_runtime.root))


@pytest.mark.asyncio
async def test_workspace_mode_rejects_parent_traversal_before_spawn(
    executor, tmp_path, monkeypatch
):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    _configure(
        monkeypatch,
        {"sandbox_mode": "workspace", "workspace_root": str(workspace)},
    )
    spawn = AsyncMock()
    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)

    result = await executor.execute_argv_async(
        ["python", "-V"], workdir=str(workspace / ".." / "outside")
    )

    assert result["success"] is False
    assert result["error_type"] == "sandbox_error"
    assert "outside" in result["stderr"]
    spawn.assert_not_awaited()


@pytest.mark.asyncio
async def test_workspace_relative_workdir_is_resolved_beneath_root(
    executor, tmp_path, monkeypatch
):
    workspace = tmp_path / "workspace"
    nested = workspace / "src"
    nested.mkdir(parents=True)
    _configure(
        monkeypatch,
        {"sandbox_mode": "workspace", "workspace_root": str(workspace)},
    )
    process = _CompletedProcess()
    spawn = AsyncMock(return_value=process)
    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)

    result = await executor.execute_argv_async(
        ["python", "-V"], workdir="src"
    )

    assert result["success"] is True
    assert spawn.await_args.kwargs["cwd"] == str(nested.resolve())
    assert "shell" not in spawn.await_args.kwargs


@pytest.mark.asyncio
async def test_docker_mode_builds_a_bounded_single_mount_command(
    executor, tmp_path, monkeypatch
):
    workspace = tmp_path / "workspace"
    nested = workspace / "pkg"
    nested.mkdir(parents=True)
    _configure(
        monkeypatch,
        {
            "sandbox_mode": "docker",
            "workspace_root": str(workspace),
            "docker_image": "python:3.12-alpine",
            "max_memory_mb": 256,
            "max_cpus": 1.5,
            "max_processes": 32,
        },
    )
    spawn = AsyncMock(return_value=_CompletedProcess())
    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)

    result = await executor.execute_async("python -V", workdir="pkg")

    assert result["success"] is True
    argv = list(spawn.await_args.args)
    assert argv[:3] == ["docker", "run", "--rm"]
    assert argv[argv.index("--network") + 1] == "none"
    mount_values = [argv[index + 1] for index, value in enumerate(argv) if value == "--mount"]
    assert mount_values == [
        f"type=bind,source={workspace.resolve()},target=/workspace"
    ]
    assert argv[argv.index("--workdir") + 1] == "/workspace/pkg"
    assert argv[argv.index("--memory") + 1] == "256m"
    assert argv[argv.index("--cpus") + 1] == "1.5"
    assert argv[argv.index("--pids-limit") + 1] == "32"
    image_index = argv.index("python:3.12-alpine")
    assert argv[image_index + 1 :] == ["/bin/sh", "-lc", "python -V"]
    assert spawn.await_args.kwargs["cwd"] is None
    assert "shell" not in spawn.await_args.kwargs


@pytest.mark.asyncio
async def test_missing_docker_runtime_fails_closed_without_host_fallback(
    executor, tmp_path, monkeypatch
):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    _configure(
        monkeypatch,
        {
            "sandbox_mode": "docker",
            "workspace_root": str(workspace),
            "docker_image": "missing:image",
        },
    )
    spawn = AsyncMock(side_effect=FileNotFoundError("docker"))
    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)

    result = await executor.execute_async("echo must-not-run")

    assert result["success"] is False
    assert result["error_type"] == "docker_sandbox"
    assert "host execution was not attempted" in result["stderr"]
    spawn.assert_awaited_once()
    assert spawn.await_args.args[0] == "docker"


@pytest.mark.asyncio
async def test_docker_image_cannot_inject_runtime_options(
    executor, tmp_path, monkeypatch
):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    _configure(
        monkeypatch,
        {
            "sandbox_mode": "docker",
            "workspace_root": str(workspace),
            "docker_image": "--privileged",
        },
    )
    spawn = AsyncMock()
    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)

    result = await executor.execute_async("id")

    assert result["error_type"] == "sandbox_error"
    assert "valid image reference" in result["stderr"]
    spawn.assert_not_awaited()


@pytest.mark.asyncio
async def test_docker_nonzero_exit_is_reported_as_sandbox_failure(
    executor, tmp_path, monkeypatch
):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    _configure(
        monkeypatch,
        {
            "sandbox_mode": "docker",
            "workspace_root": str(workspace),
            "docker_image": "missing:image",
        },
    )
    spawn = AsyncMock(
        return_value=_CompletedProcess(
            returncode=125, stderr=b"Unable to find image"
        )
    )
    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)

    result = await executor.execute_argv_async(["python", "-V"])

    assert result["success"] is False
    assert result["error_type"] == "docker_sandbox"
    assert result["stderr"].startswith("[docker_sandbox]")
    assert "Unable to find image" in result["stderr"]


@pytest.mark.asyncio
async def test_host_memory_limit_terminates_the_process_tree(
    executor, monkeypatch
):
    _configure(
        monkeypatch,
        {"sandbox_mode": "host", "max_memory_mb": 4, "max_processes": 0},
    )
    process = _BlockingProcess()
    monkeypatch.setattr(
        asyncio, "create_subprocess_exec", AsyncMock(return_value=process)
    )
    root = MagicMock()
    root.pid = process.pid
    root.children.return_value = []
    root.is_running.return_value = True
    root.memory_info.return_value = SimpleNamespace(rss=5 * 1024 * 1024)
    monkeypatch.setattr(shell_module.psutil, "Process", MagicMock(return_value=root))
    terminate = AsyncMock()
    monkeypatch.setattr(executor, "_terminate_process_tree", terminate)

    result = await executor.execute_argv_async(["python", "memory_hog.py"])

    assert result["success"] is False
    assert result["error_type"] == "resource_limit"
    assert result["resource_limit"] == "memory"
    assert "observed=5MB" in result["stderr"]
    terminate.assert_awaited_once_with(process)


@pytest.mark.asyncio
async def test_host_process_count_limit_includes_the_root_and_descendants(
    executor, monkeypatch
):
    _configure(
        monkeypatch,
        {"sandbox_mode": "host", "max_memory_mb": 0, "max_processes": 2},
    )
    process = _BlockingProcess()
    monkeypatch.setattr(
        asyncio, "create_subprocess_exec", AsyncMock(return_value=process)
    )

    def fake_process(pid):
        node = MagicMock()
        node.pid = pid
        node.is_running.return_value = True
        node.memory_info.return_value = SimpleNamespace(rss=1)
        if pid == process.pid:
            node.children.return_value = [fake_process(4101), fake_process(4102)]
        else:
            node.children.return_value = []
        return node

    monkeypatch.setattr(shell_module.psutil, "Process", fake_process)
    terminate = AsyncMock()
    monkeypatch.setattr(executor, "_terminate_process_tree", terminate)

    result = await executor.execute_argv_async(["python", "fork.py"])

    assert result["error_type"] == "resource_limit"
    assert result["resource_limit"] == "processes"
    assert "observed=3" in result["stderr"]
    terminate.assert_awaited_once_with(process)


@pytest.mark.asyncio
async def test_zero_resource_limits_disable_psutil_monitoring(
    executor, monkeypatch
):
    _configure(
        monkeypatch,
        {"sandbox_mode": "host", "max_memory_mb": 0, "max_processes": 0},
    )
    monkeypatch.setattr(
        asyncio,
        "create_subprocess_exec",
        AsyncMock(return_value=_CompletedProcess()),
    )
    inspect_process = MagicMock(side_effect=AssertionError("must stay disabled"))
    monkeypatch.setattr(shell_module.psutil, "Process", inspect_process)

    result = await executor.execute_argv_async(["python", "-V"])

    assert result["success"] is True
    inspect_process.assert_not_called()


@pytest.mark.asyncio
async def test_docker_timeout_stops_container_and_client_process(
    executor, tmp_path, monkeypatch
):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    _configure(
        monkeypatch,
        {
            "sandbox_mode": "docker",
            "workspace_root": str(workspace),
            "docker_image": "python:3.12-alpine",
        },
    )
    cidfile = tmp_path / "container.cid"
    cidfile.write_text("a" * 64, encoding="utf-8")
    monkeypatch.setattr(executor, "_new_docker_cidfile", lambda: cidfile)
    process = _BlockingProcess()
    monkeypatch.setattr(
        asyncio, "create_subprocess_exec", AsyncMock(return_value=process)
    )
    stop_container = AsyncMock()
    stop_client = AsyncMock()
    monkeypatch.setattr(executor, "_terminate_docker_container", stop_container)
    monkeypatch.setattr(executor, "_terminate_process_tree", stop_client)

    result = await executor.execute_async("sleep 10", timeout=0)

    assert result["error_type"] == "timeout"
    stop_container.assert_awaited_once_with(cidfile)
    stop_client.assert_awaited_once_with(process)
    assert not cidfile.exists()


# ---- Windows Job 出生即绑定（2026-10-07 验收缺陷修：venv launcher 冲突）-----

_CREATE_SUSPENDED = getattr(subprocess, "CREATE_SUSPENDED", 0x00000004)

_OS_SANDBOX_ON = {
    "enabled": True,
    "mode": "workspace",
    "network": "inherit",
    "on_missing_capability": "downgrade",
}


@pytest.mark.skipif(sys.platform != "win32", reason="Windows Job 出生即绑定专属")
@pytest.mark.asyncio
async def test_windows_job_spawn_is_created_suspended_then_bound(
    executor, tmp_path, monkeypatch
):
    """layer=unit 接线：Windows + Job 计划 → CREATE_SUSPENDED 创建 →
    指派 + 恢复主线程（替代后补整树枚举）。"""
    from RxyCode.RxyCode1_1_0.core.sandbox import manager as sandbox_manager

    executor.os_name = "win32"
    _configure(
        monkeypatch,
        {
            "sandbox_mode": "workspace",
            "workspace_root": str(tmp_path),
            "os_sandbox": _OS_SANDBOX_ON,
        },
    )
    bound: list[tuple[int, int]] = []
    monkeypatch.setattr(sandbox_manager, "open_sandbox_job", lambda wrapped: 4242)
    monkeypatch.setattr(
        sandbox_manager,
        "bind_spawned_process",
        lambda job, pid: bound.append((job, pid)),
    )
    process = _CompletedProcess()
    spawn = AsyncMock(return_value=process)
    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)

    result = await executor.execute_argv_async(["python", "-V"], workdir=str(tmp_path))

    assert result["success"] is True
    spawn.assert_awaited_once()
    flags = spawn.await_args.kwargs.get("creationflags", 0)
    assert flags & _CREATE_SUSPENDED
    assert flags & getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    assert bound == [(4242, process.pid)]


@pytest.mark.skipif(sys.platform != "win32", reason="Windows Job 出生即绑定专属")
@pytest.mark.asyncio
async def test_windows_job_bind_failure_is_fail_closed(
    executor, tmp_path, monkeypatch
):
    """layer=unit fail-closed：绑定失败 → sandbox_error + 进程被清理——
    不吞 GetLastError、不放行未约束进程。"""
    from RxyCode.RxyCode1_1_0.core.sandbox import manager as sandbox_manager
    from RxyCode.RxyCode1_1_0.core.sandbox.errors import SandboxUnavailableError

    executor.os_name = "win32"
    _configure(
        monkeypatch,
        {
            "sandbox_mode": "workspace",
            "workspace_root": str(tmp_path),
            "os_sandbox": _OS_SANDBOX_ON,
        },
    )
    monkeypatch.setattr(sandbox_manager, "open_sandbox_job", lambda wrapped: 4242)

    def _boom(job, pid):
        raise SandboxUnavailableError(
            "AssignProcessToJobObject 失败（GetLastError=5）"
        )

    monkeypatch.setattr(sandbox_manager, "bind_spawned_process", _boom)
    process = _CompletedProcess()
    monkeypatch.setattr(
        asyncio, "create_subprocess_exec", AsyncMock(return_value=process)
    )
    cleanup = AsyncMock()
    monkeypatch.setattr(executor, "_cleanup_process", cleanup)

    result = await executor.execute_argv_async(["python", "-V"], workdir=str(tmp_path))

    assert result["success"] is False
    assert result["error_type"] == "sandbox_error"
    assert "GetLastError=5" in result["stderr"]
    cleanup.assert_awaited_once()
