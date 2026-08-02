"""Export JSON Schema for the protocol package."""

from __future__ import annotations

import json
import sys
from typing import Any

from protocol.notifications import NOTIFICATION_MODELS
from protocol.requests import CLIENT_REQUEST_MODELS
from protocol.server_requests import SERVER_REQUEST_MODELS
from protocol.version import PROTOCOL_VERSION


def export_schema() -> dict[str, Any]:
    """Export the full protocol schema for TS codegen and compatibility clients."""

    models: tuple[type, ...] = (
        *CLIENT_REQUEST_MODELS,
        *NOTIFICATION_MODELS,
        *SERVER_REQUEST_MODELS,
    )
    defs: dict[str, Any] = {}
    for model in models:
        schema = model.model_json_schema(ref_template="#/$defs/{model}")
        nested = schema.pop("$defs", {})
        defs.update(nested)
        name = model.__name__
        defs[name] = {key: value for key, value in schema.items() if key != "$defs"}

    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "https://rxycode.dev/protocol/schema.json",
        "title": "RxyCode Protocol",
        "protocol_version": PROTOCOL_VERSION,
        "$defs": defs,
    }


def main() -> None:
    json.dump(export_schema(), sys.stdout, indent=2, ensure_ascii=False)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
