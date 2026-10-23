"""WEB-W9-B3. Event chain: tool.started, delta coalescing, notify.* audit,
run.status rows on every transition, SSE heartbeat, journal caps."""

from __future__ import annotations

import asyncio
import json
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

REPO = Path(__file__).resolve().parents[3]
for _name in (
    "rxycode-server",
    "rxycode-worker",
    "rxycode-runner",
    "rxycode-protocol",
    "rxycode-core",
):
    _path = REPO / "packages" / _name / "src"
    if _path.is_dir() and str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from rxycode_server.persistence.models import (  # noqa: E402
    Organization,
    Project,
    Run,
    RunEvent,
    SessionRow,
    User,
)
from rxycode_worker import drain, supervisor  # noqa: E402


class _Note:
    """A protocol notification stand-in — ``method`` attr plus ``params``."""

    def __init__(self, method: str, **params: Any) -> None:
        self.method = method
        self.params = params


def _emitter() -> tuple[drain._RunEmit, list[tuple[str, dict[str, Any]]]]:
    captured: list[tuple[str, dict[str, Any]]] = []
    emit = drain._RunEmit(
        "", "t1", "r1", emitter=lambda etype, payload: captured.append((etype, payload))
    )
    return emit, captured


def _seed_run(
    postgres_url: str,
    *,
    tenant: str,
    run_id: str,
    status: str,
    lease_owner: str | None = None,
    lease_epoch: int = 0,
    lease_until: datetime | None = None,
) -> None:
    engine = create_engine(postgres_url)
    try:
        with Session(engine) as db:
            if db.get(User, f"u-{tenant}") is None:
                db.add(User(id=f"u-{tenant}", github_id=None, kind="local"))
            if db.get(Organization, f"o-{tenant}") is None:
                db.add(Organization(id=f"o-{tenant}", tenant_id=tenant))
            if db.get(Project, f"p-{tenant}") is None:
                db.add(
                    Project(id=f"p-{tenant}", tenant_id=tenant, name="t", repo_config={})
                )
            if db.get(SessionRow, f"s-{run_id}") is None:
                db.add(
                    SessionRow(
                        id=f"s-{run_id}", tenant_id=tenant, project_id=f"p-{tenant}", title="t"
                    )
                )
            db.add(
                Run(
                    id=run_id,
                    tenant_id=tenant,
                    session_id=f"s-{run_id}",
                    status=status,
                    request_id=f"req-{run_id}",
                    lease_owner=lease_owner,
                    lease_epoch=lease_epoch,
                    lease_until=lease_until,
                )
            )
            db.commit()
    finally:
        engine.dispose()


def _events(postgres_url: str, run_id: str) -> list[tuple[int, str, dict[str, Any]]]:
    with Session(create_engine(postgres_url)) as db:
        rows = db.scalars(
            select(RunEvent).where(RunEvent.run_id == run_id).order_by(RunEvent.seq)
        ).all()
        return [(int(r.seq), str(r.type), dict(r.payload or {})) for r in rows]


def _statuses(postgres_url: str, run_id: str) -> list[dict[str, Any]]:
    return [p for _s, t, p in _events(postgres_url, run_id) if t == "run.status"]


# ---------------------------------------------------------------- tool.started


def test_w9_b3_tool_started_projection() -> None:
    emit, captured = _emitter()
    emit(
        _Note(
            "event/tool_begin",
            call_id="c1",
            tool_name="bash",
            arguments={"command": "ls -la"},
        )
    )
    emit(_Note("event/tool_end", call_id="c1", ok=True, summary="ok"))
    kinds = [kind for kind, _ in captured]
    assert kinds == ["notify.event/tool_begin", "tool.started", "notify.event/tool_end", "tool.completed"]
    started = dict(captured)["tool.started"]
    assert started == {"call_id": "c1", "tool": "bash", "title": "ls -la"}
    done = dict(captured)["tool.completed"]
    assert done["call_id"] == "c1" and done["tool"] == "bash"
    # ToolEnd carries no exit_code/duration_ms on the wire — never invented.
    assert "exit_code" not in done and "duration_ms" not in done


def test_reasoning_is_a_thought_and_progress_is_status() -> None:
    """The thought block is the model chain. Progress text is not appended to it."""
    thought = drain._projection_rows(
        "event/reasoning_snapshot",
        {"text": "先看文件", "snapshot": False, "intermediate": False},
        {},
        run_id="r",
    )
    assert thought == [
        (
            "assistant.delta",
            {
                "text": "先看文件",
                "intermediate": False,
                "channel": "reasoning",
                "snapshot": False,
            },
        )
    ]
    status = drain._projection_rows(
        "event/progress",
        {"text": "Analyzing your request..."},
        {},
        run_id="r",
    )
    assert status[0][1]["channel"] == "status"
    assert status[0][1]["intermediate"] is True
    emit, captured = _emitter()
    emit(_Note("event/progress", text="Thinking... (round 1)"))
    emit(_Note("event/reasoning_snapshot", text="再改测试", snapshot=False, intermediate=False))
    emit.flush()
    deltas = [payload for kind, payload in captured if kind == "assistant.delta"]
    assert [item["channel"] for item in deltas] == ["status", "reasoning"]
    assert deltas[1]["text"] == "再改测试"


def test_w9_b3_tool_started_title_fallback_and_truncation() -> None:
    rows = drain._projection_rows(
        "event/tool_begin",
        {"call_id": "c", "tool_name": "edit", "arguments": {"description": "d", "command": "c"}},
        {},
        run_id="r",
    )
    assert rows == [("tool.started", {"call_id": "c", "tool": "edit", "title": "d"})]
    rows = drain._projection_rows(
        "event/tool_begin",
        {"call_id": "c", "tool_name": "edit", "arguments": {"filePath": "x" * 400}},
        {},
        run_id="r",
    )
    assert rows[0][1]["title"] == "x" * 300


# ---------------------------------------------------------------- delta merge


def test_w9_b3_deltas_coalesce_and_keep_text() -> None:
    emit, captured = _emitter()
    texts = [f"chunk-{i} " for i in range(100)]
    for text in texts:
        emit(_Note("event/message_delta", text=text))
    emit.flush()
    deltas = [p for t, p in captured if t == "assistant.delta"]
    assert 1 <= len(deltas) <= 5
    assert "".join(d["text"] for d in deltas) == "".join(texts)
    assert all(d["intermediate"] is False for d in deltas)
    # message_delta is projection-covered: no audit row per token.
    assert not any(t.startswith("notify.") for t, _ in captured)


def test_w9_b3_delta_flushes_on_flag_change_and_size() -> None:
    emit, captured = _emitter()
    emit.project("assistant.delta", {"text": "a", "intermediate": False})
    emit.project("assistant.delta", {"text": "b", "intermediate": True})
    emit.project("assistant.delta", {"text": "c", "intermediate": True})
    emit.flush()
    deltas = [p for t, p in captured if t == "assistant.delta"]
    assert deltas == [
        {"text": "a", "intermediate": False},
        {"text": "bc", "intermediate": True},
    ]

    emit2, captured2 = _emitter()
    emit2.project("assistant.delta", {"text": "x" * 1500, "intermediate": False})
    emit2.project("assistant.delta", {"text": "y" * 1500, "intermediate": False})
    # buffer hit 2KB -> flushed on the second project; remainder is one row
    emit2.project("assistant.delta", {"text": "z", "intermediate": False})
    emit2.flush()
    texts = [p["text"] for t, p in captured2 if t == "assistant.delta"]
    assert texts == ["x" * 1500 + "y" * 1500, "z"]


def test_w9_b3_delta_flushes_on_age() -> None:
    import time

    emit, captured = _emitter()
    emit.project("assistant.delta", {"text": "old", "intermediate": False})
    time.sleep(drain._DELTA_MAX_AGE + 0.05)
    emit.project("assistant.delta", {"text": "new", "intermediate": False})
    emit.flush()
    texts = [p["text"] for t, p in captured if t == "assistant.delta"]
    assert texts == ["old", "new"]


def test_w9_b3_ordering_with_interleaved_rows() -> None:
    emit, captured = _emitter()
    emit.project("assistant.delta", {"text": "before", "intermediate": False})
    emit.project("tool.started", {"call_id": "c", "tool": "bash", "title": "ls"})
    emit.project("assistant.delta", {"text": "after", "intermediate": False})
    emit.flush()
    assert [t for t, _ in captured] == [
        "assistant.delta",
        "tool.started",
        "assistant.delta",
    ]


def test_w9_b3_structural_rows_survive_delta_cap() -> None:
    """>cap deltas drop only deltas — tool.* and assistant.final always land."""
    emit, captured = _emitter()
    emit.delta_rows = drain._JOURNAL_CAP
    for _ in range(600):
        emit.project("assistant.delta", {"text": "flood"})
    emit.project("tool.started", {"call_id": "c", "tool": "bash", "title": "t"})
    emit.project("tool.completed", {"call_id": "c", "tool": "bash", "status": "completed", "summary": "ok"})
    emit.project("assistant.final", {"text": "answer"})
    emit.flush()
    kinds = [t for t, _ in captured]
    assert "assistant.delta" not in kinds
    assert kinds == ["tool.started", "tool.completed", "assistant.final"]


# ------------------------------------------------------------------- notify.*


def test_w9_b3_notify_rows_structured_and_capped() -> None:
    emit, captured = _emitter()
    emit(_Note("event/plan", steps=["a", "b"]))
    emit(_Note("event/tool_begin", call_id="c", tool_name="bash", arguments={}))
    emit(_Note("event/message_delta", text="no audit for me"))
    emit(_Note("event/reasoning_snapshot", text="nor me"))
    emit(_Note("event/token_usage", input_tokens=1, output_tokens=2))
    emit(_Note("event/progress", text="nor me either"))
    emit.flush()
    audits = [p for t, p in captured if t.startswith("notify.")]
    assert len(audits) == 2  # plan + tool_begin only
    for payload in audits:
        encoded = json.dumps(payload)  # parseable JSON
        assert "method='" not in encoded and '"params"' in encoded
    assert audits[0]["params"]["steps"] == ["a", "b"]
    # long strings are truncated to 2000 chars recursively
    emit2, captured2 = _emitter()
    emit2(_Note("event/plan", steps=["y" * 5000]))
    audit = [p for t, p in captured2 if t.startswith("notify.")][0]
    assert audit["params"]["steps"][0] == "y" * 2000


# ----------------------------------------------------------------- P9 branch


def test_w9_b3_agent_needs_input_not_on_park_path() -> None:
    """P9 determination: the W8 park path cannot emit it. Its only producer is
    appserver.server._schedule_notification (a TUI-socket write), while the
    confined turn parks via HarnessPaused -> channel.pause_approval -> the
    parent's approval.service row. The projection branch was therefore dead
    code: deleted. Nothing projects question/approval from it anymore."""
    rows = drain._projection_rows(
        "event/agent_needs_input",
        {"request_id": "ap1", "preview": "approve rm -rf?"},
        {},
        run_id="r9",
    )
    assert rows == []
    emit, captured = _emitter()
    emit(_Note("event/agent_needs_input", request_id="ap1", preview="x"))
    ask_rows = [t for t, _ in captured if t in {"question.requested", "approval.requested"}]
    assert ask_rows == []


# ------------------------------------------------- run.status rows (Postgres)


def test_w9_b3_run_status_claim_and_terminal(postgres_url: str) -> None:
    run_id = f"r-claim-{uuid.uuid4().hex[:8]}"
    _seed_run(postgres_url, tenant="t-ev", run_id=run_id, status="pending")
    epoch = supervisor.claim(postgres_url, run_id, "worker-1")
    assert epoch is not None
    rows = _statuses(postgres_url, run_id)
    assert [r["status"] for r in rows] == ["leased"]
    assert rows[0]["epoch"] == epoch
    # seq monotonically allocated via max(event_seq, max(seq))+1
    seqs = [s for s, _t, _p in _events(postgres_url, run_id)]
    assert seqs == sorted(seqs)
    supervisor.commit_terminal(postgres_url, run_id, "worker-1", epoch, "succeeded")
    rows = _statuses(postgres_url, run_id)
    assert [r["status"] for r in rows] == ["leased", "succeeded"]
    assert rows[-1]["epoch"] == epoch


def test_w9_b3_run_status_cancel(postgres_url: str) -> None:
    run_id = f"r-cancel-{uuid.uuid4().hex[:8]}"
    _seed_run(postgres_url, tenant="t-ev", run_id=run_id, status="pending")
    assert supervisor.request_cancel(postgres_url, run_id) == "cancel_requested"
    rows = _statuses(postgres_url, run_id)
    assert [r["status"] for r in rows] == ["cancel_requested"]
    # the legacy cancel_requested audit row still exists alongside
    kinds = [t for _s, t, _p in _events(postgres_url, run_id)]
    assert "cancel_requested" in kinds and "run.status" in kinds


def test_w9_b3_run_status_park_and_resume(postgres_url: str) -> None:
    from rxycode_server.approvals.service import decide_approval, request_approval

    run_id = f"r-park-{uuid.uuid4().hex[:8]}"
    lease_until = datetime.now(timezone.utc) + timedelta(seconds=60)
    _seed_run(
        postgres_url,
        tenant="t-ev",
        run_id=run_id,
        status="leased",
        lease_owner="worker-1",
        lease_epoch=4,
        lease_until=lease_until,
    )
    parked = request_approval(
        postgres_url,
        tenant_id="t-ev",
        run_id=run_id,
        call_id="call-1",
        tool="bash",
        permission_scope="write",
        arguments={"command": "rm x"},
        deadline=datetime.now(timezone.utc) + timedelta(hours=1),
        worker_id="worker-1",
        epoch=4,
    )
    rows = _statuses(postgres_url, run_id)
    assert [r["status"] for r in rows] == ["waiting_approval"]
    assert rows[0]["epoch"] == 4
    kinds = [t for _s, t, _p in _events(postgres_url, run_id)]
    # exactly one ask row of the right kind — no fabricated second bucket
    assert kinds.count("approval.requested") == 1
    assert "question.requested" not in kinds

    decided = decide_approval(
        postgres_url,
        tenant_id="t-ev",
        approval_id=str(parked["approval_id"]),
        decision="approved",
        expected_revision=0,
    )
    assert decided["status"] == "approved"
    rows = _statuses(postgres_url, run_id)
    assert [r["status"] for r in rows] == ["waiting_approval", "pending"]


def test_w9_b3_run_status_question_park_and_answer(postgres_url: str) -> None:
    from rxycode_server.approvals.service import answer_question, request_question

    run_id = f"r-quest-{uuid.uuid4().hex[:8]}"
    lease_until = datetime.now(timezone.utc) + timedelta(seconds=60)
    _seed_run(
        postgres_url,
        tenant="t-ev",
        run_id=run_id,
        status="leased",
        lease_owner="worker-1",
        lease_epoch=7,
        lease_until=lease_until,
    )
    request_question(
        postgres_url,
        tenant_id="t-ev",
        run_id=run_id,
        question_id="q-1",
        question="pick one",
        header="choose",
        options=[{"label": "yes", "value": "yes"}],
        deadline=datetime.now(timezone.utc) + timedelta(hours=1),
        worker_id="worker-1",
        epoch=7,
        checkpoint={"k": "v"},
    )
    rows = _statuses(postgres_url, run_id)
    assert [r["status"] for r in rows] == ["waiting_approval"]
    kinds = [t for _s, t, _p in _events(postgres_url, run_id)]
    assert kinds.count("question.requested") == 1
    assert "approval.requested" not in kinds

    answer_question(
        postgres_url,
        tenant_id="t-ev",
        run_id=run_id,
        question_id="q-1",
        answer="yes",
    )
    rows = _statuses(postgres_url, run_id)
    assert [r["status"] for r in rows] == ["waiting_approval", "pending"]


# ------------------------------------------------------------- SSE heartbeat


def test_w9_b3_sse_heartbeat(postgres_url: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """Follow mode emits an SSE comment keepalive when no new event arrives."""
    from rxycode_server.api import sse

    run_id = f"r-heart-{uuid.uuid4().hex[:8]}"
    _seed_run(postgres_url, tenant="t-ev", run_id=run_id, status="pending")
    monkeypatch.setattr(sse, "HEARTBEAT_SECONDS", 0.3)

    async def _collect() -> list[str]:
        frames: list[str] = []
        gen = sse.iter_frames(
            postgres_url,
            tenant_id="t-ev",
            run_id=run_id,
            after_seq=0,
            follow=True,
        )
        try:
            async def _drain() -> None:
                async for frame in gen:
                    frames.append(frame)

            await asyncio.wait_for(_drain(), timeout=2.0)
        except (asyncio.TimeoutError, TimeoutError):
            pass
        finally:
            await gen.aclose()
        return frames

    frames = asyncio.run(_collect())
    assert ": open\n\n" in frames
    assert any(frame == ": ping\n\n" for frame in frames)


def test_w9_b3_sse_no_heartbeat_without_follow(
    postgres_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    from rxycode_server.api import sse

    run_id = f"r-nofoll-{uuid.uuid4().hex[:8]}"
    _seed_run(postgres_url, tenant="t-ev", run_id=run_id, status="pending")
    monkeypatch.setattr(sse, "HEARTBEAT_SECONDS", 0.01)

    async def _collect() -> list[str]:
        return [frame async for frame in sse.iter_frames(
            postgres_url,
            tenant_id="t-ev",
            run_id=run_id,
            after_seq=0,
            follow=False,
        )]

    frames = asyncio.run(_collect())
    assert frames == [": open\n\n"]
