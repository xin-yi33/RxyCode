"""WEB-W0-C03. Session reuse is the shipped core.session path."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
from pydantic import BaseModel

from protocol.notifications import FinalAnswer

REPO = Path(__file__).resolve().parents[3]
PLAN = REPO / "docs" / "plans" / "opus5-plan" / "rxycode -web"


def _scanner():
    path = PLAN / "scripts" / "check_plan.py"
    spec = importlib.util.spec_from_file_location("rxycode_web_check_plan_c03", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _PromptAgent:
    def __init__(self) -> None:
        self._thinking_history: list[str] = []
        self._last_thinking = ""

    async def run(self, text: str, mode: str = "build") -> str:
        return text


def _final_texts(events: list[BaseModel]) -> list[str]:
    return [item.text for item in events if isinstance(item, FinalAnswer)]


@pytest.mark.asyncio
async def test_w0_c03_contract(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """A second prompt on the same session keeps runtimes and uses the new emit."""
    from core.session import reuse_or_create_session

    monkeypatch.setenv("RXYCODE_DATA_DIR", str(tmp_path / "data"))
    workspace = tmp_path / "ws"
    workspace.mkdir()
    first_emit: list[BaseModel] = []
    second_emit: list[BaseModel] = []
    first = reuse_or_create_session(
        None,
        session_id="ses-c03",
        workspace_root=workspace,
        emit=first_emit.append,
    )
    marker = object()
    first.agent_runtimes["architect"] = marker
    agent = _PromptAgent()
    first_result = await first.prompt(agent, "one", mode="build", run_id="run-1")
    assert first_result.answer == "one"
    second = reuse_or_create_session(
        first,
        session_id="ses-c03",
        workspace_root=workspace,
        emit=second_emit.append,
    )
    assert second is first
    assert second.agent_runtimes["architect"] is marker
    second_result = await second.prompt(agent, "two", mode="build", run_id="run-2")
    assert second_result.answer == "two"
    assert second.agent_runtimes["architect"] is marker
    assert _final_texts(second_emit) == ["two"]
    assert "two" not in _final_texts(first_emit)
    assert _final_texts(first_emit) == ["one"]


def test_w0_c03_negative(tmp_path: Path):
    """A missing baseline test file is BLOCKED, not a skipped pass."""
    missing = _scanner().baseline_file_status(tmp_path / "missing_baseline_test.py")
    assert missing == "BLOCKED"
    present = _scanner().baseline_file_status(
        REPO / "tests" / "test_cache" / "test_s1_s2_split.py"
    )
    assert present == "PRESENT"
