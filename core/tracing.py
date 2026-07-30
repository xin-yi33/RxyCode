"""Node-level tracing: span collection, JSONL persistence, replay CLI, p50 stats.

Stitched from OpenHands trajectory serialization:
- NodeSpan(node_name/task_id/start/end/token_usage/duration) -> JSONL
- Per-run trace file at ~/.rxycode/logs/traces/{run_id}.jsonl
- Replay CLI: python -m core.tracing replay <run_id>
- Per-node耗时统计 + p50/p99

Adapted from OpenHands (MIT) event stream/trajectory serialization pattern.
"""

from __future__ import annotations

import json
import re
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

try:
    from ..config.settings import get_data_dir, load_config
    from ..log.log_helpers import redact_sensitive
    from .log_retention import prune_run_files
except ImportError:  # Support direct ``python -m core.tracing`` invocation.
    from config.settings import get_data_dir, load_config
    from core.log_retention import prune_run_files
    from log.log_helpers import redact_sensitive


_RUN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")


# ---------------------------------------------------------------------------
# NodeSpan
# ---------------------------------------------------------------------------

@dataclass
class NodeSpan:
    """A single node execution span (one row in the trace JSONL)."""

    node_name: str          # "goal_planner" / "executor" / etc.
    task_id: str            # associated task ID (empty for non-task nodes)
    run_id: str             # run identifier
    start_ts: float         # unix timestamp
    end_ts: float           # unix timestamp (0 if not finished)
    token_usage: dict       # {"prompt_tokens": N, "completion_tokens": M, "total_tokens": K}
    status: str             # "ok" / "error" / "timeout"
    error_msg: str          # empty if status == "ok"

    @property
    def duration_s(self) -> float:
        """Elapsed seconds (0.0 if the span has not finished)."""
        return self.end_ts - self.start_ts if self.end_ts > 0 else 0.0

    def to_dict(self) -> dict:
        """Serialize to a plain dict suitable for JSON / JSONL."""
        return {
            "node_name": self.node_name,
            "task_id": self.task_id,
            "run_id": self.run_id,
            "start_ts": self.start_ts,
            "end_ts": self.end_ts,
            "token_usage": dict(self.token_usage),
            "status": self.status,
            "error_msg": self.error_msg,
            "duration_s": self.duration_s,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "NodeSpan":
        """Reconstruct a NodeSpan from a dict (e.g. loaded from JSONL)."""
        return cls(
            node_name=d["node_name"],
            task_id=d.get("task_id", ""),
            run_id=d["run_id"],
            start_ts=float(d["start_ts"]),
            end_ts=float(d.get("end_ts", 0)),
            token_usage=dict(d.get("token_usage", {})),
            status=d.get("status", "ok"),
            error_msg=d.get("error_msg", ""),
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _trace_dir() -> Path:
    """Return the trace directory (~/.rxycode/logs/traces/), creating it if needed."""
    d = get_data_dir() / "logs" / "traces"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _trace_path(run_id: str) -> Path:
    """Return the JSONL trace file path for a given run_id."""
    return _trace_dir() / f"{run_id}.jsonl"


def _percentile(sorted_vals: list[float], pct: float) -> float:
    """Linear-interpolation percentile (like numpy's default).

    ``pct`` is a fraction in [0, 1].  Returns 0.0 for an empty list.
    """
    if not sorted_vals:
        return 0.0
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    k = pct * (len(sorted_vals) - 1)
    lo = int(k)
    hi = min(lo + 1, len(sorted_vals) - 1)
    frac = k - lo
    return sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * frac


# ---------------------------------------------------------------------------
# Tracer
# ---------------------------------------------------------------------------

class Tracer:
    """Collects NodeSpans for a single run, persists to JSONL."""

    def __init__(
        self,
        run_id: str | None = None,
        *,
        retention_runs: int | None = None,
        manage_retention: bool = True,
    ):
        resolved_run_id = run_id or uuid.uuid4().hex
        if not isinstance(resolved_run_id, str) or not _RUN_ID_RE.fullmatch(
            resolved_run_id
        ):
            raise ValueError("run_id must be a non-empty, filesystem-safe identifier")
        self.run_id = resolved_run_id
        self.trace_file: Path = _trace_path(self.run_id)
        if manage_retention:
            if retention_runs is None:
                try:
                    retention_runs = int(
                        (load_config().get("observability") or {}).get(
                            "trace_retention_runs", 200
                        )
                    )
                except (TypeError, ValueError):
                    retention_runs = 200
            prune_run_files(
                self.trace_file.parent,
                keep_runs=max(1, retention_runs),
                protected=(self.trace_file,),
            )
        # In-memory spans accumulated during this Tracer instance's lifetime.
        # get_spans() always reads from disk so it sees persisted data too.
        self._spans: list[NodeSpan] = []

    # -- public API --------------------------------------------------------

    def start_span(self, node_name: str, task_id: str = "") -> NodeSpan:
        """Start timing a node execution.

        Returns a NodeSpan with ``end_ts=0`` (not yet finished).
        The caller should pass the returned span to :meth:`end_span`.
        """
        span = NodeSpan(
            node_name=node_name,
            task_id=task_id,
            run_id=self.run_id,
            start_ts=time.time(),
            end_ts=0.0,
            token_usage={"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
            status="ok",
            error_msg="",
        )
        self._spans.append(span)
        return span

    def end_span(
        self,
        span: NodeSpan,
        *,
        status: str = "ok",
        token_usage: dict | None = None,
        error_msg: str = "",
    ) -> None:
        """End a span and persist to JSONL.

        Mutates *span* in place (sets end_ts, status, token_usage, error_msg)
        and appends one JSON line to the trace file.
        """
        span.end_ts = time.time()
        span.status = status
        span.error_msg = redact_sensitive(error_msg) if error_msg else ""
        if token_usage:
            span.token_usage = dict(token_usage)

        line = json.dumps(span.to_dict(), ensure_ascii=False)
        self.trace_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.trace_file, "a", encoding="utf-8") as f:
            f.write(line + "\n")

    def get_spans(self) -> list[NodeSpan]:
        """Load all spans from the trace file.

        If the file does not exist, returns an empty list.
        """
        if not self.trace_file.exists():
            return []
        spans: list[NodeSpan] = []
        with open(self.trace_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                spans.append(NodeSpan.from_dict(json.loads(line)))
        return spans

    def summary(self) -> dict:
        """Per-node stats: count, total_duration, p50, p99, total_tokens.

        Returns a dict keyed by node_name, each value being a stats dict.
        """
        spans = self.get_spans()
        by_node: dict[str, list[NodeSpan]] = {}
        for s in spans:
            by_node.setdefault(s.node_name, []).append(s)

        result: dict[str, dict] = {}
        for node_name, node_spans in by_node.items():
            durations = sorted(s.duration_s for s in node_spans)
            total_tokens = sum(s.token_usage.get("total_tokens", 0) for s in node_spans)
            total_prompt = sum(s.token_usage.get("prompt_tokens", 0) for s in node_spans)
            total_completion = sum(s.token_usage.get("completion_tokens", 0) for s in node_spans)
            total_duration = sum(durations)
            result[node_name] = {
                "count": len(node_spans),
                "total_duration_s": round(total_duration, 6),
                "p50_duration_s": round(_percentile(durations, 0.50), 6),
                "p99_duration_s": round(_percentile(durations, 0.99), 6),
                "total_tokens": total_tokens,
                "prompt_tokens": total_prompt,
                "completion_tokens": total_completion,
            }
        return result


# ---------------------------------------------------------------------------
# Replay CLI
# ---------------------------------------------------------------------------

def replay(run_id: str) -> None:
    """Print a text replay of a run's spans.

    Format: ``[timestamp] node_name  task_id  duration_s  status  tokens``
    """
    tracer = Tracer(run_id=run_id, manage_retention=False)
    spans = tracer.get_spans()

    if not spans:
        print(f"No trace found for run_id={run_id}")
        return

    # Header
    print(f"{'='*72}")
    print(f"  Run: {run_id}   Spans: {len(spans)}")
    print(f"{'='*72}")
    header = (
        f"{'Timestamp':<21} "
        f"{'Node':<18} "
        f"{'Task':<12} "
        f"{'Dur(s)':>8} "
        f"{'Status':<8} "
        f"{'Tokens':>8}"
    )
    print(header)
    print("-" * 72)

    for span in spans:
        ts_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(span.start_ts))
        dur = f"{span.duration_s:.3f}"
        tokens = span.token_usage.get("total_tokens", 0)
        task = span.task_id[:12] if span.task_id else "-"
        print(
            f"{ts_str:<21} "
            f"{span.node_name:<18} "
            f"{task:<12} "
            f"{dur:>8} "
            f"{span.status:<8} "
            f"{tokens:>8}"
        )
        if span.error_msg:
            print(f"{'':>21}  - {span.error_msg}")

    # Summary
    print("-" * 72)
    summary = tracer.summary()
    print(f"  Per-node stats:")
    for node_name, stats in summary.items():
        print(
            f"    {node_name:<18} "
            f"count={stats['count']}  "
            f"p50={stats['p50_duration_s']:.3f}s  "
            f"p99={stats['p99_duration_s']:.3f}s  "
            f"tokens={stats['total_tokens']}"
        )
    print(f"{'='*72}")


def main():
    """CLI entry: python -m core.tracing replay <run_id>"""
    import argparse

    parser = argparse.ArgumentParser(
        prog="core.tracing",
        description="RxyCode node-level tracing & replay",
    )
    sub = parser.add_subparsers(dest="cmd")

    rp = sub.add_parser("replay", help="Replay a run's spans")
    rp.add_argument("run_id", help="Run ID to replay")

    args = parser.parse_args()
    if args.cmd == "replay":
        replay(args.run_id)
    else:
        parser.print_help()


# ---------------------------------------------------------------------------
# Global singleton
# ---------------------------------------------------------------------------

_tracer: Optional[Tracer] = None


def get_tracer() -> Tracer:
    """Return the process-global Tracer singleton (lazy-init)."""
    global _tracer
    if _tracer is None:
        _tracer = Tracer()
    return _tracer


def reset_tracer(run_id: str | None = None) -> Tracer:
    """Discard the current global Tracer and create a fresh one.

    Useful for tests or when starting a new run with an explicit run_id.
    """
    global _tracer
    _tracer = Tracer(run_id=run_id)
    return _tracer


if __name__ == "__main__":
    main()
