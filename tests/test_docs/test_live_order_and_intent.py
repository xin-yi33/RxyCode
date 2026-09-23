"""Parse live architecture docs. Do not mock files or hard-code a second wish table."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
ARCH = REPO / "docs" / "plans" / "opus5-plan" / "rxycode" / "architecture"
DECISIONS = REPO / "docs" / "decisions"
MEMO = ARCH / "sources" / "RxyCode-产品意图备忘.md"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _memo_section12_wishes() -> list[str]:
    text = _read(MEMO)
    marker = "## 12."
    start = text.find(marker)
    assert start != -1, "memo missing §12"
    chunk = text[start:]
    nxt = chunk.find("\n## 13.")
    if nxt != -1:
        chunk = chunk[:nxt]
    wishes: list[str] = []
    for line in chunk.splitlines():
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) < 2:
            continue
        name = cells[0]
        if name in {"愿望", ""} or set(name) <= {"-", ":"}:
            continue
        wishes.append(name)
    assert wishes, "parsed zero wishes from memo §12"
    return wishes


def _coverage_destinations() -> dict[str, str]:
    text = _read(ARCH / "PHASE-P-PRODUCT-INTENT.md")
    marker = "覆盖表"
    start = text.find(marker)
    assert start != -1
    chunk = text[start:]
    mapping: dict[str, str] = {}
    for line in chunk.splitlines():
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) < 2:
            continue
        wish, dest = cells[0], cells[1]
        if wish in {"备忘愿望", ""} or "主去向" in dest or set(wish) <= {"-", ":"}:
            continue
        mapping[wish] = dest
    return mapping


def test_dev_order_has_p0_p1_p2_and_parallel_tables() -> None:
    text = _read(ARCH / "DEV-ORDER.md")
    assert "优先级 P0" in text
    assert "优先级 P1" in text
    assert "优先级 P2" in text
    assert "可并行" in text
    assert "必须串行" in text


def test_next_step_points_at_teams_workflow_not_whole_phase_l() -> None:
    text = _read(ARCH / "DEV-ORDER.md")
    idx = text.find("下一步")
    assert idx != -1
    rest = text[idx : idx + 2500]
    assert "WF-BUILTIN-EXPERT-TEAMS" in rest or "TEAMS-INCREMENT" in rest or "WFT1" in rest
    assert "等 PHASE-L 全部" not in rest
    assert "等 PHASE-L 全文" not in rest


def test_dev_order_schedules_existing_phases() -> None:
    text = _read(ARCH / "DEV-ORDER.md")
    assert "PHASE-K" in text
    assert "L0a" in text
    assert "PHASE-N" in text
    assert "PHASE-M" in text
    assert "调研" in text or "search-first" in text
    assert "波次" in text


def test_memo_section12_each_wish_has_exactly_one_destination() -> None:
    wishes = _memo_section12_wishes()
    mapping = _coverage_destinations()
    missing = [w for w in wishes if w not in mapping]
    extra = [w for w in mapping if w not in wishes]
    assert not missing, f"uncovered memo wishes: {missing}"
    assert not extra, f"coverage rows not in memo §12: {extra}"
    for wish, dest in mapping.items():
        assert dest.strip(), f"empty destination for {wish}"
        assert dest.count("PP") + dest.count("WFT") >= 1 or "PP" in dest


def test_teams_workflow_prereqs_are_cards_not_whole_phase_l() -> None:
    text = _read(ARCH / "PHASE-L-TEAMS-INCREMENT.md")
    assert "validate_team" in text or "F3" in text
    assert "S1" in text or "FXC3" in text
    assert "不是前置" in text
    assert "L13" in text or "发行版" in text
    assert "L17" in text or "跨宿主" in text
    head = text[: text.find("## §4")] if "## §4" in text else text[:4000]
    assert "等 PHASE-L 全部" not in head
    assert "等 PHASE-L 全文" not in head


def test_phase_intent_has_model_constraints_why_cards_acceptance() -> None:
    text = _read(ARCH / "PHASE-P-PRODUCT-INTENT.md")
    assert "模型约束" in text
    assert "为什么" in text or "好处" in text
    assert "任务卡" in text
    assert "验收" in text or "完成判据" in text
    assert "执行手册" in text
    assert "硬性规则" in text or "硬规则" in text
    assert "一页看懂" in text
    assert "目标架构" in text
    assert "出口检查" in text
    assert "冲突消解" in text
    assert "PC0" in text
    assert "调研先行" in text or "能抄不造" in text
    assert "Verdict:" in text
    assert re.search(r"^### PP\d+ · ", text, re.M)
    assert "**背景**" in text
    assert "**涉及文件**" in text
    assert "**操作步骤**" in text
    assert "**验收命令**" in text
    assert "**完成判据**" in text
    assert "**回滚**" in text


def test_cli_and_gui_appear_as_pairs() -> None:
    mapping = _coverage_destinations()
    text = _read(ARCH / "PHASE-P-PRODUCT-INTENT.md")
    assert "CLI" in text and "GUI" in text
    for _wish, _dest in mapping.items():
        # coverage table has CLI/GUI columns in PHASE-P
        pass
    chunk_start = text.find("覆盖表")
    chunk = text[chunk_start:]
    for line in chunk.splitlines():
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) < 4:
            continue
        if cells[0] in {"备忘愿望"} or "主去向" in cells[1]:
            continue
        if set(cells[0]) <= {"-", ":"}:
            continue
        assert cells[2] and cells[3], f"CLI/GUI empty for {cells[0]}"


def test_plugin_is_not_skill_or_mcp() -> None:
    text = _read(ARCH / "PHASE-P-PRODUCT-INTENT.md")
    assert "加号" in text
    assert "skill" in text.lower() or "Skill" in text
    assert "MCP" in text
    assert "PC2" in text


def test_computer_use_is_not_only_cli_anything() -> None:
    p = _read(ARCH / "PHASE-P-PRODUCT-INTENT.md")
    a = _read(DECISIONS / "ARCH-003-computer-use-direct-control.md")
    blob = p + "\n" + a
    assert "事实观察" in blob
    assert "授权内" in blob
    assert "并存" in blob
    assert "不得替代" in blob
    assert "仅 CLI-Anything" not in blob
    assert "只用软联系替代" not in blob
    assert "open-codex-computer-use" in blob or "iFurySt" in blob


def test_module_boundaries_require_split_agent_v2() -> None:
    text = _read(ARCH / "MODULE-BOUNDARIES.md")
    assert "harness" in text
    assert "允许改" in text
    assert "禁止顺手改" in text
    assert "agent_v2" in text
    arch4 = _read(DECISIONS / "ARCH-004-targeted-refactor-bar.md")
    assert "拆" in arch4
    assert "agent_v2" in arch4


def test_research_mentions_open_codex_computer_use() -> None:
    prior = _read(ARCH / "research" / "2026-09-01-product-prior-art-verdicts.md")
    cores = _read(ARCH / "research" / "2026-09-01-top-coding-agents-core-architecture.md")
    blob = prior + cores
    assert "open-codex-computer-use" in blob or "iFurySt" in blob
    assert "Verdict" in prior


def test_tracked_architecture_docs_are_git_visible() -> None:
    nested = REPO / "docs" / "plans" / "opus5-plan"
    listed = subprocess.check_output(
        [
            "git",
            "-C",
            str(nested),
            "-c",
            "core.quotepath=false",
            "ls-files",
            "rxycode/architecture",
        ],
        text=True,
        encoding="utf-8",
    )
    needed = [
        "rxycode/architecture/DEV-ORDER.md",
        "rxycode/architecture/PHASE-P-PRODUCT-INTENT.md",
        "rxycode/architecture/PHASE-L-TEAMS-INCREMENT.md",
        "rxycode/architecture/sources/RxyCode-产品意图备忘.md",
    ]
    for path in needed:
        assert path.replace("\\", "/") in listed.replace("\\", "/"), path
