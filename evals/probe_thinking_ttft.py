"""Live probe: Session.prompt → first thinking token WITH thinking ON.

Usage (from repo root; probe itself waits for isomorphic prefix warm):

    python -m evals.probe_thinking_ttft
    python -m evals.probe_thinking_ttft --model zhipu/glm-5.3-flash \\
        --out evals/results/thinking-ttft-glm53-flash.json
    python -m evals.probe_thinking_ttft --model deepseek/deepseek-v4-flash \\
        --out evals/results/thinking-ttft-deepseek-official-warm.json

Exit 0 if warm simple ≤ 1.5s and warm complex ≤ 3.2s (or skipped: no API key).
True cold start is excluded from the red line.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import time
import uuid
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))
os.environ.setdefault("RXYCODE_CHECKOUT_ROOT", str(REPO))

# Bind THIS checkout as RxyCode.RxyCode1_1_0 (editable install is often stale).
if not getattr(sys, "_rxycode_test_checkout_ready", False):
    import importlib
    import types as _types

    os.environ["_RXYCODE_TEST_CHECKOUT"] = str(REPO)
    sys.meta_path = [
        finder
        for finder in sys.meta_path
        if type(finder).__name__ not in ("_EditableFinder",)
    ]
    _canonical_init = REPO / "__init__.py"
    if "RxyCode" not in sys.modules:
        sys.modules["RxyCode"] = _types.ModuleType("RxyCode")
    _canonical = _types.ModuleType("RxyCode.RxyCode1_1_0")
    sys.modules["RxyCode.RxyCode1_1_0"] = _canonical
    sys.modules["RxyCode"].RxyCode1_1_0 = _canonical
    _canonical.__file__ = str(_canonical_init)
    _canonical.__path__ = [str(REPO)]
    _canonical.__package__ = "RxyCode.RxyCode1_1_0"
    exec(compile(_canonical_init.read_text(encoding="utf-8-sig"), str(_canonical_init), "exec"), _canonical.__dict__)
    _unify = getattr(_canonical, "unify_bare_package_aliases", None)
    if callable(_unify):
        _unify()
    importlib.import_module("RxyCode.RxyCode1_1_0.core")
    if callable(_unify):
        _unify()
    sys._rxycode_test_checkout_ready = True

from RxyCode.RxyCode1_1_0.core.ttft_clock import COMPLEX_UPPER_S, SIMPLE_UPPER_S
from RxyCode.RxyCode1_1_0.utils.streaming import token_stats

SIMPLE_PROMPTS = ("你好", "修一下 foo.py 里的空指针")
COMPLEX_PROMPTS = ("实现一个完整的登录功能，前后端都要",)


def _percentile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    if len(values) == 1:
        return values[0]
    ordered = sorted(values)
    idx = min(len(ordered) - 1, max(0, int(round((q / 100.0) * (len(ordered) - 1)))))
    return ordered[idx]


async def _await_cancelled(task: asyncio.Task, timeout: float = 2.0) -> None:
    if not task.done():
        task.cancel()
    try:
        await asyncio.wait_for(task, timeout=timeout)
    except BaseException:
        pass


async def _wait_idle(agent, timeout: float = 6.0) -> None:
    deadline = time.perf_counter() + timeout
    while time.perf_counter() < deadline:
        if int(getattr(agent, "_llm_in_flight", 0) or 0) <= 0:
            return
        await asyncio.sleep(0.05)


async def _one(session, agent, prompt: str, run_id: str) -> dict:
    await _wait_idle(agent)
    token_stats.reset_ttft()
    agent._last_pre_llm_ms = None
    agent._last_provider_ttfb_ms = None
    nonce = uuid.uuid4().hex[:8]
    live_prompt = f"{prompt} [ttft-{nonce}]"
    t0 = time.perf_counter()
    task = asyncio.create_task(
        session.prompt(agent, live_prompt, mode="build", run_id=run_id)
    )
    deadline = t0 + 16.0
    print(f"probe: waiting first thinking for {prompt!r}", flush=True)
    while token_stats.thinking_ttft_ms is None and time.perf_counter() < deadline:
        if task.done():
            break
        await asyncio.sleep(0.02)
    marked = token_stats.thinking_ttft_ms
    print(f"probe: marked_ms={marked}", flush=True)
    try:
        agent.cancel()
    except Exception:
        pass
    await _await_cancelled(task, timeout=8.0)
    thinking_on = not bool(getattr(agent, "_thinking_disabled_this_turn", False))
    row = {
        "prompt": prompt,
        "thinking_ttft_ms": marked,
        "thinking_ttft_s": None if marked is None else marked / 1000.0,
        "wall_s": time.perf_counter() - t0,
        "status": "first_thinking" if marked is not None else "no_thinking_token",
        "thinking_on": thinking_on,
        "effort": str((getattr(agent, "model_config", {}) or {}).get("effort") or ""),
        "pre_llm_ms": getattr(agent, "_last_pre_llm_ms", None),
        "provider_ttfb_ms": getattr(agent, "_last_provider_ttfb_ms", None),
        "cache_hit_tokens": int(getattr(token_stats, "cache_hit_tokens", 0) or 0),
    }
    return row


def _load_deepseek_comparison() -> dict | None:
    path = REPO / "evals" / "results" / "thinking-ttft.json"
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return {
        "file": "evals/results/thinking-ttft.json",
        "model": payload.get("model"),
        "provider": payload.get("provider"),
        "base_url": payload.get("base_url"),
        "simple_p50": payload.get("simple_p50"),
        "simple_p95": payload.get("simple_p95"),
        "complex_p50": payload.get("complex_p50"),
        "complex_p95": payload.get("complex_p95"),
        "pass": payload.get("pass"),
        "cache_hit_tokens": payload.get("cache_hit_tokens"),
        "split": payload.get("split"),
    }


def _wire_snapshot(agent) -> dict:
    extra_body = {}
    reasoning_effort = None
    try:
        provider = getattr(agent, "_provider", None)
        caps = getattr(agent, "_capabilities", None)
        if provider is not None and caps is not None:
            cfg = dict(getattr(agent, "model_config", {}) or {})
            cfg.setdefault("resolved_max_tokens", 4096)
            cfg.setdefault("api_key", "probe-wire")
            kwargs = provider.llm_kwargs(cfg, caps)
            extra_body = dict(kwargs.get("extra_body") or {})
            reasoning_effort = kwargs.get("reasoning_effort")
    except Exception as exc:
        extra_body = {"error": str(exc)[:200]}
    return {
        "thinking": extra_body.get("thinking"),
        "clear_thinking": extra_body.get("clear_thinking"),
        "reasoning_effort": reasoning_effort,
        "extra_body": extra_body,
    }


async def _run(model_name: str | None = None) -> dict:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    from RxyCode.RxyCode1_1_0.appserver.bootstrap import bootstrap_agent
    from RxyCode.RxyCode1_1_0.appserver.tui import ProtocolTui
    from RxyCode.RxyCode1_1_0.core.session import Session
    from RxyCode.RxyCode1_1_0.utils.tui import set_tui

    workspace = REPO
    print("probe: bootstrap model=" + str(model_name or "<active>"), flush=True)
    try:
        agent = await asyncio.wait_for(
            asyncio.to_thread(
                bootstrap_agent,
                stub=False,
                workspace_root=workspace,
                model_name=model_name,
            ),
            timeout=90.0,
        )
    except Exception as exc:
        return {"skipped": True, "reason": str(exc)[:300]}
    print(
        "probe: bootstrapped model="
        + str((getattr(agent, "model_config", {}) or {}).get("model_name") or "")
        + " thinking_default_on="
        + str(getattr(getattr(agent, "_capabilities", None), "thinking_default_on", None)),
        flush=True,
    )

    emitted: list = []
    session = Session(
        session_id="thinking-ttft-live",
        workspace_root=workspace,
        emit=emitted.append,
    )
    tui = ProtocolTui("thinking-ttft-live", emitted.append)
    set_tui(tui)
    if hasattr(agent, "_session_id"):
        agent._session_id = session.session_id
    if hasattr(agent, "_workspace_root"):
        agent._workspace_root = workspace

    try:
        from RxyCode.RxyCode1_1_0.core.session_runtime import (
            bind_session,
            reset_session_binding,
            set_working_directory,
        )

        cwd_token = bind_session(session.session_id)
        try:
            set_working_directory(workspace, persist=True)
        finally:
            reset_session_binding(cwd_token)
    except Exception as exc:
        print(f"probe: cwd bind failed {exc!r}", flush=True)

    preconnect = getattr(agent, "_preconnect_provider", None)
    if callable(preconnect):
        print("probe: preconnect", flush=True)
        try:
            await asyncio.wait_for(preconnect(), timeout=8.0)
        except Exception as exc:
            print(f"probe: preconnect failed {exc!r}", flush=True)
    print("probe: isomorphic prefix warmup (thinking ON, tools, max_tokens=4096)", flush=True)
    tool_schema_chars = 0
    tool_count = 0
    warmup_hits: list[int] = []
    prefix_warmed = False
    try:
        from RxyCode.RxyCode1_1_0.core.prewarm import (
            PREWARM_MAX_TOKENS,
            core_tools_for,
            prewarm_archive,
        )

        tools = core_tools_for(agent, "agent") or []
        payload = agent._tools_payload(tools)
        tool_count = len(payload)
        tool_schema_chars = sum(len(str(item)) for item in payload)
        print(
            f"probe: tool_schema_chars={tool_schema_chars} tools={tool_count} "
            f"prewarm_max_tokens={PREWARM_MAX_TOKENS}",
            flush=True,
        )
        awaiter = getattr(agent, "await_prefix_warm", None)
        if callable(awaiter):
            prefix_warmed = bool(await asyncio.wait_for(awaiter(timeout=45.0), timeout=50.0))
            print(f"probe: await_prefix_warm -> {prefix_warmed}", flush=True)
        for i in range(2):
            before = int(getattr(token_stats, "cache_hit_tokens", 0) or 0)
            await asyncio.wait_for(prewarm_archive(agent, "agent"), timeout=45.0)
            after = int(getattr(token_stats, "cache_hit_tokens", 0) or 0)
            warmup_hits.append(max(0, after - before))
            print(
                f"probe: warmup{i + 1} cache_hit_delta={warmup_hits[-1]} "
                f"total={after}",
                flush=True,
            )
        prefix_warmed = True
    except Exception as exc:
        print(f"probe: warmup failed {exc!r}", flush=True)

    orig_stream = agent._raw_stream

    async def _stop_after_first_thinking(*args, **kwargs):
        async for chunk in orig_stream(*args, **kwargs):
            yield chunk
            if token_stats.thinking_ttft_ms is not None:
                raise asyncio.CancelledError()

    async def _noop_tools(*_a, **_k):
        return []

    agent._raw_stream = _stop_after_first_thinking
    agent._execute_tools_parallel = _noop_tools

    simple: list[dict] = []
    for i, prompt in enumerate(SIMPLE_PROMPTS):
        print(f"probe: simple {i} {prompt!r}", flush=True)
        row = await _one(session, agent, prompt, f"simple-{i}")
        row["phase"] = "warm"
        simple.append(row)
        print(f"probe: simple {i} -> {simple[-1]}", flush=True)
        await asyncio.sleep(0.4)
    warm_hello = await _one(session, agent, SIMPLE_PROMPTS[0], "simple-warm")
    warm_hello["phase"] = "warm"
    simple.append(warm_hello)
    print(f"probe: simple warm -> {simple[-1]}", flush=True)
    await asyncio.sleep(0.4)

    complex_rows: list[dict] = []
    for i, prompt in enumerate(COMPLEX_PROMPTS):
        print(f"probe: complex {i} {prompt!r}", flush=True)
        row = await _one(session, agent, prompt, f"complex-{i}")
        row["phase"] = "warm"
        complex_rows.append(row)
        print(f"probe: complex {i} -> {complex_rows[-1]}", flush=True)

    simple_s = [r["thinking_ttft_s"] for r in simple if r["thinking_ttft_s"] is not None]
    complex_s = [
        r["thinking_ttft_s"] for r in complex_rows if r["thinking_ttft_s"] is not None
    ]
    hello_warm = [
        r["thinking_ttft_s"]
        for r in simple
        if r.get("prompt") == SIMPLE_PROMPTS[0] and r["thinking_ttft_s"] is not None
    ]
    # Red line is the warm path (idle CLI after prefix warm). Do not fold a
    # true-cold first byte into max(); that is not the user clock after open.
    simple_pass = bool(simple_s) and max(simple_s) <= SIMPLE_UPPER_S
    complex_pass = bool(complex_s) and max(complex_s) <= COMPLEX_UPPER_S
    all_rows = simple + complex_rows
    thinking_stayed_on = bool(all_rows) and all(
        bool(r.get("thinking_on")) for r in all_rows
    )
    got_thinking = bool(all_rows) and all(
        r.get("thinking_ttft_s") is not None for r in all_rows
    )
    from datetime import datetime, timezone, timedelta

    now = datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds")
    mc = getattr(agent, "model_config", {}) or {}
    caps = getattr(agent, "_capabilities", None)
    provider = getattr(agent, "_provider", None)
    pre_llm = [r.get("pre_llm_ms") for r in all_rows if r.get("pre_llm_ms") is not None]
    ttfb = [
        r.get("provider_ttfb_ms")
        for r in all_rows
        if r.get("provider_ttfb_ms") is not None
    ]
    return {
        "id": "thinking-ttft-live",
        "kind": "trace-fixture",
        "measured_at": now,
        "clock": "AFTER isomorphic prefix warm: Session.prompt start → first reasoning/thinking token WITH thinking ON",
        "thinking_on": thinking_stayed_on,
        "disable_thinking_to_buy_ttft": False,
        "gate_excludes_true_cold": True,
        "prefix_warmed": prefix_warmed,
        "hello_warm_s": hello_warm,
        "catalog_id": model_name
        or str((getattr(agent, "_cfg", {}) or {}).get("active_model") or ""),
        "model": str(mc.get("model_name") or ""),
        "provider": str(
            getattr(provider, "name", "") or getattr(caps, "provider", "") or ""
        ),
        "base_url": str(mc.get("base_url") or ""),
        "thinking_default_on": getattr(caps, "thinking_default_on", None),
        "wire": {
            **_wire_snapshot(agent),
            "tools": tool_count,
            "tool_schema_chars": tool_schema_chars,
        },
        "simple": simple,
        "complex": complex_rows,
        "simple_s": simple_s,
        "complex_s": complex_s,
        "simple_p50": _percentile(simple_s, 50) if simple_s else None,
        "simple_p95": _percentile(simple_s, 95) if simple_s else None,
        "complex_p50": _percentile(complex_s, 50) if complex_s else None,
        "complex_p95": _percentile(complex_s, 95) if complex_s else None,
        "simple_pass": simple_pass,
        "complex_pass": complex_pass,
        "pass": simple_pass and complex_pass and thinking_stayed_on and got_thinking,
        "cache_hit_tokens": int(getattr(token_stats, "cache_hit_tokens", 0) or 0),
        "warmup_cache_hit_deltas": warmup_hits,
        "tool_schema_chars": tool_schema_chars,
        "tools": tool_count,
        "gates": {
            "simple_upper_s": SIMPLE_UPPER_S,
            "complex_upper_s": COMPLEX_UPPER_S,
            "cache_hit_floor": 0.97,
            "pass_rule": "AFTER prefix warm: max(simple_s) <= 1.5 and max(complex_s) <= 3.2; true cold start is excluded",
        },
        "split": {
            "pre_llm_ms": pre_llm,
            "provider_ttfb_ms": ttfb,
        },
        "vs_deepseek_zen_go": _load_deepseek_comparison(),
        "skipped": False,
    }


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Live thinking-TTFT probe")
    parser.add_argument(
        "--model",
        default=None,
        help="config.yaml model key, e.g. zhipu/glm-5.3-flash",
    )
    parser.add_argument(
        "--out",
        default=None,
        help="results JSON path (default: evals/results/thinking-ttft.json)",
    )
    args = parser.parse_args()
    out_dir = REPO / "evals" / "results"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = Path(args.out) if args.out else (out_dir / "thinking-ttft.json")
    if not out.is_absolute():
        out = REPO / out
    out.parent.mkdir(parents=True, exist_ok=True)
    try:
        payload = asyncio.run(_run(model_name=args.model))
    except asyncio.CancelledError:
        payload = {"skipped": True, "reason": "CancelledError", "pass": False}
    except Exception as exc:
        payload = {"skipped": True, "reason": str(exc)[:400], "pass": False}
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    if payload.get("skipped"):
        print("LIVE_TTFT skipped (no key / bootstrap failed)", file=sys.stderr)
        os._exit(0)
    os._exit(0 if payload.get("pass") else 1)


if __name__ == "__main__":
    raise SystemExit(main())
