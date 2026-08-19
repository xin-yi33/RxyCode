"""Stable protocol error codes (PhaseG-B2). JSON-RPC numeric codes stay."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel

from .types import JsonObject
from .version import PROTOCOL_VERSION, PROTOCOL_VERSION_MAX, PROTOCOL_VERSION_MIN

ProtocolErrorCode = Literal[
    "PROTOCOL_MISMATCH",
    "UNSUPPORTED",
    "OVERLOADED",
    "CONFIGURATION_MISSING",
    "TIMEOUT",
    "CLOSED",
    "NOT_INITIALIZED",
]

RETRYABLE: dict[str, bool] = {
    "PROTOCOL_MISMATCH": False,
    "UNSUPPORTED": False,
    "OVERLOADED": True,
    "CONFIGURATION_MISSING": False,
    "TIMEOUT": True,
    "CLOSED": True,
    "NOT_INITIALIZED": False,
}

# Existing appserver JSON-RPC codes that map to a stable code.
JSONRPC_STABLE_CODE: dict[int, str] = {
    -32601: "UNSUPPORTED",
    -32002: "NOT_INITIALIZED",
    -32004: "TIMEOUT",
    -32006: "PROTOCOL_MISMATCH",
    -32007: "CONFIGURATION_MISSING",
    -32008: "OVERLOADED",
    -32009: "CLOSED",
}


class ProtocolErrorData(BaseModel):
    """Machine-assertable error payload in JSON-RPC ``error.data``."""

    error_code: ProtocolErrorCode
    retryable: bool
    protocol_version: str = PROTOCOL_VERSION
    protocol_min: str = PROTOCOL_VERSION_MIN
    protocol_max: str = PROTOCOL_VERSION_MAX
    server_version: str | None = None
    details: JsonObject | None = None


def error_payload(
    error_code: str,
    *,
    server_version: str | None = None,
    details: dict[str, Any] | None = None,
    retryable: bool | None = None,
) -> dict[str, Any]:
    retry = RETRYABLE[error_code] if retryable is None else retryable
    return ProtocolErrorData(
        error_code=error_code,  # type: ignore[arg-type]
        retryable=retry,
        server_version=server_version,
        details=details,
    ).model_dump(exclude_none=True)


ERROR_MODELS: tuple[type[BaseModel], ...] = (ProtocolErrorData,)
