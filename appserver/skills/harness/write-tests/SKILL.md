---
name: harness-write-tests
description: Unit + true-backend E2E. No graceful skip if software missing.
subtask: true
---

# Write Tests

Upstream SOP: CLI-Anything Phase 5: Test Implementation (Apache-2.0 vendor at docs/agents/harness/HARNESS.md).

Unit + true-backend E2E. No graceful skip if software missing.

Rules:
- Do not reimplement the real software.
- Fail with install guidance when the backend is missing.
- JSON output is mandatory for agent consumption.
- Generated packages install through B14 isolated venv (cli/install + cli/launch).
