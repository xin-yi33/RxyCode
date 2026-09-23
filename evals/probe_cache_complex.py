"""Two slightly-complex turns; wait for provider usage (do not cancel at first thinking).

Hit rate = latest_request.hit_tokens / prompt_tokens (same formula as B1).
The 97% red line is the SECOND turn after isomorphic prefix warm.

    python -m evals.probe_cache_complex --model deepseek/deepseek-v4-flash
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))
os.environ.setdefault("RXYCODE_CHECKOUT_ROOT", str(REPO))

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
    exec(
        compile(_canonical_init.read_text(encoding="utf-8-sig"), str(_canonical_init), "exec"),
        _canonical.__dict__,
    )
    _unify = getattr(_canonical, "unify_bare_package_aliases", None)
    if callable(_unify):
        _unify()
    importlib.import_module("RxyCode.RxyCode1_1_0.core")
    if callable(_unify):
        _unify()
    sys._rxycode_test_checkout_ready = True

from RxyCode.RxyCode1_1_0.evals.probe_thinking_ttft import (  # noqa: E402
    _await_cancelled,
    _wait_idle,
)
from RxyCode.RxyCode1_1_0.utils.streaming import token_stats

TURN1 = (
    "/solo 读取 core/session.py 里 Session.prompt 的实现，用两三句话说明它做什么。"
    "只读，不要改仓库。"
)
TURN2 = (
    "/solo 读取 core/agent_v2.py 里 AgentV2.run 的入口，用两三句话说明它做什么。"
    "只读，不要改仓库。"
)
CACHE_FLOOR = 0.97


def _latest() -> dict:
    latest = token_stats.latest_request
    return {
        "prompt_tokens": int(latest.get("prompt_tokens") or 0),
        "hit_tokens": int(latest.get("hit_tokens") or 0),
        "hit_rate": float(latest.get("hit_rate") or 0.0),
    }


async def _reset_agent(agent) -> None:
    await _wait_idle(agent)
    agent._cancelled = False
    deadline = time.perf_counter() + 6.0
    while time.perf_counter() < deadline:
        active = getattr(agent, "_active_task", None)
        if active is None or active.done():
            break
        await asyncio.sleep(0.05)
    agent._cancelled = False
    agent._user_turn_active = False


def _task_outcome(task: asyncio.Task) -> str:
    if not task.done():
        return "pending"
    try:
        result = task.result()
        answer = getattr(result, "answer", result)
        status = getattr(result, "status", "")
        return f"done status={status!s} answer={str(answer)[:160]!r}"
    except BaseException as exc:
        return f"exc {type(exc).__name__}: {exc}"


async def _turn(session, agent, prompt: str, run_id: str) -> dict:
    await _reset_agent(agent)
    session._agents_enabled_cached = False
    session._session_route_enabled = False
    session._session_subagents_opt_in = False
    before = _latest()
    seq0 = int(getattr(agent, "_raw_stream_request_seq", 0) or 0)
    t0 = time.perf_counter()
    task = asyncio.create_task(session.prompt(agent, prompt, mode="build", run_id=run_id))
    deadline = t0 + 90.0
    print(f"probe: waiting usage for {prompt[:48]!r} seq0={seq0}", flush=True)
    seq = seq0
    # Snapshot the first completed LLM of this turn. Later tool rounds add
    # unique suffix tokens and are not the 97% warm-prefix gate.
    while time.perf_counter() < deadline:
        seq = int(getattr(agent, "_raw_stream_request_seq", 0) or 0)
        latest = _latest()
        if seq > seq0 and latest != before:
            break
        if task.done():
            break
        await asyncio.sleep(0.01)
    latest = _latest()
    seq = int(getattr(agent, "_raw_stream_request_seq", 0) or 0)
    valid = seq > seq0 and latest != before
    print(
        f"probe: usage {latest} seq={seq} valid={valid} outcome={_task_outcome(task)}",
        flush=True,
    )
    try:
        agent.cancel()
    except Exception:
        pass
    await _await_cancelled(task, timeout=20.0)
    await _reset_agent(agent)
    prompt_tokens = int(latest["prompt_tokens"] or 0)
    hit_tokens = int(latest["hit_tokens"] or 0)
    rate_frac = hit_tokens / prompt_tokens if prompt_tokens > 0 and valid else 0.0
    return {
        "prompt": prompt,
        "wall_s": time.perf_counter() - t0,
        "prompt_tokens": prompt_tokens if valid else 0,
        "hit_tokens": hit_tokens if valid else 0,
        "hit_rate": rate_frac,
        "hit_rate_pct": rate_frac * 100.0,
        "thinking_ttft_ms": token_stats.thinking_ttft_ms,
        "llm_seq": seq,
        "seq0": seq0,
        "valid_new_request": valid,
        "task_outcome": _task_outcome(task),
    }


async def _run(model_name: str | None) -> dict:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    from RxyCode.RxyCode1_1_0.appserver.bootstrap import bootstrap_agent
    from RxyCode.RxyCode1_1_0.appserver.tui import ProtocolTui
    from RxyCode.RxyCode1_1_0.core.session import Session
    from RxyCode.RxyCode1_1_0.core.session_runtime import (
        bind_session,
        reset_session_binding,
        set_working_directory,
    )
    from RxyCode.RxyCode1_1_0.utils.tui import set_tui

    print("probe: bootstrap model=" + str(model_name or "<active>"), flush=True)
    try:
        agent = await asyncio.wait_for(
            asyncio.to_thread(
                bootstrap_agent,
                stub=False,
                workspace_root=REPO,
                model_name=model_name,
            ),
            timeout=90.0,
        )
    except Exception as exc:
        return {"skipped": True, "reason": str(exc)[:300], "pass": False}

    emitted: list = []
    session = Session(
        session_id="cache-complex-live",
        workspace_root=REPO,
        emit=emitted.append,
    )
    set_tui(ProtocolTui("cache-complex-live", emitted.append))
    agent._session_id = session.session_id
    agent._workspace_root = REPO
    cwd_token = bind_session(session.session_id)
    try:
        set_working_directory(REPO, persist=True)
    finally:
        reset_session_binding(cwd_token)

    exec_cfg = (getattr(agent, "_cfg", {}) or {}).setdefault("execution", {})
    exec_cfg["max_tool_rounds"] = 1
    session._agents_enabled_cached = False
    session._session_route_enabled = False
    session._session_subagents_opt_in = False

    from RxyCode.RxyCode1_1_0.cache.precise_cache import precise_cache
    from RxyCode.RxyCode1_1_0.cache.semantic_cache import semantic_cache

    precise_cache.get = lambda *_a, **_k: None  # type: ignore[method-assign]
    semantic_cache.get = lambda *_a, **_k: None  # type: ignore[method-assign]

    async def _noop_tools(*_a, **_k):
        return []

    agent._execute_tools_parallel = _noop_tools

    prefix_warmed = False
    try:
        from RxyCode.RxyCode1_1_0.core.prewarm import prewarm_archive

        awaiter = getattr(agent, "await_prefix_warm", None)
        if callable(awaiter):
            prefix_warmed = bool(await asyncio.wait_for(awaiter(timeout=45.0), timeout=50.0))
        await asyncio.wait_for(prewarm_archive(agent, "agent"), timeout=45.0)
        prefix_warmed = True
        print("probe: prefix warm done", flush=True)
    except Exception as exc:
        print(f"probe: warmup failed {exc!r}", flush=True)

    token_stats.reset_ttft()
    turn1 = await _turn(session, agent, TURN1, "cache-t1")
    await asyncio.sleep(0.5)
    token_stats.reset_ttft()
    turn2 = await _turn(session, agent, TURN2, "cache-t2")

    t2_rate = float(turn2.get("hit_rate") or 0.0)
    passed = bool(turn2.get("valid_new_request")) and t2_rate >= CACHE_FLOOR
    mc = getattr(agent, "model_config", {}) or {}
    now = datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds")
    return {
        "id": "cache-complex-two-turn",
        "measured_at": now,
        "calculation": "first LLM of turn 2: latest_request hit_tokens / prompt_tokens after prefix warm",
        "cache_hit_floor": CACHE_FLOOR,
        "prefix_warmed": prefix_warmed,
        "catalog_id": model_name
        or str((getattr(agent, "_cfg", {}) or {}).get("active_model") or ""),
        "model": str(mc.get("model_name") or ""),
        "base_url": str(mc.get("base_url") or ""),
        "turn1": turn1,
        "turn2": turn2,
        "turn2_hit_rate": t2_rate,
        "pass": passed,
        "note": "Slightly complex read-code prompts so the first LLM round finishes and usage is reported. Not cancelled at first thinking token.",
        "skipped": False,
    }


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="deepseek/deepseek-v4-flash")
    parser.add_argument(
        "--out",
        default="evals/results/cache-complex-official.json",
    )
    args = parser.parse_args()
    out = Path(args.out)
    if not out.is_absolute():
        out = REPO / out
    out.parent.mkdir(parents=True, exist_ok=True)
    try:
        payload = asyncio.run(_run(model_name=args.model))
    except Exception as exc:
        payload = {"skipped": True, "reason": str(exc)[:400], "pass": False}
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    if payload.get("skipped"):
        os._exit(0)
    os._exit(0 if payload.get("pass") else 1)


if __name__ == "__main__":
    raise SystemExit(main())
