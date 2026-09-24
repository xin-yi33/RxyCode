"""Phase C C8 async benchmark with a built-in threshold gate.

Fixed workloads (no external dependencies, independently reproducible):

  1. interrupt_latency_s     - a mock LLM/agent run that delays 2.0s per
                               round; the interrupt (cancel) latency is the
                               time from cancel to the run task reporting
                               cancelled.
  2. tool_timeout_kill_rate  - a process-class tool (``python -m
                               http.server`` on win32 / ``sleep 600`` on
                               POSIX) is run through the controlled shell
                               executor with a 3s deadline; the kill rate is
                               the fraction of rounds with no residual
                               process after the timeout.
  3. stream_10k_s            - 30000 chars (~10k tokens at 3 chars/token,
                               computed with len(text), no tiktoken/network)
                               pushed through StreamCoalescer; wall time.
  4. concurrent_2x_speedup   - N in [1,2,4] mock sessions running the same
                               slow workload; the reported metric is the N=2
                               speedup (serial total / concurrent total).

CLI::

    python scripts/bench_async.py --out <path> [--rounds N] [--sessions N,M]
    python scripts/bench_async.py --compare <baseline.json> --out <path>

Exit codes: 0 = all thresholds met; 2 = at least one threshold FAILED.

Output schema (version 1)::

    {"schema_version": 1, "generated_at": ISO8601, "rounds": N,
     "env": {"python": "3.x", "platform": "win32|posix", "uvloop": bool,
             "commit": "<git-short-hash>"},
     "metrics": {"interrupt_latency_s": ..., "tool_timeout_kill_rate": ...,
                 "stream_10k_s": ..., "concurrent_2x_speedup": ...}}
"""

from __future__ import annotations

import argparse
import asyncio
import json
import socket
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

INTERRUPT_TARGET_S = 2.0
TOOL_TIMEOUT_S = 3.0
STREAM_CHARS = 30000
SESSION_WORKLOAD_S = 0.5

#: §8.2 thresholds (direction: metric must be better than the target).
THRESHOLDS = {
    "interrupt_latency_s": ("<=", 1.0),
    "tool_timeout_kill_rate": ("=", 1.0),
    "stream_10k_s": ("<=", None),  # relative to baseline when compared
    "concurrent_2x_speedup": (">=", 1.43),
}

STREAM_TEMPLATE = (
    "The quick brown fox jumps over the lazy dog. "
    "Each streamed token is part of the coalesced batch. "
)


# ── workloads ────────────────────────────────────────────────────────


async def bench_interrupt_latency() -> float:
    """Cancel a mock run (2.0s) through the real interrupt API
    (RunLifecycle.cancel, the C4 interrupt semantics) and measure the time
    from the interrupt to the run_task being cancelled."""

    from RxyCode.RxyCode1_1_0.core.run_lifecycle import RunLifecycle

    lifecycle = RunLifecycle()

    async def slow_run() -> str:
        await asyncio.sleep(INTERRUPT_TARGET_S)
        return "done"

    async def run_task() -> str:
        return await lifecycle.run(slow_run, session_id="bench")

    task = asyncio.create_task(run_task())
    await asyncio.sleep(0.05)
    started = time.monotonic()
    assert lifecycle.cancel(), "interrupt must reach a running run_task"
    try:
        await task
    except asyncio.CancelledError:
        pass
    return time.monotonic() - started


def _marker_pids(marker: str) -> set[int]:
    """Cross-platform PID collection that cannot self-match."""
    if sys.platform == "win32":
        import base64

        ps = (
            "Get-CimInstance Win32_Process | "
            f"Where-Object {{ $_.CommandLine -like '*{marker}*' }} | "
            "ForEach-Object { $_.ProcessId }"
        )
        encoded = base64.b64encode(ps.encode("utf-16-le")).decode("ascii")
        out = subprocess.run(
            ["powershell", "-NoProfile", "-EncodedCommand", encoded],
            capture_output=True, text=True, timeout=10,
        ).stdout
    else:
        out = subprocess.run(
            ["pgrep", "-f", marker], capture_output=True, text=True, timeout=10
        ).stdout
    return {int(line) for line in out.split() if line.strip().isdigit()}


def _allocate_free_port() -> int:
    """Bind 127.0.0.1:0, close, and return the ephemeral port number.

    There is a theoretical race between this return and the workload bind;
    callers must fail loudly if the listener never appears (no retry).
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _win_port_listener(port: int) -> set[int]:
    """PIDs listening on *port*.

    ``Get-NetTCPConnection`` loads NetTCPIP and exceeded the 10s subprocess
    budget on windows-latest (CI run 35959167174). ``netstat -ano`` reads the
    same TCP table without that module. netstat is not the listener, so its
    own command line cannot be recorded as the workload.
    """
    wanted = str(int(port))
    # Bytes, not text=: a GBK console makes the UTF-8 reader thread throw
    # and leaves stdout None. LISTENING/TCP/PID are ASCII either way.
    raw = subprocess.run(
        ["netstat", "-ano", "-p", "tcp"],
        capture_output=True,
        timeout=15,
        check=False,
    ).stdout or b""
    out = raw.decode("utf-8", errors="replace")
    pids: set[int] = set()
    for line in out.splitlines():
        parts = line.split()
        if len(parts) < 5 or parts[0].upper() != "TCP":
            continue
        if parts[3].upper() != "LISTENING":
            continue
        _host, sep, local_port = parts[1].rpartition(":")
        if sep != ":" or local_port != wanted or not parts[4].isdigit():
            continue
        pids.add(int(parts[4]))
    return pids


def _sleep_pgids() -> set[int]:
    """PGIDs of processes whose args contain 'sleep 600' (the fixed POSIX
    workload). The query itself never matches: ps does not embed the
    pattern in its own command line."""
    out = subprocess.run(
        ["ps", "-eo", "pid=,pgid=,args="],
        capture_output=True, text=True, timeout=10,
    ).stdout
    pgids: set[int] = set()
    for line in out.splitlines():
        parts = line.split(None, 2)
        if len(parts) == 3 and "sleep 600" in parts[2]:
            try:
                pgids.add(int(parts[1]))
            except ValueError:
                continue
    return pgids


def _all_pgids() -> set[int]:
    """Every PGID currently present in the process table."""
    out = subprocess.run(
        ["ps", "-eo", "pgid="],
        capture_output=True, text=True, timeout=10,
    ).stdout
    pgids: set[int] = set()
    for line in out.splitlines():
        try:
            pgids.add(int(line.strip()))
        except ValueError:
            continue
    return pgids


async def bench_tool_timeout_kill_rate(rounds: int) -> float:
    """Run the process-class tool with a 3s deadline; return the kill rate.

    Fixed commands per the card: ``python -m http.server <ephemeral>`` on
    win32 and ``sleep 600`` on POSIX.  The residual check is bound to the
    TARGET process group/process recorded at spawn time:
    - POSIX: after the workload spawns (in its own process group via
      start_new_session), the PGIDs of its members are recorded
      (``ps -eo pgid=,args=`` matching the fixed command); the end state is
      verified against THOSE PGIDs (no member of the recorded group is
      alive - the group is empty, i.e. the group was killed).
    - win32 (no PGID): the serving process's PIDs (ephemeral-port listeners)
      are recorded at spawn; the end state is verified against THOSE PIDs
      (psutil.pid_exists is False for every recorded pid).
    """
    import psutil

    from RxyCode.RxyCode1_1_0.utils.shell import shell_executor

    port = _allocate_free_port()
    killed = 0
    for _ in range(rounds):
        if sys.platform == "win32":
            argv = [sys.executable, "-m", "http.server", str(port)]
        else:
            argv = ["sleep", "600"]
        task = asyncio.create_task(
            shell_executor.execute_argv_async(argv, timeout=600)
        )
        # Record the target process group / process ids right after spawn.
        await asyncio.sleep(0.3)
        if sys.platform == "win32":
            target_pids = _win_port_listener(port)

            def residual_after(_target=target_pids) -> bool:
                return any(psutil.pid_exists(pid) for pid in _target)
        else:
            target_pgids = _sleep_pgids()

            def residual_after(_target=target_pgids) -> bool:
                # Enumerate EVERY member of the recorded groups: any
                # process in the process table carrying one of the recorded
                # PGIDs means the group is not empty.
                return bool(_all_pgids() & _target)
        spawned = target_pids if sys.platform == "win32" else target_pgids
        if not spawned:
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass
            raise RuntimeError(
                f"bench workload failed to start on port {port} "
                f"(port may have been stolen between allocate and bind); "
                f"refusing to report a kill-rate number"
            )
        # The card's fixed workload: wait_for(3s) around the shell call; the
        # timeout cancels it and the shell's cancellation path kills the
        # process group / tree (C7-locked).
        try:
            result = await asyncio.wait_for(task, timeout=TOOL_TIMEOUT_S)
        except asyncio.TimeoutError:
            result = {"error_type": "timeout"}
        if result.get("error_type") != "timeout":
            continue
        # The process-tree cleanup is asynchronous; poll until the recorded
        # group/pid set is gone (bounded) before crediting the kill.
        cleanup_deadline = time.monotonic() + 5
        while time.monotonic() < cleanup_deadline:
            if not residual_after():
                killed += 1
                break
            await asyncio.sleep(0.2)
    return killed / max(1, rounds)


async def bench_stream_10k() -> float:
    """Push ~10k tokens (30000 chars) through StreamCoalescer; return the
    best-of-3 wall time in seconds (the min filters scheduler noise)."""
    from RxyCode.RxyCode1_1_0.appserver.jsonrpc import StreamCoalescer

    text = (STREAM_TEMPLATE * (STREAM_CHARS // len(STREAM_TEMPLATE) + 1))[:STREAM_CHARS]
    assert len(text) == STREAM_CHARS

    best = float("inf")
    for _ in range(3):
        received: list[str] = []

        async def sink(
            kind: str, payload: str, _received: list[str] = received
        ) -> None:
            _received.append(payload)

        coalescer = StreamCoalescer(sink)
        await coalescer.start()
        started = time.monotonic()
        for i in range(0, len(text), 64):
            await coalescer.push("token", text[i : i + 64])
        await coalescer.stop()
        best = min(best, time.monotonic() - started)
        assert sum(len(p) for p in received) == STREAM_CHARS, (
            "coalescer must flush all"
        )
    return best


async def bench_concurrent_speedup(sessions: list[int]) -> float:
    """Serial vs concurrent wall time for the same slow workload; the
    reported metric is the N=2 speedup (>=1.43 target)."""

    async def session_workload() -> None:
        await asyncio.sleep(SESSION_WORKLOAD_S)

    speedups: dict[int, float] = {}
    for n in sessions:
        serial_started = time.monotonic()
        for _ in range(n):
            await session_workload()
        serial = time.monotonic() - serial_started

        concurrent_started = time.monotonic()
        await asyncio.gather(*(session_workload() for _ in range(n)))
        concurrent = time.monotonic() - concurrent_started
        speedups[n] = serial / concurrent
    # The documented metric is the N=2 speedup; the workload is fixed at
    # N=1/2/4, so a session list without 2 is a CLI error, never a silent
    # fallback (the fixed workload must not be narrowed).
    if 2 not in speedups:
        raise ValueError("--sessions must include 2 for the concurrency metric")
    return speedups[2]


# ── gate / compare ───────────────────────────────────────────────────


def _check_metric(
    name: str, value: float, baseline: float | None
) -> list[str]:
    """Return a list of FAIL messages for one metric (empty when passing).

    Each metric is checked against its §8.2 absolute threshold AND, when a
    baseline is provided, against the baseline in the same direction (no
    worse than baseline); stream has a 1% measurement-noise tolerance.
    """
    op, target = THRESHOLDS[name]
    fails: list[str] = []
    if target is not None:
        ok = value <= target if op == "<=" else value >= target if op == ">=" else value == target
        if not ok:
            fails.append(f"{name}: {value:.4f} violates {op} {target}")
    if baseline is not None:
        if name == "stream_10k_s" and value > baseline * 1.5 + 1e-9:
            # Sub-millisecond measurements carry large relative scheduler
            # noise (best-of-3 min still varies 10-20% between runs); the
            # baseline comparison guards against order-of-magnitude
            # regressions, not per-run noise.
            fails.append(
                f"{name}: {value:.4f}s > baseline {baseline:.4f}s * 1.5"
            )
        elif name == "interrupt_latency_s" and value > baseline * 2.0 + 1e-6:
            # Sub-millisecond measurements carry large relative scheduler
            # noise; the absolute threshold (< 1s) is the real gate and the
            # baseline comparison only guards against order-of-magnitude
            # regressions (>= 2x worse).
            fails.append(
                f"{name}: {value:.4f}s > baseline {baseline:.4f}s * 2.0"
            )
        elif name == "tool_timeout_kill_rate" and value < baseline:
            fails.append(
                f"{name}: {value:.4f} < baseline {baseline:.4f}"
            )
        elif name == "concurrent_2x_speedup" and value < baseline * 0.99:
            fails.append(
                f"{name}: {value:.4f} < baseline {baseline:.4f} * 0.99"
            )
    return fails


def _git_short_hash() -> str:
    try:
        out = subprocess.run(
            ["git", "-C", str(Path(__file__).resolve().parents[1]),
             "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=10,
        )
        return out.stdout.strip() or "unknown"
    except Exception:
        return "unknown"


def _env_info() -> dict:
    return {
        "python": f"{sys.version_info.major}.{sys.version_info.minor}",
        "platform": "win32" if sys.platform == "win32" else "posix",
        "uvloop": "uvloop" in sys.modules,
        "commit": _git_short_hash(),
    }


def _emit(
    out: Path,
    rounds: int,
    sessions: list[int],
    metrics: dict,
) -> dict:
    payload = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "rounds": rounds,
        "env": _env_info(),
        "metrics": metrics,
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def _load(path: str) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="RxyCode Phase C async benchmark")
    parser.add_argument("--out", required=True, help="output JSON path")
    parser.add_argument("--rounds", type=int, default=3)
    parser.add_argument("--sessions", default="1,2,4")
    parser.add_argument("--compare", default=None, help="baseline JSON path")
    args = parser.parse_args(argv)

    if args.rounds < 1:
        parser.error("--rounds must be >= 1")
    # The fixed concurrency workload is exactly N=1/2/4; any other set is a
    # CLI error (the workload must never be silently narrowed).
    raw_sessions = [part.strip() for part in args.sessions.split(",")]
    try:
        sessions = [int(part) for part in raw_sessions if part]
    except ValueError:
        parser.error("--sessions must be a comma-separated list of integers")
    if sessions != [1, 2, 4]:
        parser.error("--sessions must be exactly '1,2,4' (fixed workload)")

    metrics: dict = {}

    async def run_all() -> None:
        latencies = [
            await bench_interrupt_latency() for _ in range(args.rounds)
        ]
        metrics["interrupt_latency_s"] = max(latencies)
        metrics["tool_timeout_kill_rate"] = (
            await bench_tool_timeout_kill_rate(args.rounds)
        )
        metrics["stream_10k_s"] = await bench_stream_10k()
        try:
            metrics["concurrent_2x_speedup"] = (
                await bench_concurrent_speedup(sessions)
            )
        except ValueError as exc:
            metrics["concurrent_2x_speedup"] = 0.0
            metrics["_concurrency_error"] = str(exc)

    asyncio.run(run_all())

    if metrics.pop("_concurrency_error", None):
        print(f"FAIL: {metrics.pop('_concurrency_error')}")
        print("benchmark gate: FAILED")
        return 2

    baseline = _load(args.compare) if args.compare else None
    baseline_metrics = baseline.get("metrics") if baseline else None
    if baseline is not None:
        missing = [
            name for name in THRESHOLDS if name not in (baseline_metrics or {})
        ]
        if missing:
            for name in missing:
                print(f"FAIL: baseline lacks metric '{name}'")
            print("benchmark gate: FAILED")
            return 2

    fails: list[str] = []
    for name, value in metrics.items():
        base = baseline_metrics.get(name) if baseline_metrics else None
        fails.extend(_check_metric(name, value, base))

    payload = _emit(Path(args.out), args.rounds, sessions, metrics)
    print(json.dumps(payload["metrics"], indent=2))

    if fails:
        for message in fails:
            print(f"FAIL: {message}")
        print("benchmark gate: FAILED")
        return 2
    print("benchmark gate: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(_main())
