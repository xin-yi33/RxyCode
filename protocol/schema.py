"""Export JSON Schema for the protocol package."""

from __future__ import annotations

import hashlib
import json
import sys
from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel

from .agents import AGENT_PROTOCOL_MODELS
from .errors import ERROR_MODELS, ProtocolErrorCode
from .handshake import HANDSHAKE_MODELS
from .notifications import NOTIFICATION_MODELS, WebEvent, frozen_event_methods
from .requests import CLIENT_REQUEST_MODELS, DeviceRecord, RunRecord, WebDiagnostic
from .server_requests import SERVER_REQUEST_MODELS
from .timeout_decision import (
    TimeoutDecisionEvent,
    TimeoutDecisionResponse,
    TimeoutEvidence,
)
from .version import PROTOCOL_VERSION

TIMEOUT_DECISION_MODELS: tuple[type, ...] = (
    TimeoutEvidence,
    TimeoutDecisionResponse,
    TimeoutDecisionEvent,
)

WEB_PROTOCOL_MODELS: tuple[type, ...] = (
    RunRecord,
    WebEvent,
    DeviceRecord,
    WebDiagnostic,
)


def required_field_breaks_legacy(model: type[BaseModel], fixture: Mapping[str, Any]) -> bool:
    """True when a required schema field is absent from an old client payload."""
    required = set(model.model_json_schema().get("required") or [])
    return any(name not in fixture for name in required)


def schema_digest(schema: Mapping[str, Any]) -> str:
    """Digest of the frozen version, event names, error codes, and web models."""
    capability = (
        schema.get("$defs", {})
        .get("PromptRequest", {})
        .get("properties", {})
        .get("capability", {})
    )
    names: list[str] = []
    if isinstance(capability.get("enum"), list):
        names = [str(item) for item in capability["enum"]]
    else:
        for item in capability.get("anyOf") or []:
            if isinstance(item, dict) and isinstance(item.get("enum"), list):
                names = [str(value) for value in item["enum"]]
                break
    frozen = {
        "protocol_version": schema.get("protocol_version"),
        "events": sorted(frozen_event_methods()),
        "errors": [str(code) for code in ProtocolErrorCode.__args__],
        "capabilities": names,
        "web_models": [model.__name__ for model in WEB_PROTOCOL_MODELS],
    }
    raw = json.dumps(frozen, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def export_schema() -> dict[str, Any]:
    """Export the full protocol schema for TS codegen and compatibility clients."""

    models: tuple[type, ...] = (
        *CLIENT_REQUEST_MODELS,
        *NOTIFICATION_MODELS,
        *SERVER_REQUEST_MODELS,
        *AGENT_PROTOCOL_MODELS,
        *HANDSHAKE_MODELS,
        *ERROR_MODELS,
        *TIMEOUT_DECISION_MODELS,
        *WEB_PROTOCOL_MODELS,
    )
    defs: dict[str, Any] = {}
    for model in models:
        schema = model.model_json_schema(ref_template="#/$defs/{model}")
        nested = schema.pop("$defs", {})
        defs.update(nested)
        name = model.__name__
        defs[name] = {key: value for key, value in schema.items() if key != "$defs"}

    client_refs = [{"$ref": f"#/$defs/{model.__name__}"} for model in CLIENT_REQUEST_MODELS]
    notification_refs = [
        {"$ref": f"#/$defs/{model.__name__}"} for model in NOTIFICATION_MODELS
    ]
    server_refs = [
        {"$ref": f"#/$defs/{model.__name__}"} for model in SERVER_REQUEST_MODELS
    ]
    defs["ClientRequest"] = {"oneOf": client_refs}
    defs["ProtocolNotification"] = {"oneOf": notification_refs}
    defs["ServerRequestMessage"] = {"oneOf": server_refs}
    # Codegen / freeze union only. Not a session envelope: wire RPC stays the
    # three unions above. json2ts skips unreachable $defs on a root oneOf, so
    # this fourth member is how F3 types reach frontend/protocol-client.
    defs["AgentProtocol"] = {
        "title": "AgentProtocol",
        "description": (
            "Phase F expert-team types (F3). Not a session envelope; "
            "discriminated wire messages still use method on "
            "ClientRequest / ProtocolNotification / ServerRequestMessage."
        ),
        "oneOf": [{"$ref": f"#/$defs/{model.__name__}"} for model in AGENT_PROTOCOL_MODELS],
    }
    defs["HandshakeProtocol"] = {
        "title": "HandshakeProtocol",
        "description": (
            "PhaseG-B2 initialize result, capability snapshot, and stable "
            "error payload. Not a session envelope."
        ),
        "oneOf": [
            {"$ref": f"#/$defs/{model.__name__}"}
            for model in (*HANDSHAKE_MODELS, *ERROR_MODELS)
        ],
    }
    defs["TimeoutDecisionProtocol"] = {
        "title": "TimeoutDecisionProtocol",
        "description": (
            "Phase P timeout decision evidence, response, and event. "
            "Not a session envelope."
        ),
        "anyOf": [
            {"$ref": f"#/$defs/{model.__name__}"}
            for model in TIMEOUT_DECISION_MODELS
        ],
    }
    defs["WebProtocol"] = {
        "title": "WebProtocol",
        "description": (
            "Additive Run, Event, Device, and diagnostic models. "
            "Not a session envelope. Old initialize, session/prompt, "
            "and approval/request methods are unchanged."
        ),
        "oneOf": [
            {"$ref": f"#/$defs/{model.__name__}"}
            for model in WEB_PROTOCOL_MODELS
        ],
    }

    exported = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "https://rxycode.dev/protocol/schema.json",
        "title": "RxyCode Protocol",
        "protocol_version": PROTOCOL_VERSION,
        "$defs": defs,
        "oneOf": [
            {"$ref": "#/$defs/ClientRequest"},
            {"$ref": "#/$defs/ProtocolNotification"},
            {"$ref": "#/$defs/ServerRequestMessage"},
            {"$ref": "#/$defs/AgentProtocol"},
            {"$ref": "#/$defs/HandshakeProtocol"},
            {"$ref": "#/$defs/TimeoutDecisionProtocol"},
            {"$ref": "#/$defs/WebProtocol"},
        ],
    }
    exported["schema_digest"] = schema_digest(exported)
    return exported


def main() -> None:
    json.dump(export_schema(), sys.stdout, indent=2, ensure_ascii=False)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
