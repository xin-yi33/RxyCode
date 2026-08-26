"""F12 team replay tree + J3 distillation probes."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from RxyCode.RxyCode1_1_0.core.agents.coordinator import Coordinator
from RxyCode.RxyCode1_1_0.core.agents.teams import load_builtin_team
from RxyCode.RxyCode1_1_0.core.session import Session
from RxyCode.RxyCode1_1_0.core.tracing import (
    LlmCallRecord,
    _record_safely,
    distillation_ui_notice,
    format_current_role,
    format_team_tree,
    replay,
)
from RxyCode.RxyCode1_1_0.protocol.agents import ConsultRequest, TeamEvent
from RxyCode.RxyCode1_1_0.protocol.notifications import ProgressUpdate


class _Pass:
    def run(self, stage, result):
        return type("V", (), {"passed": True, "findings": []})()


def _coord(tmp_path: Path, session_id: str = "ses-f12") -> Coordinator:
    coord = Coordinator(
        Session(session_id=session_id, workspace_root=tmp_path, emit=lambda _n: None),
        verifier=_Pass(),
    )
    coord.verdict_allows = lambda _digest: True  # type: ignore[method-assign]
    return coord


def test_replay_tree_includes_consult_and_verify(tmp_path: Path) -> None:
    import asyncio

    coord = _coord(tmp_path)
    asyncio.run(coord.run_team(load_builtin_team(), "add health"))
    coord.consult(
        load_builtin_team(),
        ConsultRequest(
            session_id="ses-f12",
            request_id="q1",
            from_role="backend_coder",
            to_role="architect",
            question="方案里没提到迁移脚本",
            stage="implement",
        ),
        answer="补一节",
    )
    spans = coord._tracer.get_spans()
    tree = format_team_tree(spans)
    assert "team=software_dev" in tree
    assert "decided_by=" in tree
    assert "budget:" in tree
    assert "/" in tree.split("budget:", 1)[1]
    assert "delegations" in tree
    assert "[consult]" in tree
    assert "[verify]" in tree
    assert coord.current_role_display
    assert "@" in coord.current_role_display
    consult = next(s for s in spans if s.kind == "consult")
    parent = next(s for s in spans if s.span_id == consult.parent_id)
    assert parent.kind == "delegate"
    assert parent.stage == "implement"
    assert any(s.kind == "audit" for s in spans)


def test_replay_show_team_cli(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    import asyncio

    coord = _coord(tmp_path)
    asyncio.run(coord.run_team(load_builtin_team(), "x"))
    replay("ses-f12", show_team=True, session="ses-f12")
    out = capsys.readouterr().out
    assert "session ses-f12" in out
    assert "software_dev" in out


def test_stage_started_event_exposes_role(tmp_path: Path) -> None:
    import asyncio

    events: list[object] = []
    coord = Coordinator(
        Session(session_id="ses-f12b", workspace_root=tmp_path, emit=events.append),
        verifier=_Pass(),
    )
    coord.verdict_allows = lambda _digest: True  # type: ignore[method-assign]
    asyncio.run(coord.run_team(load_builtin_team(), "y"))
    team_events = [e for e in events if isinstance(e, TeamEvent) and e.phase == "stage_started"]
    assert team_events
    assert team_events[0].role
    assert format_current_role(coord._tracer.get_spans()[-1])
    progress = [e.text for e in events if isinstance(e, ProgressUpdate)]
    assert any(text.startswith("[") and "]" in text for text in progress)


def test_distillation_off_writes_nothing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RXYCODE_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(
        "RxyCode.RxyCode1_1_0.core.tracing.load_config",
        lambda: {"distillation": {"collect": False}},
    )

    def _no_io(*_a, **_k):
        raise AssertionError("collect=False must not touch the filesystem")

    monkeypatch.setattr("RxyCode.RxyCode1_1_0.core.tracing.get_data_dir", _no_io)
    _record_safely(
        LlmCallRecord(role="coder", stage="implement", model="x", provider="y", session_id="s1")
    )
    dist = tmp_path / "distillation"
    assert not dist.exists()
    assert distillation_ui_notice() is None


def test_distillation_on_writes_jsonl(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RXYCODE_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(
        "RxyCode.RxyCode1_1_0.core.tracing.load_config",
        lambda: {"distillation": {"collect": True}},
    )
    _record_safely(
        LlmCallRecord(
            role="coder",
            stage="implement",
            model="m",
            provider="p",
            session_id="s1",
            response="ok",
        )
    )
    files = list((tmp_path / "distillation").rglob("*.jsonl"))
    assert files
    line = files[0].read_text(encoding="utf-8").strip().splitlines()[0]
    row = json.loads(line)
    assert row["role"] == "coder"
    assert row["response"] == "ok"
    notice = distillation_ui_notice()
    assert notice and "蒸馏" in notice


def test_distillation_notice_is_emitted_to_progress_ui(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import asyncio

    monkeypatch.setattr(
        "RxyCode.RxyCode1_1_0.core.agents.coordinator.distillation_ui_notice",
        lambda: "蒸馏采集已打开：本会话的模型输入/输出会写入本地 distillation JSONL",
    )
    events: list[object] = []
    coord = Coordinator(
        Session(session_id="ses-j3", workspace_root=tmp_path, emit=events.append),
        verifier=_Pass(),
    )
    coord.verdict_allows = lambda _digest: True  # type: ignore[method-assign]
    asyncio.run(coord.run_team(load_builtin_team(), "z"))
    texts = [e.text for e in events if isinstance(e, ProgressUpdate)]
    assert any("蒸馏" in text for text in texts)


def test_distillation_write_failure_is_swallowed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("RXYCODE_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(
        "RxyCode.RxyCode1_1_0.core.tracing.load_config",
        lambda: {"distillation": {"collect": True}},
    )

    def boom(*_a, **_k):
        raise OSError("disk full")

    monkeypatch.setattr("builtins.open", boom)
    _record_safely(
        LlmCallRecord(role="a", stage="b", model="m", provider="p", session_id="s")
    )
