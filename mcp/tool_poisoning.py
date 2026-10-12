"""MCP tool-description poisoning scan (2026-10-12).

An MCP server's ``tools/list`` description is untrusted input: it lands verbatim
in the model's system prompt, so a hostile or compromised server can hide
instructions in it ("<IMPORTANT>ignore prior rules…", <system> tags, secret
exfiltration).  Scanning cannot prove a description is safe; it exists to catch
the known tool-poisoning patterns and to *flag* the tool rather than silently
registering it.  Flagged tools still register (fail-open for usability) but
their description is annotated so the model sees the warning too.
"""

from __future__ import annotations

import re


_POISON_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"<\s*important\s*>", re.IGNORECASE), "embedded <IMPORTANT> instruction block"),
    (re.compile(r"<\s*/?\s*system\s*>", re.IGNORECASE), "embedded <system> tag"),
    (re.compile(r"ignore\s+(?:all\s+|any\s+)?(?:previous|prior|earlier)\s+(?:instructions?|rules?|prompts?)", re.IGNORECASE), "'ignore previous instructions' style override"),
    (re.compile(r"<\s*/?\s*(?:instructions?|hidden|secret|override)\b", re.IGNORECASE), "embedded instruction/secret tag"),
    (re.compile(r"(?:ssh|id_rsa|\.env|password|api[_-]?key|token|secret|credential)[^\n]{0,40}(?:curl|wget|https?://|upload|exfiltrat|send|post)", re.IGNORECASE), "secret exfiltration hint"),
    (re.compile(r"(?:cat|read|open|load|read_file)[^\n]{0,30}(?:~/\.ssh|\.aws|/etc/passwd|id_rsa|\.env|credentials)", re.IGNORECASE), "sensitive-file read hint"),
]


def scan_tool_description(text: str) -> list[str]:
    """Return poisoning findings for one description; empty means no hit."""
    body = text or ""
    findings: list[str] = []
    for pattern, label in _POISON_PATTERNS:
        if pattern.search(body):
            findings.append(label)
    return findings


def annotate_poisoned_description(description: str, findings: list[str]) -> str:
    """Prefix a visible warning so the model knows the text is suspect."""
    if not findings:
        return description
    joined = "; ".join(findings)
    return f"[⚠ description flagged: {joined}]\n{description}"
