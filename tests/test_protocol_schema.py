"""Frozen JSON Schema for the protocol package."""

from __future__ import annotations

import json
from pathlib import Path

from protocol.schema import export_schema

SCHEMA_PATH = Path(__file__).resolve().parents[1] / "protocol" / "schema.json"


def test_exported_schema_matches_committed_file() -> None:
    current = json.dumps(export_schema(), indent=2, ensure_ascii=False) + "\n"
    committed = SCHEMA_PATH.read_text(encoding="utf-8")
    assert current == committed, (
        "protocol/schema.json is out of date. "
        "Run: python -m protocol.schema > protocol/schema.json "
        "and commit the diff; bump PROTOCOL_VERSION if semantics changed."
    )


def test_schema_freeze_detects_field_changes() -> None:
    schema = export_schema()
    defs = schema["$defs"]["PromptRequest"]
    assert "timeout_seconds" in defs["properties"]
    defs["properties"]["timeout_seconds"]["description"] = "mutated"
    mutated = json.dumps(schema, indent=2, ensure_ascii=False) + "\n"
    committed = SCHEMA_PATH.read_text(encoding="utf-8")
    assert mutated != committed