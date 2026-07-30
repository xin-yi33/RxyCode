"""Unit tests for log/monitor.py (问题9: log/monitor audit hardening).

These guard the aggregation invariants called out in the plan:
- counters never hold negative drift after upsert/subtract,
- evidence totals are not over-counted when a run is re-recorded,
- record_evidence attaches to the authoritative run record even when runs
  are interleaved.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from RxyCode.RxyCode1_1_0.log.monitor import RunMonitor


def _evidence(status="succeeded", executed=True, artifacts=None):
    return {
        "status": status,
        "executed": executed,
        "artifacts": artifacts or [],
    }


def test_no_negative_counter_drift_on_upsert():
    m = RunMonitor()
    base = {
        "failure_attribution": {"timeout": 3},
        "token_usage": {"input_tokens": 100, "output_tokens": 50, "total_tokens": 150},
    }
    m.record("run-a", "succeeded", 1.0, metrics=base)
    # Upsert with DECREASED metrics; must not leave negative aggregation values.
    decreased = {
        "failure_attribution": {"timeout": 1},
        "token_usage": {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
    }
    m.record("run-a", "succeeded", 1.2, metrics=decreased)
    snap = m.snapshot()
    assert snap["failure_attribution"]["timeout"] == 1, snap["failure_attribution"]
    assert snap["token_usage"]["input_tokens"] == 10, snap["token_usage"]
    # invariant: no negative values anywhere in the aggregates
    for value in snap["failure_attribution"].values():
        assert value >= 0
    for value in snap["token_usage"].values():
        assert value >= 0


def test_evidence_totals_not_overcounted_on_upsert_and_re_evidence():
    m = RunMonitor()
    rid = "run-ev"
    m.record_evidence(rid, _evidence())
    m.record_evidence(rid, _evidence())
    m.record_evidence(rid, _evidence())
    m.record(rid, "succeeded", 1.0)
    totals_after_first = m.snapshot()["tool_evidence"]["total"]
    assert totals_after_first == 3, totals_after_first
    # Re-record the same run (duplicate observer), then more evidence arrives.
    m.record(rid, "succeeded", 1.0)
    m.record_evidence(rid, _evidence())
    m.record_evidence(rid, _evidence())
    snap = m.snapshot()
    # 3 (initial) + 2 (after upsert) = 5, NOT double-counted to 7.
    assert snap["tool_evidence"]["total"] == 5, snap["tool_evidence"]


def test_record_evidence_attaches_to_authoritative_run_when_interleaved():
    m = RunMonitor()
    m.record("run-1", "succeeded", 1.0)
    m.record("run-2", "succeeded", 1.0)
    # Evidence for run-1 arrives while run-2 is the most recent record.
    m.record_evidence("run-1", _evidence())
    snap = m.snapshot()
    last = snap["last_run"]
    assert last["run_id"] == "run-2", last  # most recent record, not corrupted
    # run-1's evidence is on run-1's own record, not run-2's.
    runs = m._runs
    assert runs["run-1"]["tool_evidence"]["total"] == 1, runs["run-1"]
    assert runs["run-2"].get("tool_evidence", {"total": 0})["total"] == 0, runs["run-2"]


def test_upsert_preserves_steps_replans_aggregates():
    m = RunMonitor()
    m.record("run-s", "succeeded", 2.0, metrics={"steps": 4, "replans": 1})
    m.record("run-s", "succeeded", 3.0, metrics={"steps": 6, "replans": 2})
    snap = m.snapshot()
    assert snap["average_steps"] == 6, snap["average_steps"]
    assert snap["average_replans"] == 2, snap["average_replans"]
    assert snap["status_counts"]["succeeded"] == 1, snap["status_counts"]
