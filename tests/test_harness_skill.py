"""PhaseG-B15 HARNESS skills. Do not mock Phase B cache as landed."""

from __future__ import annotations

from pathlib import Path

from appserver.cli_hub_service import CliHubService
from appserver.harness_service import (
    CACHE_BASELINE,
    COMMANDS,
    HARNESS_LICENSE,
    HARNESS_MD,
    STAGES,
    HarnessService,
    phase_b_cache_status,
)


def test_phase_b_cache_gate_is_honest() -> None:
    status = phase_b_cache_status()
    assert CACHE_BASELINE.is_file()
    assert status["source"] == str(CACHE_BASELINE)
    assert status["hit_rate"] < status["floor"]
    assert status["landed"] is False
    assert status["error_code"] == "BLOCKED_PREREQUISITE"


def test_generate_refine_blocked_without_mocking_cache(tmp_path: Path) -> None:
    hub = CliHubService(root=tmp_path, registry={})
    service = HarnessService(hub=hub)
    generated = service.generate("paint")
    assert generated["ok"] is False
    assert generated["error_code"] == "BLOCKED_PREREQUISITE"
    refined = service.refine("paint")
    assert refined["error_code"] == "BLOCKED_PREREQUISITE"
    failures = hub.list_generate_failures("paint")["failures"]
    assert [row["stage"] for row in failures] == ["generate", "refine"]


def test_vendor_harness_and_license() -> None:
    service = HarnessService()
    vendor = service.vendor_status()
    assert vendor["present"] is True
    assert vendor["has_apache"] is True
    text = HARNESS_MD.read_text(encoding="utf-8")
    assert "Phase 1: Codebase Analysis" in text
    assert "Apache-2.0" in text or "Apache License" in HARNESS_LICENSE.read_text(encoding="utf-8")
    assert "HKUDS" in text or "CLI-Anything" in text


def test_seven_stage_and_commands_trigger() -> None:
    service = HarnessService()
    listed = service.list_skills()
    assert listed["stages"] == list(STAGES)
    assert listed["commands"] == list(COMMANDS)
    for name in (*STAGES, *COMMANDS):
        triggered = service.trigger(name)
        assert triggered["ok"] is True
        assert triggered["subtask"] is True
        assert "HARNESS.md" in triggered["text"] or "subtask" in triggered["text"]
    validated = service.validate("paint")
    assert validated["vendor_ok"] is True
    assert validated["missing_skills"] == []
    assert validated["error_code"] == "BLOCKED_PREREQUISITE"
    assert validated["ok"] is False


def test_handwritten_wrapper_blocked_by_c8(tmp_path: Path) -> None:
    hub = CliHubService(root=tmp_path, registry={})
    service = HarnessService(hub=hub)
    result = service.handwritten_wrapper("wrap-demo", tmp_path / "pkg")
    assert result["ok"] is False
    assert result["error_code"] == "BLOCKED_PREREQUISITE"
    assert result["ladder"] == "handwritten-wrapper"
    assert hub.list_generate_failures("wrap-demo")["failures"][-1]["stage"] == "handwritten-wrapper"
