"""Small Windows ConPTY launcher and isolated runtime for clipboard E2E."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable

import psutil
import yaml
from winpty import PtyProcess

from .provider import SYNTHETIC_API_KEY, LocalOpenAIProvider


PROJECT_ROOT = Path(__file__).resolve().parents[3]
PYTHON_OVERRIDE_ENV = "RXYCODE_CLIPBOARD_E2E_PYTHON"
BUN_OVERRIDE_ENV = "RXYCODE_CLIPBOARD_E2E_BUN"
TTY_ENTRY = PROJECT_ROOT / "frontend" / "opentui-app" / "src" / "index.tsx"
ANSI_RE = re.compile(r"\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07]*(?:\x07|\x1b\\))")


def compact_terminal_text(value: str) -> str:
    """Remove ANSI controls and whitespace, preserving every other character."""
    return "".join(ANSI_RE.sub("", value).split())


def _resolve_executable(
    env_name: str,
    command: str | None = None,
    fallback: str | None = None,
    *,
    require_native_exe: bool = False,
) -> Path:
    override = os.environ.get(env_name, "").strip()
    if override:
        explicit_path = Path(override).expanduser()
        resolved = str(explicit_path) if explicit_path.is_file() else shutil.which(override)
    elif fallback:
        fallback_path = Path(fallback).expanduser()
        resolved = str(fallback_path) if fallback_path.is_file() else shutil.which(fallback)
    elif command:
        resolved = shutil.which(command)
    else:
        resolved = None
    if not resolved:
        label = command or fallback or env_name
        raise FileNotFoundError(
            f"required E2E executable {label!r} was not found; set {env_name} or add it to PATH"
        )
    path = Path(resolved).expanduser()
    if not path.is_file():
        label = command or fallback or env_name
        raise FileNotFoundError(
            f"required E2E executable {label!r} does not exist as a file: {path}; "
            f"clipboard suite stopped before broker snapshot"
        )
    if require_native_exe and path.suffix.casefold() != ".exe":
        raise FileNotFoundError(
            f"{env_name} must identify Bun's native .exe, not a shell wrapper: {path}; "
            f"clipboard suite stopped before broker snapshot"
        )
    return path.resolve()


def preflight_runtime_dependencies() -> tuple[Path, Path]:
    """Resolve and validate Bun/Python before any clipboard broker is created."""
    if not PROJECT_ROOT.is_dir():
        raise FileNotFoundError(f"E2E checkout root is missing: {PROJECT_ROOT}")
    if not TTY_ENTRY.is_file():
        raise FileNotFoundError(f"OpenTUI entrypoint is missing: {TTY_ENTRY}")
    # `which bun` may resolve a PowerShell/cmd shim (e.g. bun.ps1). ConPTY
    # needs the native executable; the explicit test-only override is the
    # reliable path when the package manager exposes only a wrapper.
    bun = _resolve_executable(BUN_OVERRIDE_ENV, command="bun", require_native_exe=True)
    python = _resolve_executable(PYTHON_OVERRIDE_ENV, fallback=sys.executable)
    return bun, python


def _safe_environment(
    provider: LocalOpenAIProvider, run_dir: Path, *, python: Path
) -> dict[str, str]:
    """Inherit Windows launch essentials, but no real credentials/proxies/config."""
    blocked_fragments = (
        "API_KEY", "TOKEN", "SECRET", "PASSWORD", "PASSWD", "PROXY",
        "CREDENTIAL", "AUTHORIZATION", "COOKIE", "RXYCODE_",
    )
    env = {
        key: value
        for key, value in os.environ.items()
        if not any(fragment in key.upper() for fragment in blocked_fragments)
    }
    home = run_dir / "home"
    skills = run_dir / "skills"
    appdata = run_dir / "appdata"
    localappdata = run_dir / "localappdata"
    for path in (home, skills, appdata, localappdata):
        path.mkdir(parents=True, exist_ok=True)

    env.update(
        {
            "HOME": str(home),
            "USERPROFILE": str(home),
            "APPDATA": str(appdata),
            "LOCALAPPDATA": str(localappdata),
            "RXYCODE_PROJECT_ROOT": str(PROJECT_ROOT),
            "RXYCODE_WORKSPACE_ROOT": str(run_dir / "workspace"),
            "RXYCODE_DATA_DIR": str(run_dir / "data"),
            "RXYCODE_V2_CONFIG_DIR": str(run_dir / "data"),
            "RXYCODE_APPSERVER_PYTHON": str(python),
            "RXYCODE_APPSERVER_LOG": str(run_dir / "appserver-stderr.log"),
            "RXYCODE_TRANSPORT": "stdio",
            "RXYCODE_CLIPBOARD_E2E_API_KEY": SYNTHETIC_API_KEY,
            "RXYCODE_SKILLS_DIR": str(skills),
            "RXYCODE_SKILLS_DIRS": str(skills),
            "RXYCODE_SUBAGENTS": "0",
            "RXYCODE_SUBAGENTS_TASK": "0",
            "RXYCODE_SUBAGENTS_MENTION": "0",
            "RXYCODE_STREAM_COALESCE": "1",
            "PYTHONPATH": str(PROJECT_ROOT),
            "PYTHONUTF8": "1",
            "PYTHONIOENCODING": "utf-8",
            "PYWINPTY_BACKEND": "0",  # pywinpty's ConPTY backend (WinPTY is 1).
            "SSL_CERT_FILE": str(provider.ca_path),
            "REQUESTS_CA_BUNDLE": str(provider.ca_path),
            "CURL_CA_BUNDLE": str(provider.ca_path),
            "NO_PROXY": "127.0.0.1,localhost",
            "no_proxy": "127.0.0.1,localhost",
            "TERM": "xterm-256color",
        }
    )
    for key in (
        "RXYCODE_APPSERVER_STUB", "RXYCODE_E2E_BYPASS_TTY", "RXYCODE_SCRIPTED_AGENT_REPLIES",
        "RXYCODE_SCRIPTED_AGENT_CAPTURE", "RXYCODE_AGENT_TEST_HOOK", "RXYCODE_LIVE_API_KEY",
    ):
        env.pop(key, None)
    (run_dir / "workspace").mkdir(parents=True, exist_ok=True)
    (run_dir / "data").mkdir(parents=True, exist_ok=True)
    return env


def _write_config(env: dict[str, str], provider: LocalOpenAIProvider) -> Path:
    config_path = Path(env["RXYCODE_DATA_DIR"]) / "config.yaml"
    config = {
        "active_model": "clipboard-e2e-vision",
        "models": {
            "clipboard-e2e-vision": {
                "provider_id": "openai_compatible",
                "provider_name": "OpenAI-compatible local control provider",
                "model_name": "gpt-5.6-luna",
                "base_url": provider.base_url,
                "api_transport": "openai_chat",
                "api_key_env": "RXYCODE_CLIPBOARD_E2E_API_KEY",
                "temperature": 0,
                "max_tokens": 256,
            }
        },
        "agents": {"enabled": False, "route_mode": "auto", "multi_model": {"enabled": False}},
        "cache": {"enabled": False, "prompt_prefix_cache": False},
        "safety": {"auto_approve": ["read"]},
        "mcpServers": {},
    }
    config_path.write_text(yaml.safe_dump(config, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return config_path


def verify_checkout_binding(env: dict[str, str], *, python: Path) -> dict[str, Any]:
    script = r'''
import importlib, json, os
from pathlib import Path
root = Path(os.environ["RXYCODE_PROJECT_ROOT"]).resolve()
appserver = importlib.import_module("appserver")
bare = importlib.import_module("core.agent_v2")
canonical = importlib.import_module("RxyCode.RxyCode1_1_0.core.agent_v2")
paths = {
  "appserver": str(Path(appserver.__file__).resolve()),
  "agent_v2_bare": str(Path(bare.__file__).resolve()),
  "agent_v2_canonical": str(Path(canonical.__file__).resolve()),
}
for name, value in paths.items():
  if not Path(value).is_relative_to(root):
    raise SystemExit(f"{name} resolved outside requested checkout: {value}")
if bare is not canonical:
  raise SystemExit("bare and canonical AgentV2 imports are different module objects")
print(json.dumps({"project_root": str(root), "module_paths": paths, "canonical_identity": True}))
'''
    completed = subprocess.run(
        [str(python), "-c", script],
        cwd=PROJECT_ROOT,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=25,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            "test child did not bind to this worktree: "
            + (completed.stderr[-4000:] or completed.stdout[-4000:])
        )
    return json.loads(completed.stdout.strip().splitlines()[-1])


class ConPTYApp:
    """Capture actual OpenTUI output without replacing its App or transport."""

    def __init__(self, run_dir: Path, env: dict[str, str], *, bun: Path) -> None:
        if not bun.is_file() or not TTY_ENTRY.is_file():
            raise FileNotFoundError("Bun or the OpenTUI entrypoint is missing")
        self.run_dir = run_dir
        self.pty = PtyProcess.spawn(
            [str(bun), str(TTY_ENTRY)],
            cwd=str(TTY_ENTRY.parent.parent),
            env=env,
            dimensions=(44, 132),
        )
        self.pid = int(self.pty.pid)
        self._condition = threading.Condition()
        self._write_lock = threading.Lock()
        self._chunks: list[dict[str, Any]] = []
        self._reader_error: str | None = None
        self._reader = threading.Thread(target=self._read_output, name="clipboard-e2e-conpty-reader", daemon=True)
        self._reader.start()

    def _read_output(self) -> None:
        while True:
            try:
                chunk = self.pty.read(8192)
            except (EOFError, OSError) as exc:
                with self._condition:
                    if not isinstance(exc, EOFError):
                        self._reader_error = type(exc).__name__
                    self._condition.notify_all()
                return
            with self._condition:
                self._chunks.append({"monotonic": time.monotonic(), "text": chunk})
                self._condition.notify_all()

    def write(self, text: str) -> None:
        with self._write_lock:
            self.pty.write(text)

    def wait_for(
        self,
        needle: str,
        timeout: float,
        *,
        after_chunks: int = 0,
        normalize: Callable[[str], str] | None = None,
    ) -> tuple[float, str]:
        """Wait for a needle; normalize affects matching, not returned evidence."""
        deadline = time.monotonic() + timeout
        with self._condition:
            while True:
                chunks = self._chunks[after_chunks:]
                value = "".join(item["text"] for item in chunks)
                observed = normalize(value) if normalize is not None else ANSI_RE.sub("", value)
                if needle in observed:
                    return time.monotonic(), value
                if not self.pty.isalive():
                    raise RuntimeError(f"OpenTUI exited while waiting for {needle!r}; output tail={value[-2000:]!r}")
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError(f"OpenTUI did not show {needle!r}; output tail={value[-2000:]!r}")
                self._condition.wait(min(remaining, 0.15))

    def chunk_count(self) -> int:
        with self._condition:
            return len(self._chunks)

    def text_since(self, chunk_index: int = 0) -> str:
        with self._condition:
            return ANSI_RE.sub("", "".join(item["text"] for item in self._chunks[chunk_index:]))

    def process_snapshot(self) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        try:
            root = psutil.Process(self.pid)
            processes = [root, *root.children(recursive=True)]
        except psutil.Error:
            processes = []
        for process in processes:
            try:
                result.append(
                    {
                        "pid": process.pid,
                        "create_time": process.create_time(),
                        "name": process.name(),
                        "parent_pid": process.ppid(),
                    }
                )
            except psutil.Error:
                continue
        return result

    def save_terminal(self) -> tuple[Path, Path]:
        self.run_dir.mkdir(parents=True, exist_ok=True)
        with self._condition:
            chunks = list(self._chunks)
        raw = self.run_dir / "terminal-ansi.txt"
        frames = self.run_dir / "terminal-text-chunks.jsonl"
        raw.write_text("".join(item["text"] for item in chunks), encoding="utf-8")
        frames.write_text(
            "".join(
                json.dumps(
                    {"monotonic": row["monotonic"], "text": ANSI_RE.sub("", row["text"])},
                    ensure_ascii=False,
                )
                + "\n"
                for row in chunks
            ),
            encoding="utf-8",
        )
        return raw, frames

    def close(self, grace: float = 8) -> dict[str, Any]:
        processes = self.process_snapshot()
        if self.pty.isalive():
            try:
                self.write("\x03\x03")
            except (EOFError, OSError):
                pass
            deadline = time.monotonic() + grace
            while self.pty.isalive() and time.monotonic() < deadline:
                time.sleep(0.1)
        if self.pty.isalive():
            self.pty.terminate(force=True)
            deadline = time.monotonic() + 2
            while self.pty.isalive() and time.monotonic() < deadline:
                time.sleep(0.05)

        # Only terminate exact descendants captured from this ConPTY, and only
        # if the PID still has its original creation timestamp.
        cleanup: list[dict[str, Any]] = []
        for row in reversed(processes):
            try:
                process = psutil.Process(int(row["pid"]))
                same_process = abs(process.create_time() - float(row["create_time"])) < 0.01
                if same_process and process.is_running():
                    process.terminate()
                    try:
                        process.wait(timeout=1.5)
                    except psutil.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=1.5)
                gone = not (same_process and process.is_running())
                cleanup.append({"pid": row["pid"], "identity_matched": same_process, "exited": gone})
            except psutil.NoSuchProcess:
                cleanup.append({"pid": row["pid"], "identity_matched": True, "exited": True})
            except psutil.Error as exc:
                cleanup.append({"pid": row["pid"], "identity_matched": False, "exited": False, "error_type": type(exc).__name__})
        self.pty.close(force=True)
        self._reader.join(timeout=2)
        self.save_terminal()
        return {
            "pty_pid": self.pid,
            "processes": processes,
            "cleanup": cleanup,
            "pty_exit_status": self.pty.exitstatus,
            "reader_stopped": not self._reader.is_alive(),
        }


def create_run(run_parent: Path) -> tuple[Path, dict[str, Any]]:
    """Create a unique evidence/runtime folder without removing prior artifacts."""
    run_parent.mkdir(parents=True, exist_ok=True)
    run_dir = run_parent / time.strftime("clipboard-e2e-%Y%m%d-%H%M%S")
    suffix = 0
    while run_dir.exists():
        suffix += 1
        run_dir = run_parent / f"clipboard-e2e-{time.strftime('%Y%m%d-%H%M%S')}-{suffix}"
    run_dir.mkdir()
    return run_dir, {"created_monotonic": time.monotonic(), "run_dir": str(run_dir)}


def summarize_task_store(data_dir: Path, output_path: Path) -> dict[str, Any]:
    source = data_dir / "desktop" / "tasks.json"
    if not source.is_file():
        result = {"available": False, "reason": "task store file not created"}
        output_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        return result
    try:
        data = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        result = {"available": False, "reason": type(exc).__name__}
        output_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        return result
    tasks = []
    for task in (data.get("tasks") or {}).values():
        if not isinstance(task, dict):
            continue
        tasks.append(
            {
                key: task.get(key)
                for key in (
                    "session_id", "workspace_root", "model_id", "provider_id", "status",
                    "created_at", "updated_at", "usage",
                )
            }
        )
    event_groups = data.get("events") if isinstance(data.get("events"), dict) else {}
    events = []
    for session_id, rows in event_groups.items():
        for event in rows if isinstance(rows, list) else []:
            if not isinstance(event, dict):
                continue
            params = event.get("params") if isinstance(event.get("params"), dict) else {}
            events.append(
                {
                    "session_id": session_id,
                    "method": event.get("method"),
                    "tool_name": params.get("tool_name"),
                    "ok": params.get("ok"),
                    "seq": event.get("seq"),
                }
            )
    result = {"available": True, "tasks": tasks, "events": events, "usage_is_synthetic": True}
    output_path.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return result
