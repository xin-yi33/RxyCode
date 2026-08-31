"""Deterministic local stress harness for the Muse Responses adapter.

This script performs no network I/O and reads no credentials. It measures the
RxyCode chunk-normalization boundary under concurrent streams; it is not a
model-quality, gateway-capacity, or regional-availability benchmark.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
from pathlib import Path
import sys
import time
import tracemalloc
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.providers.responses_adapter import (  # noqa: E402
    responses_stream_as_chat_chunks,
)


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, math.ceil(percentile * len(ordered)) - 1)
    return ordered[index]


async def _source(request_id: int, chunks: int):
    for index in range(chunks):
        await asyncio.sleep(0)
        yield SimpleNamespace(
            content=[{"type": "text", "text": "x", "index": index}],
            tool_call_chunks=[],
            usage_metadata=None,
            chunk_position=None,
        )
    yield SimpleNamespace(
        content=[],
        tool_call_chunks=[],
        usage_metadata={
            "input_tokens": request_id + 1,
            "output_tokens": chunks,
            "input_token_details": {"cache_read": request_id % 3},
            "output_token_details": {"reasoning": 0},
        },
        chunk_position="last",
        response_metadata={"status": "completed"},
    )


async def _run_one(request_id: int, chunks: int, semaphore: asyncio.Semaphore):
    started = time.perf_counter()
    text_length = 0
    terminal_count = 0
    usage_seen = False
    async with semaphore:
        async for chunk in responses_stream_as_chat_chunks(
            _source(request_id, chunks)
        ):
            text_length += len(chunk.choices[0].delta.content or "")
            terminal_count += int(bool(chunk._rxy_responses_terminal))
            usage_seen = usage_seen or chunk.usage is not None
    if text_length != chunks or terminal_count != 1 or not usage_seen:
        raise AssertionError(
            f"stream integrity failed for request {request_id}: "
            f"text={text_length}, terminal={terminal_count}, usage={usage_seen}"
        )
    return (time.perf_counter() - started) * 1000


async def _stage(concurrency: int, requests: int, chunks: int) -> dict:
    semaphore = asyncio.Semaphore(concurrency)
    before = {task for task in asyncio.all_tasks() if not task.done()}
    started = time.perf_counter()
    results = await asyncio.gather(
        *(_run_one(index, chunks, semaphore) for index in range(requests)),
        return_exceptions=True,
    )
    elapsed = time.perf_counter() - started
    errors = [str(result) for result in results if isinstance(result, BaseException)]
    latencies = [float(result) for result in results if not isinstance(result, BaseException)]
    after = {task for task in asyncio.all_tasks() if not task.done()}
    leaked_tasks = len(after - before)
    return {
        "concurrency": concurrency,
        "requests": requests,
        "chunks_per_request": chunks,
        "successes": len(latencies),
        "errors": len(errors),
        "error_samples": errors[:3],
        "elapsed_s": round(elapsed, 4),
        "throughput_requests_s": round(len(latencies) / elapsed, 2) if elapsed else 0.0,
        "latency_ms": {
            "p50": _percentile(latencies, 0.50),
            "p95": _percentile(latencies, 0.95),
            "p99": _percentile(latencies, 0.99),
        },
        "pending_task_leaks": leaked_tasks,
    }


async def _run(args: argparse.Namespace) -> dict:
    tracemalloc.start()
    stages = [
        await _stage(level, args.requests, args.chunks)
        for level in args.concurrency
    ]
    current_bytes, peak_bytes = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    passed = all(
        stage["errors"] == 0
        and stage["successes"] == stage["requests"]
        and stage["pending_task_leaks"] == 0
        for stage in stages
    )
    return {
        "kind": "rxycode-local-muse-responses-adapter",
        "network_used": False,
        "passed": passed,
        "total_requests": sum(stage["requests"] for stage in stages),
        "total_chunks": sum(
            stage["requests"] * (stage["chunks_per_request"] + 1)
            for stage in stages
        ),
        "memory": {
            "current_bytes": current_bytes,
            "peak_bytes": peak_bytes,
        },
        "stages": stages,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--requests", type=int, default=200)
    parser.add_argument("--chunks", type=int, default=32)
    parser.add_argument(
        "--concurrency", type=int, nargs="+", default=[1, 2, 4, 8, 16]
    )
    args = parser.parse_args()
    if args.requests <= 0 or args.chunks <= 0:
        parser.error("--requests and --chunks must be positive")
    if not args.concurrency or any(level <= 0 for level in args.concurrency):
        parser.error("--concurrency values must be positive")
    report = asyncio.run(_run(args))
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
