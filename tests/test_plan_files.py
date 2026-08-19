"""GX9-B: plan/persist + plan/implement under RXYCODE_DATA_DIR."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from appserver.plan_files import PlanFileError, PlanFileService
from appserver.server import AppServer
from protocol.requests import PlanImplementRequest, PlanPersistRequest


def test_protocol_methods() -> None:
    assert PlanPersistRequest.model_fields["method"].default == "plan/persist"
    assert PlanImplementRequest.model_fields["method"].default == "plan/implement"


def test_persist_three_sections_and_implement(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("RXYCODE_DATA_DIR", str(tmp_path))
    svc = PlanFileService()
    saved = svc.persist(
        thread_id="t1",
        title="Ship GX9",
        goal="Persist plans",
        steps=["write markdown", "implement"],
        acceptance=["three sections"],
    )
    path = Path(saved["path"])
    assert path.parent == tmp_path / "plans"
    text = path.read_text(encoding="utf-8")
    assert "## 目标" in text
    assert "## 步骤" in text
    assert "## 验收清单" in text
    assert os.environ["RXYCODE_DATA_DIR"] in saved["path"]
    with pytest.raises(PlanFileError, match="confirm"):
        svc.implement(plan_id=saved["plan_id"], confirm=False)
    started = svc.implement(plan_id=saved["plan_id"], confirm=True)
    assert started["status"] == "implementing"
    assert "first-turn context" in started["turn_prompt"]


@pytest.mark.asyncio
async def test_appserver_plan_rpc(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("RXYCODE_DATA_DIR", str(tmp_path))
    sent: list[dict] = []

    async def capture(message: dict) -> None:
        sent.append(message)

    monkeypatch.setattr("appserver.server.write_message", capture)
    server = AppServer(stub=True)
    server._initialized = True
    await server._dispatch(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "plan/persist",
            "params": {
                "thread_id": "th",
                "title": "Demo",
                "goal": "g",
                "steps": ["s1"],
                "acceptance": ["a1"],
            },
        }
    )
    saved = next(item["result"] for item in sent if item.get("id") == 1)
    sent.clear()
    await server._dispatch(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "plan/implement",
            "params": {"plan_id": saved["plan_id"], "confirm": True},
        }
    )
    started = next(item["result"] for item in sent if item.get("id") == 2)
    assert started["status"] == "implementing"


def test_no_handlers_package() -> None:
    assert not (Path(__file__).resolve().parents[1] / "appserver" / "handlers").exists()
