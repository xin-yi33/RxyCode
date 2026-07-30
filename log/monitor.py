"""Thread-safe, content-free aggregate metrics for agent runs and evidence."""

from __future__ import annotations

from collections import Counter, OrderedDict
from threading import Lock
from typing import Any


def _evidence_counts(evidence: Any) -> tuple[int, int, int, int]:
    status = getattr(evidence, "status", None)
    executed = getattr(evidence, "executed", None)
    if isinstance(evidence, dict):
        status = evidence.get("status")
        executed = evidence.get("executed")
        artifacts = evidence.get("artifacts") or []
    else:
        artifacts = getattr(evidence, "artifacts", None) or []

    tools_failed = int(status != "succeeded" or executed is not True)
    artifacts_failed = 0
    for artifact in artifacts:
        if isinstance(artifact, dict):
            exists = artifact.get("exists")
            valid = artifact.get("valid")
        else:
            exists = getattr(artifact, "exists", None)
            valid = getattr(artifact, "valid", None)
        artifacts_failed += int(exists is not True or valid is False)
    return 1, tools_failed, len(artifacts), artifacts_failed


class RunMonitor:
    """Aggregate statuses and verified outputs without retaining user content."""

    _MAX_TRACKED_RUNS = 1024

    def __init__(self) -> None:
        self._lock = Lock()
        self.reset()

    def reset(self) -> None:
        with self._lock:
            self._counts: Counter[str] = Counter()
            self._total_duration_s = 0.0
            self._total_steps = 0
            self._total_replans = 0
            self._failure_attribution: Counter[str] = Counter()
            self._token_usage: Counter[str] = Counter()
            self._last_run: dict[str, object] | None = None
            self._runs: OrderedDict[str, dict[str, object]] = OrderedDict()
            self._evidence_by_run: OrderedDict[str, Counter[str]] = OrderedDict()
            self._evidence_totals: Counter[str] = Counter()

    def _trim(self, mapping: OrderedDict[str, Any]) -> None:
        while len(mapping) > self._MAX_TRACKED_RUNS:
            mapping.popitem(last=False)

    def record_evidence(self, run_id: str, evidence: Any) -> None:
        """Record only pass/fail counts for one tool result and its artifacts."""
        tools, tools_failed, artifacts, artifacts_failed = _evidence_counts(evidence)
        with self._lock:
            counts = self._evidence_by_run.setdefault(run_id, Counter())
            self._evidence_by_run.move_to_end(run_id)
            counts["tools_total"] += tools
            counts["tools_failed"] += tools_failed
            counts["artifacts_total"] += artifacts
            counts["artifacts_failed"] += artifacts_failed
            self._evidence_totals.update({
                "tools_total": tools,
                "tools_failed": tools_failed,
                "artifacts_total": artifacts,
                "artifacts_failed": artifacts_failed,
            })
            self._trim(self._evidence_by_run)
            # Attach evidence to the authoritative run record (if it already
            # exists) rather than the volatile ``_last_run`` snapshot, so
            # interleaved runs cannot corrupt each other's tallies.
            run_record = self._runs.get(run_id)
            if run_record is not None:
                self._add_evidence_to_run(run_record, counts)

    @staticmethod
    def _add_evidence_to_run(
        record: dict[str, object],
        counts: Counter[str],
    ) -> None:
        record["tool_evidence"] = {
            "total": counts["tools_total"],
            "failed": counts["tools_failed"],
        }
        record["artifact_evidence"] = {
            "total": counts["artifacts_total"],
            "failed": counts["artifacts_failed"],
        }

    @staticmethod
    def _normalise_metrics(metrics: dict[str, Any] | None) -> dict[str, Any]:
        raw = metrics or {}
        failures = raw.get("failure_attribution") or {}
        tokens = raw.get("token_usage") or {}
        return {
            "steps": max(0, int(raw.get("steps", 0) or 0)),
            "replans": max(0, int(raw.get("replans", 0) or 0)),
            "failure_attribution": {
                str(key): max(0, int(value or 0))
                for key, value in failures.items()
                if int(value or 0) > 0
            },
            "token_usage": {
                "input_tokens": max(
                    0,
                    int(tokens.get("input_tokens", tokens.get("prompt_tokens", 0)) or 0),
                ),
                "output_tokens": max(
                    0,
                    int(
                        tokens.get(
                            "output_tokens",
                            tokens.get("completion_tokens", 0),
                        )
                        or 0
                    ),
                ),
                "total_tokens": max(0, int(tokens.get("total_tokens", 0) or 0)),
            },
        }

    def _remove_metrics(self, record: dict[str, object]) -> None:
        self._total_steps -= int(record.get("steps", 0) or 0)
        self._total_replans -= int(record.get("replans", 0) or 0)
        self._subtract_prune(self._failure_attribution, record.get("failure_attribution", {}))
        self._subtract_prune(self._token_usage, record.get("token_usage", {}))

    @staticmethod
    def _subtract_prune(counter: Counter[str], values: dict[str, Any]) -> None:
        """Subtract run-contributed metric counts, then drop any non-positive
        drift so a snapshot never reports negative aggregation values."""
        counter.subtract({
            k: int(v) for k, v in (values or {}).items() if int(v or 0) != 0
        })
        for key in [k for k, v in counter.items() if v <= 0]:
            del counter[key]

    def record(
        self,
        run_id: str,
        status: str,
        duration_s: float,
        *,
        metrics: dict[str, Any] | None = None,
    ) -> None:
        """Upsert a terminal run; duplicate observers share the same run ID."""
        duration = max(0.0, float(duration_s))
        with self._lock:
            previous = self._runs.get(run_id)
            previous_has_metrics = bool(
                previous
                and any(
                    key in previous
                    for key in (
                        "steps",
                        "replans",
                        "failure_attribution",
                        "token_usage",
                    )
                )
            )
            metric_source = (
                previous if metrics is None and previous_has_metrics else metrics
            )
            normalised = self._normalise_metrics(metric_source)
            if previous is not None:
                previous_status = str(previous["status"])
                self._counts[previous_status] -= 1
                if self._counts[previous_status] <= 0:
                    del self._counts[previous_status]
                self._total_duration_s -= float(previous["duration_s"])
                self._remove_metrics(previous)

            record: dict[str, object] = {
                "run_id": run_id,
                "status": status,
                "duration_s": round(duration, 6),
            }
            if metrics is not None or previous_has_metrics:
                record.update(normalised)
            evidence_counts = self._evidence_by_run.get(run_id)
            if evidence_counts:
                self._add_evidence_to_run(record, evidence_counts)

            self._counts[status] += 1
            self._total_duration_s += duration
            self._total_steps += normalised["steps"]
            self._total_replans += normalised["replans"]
            self._failure_attribution.update(normalised["failure_attribution"])
            self._token_usage.update(normalised["token_usage"])
            self._runs[run_id] = record
            self._runs.move_to_end(run_id)
            self._trim(self._runs)
            self._last_run = record

    def snapshot(self) -> dict[str, object]:
        with self._lock:
            total = sum(self._counts.values())
            return {
                "total_runs": total,
                "status_counts": dict(self._counts),
                "total_duration_s": round(self._total_duration_s, 6),
                "average_duration_s": (
                    round(self._total_duration_s / total, 6) if total else 0.0
                ),
                "success_rate": (
                    round(self._counts["succeeded"] / total, 6) if total else 0.0
                ),
                "average_steps": (
                    round(self._total_steps / total, 6) if total else 0.0
                ),
                "average_replans": (
                    round(self._total_replans / total, 6) if total else 0.0
                ),
                "failure_attribution": dict(self._failure_attribution),
                "token_usage": {
                    "input_tokens": self._token_usage["input_tokens"],
                    "output_tokens": self._token_usage["output_tokens"],
                    "total_tokens": self._token_usage["total_tokens"],
                },
                "tool_evidence": {
                    "total": self._evidence_totals["tools_total"],
                    "failed": self._evidence_totals["tools_failed"],
                },
                "artifact_evidence": {
                    "total": self._evidence_totals["artifacts_total"],
                    "failed": self._evidence_totals["artifacts_failed"],
                },
                "last_run": dict(self._last_run) if self._last_run else None,
            }


run_monitor = RunMonitor()
