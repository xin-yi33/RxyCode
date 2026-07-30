"""core.safety — RxyCode safety防线 (阶段二).

Public API. Adapted from OpenHands (MIT) openhands/security/ — three-tier
risk model + confirmation mode + audit trail; design ported, no vendoring.
"""

from .policy import (
    RiskLevel,
    TOOL_RISK_TABLE,
    DANGEROUS_COMMAND_PATTERNS,
    classify_bash_command,
    classify_tool_risk,
    get_tool_risk,
    register_tool_risk,
    is_write_allowed,
    is_dry_run,
    summarize_args,
)
from .approval import (
    ApprovalRequest,
    ApprovalDecision,
    ApprovalBroker,
    TuiApproval,
    SseApproval,
    get_approval_broker,
    set_approval_broker,
)
from .audit import AuditLogger, get_audit_logger, sanitize_args

__all__ = [
    "RiskLevel",
    "TOOL_RISK_TABLE",
    "DANGEROUS_COMMAND_PATTERNS",
    "classify_bash_command",
    "classify_tool_risk",
    "get_tool_risk",
    "register_tool_risk",
    "is_write_allowed",
    "is_dry_run",
    "summarize_args",
    "ApprovalRequest",
    "ApprovalDecision",
    "ApprovalBroker",
    "TuiApproval",
    "SseApproval",
    "get_approval_broker",
    "set_approval_broker",
    "AuditLogger",
    "get_audit_logger",
    "sanitize_args",
]
