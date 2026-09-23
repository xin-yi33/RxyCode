"""Run official BFCL / GAIA-style / ChatEval against AgentV2 only."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from .cases import bfcl_cases, chateval_cases, gaia_cases
from .chateval import debate, lexical_value_hit
from .reports import render_bfcl, render_chateval, render_final, render_gaia, render_index
# 废弃代码（2026-09-23）：render_matrix 没有任何调用方。评测入口只用
# render_bfcl / render_chateval / render_gaia / render_final / render_index。
# from .reports import render_matrix
from .score import canonicalize_func_name, parse_tool_calls, score_bfcl, score_gaia

RESULTS_DIR = Path(__file__).resolve().parents[1] / "results"

INTERNAL_SMOKE_IDS = (
    "bugfix-off-by-one",
    "feature-fizzbuzz",
    "feature-json-merge",
    "refactor-list-comprehension",
)

_RETRY_MARKERS = (
    "429",
    "rate limit",
    "ratelimit",
    "1305",
    "访问量过大",
    "请您稍后再试",
    "too many requests",
    "circuit breaker",
    "circuitbreaker",
    "gousagelimiterror",
)


def is_retryable_text(text: str | None) -> bool:
    blob = (text or "").lower()
    if not blob:
        return False
    if "invalid_api_key" in blob or "authenticationerror" in blob:
        return False
    return any(marker in blob for marker in _RETRY_MARKERS)


async def retry_until_not_429(factory, *, label: str = "") -> Any:
    """Retry the same case forever on 429/1305. Never return a 429 as a scored fail."""
    delay = 10.0
    attempt = 0
    while True:
        attempt += 1
        try:
            row = await factory()
        except Exception as exc:
            text = f"{type(exc).__name__}: {exc}"
            if is_retryable_text(text):
                print(f"[429 retry {attempt}] {label} {text[:240]}", flush=True)
                await asyncio.sleep(delay)
                delay = min(delay * 1.5, 120.0)
                continue
            raise
        err = str((row or {}).get("error") or "")
        if is_retryable_text(err):
            print(f"[429 retry {attempt}] {label} {err[:240]}", flush=True)
            await asyncio.sleep(delay)
            delay = min(delay * 1.5, 120.0)
            continue
        return row


def _now_tag() -> str:
    return datetime.now().strftime("%Y-%m-%d-public")


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_md(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _tool_export_name(name: str) -> str:
    cleaned = re.sub(r"[^0-9a-zA-Z_]", "_", canonicalize_func_name(name))
    cleaned = re.sub(r"_+", "_", cleaned).strip("_") or "tool"
    if cleaned[0].isdigit():
        cleaned = f"t_{cleaned}"
    return cleaned[:64]


def _py_type(declared: str) -> type:
    return {
        "integer": int,
        "number": float,
        "float": float,
        "boolean": bool,
        "array": list,
        "tuple": list,
        "dict": dict,
        "object": dict,
    }.get(str(declared or "string").lower(), str)


def _make_bfcl_tools(functions: list[dict[str, Any]], recorder: list[dict[str, Any]]):
    from langchain_core.tools import StructuredTool
    from pydantic import create_model

    tools = []
    for spec in functions:
        original = str(spec["name"])
        export = _tool_export_name(original)
        props = ((spec.get("parameters") or {}).get("properties")) or {}
        required = set((spec.get("parameters") or {}).get("required") or [])
        fields: dict[str, tuple[type, Any]] = {}
        for key, schema in props.items():
            py_type = _py_type(str((schema or {}).get("type") or "string"))
            fields[key] = (py_type, ... if key in required else None)
        if not fields:
            fields["value"] = (str, None)
        model = create_model(f"{export.title().replace('_', '')}Args", **fields)  # type: ignore[arg-type]

        def _factory(_original: str = original):
            def _run(**kwargs: Any) -> str:
                args = {key: value for key, value in kwargs.items() if value is not None}
                recorder.append({"name": _original, "arguments": args})
                return json.dumps({"ok": True, "tool": _original, "args": args}, ensure_ascii=False)

            return _run

        tools.append(
            StructuredTool.from_function(
                func=_factory(),
                name=export,
                description=str(spec.get("description") or original),
                args_schema=model,
            )
        )
    return tools


def _replace_agent_tools(agent, tools) -> None:
    from RxyCode.RxyCode1_1_0.core.safety.policy import RiskLevel, register_tool_risk

    orch = getattr(agent, "_tool_orchestrator", None)
    if orch is None:
        return
    for name in list(orch.get_all().keys()):
        orch.unregister(name)
    for tool in tools:
        register_tool_risk(tool.name, RiskLevel.READ)
        orch.register(tool.name, tool, risk="read")


async def _run_bfcl_agent(model_name: Optional[str], case: dict[str, Any]) -> dict[str, Any]:
    from RxyCode.RxyCode1_1_0.evals.backends import AgentBackend

    recorder: list[dict[str, Any]] = []
    tools = _make_bfcl_tools(case["functions"], recorder)

    def _factory(*, session_id: str):
        from RxyCode.RxyCode1_1_0.core.agent_v2 import AgentV2

        agent = AgentV2(model_name=model_name)
        agent._session_id = session_id
        _replace_agent_tools(agent, tools)
        return agent

    backend = AgentBackend(_factory)
    irrelevance = str(case.get("category") or "") == "irrelevance"
    if irrelevance:
        prompt = (
            "You have a fixed tool list. If none of the tools can solve the user "
            "request, do not call any tool. Say you cannot help with the available tools.\n\n"
            f"{case['prompt']}"
        )
    else:
        prompt = (
            "Solve this by calling the provided tools. Do not substitute bash, "
            "write, python, or websearch for those tools.\n\n"
            f"{case['prompt']}"
        )
    started = time.perf_counter()
    result = await backend.run(prompt, None)
    calls = recorder or parse_tool_calls(result.answer)
    verdict = score_bfcl(
        calls,
        expected_calls=case.get("expected_calls") or [],
        ground_truth=case.get("ground_truth"),
        category=str(case.get("category") or "simple"),
    )
    error = result.error
    passed = bool(verdict["passed"]) and not error
    if is_retryable_text(error):
        passed = False
    return {
        "id": case["id"],
        "suite": "bfcl",
        "backend": "agent",
        "category": case.get("category"),
        "passed": passed,
        "duration_s": round(time.perf_counter() - started, 3),
        "error": error,
        "answer": (result.answer or "")[:2000],
        "score": verdict,
        "tools_used": result.tools_used or [str(item.get("name") or "") for item in calls],
        "token_usage": result.token_usage,
    }


async def _run_gaia_case(backend, case: dict[str, Any]) -> dict[str, Any]:
    import shutil

    setup = case.get("setup") or {}
    files = setup.get("files") or {}
    attachment = str(case.get("attachment") or "")
    file_name = str(case.get("file_name") or "")
    tmp: tempfile.TemporaryDirectory[str] | None = None
    workdir = None
    if files or attachment:
        tmp = tempfile.TemporaryDirectory(prefix="rxy-gaia-")
        workdir = Path(tmp.name)
        for rel, content in files.items():
            path = workdir / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(str(content), encoding="utf-8")
        if attachment:
            src = Path(attachment)
            dest = workdir / (file_name or src.name)
            dest.parent.mkdir(parents=True, exist_ok=True)
            if src.is_file():
                shutil.copy2(src, dest)
    started = time.perf_counter()
    try:
        result = await backend.run(case["prompt"], workdir)
    finally:
        if tmp is not None:
            tmp.cleanup()
    verdict = score_gaia(result.answer, str(case["expected"]), aliases=list(case.get("aliases") or []))
    error = result.error
    passed = bool(verdict["passed"]) and not error
    if is_retryable_text(error):
        passed = False
    return {
        "id": case["id"],
        "suite": "gaia",
        "backend": "agent",
        "level": case.get("level"),
        "passed": passed,
        "duration_s": round(time.perf_counter() - started, 3),
        "error": error,
        "answer": (result.answer or "")[:2000],
        "score": verdict,
        "tools_used": result.tools_used,
        "token_usage": result.token_usage,
    }


async def _run_chateval_case(backend, llm, case: dict[str, Any]) -> dict[str, Any]:
    started = time.perf_counter()
    result = await backend.run(case["prompt"], None)
    if is_retryable_text(result.error):
        return {
            "id": case["id"],
            "suite": "chateval",
            "backend": "agent",
            "passed": False,
            "duration_s": round(time.perf_counter() - started, 3),
            "error": result.error,
            "answer": (result.answer or "")[:2000],
        }
    if case.get("must_mention"):
        lexical = lexical_value_hit(result.answer, list(case.get("must_mention") or []))
    else:
        lexical = {"passed": True, "missing": [], "reason": "debate-only official item"}
    try:
        judged = await debate(
            llm,
            task=case["prompt"],
            answer=result.answer,
            values=list(case.get("values") or []),
        )
    except Exception as exc:
        text = f"{type(exc).__name__}: {exc}"
        return {
            "id": case["id"],
            "suite": "chateval",
            "backend": "agent",
            "passed": False,
            "duration_s": round(time.perf_counter() - started, 3),
            "error": text,
            "answer": (result.answer or "")[:2000],
            "score": {"lexical": lexical},
            "tools_used": result.tools_used,
            "token_usage": result.token_usage,
            "values": case.get("values"),
        }
    error = result.error
    if is_retryable_text(str(judged.get("raw") or "")) or is_retryable_text(str(judged.get("rationale") or "")):
        error = error or str(judged.get("raw") or judged.get("rationale") or "chateval 429")
    passed = lexical["passed"] and judged.get("passed") and not error
    if is_retryable_text(error):
        passed = False
    return {
        "id": case["id"],
        "suite": "chateval",
        "backend": "agent",
        "passed": bool(passed),
        "duration_s": round(time.perf_counter() - started, 3),
        "error": error,
        "answer": (result.answer or "")[:2000],
        "score": {"lexical": lexical, "debate": judged},
        "tools_used": result.tools_used,
        "token_usage": result.token_usage,
        "values": case.get("values"),
    }


def _rate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(rows)
    passed = sum(1 for row in rows if row.get("passed"))
    return {
        "passed": passed,
        "total": total,
        "pass_rate": (passed / total) if total else 0.0,
        "duration_s": round(sum(float(row.get("duration_s") or 0) for row in rows), 3),
    }


def _summarize(cases: list[dict[str, Any]]) -> dict[str, Any]:
    suites: dict[str, dict[str, Any]] = {}
    for suite in ("bfcl", "gaia", "chateval", "internal"):
        rows = [row for row in cases if row.get("suite") == suite]
        agent_rows = [row for row in rows if row.get("backend") == "agent"]
        block: dict[str, Any] = {"agent": _rate(agent_rows)}
        if suite == "bfcl":
            by_category = {}
            for name in ("simple", "multiple", "parallel", "parallel_multiple", "irrelevance"):
                by_category[name] = _rate([row for row in agent_rows if row.get("category") == name])
            block["by_category"] = by_category
        if suite == "gaia":
            by_level = {}
            for level in (1, 2, 3):
                by_level[str(level)] = _rate(
                    [row for row in agent_rows if int(row.get("level") or 0) == level]
                )
            block["by_level"] = by_level
        if suite == "chateval":
            cats = sorted({str(row.get("category") or "") for row in agent_rows if row.get("category")})
            block["by_category"] = {
                name: _rate([row for row in agent_rows if row.get("category") == name])
                for name in cats
            }
        suites[suite] = block
    return suites


def _persist(tag: str, report: dict[str, Any]) -> None:
    json_path = RESULTS_DIR / f"{tag}.json"
    _write_json(json_path, report)
    _write_md(RESULTS_DIR / f"{tag}.md", render_index(report))
    _write_md(RESULTS_DIR / f"{tag}-FINAL.md", render_final(report))
    _write_md(RESULTS_DIR / f"{tag}-bfcl.md", render_bfcl(report))
    _write_md(RESULTS_DIR / f"{tag}-gaia.md", render_gaia(report))
    _write_md(RESULTS_DIR / f"{tag}-chateval.md", render_chateval(report))
    date_prefix = tag.split("-public")[0] if "-public" in tag else ""
    if date_prefix and date_prefix != tag:
        _write_md(RESULTS_DIR / f"{date_prefix}-FINAL.md", render_final(report))
        _write_md(RESULTS_DIR / f"{date_prefix}-bfcl.md", render_bfcl(report))
        _write_md(RESULTS_DIR / f"{date_prefix}-gaia.md", render_gaia(report))
        _write_md(RESULTS_DIR / f"{date_prefix}-chateval.md", render_chateval(report))


async def _run_internal(model_name: Optional[str]) -> list[dict[str, Any]]:
    from RxyCode.RxyCode1_1_0.evals.backends import build_backend
    from RxyCode.RxyCode1_1_0.evals.runner import run_task
    from RxyCode.RxyCode1_1_0.evals.tasks import load_tasks

    tasks = load_tasks(task_ids=list(INTERNAL_SMOKE_IDS))
    backend = build_backend("agent", model_name=model_name)
    rows: list[dict[str, Any]] = []
    for task in tasks:
        async def _once(_task=task):
            item = await run_task(_task, backend)
            return {
                "id": item.task_id,
                "suite": "internal",
                "backend": "agent",
                "category": item.category,
                "passed": item.passed,
                "duration_s": item.duration_s,
                "error": item.error,
                "answer": (item.agent_answer or "")[:2000],
                "tools_used": item.tools_used,
                "token_usage": item.token_usage,
            }

        rows.append(await retry_until_not_429(_once, label=f"internal {task.id}"))
    return rows


async def run_public(
    *,
    model_name: Optional[str] = None,
    include_internal: bool = True,
    task_timeout: int = 180,
    tag: str | None = None,
    suites: tuple[str, ...] = ("bfcl", "gaia", "chateval", "internal"),
) -> dict[str, Any]:
    from RxyCode.RxyCode1_1_0.evals.backends import build_backend
    from RxyCode.RxyCode1_1_0.evals.runner import _build_llm

    llm, resolved = _build_llm(model_name)
    agent_backend = build_backend("agent", model_name=model_name)
    tag = tag or _now_tag()
    json_path = RESULTS_DIR / f"{tag}.json"
    cases: list[dict[str, Any]] = []
    done: set[str] = set()
    if json_path.is_file():
        try:
            previous = json.loads(json_path.read_text(encoding="utf-8"))
            for row in previous.get("cases") or []:
                if is_retryable_text(str(row.get("error") or "")):
                    continue
                cases.append(row)
                done.add(f"{row.get('suite')}:{row.get('id')}")
            print(f"resume {len(done)} scored cases from {json_path}", flush=True)
        except json.JSONDecodeError:
            pass

    async def _bounded(coro_factory):
        if task_timeout <= 0:
            return await coro_factory()
        return await asyncio.wait_for(coro_factory(), timeout=task_timeout)

    def _snapshot() -> dict[str, Any]:
        return {
            "date": datetime.now().isoformat(timespec="seconds"),
            "tag": tag,
            "model": model_name or resolved,
            "gaia_official_gated": False,
            "note": (
                "Agent-only. BFCL is Gorilla v4 official AST JSONL (1240). "
                "GAIA is official 2023 validation (165). "
                "ChatEval judges official LMSYS MT-Bench (80). "
                "429/1305 retries the same item forever and is never scored as fail."
            ),
            "suites": _summarize(cases),
            "cases": cases,
        }

    async def _record(row: dict[str, Any]) -> None:
        if is_retryable_text(str(row.get("error") or "")):
            raise RuntimeError("retry helper leaked a 429 row")
        cases.append(row)
        done.add(f"{row.get('suite')}:{row.get('id')}")
        status = "PASS" if row.get("passed") else "FAIL"
        print(
            f"[{status}] {row.get('suite')} {row.get('id')} "
            f"{row.get('duration_s')}s {row.get('error') or ''}",
            flush=True,
        )
        _persist(tag, _snapshot())

    async def _run_and_record(case_id: str, suite: str, factory, extra: dict[str, Any] | None = None) -> None:
        try:
            row = await retry_until_not_429(factory, label=f"{suite} {case_id}")
        except asyncio.TimeoutError:
            row = {
                "id": case_id,
                "suite": suite,
                "backend": "agent",
                "passed": False,
                "error": "TimeoutError",
                "duration_s": float(task_timeout),
            }
        except Exception as exc:
            text = f"{type(exc).__name__}: {exc}"
            if is_retryable_text(text):
                row = await retry_until_not_429(factory, label=f"{suite} {case_id}")
            else:
                row = {
                    "id": case_id,
                    "suite": suite,
                    "backend": "agent",
                    "passed": False,
                    "error": text,
                    "duration_s": 0.0,
                }
        if extra:
            merged = dict(extra)
            merged.update(row)
            row = merged
        await _record(row)

    wanted = set(suites)

    if "bfcl" in wanted:
        official = bfcl_cases(official=True)
        total = len(official)
        for index, case in enumerate(official, start=1):
            key = f"bfcl:{case['id']}"
            if key in done:
                continue
            print(f"BFCL {index}/{total} {case['id']}", flush=True)
            await _run_and_record(
                case["id"],
                "bfcl",
                lambda c=case: _bounded(lambda: _run_bfcl_agent(model_name, c)),
                extra={"category": case.get("category")},
            )

    if "gaia" in wanted:
        for case in gaia_cases():
            key = f"gaia:{case['id']}"
            if key in done:
                continue
            await _run_and_record(
                case["id"],
                "gaia",
                lambda c=case: _bounded(lambda: _run_gaia_case(agent_backend, c)),
            )

    if "chateval" in wanted:
        for case in chateval_cases():
            key = f"chateval:{case['id']}"
            if key in done:
                continue
            await _run_and_record(
                case["id"],
                "chateval",
                lambda c=case: _bounded(lambda: _run_chateval_case(agent_backend, llm, c)),
            )

    if include_internal and "internal" in wanted:
        pending = [
            task_id
            for task_id in INTERNAL_SMOKE_IDS
            if f"internal:{task_id}" not in done
        ]
        if pending:
            for row in await _run_internal(model_name):
                key = f"internal:{row.get('id')}"
                if key in done:
                    continue
                await _record(row)

    report = _snapshot()
    _persist(tag, report)
    return report


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m evals.public")
    parser.add_argument("--model", default=None, help="Local config model key")
    parser.add_argument("--tag", default=None, help="Result tag under evals/results/")
    parser.add_argument("--skip-internal", action="store_true")
    parser.add_argument("--task-timeout", type=int, default=180)
    parser.add_argument(
        "--suites",
        default="bfcl,gaia,chateval,internal",
        help="Comma list: bfcl,gaia,chateval,internal",
    )
    args = parser.parse_args(argv)
    os.environ.setdefault("RXYCODE_EVAL_MODE", "solo")
    tag = args.tag or _now_tag()
    suites = tuple(item.strip() for item in str(args.suites).split(",") if item.strip())
    report = asyncio.run(
        run_public(
            model_name=args.model,
            include_internal=not args.skip_internal,
            task_timeout=args.task_timeout,
            tag=tag,
            suites=suites,
        )
    )
    print(render_final(report))
    print(f"wrote {RESULTS_DIR / f'{tag}.json'}")
    print(f"wrote {RESULTS_DIR / f'{tag}-FINAL.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
