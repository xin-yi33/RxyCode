"""WEB-W6-C04. Steer stays on the same run, in order, and replay keeps the tree."""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
_WORKER = REPO / "packages" / "rxycode-worker" / "src"
_SERVER = REPO / "packages" / "rxycode-server" / "src"
from tests.support.pgurl import bun_path

BUN = bun_path()


def _run_async(coro):
    """asyncio.run cannot start when this thread already has a loop."""
    box: dict[str, BaseException] = {}

    def _go() -> None:
        try:
            asyncio.run(coro)
        except BaseException as exc:
            box["error"] = exc

    worker = threading.Thread(target=_go)
    worker.start()
    worker.join()
    if "error" in box:
        raise box["error"]
for _entry in (str(_WORKER), str(_SERVER), str(REPO / "tests" / "web" / "w6")):
    if _entry not in sys.path:
        sys.path.insert(0, _entry)


def test_w6_c04_integration(tmp_path: Path) -> None:
    """Two steers apply in order on the original run. Refresh drops no node."""
    from test_w6_c04_unit import _run
    from rxycode_worker.agent_events import final_answer, project_run
    from RxyCode.RxyCode1_1_0.core.subagents.events import EventStore
    from RxyCode.RxyCode1_1_0.protocol.agents import TeamEvent

    spans, emitted = _run(tmp_path, "ses-w6c04-mod")
    events = [item for item in emitted if isinstance(item, TeamEvent)]
    first = project_run(spans=spans, events=events)
    replayed = project_run(
        spans=[_round_trip(span) for span in spans],
        events=events,
    )
    assert {node["id"] for node in replayed["nodes"]} == {node["id"] for node in first["nodes"]}
    assert [node["parent_id"] for node in replayed["nodes"]] == [
        node["parent_id"] for node in first["nodes"]
    ]
    store = EventStore()
    before = store.latest_cursor()
    run_id = str(first["run_id"])
    one, two, queued = _run_async(_steer_pair(run_id, store))
    assert one["run_id"] == run_id
    assert two["run_id"] == run_id
    assert [item["text"] for item in two["applied"]] == ["steer-one", "steer-two"]
    assert [item["seq"] for item in two["applied"]] == [1, 2]
    assert queued == ["steer-one", "steer-two"]
    assert store.latest_cursor() == before
    marker = "secret-child-draft-99"
    answer = final_answer(
        parent_text="ship the health endpoint",
        child_events=[{"kind": "intermediate", "text": marker}],
    )
    legacy = _render_legacy()
    assert 'data-agents' in legacy
    assert 'data-agent-id="coder"' in legacy
    markup = _render(first["nodes"], answer["text"])
    assert 'aria-label="agent-tree"' in markup
    assert 'data-final="ship the health endpoint"' in markup
    assert marker not in markup
    assert "<button" in markup
    child = next(node for node in first["nodes"] if node["parent_id"])
    assert f'data-id="{child["id"]}"' in markup
    assert f'data-parent="{child["parent_id"]}"' in markup
    assert f'data-tokens="{child["tokens"]}"' in markup
    web_agents = _run_async(_web_commands())
    assert any(item["parent_id"] and item["status"] == "completed" for item in web_agents)


async def _web_commands() -> list[dict[str, object]]:
    """HTTP steer and child cancel hit the bound worker. AgentTask writes the run log."""
    import json
    import time
    import uuid

    from sqlalchemy import create_engine, delete
    from sqlalchemy.orm import Session
    from sqlalchemy.pool import NullPool
    from starlette.requests import Request

    from appserver.agent_task import AgentTask
    from appserver.agent_worker import AgentWorker
    from appserver.eventbus import AppendOnlyLog, EventBus
    from protocol.subagents import (
        AgentDefinition,
        AgentMode,
        PermissionSpec,
        PermissionVerdict,
        TaskPermissionSpec,
        TaskRequest,
        ToolPermission,
        TriggerKind,
    )
    from rxycode_server.api.auth import AuthRecord, _hash_token
    from rxycode_server.api.runs import cancel_child_run, steer_run
    from rxycode_server.events.store import replay
    from rxycode_server.persistence.models import Organization, Outbox, Project, Run, RunEvent, SessionRow
    from RxyCode.RxyCode1_1_0.core.subagents.definitions import AgentDefinitionRegistry
    from RxyCode.RxyCode1_1_0.core.subagents.manager import ChildSessionManager
    from RxyCode.RxyCode1_1_0.core.subagents.modes import SubagentConfig, SubagentFeatureFlags
    from RxyCode.RxyCode1_1_0.core.subagents.sessions import create_child_session

    from tests.support.pgurl import ensure_container, worker_url

    _pg_base = "postgresql+psycopg://postgres@127.0.0.1:55432/rxycode"
    ensure_container("rxy-w2c01-pg", 55432)
    database_url = worker_url(_pg_base)
    secret = "local-web-secret-value-32bytes!!"
    origin = "http://test.example"
    tenant = "ten-w6c04-" + uuid.uuid4().hex[:8]
    run_id = "run-w6c04-" + uuid.uuid4().hex[:8]
    old_run_id = "old-" + run_id
    class _App:
        def __init__(self) -> None:
            self.state = type("State", (), {})()

    app = _App()
    app.state.database_url = database_url
    app.state.allowed_origins = (origin,)
    app.state.secret = secret
    app.state.sessions = {}
    token = "c04-session"
    app.state.sessions[_hash_token(secret, token)] = AuthRecord("user-w6c04", tenant, time.monotonic())
    from rxycode_server.persistence.migrate import upgrade_head

    upgrade_head(database_url)
    engine = create_engine(database_url, poolclass=NullPool)
    ids = {"org": "org-" + tenant, "project": "prj-" + tenant, "session": "ses-" + tenant}
    try:
        with Session(engine) as db:
            db.add(Organization(id=ids["org"], tenant_id=tenant))
            db.add(Project(id=ids["project"], tenant_id=tenant, name="c04-" + tenant, repo_config={}))
            db.add(SessionRow(id=ids["session"], tenant_id=tenant, project_id=ids["project"], title="c04"))
            db.add(
                Run(
                    id=old_run_id,
                    tenant_id=tenant,
                    session_id=ids["session"],
                    status="cancelled",
                    revision=99,
                    lease_epoch=0,
                    request_id="old-" + tenant,
                    input_digest="",
                    event_seq=0,
                    target_id="",
                )
            )
            db.add(
                Run(
                    id=run_id,
                    tenant_id=tenant,
                    session_id=ids["session"],
                    status="waiting_approval",
                    revision=0,
                    lease_epoch=0,
                    request_id="req-" + tenant,
                    input_digest="",
                    event_seq=0,
                    target_id="",
                )
            )
            db.commit()
        registry = AgentDefinitionRegistry()
        registry.register_builtin(
            AgentDefinition(
                id="explore",
                description="read",
                mode=AgentMode.SUBAGENT,
                steps=4,
                permission=PermissionSpec(
                    read=ToolPermission.from_raw({"**": "allow"}),
                    edit=ToolPermission.from_raw({"**": "deny"}),
                    external_directory=PermissionVerdict.DENY,
                ),
                task_permission=TaskPermissionSpec(default_verdict=PermissionVerdict.DENY),
            )
        )
        manager = ChildSessionManager(
            registry=registry,
            config=SubagentConfig(
                flags=SubagentFeatureFlags(
                    subagents_enabled=True,
                    subagents_task=True,
                    subagents_mention=True,
                    subagents_child_tasks=True,
                )
            ),
        )
        session_id = ids["session"]
        request = TaskRequest(
            parent_session_id=session_id,
            agent_id="explore",
            prompt="inspect",
            trigger=TriggerKind.AUTOMATIC,
        )
        definition = registry.get("explore")
        child = create_child_session(
            request,
            manager._compute_policy(request, definition),
            definition=definition,
        )
        child.root_session_id = session_id
        manager._tree_for(session_id).add(child)
        cancelled = {"hit": False}

        class _Runtime:
            def cancel(self) -> None:
                cancelled["hit"] = True

        manager._live_runtimes[child.session_id] = _Runtime()
        worker = AgentWorker()

        async def _hold() -> None:
            await asyncio.sleep(30)

        worker._run_task = asyncio.create_task(_hold())
        from rxycode_worker.agent_events import publish_database_url

        publish_database_url(database_url)
        try:
            steered = await steer_run(run_id, _command(app, token, {"text": "steer-web"}))
            assert steered["delivered"] is False
            stopped = await cancel_child_run(run_id, child.session_id, _command(app, token, {}))
            assert stopped["delivered"] is False
            worker.bind_web_session(ids["session"])
            worker.bind_core_session(ids["session"], REPO, lambda _event: None)
            manager.get_tree(ids["session"])
            applied = await worker.drain_web_commands()
            assert worker._web_run_id == run_id
            assert applied
            assert worker._steer_queue == ["steer-web"]
            assert cancelled["hit"] is True
            with Session(engine) as db:
                row = db.get(Run, run_id)
                assert row is not None
                assert row.status == "waiting_approval"
        finally:
            task = worker._run_task
            if task is not None:
                task.cancel()

        async def _work(_task: str, _checkpoint: object | None = None) -> str:
            return "ok"

        from appserver.agent_runtime import AgentConfig, AgentRuntime

        runtime = AgentRuntime(EventBus(AppendOnlyLog()), run_factory=lambda _cfg: _work)
        agent = await runtime.spawn(AgentConfig(agent_id="child-a", mechanical=True))
        if agent._main_task is not None:
            await agent._main_task
        streamed = replay(database_url, tenant_id=tenant, run_id=run_id, after_seq=0)
        names = [item["type"] for item in streamed["events"]]
        assert "event/agent_started" in names
        assert "event/agent_done" in names
        started = next(item for item in streamed["events"] if item["type"] == "event/agent_started")
        assert started["payload"]["agent_id"] == "child-a"
        assert started["payload"]["parent_id"] == ids["session"]
        return _reduce_agents(streamed["events"])
    finally:
        with Session(engine) as db:
            event_ids = [
                row.event_id
                for row in db.query(RunEvent).filter(RunEvent.run_id == run_id).all()
            ]
            if event_ids:
                db.query(Outbox).filter(Outbox.event_id.in_(event_ids)).delete(synchronize_session=False)
            db.execute(delete(RunEvent).where(RunEvent.run_id.in_([run_id, old_run_id])))
            db.execute(delete(Run).where(Run.id.in_([run_id, old_run_id])))
            db.execute(delete(SessionRow).where(SessionRow.id == ids["session"]))
            db.execute(delete(Project).where(Project.id == ids["project"]))
            db.execute(delete(Organization).where(Organization.id == ids["org"]))
            db.commit()
        engine.dispose()
        from rxycode_worker.agent_events import clear_web_run

        clear_web_run()
        os.environ.pop("RXYCODE_WEB_DATABASE_URL", None)


def _command(app: object, token: str, body: dict[str, object]):
    import json

    from starlette.requests import Request

    payload = json.dumps(body).encode("utf-8")

    async def receive() -> dict[str, object]:
        return {"type": "http.request", "body": payload, "more_body": False}

    scope = {
        "type": "http",
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/",
        "raw_path": b"/",
        "query_string": b"",
        "headers": [
            (b"origin", b"http://test.example"),
            (b"x-csrf-token", b"csrf-token"),
            (b"cookie", f"rxy_session={token}; rxy_csrf=csrf-token".encode("ascii")),
            (b"content-type", b"application/json"),
        ],
        "client": ("127.0.0.1", 1234),
        "server": ("test", 80),
        "app": app,
    }
    return Request(scope, receive)


def _reduce_agents(events: list[dict[str, object]]) -> list[dict[str, object]]:
    if BUN is None:
        pytest.skip("bun is not installed")
    component = REPO / "apps" / "web" / "src" / "features" / "runs" / "eventReducer.ts"
    env = os.environ.copy()
    env["RXY_EVENTS"] = json.dumps(events)
    env["RXY_COMPONENT"] = str(component)
    script = r"""
import { pathToFileURL } from "url"
const { reduceEvents } = await import(pathToFileURL(process.env.RXY_COMPONENT).href)
const projection = reduceEvents(JSON.parse(process.env.RXY_EVENTS))
process.stdout.write(JSON.stringify(projection.agents))
"""
    program = Path(tempfile.mkdtemp(prefix="rxy-w6c04-reduce-")) / "reduce.ts"
    program.write_text(script, encoding="utf-8")
    try:
        rendered = subprocess.run(
            [BUN, str(program)],
            cwd=REPO,
            env=env,
            text=True,
            capture_output=True,
            check=False,
            timeout=60,
        )
    finally:
        program.unlink(missing_ok=True)
    assert rendered.returncode == 0, rendered.stderr
    return json.loads(rendered.stdout)


async def _steer_pair(run_id: str, store: object) -> tuple[dict[str, object], dict[str, object], list[str]]:
    import asyncio

    from appserver.agent_worker import AgentWorker
    from rxycode_worker.agent_events import accept_steer

    worker = AgentWorker()
    worker._session_id = run_id

    async def _hold() -> None:
        await asyncio.sleep(30)

    worker._run_task = asyncio.create_task(_hold())
    try:
        one = await accept_steer(run_id=run_id, text="steer-one", worker=worker, store=store)
        two = await accept_steer(run_id=run_id, text="steer-two", worker=worker, store=store)
        return one, two, list(worker._steer_queue)
    finally:
        task = worker._run_task
        if task is not None:
            task.cancel()


def _round_trip(span: object) -> object:
    from RxyCode.RxyCode1_1_0.core.tracing import NodeSpan

    return NodeSpan.from_dict(span.to_dict())  # type: ignore[attr-defined]


def _render(nodes: list[dict[str, object]], final_text: str) -> str:
    if BUN is None:
        pytest.skip("bun is not installed")
    env = os.environ.copy()
    env["RXY_NODES"] = json.dumps(nodes)
    env["RXY_FINAL"] = final_text
    component = REPO / "apps" / "web" / "src" / "features" / "agents" / "AgentTree.tsx"
    env["RXY_COMPONENT"] = str(component)
    script = r"""
import { createRequire } from "module"
import { pathToFileURL } from "url"
const require = createRequire(pathToFileURL(process.env.RXY_COMPONENT).href)
const React = require(require.resolve("react", { paths: [process.cwd() + "/apps/web"] }))
const { renderToStaticMarkup } = require(require.resolve("react-dom/server", { paths: [process.cwd() + "/apps/web"] }))
const { AgentTree } = await import(pathToFileURL(process.env.RXY_COMPONENT).href)
const html = renderToStaticMarkup(React.createElement(AgentTree, {
  nodes: JSON.parse(process.env.RXY_NODES),
  finalText: process.env.RXY_FINAL,
}))
process.stdout.write(html)
"""
    program = Path(tempfile.mkdtemp(prefix="rxy-w6c04-ui-")) / "render.ts"
    program.write_text(script, encoding="utf-8")
    try:
        rendered = subprocess.run(
            [BUN, str(program)],
            cwd=REPO,
            env=env,
            text=True,
            capture_output=True,
            check=False,
            timeout=60,
        )
    finally:
        program.unlink(missing_ok=True)
    assert rendered.returncode == 0, rendered.stderr
    return rendered.stdout


def _render_legacy() -> str:
    if BUN is None:
        pytest.skip("bun is not installed")
    component = REPO / "apps" / "web" / "src" / "features" / "agents" / "AgentTree.tsx"
    script = r"""
import { createRequire } from "module"
import { pathToFileURL } from "url"
const require = createRequire(pathToFileURL(process.env.RXY_COMPONENT).href)
const React = require(require.resolve("react", { paths: [process.cwd() + "/apps/web"] }))
const { renderToStaticMarkup } = require(require.resolve("react-dom/server", { paths: [process.cwd() + "/apps/web"] }))
const { AgentTree } = await import(pathToFileURL(process.env.RXY_COMPONENT).href)
const html = renderToStaticMarkup(React.createElement(AgentTree, {
  agents: [{ id: "coder", name: "coder", status: "running", cost: "0" }],
}))
process.stdout.write(html)
"""
    program = Path(tempfile.mkdtemp(prefix="rxy-w6c04-legacy-")) / "render.ts"
    program.write_text(script, encoding="utf-8")
    env = os.environ.copy()
    env["RXY_COMPONENT"] = str(component)
    try:
        rendered = subprocess.run(
            [BUN, str(program)],
            cwd=REPO,
            env=env,
            text=True,
            capture_output=True,
            check=False,
            timeout=60,
        )
    finally:
        program.unlink(missing_ok=True)
    assert rendered.returncode == 0, rendered.stderr
    return rendered.stdout
