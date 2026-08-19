---
name: harness-plan-tests
description: Write TEST.md inventory before any test code.
subtask: true
---

# Plan Tests

Upstream SOP: CLI-Anything Phase 4: Test Planning (Apache-2.0 vendor at docs/agents/harness/HARNESS.md).

Write TEST.md inventory before any test code.

Rules:
- Do not reimplement the real software.
- Fail with install guidance when the backend is missing.
- JSON output is mandatory for agent consumption.
- Generated packages install through B14 isolated venv (cli/install + cli/launch).
