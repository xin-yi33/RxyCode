"""layer=unit FR-DU-0"""
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
RESEARCH = REPO / "docs/plans/opus5-plan/rxycode/research/2026-09-15-session-durability-snapshots-loop-timeout.md"
PHASE = REPO / "docs/plans/opus5-plan/rxycode/PHASE-UPDATE-01.md"
DEV = REPO / "docs/plans/opus5-plan/rxycode/architecture/DEV-ORDER.md"

NEEDLES_RESEARCH = [
    "transcript",
    "checkpointId",
    "rollout",
    "scheduler_create",
    "durable",
    "workflow_tool",
    "retain_history_on_model_change",
    "classify_durable_layer",
    "loop_replays_killed_foreground_bash",
    "restore_after_restart",
]
NEEDLES_PHASE = [
    "轨 K",
    "U68",
    "FR-DU-1",
    "BASH_DEFAULT_TIMEOUT_SECONDS",
    "retain_history_on_model_change",
    "restore_after_restart",
    "classify_durable_layer",
    "should_use_workflow_not_bash",
    "UPI-22",
]


def test_session_durability_research_needles():
    body = RESEARCH.read_text(encoding="utf-8")
    for n in NEEDLES_RESEARCH:
        assert n in body, n


def test_update01_track_k_hooks():
    phase = PHASE.read_text(encoding="utf-8")
    for n in NEEDLES_PHASE:
        assert n in phase, n
    assert "### U62 · 轨 J" in phase
    u62 = phase.split("### U62 ·", 1)[1].split("### U63 ·", 1)[0]
    assert "BASH_DEFAULT_TIMEOUT_SECONDS" not in u62
    assert "retain_history_on_model_change" not in u62
    u63_head = phase.split("### U63 ·", 1)[1].split("**单元测试**", 1)[0]
    assert "PHASE-UPDATE-02.md" not in u63_head


def test_dev_order_splits_session_durability():
    dev = DEV.read_text(encoding="utf-8")
    assert "U63" in dev and "U68" in dev
    assert "session-durability" in dev or "落盘" in dev


def test_track_k2_hooks():
    phase = PHASE.read_text(encoding="utf-8")
    assert "### U69 ·" in phase and "### U72 ·" in phase
    assert "workspace_snapshot_store_is_durable" in phase
    assert "SNAPSHOT_KEEP_CHECKPOINTS" in phase
    assert "UPI-23" in phase
    u68 = phase.split("### U68 ·", 1)[1].split("### U69 ·", 1)[0]
    assert "workspace_snapshot_store_is_durable" not in u68
    research = RESEARCH.read_text(encoding="utf-8")
    assert "workspace_snapshot_store_is_durable" in research
    assert "SNAPSHOT_KEEP_CHECKPOINTS" in research
    assert "Field(default=60)" in research
    assert "突然关机" in research
