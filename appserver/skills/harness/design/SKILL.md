---
name: harness-design
description: Choose REPL/subcommand model, state, and --json output.
subtask: true
---

# Design

Upstream SOP: CLI-Anything Phase 2: CLI Architecture Design (Apache-2.0 vendor at docs/agents/harness/HARNESS.md).

Choose REPL/subcommand model, state, and --json output.

Rules:
- Do not reimplement the real software.
- Fail with install guidance when the backend is missing.
- JSON output is mandatory for agent consumption.
- Generated packages install through B14 isolated venv (cli/install + cli/launch).
