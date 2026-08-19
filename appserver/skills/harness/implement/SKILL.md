---
name: harness-implement
description: Data layer, backend wrapper via shutil.which + subprocess, REPL skin.
subtask: true
---

# Implement

Upstream SOP: CLI-Anything Phase 3: Implementation (Apache-2.0 vendor at docs/agents/harness/HARNESS.md).

Data layer, backend wrapper via shutil.which + subprocess, REPL skin.

Rules:
- Do not reimplement the real software.
- Fail with install guidance when the backend is missing.
- JSON output is mandatory for agent consumption.
- Generated packages install through B14 isolated venv (cli/install + cli/launch).
