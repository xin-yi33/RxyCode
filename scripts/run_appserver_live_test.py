#!/usr/bin/env python3
"""P4 appserver 全量 + Live AgentV2 观测入口（在 CMD 中运行此脚本即可）。

用法（项目根目录）::

    python scripts\\run_appserver_live_test.py

环境变量（可选）::

    RXYCODE_APPSERVER_LIVE_TIMEOUT=300   # live prompt 超时（秒）
    RXYCODE_MONITOR_HEARTBEAT=5          # 心跳间隔（秒）
    RXYCODE_MONITOR_STALL_WARN=90        # 无新输出超过此秒数则提示可能卡住
    RXYCODE_MONITOR_TOTAL_TIMEOUT=900    # 全量总时长上限（秒），0=不限制

输出说明::

    [monitor]  心跳：阶段、耗时、子进程状态、最近一条 pytest/live 日志
    [pytest]   pytest -s 透传
    [STALL?]   长时间无新输出时的卡住提示（bootstrap 常需 1–3 分钟，属正常）
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from appserver.live_env import build_live_appserver_env, live_credentials_status

PHASE_STUB = "STUB_SUITE"
PHASE_LIVE = "LIVE_AGENTV2"

STUB_TARGETS = [
    "tests/test_appserver",
    "tests/test_protocol_schema.py",
]
LIVE_TARGET = (
    "tests/test_appserver/test_stdio_integration.py::test_appserver_live_agent_bootstrap"
)

HEARTBEAT_SECONDS = float(os.environ.get("RXYCODE_MONITOR_HEARTBEAT", "5"))
STALL_WARN_SECONDS = float(os.environ.get("RXYCODE_MONITOR_STALL_WARN", "90"))
TOTAL_TIMEOUT_SECONDS = float(os.environ.get("RXYCODE_MONITOR_TOTAL_TIMEOUT", "900"))


@dataclass
class MonitorState:
    phase: str = "INIT"
    phase_started: float = field(default_factory=time.monotonic)
    run_started: float = field(default_factory=time.monotonic)
    last_output_at: float = field(default_factory=time.monotonic)
    last_line: str = "(waiting for output)"
    proc: subprocess.Popen[str] | None = None
    lock: threading.Lock = field(default_factory=threading.Lock)

    def set_phase(self, phase: str) -> None:
        with self.lock:
            self.phase = phase
            self.phase_started = time.monotonic()

    def note_output(self, line: str) -> None:
        text = line.rstrip()
        if not text:
            return
        with self.lock:
            self.last_output_at = time.monotonic()
            self.last_line = text[:160]

    def snapshot(self) -> tuple[str, float, float, float, str, str | None]:
        with self.lock:
            phase = self.phase
            phase_elapsed = time.monotonic() - self.phase_started
            total_elapsed = time.monotonic() - self.run_started
            silent = time.monotonic() - self.last_output_at
            last = self.last_line
            proc = self.proc
        if proc is None:
            status = "idle"
        elif proc.poll() is None:
            status = f"running pid={proc.pid}"
        else:
            status = f"exited({proc.returncode})"
        return phase, phase_elapsed, total_elapsed, silent, last, status


def _log(msg: str) -> None:
    print(msg, flush=True)


def _heartbeat_loop(state: MonitorState, stop: threading.Event) -> None:
    while not stop.wait(HEARTBEAT_SECONDS):
        phase, phase_s, total_s, silent_s, last, status = state.snapshot()
        line = (
            f"[monitor] PHASE={phase} | phase={phase_s:6.1f}s | total={total_s:7.1f}s | "
            f"{status} | silent={silent_s:5.1f}s"
        )
        _log(line)
        _log(f"[monitor]   last: {last}")
        if silent_s >= STALL_WARN_SECONDS and phase == PHASE_LIVE:
            _log(
                f"[STALL?] 已 {silent_s:.0f}s 无新输出 — Live 阶段 AgentV2 bootstrap/LLM "
                f"可能仍在进行（正常可达 1–3 分钟）；超过 "
                f"{os.environ.get('RXYCODE_APPSERVER_LIVE_TIMEOUT', '300')}s 将超时失败"
            )
        if TOTAL_TIMEOUT_SECONDS > 0 and total_s >= TOTAL_TIMEOUT_SECONDS:
            _log(
                f"[monitor] TOTAL_TIMEOUT {TOTAL_TIMEOUT_SECONDS:.0f}s 已到，终止子进程"
            )
            proc = state.proc
            if proc is not None and proc.poll() is None:
                proc.kill()
            stop.set()
            return


def _pump(stream, prefix: str, state: MonitorState) -> None:
    if stream is None:
        return
    for line in stream:
        text = line.rstrip()
        if text:
            state.note_output(text)
            print(f"{prefix}{text}", flush=True)


def _run_pytest(
    state: MonitorState,
    *,
    phase: str,
    args: list[str],
    env: dict[str, str],
) -> int:
    state.set_phase(phase)
    cmd = [sys.executable, "-m", "pytest", *args]
    _log(f"[monitor] >>> {' '.join(cmd)}")

    proc = subprocess.Popen(
        cmd,
        cwd=ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        bufsize=1,
    )
    state.proc = proc
    pump = threading.Thread(
        target=_pump, args=(proc.stdout, "[pytest] ", state), daemon=True
    )
    pump.start()
    rc = proc.wait()
    pump.join(timeout=2)
    state.proc = None
    phase, phase_s, total_s, _, _, _ = state.snapshot()
    _log(f"[monitor] <<< phase {phase} done in {phase_s:.1f}s exit={rc}")
    return int(rc)


def _check_config_hint() -> bool:
    home = Path.home()
    cfg = home / ".RxyCode" / "config.yaml"
    if cfg.is_file():
        _log(f"[monitor] config: {cfg}")
    else:
        _log(f"[monitor] WARN: 未找到 {cfg}")
        return False
    cred = live_credentials_status()
    _log(f"[monitor] credentials: {cred}")
    return cred.startswith("OK")


def main() -> int:
    env_stub = os.environ.copy()
    env_stub.setdefault("PYTHONIOENCODING", "utf-8")
    env_stub["RXYCODE_APPSERVER_STUB"] = "1"

    env_live = build_live_appserver_env(project_root=ROOT)
    env_live["RXYCODE_APPSERVER_LIVE"] = "1"
    live_timeout = env_live.get("RXYCODE_APPSERVER_LIVE_TIMEOUT", "300")

    _log("=" * 72)
    _log("[monitor] P4 appserver 全量验收 + Live AgentV2")
    _log(f"[monitor] ROOT={ROOT}")
    _log(f"[monitor] LIVE_TIMEOUT={live_timeout}s | HEARTBEAT={HEARTBEAT_SECONDS}s")
    _log(
        "[monitor] 阶段 1: Stub 集成 + 协议 schema | 阶段 2: Live AgentV2 bootstrap+prompt"
    )
    cred_ok = _check_config_hint()
    _log("=" * 72)

    state = MonitorState()
    stop = threading.Event()
    threading.Thread(target=_heartbeat_loop, args=(state, stop), daemon=True).start()

    exit_code = 0

    stub_rc = _run_pytest(
        state,
        phase=PHASE_STUB,
        args=[*STUB_TARGETS, "-v", "-s", "--tb=short"],
        env=env_stub,
    )
    if stub_rc != 0:
        _log(f"[monitor] FAIL: Stub 阶段 exit={stub_rc}，跳过 Live")
        stop.set()
        return stub_rc

    if not cred_ok:
        _log("[monitor] FAIL: 无法从 ~/.RxyCode 解析 API key，跳过 Live 阶段")
        _log(
            "[monitor] 提示: active_model 若使用 api_key_env，需设置对应环境变量，"
            "或在 config 里用已保存密钥的模型条目"
        )
        stop.set()
        return 1

    live_rc = _run_pytest(
        state,
        phase=PHASE_LIVE,
        args=[LIVE_TARGET, "-v", "-s", "--tb=short"],
        env=env_live,
    )
    if live_rc != 0:
        exit_code = live_rc

    stop.set()
    _, _, total_s, _, _, _ = state.snapshot()
    if exit_code == 0:
        _log(f"[monitor] ALL PASSED in {total_s:.1f}s")
    else:
        _log(f"[monitor] FAILED exit={exit_code} after {total_s:.1f}s")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
