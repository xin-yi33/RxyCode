"""Shared protocol literals aligned with runtime enums and SSE payloads."""

from typing import Any, Literal, TypeAlias

# Values from ``RiskLevel.name`` in core/safety/policy.py (READ, WRITE, DANGER).
RiskLevelName: TypeAlias = Literal["READ", "WRITE", "DANGER"]

# Terminal run statuses from ``classify_agent_result`` in log/log_helpers.py.
RunStatus: TypeAlias = Literal["succeeded", "failed", "cancelled", "timed_out"]

# Background job lifecycle strings used by api_server lifespan / task services (P4).
JobState: TypeAlias = Literal["submitted", "running", "failed"]

# Client decisions for ``POST /approve`` (api_server.py) and ApprovalDecision in core/safety/approval.py.
ApprovalDecisionName: TypeAlias = Literal[
    "approved",
    "rejected",
    "allow_once",
    "always_allow_level",
]

JsonObject: TypeAlias = dict[str, Any]
