"""F14 team eval checks + efficiency gate."""

from __future__ import annotations

from RxyCode.RxyCode1_1_0.core.agents.router import L2Thresholds
from RxyCode.RxyCode1_1_0.evals.runner import _run_single_check
from RxyCode.RxyCode1_1_0.evals.tasks import Check
from RxyCode.RxyCode1_1_0.evals.team_metrics import efficiency, label_failure, project_team, summarize


def test_new_check_types() -> None:
    ok, _ = _run_single_check(
        Check(type="role_participated", role="coder"),
        workdir=None,
        agent_answer="",
        extras={"roles": ["architect", "coder"]},
    )
    assert ok
    ok, _ = _run_single_check(
        Check(type="max_delegations", max=3),
        workdir=None,
        agent_answer="",
        extras={"delegations": 4},
    )
    assert not ok
    ok, _ = _run_single_check(
        Check(type="verdict_bound", subject_hash="abc"),
        workdir=None,
        agent_answer="",
        extras={"subject_hash": "abc"},
    )
    assert ok
    ok, _ = _run_single_check(
        Check(type="cache_hit_floor", floor=0.85),
        workdir=None,
        agent_answer="",
        extras={"cache_hit_rate": 0.9},
    )
    assert ok


def test_efficiency_is_red_when_team_is_only_overhead() -> None:
    solo = summarize(
        [
            {"passed": True, "token_usage": {"total": 1000}, "duration_s": 10, "cache_hit_rate": 0.9},
            {"passed": True, "token_usage": {"total": 1000}, "duration_s": 10, "cache_hit_rate": 0.9},
        ]
    )
    team = project_team(solo)
    gate = efficiency(solo, team)
    assert gate["light"] == "red"
    assert gate["token_x"] == 3.0


def test_mast_labels_verification_failures() -> None:
    assert label_failure("lint dirty") == "FM-3.3"


def test_f14_relaxed_l2_file_threshold() -> None:
    assert L2Thresholds().min_files_for_team == 2


def test_auto_route_eval_fixture_matches_router() -> None:
    import json
    from pathlib import Path

    from RxyCode.RxyCode1_1_0.core.agents.router import ExecutionMode, ModeRouter

    path = (
        Path(__file__).resolve().parents[2]
        / "evals"
        / "baselines"
        / "auto-route-explore-team.json"
    )
    payload = json.loads(path.read_text(encoding="utf-8"))
    router = ModeRouter(enabled=True)
    for case in payload["required_after"]["cases"]:
        decision = router.route(case["prompt"])
        assert decision.mode is ExecutionMode(case["mode"]), case
        if "decided_by" in case:
            assert decision.decided_by == case["decided_by"], case
