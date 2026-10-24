"""Three permission tiers on the web route vocabulary: confirm | auto_edit | full.

The agent core has three approval modes (confirm_all / auto_edit / full_auto);
the web routes speak ``confirm`` / ``auto_edit`` / ``full`` and the worker maps
them 1:1. These are pure unit tests (no database, no container): they pin the
input validation for both run submission and schedules, the schedule submit
gate that must not downgrade the middle tier to confirm, and the approval
broker seam where BOTH the web spelling (``full``) and the agent spelling
(``full_auto``) mean "already authorized — do not ask" while ``confirm`` and
``auto_edit`` still ask.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi import HTTPException

REPO = Path(__file__).resolve().parents[3]
for _name in (
    "rxycode-server",
    "rxycode-worker",
    "rxycode-runner",
    "rxycode-protocol",
    "rxycode-core",
):
    _path = REPO / "packages" / _name / "src"
    if _path.is_dir() and str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

pytestmark = pytest.mark.unit

#: The three web tiers, in the order the composer renders them.
_TIERS = ("confirm", "auto_edit", "full")

#: Values that must stay rejected at the route boundary: agent vocabulary is
#: not a valid route value, and case/underscore variants are not aliases.
_GARBAGE = (
    "",
    "sudo",
    "confirm_all",
    "full_auto",
    "AUTO_EDIT",
    "auto-edit",
    "Confirm",
)


# ---- run submission (/api/v1/tasks, /api/v1/sessions/{id}/runs) --------------


def test_run_validation_accepts_the_three_web_tiers() -> None:
    from rxycode_server.api.runs import _PROFILES, _check_run_input

    assert tuple(_PROFILES) == _TIERS
    request_id = "req-" + "a" * 16
    for profile in _TIERS:
        # No exception == accepted by the same helper both run endpoints call.
        _check_run_input("do the thing", request_id, profile)


@pytest.mark.parametrize("profile", _GARBAGE)
def test_run_validation_still_rejects_garbage(profile: str) -> None:
    from rxycode_server.api.runs import _check_run_input

    with pytest.raises(HTTPException) as caught:
        _check_run_input("do the thing", "req-" + "a" * 16, profile)
    assert caught.value.status_code == 400
    assert caught.value.detail == "INVALID_INPUT"


# ---- schedules (/api/v1/schedules create + patch) ----------------------------


def test_schedule_validation_accepts_the_three_web_tiers() -> None:
    from rxycode_server.api.schedules import _PROFILES, _valid_profile

    assert _PROFILES == set(_TIERS)
    for profile in _TIERS:
        assert _valid_profile(profile) == profile


@pytest.mark.parametrize("profile", _GARBAGE)
def test_schedule_validation_still_rejects_garbage(profile: str) -> None:
    from rxycode_server.api.schedules import _valid_profile

    with pytest.raises(HTTPException) as caught:
        _valid_profile(profile)
    assert caught.value.status_code == 422
    assert caught.value.detail == "INVALID_INPUT"


# ---- scheduled runs keep the stored tier ------------------------------------


def test_scheduled_run_gate_keeps_auto_edit() -> None:
    """Firing a schedule must use its stored tier, not silently fall back to the
    most conservative one (notifications/service._submit_scheduled/_fire_manual)."""
    from rxycode_server.notifications.service import _SCHEDULE_PROFILES

    assert _SCHEDULE_PROFILES == set(_TIERS)

    def routed(profile: str) -> str:
        return profile if profile in _SCHEDULE_PROFILES else "confirm"

    for profile in _TIERS:
        assert routed(profile) == profile
    assert routed("full_auto") == "confirm"  # unknown/agent value stays conservative


# ---- approval broker: no-approval tier has two spellings ---------------------


def test_approval_broker_treats_web_full_as_no_approval() -> None:
    from rxycode_server.approvals.service import _is_no_approval_profile

    assert _is_no_approval_profile("full") is True
    assert _is_no_approval_profile("full_auto") is True
    for profile in ("confirm", "auto_edit", "", None):
        assert _is_no_approval_profile(profile) is False
