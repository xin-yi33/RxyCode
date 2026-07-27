"""Table-driven user-facing error mapping matrices (E2/E3/E8)."""

from __future__ import annotations

import itertools
import re

import pytest

from RxyCode.RxyCode1_1_0.utils import user_facing_errors as ufe

_FORBIDDEN = re.compile(
    r"synthesizer|claim\s*manifest|grounded\s*claims?",
    re.IGNORECASE,
)

_BUILD_SUFFIXES = (
    "Task not verified: deploy (failed)",
    "Synthesizer produced no grounded claims",
    "Synthesis answer contains text outside its claim manifest",
    "Synthesizer output was not valid grounded JSON.",
    "Final response differs from the verified synthesis manifest",
    "Passed leaf has no grounded final claim: t1",
    "Synthesizer produced no final response",
    "Missing side-effect evidence for write task",
)

_EVIDENCE_SUFFIXES = (
    "Tool bash did not complete: failed",
    "Tool read did not complete: cancelled",
    "Tool write did not complete: timeout",
    "Tool patch did not complete: error",
    "Tool grep did not complete: failed",
)

_GROUNDING_MARKERS = ufe._GROUNDING_MARKERS

_TIMEOUT_VARIANTS = (
    "TimeoutError: operation timed out after 600s",
    "Request timed out waiting for synthesizer",
    "connection timeout after 30s",
    "TIMEOUT: executor stalled",
)

_CANCEL_VARIANTS = (
    "Cancelled",
    "cancelled",
    "CancelledError: user cancelled",
    "cancel requested by client",
)

_BUILD_CASES = [f"[Build incomplete: {suffix}]" for suffix in _BUILD_SUFFIXES]
_EVIDENCE_CASES = [f"[evidence failed: {suffix}]" for suffix in _EVIDENCE_SUFFIXES]
_GROUNDING_CASES = [
    f"Internal: {marker} detected in pipeline stage {idx}"
    for marker, idx in itertools.product(_GROUNDING_MARKERS, range(1, 4))
]
_DEFAULT_CASES = [
    f"unexpected internal failure code {code}"
    for code in range(100, 160)
]


def _map(raw: str) -> str:
    return ufe.to_user_facing_error(raw)


def _assert_friendly(raw: str, friendly: str) -> None:
    assert friendly
    assert not _FORBIDDEN.search(friendly), friendly
    assert "manifest" not in friendly.lower()
    assert "grounded" not in friendly.lower()
    assert friendly in {
        ufe.MSG_BUILD_INCOMPLETE,
        ufe.MSG_GROUNDING,
        ufe.MSG_TOOL_INTERRUPTED,
        ufe.MSG_TIMEOUT,
        ufe.MSG_CANCELLED,
        ufe.MSG_DEFAULT,
    }


@pytest.mark.parametrize("raw", _BUILD_CASES)
def test_build_incomplete_matrix(raw: str):
    friendly = _map(raw)
    _assert_friendly(raw, friendly)
    lowered = raw.lower()
    if any(marker in lowered for marker in ufe._GROUNDING_MARKERS):
        assert friendly == ufe.MSG_GROUNDING
    else:
        assert friendly == ufe.MSG_BUILD_INCOMPLETE


@pytest.mark.parametrize("raw", _EVIDENCE_CASES)
def test_evidence_failed_matrix(raw: str):
    friendly = _map(raw)
    _assert_friendly(raw, friendly)
    if "timeout" in raw.lower():
        assert friendly == ufe.MSG_TIMEOUT
    else:
        assert friendly == ufe.MSG_TOOL_INTERRUPTED


@pytest.mark.parametrize("raw", _GROUNDING_CASES)
def test_grounding_marker_matrix(raw: str):
    friendly = _map(raw)
    _assert_friendly(raw, friendly)
    assert friendly == ufe.MSG_GROUNDING


@pytest.mark.parametrize("raw", _TIMEOUT_VARIANTS)
def test_timeout_matrix(raw: str):
    friendly = _map(raw)
    _assert_friendly(raw, friendly)
    assert friendly == ufe.MSG_TIMEOUT


@pytest.mark.parametrize("raw", _CANCEL_VARIANTS)
def test_cancelled_matrix(raw: str):
    friendly = _map(raw)
    _assert_friendly(raw, friendly)
    assert friendly == ufe.MSG_CANCELLED


@pytest.mark.parametrize("raw", _DEFAULT_CASES)
def test_unknown_errors_map_to_default(raw: str):
    friendly = _map(raw)
    _assert_friendly(raw, friendly)
    assert friendly == ufe.MSG_DEFAULT


@pytest.mark.parametrize("raw", ["", "   ", None])
def test_empty_input_matrix(raw):
    assert _map(raw) == ufe.MSG_DEFAULT
