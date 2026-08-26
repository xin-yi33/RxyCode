"""F3 · AgentSpec / TeamSpec 静态校验。"""

from __future__ import annotations

import pytest

from RxyCode.RxyCode1_1_0.core.agents.spec import (
    MAX_DELEGATE_DEPTH,
    AgentSpecError,
    validate_team,
)
from RxyCode.RxyCode1_1_0.protocol.agents import (
    AGENT_PROTOCOL_MODELS,
    AgentSpec,
    SopStage,
    TeamSpec,
)
from RxyCode.RxyCode1_1_0.protocol.schema import export_schema


def _member(
    role: str,
    *,
    may_consult: list[str] | None = None,
    extra: dict[str, object] | None = None,
) -> AgentSpec:
    return AgentSpec(
        role=role,
        display_name=role,
        goal="do the job",
        prompt_stage="default",
        may_consult=list(may_consult or ()),
        extra=dict(extra or {}),
    )


def _stage(
    name: str,
    role: str,
    *,
    next_on_success: str | None = None,
    next_on_failure: str | None = None,
) -> SopStage:
    return SopStage(
        name=name,
        role=role,
        expected_output="artifact",
        output_key=name,
        next_on_success=next_on_success,
        next_on_failure=next_on_failure,
    )


def _team(
    members: list[AgentSpec],
    stages: list[SopStage],
    *,
    entry_stage: str | None = None,
    extra: dict[str, object] | None = None,
) -> TeamSpec:
    return TeamSpec(
        name="sample",
        display_name="Sample Team",
        members=members,
        stages=stages,
        entry_stage=entry_stage if entry_stage is not None else stages[0].name,
        extra=dict(extra or {}),
    )


def _valid_team() -> TeamSpec:
    return _team(
        [_member("coder")],
        [_stage("code", "coder")],
        extra={"ecosystem.version": "1", "note": "plain keys stay allowed"},
    )


def test_valid_team_passes() -> None:
    validate_team(_valid_team())


def test_duplicate_role() -> None:
    team = _team(
        [_member("coder"), _member("coder")],
        [_stage("code", "coder")],
    )
    with pytest.raises(AgentSpecError, match="duplicate role"):
        validate_team(team)


def test_duplicate_stage() -> None:
    team = _team(
        [_member("coder")],
        [_stage("code", "coder"), _stage("code", "coder")],
    )
    with pytest.raises(AgentSpecError, match="duplicate stage"):
        validate_team(team)


def test_entry_stage_missing() -> None:
    team = _team(
        [_member("coder")],
        [_stage("code", "coder")],
        entry_stage="missing",
    )
    with pytest.raises(AgentSpecError, match="entry_stage"):
        validate_team(team)


def test_stage_unknown_role() -> None:
    team = _team(
        [_member("coder")],
        [_stage("code", "reviewer")],
    )
    with pytest.raises(AgentSpecError, match="unknown role"):
        validate_team(team)


def test_next_unknown_stage() -> None:
    team = _team(
        [_member("coder")],
        [_stage("code", "coder", next_on_success="ghost")],
    )
    with pytest.raises(AgentSpecError, match="unknown stage"):
        validate_team(team)


def test_may_consult_unknown_role() -> None:
    team = _team(
        [_member("coder", may_consult=["architect"])],
        [_stage("code", "coder")],
    )
    with pytest.raises(AgentSpecError, match="may_consult unknown role"):
        validate_team(team)


def test_self_consult_is_rejected() -> None:
    team = _team(
        [_member("coder", may_consult=["coder"])],
        [_stage("code", "coder")],
    )
    with pytest.raises(AgentSpecError, match="may not consult itself"):
        validate_team(team)


def test_consult_binary_cycle() -> None:
    team = _team(
        [
            _member("coder", may_consult=["architect"]),
            _member("architect", may_consult=["coder"]),
        ],
        [
            _stage("plan", "architect", next_on_success="code"),
            _stage("code", "coder"),
        ],
    )
    with pytest.raises(AgentSpecError, match="consult graph contains a cycle"):
        validate_team(team)


def test_consult_ternary_cycle() -> None:
    team = _team(
        [
            _member("coder", may_consult=["architect"]),
            _member("architect", may_consult=["reviewer"]),
            _member("reviewer", may_consult=["coder"]),
        ],
        [
            _stage("plan", "architect", next_on_success="code"),
            _stage("code", "coder", next_on_success="review"),
            _stage("review", "reviewer"),
        ],
    )
    with pytest.raises(AgentSpecError, match="consult graph contains a cycle"):
        validate_team(team)


def test_sop_graph_has_no_exit() -> None:
    team = _team(
        [_member("coder"), _member("reviewer")],
        [
            _stage("code", "coder", next_on_success="review", next_on_failure="review"),
            _stage("review", "reviewer", next_on_success="code", next_on_failure="code"),
        ],
    )
    with pytest.raises(AgentSpecError, match="no reachable exit"):
        validate_team(team)


def test_allowed_extra_namespaces() -> None:
    team = _team(
        [
            _member(
                "coder",
                extra={
                    "pair.with": "reviewer",
                    "vision.required": False,
                    "persona.id": "builder",
                    "ecosystem.is_leader": False,
                },
            )
        ],
        [_stage("code", "coder")],
        extra={
            "ecosystem.category": "software",
            "ecosystem.version": "1.0.0",
        },
    )
    validate_team(team)


def test_unknown_extra_namespace_rejected() -> None:
    team = _team(
        [_member("coder")],
        [_stage("code", "coder")],
        extra={"foo.bar": 1},
    )
    with pytest.raises(AgentSpecError, match="unknown namespace"):
        validate_team(team)


def test_member_unknown_extra_namespace_rejected() -> None:
    team = _team(
        [_member("coder", extra={"misc.flag": True})],
        [_stage("code", "coder")],
    )
    with pytest.raises(AgentSpecError, match="unknown namespace"):
        validate_team(team)


def test_extra_namespaces_survive_roundtrip() -> None:
    extra = {
        "persona.id": "p1",
        "persona.skills": ["review"],
        "unknown_plain": {"nested": 1},
        "pair.with": "coder",
    }
    spec = _member("reviewer", extra=extra)
    restored = AgentSpec.model_validate(spec.model_dump())
    assert restored.extra == extra
    team = _valid_team()
    dumped = team.model_dump()
    dumped["extra"] = {"ecosystem.version": "9", "plain": "ok"}
    again = TeamSpec.model_validate(dumped)
    assert again.extra["ecosystem.version"] == "9"
    assert again.extra["plain"] == "ok"


def test_max_delegate_depth_is_not_phase_d_subagent_depth() -> None:
    assert MAX_DELEGATE_DEPTH == 3
    # Phase D counts isolated ChildSession hops (0/1/2). This constant
    # counts Coordinator -> member stage hops and stays independent.


def test_agent_protocol_models_are_in_schema_defs() -> None:
    schema = export_schema()
    defs = schema["$defs"]
    for model in AGENT_PROTOCOL_MODELS:
        assert model.__name__ in defs, model.__name__
    assert "extra" in defs["TeamSpec"]["properties"]
    assert "extra" in defs["AgentSpec"]["properties"]
    assert "parallel_members" in defs["SopStage"]["properties"]
    assert "TeamEvent" in defs
    assert "AgentProtocol" in defs
    assert {"$ref": "#/$defs/AgentProtocol"} in schema["oneOf"]
    # Existing wire unions stay the same length.
    from protocol.notifications import NOTIFICATION_MODELS
    from protocol.requests import CLIENT_REQUEST_MODELS

    assert len(defs["ClientRequest"]["oneOf"]) == len(CLIENT_REQUEST_MODELS)
    assert len(defs["ProtocolNotification"]["oneOf"]) == len(NOTIFICATION_MODELS)


def test_f_layer_has_no_agent_event() -> None:
    import RxyCode.RxyCode1_1_0.protocol.agents as agents_mod

    assert not hasattr(agents_mod, "AgentEvent")
    assert hasattr(agents_mod, "TeamEvent")


def test_parallel_members_unknown_role() -> None:
    team = _team(
        [_member("coder")],
        [
            SopStage(
                name="code",
                role="coder",
                expected_output="artifact",
                output_key="code",
                parallel_members=["ghost"],
            )
        ],
    )
    with pytest.raises(AgentSpecError, match="unknown role"):
        validate_team(team)


def test_parallel_members_duplicate() -> None:
    team = _team(
        [_member("coder"), _member("reviewer")],
        [
            SopStage(
                name="code",
                role="coder",
                expected_output="artifact",
                output_key="code",
                parallel_members=["coder", "coder"],
            )
        ],
    )
    with pytest.raises(AgentSpecError, match="duplicate parallel"):
        validate_team(team)


def test_invalid_skill_name_rejected() -> None:
    team = _team(
        [_member("coder", extra={"ecosystem.skill": "Not Valid"})],
        [_stage("code", "coder")],
    )
    with pytest.raises(AgentSpecError, match="invalid skill name"):
        validate_team(team)


def test_two_leaders_rejected() -> None:
    team = _team(
        [
            _member("pm", extra={"ecosystem.is_leader": True}),
            _member("coder", extra={"ecosystem.is_leader": True}),
        ],
        [_stage("code", "coder")],
    )
    with pytest.raises(AgentSpecError, match="is_leader"):
        validate_team(team)


def test_unknown_ecosystem_key_is_ignored() -> None:
    from RxyCode.RxyCode1_1_0.core.agents.spec import unknown_ecosystem_keys

    team = _team(
        [_member("coder", extra={"ecosystem.not_a_real_field": 1})],
        [_stage("code", "coder")],
        extra={"ecosystem.also_future": "x"},
    )
    validate_team(team)
    assert "ecosystem.not_a_real_field" in unknown_ecosystem_keys(team.members[0].extra)
    assert "ecosystem.also_future" in unknown_ecosystem_keys(team.extra)
