"""Shared fake open-computer-use stdio server for PP40 tests."""

from __future__ import annotations

FAKE_OCU = r'''
import json
import sys

def emit(message):
    sys.stdout.write(json.dumps(message, separators=(",", ":")) + "\n")
    sys.stdout.flush()

TOOLS = [
    {
        "name": "list_apps",
        "description": "List apps",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
        "annotations": {"readOnlyHint": True},
    },
    {
        "name": "get_app_state",
        "description": "App state",
        "inputSchema": {
            "type": "object",
            "properties": {"app": {"type": "string"}},
            "required": ["app"],
            "additionalProperties": False,
        },
        "annotations": {"readOnlyHint": True},
    },
    {
        "name": "click",
        "description": "Click",
        "inputSchema": {
            "type": "object",
            "properties": {
                "app": {"type": "string"},
                "element_index": {"type": "string"},
            },
            "required": ["app"],
            "additionalProperties": False,
        },
        "annotations": {"destructiveHint": True},
    },
    {
        "name": "type_text",
        "description": "Type",
        "inputSchema": {
            "type": "object",
            "properties": {"app": {"type": "string"}, "text": {"type": "string"}},
            "required": ["app", "text"],
            "additionalProperties": False,
        },
        "annotations": {"destructiveHint": True},
    },
    {
        "name": "press_key",
        "description": "Key",
        "inputSchema": {
            "type": "object",
            "properties": {"app": {"type": "string"}, "key": {"type": "string"}},
            "required": ["app", "key"],
            "additionalProperties": False,
        },
        "annotations": {"destructiveHint": True},
    },
    {
        "name": "scroll",
        "description": "Scroll",
        "inputSchema": {
            "type": "object",
            "properties": {"app": {"type": "string"}, "pages": {"type": "number"}},
            "required": ["app"],
            "additionalProperties": False,
        },
    },
]

for raw_line in sys.stdin:
    message = json.loads(raw_line)
    method = message.get("method")
    request_id = message.get("id")
    if method == "initialize":
        emit({
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "protocolVersion": "2025-11-25",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "ocu-fake", "version": "test"},
            },
        })
    elif method == "notifications/initialized":
        continue
    elif method == "tools/list":
        emit({"jsonrpc": "2.0", "id": request_id, "result": {"tools": TOOLS}})
    elif method == "tools/call":
        name = message.get("params", {}).get("name")
        arguments = message.get("params", {}).get("arguments") or {}
        if name == "list_apps":
            payload = {
                "source": "accessibility",
                "apps": [{"name": "msedge", "pid": 4242, "title": "Docs"}],
            }
        elif name == "get_app_state":
            payload = {
                "source": "accessibility",
                "app": arguments.get("app"),
                "tree": [{"index": "0", "role": "button", "name": "Submit"}],
                "screenshot": "SHOULD_STRIP",
            }
        elif name == "click":
            payload = {"ok": True, "source": "accessibility", "clicked": arguments}
        elif name == "type_text":
            payload = {"ok": True, "typed": arguments.get("text")}
        elif name == "press_key":
            payload = {"ok": True, "key": arguments.get("key")}
        elif name == "scroll":
            payload = {"ok": True, "pages": arguments.get("pages")}
        else:
            payload = {"ok": True}
        emit({
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "content": [{"type": "text", "text": json.dumps(payload)}],
                "structuredContent": payload,
            },
        })
'''
