"""layer=unit FR-SS-0"""
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
RESEARCH = REPO / "docs/plans/opus5-plan/rxycode/research/2026-09-15-session-list-opencode-grok.md"
PHASE = REPO / "docs/plans/opus5-plan/rxycode/PHASE-UPDATE-01.md"
DEV = REPO / "docs/plans/opus5-plan/rxycode/architecture/DEV-ORDER.md"

NEEDLES_RESEARCH = [
    "generated_title",
    "title_is_manual",
    "ctrl+d",
    "ctrl+r",
    "ctrl+f",
    "Today",
    "sessions/list",
    "chat_storage",
    "thread/pin",
]
NEEDLES_PHASE = [
    "轨 H",
    "U51",
    "FR-SS-1",
    "format_session_age",
    "maybe_generate_session_title",
    "DialogSessionList",
    "SESSION_DEFAULT_TITLE",
    "ctrl+shift+f",
]


def test_session_list_research_needles():
    body = RESEARCH.read_text(encoding="utf-8")
    for n in NEEDLES_RESEARCH:
        assert n in body, n


def test_update01_track_h_hooks():
    phase = PHASE.read_text(encoding="utf-8")
    for n in NEEDLES_PHASE:
        assert n in phase, n
    assert "### U38 · 有活前缀" in phase
    u38 = phase.split("### U38 · 有活前缀", 1)[1].split("### U39 ·", 1)[0]
    assert "format_session_age" not in u38
    assert "sessions/list" not in u38
    u47 = phase.split("### U47 ·", 1)[1].split("### U48 ·", 1)[0]
    assert "PHASE-UPDATE-02.md" not in u47
    assert "chat_storage" in phase


def test_dev_order_splits_session_catalog():
    dev = DEV.read_text(encoding="utf-8")
    assert "U47" in dev and "U51" in dev
    assert "session-catalog" in dev or "会话列表" in dev
