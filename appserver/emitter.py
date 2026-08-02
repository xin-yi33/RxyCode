"""Map protocol pydantic models to JSON-RPC wire messages."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel


def model_to_notification(model: BaseModel) -> dict[str, Any]:
    """Convert a protocol notification model to a JSON-RPC notification."""
    method = getattr(model, "method", None)
    if not isinstance(method, str):
        raise TypeError(f"notification model missing method discriminator: {type(model)}")
    params = model.model_dump()
    params.pop("method", None)
    return {"jsonrpc": "2.0", "method": method, "params": params}