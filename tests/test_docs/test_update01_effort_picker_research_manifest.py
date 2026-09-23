"""layer=unit FR-EF-0"""
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
RESEARCH = REPO / "docs/plans/opus5-plan/rxycode/research/2026-09-15-effort-variant-opencode.md"
PHASE = REPO / "docs/plans/opus5-plan/rxycode/PHASE-UPDATE-01.md"
DEV = REPO / "docs/plans/opus5-plan/rxycode/architecture/DEV-ORDER.md"

NEEDLES_RESEARCH = [
    "Select effort",
    "Default",
    "shouldOpenEffortPicker",
    "/variant",
    "/effort",
    "addmodel",
    "formatHeaderLine",
]
NEEDLES_PHASE = [
    "轨 I",
    "U56",
    "FR-EF-1",
    "SELECT_EFFORT_TITLE",
    "buildEffortPickerOptions",
    "formatComposerEffortChip",
    "effortOnDismiss",
]


def test_effort_research_needles():
    body = RESEARCH.read_text(encoding="utf-8")
    for n in NEEDLES_RESEARCH:
        assert n in body, n


def test_update01_track_i_hooks():
    phase = PHASE.read_text(encoding="utf-8")
    for n in NEEDLES_PHASE:
        assert n in phase, n
    assert "### U50 · OpenTUI session list" in phase
    u50 = phase.split("### U50 · OpenTUI session list", 1)[1].split("### U51 ·", 1)[0]
    assert "SELECT_EFFORT_TITLE" not in u50
    u52 = phase.split("### U52 ·", 1)[1].split("### U53 ·", 1)[0]
    assert "PHASE-UPDATE-02.md" not in u52
    assert "/variant" in phase


def test_dev_order_splits_effort_picker():
    dev = DEV.read_text(encoding="utf-8")
    assert "U52" in dev and "U56" in dev
    assert "effort-picker" in dev or "/effort" in dev
