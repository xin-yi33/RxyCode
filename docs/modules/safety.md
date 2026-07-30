# core/safety/ - Safety Gate (阶段二)

## What Is This Module?
The safety防线 for every tool call: three-tier risk classification, write-path
whitelist, dry-run simulation, user approval (CLI TUI + API SSE) and an
append-only audit log. Adapted from OpenHands (MIT) `openhands/security/` —
the SecurityRisk level model and confirmation-mode flow; design ported, no
code vendored.

## Key Files
| File | Purpose |
|------|---------|
| policy.py | RiskLevel (READ/WRITE/DANGER), static defaults, argument-aware `classify_tool_risk`, write-path and dry-run policy |
| approval.py | ApprovalRequest/Decision, ApprovalBroker ABC, TuiApproval (CLI), SseApproval (API), global singleton |
| audit.py | AuditLogger -> ~/.rxycode/logs/audit.jsonl, sensitive-key redaction |

## Core Code: policy.py

**RiskLevel (OpenHands SecurityRisk mapping):**
- READ (LOW) — inspection only, no side effects (read/view/grep/glob/ls/webfetch/...)
- WRITE (MEDIUM) — reversible side effects (write/edit/patch/bash/format/...)
- DANGER (HIGH) — potentially destructive (installer/git; bash escalated dynamically)

**Bash dynamic escalation:** `classify_bash_command(cmd)` matches against
`DANGEROUS_COMMAND_PATTERNS` (plain list, easy to extend): `rm -rf /`,
`mkfs`, `dd of=/dev/...`, `curl|sh`, `wget|sh`, `git push --force`,
`chmod -R 777 /`, `> /dev/sda`, `shutdown`/`reboot`, `reg delete`, `format C:`.

**Argument-aware classification:** `classify_tool_risk(name, args)` is the
entry point used by the orchestrator. Stateful composite tools fail closed:
`memory search/list`, `task list/get`, and `workflow status/wait` are READ;
memory/task mutations and workflow cancellation are WRITE; `workflow run`
and unknown workflow operations are DANGER. Missing or unknown memory/task
operations retain their conservative WRITE defaults.

**Write-path whitelist:** `is_write_allowed(path, config)` resolves the
target and requires it to live under cwd, `~/.rxycode/output/` (or
`RXYCODE_OUTPUT_DIR`), or `safety.allowed_write_paths`. `Path.relative_to`
prefix check blocks `../` escapes and sibling-prefix confusion. The tool
orchestrator applies this check to download `save_path` values as well as
normal file path arguments.

**Dry-run:** `safety.dry_run: true` in config or `RXYCODE_DRY_RUN=1` makes
WRITE/DANGER tools return `[dry-run] 未实际执行: <summary>` without running.

## Core Code: approval.py

**Flow (OpenHands confirmation mode):**
1. Gate builds an ApprovalRequest (tool, truncated args summary, risk, id)
2. Broker publishes it and waits for a decision
3. `always_allow_level` is cached per session — later calls at the same
   risk level auto-pass

**TuiApproval (CLI):** prints via the TUI channel, reads y/n/a from stdin
in a worker thread (`asyncio.to_thread`) so the event loop is never blocked.
EOF defaults to REJECTED (fail-closed).

**SseApproval (API):** pushes an `approval_request` event onto the SSE
queue of `/chat/stream`; `POST /approve {approval_id, decision}` resolves
the pending `asyncio.Event`. Timeout (`safety.approval_timeout`, default
120s) defaults to REJECTED. Unknown ids -> 404; no broker -> 409.

**Broker selection:** `main.py` (CLI) installs TuiApproval at startup;
`api_server.py` startup installs SseApproval. `get_approval_broker()` is the
global accessor. No broker + WRITE/DANGER tool => rejected (fail-closed).

## Core Code: audit.py

Every gated call appends one JSONL record to `~/.rxycode/logs/audit.jsonl`:
`ts, run_id (log/logger.py RUN_ID), tool, risk, args, approval, result`.
- `approval` ∈ auto / approved / rejected / always / dry_run
- args sanitized recursively: keys matching api_key/password/token/secret/
  authorization are replaced with `***`; credentials embedded in ordinary
  command/query strings (Bearer, api_key/token/password assignments, and
  `sk-...` keys) are redacted before values are truncated to 200 chars
- Thread-safe (single lock); write failures are swallowed (best-effort)

## Gate Integration (execution/tool_orchestrator.py)

`ToolOrchestrator.execute_tool(name, args, config)` is the single choke
point, called by `AgentV2._execute_tool`:

1. classify by tool name and arguments (including bash and composite operations)
2. write-path whitelist (WRITE/DANGER tools with a path arg)
3. dry-run simulation (WRITE/DANGER only)
4. approval (READ exempt; `safety.auto_approve: ["write"]` exempts a level)
5. execute + audit

## Config (config/settings.py `_default_config`)

```yaml
safety:
  enabled: true
  auto_approve: []          # level names: "read" | "write" | "danger"
  allowed_write_paths: []   # extra writable roots
  dry_run: false
  approval_timeout: 120     # seconds; SSE approval timeout
```

## Frontend (frontend/)

- `useApi` handles the `approval_request` SSE event, exposes
  `pendingApproval` + `respondApproval(decision)` (POST /approve)
- `components/ApprovalDialog.tsx` renders tool/risk/args with three
  choices: Approve / Reject / Always-allow-level (keys a/r/l, arrows+Enter)
- While pending, the InputBox is replaced by the dialog and the thinking
  panel shows "等待用户确认"

## Dependencies
- config/settings.py (data dir, output dir, safety config)
- log/logger.py (RUN_ID)
- utils/tui.py (CLI prompt channel)
- api_server.py (/approve endpoint, SSE queue sink)
