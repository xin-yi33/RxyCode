"""Shared builders for PHASE-FIX4 E2E (AppserverClient 抄用 stdio 集成测试手法)。"""
from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import threading
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]


def appserver_env(extra: dict[str, str] | None = None) -> dict[str, str]:
    env = os.environ.copy()
    env["RXYCODE_APPSERVER_STUB"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONPATH"] = str(PROJECT_ROOT)
    if extra:
        env.update(extra)
    return env


def spawn_appserver(env: dict[str, str], cwd: Path | None = None) -> subprocess.Popen[str]:
    """启动 appserver 子进程。cwd 默认 PROJECT_ROOT；scheduler E2E 传 tmp_path —
    desktop/schedules.json 是相对 CWD 落盘的（appserver/server.py:265-270 现状），
    不传 tmp_path 会污染仓库根的 desktop/schedules.json（共享状态假绿源）。"""
    proc = subprocess.Popen(
        [sys.executable, "-m", "appserver"],
        cwd=str(cwd or PROJECT_ROOT),
        env=env,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        bufsize=1,
    )

    def _drain():
        assert proc.stderr is not None
        for line in proc.stderr:
            text = line.rstrip()
            if text:
                print(f"[fix4-e2e-stderr] {text}", flush=True)

    threading.Thread(target=_drain, daemon=True).start()
    return proc


def shutdown_appserver(proc: subprocess.Popen[str]) -> None:
    if proc.poll() is None:
        try:
            if proc.stdin:
                proc.stdin.write(json.dumps({"jsonrpc": "2.0", "id": 99, "method": "shutdown"}) + "\n")
                proc.stdin.flush()
        except Exception:
            pass
        proc.terminate()
        proc.wait(timeout=10)


class AppserverClient:
    """逐行抄 tests/test_appserver/test_stdio_integration.py 的同名类。"""

    def __init__(self, proc: subprocess.Popen[str]) -> None:
        self.proc = proc
        self._next_id = 1
        self._send_lock = threading.Lock()
        self._pending: dict[int, queue.Queue[dict]] = {}
        self._pending_lock = threading.Lock()
        self._notifications: queue.Queue[dict] = queue.Queue()
        self._stop = threading.Event()
        self._reader = threading.Thread(target=self._read_loop, daemon=True)
        self._reader.start()

    def _read_loop(self) -> None:
        assert self.proc.stdout is not None
        while not self._stop.is_set():
            line = self.proc.stdout.readline()
            if not line:
                break
            message = json.loads(line)
            request_id = message.get("id")
            routed = False
            if isinstance(request_id, int):
                with self._pending_lock:
                    pending = self._pending.get(request_id)
                if pending is not None:
                    pending.put(message)
                    routed = True
            if not routed and ("method" in message or "result" in message or "error" in message):
                self._notifications.put(message)

    def close(self) -> None:
        """停止 reader 的旗标（四轮复审 #1 修正）：普通「消费方重建」**不需要**也
        **不允许**通过关闭 stdout 实现——构造保存的是 ``self.proc``（写错属性名会
        被 except 吞掉）、``stdout.close()`` 可能阻塞、同一进程再建 client 只能拿到
        已关闭的 stdout。本方法只置旗标；reader 的最终回收走 ``shutdown()``。"""
        self._stop.set()

    def shutdown(self) -> None:
        """最终回收（五轮复审 #1 修正顺序）：
        停止消费方 → 停等 appserver 退出 → **join reader（EOF 后自然退出）** →
        关管道句柄。**禁止**先关闭被另一线程阻塞读取的 stdout——`close()`
        自身会阻塞，join 根本走不到（四轮搬到 `shutdown()` 没改变这一点）。
        调用方必须先停等 appserver（`shutdown_appserver(proc)` / 进程退出），
        收到 EOF 后 reader 的 readline 返回 b"" 自然结束。"""
        self._stop.set()
        self._reader.join(timeout=5.0)
        assert not self._reader.is_alive(), "reader thread leaked"
        for stream in (self.proc.stdout, self.proc.stdin, self.proc.stderr):
            try:
                if stream is not None:
                    stream.close()
            except Exception:
                pass

    def send(self, method: str, params: dict | None = None) -> int:
        return self._write_request(method, params)

    def _write_request(self, method, params=None, *, pending=None) -> int:
        with self._send_lock:
            request_id = self._next_id
            self._next_id += 1
        if pending is not None:
            with self._pending_lock:
                self._pending[request_id] = pending
        message = {"jsonrpc": "2.0", "id": request_id, "method": method}
        if params is not None:
            message["params"] = params
        assert self.proc.stdin is not None
        self.proc.stdin.write(json.dumps(message) + "\n")
        self.proc.stdin.flush()
        return request_id

    def readline(self, timeout: float = 10.0) -> dict | None:
        try:
            return self._notifications.get(timeout=timeout)
        except queue.Empty:
            return None

    def request(self, method: str, params: dict | None = None, timeout: float = 10.0) -> dict:
        response_queue: queue.Queue[dict] = queue.Queue()
        request_id = self._write_request(method, params, pending=response_queue)
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

    def initialize_and_session(self, workspace: str) -> str:
        from protocol.version import PROTOCOL_VERSION

        init = self.request(
            "initialize",
            {
                "client_name": "pytest-fix4",
                "client_version": "0.0.0",
                "protocol_version": PROTOCOL_VERSION,
            },
        )
        assert init["protocol_version"] == PROTOCOL_VERSION
        session = self.request("session/new", {"workspace_root": workspace}, timeout=30.0)
        return session["session_id"]


def collect_until(client: AppserverClient, predicate, timeout: float = 30.0) -> list[dict]:
    """持续收通知直到 predicate(events) 为真；返回消息序列（含响应）。"""
    import time

    seen: list[dict] = []
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        message = client.readline(timeout=0.5)
        if message is not None:
            seen.append(message)
            if predicate(seen):
                return seen
    return seen


def poll_session_events(
    client: AppserverClient,
    session_id: str,
    predicate,
    timeout: float = 20.0,
    cursor: int = 0,
) -> tuple[list[dict], int]:
    """生产 session/events RPC 轮询消费（cursor 去重，server.py:1834-1846 手法）。

    每 0.25s 一次 session/events 请求（cursor 递增），直到 predicate(events_seen) 真。
    返回 (全部已见事件, 最新 cursor)。超时返回截至当前的全部事件（断言层判红）。
    """
    import time

    seen: list[dict] = []
    latest_cursor = cursor
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = client.request(
            "session/events",
            {"session_id": session_id, "cursor": latest_cursor},
            timeout=5.0,
        )
        batch = result.get("events") or []
        latest_cursor = int(result.get("next_cursor") or latest_cursor)
        seen.extend(batch)
        if batch and predicate(seen):
            return seen, latest_cursor
        time.sleep(0.25)
    return seen, latest_cursor
