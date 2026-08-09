"""B9 · PermissionPolicy, approval, and agent task permission tests."""

from __future__ import annotations

import pytest

from protocol.subagents import (
    PermissionRule,
    PermissionSpec,
    PermissionVerdict,
    ToolPermission,
)
from core.subagents.permissions import (
    ApprovalDecision,
    ApprovalManager,
    ApprovalRequest,
    DecisionKind,
    PermissionDecision,
    PermissionPolicy,
    _matches,
    is_system_hard_denied,
)


# ============================================================================
# Pattern matching
# ============================================================================

class TestPatternMatching:
    """Glob/exact/catch-all pattern matching."""

    @pytest.mark.parametrize("pattern,value,expected", [
        ("**", "anything", True),
        ("*", "anything", True),
        ("src/**", "src/auth.py", True),
        ("src/**", "src/nested/deep/file.py", True),
        ("src/**", "tests/auth.py", False),
        ("**/*.secret", "src/config.secret", True),
        ("pytest *", "pytest tests -q", True),
        ("pytest *", "git status", False),
        ("exact", "exact", True),
        ("exact", "different", False),
        ("core/auth.py", "core/auth.py", True),
    ])
    def test_matches(self, pattern, value, expected):
        assert _matches(pattern, value) is expected


# ============================================================================
# System hard-reject
# ============================================================================

class TestSystemHardReject:
    """System hard-reject rules always win."""

    def test_git_push_denied(self):
        assert is_system_hard_denied("bash", "git push origin main") is not None

    def test_rm_rf_denied(self):
        assert is_system_hard_denied("bash", "rm -rf /tmp") is not None

    def test_git_config_path_denied(self):
        assert is_system_hard_denied("edit", ".git/config") is not None

    def test_benign_bash_allowed(self):
        assert is_system_hard_denied("bash", "pytest tests -q") is None

    def test_normal_read_not_denied(self):
        assert is_system_hard_denied("read", "src/auth.py") is None


# ============================================================================
# PermissionPolicy evaluation
# ============================================================================

class TestPolicyEvaluation:
    """Core allow/ask/deny evaluation."""

    def _policy(self, permission: PermissionSpec) -> PermissionPolicy:
        return PermissionPolicy.from_definition(permission, definition_version="v1.0")

    def test_default_deny_no_rules(self):
        policy = self._policy(PermissionSpec())
        decision = policy.evaluate("read", "anything")
        assert decision.kind == DecisionKind.DENY
        assert decision.matched_rule == "(no-rule)"

    def test_allow_rule(self):
        spec = PermissionSpec(
            read=ToolPermission.from_raw({"**": "allow"}),
        )
        decision = self._policy(spec).evaluate("read", "src/auth.py")
        assert decision.kind == DecisionKind.ALLOW
        assert decision.allows

    def test_last_matching_rule_wins(self):
        """Rules evaluated in order; LAST match wins."""
        spec = PermissionSpec(
            read=ToolPermission.from_raw({
                "src/**": "allow",
                "src/**/*.secret": "deny",
            }),
        )
        policy = self._policy(spec)

        # "src/auth.py" → matches only the allow rule
        assert policy.evaluate("read", "src/auth.py").kind == DecisionKind.ALLOW

        # "src/config.secret" → matches both; last (deny) wins
        decision = policy.evaluate("read", "src/config.secret")
        assert decision.kind == DecisionKind.DENY
        assert decision.matched_rule == "src/**/*.secret"

    def test_deny_beats_default_allow(self):
        spec = PermissionSpec(
            read=ToolPermission.from_raw({
                "**": "allow",
                "**/*.secret": "deny",
            }),
        )
        policy = self._policy(spec)
        assert policy.evaluate("read", "any.py").kind == DecisionKind.ALLOW
        assert policy.evaluate("read", "keys.secret").kind == DecisionKind.DENY

    def test_ask_produces_requires_approval(self):
        spec = PermissionSpec(
            edit=ToolPermission.from_raw({"src/**": "ask"}),
        )
        policy = self._policy(spec)
        decision = policy.evaluate("edit", "src/auth.py")
        assert decision.kind == DecisionKind.ASK
        assert decision.requires_approval
        assert not decision.allows

    def test_system_hard_reject_overrides_allow(self):
        """Agent allow cannot override system hard-reject."""
        spec = PermissionSpec(
            edit=ToolPermission.from_raw({"**": "allow"}),
        )
        policy = self._policy(spec)
        decision = policy.evaluate("edit", ".git/config")
        assert decision.kind == DecisionKind.DENY
        assert decision.matched_rule.startswith("system:")

    def test_each_tool_has_own_rules(self):
        spec = PermissionSpec(
            read=ToolPermission.from_raw({"**": "allow"}),
            edit=ToolPermission.from_raw({"**": "deny"}),
        )
        policy = self._policy(spec)
        assert policy.evaluate("read", "x.py").kind == DecisionKind.ALLOW
        assert policy.evaluate("edit", "x.py").kind == DecisionKind.DENY

    def test_definition_version_carried(self):
        policy = PermissionPolicy.from_definition(
            PermissionSpec(read=ToolPermission.from_raw({"**": "allow"})),
            definition_version="def-abc123",
        )
        decision = policy.evaluate("read", "x")
        assert decision.rule_version == "def-abc123"


# ============================================================================
# external_directory
# ============================================================================

class TestExternalDirectory:
    """external_directory is controlled separately from read/edit."""

    def _policy_with_root(self, ext: PermissionVerdict) -> PermissionPolicy:
        spec = PermissionSpec(
            read=ToolPermission.from_raw({"**": "allow"}),
            external_directory=ext,
        )
        return PermissionPolicy.from_definition(
            spec,
            definition_version="v1",
            workspace_root=None,  # No root → no external detection
        )

    def test_external_directory_deny(self):
        """With workspace_root set, absolute external paths are denied."""
        spec = PermissionSpec(
            read=ToolPermission.from_raw({"**": "allow"}),
            external_directory=PermissionVerdict.DENY,
        )
        policy = PermissionPolicy.from_definition(
            spec, definition_version="v1",
            workspace_root=__import__("pathlib").Path("C:/workspace"),
        )
        decision = policy.evaluate("read", "C:/outside/file.txt")
        assert decision.kind == DecisionKind.DENY
        assert decision.matched_rule == "external_directory"

    def test_external_directory_allow(self):
        spec = PermissionSpec(
            read=ToolPermission.from_raw({"**": "allow"}),
            external_directory=PermissionVerdict.ALLOW,
        )
        policy = PermissionPolicy.from_definition(
            spec, definition_version="v1",
            workspace_root=__import__("pathlib").Path("C:/workspace"),
        )
        decision = policy.evaluate("read", "C:/outside/file.txt")
        assert decision.kind == DecisionKind.ALLOW

    def test_external_directory_ask(self):
        spec = PermissionSpec(
            read=ToolPermission.from_raw({"**": "allow"}),
            external_directory=PermissionVerdict.ASK,
        )
        policy = PermissionPolicy.from_definition(
            spec, definition_version="v1",
            workspace_root=__import__("pathlib").Path("C:/workspace"),
        )
        decision = policy.evaluate("read", "C:/outside/file.txt")
        assert decision.kind == DecisionKind.ASK

    def test_relative_path_not_external(self):
        spec = PermissionSpec(
            read=ToolPermission.from_raw({"**": "allow"}),
            external_directory=PermissionVerdict.DENY,
        )
        policy = PermissionPolicy.from_definition(
            spec, definition_version="v1",
            workspace_root=__import__("pathlib").Path("C:/workspace"),
        )
        # Relative paths are inside the workspace
        decision = policy.evaluate("read", "src/auth.py")
        assert decision.kind == DecisionKind.ALLOW


# ============================================================================
# Task permission (agent-level)
# ============================================================================

class TestTaskPermissionRules:
    """task permission matches by target agent id."""

    def test_task_allows_explore_denies_general(self):
        spec = PermissionSpec(
            task=ToolPermission.from_raw({
                "explore": "allow",
                "general": "deny",
            }),
        )
        policy = PermissionPolicy.from_definition(spec, definition_version="v1")
        assert policy.evaluate("task", "explore").kind == DecisionKind.ALLOW
        assert policy.evaluate("task", "general").kind == DecisionKind.DENY

    def test_task_default_deny(self):
        spec = PermissionSpec(task=ToolPermission.from_raw({"**": "deny"}))
        policy = PermissionPolicy.from_definition(spec, definition_version="v1")
        assert policy.evaluate("task", "any_agent").kind == DecisionKind.DENY

    def test_task_last_rule_wins(self):
        spec = PermissionSpec(
            task=ToolPermission.from_raw({
                "explore": "allow",
                "**": "deny",
            }),
        )
        policy = PermissionPolicy.from_definition(spec, definition_version="v1")
        # explore matches "explore" (allow) AND "**" (deny) — last wins → deny
        assert policy.evaluate("task", "explore").kind == DecisionKind.DENY


# ============================================================================
# Approval manager
# ============================================================================

class TestApprovalManager:
    """Approval request lifecycle and audit log."""

    def test_create_approval(self):
        mgr = ApprovalManager()
        req = mgr.request(
            session_id="ses_child_1",
            tool_call_id="call_1",
            tool="edit",
            args_summary="path=src/auth.py",
            matched_rule="src/**",
            rule_version="v1.0",
        )
        assert isinstance(req, ApprovalRequest)
        assert req.approval_id != ""
        assert mgr.is_resolved(req.approval_id) is False
        assert len(mgr) == 1

    def test_resolve_approved(self):
        mgr = ApprovalManager()
        req = mgr.request(
            session_id="ses_child_1", tool_call_id="call_1", tool="edit",
            args_summary="x", matched_rule="r", rule_version="v1",
        )
        resolved = mgr.resolve(req.approval_id, ApprovalDecision.APPROVED)
        assert resolved.decision == ApprovalDecision.APPROVED
        assert resolved.decided_at is not None
        assert mgr.is_resolved(req.approval_id) is True
        assert len(mgr) == 0

    def test_resolve_rejected(self):
        mgr = ApprovalManager()
        req = mgr.request(
            session_id="s1", tool_call_id="c1", tool="bash",
            args_summary="git push", matched_rule="**", rule_version="v1",
        )
        resolved = mgr.resolve(req.approval_id, ApprovalDecision.REJECTED)
        assert resolved.decision == ApprovalDecision.REJECTED

    def test_resolve_unknown_raises(self):
        mgr = ApprovalManager()
        with pytest.raises(KeyError):
            mgr.resolve("nonexistent", ApprovalDecision.APPROVED)

    def test_resolve_twice_raises(self):
        mgr = ApprovalManager()
        req = mgr.request(
            session_id="s1", tool_call_id="c1", tool="edit",
            args_summary="x", matched_rule="r", rule_version="v1",
        )
        mgr.resolve(req.approval_id, ApprovalDecision.APPROVED)
        with pytest.raises(ValueError, match="already resolved"):
            mgr.resolve(req.approval_id, ApprovalDecision.APPROVED)

    def test_decision_log_audit_consumable(self):
        """Decision log carries full audit context for Desktop."""
        mgr = ApprovalManager()
        req = mgr.request(
            session_id="ses_child_1",
            tool_call_id="call_7",
            tool="edit",
            args_summary="path=src/auth.py, mode=write",
            matched_rule="src/**",
            rule_version="def-abc",
        )
        mgr.resolve(req.approval_id, ApprovalDecision.ALLOW_ONCE)

        log = mgr.decision_log()
        assert len(log) == 1
        entry = log[0]
        assert entry["session_id"] == "ses_child_1"
        assert entry["tool_call_id"] == "call_7"
        assert entry["tool"] == "edit"
        assert entry["matched_rule"] == "src/**"
        assert entry["rule_version"] == "def-abc"
        assert entry["decision"] == "allow_once"
        assert entry["decided_at"] is not None

    def test_pending_for_session(self):
        mgr = ApprovalManager()
        mgr.request(session_id="s1", tool_call_id="c1", tool="edit", args_summary="x", matched_rule="r", rule_version="v1")
        mgr.request(session_id="s2", tool_call_id="c2", tool="edit", args_summary="y", matched_rule="r", rule_version="v1")
        pending_s1 = mgr.pending_for_session("s1")
        assert len(pending_s1) == 1
        assert pending_s1[0].session_id == "s1"

    def test_approval_binds_tool_call_and_path(self):
        """Approval must bind session, tool_call, path, rule version."""
        mgr = ApprovalManager()
        req = mgr.request(
            session_id="ses_child_9",
            tool_call_id="call_99",
            tool="edit",
            args_summary="path=src/core.py",
            matched_rule="src/**",
            rule_version="def-v3",
        )
        assert req.session_id == "ses_child_9"
        assert req.tool_call_id == "call_99"
        assert req.args_summary == "path=src/core.py"
        assert req.rule_version == "def-v3"
