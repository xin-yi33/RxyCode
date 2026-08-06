"""B14 · Protocol schema machine-verification tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from protocol.subagents import (
    AgentMode,
    ChildStatus,
    TaskResult,
    TriggerKind,
    UsageRecord,
)

SCHEMA_PATH = Path(__file__).resolve().parent.parent.parent / "protocol" / "subagents_schema.json"


@pytest.fixture
def schema() -> dict:
    data = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    assert data["version"] == 1
    return data


@pytest.fixture
def jsonschema_validator():
    """Validate via jsonschema if available; otherwise structural fallback."""
    try:
        import jsonschema  # noqa: F401
        return True
    except ImportError:
        return False


class TestSchemaPresence:
    """The machine-verifiable protocol schema exists and is valid JSON."""

    def test_schema_file_exists(self):
        assert SCHEMA_PATH.exists()

    def test_schema_is_valid_json(self, schema):
        assert "definitions" in schema
        assert "agent_definition" in schema["definitions"]
        assert "task_request" in schema["definitions"]
        assert "task_result" in schema["definitions"]
        assert "child_session_event" in schema["definitions"]


class TestAgentDefinitionSchema:
    """AgentDefinition payloads validate against the schema."""

    def test_valid_definition(self, schema, jsonschema_validator):
        payload = {
            "id": "explore",
            "description": "只读探索",
            "mode": "subagent",
            "steps": 12,
            "permission": {"read": {"**": "allow"}, "edit": {"**": "deny"}},
            "workspace_scope": "read_only",
        }
        definition = json.loads(json.dumps(payload))
        if jsonschema_validator:
            import jsonschema
            jsonschema.validate(definition, {"$ref": "#/definitions/agent_definition", **schema})
        else:
            assert definition["mode"] in ("primary", "subagent", "all")

    def test_invalid_mode_rejected_by_schema(self, schema, jsonschema_validator):
        payload = {"id": "x", "description": "d", "mode": "super"}
        if jsonschema_validator:
            import jsonschema
            with pytest.raises(jsonschema.ValidationError):
                jsonschema.validate(
                    payload,
                    {"$ref": "#/definitions/agent_definition", **schema},
                )

    def test_top_level_task_permission_forbidden(self, schema, jsonschema_validator):
        """The schema's 'not' clause rejects top-level task_permission."""
        payload = {"id": "x", "description": "d", "mode": "subagent", "task_permission": {"a": "allow"}}
        if jsonschema_validator:
            import jsonschema
            with pytest.raises(jsonschema.ValidationError):
                jsonschema.validate(
                    payload,
                    {"$ref": "#/definitions/agent_definition", **schema},
                )


class TestTaskResultSchema:
    """TaskResult payloads validate against the schema."""

    def test_valid_task_result(self, schema, jsonschema_validator):
        result = TaskResult(
            request_id="req_1",
            child_session_id="ses_child_1",
            status=ChildStatus.COMPLETED,
            summary="done",
            usage=UsageRecord(steps=3, input_tokens=100),
        )
        from dataclasses import asdict
        payload = json.loads(json.dumps(asdict(result), ensure_ascii=False))
        if jsonschema_validator:
            import jsonschema
            jsonschema.validate(payload, {"$ref": "#/definitions/task_result", **schema})
        else:
            assert payload["status"] == "completed"


class TestSchemaVsDataclasses:
    """Schema and dataclasses stay in sync."""

    def test_enum_values_match(self, schema):
        """The schema's enums match the Python protocol enums."""
        mode_enum = {e.value for e in AgentMode}
        schema_modes = set(schema["definitions"]["agent_mode"]["enum"])
        assert mode_enum == schema_modes

        trigger_enum = {t.value for t in TriggerKind}
        schema_triggers = set(schema["definitions"]["trigger_kind"]["enum"])
        assert trigger_enum == schema_triggers

        status_enum = {s.value for s in ChildStatus}
        schema_statuses = set(schema["definitions"]["child_status"]["enum"])
        assert status_enum == schema_statuses
