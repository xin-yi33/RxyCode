---
name: harness-refine
description: Iterate a generated harness against HARNESS.md failures.
subtask: true
---

# refine

Upstream SOP: CLI-Anything /refine (Apache-2.0 vendor at docs/agents/harness/HARNESS.md).

Iterate a generated harness against HARNESS.md failures.

Rules:
- Do not reimplement the real software.
- Fail with install guidance when the backend is missing.
- JSON output is mandatory for agent consumption.
- Generated packages install through B14 isolated venv (cli/install + cli/launch).
