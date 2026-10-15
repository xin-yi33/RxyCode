"""WEB-W1-C04. New schema fields stay optional for old JSON-RPC clients."""
from __future__ import annotations

from protocol.requests import InitializeRequest, PromptRequest
from protocol.schema import export_schema, required_field_breaks_legacy
from protocol.server_requests import ApprovalRequest

LEGACY_PROMPT = {
    "method": "session/prompt",
    "session_id": "s1",
    "text": "hello",
}
LEGACY_INITIALIZE = {
    "method": "initialize",
    "client_name": "cli",
    "client_version": "1.4.3",
    "protocol_version": "1.1.0",
}
LEGACY_APPROVAL = {
    "method": "approval/request",
    "session_id": "s1",
    "request_id": "r1",
    "risk_level": "WRITE",
    "action": "bash",
}


def test_w1_c04_contract():
    """A legacy JSON-RPC fixture still parses to the old method and fields."""
    schema = export_schema()
    prompt = PromptRequest.model_validate(LEGACY_PROMPT)
    initialize = InitializeRequest.model_validate(LEGACY_INITIALIZE)
    approval = ApprovalRequest.model_validate(LEGACY_APPROVAL)
    assert prompt.model_dump()["method"] == "session/prompt"
    assert prompt.model_dump()["session_id"] == "s1"
    assert prompt.model_dump()["text"] == "hello"
    assert initialize.method == "initialize"
    assert approval.method == "approval/request"
    prompt_def = schema["$defs"]["PromptRequest"]
    assert prompt_def["properties"]["method"]["const"] == "session/prompt"
    assert "run_id" in prompt_def["properties"]
    assert "run_id" not in prompt_def.get("required", [])
    assert schema["$defs"]["InitializeRequest"]["properties"]["method"]["const"] == "initialize"
    assert schema["$defs"]["ApprovalRequest"]["properties"]["method"]["const"] == "approval/request"
    assert {"RunRecord", "WebEvent", "DeviceRecord", "WebDiagnostic"} <= set(schema["$defs"])


def test_w1_c04_negative():
    """A new required field makes the legacy fixture incompatible."""
    assert required_field_breaks_legacy(PromptRequest, LEGACY_PROMPT) is False

    class RequiredRun(PromptRequest):
        """Temporary break used only to prove the checker fails closed."""

        run_id: str

    assert required_field_breaks_legacy(RequiredRun, LEGACY_PROMPT) is True
