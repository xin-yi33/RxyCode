"""Fail CI when source or fixture files contain likely live credentials.

Only file, line, and rule names are reported. Matched credential text is never
printed, which keeps the scanner itself from copying a secret into CI logs.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


SKIP_DIRECTORIES = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "dist",
    "htmlcov",
    "node_modules",
    "venv",
}
TEXT_SUFFIXES = {
    ".env",
    ".html",
    ".ini",
    ".json",
    ".jsonl",
    ".log",
    ".md",
    ".mjs",
    ".py",
    ".toml",
    ".ts",
    ".tsx",
    ".txt",
    ".xml",
    ".yaml",
    ".yml",
}

SECRET_RULES = {
    "provider-token": re.compile(
        r"\b(?:sk-[A-Za-z0-9_-]{20,}|AIza[0-9A-Za-z_-]{30,}|"
        r"ghp_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,}|"
        r"AKIA[0-9A-Z]{16})\b"
    ),
    "credential-assignment": re.compile(
        r"(?i)\b(?:api[_-]?key|access[_-]?token|authorization|password|secret)"
        r"\s*[:=]\s*(?:['\"][A-Za-z0-9_./+=-]{20,}['\"]|"
        r"[A-Za-z0-9_+/=-]{20,}(?=\s*(?:#.*)?$))"
    ),
    "private-key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "bearer-token": re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/-]{20,}={0,2}"),
}
PLACEHOLDER_VALUE_MARKERS = (
    "<redacted>",
    "fake",
    "placeholder",
    "runtime-secret-value",
    "test-key",
    "test-secret",
    "your-key",
    "your-token",
)


def _is_text_candidate(path: Path) -> bool:
    return path.name.startswith(".env") or path.suffix.lower() in TEXT_SUFFIXES


def scan(root: Path) -> list[tuple[Path, int, str]]:
    """Return redacted findings as ``(path, line, rule)`` tuples."""
    root = root.resolve()
    findings: list[tuple[Path, int, str]] = []
    for path in root.rglob("*"):
        if not path.is_file() or not _is_text_candidate(path):
            continue
        try:
            relative = path.relative_to(root)
        except ValueError:
            continue
        if any(part in SKIP_DIRECTORIES for part in relative.parts):
            continue
        try:
            with path.open("r", encoding="utf-8") as handle:
                for line_number, line in enumerate(handle, start=1):
                    for rule_name, pattern in SECRET_RULES.items():
                        match = pattern.search(line)
                        if not match:
                            continue
                        matched_value = match.group(0).lower()
                        if any(marker in matched_value for marker in PLACEHOLDER_VALUE_MARKERS):
                            continue
                        findings.append((relative, line_number, rule_name))
                        break
        except (OSError, UnicodeDecodeError):
            continue
    return findings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", nargs="?", default=Path(__file__).parents[1])
    args = parser.parse_args(argv)

    findings = scan(Path(args.root))
    for path, line, rule in findings:
        print(f"secret-scan: {path}:{line}: {rule}", file=sys.stderr)
    if findings:
        print(
            f"secret-scan: blocked {len(findings)} potential credential(s)",
            file=sys.stderr,
        )
        return 1
    print("secret-scan: no credentials detected")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
