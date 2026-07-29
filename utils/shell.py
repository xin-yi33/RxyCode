"""Cross-platform command execution with enforceable sandbox policies."""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
from dataclasses import dataclass
import locale
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import tempfile
from typing import Any

import psutil

from ..config.settings import load_config
from ..core.session_runtime import (
    current_working_directory,
    initial_working_directory,
)


_MONITOR_INTERVAL_SECONDS = 0.05
_DOCKER_CID_PATTERN = re.compile(r"^[a-fA-F0-9]{12,64}$")


@dataclass(frozen=True)
class _ExecutionPolicy:
    mode: str
    cwd: Path | None
    workspace_root: Path | None
    docker_image: str
    docker_network: str
    max_memory_mb: int
    max_cpus: float
    max_processes: int


@dataclass(frozen=True)
class _ResourceViolation:
    resource: str
    observed: int
    limit: int
    unit: str = ""

    def message(self) -> str:
        suffix = self.unit
        return (
            f"[resource_limit] {self.resource} limit exceeded: "
            f"observed={self.observed}{suffix}, limit={self.limit}{suffix}"
        )


def _failure(
    message: str,
    *,
    error_type: str,
    resource_limit: str | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "stdout": "",
        "stderr": message,
        "exit_code": -1,
        "success": False,
        "error_type": error_type,
    }
    if resource_limit is not None:
        result["resource_limit"] = resource_limit
    return result


def _as_mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _first_config_value(
    execution: dict[str, Any],
    sandbox: dict[str, Any],
    docker: dict[str, Any],
    limits: dict[str, Any],
    key: str,
    default: Any,
) -> Any:
    """Read flat execution keys first while supporting grouped config."""
    if key in execution:
        return execution[key]
    if key in limits:
        return limits[key]
    if key in docker:
        return docker[key]
    if key in sandbox:
        return sandbox[key]
    return default


def _non_negative_int(value: Any, key: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"execution.{key} must be a non-negative integer")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"execution.{key} must be a non-negative integer"
        ) from exc
    if parsed < 0:
        raise ValueError(f"execution.{key} must be a non-negative integer")
    return parsed


def _non_negative_float(value: Any, key: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"execution.{key} must be a non-negative number")
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"execution.{key} must be a non-negative number"
        ) from exc
    if parsed < 0:
        raise ValueError(f"execution.{key} must be a non-negative number")
    return parsed


def _resolve_path(value: str | os.PathLike[str], *, base: Path) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = base / path
    return path.resolve()


def _is_within(candidate: Path, root: Path) -> bool:
    try:
        candidate.relative_to(root)
    except (ValueError, OSError):
        return False
    return True


class ShellExecutor:
    def __init__(self):
        self.os_name = sys.platform
        self.shell_type = self._detect_shell()
        self.user_home = str(Path.home())
        self.desktop_path = self._detect_desktop()

    def _detect_shell(self) -> str:
        if self.os_name == "win32":
            return "powershell" if self._has_powershell() else "cmd"
        return "bash"

    def _has_powershell(self) -> bool:
        try:
            result = subprocess.run(
                ["powershell", "-NoProfile", "-Command", "echo ok"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            return result.returncode == 0
        except Exception:
            return False

    def _detect_desktop(self) -> str:
        if self.os_name == "win32":
            try:
                result = subprocess.run(
                    [
                        "powershell",
                        "-NoProfile",
                        "-Command",
                        "[Environment]::GetFolderPath('Desktop')",
                    ],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                if result.returncode == 0 and result.stdout.strip():
                    return result.stdout.strip()
            except Exception:
                pass
        return str(Path.home() / "Desktop")

    def _is_powershell_syntax(self, command: str) -> bool:
        patterns = [
            r"\$\w+\s*=",
            r"\$env:",
            r"\(Join-Path",
            r"Write-Host",
            r"Test-Path",
            r"Get-ChildItem",
            r"Set-Location",
            r"\[Environment\]::",
            r"powershell",
        ]
        return any(re.search(pattern, command) for pattern in patterns)

    def translate_command(self, command: str) -> tuple[str, str]:
        needs_powershell = self._is_powershell_syntax(command)
        actual_shell = self.shell_type
        if needs_powershell and self.shell_type == "cmd":
            actual_shell = "powershell"

        if actual_shell == "cmd":
            command = command.replace("$env:USERPROFILE", "%USERPROFILE%")
            command = command.replace("$env:APPDATA", "%APPDATA%")
            command = command.replace("$env:LOCALAPPDATA", "%LOCALAPPDATA%")
            command = command.replace("$env:TEMP", "%TEMP%")
            command = command.replace("powershell -Command ", "")
            command = command.replace("powershell -c ", "")
        elif actual_shell == "powershell":
            # Windows PowerShell 5.x rejects bash/cmd `&&`; PS 7+ accepts it.
            # Prefer `;` so agent-written cmd-style chains run on WinPS 5.
            if "&&" in command:
                command = re.sub(r"\s*&&\s*", "; ", command)
            # cmd.exe `cd /d X` → PowerShell Set-Location
            command = re.sub(
                r"\bcd\s+/d\s+",
                "Set-Location ",
                command,
                flags=re.IGNORECASE,
            )
            # `start cmd /k ...` is cmd.exe syntax; Start-Process is the PS form.
            # Common agent mistake: `start cmd /k python foo.py`
            start_cmd = re.match(
                r"^\s*start\s+cmd\s+/k\s+(.+)$",
                command,
                flags=re.IGNORECASE,
            )
            if start_cmd:
                inner = start_cmd.group(1).strip().replace("'", "''")
                command = (
                    "Start-Process -FilePath cmd.exe "
                    f"-ArgumentList '/k','{inner}'"
                )
        return command, actual_shell

    def _build_command(self, command: str) -> list[str]:
        translated, actual_shell = self.translate_command(command)
        if actual_shell == "powershell":
            return ["powershell", "-NoProfile", "-Command", translated]
        if actual_shell == "cmd":
            return ["cmd", "/c", translated]
        return ["bash", "-c", translated]

    def _execution_policy(self, workdir: str) -> _ExecutionPolicy:
        config = load_config()
        execution = _as_mapping(config.get("execution"))
        sandbox = _as_mapping(execution.get("sandbox"))
        docker = _as_mapping(execution.get("docker"))
        limits = _as_mapping(execution.get("resource_limits"))

        mode_value = execution.get("sandbox_mode", sandbox.get("mode", "workspace"))
        mode = str(mode_value or "workspace").strip().lower()
        if mode not in {"host", "workspace", "docker"}:
            raise ValueError(
                "execution.sandbox_mode must be one of: host, workspace, docker"
            )

        launch_dir = initial_working_directory()
        current_dir = current_working_directory(launch_dir)
        root_value = execution.get(
            "workspace_root", sandbox.get("workspace_root", launch_dir)
        )
        workspace_root = _resolve_path(root_value or launch_dir, base=launch_dir)
        if mode in {"workspace", "docker"}:
            if not workspace_root.exists() or not workspace_root.is_dir():
                raise ValueError(
                    f"execution.workspace_root is not a directory: {workspace_root}"
                )
            session_base = (
                current_dir
                if _is_within(current_dir, workspace_root)
                else workspace_root
            )
            candidate = (
                _resolve_path(workdir, base=session_base)
                if workdir
                else session_base
            )
            if not _is_within(candidate, workspace_root):
                raise ValueError(
                    "sandbox workdir escapes execution.workspace_root: "
                    f"{candidate} is outside {workspace_root}"
                )
            if not candidate.exists() or not candidate.is_dir():
                raise ValueError(f"sandbox workdir is not a directory: {candidate}")
            cwd: Path | None = candidate
        else:
            cwd = _resolve_path(workdir, base=current_dir) if workdir else None
            if not workdir:
                cwd = current_dir

        image_value = _first_config_value(
            execution, sandbox, docker, limits, "docker_image", ""
        )
        if not image_value and "image" in docker:
            image_value = docker["image"]
        docker_image = str(image_value or "").strip()
        if mode == "docker" and not docker_image:
            raise ValueError(
                "execution.docker_image is required when sandbox_mode=docker"
            )
        if mode == "docker" and (
            docker_image.startswith("-")
            or any(character.isspace() for character in docker_image)
            or "\x00" in docker_image
        ):
            raise ValueError("execution.docker_image is not a valid image reference")

        network_value = _first_config_value(
            execution, sandbox, docker, limits, "docker_network", "none"
        )
        if "network" in docker and "docker_network" not in execution:
            network_value = docker["network"]
        docker_network = str(network_value or "none").strip() or "none"

        max_memory_mb = _non_negative_int(
            _first_config_value(
                execution, sandbox, docker, limits, "max_memory_mb", 4096
            ),
            "max_memory_mb",
        )
        max_cpus = _non_negative_float(
            _first_config_value(
                execution, sandbox, docker, limits, "max_cpus", 2.0
            ),
            "max_cpus",
        )
        max_processes = _non_negative_int(
            _first_config_value(
                execution, sandbox, docker, limits, "max_processes", 128
            ),
            "max_processes",
        )
        return _ExecutionPolicy(
            mode=mode,
            cwd=cwd,
            workspace_root=(
                workspace_root if mode in {"workspace", "docker"} else None
            ),
            docker_image=docker_image,
            docker_network=docker_network,
            max_memory_mb=max_memory_mb,
            max_cpus=max_cpus,
            max_processes=max_processes,
        )

    @staticmethod
    def _container_workdir(policy: _ExecutionPolicy) -> str:
        assert policy.workspace_root is not None
        assert policy.cwd is not None
        relative = policy.cwd.relative_to(policy.workspace_root)
        if relative == Path("."):
            return "/workspace"
        return "/workspace/" + relative.as_posix()

    @staticmethod
    def _new_docker_cidfile() -> Path:
        descriptor, name = tempfile.mkstemp(prefix="rxycode-docker-", suffix=".cid")
        os.close(descriptor)
        path = Path(name)
        path.unlink(missing_ok=True)
        return path

    def _docker_argv(
        self,
        policy: _ExecutionPolicy,
        argv: list[str],
        *,
        shell_command: str | None,
        cidfile: Path,
    ) -> list[str]:
        assert policy.workspace_root is not None
        docker_argv = [
            "docker",
            "run",
            "--rm",
            "--cidfile",
            str(cidfile),
            "--network",
            policy.docker_network,
            "--mount",
            (
                "type=bind,source="
                f"{policy.workspace_root},target=/workspace"
            ),
            "--workdir",
            self._container_workdir(policy),
        ]
        if policy.max_memory_mb > 0:
            docker_argv.extend(["--memory", f"{policy.max_memory_mb}m"])
        if policy.max_cpus > 0:
            docker_argv.extend(["--cpus", f"{policy.max_cpus:g}"])
        if policy.max_processes > 0:
            docker_argv.extend(["--pids-limit", str(policy.max_processes)])
        docker_argv.append(policy.docker_image)
        if shell_command is None:
            docker_argv.extend(argv)
        else:
            docker_argv.extend(["/bin/sh", "-lc", shell_command])
        return docker_argv

    @staticmethod
    def _process_kwargs(cwd: Path | None, os_name: str) -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            "stdout": asyncio.subprocess.PIPE,
            "stderr": asyncio.subprocess.PIPE,
            "cwd": str(cwd) if cwd is not None else None,
        }
        if os_name == "win32":
            kwargs["creationflags"] = getattr(
                subprocess, "CREATE_NEW_PROCESS_GROUP", 0
            )
        else:
            kwargs["start_new_session"] = True
        return kwargs

    def execute(self, command: str, workdir: str = "", timeout: int = 60) -> dict:
        """Run the same controlled async implementation from synchronous callers."""

        def run() -> dict:
            return asyncio.run(self.execute_async(command, workdir, timeout))

        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return run()

        # A synchronous tool can be invoked from an application-owned event loop.
        # Run its private loop on another thread instead of nesting asyncio.run().
        context = copy_context()
        with ThreadPoolExecutor(max_workers=1) as executor:
            return executor.submit(context.run, run).result()

    async def execute_async(
        self,
        command: str,
        workdir: str = "",
        timeout: int = 60,
    ) -> dict:
        return await self._execute_controlled(
            self._build_command(command),
            workdir=workdir,
            timeout=timeout,
            shell_command=command,
        )

    async def execute_argv_async(
        self,
        argv: list[str],
        workdir: str = "",
        timeout: int = 60,
    ) -> dict:
        """Run an argv command without ever enabling subprocess shell mode."""
        if not isinstance(argv, list) or not argv or not all(
            isinstance(item, str) and item for item in argv
        ):
            return _failure(
                "[sandbox_error] argv must be a non-empty list of strings",
                error_type="sandbox_error",
            )
        return await self._execute_controlled(
            list(argv),
            workdir=workdir,
            timeout=timeout,
            shell_command=None,
        )

    async def _execute_controlled(
        self,
        argv: list[str],
        *,
        workdir: str,
        timeout: int,
        shell_command: str | None,
    ) -> dict[str, Any]:
        try:
            policy = self._execution_policy(workdir)
        except Exception as exc:
            return _failure(
                f"[sandbox_error] {exc}", error_type="sandbox_error"
            )

        cidfile: Path | None = None
        spawn_argv = argv
        spawn_cwd = policy.cwd
        if policy.mode == "docker":
            cidfile = self._new_docker_cidfile()
            spawn_argv = self._docker_argv(
                policy,
                argv,
                shell_command=shell_command,
                cidfile=cidfile,
            )
            spawn_cwd = None

        process: asyncio.subprocess.Process | None = None
        communicate_task: asyncio.Task | None = None
        monitor_task: asyncio.Task | None = None
        try:
            process = await asyncio.create_subprocess_exec(
                *spawn_argv,
                **self._process_kwargs(spawn_cwd, self.os_name),
            )
            communicate_task = asyncio.create_task(process.communicate())
            if policy.mode in {"host", "workspace"} and (
                policy.max_memory_mb > 0 or policy.max_processes > 0
            ):
                monitor_task = asyncio.create_task(
                    self._monitor_process_tree(process, policy)
                )

            waiters = {communicate_task}
            if monitor_task is not None:
                waiters.add(monitor_task)
            done, _ = await asyncio.wait(
                waiters,
                timeout=max(0, timeout),
                return_when=asyncio.FIRST_COMPLETED,
            )
            if not done:
                await self._cleanup_process(process, cidfile)
                await self._cancel_task(communicate_task)
                return _failure(
                    f"[timeout after {timeout}s]", error_type="timeout"
                )

            if monitor_task is not None and monitor_task in done:
                violation = monitor_task.result()
                if violation is not None:
                    await self._cleanup_process(process, cidfile)
                    await self._cancel_task(communicate_task)
                    return _failure(
                        violation.message(),
                        error_type="resource_limit",
                        resource_limit=violation.resource,
                    )

            stdout, stderr = await communicate_task
            encoding = locale.getpreferredencoding(False) or "utf-8"
            stdout_text = stdout.decode(encoding, errors="replace") if stdout else ""
            stderr_text = stderr.decode(encoding, errors="replace") if stderr else ""
            result: dict[str, Any] = {
                "stdout": stdout_text,
                "stderr": stderr_text,
                "exit_code": process.returncode,
                "success": process.returncode == 0,
            }
            if policy.mode == "docker" and process.returncode != 0:
                detail = stderr_text.strip() or "docker run returned a non-zero exit code"
                result["stderr"] = f"[docker_sandbox] {detail}"
                result["error_type"] = "docker_sandbox"
            return result
        except asyncio.CancelledError:
            if process is not None:
                await self._cleanup_process(process, cidfile)
            await self._cancel_task(communicate_task)
            raise
        except FileNotFoundError as exc:
            if process is not None:
                await self._cleanup_process(process, cidfile)
            if policy.mode == "docker":
                return _failure(
                    "[docker_sandbox] Docker runtime is unavailable; "
                    "host execution was not attempted",
                    error_type="docker_sandbox",
                )
            return _failure(f"[spawn_error] {exc}", error_type="spawn_error")
        except Exception as exc:
            if process is not None:
                await self._cleanup_process(process, cidfile)
            if policy.mode == "docker":
                return _failure(
                    f"[docker_sandbox] Docker sandbox failed: {exc}; "
                    "host execution was not attempted",
                    error_type="docker_sandbox",
                )
            return _failure(str(exc), error_type="execution_error")
        finally:
            await self._cancel_task(monitor_task)
            if cidfile is not None:
                cidfile.unlink(missing_ok=True)

    async def _monitor_process_tree(
        self,
        process: asyncio.subprocess.Process,
        policy: _ExecutionPolicy,
    ) -> _ResourceViolation | None:
        memory_limit_bytes = policy.max_memory_mb * 1024 * 1024
        while process.returncode is None:
            try:
                root = psutil.Process(process.pid)
                candidates = [root, *root.children(recursive=True)]
                by_pid = {candidate.pid: candidate for candidate in candidates}
                live_processes = []
                total_rss = 0
                for candidate in by_pid.values():
                    try:
                        if not candidate.is_running():
                            continue
                        live_processes.append(candidate)
                        total_rss += candidate.memory_info().rss
                    except (psutil.NoSuchProcess, psutil.ZombieProcess):
                        continue
                    except psutil.AccessDenied:
                        return _ResourceViolation(
                            "process_monitor", observed=1, limit=0
                        )
            except (psutil.NoSuchProcess, psutil.ZombieProcess):
                await asyncio.sleep(_MONITOR_INTERVAL_SECONDS)
                continue
            except psutil.AccessDenied:
                return _ResourceViolation("process_monitor", observed=1, limit=0)

            if memory_limit_bytes > 0 and total_rss > memory_limit_bytes:
                observed_mb = (total_rss + 1024 * 1024 - 1) // (1024 * 1024)
                return _ResourceViolation(
                    "memory", observed=observed_mb, limit=policy.max_memory_mb, unit="MB"
                )
            if (
                policy.max_processes > 0
                and len(live_processes) > policy.max_processes
            ):
                return _ResourceViolation(
                    "processes",
                    observed=len(live_processes),
                    limit=policy.max_processes,
                )
            await asyncio.sleep(_MONITOR_INTERVAL_SECONDS)
        return None

    @staticmethod
    async def _cancel_task(task: asyncio.Task | None) -> None:
        if task is None or task.done():
            return
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    async def _cleanup_process(
        self,
        process: asyncio.subprocess.Process,
        cidfile: Path | None,
    ) -> None:
        if cidfile is not None:
            await self._terminate_docker_container(cidfile)
        await self._terminate_process_tree(process)

    async def _terminate_docker_container(self, cidfile: Path) -> None:
        try:
            container_id = cidfile.read_text(encoding="utf-8").strip()
        except (FileNotFoundError, OSError):
            return
        if not _DOCKER_CID_PATTERN.fullmatch(container_id):
            return
        try:
            kwargs: dict[str, Any] = {
                "stdout": asyncio.subprocess.DEVNULL,
                "stderr": asyncio.subprocess.DEVNULL,
            }
            if self.os_name == "win32":
                kwargs["creationflags"] = getattr(
                    subprocess, "CREATE_NO_WINDOW", 0
                )
            killer = await asyncio.create_subprocess_exec(
                "docker", "rm", "--force", container_id, **kwargs
            )
            await asyncio.wait_for(killer.wait(), timeout=5)
        except Exception:
            # The docker run client may already have removed the container.
            pass

    async def _terminate_process_tree(
        self, process: asyncio.subprocess.Process
    ) -> None:
        """Best-effort, bounded cleanup for a command and all descendants."""
        if process.returncode is not None:
            return

        if self.os_name == "win32":
            try:
                flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
                killer = await asyncio.create_subprocess_exec(
                    "taskkill",
                    "/PID",
                    str(process.pid),
                    "/T",
                    "/F",
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL,
                    creationflags=flags,
                )
                await asyncio.wait_for(killer.wait(), timeout=5)
            except Exception:
                if process.returncode is None:
                    process.kill()
        else:
            try:
                os.killpg(os.getpgid(process.pid), signal.SIGTERM)
            except (ProcessLookupError, PermissionError, OSError):
                if process.returncode is None:
                    process.terminate()

        try:
            await asyncio.wait_for(process.wait(), timeout=3)
        except asyncio.TimeoutError:
            if self.os_name != "win32":
                try:
                    os.killpg(os.getpgid(process.pid), signal.SIGKILL)
                except (ProcessLookupError, PermissionError, OSError):
                    pass
            if process.returncode is None:
                process.kill()
            await process.wait()


shell_executor = ShellExecutor()
