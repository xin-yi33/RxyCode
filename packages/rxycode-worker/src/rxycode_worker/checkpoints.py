"""One LangGraph thread per session and run, stored in AsyncPostgresSaver.

A restarted worker reads that checkpoint. It does not continue into a later
side-effect node. Two runs never share a thread id.
"""

from __future__ import annotations

import asyncio
import selectors
import sys
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from typing import TypedDict
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from langgraph.graph import END, START, StateGraph


class CheckpointerUnavailable(RuntimeError):
    """The graph checkpointer cannot be opened. No side effect may start."""


class _ReadState(TypedDict, total=False):
    source: str
    observed: str
    marker: str


def graph_thread_id(session_id: str, run_id: str) -> str:
    """Stable id. Length prefixes stop `a:b` + `c` colliding with `a` + `b:c`."""
    if not isinstance(session_id, str) or not session_id or "\x00" in session_id:
        raise ValueError("invalid session_id")
    if not isinstance(run_id, str) or not run_id or "\x00" in run_id:
        raise ValueError("invalid run_id")
    return f"rxy:{len(session_id)}:{session_id}:{len(run_id)}:{run_id}"


def _conninfo(database_url: str) -> str:
    if not isinstance(database_url, str) or not database_url:
        raise CheckpointerUnavailable("database url is missing")
    url = database_url.replace("postgresql+psycopg://", "postgresql://", 1)
    url = url.replace("postgres+psycopg://", "postgresql://", 1)
    parts = urlparse(url)
    if parts.scheme not in {"postgresql", "postgres"}:
        raise CheckpointerUnavailable("checkpointer url is not postgres")
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query.setdefault("connect_timeout", "3")
    return urlunparse(parts._replace(query=urlencode(query)))


def _read_node(state: _ReadState) -> dict[str, str]:
    return {"observed": state["source"]}


def _side_node(state: _ReadState) -> dict[str, str]:
    """A later write. interrupt_before keeps a pure-read crash from reaching it."""
    marker = state.get("marker") or ""
    if marker:
        from pathlib import Path

        Path(marker).write_text("side-effect", encoding="utf-8")
    return {}


def _compile(saver: object):
    graph = StateGraph(_ReadState)
    graph.add_node("read", _read_node)
    graph.add_node("side", _side_node)
    graph.add_edge(START, "read")
    graph.add_edge("read", "side")
    graph.add_edge("side", END)
    return graph.compile(checkpointer=saver, interrupt_before=["side"])


@asynccontextmanager
async def _open_saver(database_url: str):
    """Yield a ready AsyncPostgresSaver. Setup failure stays fail-closed."""
    try:
        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
    except ImportError as exc:
        raise CheckpointerUnavailable("AsyncPostgresSaver is not installed") from exc
    conninfo = _conninfo(database_url)
    saver_cm = AsyncPostgresSaver.from_conn_string(conninfo)
    entered = False
    try:
        saver = await saver_cm.__aenter__()
        entered = True
        await saver.setup()
    except CheckpointerUnavailable:
        if entered:
            await saver_cm.__aexit__(*sys.exc_info())
        raise
    except Exception as exc:
        if entered:
            await saver_cm.__aexit__(type(exc), exc, exc.__traceback__)
        raise CheckpointerUnavailable(f"checkpointer is unavailable: {exc}") from exc
    try:
        yield saver
    finally:
        await saver_cm.__aexit__(None, None, None)


def _run_on_selector(factory: Callable[[], Awaitable[dict[str, object]]]) -> dict[str, object]:
    """psycopg async refuses the Windows ProactorEventLoop, so use a selector loop."""
    if sys.platform == "win32":
        loop = asyncio.SelectorEventLoop(selectors.SelectSelector())
    else:
        loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(factory())
    finally:
        loop.run_until_complete(loop.shutdown_asyncgens())
        loop.close()
        asyncio.set_event_loop(None)


async def _call_on_selector(
    factory: Callable[[], Awaitable[dict[str, object]]],
) -> dict[str, object]:
    return await asyncio.to_thread(_run_on_selector, factory)


async def _record_readonly_checkpoint(
    database_url: str,
    *,
    session_id: str,
    run_id: str,
    source: str,
    marker: str,
) -> dict[str, object]:
    thread_id = graph_thread_id(session_id, run_id)
    async with _open_saver(database_url) as saver:
        graph = _compile(saver)
        config = {"configurable": {"thread_id": thread_id}}
        await graph.ainvoke({"source": source, "marker": marker}, config)
        snap = await graph.aget_state(config)
        return {
            "thread_id": thread_id,
            "observed": snap.values.get("observed"),
            "next": list(snap.next),
        }


async def record_readonly_checkpoint(
    database_url: str,
    *,
    session_id: str,
    run_id: str,
    source: str,
    marker: str = "",
) -> dict[str, object]:
    """Run only the read node, then stop before the side-effect node."""
    return await _call_on_selector(
        lambda: _record_readonly_checkpoint(
            database_url,
            session_id=session_id,
            run_id=run_id,
            source=source,
            marker=marker,
        )
    )


async def _resume_readonly(
    database_url: str,
    *,
    session_id: str,
    run_id: str,
) -> dict[str, object]:
    thread_id = graph_thread_id(session_id, run_id)
    async with _open_saver(database_url) as saver:
        graph = _compile(saver)
        config = {"configurable": {"thread_id": thread_id}}
        snap = await graph.aget_state(config)
        values = snap.values or {}
        return {
            "thread_id": thread_id,
            "observed": values.get("observed"),
            "next": list(snap.next),
        }


async def resume_readonly(
    database_url: str,
    *,
    session_id: str,
    run_id: str,
) -> dict[str, object]:
    """Open a new saver and read the checkpoint. Do not continue the graph."""
    return await _call_on_selector(
        lambda: _resume_readonly(
            database_url,
            session_id=session_id,
            run_id=run_id,
        )
    )


async def _accept_run(
    database_url: str,
    *,
    session_id: str,
    run_id: str,
    effect: Callable[[], object],
) -> dict[str, object]:
    thread_id = graph_thread_id(session_id, run_id)
    try:
        async with _open_saver(database_url) as saver:
            await saver.aget_tuple({"configurable": {"thread_id": thread_id}})
    except CheckpointerUnavailable:
        return {
            "started": False,
            "status": "recovery_required",
            "thread_id": thread_id,
        }
    effect()
    return {"started": True, "status": "running", "thread_id": thread_id}


async def accept_run(
    database_url: str,
    *,
    session_id: str,
    run_id: str,
    effect: Callable[[], object],
) -> dict[str, object]:
    """Prove the checkpointer is usable before any unjournaled side effect."""
    return await _call_on_selector(
        lambda: _accept_run(
            database_url,
            session_id=session_id,
            run_id=run_id,
            effect=effect,
        )
    )
