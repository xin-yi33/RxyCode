"""Fixed tool call and chunk frames. Version is required and must be at least 1."""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from dataclasses import dataclass


@dataclass(frozen=True)
class ToolCall:
    name: str
    target_id: str
    arguments: dict[str, object]
    version: int
    call_id: str = ""

    def __post_init__(self) -> None:
        if self.version < 1:
            raise ValueError("tool call version must be >= 1")
        if not self.call_id:
            object.__setattr__(self, "call_id", uuid.uuid4().hex)

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "target_id": self.target_id,
            "arguments": dict(self.arguments),
            "version": self.version,
            "call_id": self.call_id,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> ToolCall:
        version = int(data["version"])
        if version < 1:
            raise ValueError("tool call version must be >= 1")
        arguments = data.get("arguments") or {}
        if not isinstance(arguments, dict):
            raise ValueError("tool call arguments must be an object")
        return cls(
            name=str(data["name"]),
            target_id=str(data["target_id"]),
            arguments=dict(arguments),
            version=version,
            call_id=str(data.get("call_id") or ""),
        )


@dataclass(frozen=True)
class ToolChunk:
    call_id: str
    index: int
    text: str
    final: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "call_id": self.call_id,
            "index": self.index,
            "text": self.text,
            "final": self.final,
        }
