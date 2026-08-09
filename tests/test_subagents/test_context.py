"""B6 · ContextEnvelope, references, and redaction tests."""

from __future__ import annotations

import pytest

from protocol.subagents import (
    ContextEnvelope,
    ContextReference,
    WorkspaceMode,
    WorkspaceScope,
)
from core.subagents.context import (
    ContextBuilder,
    ContextValidationError,
    ReferenceValidationError,
    create_minimal_context,
    is_field_redacted,
    redact_text,
)


# ============================================================================
# Redaction
# ============================================================================

class TestRedaction:
    """Secret/sensitive field redaction."""

    def test_redact_api_key(self):
        text = "api_key=sk-abc123def456"
        result = redact_text(text)
        assert "sk-abc123def456" not in result
        assert "[REDACTED]" in result

    def test_redact_authorization_bearer(self):
        text = "Authorization: Bearer fake-eyJhbGciOiJIUzI1NiJ9.abc.def"
        result = redact_text(text)
        assert "fake-eyJhbGciOiJIUzI1NiJ9" not in result
        assert "[REDACTED]" in result

    def test_redact_password(self):
        text = "password=supersecret123"
        result = redact_text(text)
        assert "supersecret123" not in result
        assert "[REDACTED]" in result

    def test_redact_private_key_block(self):
        text = "-----BEGIN RSA " + "PRIVATE KEY-----\\nfake-AAAA\\n-----END RSA " + "PRIVATE KEY-----"
        result = redact_text(text)
        assert "RSA PRIVATE KEY" in result  # Marker text remains
        assert "[REDACTED]" in result

    def test_plain_text_not_redacted(self):
        text = "The quick brown fox jumps over the lazy dog."
        result = redact_text(text)
        assert result == text

    def test_custom_redaction_marker(self):
        text = "api_key=sk-secret"
        result = redact_text(text, redaction_marker="<HIDDEN>")
        assert "<HIDDEN>" in result
        assert "sk-secret" not in result

    def test_is_field_redacted(self):
        assert is_field_redacted("api_key") is True
        assert is_field_redacted("API_KEY") is True
        assert is_field_redacted("authorization") is True
        assert is_field_redacted("password") is True
        assert is_field_redacted("prompt") is False
        assert is_field_redacted("path") is False

    def test_custom_redaction_fields(self):
        assert is_field_redacted("phone", redactions=["phone"]) is True
        assert is_field_redacted("api_key", redactions=["phone"]) is False


# ============================================================================
# Context building
# ============================================================================

class TestContextBuilder:
    """ContextBuilder constructs valid minimal context envelopes."""

    def test_minimal_context(self):
        ctx = ContextBuilder("ses_primary_1", "探索认证模块").build()
        assert ctx.parent_session_id == "ses_primary_1"
        assert ctx.task == "探索认证模块"
        assert ctx.references == ()
        assert ctx.attachments == ()
        assert ctx.max_context_tokens == 12000

    def test_add_file_reference(self):
        builder = ContextBuilder("ses_primary_1", "探索文件")
        builder.add_file_reference("core/auth.py")
        ctx = builder.build()
        assert len(ctx.references) == 1
        assert ctx.references[0].kind == "file"
        assert ctx.references[0].path == "core/auth.py"

    def test_add_directory_reference(self):
        builder = ContextBuilder("ses_primary_1", "探索目录")
        builder.add_directory_reference("protocol")
        ctx = builder.build()
        assert ctx.references[0].kind == "directory"
        assert ctx.references[0].path == "protocol"

    def test_add_item_reference(self):
        builder = ContextBuilder("ses_primary_1", "总结引用")
        builder.add_item_reference("turn_42.item_7", visibility="summary")
        ctx = builder.build()
        assert ctx.references[0].kind == "item"
        assert ctx.references[0].item_id == "turn_42.item_7"
        assert ctx.references[0].visibility == "summary"

    def test_add_attachment(self):
        builder = ContextBuilder("ses_primary_1", "附件测试")
        builder.add_attachment("block_123")
        ctx = builder.build()
        assert ctx.attachments == ("block_123",)

    def test_custom_max_tokens(self):
        builder = ContextBuilder("ses_primary_1", "测试", max_context_tokens=5000)
        ctx = builder.build()
        assert ctx.max_context_tokens == 5000

    def test_custom_redactions(self):
        builder = ContextBuilder("ses_primary_1", "测试", redactions=["phone"])
        ctx = builder.build()
        assert "phone" in ctx.redactions


# ============================================================================
# Context validation
# ============================================================================

class TestContextValidation:
    """Context validation rules."""

    def test_validate_sha256_match(self, tmp_path):
        """A matching sha256 passes validation."""
        f = tmp_path / "auth.py"
        f.write_text("print('hello')", encoding="utf-8")
        import hashlib
        expected = hashlib.sha256(f.read_bytes()).hexdigest()

        builder = ContextBuilder("ses_primary_1", "探索文件", workspace=WorkspaceScope())
        builder.add_file_reference(str(f), sha256=expected)
        ctx = builder.build()
        assert ctx.references[0].sha256 == expected

    def test_validate_sha256_mismatch(self, tmp_path):
        """A mismatched sha256 is rejected."""
        f = tmp_path / "auth.py"
        f.write_text("print('hello')", encoding="utf-8")

        builder = ContextBuilder("ses_primary_1", "探索文件", workspace=WorkspaceScope())
        with pytest.raises(ReferenceValidationError, match="sha256 mismatch"):
            builder.add_file_reference(str(f), sha256="deadbeefdeadbeefdeadbeefdeadbeef")

    def test_validate_missing_file(self, tmp_path):
        """A reference to a missing file is rejected."""
        builder = ContextBuilder("ses_primary_1", "探索文件", workspace=WorkspaceScope())
        with pytest.raises(ReferenceValidationError, match="Cannot read"):
            builder.add_file_reference(str(tmp_path / "does_not_exist.py"), sha256="abc")

    def test_validate_empty_file_path(self):
        builder = ContextBuilder("ses_primary_1", "探索文件")
        with pytest.raises(ReferenceValidationError, match="must have a path"):
            builder.add_file_reference("")

    def test_context_token_limit(self):
        """Context exceeding the token limit is rejected."""
        builder = ContextBuilder(
            "ses_primary_1",
            "这是一个非常长的任务描述" * 500,  # ~4000 chars → ~1000 tokens
            max_context_tokens=100,
        )
        with pytest.raises(ContextValidationError, match="exceeds"):
            builder.build()

    def test_no_full_history_by_default(self):
        """Child context must not contain full Primary history."""
        builder = ContextBuilder("ses_primary_1", "探索认证模块")
        ctx = builder.build()
        # Only references explicitly added — no history auto-inclusion
        assert ctx.references == ()
        assert "history" not in ctx.task


# ============================================================================
# Minimal context factory
# ============================================================================

class TestMinimalContext:
    """create_minimal_context convenience factory."""

    def test_creates_empty_references(self):
        ctx = create_minimal_context("ses_primary_1", "探索代码")
        assert ctx.parent_session_id == "ses_primary_1"
        assert ctx.task == "探索代码"
        assert ctx.references == ()
        assert ctx.attachments == ()

    def test_custom_max_tokens(self):
        ctx = create_minimal_context("ses_primary_1", "测试", max_tokens=8000)
        assert ctx.max_context_tokens == 8000

    def test_default_redactions_include_secrets(self):
        ctx = create_minimal_context("ses_primary_1", "测试")
        assert "secret" in ctx.redactions
        assert "api_key" in ctx.redactions
        assert "authorization" in ctx.redactions


# ============================================================================
# ContextEnvelope protocol type
# ============================================================================

class TestContextEnvelopeType:
    """ContextEnvelope is a frozen dataclass with required fields."""

    def test_frozen(self):
        from dataclasses import FrozenInstanceError
        ctx = create_minimal_context("p1", "t")
        with pytest.raises(FrozenInstanceError):
            ctx.task = "modified"

    def test_redactions_are_safe_fields(self):
        """Redaction metadata is carried on the envelope."""
        ctx = create_minimal_context("p1", "t")
        assert isinstance(ctx.redactions, tuple)

    def test_max_context_tokens_is_positive(self):
        ctx = create_minimal_context("p1", "t")
        assert ctx.max_context_tokens > 0
