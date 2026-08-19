"""PhaseG-B2 handshake, capability snapshot, and stable errors."""

from __future__ import annotations

from protocol.errors import RETRYABLE, ProtocolErrorData
from protocol.handshake import InitializeResult
from protocol.requests import InitializeRequest
from protocol.schema import export_schema
from protocol.version import (
    PROTOCOL_VERSION,
    PROTOCOL_VERSION_MAX,
    PROTOCOL_VERSION_MIN,
    protocol_version_compatible,
)
from protocol.notifications import InitializedNotification


def test_compatible_versions() -> None:
    assert protocol_version_compatible("")
    assert protocol_version_compatible("1.0.0")
    assert protocol_version_compatible("1.1.0")
    assert not protocol_version_compatible("2.0.0")
    assert not protocol_version_compatible("0.9.0")
    assert not protocol_version_compatible("not-a-version")


def test_initialize_request_accepts_unknown_and_optional_fields() -> None:
    req = InitializeRequest.model_validate(
        {
            "method": "initialize",
            "client_name": "desktop",
            "client_version": "1.2.10",
            "protocol_version": "1.1.0",
            "client_info": {"name": "desktop", "title": "RxyCode", "version": "1.2.10"},
            "client_capabilities": {"threads": True},
            "requested_features": ["review"],
            "unknown_future_field": {"x": 1},
        }
    )
    assert req.requested_features == ["review"]
    assert req.client_info is not None


def test_capability_snapshot_is_honest() -> None:
    snap = InitializeResult(
        capabilities={"sessions": True, "approval": True, "models": True, "credentials": True},
        capability_snapshot=__import__(
            "protocol.handshake", fromlist=["CapabilitySnapshot"]
        ).CapabilitySnapshot(),
        model_providers=[],
        permission_profiles=[],
    ).capability_snapshot
    assert snap.threads is True
    assert snap.thread_fork is False
    assert snap.review is False
    assert snap.approval_auto_review is False
    dumped = snap.model_dump(by_alias=True)
    assert dumped["approval.auto_review"] is False
    assert snap.vision is False


def test_error_retryability() -> None:
    assert RETRYABLE["TIMEOUT"] is True
    assert RETRYABLE["OVERLOADED"] is True
    assert RETRYABLE["PROTOCOL_MISMATCH"] is False
    assert RETRYABLE["UNSUPPORTED"] is False
    payload = ProtocolErrorData(error_code="PROTOCOL_MISMATCH", retryable=False)
    assert payload.protocol_min == PROTOCOL_VERSION_MIN
    assert payload.protocol_max == PROTOCOL_VERSION_MAX


def test_schema_contains_b2_models() -> None:
    defs = export_schema()["$defs"]
    for name in (
        "InitializeResult",
        "CapabilitySnapshot",
        "ProtocolErrorData",
        "InitializedNotification",
    ):
        assert name in defs
    init = defs["InitializeRequest"]["properties"]
    assert "client_info" in init
    assert "client_capabilities" in init
    assert "requested_features" in init
    assert export_schema()["protocol_version"] == PROTOCOL_VERSION


def test_initialized_notification_method() -> None:
    note = InitializedNotification(
        protocol_version=PROTOCOL_VERSION, server_version="1.2.10"
    )
    assert note.method == "initialized"
