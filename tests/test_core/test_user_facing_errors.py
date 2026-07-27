"""Tests for user-facing error message mapping (E2/E3/E8)."""

from __future__ import annotations

import re

import pytest

FORBIDDEN = re.compile(
    r"synthesizer|claim\s*manifest|grounded\s*claims?",
    re.IGNORECASE,
)


def _assert_friendly(raw: str, friendly: str) -> None:
    assert friendly
    assert not FORBIDDEN.search(friendly), friendly
    assert "manifest" not in friendly.lower()
    assert "grounded" not in friendly.lower()


class TestToUserFacingError:
    def _map(self, raw: str) -> str:
        from RxyCode.RxyCode1_1_0.utils.user_facing_errors import to_user_facing_error

        return to_user_facing_error(raw)

    def test_build_incomplete_generic(self):
        raw = "[Build incomplete: Task not verified: deploy (failed)]"
        friendly = self._map(raw)
        _assert_friendly(raw, friendly)
        assert "构建流程未完成" in friendly

    def test_grounded_claims_issue(self):
        raw = "[Build incomplete: Synthesizer produced no grounded claims]"
        friendly = self._map(raw)
        _assert_friendly(raw, friendly)
        assert "构建流程未完成" in friendly or "校验" in friendly

    def test_claim_manifest_issue(self):
        raw = (
            "[Build incomplete: Synthesis answer contains text outside "
            "its claim manifest]"
        )
        friendly = self._map(raw)
        _assert_friendly(raw, friendly)

    def test_synthesizer_structured_output_error(self):
        raw = "[Build incomplete: Synthesizer output was not valid grounded JSON.]"
        friendly = self._map(raw)
        _assert_friendly(raw, friendly)

    def test_evidence_failed(self):
        raw = "[evidence failed: Tool bash did not complete: failed]"
        friendly = self._map(raw)
        _assert_friendly(raw, friendly)
        assert "工具执行中断" in friendly

    def test_tool_did_not_complete(self):
        raw = "[evidence failed: Tool read did not complete: cancelled]"
        friendly = self._map(raw)
        _assert_friendly(raw, friendly)
        assert "工具执行中断" in friendly

    def test_timeout(self):
        raw = "TimeoutError: operation timed out after 600s"
        friendly = self._map(raw)
        _assert_friendly(raw, friendly)
        assert "超时" in friendly

    def test_cancelled(self):
        raw = "Cancelled"
        friendly = self._map(raw)
        _assert_friendly(raw, friendly)
        assert "取消" in friendly

    def test_unknown_internal_jargon_stripped(self):
        raw = "Synthesizer grounding failed: malformed manifest payload"
        friendly = self._map(raw)
        _assert_friendly(raw, friendly)

    @pytest.mark.parametrize(
        "raw",
        [
            "[Build incomplete: Final response differs from the verified synthesis manifest]",
            "[Build incomplete: Passed leaf has no grounded final claim: t1]",
            "[Build incomplete: Synthesizer produced no final response]",
        ],
    )
    def test_various_internal_errors_never_leak_jargon(self, raw: str):
        friendly = self._map(raw)
        _assert_friendly(raw, friendly)
