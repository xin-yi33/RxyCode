"""WEB-W6-C04. Steer stays on the same run, in order, and replay keeps the tree."""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
_WORKER = REPO / "packages" / "rxycode-worker" / "src"
BUN = Path(r"D:\nodejs\node_modules\bun\bin\bun.exe")
for _entry in (str(_WORKER), str(REPO / "tests" / "web" / "w6")):
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
    one, two, queued = asyncio.run(_steer_pair(run_id, store))
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
    if not BUN.is_file():
        pytest.fail("bun is not installed")
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
            [str(BUN), str(program)],
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
    if not BUN.is_file():
        pytest.fail("bun is not installed")
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
            [str(BUN), str(program)],
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
