---
name: harness-analyze
description: Map GUI actions to backend APIs and existing CLIs.
subtask: true
---

# Analyze

Upstream SOP: CLI-Anything Phase 1: Codebase Analysis (Apache-2.0 vendor at docs/agents/harness/HARNESS.md).

Map GUI actions to backend APIs and existing CLIs.

Rules:
- Do not reimplement the real software.
- Fail with install guidance when the backend is missing.
- JSON output is mandatory for agent consumption.
- Generated packages install through B14 isolated venv (cli/install + cli/launch).
