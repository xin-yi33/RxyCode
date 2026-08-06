"""PermissionPolicy — allow/ask/deny evaluation with approval.

B9 · Implements the permission model:
  - Agent-level rules override global defaults but never system hard-reject.
  - Rules for the same tool match in configuration order; LAST match wins.
  - `task` permission matches by target agent id, never blanket recursion.
  - `external_directory` is controlled separately from read/edit.
  - `ask` produces a trackable ApprovalRequest; the decision is bound to
    session_id, tool_call_id, path, and rule version.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any
from uuid import uuid4

from protocol.subagents import (
    PermissionRule,
    PermissionSpec,
    PermissionVerdict,
)


# ---------------------------------------------------------------------------
# Pattern matching
# ---------------------------------------------------------------------------

def _matches(pattern: str, value: str, *, path_mode: bool = False) -> bool:
    """Match a permission pattern against a tool input value.

    Supports:
      - ``**`` recursive glob (matches zero or more path segments)
      - glob patterns (``src/**``, ``**/*.secret``, ``pytest *``)
      - exact match

    In ``path_mode`` (read/edit/open_file), values are matched on
    ``/``-separated segments so ``**`` correctly crosses directories and
    matches zero segments (``src/**/*.secret`` matches ``src/config.secret``).

    Otherwise plain fnmatch is used on the whole string (commands, URLs,
    agent ids) — fnmatch ``*`` already crosses ``/`` in those contexts.
    """
    import fnmatch

    if pattern == "**" or pattern == "*":
        return True
    if pattern == value:
        return True

    if path_mode:
        pat_segs = pattern.split("/")
        val_segs = value.split("/")
        return _match_segments(tuple(pat_segs), tuple(val_segs))

    return fnmatch.fnmatch(value, pattern)


def _match_segments(pat_segs: tuple[str, ...], val_segs: tuple[str, ...]) -> bool:
    """Recursive segment matcher with ``**`` support."""
    import fnmatch

    if not pat_segs:
        return not val_segs

    first = pat_segs[0]
    rest = pat_segs[1:]

    if first == "**":
        # Try matching 0..N value segments before consuming the rest
        for consumed in range(len(val_segs) + 1):
            if _match_segments(rest, val_segs[consumed:]):
                return True
        return False

    if not val_segs:
        return False

    head = val_segs[0]
    tail = val_segs[1:]

    if fnmatch.fnmatch(head, first) or head == first:
        return _match_segments(rest, tail)

    return False


# ---------------------------------------------------------------------------
# Decision
# ---------------------------------------------------------------------------

class DecisionKind(str, Enum):
    ALLOW = "allow"
    ASK = "ask"
    DENY = "deny"


@dataclass(frozen=True)
class PermissionDecision:
    """Result of evaluating a tool call against a permission policy."""

    kind: DecisionKind
    tool: str
    matched_rule: str = ""       # The rule pattern that decided
    rule_version: str = ""       # Agent definition version snapshot
    reason: str = ""

    @property
    def allows(self) -> bool:
        return self.kind == DecisionKind.ALLOW

    @property
    def requires_approval(self) -> bool:
        return self.kind == DecisionKind.ASK


# ---------------------------------------------------------------------------
# System hard-reject rules (cannot be overridden by agent config)
# ---------------------------------------------------------------------------

_SYSTEM_HARD_DENY_TOOLS: dict[str, tuple[str, ...]] = {
    # tool name → patterns that are always denied
    "edit": ("**/.git/**", "**/venv/**", "**/.venv/**"),
    "delete": ("**",),                       # delete is always hard-denied for children
    "bash": ("git push **", "rm -rf **", "rm -fr **", "pip uninstall **", "npm publish **"),
}

# Paths outside the project that children can never touch when external_directory=deny
_SYSTEM_PROTECTED_PATHS: tuple[Path, ...] = ()


def is_system_hard_denied(tool: str, value: str) -> str | None:
    """Return the matched hard-deny pattern for a tool call, or None.

    System hard-reject rules always win over agent permissions.
    """
    path_mode = tool in ("read", "edit", "open_file")
    patterns = _SYSTEM_HARD_DENY_TOOLS.get(tool, ())
    for pattern in patterns:
        if _matches(pattern, value, path_mode=path_mode):
            return pattern
    return None


# ---------------------------------------------------------------------------
# PermissionPolicy
# ---------------------------------------------------------------------------

@dataclass
class PermissionPolicy:
    """Evaluates tool calls against an agent's PermissionSpec.

    A policy is built per child session (from its AgentDefinition snapshot).
    """

    permission: PermissionSpec
    definition_version: str = "unknown"
    external_directory: PermissionVerdict = PermissionVerdict.DENY
    workspace_root: Path | None = None

    @classmethod
    def from_definition(
        cls,
        permission: PermissionSpec,
        *,
        definition_version: str = "unknown",
        workspace_root: Path | None = None,
    ) -> PermissionPolicy:
        """Build a policy from an AgentDefinition's permission spec."""
        return cls(
            permission=permission,
            definition_version=definition_version,
            external_directory=permission.external_directory,
            workspace_root=workspace_root,
        )

    # -- core evaluation -----------------------------------------------------

    def evaluate(self, tool: str, value: str = "") -> PermissionDecision:
        """Evaluate a tool call and return a decision.

        Order:
          1. system hard-reject (always wins)
          2. external_directory check (if tool touches paths)
          3. agent rule matching (last matching rule wins)
          4. default deny
        """
        # 1. System hard-reject
        hard = is_system_hard_denied(tool, value)
        if hard is not None:
            return PermissionDecision(
                kind=DecisionKind.DENY,
                tool=tool,
                matched_rule=f"system:{hard}",
                rule_version=self.definition_version,
                reason="system hard-reject",
            )

        # 2. external_directory
        if self._touches_external_path(tool, value) and self.external_directory != PermissionVerdict.ALLOW:
            verdict = (
                PermissionVerdict.ASK
                if self.external_directory == PermissionVerdict.ASK
                else PermissionVerdict.DENY
            )
            return PermissionDecision(
                kind=DecisionKind(verdict.value),
                tool=tool,
                matched_rule="external_directory",
                rule_version=self.definition_version,
                reason="path outside workspace",
            )

        # 3. Agent rules (ordered; last match wins)
        path_mode = tool in ("read", "edit", "open_file")
        rules = self._rules_for(tool)
        matched: PermissionRule | None = None
        for rule in rules:
            if _matches(rule.pattern, value or "", path_mode=path_mode):
                matched = rule

        if matched is None:
            # 4. default deny
            return PermissionDecision(
                kind=DecisionKind.DENY,
                tool=tool,
                matched_rule="(no-rule)",
                rule_version=self.definition_version,
                reason="no matching rule; default deny",
            )

        return PermissionDecision(
            kind=DecisionKind(matched.verdict.value),
            tool=tool,
            matched_rule=matched.pattern,
            rule_version=self.definition_version,
        )

    def _rules_for(self, tool: str) -> tuple[PermissionRule, ...]:
        """Return the ordered rules for a tool category."""
        mapping = {
            "read": self.permission.read,
            "edit": self.permission.edit,
            "bash": self.permission.bash,
            "webfetch": self.permission.webfetch,
            "websearch": self.permission.websearch,
            "task": self.permission.task,
        }
        tp = mapping.get(tool)
        return tuple(tp.rules) if tp is not None else ()

    def _touches_external_path(self, tool: str, value: str) -> bool:
        """Check whether a tool call references a path outside the workspace."""
        if tool not in ("read", "edit", "bash", "open_file"):
            return False
        if not value:
            return False
        if self.workspace_root is None:
            return False

        p = Path(value)
        if not p.is_absolute():
            # Relative paths are inside the workspace
            return False

        try:
            return p.resolve() not in self.workspace_root.resolve().parents and p.resolve() != self.workspace_root.resolve()
        except OSError:
            return True


# ---------------------------------------------------------------------------
# Approval
# ---------------------------------------------------------------------------

class ApprovalDecision(str, Enum):
    APPROVED = "approved"
    REJECTED = "rejected"
    ALLOW_ONCE = "allow_once"
    ALWAYS_ALLOW_LEVEL = "always_allow_level"


@dataclass
class ApprovalRequest:
    """A pending approval created by an `ask` verdict."""

    approval_id: str = field(default_factory=lambda: str(uuid4()))
    session_id: str = ""
    tool_call_id: str = ""
    tool: str = ""
    args_summary: str = ""
    matched_rule: str = ""
    rule_version: str = ""
    reason: str = ""
    created_at: float = field(default_factory=time.time)
    decision: ApprovalDecision | None = None
    decided_at: float | None = None


@dataclass
class ApprovalManager:
    """Tracks pending approvals and records decisions for audit."""

    # pending approvals: approval_id → ApprovalRequest
    _pending: dict[str, ApprovalRequest] = field(default_factory=dict)
    # already-resolved approval ids (for double-resolve detection)
    _resolved_ids: set[str] = field(default_factory=set)
    # decision log (audit-consumable): list of decision records
    _log: list[dict[str, Any]] = field(default_factory=list)

    def request(
        self,
        session_id: str,
        tool_call_id: str,
        tool: str,
        args_summary: str,
        *,
        matched_rule: str,
        rule_version: str,
        reason: str = "",
    ) -> ApprovalRequest:
        """Create a pending approval request."""
        req = ApprovalRequest(
            session_id=session_id,
            tool_call_id=tool_call_id,
            tool=tool,
            args_summary=args_summary,
            matched_rule=matched_rule,
            rule_version=rule_version,
            reason=reason,
        )
        self._pending[req.approval_id] = req
        return req

    def resolve(self, approval_id: str, decision: ApprovalDecision) -> ApprovalRequest:
        """Resolve a pending approval and record the decision.

        Resolving the same approval twice is an error (idempotency guard).
        """
        if approval_id in self._resolved_ids:
            raise ValueError(f"Approval already resolved: {approval_id}")

        req = self._pending.get(approval_id)
        if req is None:
            raise KeyError(f"No pending approval: {approval_id}")

        req.decision = decision
        req.decided_at = time.time()

        self._log.append({
            "approval_id": approval_id,
            "session_id": req.session_id,
            "tool_call_id": req.tool_call_id,
            "tool": req.tool,
            "args_summary": req.args_summary,
            "matched_rule": req.matched_rule,
            "rule_version": req.rule_version,
            "decision": decision.value,
            "decided_at": req.decided_at,
        })

        del self._pending[approval_id]
        self._resolved_ids.add(approval_id)
        return req

    def get_pending(self, approval_id: str) -> ApprovalRequest | None:
        return self._pending.get(approval_id)

    def pending_for_session(self, session_id: str) -> list[ApprovalRequest]:
        return [r for r in self._pending.values() if r.session_id == session_id]

    def decision_log(self) -> list[dict[str, Any]]:
        """Return the decision log (consumable by Desktop audit panel)."""
        return list(self._log)

    def is_resolved(self, approval_id: str) -> bool:
        return approval_id not in self._pending

    def __len__(self) -> int:
        return len(self._pending)
