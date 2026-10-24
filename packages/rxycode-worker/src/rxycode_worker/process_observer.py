"""Kernel-identified process registration and per-window observation."""

from __future__ import annotations

import asyncio
import re
import sys
import threading
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from rxycode_worker.ctl import CTL_TIMEOUT_SECONDS

_KEY_RE = re.compile(r"^[a-f0-9]{64}$")


@dataclass
class _Process:
    pid: int
    create_time: float


@dataclass
class _Window:
    process_key: str
    sampler: Any


class ProcessObserverRegistry:
    """Parent-side, per-run process identities with isolated observation windows."""

    def __init__(
        self,
        max_processes: int = 16,
        max_windows: int = 16,
    ) -> None:
        self._max_processes = max(1, int(max_processes))
        self._max_windows = max(1, int(max_windows))
        self._root_pid = 0
        self._root_create_time = 0.0
        self._processes: OrderedDict[str, _Process] = OrderedDict()
        self._windows: OrderedDict[str, _Window] = OrderedDict()
        self._lock = threading.RLock()

    def bind_root(self, pid: int, create_time: float) -> None:
        with self._lock:
            self._root_pid = int(pid) if int(pid) > 0 else 0
            self._root_create_time = float(create_time) if self._root_pid else 0.0

    def close(self) -> None:
        with self._lock:
            self._windows.clear()
            self._processes.clear()
            self._root_pid = 0
            self._root_create_time = 0.0

    def register(self, args: dict[str, Any]) -> dict[str, Any]:
        process_key = str(args.get("process_key") or "")
        peer_pid = int(args.get("_peer_pid") or 0)
        if not _KEY_RE.fullmatch(process_key):
            return {"registered": False, "reason": "bad_process_key"}
        with self._lock:
            if not self._root_valid_unlocked():
                return {"registered": False, "reason": "root_unavailable"}
            self._prune_unlocked()
            existing = self._processes.get(process_key)
            if existing is not None:
                return {"registered": False, "reason": "duplicate"}
            create_time = self._verified_descendant_unlocked(peer_pid)
            if create_time is None:
                return {"registered": False, "reason": "peer_not_bound"}
            if len(self._processes) >= self._max_processes:
                return {"registered": False, "reason": "capacity"}
            self._processes[process_key] = _Process(peer_pid, create_time)
            return {"registered": True}

    def release_process(self, args: dict[str, Any]) -> dict[str, Any]:
        process_key = str(args.get("process_key") or "")
        with self._lock:
            removed = self._processes.pop(process_key, None) is not None
            for window_id, window in list(self._windows.items()):
                if window.process_key == process_key:
                    self._windows.pop(window_id, None)
        return {"released": removed}

    def observe_start(self, args: dict[str, Any]) -> dict[str, Any]:
        process_key = str(args.get("process_key") or "")
        window_id = str(args.get("window_id") or "")
        if not _KEY_RE.fullmatch(process_key) or not _KEY_RE.fullmatch(window_id):
            return {"available": False, "reason": "bad_observation_key"}
        with self._lock:
            if not self._process_alive_unlocked(process_key):
                return {"available": False, "reason": "process_unavailable"}
            if window_id in self._windows:
                return {"available": False, "reason": "duplicate_window"}
            if len(self._windows) >= self._max_windows:
                return {"available": False, "reason": "window_capacity"}
            process = self._processes[process_key]
            sampler = self._new_sampler(process.pid)
            sampler.sample()
            if not bool(getattr(sampler, "available", False)):
                return {
                    "available": False,
                    "reason": str(getattr(sampler, "reason", "") or "unavailable"),
                }
            self._windows[window_id] = _Window(process_key, sampler)
            return {"available": True}

    def observe_sample(self, args: dict[str, Any]) -> dict[str, Any]:
        window_id = str(args.get("window_id") or "")
        with self._lock:
            self._prune_unlocked()
            window = self._windows.get(window_id)
            if window is None:
                return {"available": False, "reason": "not_observing"}
            if not self._process_alive_unlocked(window.process_key):
                self._windows.pop(window_id, None)
                return {"available": False, "reason": "process_unavailable"}
            value = window.sampler.sample()
            if not bool(getattr(window.sampler, "available", False)):
                return {
                    "available": False,
                    "reason": str(
                        getattr(window.sampler, "reason", "") or "unavailable"
                    ),
                }
            return {"available": True, "sample": list(value)}

    def observe_cancel(self, args: dict[str, Any]) -> dict[str, Any]:
        window_id = str(args.get("window_id") or "")
        with self._lock:
            removed = self._windows.pop(window_id, None) is not None
        return {"cancelled": removed}

    def _process_alive_unlocked(self, process_key: str) -> bool:
        process = self._processes.get(process_key)
        if process is None:
            return False
        if self._process_identity_unlocked(process.pid) != process.create_time:
            self._processes.pop(process_key, None)
            for window_id, window in list(self._windows.items()):
                if window.process_key == process_key:
                    self._windows.pop(window_id, None)
            return False
        return True

    def _root_valid_unlocked(self) -> bool:
        if self._root_pid <= 0 or self._root_create_time <= 0:
            return False
        return self._process_identity_unlocked(self._root_pid) == self._root_create_time

    def _verified_descendant_unlocked(self, peer_pid: int) -> float | None:
        if peer_pid <= 0 or peer_pid == self._root_pid:
            return None
        identity = self._process_identity_unlocked(peer_pid)
        if identity is None:
            return None
        try:
            import psutil

            parents = {int(proc.pid) for proc in psutil.Process(peer_pid).parents()}
        except Exception:
            return None
        return identity if self._root_pid in parents else None

    def _prune_unlocked(self) -> None:
        if not self._root_valid_unlocked():
            self._windows.clear()
            self._processes.clear()
            return
        for process_key in list(self._processes):
            self._process_alive_unlocked(process_key)

    @staticmethod
    def _process_identity_unlocked(pid: int) -> float | None:
        try:
            import psutil

            proc = psutil.Process(pid)
            if not proc.is_running():
                return None
            return float(proc.create_time())
        except Exception:
            return None

    @staticmethod
    def _new_sampler(pid: int) -> Any:
        from RxyCode.RxyCode1_1_0.utils.shell import ProcessTreeSampler

        return ProcessTreeSampler(pid)


class RemoteProcessObserver:
    """Child-side adapter over the existing synchronous control channel."""

    def __init__(self, channel: Any) -> None:
        self._channel = channel

    def wrap_argv(self, argv: list[str], process_key: str) -> list[str]:
        helper = Path(__file__).with_name("registration_helper.py")
        return [
            str(Path(sys.executable).resolve()),
            "-I",
            "-S",
            str(helper.resolve()),
            "--socket",
            str(self._channel.sock_path),
            "--process-key",
            str(process_key),
            "--timeout",
            str(CTL_TIMEOUT_SECONDS),
            "--",
            *argv,
        ]

    async def prime(self, process_key: str, window_id: str) -> bool:
        result = await asyncio.to_thread(
            self._channel.process_observe_start,
            str(process_key),
            str(window_id),
        )
        return bool(result.get("available"))

    async def sample(self, window_id: str) -> tuple[float, int, int, int] | None:
        result = await asyncio.to_thread(
            self._channel.process_observe_sample,
            str(window_id),
        )
        if not result.get("available"):
            return None
        value = result.get("sample")
        if not isinstance(value, list) or len(value) != 4:
            return None
        return float(value[0]), int(value[1]), int(value[2]), int(value[3])

    async def cancel(self, window_id: str) -> None:
        await asyncio.to_thread(
            self._channel.process_observe_cancel,
            str(window_id),
        )

    async def release_process(self, process_key: str) -> None:
        await asyncio.to_thread(
            self._channel.process_release,
            str(process_key),
        )
