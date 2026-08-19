---
name: harness-validate
description: Check vendor HARNESS.md, license, and required skill templates.
subtask: true
---

# validate

Upstream SOP: CLI-Anything /validate (Apache-2.0 vendor at docs/agents/harness/HARNESS.md).

Check vendor HARNESS.md, license, and required skill templates.

Rules:
- Do not reimplement the real software.
- Fail with install guidance when the backend is missing.
- JSON output is mandatory for agent consumption.
- Generated packages install through B14 isolated venv (cli/install + cli/launch).
