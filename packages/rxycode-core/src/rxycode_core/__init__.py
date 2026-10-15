"""Install-time identity for the one historical Session class.

This package does not copy AgentV2. Session and reuse_or_create_session are
the class and function objects defined in RxyCode.RxyCode1_1_0.core.session.
"""

from __future__ import annotations

from RxyCode.RxyCode1_1_0.core.session import Session, reuse_or_create_session

__all__ = ["Session", "audit_class_identity", "reuse_or_create_session"]


def audit_class_identity(classes: list[type]) -> str:
    """Return OK when every entry is the same class object, otherwise BLOCKED."""
    if len(set(classes)) > 1:
        return "BLOCKED"
    return "OK"
