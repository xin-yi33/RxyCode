# core/tracing.py - Node-Level Tracing & Observability

## What Is This Module?
The tracing module provides node-level execution tracing for RxyCode's LangGraph pipeline. It collects per-node timing spans (start/end, token usage, status), persists them as JSONL for each run, and provides a replay CLI with p50/p99 latency statistics per node.

**Design stitched from:**
- **OpenHands** (MIT): trajectory serialization pattern — event stream -> structured records -> replay

## Architecture

### Key Files
| File | Purpose |
|------|---------|
| `core/tracing.py` | All tracing logic: `NodeSpan`, `Tracer`, `replay()`, CLI `main()` |

### Core Code: NodeSpan

```python
@dataclass
class NodeSpan:
    node_name: str          # "goal_planner" / "executor" / etc.
    task_id: str            # associated task ID (empty for non-task nodes)
    run_id: str             # run identifier
    start_ts: float         # unix timestamp
    end_ts: float           # unix timestamp (0 if not finished)
    token_usage: dict       # {"prompt_tokens": N, "completion_tokens": M, "total_tokens": K}
    status: str             # "ok" / "error" / "timeout" / "cancelled"
    error_msg: str          # empty if status == "ok"
```

**Properties:**
- `duration_s` — Elapsed seconds (0.0 if span has not finished)
- `to_dict()` / `from_dict()` — JSON/JSONL serialization

### Core Code: Tracer

The `Tracer` class collects NodeSpans for a single run and persists to JSONL.

**Key Methods:**
- `start_span(node_name, task_id="") -> NodeSpan`: Start timing a node execution. Returns a span with `end_ts=0` (not yet finished). The caller should pass the returned span to `end_span()`.
- `end_span(span, status="ok", token_usage=None, error_msg="") -> None`: End a span, mutate it in place (set end_ts, status, token_usage, error_msg), and append one JSON line to the trace file.
- `get_spans() -> list[NodeSpan]`: Load all spans from the trace JSONL file. Always reads from disk so it sees persisted data.
- `summary() -> dict`: Per-node stats: count, total_duration, p50, p99, total_tokens, prompt_tokens, completion_tokens. Keyed by node_name.

**Global Singleton:**
- `get_tracer() -> Tracer`: Return the process-global Tracer singleton (lazy-init)
- `reset_tracer(run_id=None) -> Tracer`: Discard the current global Tracer and create a fresh one. Useful for tests or when starting a new run with an explicit run_id.

### Percentile Calculation

`_percentile(sorted_vals, pct)` — Linear-interpolation percentile (like numpy's default). `pct` is a fraction in [0, 1]. Returns 0.0 for an empty list.

## Work Flow

1. At the start of a pipeline run, `reset_tracer()` creates a fresh `Tracer` with a new `run_id`
2. Before each graph node executes, `tracer.start_span(node_name, task_id)` is called
3. After the node finishes, `tracer.end_span(span, status=..., token_usage=...)` is called, which:
   - Sets `end_ts` to the current time
   - Updates status, token_usage, and error_msg
   - Appends one JSON line to `~/.rxycode/logs/traces/{run_id}.jsonl`
4. After the run, `tracer.summary()` provides per-node p50/p99 latency statistics
5. The replay CLI can reconstruct the full execution timeline from the JSONL file

Tool spans classify returned failure sentinels as well as raised exceptions, so
blocked/rejected/error results cannot be persisted with an `ok` status.

## CLI

```bash
# Replay a run's execution timeline
python -m core.tracing replay <run_id>
```

**Output format:**
```
========================================================================
  Run: <run_id>   Spans: <N>
========================================================================
Timestamp            Node               Task         Dur(s)  Status   Tokens
------------------------------------------------------------------------
2025-01-15 10:30:00  goal_planner       -             0.234  ok          512
2025-01-15 10:30:00  decomposer         -             0.567  ok         1200
2025-01-15 10:30:01  executor           task-1        1.234  ok         3400
...
------------------------------------------------------------------------
  Per-node stats:
    goal_planner      count=1  p50=0.234s  p99=0.234s  tokens=512
    decomposer        count=1  p50=0.567s  p99=0.567s  tokens=1200
    executor          count=3  p50=1.234s  p99=2.100s  tokens=10200
========================================================================
```

## Data Location

- Trace files: `~/.rxycode/logs/traces/{run_id}.jsonl`
- Each line is a JSON object (NodeSpan.to_dict())
- Files are append-only during a run

## Dependencies
- **Internal**: `config/settings.py` (`get_data_dir()` for trace file location)
- **External**: Standard library only (`json`, `time`, `uuid`, `dataclasses`, `pathlib`)
- **Stitched from**: OpenHands (MIT) trajectory serialization pattern
