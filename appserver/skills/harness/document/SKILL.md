---
name: harness-document
description: Append TEST.md results and generate SKILL.md.
subtask: true
---

# Document

Upstream SOP: CLI-Anything Phase 6 + 6.5 (Apache-2.0 vendor at docs/agents/harness/HARNESS.md).

Append TEST.md results and generate SKILL.md.

Rules:
- Do not reimplement the real software.
- Fail with install guidance when the backend is missing.
- JSON output is mandatory for agent consumption.
- Generated packages install through B14 isolated venv (cli/install + cli/launch).
