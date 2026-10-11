"""Validated policy for retaining and recycling idle session workers."""

from __future__ import annotations

import math
import os
from dataclasses import dataclass
from typing import Mapping


DEFAULT_WORKER_IDLE_SECONDS = 600.0
DEFAULT_MAX_IDLE_WORKERS = 2
_MAX_IDLE_WORKERS = 1024


def _idle_seconds(raw: object, default: float) -> float:
    if raw is None or not str(raw).strip():
        return default
    try:
        parsed = float(raw)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(parsed) or parsed < 0:
        return default
    return parsed


def _max_idle_workers(raw: object, default: int) -> int:
    if raw is None or not str(raw).strip():
        return default
    try:
        parsed = int(str(raw).strip(), 10)
    except (TypeError, ValueError):
        return default
    if parsed < 0 or parsed > _MAX_IDLE_WORKERS:
        return default
    return parsed


@dataclass(frozen=True)
class IdleWorkerPolicy:
    """TTL and count bound applied only to workers proven idle."""

    idle_seconds: float = DEFAULT_WORKER_IDLE_SECONDS
    max_idle_workers: int = DEFAULT_MAX_IDLE_WORKERS

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "IdleWorkerPolicy":
        values = os.environ if env is None else env
        return cls(
            idle_seconds=_idle_seconds(
                values.get("RXYCODE_WORKER_IDLE_SECONDS"),
                DEFAULT_WORKER_IDLE_SECONDS,
            ),
            max_idle_workers=_max_idle_workers(
                values.get("RXYCODE_MAX_IDLE_WORKERS"),
                DEFAULT_MAX_IDLE_WORKERS,
            ),
        )
