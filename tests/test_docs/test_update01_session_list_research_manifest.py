"""layer=unit FR-SS-0"""
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
RESEARCH = REPO / "docs/plans/opus5-plan/rxycode/research/2026-09-15-session-list-opencode-grok.md"
PHASE = REPO / "docs/plans/opus5-plan/rxycode/PHASE-UPDATE-01.md"
DEV = REPO / "docs/plans/opus5-plan/rxycode/architecture/DEV-ORDER.md"


def _phase_body() -> str:
    # PHASE-UPDATE-01 是 gitignored 计划文档，发布件/外部工作树中可能缺失或
    # 为空（2026-10-07 验收：本工作树为 0 字节）——缺失即跳过，不虚构内容
    # 求绿；可分发契约断言应落在协议/实现上（RESEARCH 断言不受影响）。
    text = PHASE.read_text(encoding="utf-8") if PHASE.is_file() else ""
    if not text.strip():
        pytest.skip("PHASE-UPDATE-01.md 不在发布件内（缺失或为空），计划清单契约不适用")
    return text

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
    phase = _phase_body()
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
