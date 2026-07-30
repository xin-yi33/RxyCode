"""
Tests for core/tracing.py: NodeSpan, Tracer, replay CLI, singleton.

Covers:
- NodeSpan creation and serialization (to_dict / from_dict round-trip)
- Tracer start_span / end_span lifecycle
- summary() per-node stats (count, p50, p99, total_tokens)
- JSONL persistence and reload via get_spans()
- replay() text output
- Global singleton get_tracer / reset_tracer
"""

import json
import time

import pytest

from RxyCode.RxyCode1_1_0.core.tracing import (
    NodeSpan,
    Tracer,
    get_tracer,
    reset_tracer,
    replay,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _isolated_data_dir(tmp_path, monkeypatch):
    """Redirect ~/.rxycode to a temp dir so tests never touch real user data."""
    monkeypatch.setenv("RXYCODE_DATA_DIR", str(tmp_path))
    # Reset the global tracer singleton so each test starts fresh.
    reset_tracer()
    yield
    reset_tracer()


# ---------------------------------------------------------------------------
# NodeSpan
# ---------------------------------------------------------------------------

class TestSpanCreation:
    """test_span_creation: NodeSpan creation and serialization."""

    def test_basic_creation(self):
        span = NodeSpan(
            node_name="executor",
            task_id="task_1",
            run_id="run_abc",
            start_ts=1000.0,
            end_ts=1002.5,
            token_usage={"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150},
            status="ok",
            error_msg="",
        )
        assert span.node_name == "executor"
        assert span.task_id == "task_1"
        assert span.run_id == "run_abc"
        assert span.status == "ok"
        assert span.error_msg == ""

    def test_duration_property(self):
        span = NodeSpan(
            node_name="goal_planner",
            task_id="",
            run_id="r1",
            start_ts=100.0,
            end_ts=105.0,
            token_usage={},
            status="ok",
            error_msg="",
        )
        assert span.duration_s == 5.0

    def test_duration_zero_when_not_finished(self):
        span = NodeSpan(
            node_name="decomposer",
            task_id="",
            run_id="r1",
            start_ts=100.0,
            end_ts=0.0,
            token_usage={},
            status="ok",
            error_msg="",
        )
        assert span.duration_s == 0.0

    def test_to_dict_roundtrip(self):
        span = NodeSpan(
            node_name="validator",
            task_id="task_42",
            run_id="run_xyz",
            start_ts=1000.0,
            end_ts=1003.5,
            token_usage={"prompt_tokens": 200, "completion_tokens": 80, "total_tokens": 280},
            status="error",
            error_msg="validation failed",
        )
        d = span.to_dict()
        assert d["node_name"] == "validator"
        assert d["task_id"] == "task_42"
        assert d["run_id"] == "run_xyz"
        assert d["start_ts"] == 1000.0
        assert d["end_ts"] == 1003.5
        assert d["token_usage"]["total_tokens"] == 280
        assert d["status"] == "error"
        assert d["error_msg"] == "validation failed"
        assert d["duration_s"] == 3.5

    def test_from_dict_roundtrip(self):
        original = NodeSpan(
            node_name="re_planner",
            task_id="task_5",
            run_id="run_001",
            start_ts=500.0,
            end_ts=501.0,
            token_usage={"prompt_tokens": 50, "completion_tokens": 30, "total_tokens": 80},
            status="timeout",
            error_msg="timed out",
        )
        d = original.to_dict()
        restored = NodeSpan.from_dict(d)
        assert restored.node_name == original.node_name
        assert restored.task_id == original.task_id
        assert restored.run_id == original.run_id
        assert restored.start_ts == original.start_ts
        assert restored.end_ts == original.end_ts
        assert restored.token_usage == original.token_usage
        assert restored.status == original.status
        assert restored.error_msg == original.error_msg
        assert restored.duration_s == original.duration_s

    def test_from_dict_defaults(self):
        """from_dict should tolerate missing optional fields."""
        minimal = {
            "node_name": "synthesizer",
            "run_id": "run_x",
            "start_ts": 0.0,
        }
        span = NodeSpan.from_dict(minimal)
        assert span.node_name == "synthesizer"
        assert span.task_id == ""
        assert span.end_ts == 0.0
        assert span.token_usage == {}
        assert span.status == "ok"
        assert span.error_msg == ""

    def test_to_dict_is_json_serializable(self):
        span = NodeSpan(
            node_name="goal_planner",
            task_id="",
            run_id="r1",
            start_ts=1.0,
            end_ts=2.0,
            token_usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            status="ok",
            error_msg="",
        )
        # Should not raise
        json_str = json.dumps(span.to_dict())
        d = json.loads(json_str)
        assert d["node_name"] == "goal_planner"


# ---------------------------------------------------------------------------
# Tracer: start / end
# ---------------------------------------------------------------------------

class TestTracerStartEnd:
    """test_tracer_start_end: Tracer start_span/end_span lifecycle."""

    def test_start_span_returns_span_with_start_ts(self):
        tracer = Tracer()
        span = tracer.start_span("goal_planner")
        assert span.node_name == "goal_planner"
        assert span.task_id == ""
        assert span.run_id == tracer.run_id
        assert span.start_ts > 0
        assert span.end_ts == 0.0  # not finished yet
        assert span.status == "ok"

    def test_start_span_with_task_id(self):
        tracer = Tracer()
        span = tracer.start_span("executor", task_id="task_1")
        assert span.task_id == "task_1"

    def test_end_span_sets_end_ts_and_persists(self):
        tracer = Tracer()
        span = tracer.start_span("executor", task_id="t1")
        time.sleep(0.01)
        tracer.end_span(span, token_usage={"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150})
        assert span.end_ts > span.start_ts
        assert span.duration_s > 0
        assert span.status == "ok"
        assert span.token_usage["total_tokens"] == 150
        # The trace file should exist on disk
        assert tracer.trace_file.exists()

    def test_end_span_with_error_status(self):
        tracer = Tracer()
        span = tracer.start_span("validator", task_id="t2")
        tracer.end_span(span, status="error", error_msg="bad output")
        assert span.status == "error"
        assert span.error_msg == "bad output"

    def test_end_span_with_timeout_status(self):
        tracer = Tracer()
        span = tracer.start_span("executor", task_id="t3")
        tracer.end_span(span, status="timeout", error_msg="30s exceeded")
        assert span.status == "timeout"
        assert span.error_msg == "30s exceeded"

    def test_end_span_redacts_credentials_from_error(self):
        tracer = Tracer(run_id="redacted")
        span = tracer.start_span("tool:web")
        secret = "sk-" + "abcdefghijklmnopqrstuvwxyz" + "123456"
        tracer.end_span(span, status="error", error_msg=f"Authorization: Bearer {secret}")
        assert secret not in span.error_msg
        assert "[REDACTED]" in span.error_msg

    def test_run_id_auto_generated(self):
        tracer = Tracer()
        assert tracer.run_id is not None
        assert len(tracer.run_id) > 0

    def test_run_id_explicit(self):
        tracer = Tracer(run_id="my_custom_run")
        assert tracer.run_id == "my_custom_run"
        assert "my_custom_run" in str(tracer.trace_file)

    def test_multiple_spans_persisted(self):
        tracer = Tracer()
        s1 = tracer.start_span("goal_planner")
        tracer.end_span(s1)
        s2 = tracer.start_span("decomposer")
        tracer.end_span(s2)
        s3 = tracer.start_span("executor", task_id="task_1")
        tracer.end_span(s3, token_usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15})
        spans = tracer.get_spans()
        assert len(spans) == 3
        assert spans[0].node_name == "goal_planner"
        assert spans[1].node_name == "decomposer"
        assert spans[2].node_name == "executor"
        assert spans[2].task_id == "task_1"
        assert spans[2].token_usage["total_tokens"] == 15


# ---------------------------------------------------------------------------
# Tracer: summary
# ---------------------------------------------------------------------------

class TestTracerSummary:
    """test_tracer_summary: summary() per-node statistics."""

    def test_summary_empty(self):
        tracer = Tracer()
        assert tracer.summary() == {}

    def test_summary_single_node(self):
        tracer = Tracer()
        span = tracer.start_span("goal_planner")
        tracer.end_span(span, token_usage={"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150})
        summary = tracer.summary()
        assert "goal_planner" in summary
        stats = summary["goal_planner"]
        assert stats["count"] == 1
        assert stats["total_tokens"] == 150
        assert stats["prompt_tokens"] == 100
        assert stats["completion_tokens"] == 50
        assert stats["total_duration_s"] >= 0
        assert stats["p50_duration_s"] >= 0
        assert stats["p99_duration_s"] >= 0

    def test_summary_multiple_nodes(self):
        tracer = Tracer()
        for node in ["goal_planner", "executor", "executor"]:
            s = tracer.start_span(node, task_id=f"t_{node}")
            tracer.end_span(s, token_usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15})
        summary = tracer.summary()
        assert set(summary.keys()) == {"goal_planner", "executor"}
        assert summary["goal_planner"]["count"] == 1
        assert summary["executor"]["count"] == 2
        assert summary["executor"]["total_tokens"] == 30  # 15 * 2

    def test_summary_p50_p99(self):
        """p50 should be the median, p99 near the max."""
        tracer = Tracer()
        # Create 5 spans with known durations by setting start/end directly
        durations = [0.1, 0.2, 0.3, 0.4, 0.5]
        for dur in durations:
            s = tracer.start_span("executor")
            # Manually set end_ts before calling end_span logic
            s.end_ts = s.start_ts + dur
            # Write to file directly since end_span uses time.time()
            import json as _json
            line = _json.dumps(s.to_dict(), ensure_ascii=False)
            with open(tracer.trace_file, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        summary = tracer.summary()
        stats = summary["executor"]
        assert stats["count"] == 5
        # p50 = median of [0.1, 0.2, 0.3, 0.4, 0.5] = 0.3
        assert abs(stats["p50_duration_s"] - 0.3) < 0.001
        # p99 should be very close to the max (0.5)
        assert abs(stats["p99_duration_s"] - 0.5) < 0.01
        # total_duration = sum of all = 1.5
        assert abs(stats["total_duration_s"] - 1.5) < 0.001

    def test_summary_token_accumulation(self):
        tracer = Tracer()
        usages = [
            {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150},
            {"prompt_tokens": 200, "completion_tokens": 100, "total_tokens": 300},
            {"prompt_tokens": 50, "completion_tokens": 25, "total_tokens": 75},
        ]
        for usage in usages:
            s = tracer.start_span("decomposer")
            tracer.end_span(s, token_usage=usage)
        summary = tracer.summary()
        stats = summary["decomposer"]
        assert stats["count"] == 3
        assert stats["total_tokens"] == 525  # 150 + 300 + 75
        assert stats["prompt_tokens"] == 350  # 100 + 200 + 50
        assert stats["completion_tokens"] == 175  # 50 + 100 + 25


# ---------------------------------------------------------------------------
# Tracer: JSONL persistence
# ---------------------------------------------------------------------------

class TestTracerPersistence:
    """test_tracer_persistence: JSONL file round-trip."""

    def test_trace_file_location(self, tmp_path):
        tracer = Tracer(run_id="test_persist")
        span = tracer.start_span("goal_planner")
        tracer.end_span(span)
        # File should be under RXYCODE_DATA_DIR/logs/traces/
        trace_dir = tmp_path / "logs" / "traces"
        assert tracer.trace_file == trace_dir / "test_persist.jsonl"
        assert tracer.trace_file.exists()

    def test_jsonl_format(self):
        tracer = Tracer(run_id="jsonl_fmt")
        span = tracer.start_span("executor", task_id="t1")
        tracer.end_span(span, token_usage={"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150})
        lines = tracer.trace_file.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == 1
        record = json.loads(lines[0])
        assert record["node_name"] == "executor"
        assert record["task_id"] == "t1"
        assert record["run_id"] == "jsonl_fmt"
        assert record["status"] == "ok"
        assert record["token_usage"]["total_tokens"] == 150

    def test_get_spans_reloads_from_disk(self):
        tracer = Tracer(run_id="reload_test")
        s1 = tracer.start_span("goal_planner")
        tracer.end_span(s1)
        s2 = tracer.start_span("decomposer")
        tracer.end_span(s2)
        # Create a NEW tracer with the same run_id - simulates a fresh process
        tracer2 = Tracer(run_id="reload_test")
        spans = tracer2.get_spans()
        assert len(spans) == 2
        assert spans[0].node_name == "goal_planner"
        assert spans[1].node_name == "decomposer"

    def test_get_spans_empty_when_no_file(self):
        tracer = Tracer(run_id="nonexistent_run")
        spans = tracer.get_spans()
        assert spans == []

    def test_multiple_writes_append(self):
        tracer = Tracer(run_id="append_test")
        for i in range(5):
            s = tracer.start_span("executor", task_id=f"task_{i}")
            tracer.end_span(s)
        spans = tracer.get_spans()
        assert len(spans) == 5
        for i, span in enumerate(spans):
            assert span.task_id == f"task_{i}"

    def test_error_msg_persisted(self):
        tracer = Tracer(run_id="err_persist")
        s = tracer.start_span("validator", task_id="t_err")
        tracer.end_span(s, status="error", error_msg="assertion failed: expected True got False")
        spans = tracer.get_spans()
        assert len(spans) == 1
        assert spans[0].status == "error"
        assert "assertion failed" in spans[0].error_msg


# ---------------------------------------------------------------------------
# Replay CLI
# ---------------------------------------------------------------------------

class TestReplay:
    """test_replay: replay() text output."""

    def test_replay_prints_spans(self, capsys):
        tracer = Tracer(run_id="replay_test")
        s1 = tracer.start_span("goal_planner")
        tracer.end_span(s1, token_usage={"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150})
        s2 = tracer.start_span("executor", task_id="task_1")
        tracer.end_span(s2, status="error", error_msg="boom")

        replay("replay_test")
        out = capsys.readouterr().out
        assert "replay_test" in out
        assert "goal_planner" in out
        assert "executor" in out
        assert "task_1" in out
        # Summary section
        assert "Per-node stats" in out
        assert "p50" in out

    def test_replay_shows_error_msg(self, capsys):
        tracer = Tracer(run_id="replay_err")
        s = tracer.start_span("validator", task_id="t_e")
        tracer.end_span(s, status="error", error_msg="custom error detail")
        replay("replay_err")
        out = capsys.readouterr().out
        assert "custom error detail" in out

    def test_replay_no_trace_found(self, capsys):
        replay("nonexistent_run_xyz")
        out = capsys.readouterr().out
        assert "No trace found" in out
        assert "nonexistent_run_xyz" in out

    def test_replay_multiple_spans(self, capsys):
        tracer = Tracer(run_id="replay_multi")
        for i in range(3):
            s = tracer.start_span("executor", task_id=f"task_{i}")
            tracer.end_span(s, token_usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15})
        replay("replay_multi")
        out = capsys.readouterr().out
        # Should show all 3 spans
        assert "Spans: 3" in out
        assert "task_0" in out
        assert "task_1" in out
        assert "task_2" in out


# ---------------------------------------------------------------------------
# Global singleton
# ---------------------------------------------------------------------------

class TestSingleton:
    """test singleton get_tracer / reset_tracer."""

    def test_get_tracer_returns_singleton(self):
        t1 = get_tracer()
        t2 = get_tracer()
        assert t1 is t2

    def test_reset_tracer_creates_new(self):
        t1 = get_tracer()
        t2 = reset_tracer()
        assert t1 is not t2
        assert get_tracer() is t2

    def test_reset_tracer_with_run_id(self):
        t = reset_tracer(run_id="custom_singleton")
        assert t.run_id == "custom_singleton"
        assert get_tracer() is t

    def test_singleton_persists_spans(self):
        tracer = get_tracer()
        s = tracer.start_span("goal_planner")
        tracer.end_span(s)
        # get_tracer again should return same tracer with same data
        same_tracer = get_tracer()
        spans = same_tracer.get_spans()
        assert len(spans) == 1
        assert spans[0].node_name == "goal_planner"


def test_trace_retention_keeps_current_and_newest_prior_run(tmp_path, monkeypatch):
    import RxyCode.RxyCode1_1_0.core.tracing as tracing

    monkeypatch.setattr(tracing, "get_data_dir", lambda: tmp_path)
    trace_dir = tmp_path / "logs" / "traces"
    trace_dir.mkdir(parents=True, exist_ok=True)
    for index in range(4):
        (trace_dir / f"old-{index}.jsonl").write_text("{}\n", encoding="utf-8")

    tracer = tracing.Tracer("current", retention_runs=2)
    span = tracer.start_span("executor")
    tracer.end_span(span)

    names = {path.name for path in trace_dir.glob("*.jsonl")}
    assert "current.jsonl" in names
    assert len(names) == 2


def test_trace_run_id_cannot_escape_trace_directory():
    with pytest.raises(ValueError, match="filesystem-safe"):
        Tracer("../outside")
