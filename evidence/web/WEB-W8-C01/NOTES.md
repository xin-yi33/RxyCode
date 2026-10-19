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

## Audit round 1 (gpt-6.1-sol, same Codex session 01a140a7) — VERDICT: PROBLEMS

Seven findings against `4771b01f`; all remediated:

1. **[P1] ApprovalRequest.call_id/arguments existed only in the dirty
   worktree** — `core/safety/approval.py` and
   `execution/tool_orchestrator.py` are committed with this fix so the
   committed approval chain is real, not worktree-only.
2. **[P1] ro-mounted config disclosed the raw key** — an ro bind stops
   modification, not reads: the worker's config.yaml (incl. any literal
   `api_key`) was readable under `RXYCODE_TURN_CONFIG_SRC`.
   `_prepare_child_data_dir` now sanitizes BEFORE the file is mounted
   (`_scrub_model_credentials` shared with the child-side merge, which
   re-scrubs idempotently); an unparseable source is dropped entirely.
3. **[P1] resume lacked a current-lease/cancel fence** —
   `resume_state` checked only the approval row. It now additionally
   requires `_lease_fenced` (right owner+epoch, `leased`/`running`
   status, unexpired lease): approve→claim→cancel refuses late
   execution; a foreign/stale claim gets nothing.
4. **[P1] journal lived in child-writable workspace** — a completed-
   then-wiped `.journal` read back as `not_started` and re-executed.
   The journal moved to parent-owned `state_root/{sandbox}-journal`,
   reachable only through new `journal_state/reserve/complete` ctl ops
   (`_ChannelJournal` child-side, same adapter semantics parent-side).
   The module test now literally deletes the side-effect file and
   proves the second resume still reuses, never re-runs.
5. **[P1] `self._tunnel` didn't exist** — the method was indented
   inside module-level `_gateway_head`; every successful
   CONNECT/forward/gateway path raised AttributeError. Dedented into
   `EgressProxy`; a real socketpair tunnel test now exercises it.
6. **[P2] `--overlay SRC DEST` is not valid bwrap** — the three-operand
   form `--overlay UPPER WORK DEST` is emitted now, with per-task
   upper/work dirs under `state_root/{sandbox}-ovl` (same fs as
   required; installs persist across the task's turns). The probe uses
   `--tmp-overlay`, the same kernel path.
7. **[P2] acceptance chains under-demonstrated** — module test now
   covers dependency-install + test-run legs in BOTH modes, a strict
   bash side-effect assert, boundary legs split into tool-layer
   (write denial ×3 tool classes), egress-layer (metadata/private/
   multicast/odd-port refusal incl. a real public pass) and a
   bwrap-confined read/connect leg that honestly skips where the
   kernel feature is absent; plus a real-child cancel-reap leg and a
   stale-claim resume fence test. Misleading "in-container" header
   claims corrected.

## Audit round 2 (gpt-6.1-sol, same session) — VERDICT: PROBLEMS

r1 fixes verified real (CONNECT echoed bytes, approval fields
committed). Seven new findings against `47ccfc91`; all remediated:

1. **[P1] journal recreated per claim** — `journal_dir` was derived
   from the fresh per-claim `sandbox_id`, so a reclaimed run saw an
   empty journal and re-executed the approved call. Now
   `_run_journal_dir(state_root, tenant, run_id)` — run-keyed, still
   parent-owned and outside every mount.
2. **[P1] teardown barrier fails open + child-forged proof** — the
   6 s marker wait proceeded silently on timeout, and `_emit` let the
   child mint `turn.paused`/`steer.accepted`/`approval.requested`
   itself. `_emit` now denies reserved namespaces (`turn.*`, `run.*`,
   `approval.*`, `worker.*`, `usage.attribution`, `steer.accepted`,
   `child.cancel`); on marker timeout `_pending_resume` probes the OLD
   sandbox's ctl socket — dead listener ⇒ reaped child ⇒ proceed;
   alive/unprobeable ⇒ `teardown_unproven` ⇒ the claim settles
   `recovery_required`, never a guess. `sandbox_id` rides the
   `approval.requested` payload for that probe.
3. **[P1] cancellation fencing holes** — `request_approval` treated
   `cancel_requested` as parkable (a kill landing just before the ask
   got overwritten into `waiting_approval`); `journal_reserve` granted
   with no lease check at all. The ask paths (`request_approval`,
   `pause_under_lock`, `prepare_pause`) now refuse `cancel_requested`
   inside the locked txn, and `journal_reserve` requires
   `_lease_fenced` + the (attempt,call,tool,args) pair matching this
   run's stored approval payload — `journal_complete` keeps recording
   post-lease-loss outcomes but refuses unbound pairs.
4. **[P1] config scrub missed non-model credentials** —
   `rag.embedding.api_key`, MCP-server `env` tokens and friends were
   mounted verbatim. `_scrub_credential_values` now walks the whole
   copied config: credential-named scalars → `"confined"`,
   `*_env`/`*_file` indirection resolvers deleted — while
   `max_tokens`-style budgets survive (word-boundary suffixes).
5. **[P2] overlay argv still invalid** — bwrap requires
   `--overlay-src` before every overlay op; both the `--tmp-overlay`
   probe and the persistent `--overlay UPPER WORK DEST` now emit it.
6. **[P2] error results recorded as success** — `journal_complete` is
   replay safety, not success: `_execute_approved_call` now returns
   `(ok, text)` by classifying the stored/returned output
   (`[error`/`[blocked:`/`[evidence failed:`/`[rejected`/`[cancelled:`/
   `[dry-run]` prefixes), `_resume_turn` settles failed on a stored
   error, and BOTH parent checks (pre-spawn skip and post-spawn
   settle) classify the stored result — the "not-found tool becomes
   succeeded" counterexample now settles failed and stays failed on
   re-resume.
7. **[P2] tests overstated two chains** — the dependency leg now runs
   a REAL `pip install --no-index` of a locally built wheel plus an
   import-resolution check (not a marker dir); the cancel test asserts
   the grandchild dies too — `_wait_child` now sweeps descendants via
   psutil wherever the pid-namespace guarantee doesn't apply.
