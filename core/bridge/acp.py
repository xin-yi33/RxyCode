"""B10: ACP（JSON-RPC over stdio）桥接适配器。

Claude Code ACP / Qwen Code ACP / Kimi Code ACP 语义：NDJSON 请求-响应。
复用 appserver/jsonrpc.py 的封装语义（逐行 JSON）。
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import subprocess
from typing import AsyncIterator

_logger = logging.getLogger(__name__)

from .base import AgentBridge, BridgeConfig

STDIN = asyncio.subprocess.PIPE
STDOUT = asyncio.subprocess.PIPE


def _process_wrapper_alive(proc: object) -> bool:
    """True if this Process object still thinks the child is running."""
    if getattr(proc, "returncode", None) is not None:
        return False
    poll = getattr(proc, "poll", None)
    if callable(poll):
        return poll() is None
    return True


def _os_pid_alive(pid: int | None) -> bool:
    if not pid:
        return False
    if os.name == "nt":
        import ctypes

        process_query_limited_information = 0x1000
        still_active = 259
        handle = ctypes.windll.kernel32.OpenProcess(
            process_query_limited_information, False, int(pid)
        )
        if not handle:
            return False
        try:
            exit_code = ctypes.c_ulong()
            if ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)) == 0:
                return False
            return int(exit_code.value) == still_active
        finally:
            ctypes.windll.kernel32.CloseHandle(handle)
    try:
        os.kill(int(pid), 0)
    except (ProcessLookupError, OSError):
        return False
    return True


def _kill_process_tree(proc: asyncio.subprocess.Process) -> None:
    """Kill the official-CLI process tree; never treat a platform call as success.

    Windows: taskkill /T /F, then verify.  POSIX: killpg, then verify.
    Either path falls back to ``proc.kill()``.  If the child is still alive
    after the fallback, log at error and raise (RLI-4).
    """
    pid = getattr(proc, "pid", None)
    if os.name == "nt":
        try:
            subprocess.run(
                ["taskkill", "/T", "/F", "/PID", str(pid)],
                capture_output=True,
                timeout=10,
            )
        except Exception:
            _logger.error("taskkill failed for pid=%s", pid, exc_info=True)
    else:
        killpg = getattr(os, "killpg", None)
        if killpg is not None:
            try:
                killpg(os.getpgid(proc.pid), 9)
            except (ProcessLookupError, OSError):
                _logger.error("killpg failed for pid=%s", pid, exc_info=True)

    if not _process_wrapper_alive(proc):
        return

    try:
        proc.kill()
    except ProcessLookupError:
        return

    if _os_pid_alive(pid):
        _logger.error("process tree still alive after kill fallback pid=%s", pid)
        raise RuntimeError(f"failed to kill process tree pid={pid}")


class ACPBridge(AgentBridge):
    """ACP 适配器：spawn 官方 agent（--acp），NDJSON JSON-RPC 会话。"""

    def __init__(
        self,
        cfg: BridgeConfig | None = None,
        cmd: list[str] | None = None,
    ) -> None:
        super().__init__(cfg or BridgeConfig())
        self._cmd = cmd or ["claude", "--acp"]
        self._proc: asyncio.subprocess.Process | None = None

    async def start(self) -> None:
        """spawn 子进程并完成 ACP 握手（进程组隔离，便于整树 kill）。"""
        kwargs: dict = {}
        if os.name != "nt":
            kwargs["start_new_session"] = True
        else:  # pragma: no cover - Windows 分支
            kwargs["creationflags"] = getattr(
                subprocess, "CREATE_NEW_PROCESS_GROUP", 0
            )
        self._proc = await asyncio.create_subprocess_exec(
            *self._cmd,
            stdin=STDIN,
            stdout=STDOUT,
            stderr=asyncio.subprocess.PIPE,
            **kwargs,
        )

    async def invoke(self, task: str) -> AsyncIterator[dict]:
        """发送 session/new_prompt 请求，流式消费 NDJSON 事件。"""
        proc = self._proc
        if proc is None or proc.stdin is None or proc.stdout is None:
            raise RuntimeError("bridge not started")
        req = {
            "jsonrpc": "2.0",
            "method": "session/new_prompt",
            "params": {"text": task},
            "id": 1,
        }
        proc.stdin.write((json.dumps(req) + "\n").encode("utf-8"))
        await proc.stdin.drain()
        async for line in proc.stdout:
            try:
                msg = json.loads(line)
            except (ValueError, TypeError):
                continue
            method = msg.get("method")
            if method in ("agent_message_chunk", "agent_thought_chunk", "tool_call"):
                yield {"type": method, "content": msg.get("params", {})}
            elif method == "session/result":
                yield {"type": "result", "content": msg.get("params", {}).get("result", "")}
                return

    async def stop(self) -> None:
        """超时/预算超限时 kill 整树并回收（不留僵尸进程，luna R1-3）。"""
        proc = self._proc
        if proc is not None and proc.returncode is None:
            _kill_process_tree(proc)
            try:
                await asyncio.wait_for(proc.wait(), timeout=5)
            except (asyncio.TimeoutError, ProcessLookupError):
                pass

    def usage(self) -> dict:
        """本桥接 usage；按 B9 契约归一化（luna R1-1：桥接按模型读契约）。

        桥接 agent 是旁路子进程（官方 CLI 自行管理协议细节），本层只
        按 B9 cache_contract 的 usage_fields 语义回填命中/成本字段；
        未识别模型 → 空（CB8）。
        """
        model = self.cfg.model or ""
        provider = self.cfg.provider or ""
        if not model or not provider:
            return {}
        from RxyCode.RxyCode1_1_0.core.catalog import get_contract

        contract = get_contract(provider, model)
        if contract is None:
            return {}
        fields = contract.get("usage_fields") or {}
        return {
            "cached_field": fields.get("cached"),
            "cost_ticks_field": fields.get("cost_ticks"),
            "reasoning_field": fields.get("reasoning"),
            "cache_mode": contract.get("cache_mode"),
        }
