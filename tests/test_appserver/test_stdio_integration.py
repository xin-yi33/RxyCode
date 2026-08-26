"""Subprocess integration tests for appserver stdio JSON-RPC."""

from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from appserver.live_env import build_live_appserver_env

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _appserver_env() -> dict[str, str]:
    env = os.environ.copy()
    env["RXYCODE_APPSERVER_STUB"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONPATH"] = str(PROJECT_ROOT)
    return env


def _live_appserver_env() -> dict[str, str]:
    """Use real user config; pytest conftest isolates RXYCODE_DATA_DIR."""
    return build_live_appserver_env(project_root=PROJECT_ROOT)


def _appserver_proc_with_env(env: dict[str, str]) -> subprocess.Popen[str]:
    return subprocess.Popen(
        [sys.executable, "-m", "appserver"],
        cwd=PROJECT_ROOT,
        env=env,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        bufsize=1,
    )


class AppserverClient:
    def __init__(self, proc: subprocess.Popen[str]) -> None:
        self.proc = proc
        self._next_id = 1
        self._send_lock = threading.Lock()
        self._pending: dict[int, queue.Queue[dict]] = {}
        self._pending_lock = threading.Lock()
        self._notifications: queue.Queue[dict] = queue.Queue()
        self.raw_lines: list[str] = []
        self._stop = threading.Event()
        self._reader = threading.Thread(target=self._read_loop, daemon=True)
        self._reader.start()

    def _read_loop(self) -> None:
        assert self.proc.stdout is not None
        while not self._stop.is_set():
            line = self.proc.stdout.readline()
            if not line:
                break
            self.raw_lines.append(line.rstrip("\n"))
            message = json.loads(line)
            request_id = message.get("id")
            routed = False
            if isinstance(request_id, int):
                with self._pending_lock:
                    pending = self._pending.get(request_id)
                if pending is not None:
                    pending.put(message)
                    routed = True
            if not routed and (
                "method" in message or "result" in message or "error" in message
            ):
                self._notifications.put(message)

    def close(self) -> None:
        self._stop.set()

    def send(self, method: str, params: dict | None = None) -> int:
        with self._send_lock:
            request_id = self._next_id
            self._next_id += 1
        message = {"jsonrpc": "2.0", "id": request_id, "method": method}
        if params is not None:
            message["params"] = params
        assert self.proc.stdin is not None
        self.proc.stdin.write(json.dumps(message) + "\n")
        self.proc.stdin.flush()
        return request_id

    def respond(self, request_id: int, result: dict) -> None:
        assert self.proc.stdin is not None
        self.proc.stdin.write(
            json.dumps({"jsonrpc": "2.0", "id": request_id, "result": result})
            + "\n"
        )
        self.proc.stdin.flush()

    def readline(self, timeout: float = 10.0) -> dict | None:
        try:
            return self._notifications.get(timeout=timeout)
        except queue.Empty:
            if self.proc.poll() is not None:
                return None
            return None

    def request(self, method: str, params: dict | None = None, timeout: float = 10.0) -> dict:
        request_id = self.send(method, params)
        response_queue: queue.Queue[dict] = queue.Queue()
        with self._pending_lock:
            self._pending[request_id] = response_queue
        try:
            message = response_queue.get(timeout=timeout)
        except queue.Empty as exc:
            raise TimeoutError(f"no response for {method}") from exc
        finally:
            with self._pending_lock:
                self._pending.pop(request_id, None)
        if "error" in message:
            raise AssertionError(message["error"])
        return message.get("result") or {}


@pytest.fixture
def appserver_proc():
    proc = subprocess.Popen(
        [sys.executable, "-m", "appserver"],
        cwd=PROJECT_ROOT,
        env=_appserver_env(),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        bufsize=1,
    )
    import threading as _t

    def _drain():
        assert proc.stderr is not None
        for line in proc.stderr:
            text = line.rstrip()
            if text:
                print(f"[appserver-fixture-stderr] {text}", flush=True)

    _t.Thread(target=_drain, daemon=True).start()
    try:
        yield proc
    finally:
        if proc.poll() is None:
            try:
                if proc.stdin:
                    proc.stdin.write(
                        json.dumps({"jsonrpc": "2.0", "id": 99, "method": "shutdown"})
                        + "\n"
                    )
                    proc.stdin.flush()
            except Exception:
                pass
            proc.terminate()
            proc.wait(timeout=5)


def test_appserver_full_conversation_round_trip(appserver_proc):
    client = AppserverClient(appserver_proc)
    from protocol.version import PROTOCOL_VERSION

    init = client.request(
        "initialize",
        {
            "client_name": "pytest",
            "client_version": "0.0.0",
            "protocol_version": PROTOCOL_VERSION,
        },
    )
    assert init["protocol_version"] == PROTOCOL_VERSION

    session = client.request(
        "session/new",
        {"workspace_root": str(PROJECT_ROOT)},
    )
    session_id = session["session_id"]

    result = client.request(
        "session/prompt",
        {"session_id": session_id, "text": "hello appserver"},
        timeout=30.0,
    )
    assert result["status"] == "succeeded"
    assert result["text"] == "stub:hello appserver"


def test_appserver_session_new_preserves_explicit_model_metadata(appserver_proc):
    client = AppserverClient(appserver_proc)
    client.request(
        "initialize",
        {
            "client_name": "pytest",
            "client_version": "0.0.0",
            "protocol_version": "1.0.0",
        },
    )
    session = client.request(
        "session/new",
        {
            "workspace_root": str(PROJECT_ROOT),
            "model": "deepseek-v4-flash",
            "provider_id": "deepseek",
        },
    )
    assert session["model_id"] == "deepseek-v4-flash"
    assert session["provider_id"] == "deepseek"


def test_appserver_stdout_only_jsonrpc(appserver_proc):
    client = AppserverClient(appserver_proc)
    client.request(
        "initialize",
        {
            "client_name": "pytest",
            "client_version": "0.0.0",
            "protocol_version": "1.0.0",
        },
    )
    session = client.request("session/new", {"workspace_root": str(PROJECT_ROOT)})
    client.request(
        "session/prompt",
        {"session_id": session["session_id"], "text": "ping"},
        timeout=30.0,
    )

    for line in client.raw_lines:
        if not line.strip():
            continue
        payload = json.loads(line)
        assert payload.get("jsonrpc") == "2.0"


def test_appserver_approval_bidirectional(appserver_proc):
    client = AppserverClient(appserver_proc)
    client.request(
        "initialize",
        {
            "client_name": "pytest",
            "client_version": "0.0.0",
            "protocol_version": "1.0.0",
        },
    )
    session = client.request("session/new", {"workspace_root": str(PROJECT_ROOT)})
    session_id = session["session_id"]

    prompt_id = client.send(
        "session/prompt",
        {"session_id": session_id, "text": "trigger-approval"},
    )

    deadline = time.monotonic() + 15.0
    while time.monotonic() < deadline:
        message = client.readline(timeout=0.5)
        if message is None:
            continue
        if message.get("method") == "approval/request":
            approval_rpc_id = message.get("id")
            params = message.get("params") or {}
            client.respond(
                int(approval_rpc_id),
                {
                    "request_id": params.get("request_id"),
                    "decision": "approved",
                },
            )
            continue
        if message.get("id") == prompt_id and "result" in message:
            assert message["result"]["text"] == "approval:approved"
            return
    raise AssertionError("approval round-trip did not complete")


def test_appserver_multiple_sessions(appserver_proc):
    client = AppserverClient(appserver_proc)
    client.request(
        "initialize",
        {
            "client_name": "pytest",
            "client_version": "0.0.0",
            "protocol_version": "1.0.0",
        },
    )
    s1 = client.request(
        "session/new",
        {"workspace_root": str(PROJECT_ROOT)},
        timeout=30.0,
    )
    s2 = client.request(
        "session/new",
        {"workspace_root": str(PROJECT_ROOT)},
        timeout=30.0,
    )
    assert s1["session_id"] != s2["session_id"]

    r1 = client.request(
        "session/prompt",
        {"session_id": s1["session_id"], "text": "one"},
        timeout=30.0,
    )
    r2 = client.request(
        "session/prompt",
        {"session_id": s2["session_id"], "text": "two"},
        timeout=30.0,
    )
    assert r1["text"] == "stub:one"
    assert r2["text"] == "stub:two"


def test_appserver_concurrent_sessions(appserver_proc):
    """Two sessions prompt in parallel; wall time must stay below 2x slow stub."""
    client = AppserverClient(appserver_proc)
    client.request(
        "initialize",
        {
            "client_name": "pytest",
            "client_version": "0.0.0",
            "protocol_version": "1.0.0",
        },
    )
    s1 = client.request(
        "session/new",
        {"workspace_root": str(PROJECT_ROOT)},
        timeout=30.0,
    )
    s2 = client.request(
        "session/new",
        {"workspace_root": str(PROJECT_ROOT)},
        timeout=30.0,
    )

    results: dict[str, dict] = {}
    errors: list[BaseException] = []

    def run_prompt(key: str, session_id: str, text: str) -> None:
        try:
            results[key] = client.request(
                "session/prompt",
                {"session_id": session_id, "text": text},
                timeout=30.0,
            )
        except BaseException as exc:
            errors.append(exc)

    start = time.monotonic()
    t1 = threading.Thread(
        target=run_prompt,
        args=("r1", s1["session_id"], "slow:one"),
    )
    t2 = threading.Thread(
        target=run_prompt,
        args=("r2", s2["session_id"], "slow:two"),
    )
    t1.start()
    t2.start()
    t1.join()
    t2.join()
    elapsed = time.monotonic() - start

    assert not errors, errors
    assert results["r1"]["text"] == "stub:one"
    assert results["r2"]["text"] == "stub:two"
    # Two slow stubs sleep 0.5s each; sequential ≥1.0s plus IPC. Coverage,
    # worker spawn, and GX job/persist work add ~0.5–1.2s in parallel; 2.25s
    # still fails a fully serial 2×(0.5s+spawn) run.
    assert elapsed < 2.25, f"expected concurrent prompts (<2.25s), got {elapsed:.2f}s"


def test_appserver_bootstrap_timeout():
    env = _appserver_env()
    env["RXYCODE_APPSERVER_BOOTSTRAP_DELAY"] = "2.0"
    proc = _appserver_proc_with_env(env)
    try:
        client = AppserverClient(proc)
        client.request(
            "initialize",
            {
                "client_name": "pytest",
                "client_version": "0.0.0",
                "protocol_version": "1.0.0",
            },
        )
        session = client.request(
            "session/new", {"workspace_root": str(PROJECT_ROOT)}
        )
        with pytest.raises(AssertionError, match="timed out"):
            client.request(
                "session/prompt",
                {
                    "session_id": session["session_id"],
                    "text": "hello",
                    "timeout_seconds": 0.2,
                },
                timeout=5.0,
            )
    finally:
        if proc.poll() is None:
            try:
                if proc.stdin:
                    proc.stdin.write(
                        json.dumps(
                            {"jsonrpc": "2.0", "id": 99, "method": "shutdown"}
                        )
                        + "\n"
                    )
                    proc.stdin.flush()
            except Exception:
                pass
            proc.terminate()
        proc.wait(timeout=10)


def test_appserver_emits_bootstrap_progress_before_first_result():
    """The first cold turn must explain bootstrap instead of appearing frozen."""
    env = _appserver_env()
    env["RXYCODE_APPSERVER_BOOTSTRAP_DELAY"] = "0.2"
    proc = _appserver_proc_with_env(env)
    try:
        client = AppserverClient(proc)
        client.request(
            "initialize",
            {
                "client_name": "pytest",
                "client_version": "0.0.0",
                "protocol_version": "1.0.0",
            },
        )
        session = client.request("session/new", {"workspace_root": str(PROJECT_ROOT)})
        prompt_id = client.send(
            "session/prompt",
            {"session_id": session["session_id"], "text": "cold start"},
        )
        progress: list[str] = []
        result: dict | None = None
        deadline = time.monotonic() + 10.0
        while time.monotonic() < deadline:
            message = client.readline(timeout=0.5)
            if message is None:
                continue
            if message.get("method") == "event/progress":
                params = message.get("params") or {}
                progress.append(str(params.get("text", "")))
            if message.get("id") == prompt_id and "result" in message:
                result = message["result"]
                break
        assert result is not None
        assert result["status"] == "succeeded"
        assert any("Agent" in text or "bootstrap" in text.lower() for text in progress)
    finally:
        if proc.poll() is None:
            try:
                if proc.stdin:
                    proc.stdin.write(
                        json.dumps({"jsonrpc": "2.0", "id": 99, "method": "shutdown"})
                        + "\n"
                    )
                    proc.stdin.flush()
            except Exception:
                pass
            proc.terminate()
            proc.wait(timeout=10)


def test_appserver_session_new_announces_background_warm():
    """Creating a task must expose the background warm instead of looking idle."""
    client = AppserverClient(_appserver_proc_with_env(_appserver_env()))
    proc = client.proc
    try:
        client.request(
            "initialize",
            {
                "client_name": "pytest",
                "client_version": "0.0.0",
                "protocol_version": "1.0.0",
            },
        )
        session = client.request("session/new", {"workspace_root": str(PROJECT_ROOT)})
        progress: list[str] = []
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline:
            message = client.readline(timeout=0.2)
            if message is None:
                continue
            if message.get("method") != "event/progress":
                continue
            params = message.get("params") or {}
            if params.get("session_id") == session["session_id"]:
                progress.append(str(params.get("text", "")))
                break
        assert any("warm" in text.lower() or "agent" in text.lower() for text in progress)
    finally:
        if proc.poll() is None:
            try:
                if proc.stdin:
                    proc.stdin.write(
                        json.dumps({"jsonrpc": "2.0", "id": 99, "method": "shutdown"})
                        + "\n"
                    )
                    proc.stdin.flush()
            except Exception:
                pass
            proc.terminate()
            proc.wait(timeout=10)


def test_appserver_prompt_timeout(appserver_proc):
    client = AppserverClient(appserver_proc)
    client.request(
        "initialize",
        {
            "client_name": "pytest",
            "client_version": "0.0.0",
            "protocol_version": "1.0.0",
        },
    )
    session = client.request("session/new", {"workspace_root": str(PROJECT_ROOT)})
    with pytest.raises(AssertionError, match="timed out"):
        client.request(
            "session/prompt",
            {
                "session_id": session["session_id"],
                "text": "hang:forever",
                "timeout_seconds": 0.2,
            },
            timeout=5.0,
        )


def test_appserver_prompt_timeout_does_not_block_next_prompt(appserver_proc):
    """An explicit prompt timeout is recoverable for the next user turn."""
    client = AppserverClient(appserver_proc)
    client.request(
        "initialize",
        {
            "client_name": "pytest",
            "client_version": "0.0.0",
            "protocol_version": "1.0.0",
        },
    )
    session = client.request("session/new", {"workspace_root": str(PROJECT_ROOT)})
    with pytest.raises(AssertionError, match="timed out"):
        client.request(
            "session/prompt",
            {
                "session_id": session["session_id"],
                "text": "hang:forever",
                "timeout_seconds": 0.2,
            },
            timeout=5.0,
        )

    recovered = client.request(
        "session/prompt",
        {
            "session_id": session["session_id"],
            "text": "hello after explicit timeout",
        },
        timeout=10.0,
    )
    assert recovered["status"] == "succeeded"


def test_appserver_silent_prompt_does_not_trigger_false_watchdog_stall():
    """A live provider may be silent while waiting; silence is not a dead worker."""
    env = _appserver_env()
    env["RXYCODE_APPSERVER_STALL_SECONDS"] = "2"
    env["RXYCODE_APPSERVER_HEARTBEAT_SECONDS"] = "1"
    env["RXYCODE_APPSERVER_WORKER_HEARTBEAT_SECONDS"] = "0.5"
    proc = _appserver_proc_with_env(env)
    try:
        client = AppserverClient(proc)
        client.request(
            "initialize",
            {
                "client_name": "pytest",
                "client_version": "0.0.0",
                "protocol_version": "1.0.0",
            },
        )
        session = client.request("session/new", {"workspace_root": str(PROJECT_ROOT)})
        result = client.request(
            "session/prompt",
            {"session_id": session["session_id"], "text": "silent:3"},
            timeout=10.0,
        )
        assert result["status"] == "succeeded"
        assert result["text"] == "stub:silent-complete"
    finally:
        if proc.poll() is None:
            try:
                if proc.stdin:
                    proc.stdin.write(
                        json.dumps({"jsonrpc": "2.0", "id": 99, "method": "shutdown"})
                        + "\n"
                    )
                    proc.stdin.flush()
            except Exception:
                pass
            proc.terminate()
            proc.wait(timeout=10)




def test_appserver_watchdog_stall_kills_job():
    env = _appserver_env()
    env["RXYCODE_APPSERVER_STALL_SECONDS"] = "2"
    env["RXYCODE_APPSERVER_HEARTBEAT_SECONDS"] = "1"
    env["RXYCODE_APPSERVER_WORKER_HEARTBEAT_SECONDS"] = "0"
    proc = _appserver_proc_with_env(env)
    try:
        client = AppserverClient(proc)
        client.request(
            "initialize",
            {
                "client_name": "pytest",
                "client_version": "0.0.0",
                "protocol_version": "1.0.0",
            },
        )
        session = client.request("session/new", {"workspace_root": str(PROJECT_ROOT)})
        prompt_id = client.send(
            "session/prompt",
            {"session_id": session["session_id"], "text": "hang:forever"},
        )

        job_states: list[str] = []
        error_response: dict | None = None
        saw_degraded_heartbeat = False
        deadline = time.monotonic() + 20.0
        while time.monotonic() < deadline:
            message = client.readline(timeout=0.5)
            if message is None:
                continue
            if message.get("method") == "event/job_status":
                params = message.get("params") or {}
                job_states.append(str(params.get("state")))
            if message.get("method") == "event/server_heartbeat":
                params = message.get("params") or {}
                if params.get("degraded"):
                    saw_degraded_heartbeat = True
            if message.get("id") == prompt_id and "error" in message:
                error_response = message["error"]
            if error_response is not None and saw_degraded_heartbeat:
                break

        assert error_response is not None, "expected stalled prompt JSON-RPC error"
        assert error_response["code"] == -32004
        assert "failed" in job_states
        assert saw_degraded_heartbeat

        # A stalled job kills only the affected worker. The appserver must
        # recover its prompt path so the next user message is not rejected by
        # a permanently degraded global latch.
        recovered = client.request(
            "session/prompt",
            {
                "session_id": session["session_id"],
                "text": "hello after stalled job",
            },
            timeout=10.0,
        )
        assert recovered["status"] == "succeeded"
    finally:
        if proc.poll() is None:
            try:
                if proc.stdin:
                    proc.stdin.write(
                        json.dumps({"jsonrpc": "2.0", "id": 99, "method": "shutdown"})
                        + "\n"
                    )
                    proc.stdin.flush()
            except Exception:
                pass
            proc.terminate()
            proc.wait(timeout=10)


def test_appserver_stalled_session_does_not_block_another_session():
    env = _appserver_env()
    env["RXYCODE_APPSERVER_STALL_SECONDS"] = "2"
    env["RXYCODE_APPSERVER_HEARTBEAT_SECONDS"] = "1"
    env["RXYCODE_APPSERVER_WORKER_HEARTBEAT_SECONDS"] = "0"
    proc = _appserver_proc_with_env(env)
    try:
        client = AppserverClient(proc)
        client.request(
            "initialize",
            {
                "client_name": "pytest",
                "client_version": "0.0.0",
                "protocol_version": "1.0.0",
            },
        )
        first = client.request("session/new", {"workspace_root": str(PROJECT_ROOT)})
        second = client.request("session/new", {"workspace_root": str(PROJECT_ROOT)})
        first_prompt = client.send(
            "session/prompt",
            {"session_id": first["session_id"], "text": "hang:forever"},
        )
        second_prompt = client.send(
            "session/prompt",
            {"session_id": second["session_id"], "text": "hang:forever"},
        )

        first_failed = False
        deadline = time.monotonic() + 15.0
        while time.monotonic() < deadline:
            message = client.readline(timeout=0.5)
            if message is None:
                continue
            if message.get("id") == first_prompt and "error" in message:
                first_failed = True
                break
        assert first_failed, "expected one stalled session to fail"

        third = client.request("session/new", {"workspace_root": str(PROJECT_ROOT)})
        recovered = client.request(
            "session/prompt",
            {"session_id": third["session_id"], "text": "hello while sibling is stalled"},
            timeout=10.0,
        )
        assert recovered["status"] == "succeeded"
        # Keep the second request id referenced so a late terminal response is
        # not mistaken for an untracked test request during teardown.
        assert second_prompt > first_prompt
    finally:
        if proc.poll() is None:
            try:
                if proc.stdin:
                    proc.stdin.write(
                        json.dumps({"jsonrpc": "2.0", "id": 99, "method": "shutdown"})
                        + "\n"
                    )
                    proc.stdin.flush()
            except Exception:
                pass
            proc.terminate()
            proc.wait(timeout=10)

def test_appserver_stalled_session_allows_existing_idle_session():
    """A failed first session must not poison an already-created idle task."""
    env = _appserver_env()
    env["RXYCODE_APPSERVER_STALL_SECONDS"] = "2"
    env["RXYCODE_APPSERVER_HEARTBEAT_SECONDS"] = "1"
    env["RXYCODE_APPSERVER_WORKER_HEARTBEAT_SECONDS"] = "0"
    proc = _appserver_proc_with_env(env)
    try:
        client = AppserverClient(proc)
        client.request(
            "initialize",
            {
                "client_name": "pytest",
                "client_version": "0.0.0",
                "protocol_version": "1.0.0",
            },
        )
        first = client.request("session/new", {"workspace_root": str(PROJECT_ROOT)})
        idle = client.request("session/new", {"workspace_root": str(PROJECT_ROOT)})
        first_prompt = client.send(
            "session/prompt",
            {"session_id": first["session_id"], "text": "hang:forever"},
        )
        first_failed = False
        deadline = time.monotonic() + 15.0
        while time.monotonic() < deadline:
            message = client.readline(timeout=0.5)
            if message is not None and message.get("id") == first_prompt and "error" in message:
                first_failed = True
                break
        assert first_failed
        recovered = client.request(
            "session/prompt",
            {"session_id": idle["session_id"], "text": "hello from idle sibling"},
            timeout=10.0,
        )
        assert recovered["status"] == "succeeded"
    finally:
        if proc.poll() is None:
            try:
                if proc.stdin:
                    proc.stdin.write(
                        json.dumps({"jsonrpc": "2.0", "id": 99, "method": "shutdown"})
                        + "\n"
                    )
                    proc.stdin.flush()
            except Exception:
                pass
            proc.terminate()
            proc.wait(timeout=10)


def test_appserver_failed_job_event(appserver_proc):
    client = AppserverClient(appserver_proc)
    client.request(
        "initialize",
        {
            "client_name": "pytest",
            "client_version": "0.0.0",
            "protocol_version": "1.0.0",
        },
    )
    session = client.request("session/new", {"workspace_root": str(PROJECT_ROOT)})
    prompt_id = client.send(
        "session/prompt",
        {"session_id": session["session_id"], "text": "fail:broken"},
    )

    job_states: list[str] = []
    result: dict | None = None
    deadline = time.monotonic() + 15.0
    while time.monotonic() < deadline:
        message = client.readline(timeout=0.5)
        if message is None:
            continue
        if message.get("method") == "event/job_status":
            params = message.get("params") or {}
            job_states.append(str(params.get("state")))
        if message.get("id") == prompt_id and "result" in message:
            result = message["result"]
            break

    assert result is not None
    assert result["status"] == "failed"
    assert "failed" in job_states


@pytest.mark.skipif(
    os.environ.get("RXYCODE_APPSERVER_LIVE") != "1",
    reason="set RXYCODE_APPSERVER_LIVE=1 to exercise real AgentV2 bootstrap",
)
@pytest.mark.timeout(360)
def test_appserver_live_agent_bootstrap():
    env = _live_appserver_env()
    proc = _appserver_proc_with_env(env)

    def _drain_appserver_stderr() -> None:
        assert proc.stderr is not None
        for line in proc.stderr:
            text = line.rstrip()
            if text:
                print(f"[appserver] {text}", flush=True)

    stderr_thread = threading.Thread(target=_drain_appserver_stderr, daemon=True)
    stderr_thread.start()

    try:
        client = AppserverClient(proc)
        print("[live] -> initialize", flush=True)
        started = time.monotonic()
        client.request(
            "initialize",
            {
                "client_name": "pytest-live",
                "client_version": "0.0.0",
                "protocol_version": "1.0.0",
            },
            timeout=60.0,
        )
        print(f"[live] <- initialize OK ({time.monotonic() - started:.1f}s)", flush=True)

        print("[live] -> session/new", flush=True)
        started = time.monotonic()
        session = client.request(
            "session/new",
            {"workspace_root": str(PROJECT_ROOT)},
            timeout=30.0,
        )
        print(f"[live] <- session/new OK ({time.monotonic() - started:.1f}s)", flush=True)
        session_id = session["session_id"]
        assert session_id

        print("[live] -> session/prompt (loads AgentV2; may take minutes)", flush=True)
        started = time.monotonic()
        result = client.request(
            "session/prompt",
            {
                "session_id": session_id,
                "text": "reply with exactly: ok",
                "timeout_seconds": float(
                    os.environ.get("RXYCODE_APPSERVER_LIVE_TIMEOUT", "300")
                ),
            },
            timeout=float(os.environ.get("RXYCODE_APPSERVER_LIVE_TIMEOUT", "300"))
            + 30.0,
        )
        print(
            f"[live] <- session/prompt {result.get('status')} "
            f"({time.monotonic() - started:.1f}s)",
            flush=True,
        )
        assert result.get("status") == "succeeded"
    finally:
        if proc.poll() is None:
            try:
                if proc.stdin:
                    proc.stdin.write(
                        json.dumps(
                            {"jsonrpc": "2.0", "id": 99, "method": "shutdown"}
                        )
                        + "\n"
                    )
                    proc.stdin.flush()
            except Exception:
                pass
            proc.terminate()
            proc.wait(timeout=10)
def test_appserver_set_thinking_expanded_emits_reasoning(appserver_proc):
    client = AppserverClient(appserver_proc)
    client.request(
        "initialize",
        {
            "client_name": "pytest",
            "client_version": "0.0.0",
            "protocol_version": "1.0.0",
        },
    )
    session = client.request("session/new", {"workspace_root": str(PROJECT_ROOT)})
    session_id = session["session_id"]

    toggled = client.request(
        "session/set_thinking_expanded",
        {"session_id": session_id, "expanded": True},
    )
    assert toggled["expanded"] is True

    prompt_id = client.send(
        "session/prompt",
        {
            "session_id": session_id,
            "text": "think:hello-thought",
            "thinking_expanded": True,
        },
    )
    saw_reasoning = False
    result = None
    deadline = time.monotonic() + 30.0
    while time.monotonic() < deadline:
        message = client.readline(timeout=1.0)
        if message is None:
            continue
        if message.get("method") == "event/reasoning_snapshot":
            params = message.get("params") or {}
            if "hello-thought" in str(params.get("text", "")):
                saw_reasoning = True
        if message.get("id") == prompt_id and "result" in message:
            result = message["result"]
            break
    assert result is not None
    assert result["status"] == "succeeded"
    assert saw_reasoning, "expected event/reasoning_snapshot while thinking expanded"


def test_appserver_session_warm_bootstraps(appserver_proc):
    client = AppserverClient(appserver_proc)
    client.request(
        "initialize",
        {
            "client_name": "pytest",
            "client_version": "0.0.0",
            "protocol_version": "1.0.0",
        },
    )
    session = client.request("session/new", {"workspace_root": str(PROJECT_ROOT)})
    warmed = client.request(
        "session/warm",
        {"session_id": session["session_id"], "timeout_seconds": 30},
        timeout=30.0,
    )
    assert warmed["ok"] is True
    assert warmed["warmed"] is True
