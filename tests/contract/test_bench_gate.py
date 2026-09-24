"""Phase C C8 contract tests: async benchmark script + threshold gate.

scripts/bench_async.py must:
- require --out (CLI), default --rounds 3, default --sessions 1,2,4;
- run four fixed workloads and emit the documented JSON schema;
- enforce the §8.2 thresholds (FAIL -> exit code 2; OK -> 0);
- support --compare against a baseline file (same schema).
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

BENCH = Path(__file__).resolve().parents[2] / "scripts" / "bench_async.py"
EVIDENCE = (
    Path(__file__).resolve().parents[2]
    / "docs" / "plans" / "opus5-plan" / "rxycode" / "evidence"
)


def _run_bench(*args: str, timeout: float = 300) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(BENCH), *args],
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def test_win_port_listener_sees_a_real_socket():
    """The Windows listener lookup must see a socket this process opened.

    This drives ``_win_port_listener`` itself. A subprocess timeout inside
    that helper used to fail the bench contract on windows-latest.
    """
    import os
    import socket

    if sys.platform != "win32":
        pytest.skip("netstat listener lookup is Windows-only")
    from RxyCode.RxyCode1_1_0.scripts.bench_async import _win_port_listener

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    sock.listen(1)
    port = int(sock.getsockname()[1])
    try:
        assert os.getpid() in _win_port_listener(port)
    finally:
        sock.close()


def test_bench_requires_out(tmp_path):
    result = _run_bench("--rounds", "1")
    assert result.returncode != 0
    assert "--out" in result.stderr or "--out" in result.stdout


def test_bench_emits_documented_schema(tmp_path):
    out = tmp_path / "bench.json"
    result = _run_bench("--out", str(out), "--rounds", "1")
    assert result.returncode == 0, result.stderr
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["schema_version"] == 1
    assert "generated_at" in data and "T" in data["generated_at"]
    assert data["rounds"] == 1
    env = data["env"]
    for key in ("python", "platform", "uvloop", "commit"):
        assert key in env
    metrics = data["metrics"]
    for key in (
        "interrupt_latency_s",
        "tool_timeout_kill_rate",
        "stream_10k_s",
        "concurrent_2x_speedup",
    ):
        assert key in metrics


def test_bench_thresholds_pass_for_current_implementation(tmp_path):
    """The four metrics must meet the §8.2 thresholds (interrupt < 1s,
    kill rate = 1.0, stream <= baseline x1.0 (no baseline: recorded only),
    concurrency speedup >= 1.43)."""
    out = tmp_path / "bench.json"
    result = _run_bench("--out", str(out), "--rounds", "1")
    assert result.returncode == 0, result.stderr
    data = json.loads(out.read_text(encoding="utf-8"))
    m = data["metrics"]
    assert m["interrupt_latency_s"] < 1.0
    assert m["tool_timeout_kill_rate"] == 1.0
    assert m["concurrent_2x_speedup"] >= 1.43


def test_bench_compare_ok_when_current_meets_baseline(tmp_path):
    """--compare passes when the current run meets a (constructed) baseline;
    a real run's measurement noise must not decide the unit test, so the
    baseline is a generous JSON document and the current run is real."""
    base = tmp_path / "base.json"
    cur = tmp_path / "cur.json"
    base.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "generated_at": "2026-08-11T00:00:00",
                "rounds": 1,
                "env": {"python": "3", "platform": "x", "uvloop": False, "commit": "x"},
                "metrics": {
                    "interrupt_latency_s": 1.0,
                    "tool_timeout_kill_rate": 1.0,
                    "stream_10k_s": 5.0,
                    "concurrent_2x_speedup": 1.0,
                },
            }
        ),
        encoding="utf-8",
    )
    assert _run_bench("--out", str(cur), "--rounds", "1").returncode == 0
    result = _run_bench("--compare", str(base), "--out", str(cur))
    assert result.returncode == 0, result.stderr


def test_bench_compare_fails_when_stream_regressed(tmp_path):
    # The stream criterion is a relative check: value > baseline * 1.5 + 1e-9
    # must FAIL. We test the gate logic directly instead of through a real
    # measurement, because fast CI runners can legitimately measure
    # stream_10k_s == 0.0, which can never exceed any baseline and would make
    # the integration path undetectable for the regression this test guards.
    from RxyCode.RxyCode1_1_0.scripts.bench_async import _check_metric

    fails = _check_metric("stream_10k_s", 0.001, baseline=0.0)
    assert len(fails) == 1, fails
    assert "stream_10k_s" in fails[0]

    ok = _check_metric("stream_10k_s", 0.001, baseline=0.01)
    assert ok == []


def test_bench_invalid_sessions_is_rejected(tmp_path):
    """A session list other than exactly 1,2,4 must be a CLI error (the
    fixed N=1/2/4 workload must never be silently narrowed)."""
    out = tmp_path / "bench.json"
    result = _run_bench("--out", str(out), "--rounds", "1", "--sessions", "bogus")
    assert result.returncode != 0
    partial = _run_bench("--out", str(out), "--rounds", "1", "--sessions", "1,2")
    assert partial.returncode != 0
