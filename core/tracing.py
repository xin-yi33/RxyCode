"""Node-level tracing: span collection, JSONL persistence, replay CLI, p50 stats.

Stitched from OpenHands trajectory serialization:
- NodeSpan(node_name/task_id/start/end/token_usage/duration) -> JSONL
- Per-run trace file at ~/.rxycode/logs/traces/{run_id}.jsonl
- Replay CLI: python -m core.tracing replay <run_id>
- Per-node耗时统计 + p50/p99

Adapted from OpenHands (MIT) event stream/trajectory serialization pattern.
"""

from __future__ import annotations

import argparse
import json
import re
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from RxyCode.RxyCode1_1_0.config.settings import get_data_dir, load_config
from RxyCode.RxyCode1_1_0.core.log_retention import prune_run_files
from RxyCode.RxyCode1_1_0.log.log_helpers import redact_sensitive


_RUN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")


# ---------------------------------------------------------------------------
# NodeSpan
# ---------------------------------------------------------------------------

@dataclass
class LlmCallRecord:
    """一次 LLM 调用的完整记录。

    这是蒸馏数据集的原始素材。默认**不采集**（隐私 + 磁盘），由
    settings.distillation.collect 打开。

    quality 由 J4 回填 QualitySignal；采集时先留空。
    """

    role: str
    stage: str
    model: str
    provider: str
    messages: list[dict] | None = None
    response: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    duration_s: float = 0.0
    quality: Any | None = None
    session_id: str = ""


DISTILLATION_COLLECT_NOTICE = (
    "蒸馏采集已打开：本会话的模型输入/输出会写入本地 distillation JSONL，"
    "仅用于后续训练，默认关闭。"
)


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
    role: str = ""
    stage: str = ""
    delegation_depth: int = 0
    tokens: int = 0
    span_id: str = ""
    parent_id: str = ""
    kind: str = ""
    detail: str = ""
    session_id: str = ""
    team: str = ""
    mode: str = ""
    decided_by: str = ""
    budget: dict = field(default_factory=dict)
    cache_hit_rate: float | None = None

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
            "role": self.role,
            "stage": self.stage,
            "delegation_depth": self.delegation_depth,
            "tokens": self.tokens,
            "span_id": self.span_id,
            "parent_id": self.parent_id,
            "kind": self.kind,
            "detail": self.detail,
            "session_id": self.session_id,
            "team": self.team,
            "mode": self.mode,
            "decided_by": self.decided_by,
            "budget": dict(self.budget),
            "cache_hit_rate": self.cache_hit_rate,
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
            role=d.get("role", ""),
            stage=d.get("stage", ""),
            delegation_depth=int(d.get("delegation_depth", 0) or 0),
            tokens=int(d.get("tokens", 0) or 0),
            span_id=d.get("span_id", ""),
            parent_id=d.get("parent_id", ""),
            kind=d.get("kind", ""),
            detail=d.get("detail", ""),
            session_id=d.get("session_id", ""),
            team=d.get("team", ""),
            mode=d.get("mode", ""),
            decided_by=d.get("decided_by", ""),
            budget=dict(d.get("budget") or {}),
            cache_hit_rate=d.get("cache_hit_rate"),
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

    def start_span(
        self,
        node_name: str,
        task_id: str = "",
        *,
        role: str = "",
        stage: str = "",
        delegation_depth: int = 0,
        kind: str = "",
        parent_id: str = "",
        detail: str = "",
        session_id: str = "",
        team: str = "",
        mode: str = "",
        decided_by: str = "",
        budget: dict | None = None,
    ) -> NodeSpan:
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
            role=role,
            stage=stage,
            delegation_depth=delegation_depth,
            span_id=uuid.uuid4().hex[:12],
            parent_id=parent_id,
            kind=kind,
            detail=detail,
            session_id=session_id or task_id,
            team=team,
            mode=mode,
            decided_by=decided_by,
            budget=dict(budget or {}),
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
            span.tokens = int(span.token_usage.get("total_tokens", 0) or 0)

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

def _collect_enabled() -> bool:
    try:
        return bool((load_config().get("distillation") or {}).get("collect", False))
    except Exception:
        return False


def distillation_ui_notice() -> str | None:
    """Non-empty only when collection is on — F13/settings must show this."""
    if _collect_enabled():
        return DISTILLATION_COLLECT_NOTICE
    return None


def _record_safely(record: LlmCallRecord) -> None:
    """采集永远不能影响主流程。

    磁盘满、权限不足、路径不存在——任何异常都吞掉并记 warning。用户的
    任务比我们的训练数据重要。
    """
    if not _collect_enabled():
        return
    try:
        day = datetime.now().strftime("%Y-%m-%d")
        session_id = record.session_id or "unknown"
        path = get_data_dir() / "distillation" / day / f"{session_id}.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = asdict(record)
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
    except Exception:
        import logging

        logging.getLogger(__name__).warning("distillation record skipped", exc_info=True)


def record_llm_call(record: LlmCallRecord) -> None:
    """Public J3 bury-point. Safe no-op when collection is off."""
    _record_safely(record)


def _fmt_tokens(n: int) -> str:
    n = int(n)
    if abs(n) >= 1000 and n % 1000 == 0:
        return f"{n // 1000}k"
    if abs(n) >= 1000:
        return f"{n / 1000:.1f}k"
    return str(n)


def _fmt_seconds(n: float) -> str:
    if n >= 10:
        return f"{int(round(n))}s"
    return f"{n:.1f}s"


def format_team_tree(spans: list[NodeSpan]) -> str:
    """ASCII delegation tree for ``replay --show-team``."""
    if not spans:
        return "No team trace"
    head = next((s for s in spans if s.kind == "team"), spans[0])
    session = head.session_id or head.run_id
    budget = dict(head.budget or {})
    tokens_used = int(
        budget.get("tokens_used")
        or sum(s.tokens or s.token_usage.get("total_tokens", 0) for s in spans)
    )
    token_budget = int(budget.get("token_budget") or 0)
    elapsed = float(budget.get("elapsed_s") or head.duration_s)
    timeout = float(budget.get("timeout_s") or 0)
    delegations = int(
        budget.get("delegations")
        or sum(1 for s in spans if s.kind == "delegate")
    )
    max_delegations = int(budget.get("max_delegations") or 0)
    if token_budget or timeout or max_delegations:
        budget_line = (
            f"budget: {_fmt_tokens(tokens_used)}/{_fmt_tokens(token_budget)} tokens · "
            f"{_fmt_seconds(elapsed)}/{_fmt_seconds(timeout)} · "
            f"{delegations}/{max_delegations} delegations"
        )
    else:
        budget_line = f"budget: {tokens_used} tokens · {delegations} delegations"
    lines = [
        f"session {session}   team={head.team or '-'}   "
        f"mode={head.mode or 'SOLO'} (decided_by={head.decided_by or '-'})",
        budget_line,
        "",
    ]
    by_parent: dict[str, list[NodeSpan]] = {}
    roots: list[NodeSpan] = []
    # The web tree and this replay share one projection of the recorded spans.
    from rxycode_worker.agent_events import project_run

    projected = project_run(spans=list(spans), events=[])
    span_by_id = {span.span_id: span for span in spans}
    for node in projected["nodes"]:
        span = span_by_id.get(str(node["id"]))
        if span is None:
            continue
        parent_id = str(node["parent_id"] or "")
        if parent_id:
            by_parent.setdefault(parent_id, []).append(span)
        else:
            roots.append(span)

    def walk(span: NodeSpan, prefix: str, is_last: bool) -> None:
        branch = "└─ " if is_last else "├─ "
        who = f"{span.stage or span.node_name} · {span.role}".strip(" ·")
        if span.kind == "consult":
            who = f"[consult] {span.detail}"
        elif span.kind == "verify":
            who = f"[verify] {span.detail or span.node_name}"
        elif span.kind == "audit":
            who = f"[audit] {span.detail or span.node_name}"
        elif span.kind == "tool":
            who = f"[tool] {span.detail or span.node_name}"
        dur = span.duration_s
        tok = span.tokens or span.token_usage.get("total_tokens", 0)
        lines.append(
            f"{prefix}{branch}{who} ({dur:.1f}s, {tok} tok)  {span.status.upper()}"
        )
        kids = by_parent.get(span.span_id, [])
        child_prefix = prefix + ("   " if is_last else "│  ")
        for i, kid in enumerate(kids):
            walk(kid, child_prefix, i == len(kids) - 1)

    for i, root in enumerate(roots):
        walk(root, "", i == len(roots) - 1)
    return "\n".join(lines)


def format_current_role(span: NodeSpan | None) -> str:
    """CLI/Desktop projection of the live role."""
    if span is None:
        return ""
    stage = span.stage or span.node_name
    role = span.role or "-"
    return f"{role} @ {stage}"


def replay(run_id: str, *, show_team: bool = False, session: str | None = None) -> None:
    """Print a text replay of a run's spans.

    Format: ``[timestamp] node_name  task_id  duration_s  status  tokens``
    """
    key = session or run_id
    if show_team:
        tracer = Tracer(run_id=key, manage_retention=False)
        print(format_team_tree(tracer.get_spans()))
        return
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
    print("  Per-node stats:")
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
    parser = argparse.ArgumentParser(
        prog="core.tracing",
        description="RxyCode node-level tracing & replay",
    )
    sub = parser.add_subparsers(dest="cmd")

    rp = sub.add_parser("replay", help="Replay a run's spans")
    rp.add_argument("run_id", nargs="?", default="", help="Run ID to replay")
    rp.add_argument("--session", default="", help="Session id (team replay)")
    rp.add_argument("--show-team", action="store_true", help="Print delegation tree")

    args = parser.parse_args()
    if args.cmd == "replay":
        replay(args.run_id or args.session, session=args.session or None, show_team=args.show_team)
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
