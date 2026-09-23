"""layer=unit FR-MA-0"""
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
RESEARCH = REPO / "docs/plans/opus5-plan/rxycode/research/2026-09-15-message-actions-opencode.md"
PHASE = REPO / "docs/plans/opus5-plan/rxycode/PHASE-UPDATE-01.md"
DEV = REPO / "docs/plans/opus5-plan/rxycode/architecture/DEV-ORDER.md"

NEEDLES_RESEARCH = [
    "Message Actions",
    "shouldOpenMessageActions",
    "hitTestUserBubble",
    "ctrl+x r",
    "thread/fork",
    "session/fork",
    "undo messages and file changes",
    "assertNotBusy",
    "session.abort",
    "#14014",
]
NEEDLES_PHASE = [
    "轨 J",
    "U62",
    "FR-MA-1",
    "MESSAGE_ACTIONS_TITLE",
    "shouldOpenMessageActions",
    "formatRevertBanner",
    "visible_messages",
    "revertNeedsAbort",
    "FR-MA-7",
]


def test_message_actions_research_needles():
    body = RESEARCH.read_text(encoding="utf-8")
    for n in NEEDLES_RESEARCH:
        assert n in body, n


def test_update01_track_j_hooks():
    phase = PHASE.read_text(encoding="utf-8")
    for n in NEEDLES_PHASE:
        assert n in phase, n
    assert "### U56 · 轨 I" in phase
    u56 = phase.split("### U56 · 轨 I", 1)[1].split("### U57 ·", 1)[0]
    assert "MESSAGE_ACTIONS_TITLE" not in u56
    u57 = phase.split("### U57 ·", 1)[1].split("### U58 ·", 1)[0]
    assert "PHASE-UPDATE-02.md" not in u57
    assert "session/fork" in phase


def test_dev_order_splits_message_actions():
    dev = DEV.read_text(encoding="utf-8")
    assert "U57" in dev and "U62" in dev
    assert "message-actions" in dev or "Message Actions" in dev
