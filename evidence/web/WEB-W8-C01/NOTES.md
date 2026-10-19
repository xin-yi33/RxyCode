# WEB-W8-C01 — cloud Full = sandboxed Full-Auto; real confined turns

Scope (user directive): decouple Full from sandbox choice; complete the
task-private development environment; keep ToolOrchestrator as the single
execution entry; wire non-Full approval to the real running call; add the
control-plane credential and network boundaries outside the sandbox.

## What changed

- `_execution_gate()` keeps tenant/target checks and now maps `full` →
  `full_auto` for tenant-owned `cloud:` targets. `permission_mode =
  full_auto`, `execution_target = the tenant's cloud sandbox`,
  `isolation_required = true` — Full is an approval semantic, never an
  isolation level. Local CLI Full semantics and
  `core/sandbox/policy.py` are untouched.
- Worker drain split into two trust domains: the parent keeps DB creds,
  lease, ctl socket, filtered egress proxy, lifecycle and metering; the
  confined child runs `Session.prompt()`/`AgentV2`/`ToolOrchestrator`
  inside userns+bwrap with a private mount namespace and `--unshare-net`.
- Task-private dev env: `HOME`, XDG/pip/npm/uv caches, private `/tmp`,
  tmpfs-overlay system roots (`/usr` etc.) for apt/dpkg — all under the
  run's workspace; `safety.allowed_write_paths` merges the sandbox-real
  domain; nested `os_sandbox` forced off; `safety.enabled` forced on.
- Control-plane credentials never enter the sandbox: no platform DSN, no
  Docker socket, no model key (`RXYCODE_API_KEY` out of the env passlist;
  copied config scrubs `api_key*` and rewrites the used model's
  `base_url` to the loopback gateway; the PARENT injects real auth).
  Events/run-reads/commands/approvals travel a per-run parent-owned
  UNIX ctl socket (`ctl.py`); the child holds `TurnChannel` only.
- Network boundary at exec-env level: `--unshare-net` unconditionally,
  `lo` brought up in-child (`netrelay.py`), `127.0.0.1:<egress_port>`
  relayed to the parent's UNIX socket. `egress.py` refuses private,
  link-local, loopback, multicast, reserved, metadata and non-80/443
  ports after PARENT-side DNS (rebinding can't slip a resolved private
  answer past the check); explicit allowlist for in-cluster endpoints.
  All proxy-aware children (bash, pip, npm, git, MCP, Playwright)
  inherit `HTTP_PROXY`/`HTTPS_PROXY`/`ALL_PROXY`/`NO_PROXY`.
- Durable approval bound to the real call: `_CtlApproval` asks through
  the channel with raw `arguments`, `source_call_id`, scope, command,
  workdir; the PARENT derives the journal-keyed `call_[0-9a-f]{32}` id
  and mints `att_[0-9a-f]{32}` (both journal contracts), stores
  `source_call_id` in the event payload for audit. `_RunPaused`
  (BaseException) unwinds the turn; the run sits `waiting_approval`
  with its lease released — not claimable, not no-progress.
- Resume executes THE stored call once: a fresh confined child runs
  `_resume_turn` → channel `resume_state` → journal-checked
  `_execute_approved_call` through the same ToolOrchestrator under a
  grant broker (`safety.enabled=true`, blacklist and write-path gate
  intact). `completed` → reuse, `unknown`/`uncertain` → refuse and
  settle `recovery_required`. A parent pre-check skips the spawn
  entirely when the journal already knows the outcome.
- Stale-decision guard: `decide_approval` requires
  `run.status == waiting_approval` — a late approval after cancel or
  terminalization raises `ApprovalStale`, never resurrects the run.
- Process-tree cleanup: `--die-with-parent` + `--unshare-pid` inside
  bwrap; parent kills the supervisor process on cancel and destroys the
  sandbox record in `finally`.

## Real findings fixed while testing (not hypothetical)

1. `remote_call_key`/`validate_attempt_id` enforce
   `call_[0-9a-f]{32}`/`att_[0-9a-f]{32}` — the orchestrator's raw
   call ids (uuid hex, provider strings) and the parent's 12-char
   attempt ids both failed closed → every resume would have crashed.
   Parent now derives/mints journal-valid ids.
2. `safety.enabled` defaults False — a copied config without the key
   would have run the whole turn with the gate bypassed
   (`safety_disabled`), including the resume path. `_merge_turn_config`
   and `_execute_approved_call` now force `enabled=true`.
3. `decide_approval` resurrected cancelled runs (missing state guard).
4. `_ip_blocked` passed multicast (`224.0.0.1` is `is_global`) —
   multicast/reserved/unspecified now refuse explicitly.
5. `_CtlApproval` sent the raw call id as the durable key — a child
   could mint colliding keys; derivation moved to the trusted parent.
