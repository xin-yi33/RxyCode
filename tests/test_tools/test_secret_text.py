"""Secret redaction candidate detection and parser regression coverage."""
from __future__ import annotations

import pytest

from RxyCode.RxyCode1_1_0.tools import secret_text


def test_redact_secrets_returns_early_without_candidates(monkeypatch):
    def fail_if_called(_text: str) -> str:
        raise AssertionError("a marker-free text must not enter a redaction parser")

    monkeypatch.setattr(secret_text, "_redact_bearer", fail_if_called)
    monkeypatch.setattr(secret_text, "_redact_assignments", fail_if_called)
    text = "-" * 90000

    assert secret_text.redact_secrets(text) is text


@pytest.mark.parametrize(
    ("text", "secret"),
    (
        ("authorization=auth-secret", "auth-secret"),
        ("api_key=plain-secret", "plain-secret"),
        ("api-key=hyphen-secret", "hyphen-secret"),
        ("apikey=compact-secret", "compact-secret"),
        ("PaSsWoRd=case-secret", "case-secret"),
        ("passwd=passwd-secret", "passwd-secret"),
        ("secret=secret-value", "secret-value"),
        ("token=\n\"multiline-secret\"", "multiline-secret"),
        ('\"secret\": \"quoted-secret\"', "quoted-secret"),
        ('{"password":"Bearer DEMO123\\\"escaped-secret"}', "escaped-secret"),
        ("Authorization: Bearer bearer-secret", "bearer-secret"),
    ),
    ids=(
        "authorization",
        "api_key",
        "api_key_hyphen",
        "apikey",
        "password_case",
        "passwd",
        "secret",
        "token_multiline",
        "quoted_key",
        "escaped_payload",
        "bearer",
    ),
)
def test_redact_secrets_still_redacts_all_supported_candidate_forms(
    text: str, secret: str
):
    redacted = secret_text.redact_secrets(text)

    assert secret not in redacted
    assert "***" in redacted
