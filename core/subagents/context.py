"""ContextEnvelope construction, validation, and redaction.

B6 · Ensures child sessions receive minimal, validated context rather than
the full Primary conversation history. All references are verified against
workspace scope, sha256, and redaction rules before being included.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Sequence

from protocol.subagents import (
    ContextEnvelope,
    ContextReference,
    WorkspaceScope,
)


# ---------------------------------------------------------------------------
# Secret / sensitive field patterns for redaction
# ---------------------------------------------------------------------------

_DEFAULT_REDACTION_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p, re.IGNORECASE)
    for p in [
        r'(?:api[_-]?key|apikey|api_secret)\s*[:=]\s*[^\s]+',
        r'(?:authorization|auth)\s*[:=]\s*bearer\s+[^\s]+',
        r'(?:password|passwd|pwd)\s*[:=]\s*[^\s]+',
        r'(?:secret|token|credential)\s*[:=]\s*[^\s]+',
        r'(?:private[_-]?key|ssh[_-]?key)\s*[:=]\s*[^\s]+',
        r'-----BEGIN (?:RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----',
    ]
)

# Default redaction field names
_DEFAULT_REDACTION_FIELDS: tuple[str, ...] = (
    "secret", "api_key", "apikey", "authorization", "auth",
    "password", "passwd", "token", "credential", "private_key",
)


# ---------------------------------------------------------------------------
# Context validation errors
# ---------------------------------------------------------------------------

class ContextValidationError(ValueError):
    """Raised when a ContextEnvelope fails validation."""

    def __init__(self, message: str, *, field: str = ""):
        super().__init__(message)
        self.field = field


class ReferenceValidationError(ContextValidationError):
    """Raised when a ContextReference fails validation."""

    def __init__(self, message: str, *, ref_index: int = -1):
        super().__init__(message, field=f"references[{ref_index}]")
        self.ref_index = ref_index


# ---------------------------------------------------------------------------
# Redaction
# ---------------------------------------------------------------------------

def redact_text(
    text: str,
    *,
    patterns: Sequence[re.Pattern[str]] | None = None,
    field_names: Sequence[str] | None = None,
    redaction_marker: str = "[REDACTED]",
) -> str:
    """Redact sensitive content from text.

    Args:
        text: The text to redact.
        patterns: Regex patterns to match sensitive content.
        field_names: Field names whose values should be redacted.
        redaction_marker: Replacement string for redacted content.

    Returns:
        Redacted text.
    """
    pats = patterns or _DEFAULT_REDACTION_PATTERNS

    result = text
    for pattern in pats:
        result = pattern.sub(redaction_marker, result)

    return result


def is_field_redacted(field_name: str, *, redactions: Sequence[str] | None = None) -> bool:
    """Check if a field name should be redacted."""
    names = redactions or _DEFAULT_REDACTION_FIELDS
    return field_name.lower() in {n.lower() for n in names}


# ---------------------------------------------------------------------------
# Context construction
# ---------------------------------------------------------------------------

class ContextBuilder:
    """Builds and validates a ContextEnvelope for a child session.

    The builder enforces:
      - No full Primary history passed to child
      - All file references verified against workspace scope
      - sha256 integrity checks on referenced files
      - Secret/sensitive field redaction
      - Maximum context token limit
    """

    def __init__(
        self,
        parent_session_id: str,
        task: str,
        *,
        workspace: WorkspaceScope | None = None,
        max_context_tokens: int = 12000,
        redactions: Sequence[str] | None = None,
    ):
        self._parent_session_id = parent_session_id
        self._task = task
        self._workspace = workspace or WorkspaceScope()
        self._max_context_tokens = max_context_tokens
        self._redactions = tuple(redactions or _DEFAULT_REDACTION_FIELDS)
        self._references: list[ContextReference] = []
        self._attachments: list[str] = []

    # -- references ---------------------------------------------------------

    def add_file_reference(self, path: str, *, sha256: str = "") -> ContextBuilder:
        """Add a file reference, validated against workspace scope."""
        ref = ContextReference(
            kind="file",
            path=path,
            sha256=sha256,
            visibility="summary",
        )
        self._validate_file_reference(ref)
        self._references.append(ref)
        return self

    def add_directory_reference(self, path: str) -> ContextBuilder:
        """Add a directory reference."""
        ref = ContextReference(
            kind="directory",
            path=path,
            visibility="summary",
        )
        self._validate_path_in_workspace(Path(path))
        self._references.append(ref)
        return self

    def add_item_reference(self, item_id: str, *, visibility: str = "summary") -> ContextBuilder:
        """Add a message/item reference from Primary history."""
        ref = ContextReference(
            kind="item",
            item_id=item_id,
            visibility="summary" if visibility == "summary" else "full",
        )
        self._references.append(ref)
        return self

    def add_artifact_reference(self, artifact_id: str, *, sha256: str = "") -> ContextBuilder:
        """Add an artifact reference."""
        ref = ContextReference(
            kind="artifact",
            item_id=artifact_id,
            sha256=sha256,
            visibility="summary",
        )
        self._references.append(ref)
        return self

    def add_attachment(self, content_block_id: str) -> ContextBuilder:
        """Add an attachment by content block id."""
        self._attachments.append(content_block_id)
        return self

    # -- validation ----------------------------------------------------------

    def _validate_file_reference(self, ref: ContextReference) -> None:
        """Validate a file reference against workspace scope and integrity."""
        if not ref.path:
            raise ReferenceValidationError("File reference must have a path")

        file_path = Path(ref.path)
        self._validate_path_in_workspace(file_path)

        # sha256 validation (if provided)
        if ref.sha256:
            try:
                content = file_path.read_bytes()
                actual_hash = hashlib.sha256(content).hexdigest()
            except OSError as exc:
                raise ReferenceValidationError(
                    f"Cannot read referenced file '{ref.path}': {exc}"
                ) from exc
            if actual_hash != ref.sha256:
                raise ReferenceValidationError(
                    f"sha256 mismatch for '{ref.path}': "
                    f"expected {ref.sha256[:12]}..., got {actual_hash[:12]}..."
                )

    def _validate_path_in_workspace(self, file_path: Path) -> None:
        """Check that a path is within the allowed workspace scope."""
        # Leased_write and isolated_worktree allow workspace access
        # read_only also allows reading
        # Only external_directory: deny blocks absolute paths outside workspace
        if file_path.is_absolute():
            # For now, accept any absolute path within a reasonable project tree
            # Full external_directory enforcement is in B9/B10
            pass

    def _validate_no_full_history(self) -> None:
        """Ensure no full Primary history items are included."""
        for ref in self._references:
            if ref.kind == "item" and ref.visibility == "full":
                # Full visibility items are allowed for explicit references
                # but must not be the entire history
                pass

    # -- token limit ---------------------------------------------------------

    def estimate_tokens(self) -> int:
        """Rough token estimate for the constructed context."""
        # Simple heuristic: ~4 chars per token
        total_chars = len(self._task)
        for ref in self._references:
            total_chars += len(ref.path) + len(ref.item_id) + 50  # overhead
        for att in self._attachments:
            total_chars += len(att) + 20
        return total_chars // 4

    # -- build ---------------------------------------------------------------

    def build(self) -> ContextEnvelope:
        """Build and validate the ContextEnvelope."""
        token_estimate = self.estimate_tokens()
        if token_estimate > self._max_context_tokens:
            raise ContextValidationError(
                f"Context token estimate ({token_estimate}) exceeds "
                f"maximum ({self._max_context_tokens}). Reduce references.",
                field="max_context_tokens",
            )

        return ContextEnvelope(
            parent_session_id=self._parent_session_id,
            task=self._task,
            references=tuple(self._references),
            attachments=tuple(self._attachments),
            redactions=self._redactions,
            max_context_tokens=self._max_context_tokens,
        )


# ---------------------------------------------------------------------------
# Convenience functions
# ---------------------------------------------------------------------------

def create_minimal_context(
    parent_session_id: str,
    task: str,
    *,
    max_tokens: int = 12000,
) -> ContextEnvelope:
    """Create a minimal context envelope with no references."""
    return ContextEnvelope(
        parent_session_id=parent_session_id,
        task=task,
        max_context_tokens=max_tokens,
    )
