---
name: harness-publish
description: PEP 420 namespace package under cli_anything.
subtask: true
---

# Publish

Upstream SOP: CLI-Anything Phase 7: PyPI Publishing (Apache-2.0 vendor at docs/agents/harness/HARNESS.md).

PEP 420 namespace package under cli_anything.

Rules:
- Do not reimplement the real software.
- Fail with install guidance when the backend is missing.
- JSON output is mandatory for agent consumption.
- Generated packages install through B14 isolated venv (cli/install + cli/launch).
