"""Export JSON Schema for the protocol package."""

from __future__ import annotations

import json
import sys
from typing import Any

from .agents import AGENT_PROTOCOL_MODELS
from .errors import ERROR_MODELS
from .handshake import HANDSHAKE_MODELS
from .notifications import NOTIFICATION_MODELS
from .requests import CLIENT_REQUEST_MODELS
from .server_requests import SERVER_REQUEST_MODELS
from .version import PROTOCOL_VERSION


def export_schema() -> dict[str, Any]:
    """Export the full protocol schema for TS codegen and compatibility clients."""

    models: tuple[type, ...] = (
        *CLIENT_REQUEST_MODELS,
        *NOTIFICATION_MODELS,
        *SERVER_REQUEST_MODELS,
        *AGENT_PROTOCOL_MODELS,
        *HANDSHAKE_MODELS,
        *ERROR_MODELS,
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

    return {
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
        ],
    }


def main() -> None:
    json.dump(export_schema(), sys.stdout, indent=2, ensure_ascii=False)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
