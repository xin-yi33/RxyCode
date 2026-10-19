# WEB-W7-C05 self-audit / manual review

Audited commit: `<filled after the audited fix commit>`
Final verdict: `<filled by the Codex audit>` (session
`01a140a7-2cc1-7f61-bdab-2af627f08e80`, `gpt-6.1-sol` `high`).

## Audit history

| round | verdict | findings fixed |
|---|---|---|
| r1 | PROBLEMS | 8: no deployed queue consumer (idle stdio worker); api bypassed `serve()` mode guard; upgrade/rollback ran stale `repo-src`; CI lint failed on 3 committed files; rate limiting was text-only; validator accepted wildcard port publication; `compose up` outside try/finally skipped cleanup; NOTES/.gitignore scope disagreement |
| r2 | PROBLEMS | 7: persisted `target_id` ignored (every target ran on local AgentV2); watchdog transient DB error killed the monitor while the turn ran; drain journaled only stringified `notify.event/*` (web reducer got nothing); failed/cancelled turns recorded zero tokens; usage-ledger write failure didn't block `succeeded`; upgrade overlay left deleted files in `repo-src`; secret pattern missed `API_KEY` literals |
| r3 | PROBLEMS | 5: `local:*` acceptance still let shared-worker Full runs execute on the worker host (no tenant sandbox bound); lease-watchdog store calls had no deadline (could stall past TTL while the turn ran); tool/stream mappings lacked the production producer (no `ProtocolTui`/`bind_prompt_context` in the drain path); the projection cap could drop terminal `assistant.final`; the two new test files failed `ruff format --check` |

## Scope rulings committed to the nested plan

1. r1 remediation (nested `c7621e7`): `rxycode_worker/drain.py`+`__main__.py`
   (real queue consumer), `rxycode_server/main.py` `rate_limit_rpm` +
   `serve()` boot path, `api/ratelimit.py` middleware, `.gitignore`
   `!docs/deploy/` negation, three lint fixes, port validator + CI port
   invariant, runbook versioned reseed sequence.
2. r2 remediation (same files): drain `local:*` target gate +
   `_LeaseRenewalLost` deadline semantics + `_projection_rows` reducer
   vocabulary + metered-usage-on-every-terminal + ledger-failure→`failed`;
   runbook exact-reseed (volume emptied before the tar stream); validator +
   CI secret pattern extended to `api_key`/`credential`.
3. r3 remediation: `rxycode_runner/sandbox/userns.py` (NEW — the per-run
   kernel boundary + `UsernsSandboxProvider` implementing the
   `SandboxProvider` contract, `userns_available()` real probe,
   `IsolationUnavailable` fail-closed); `drain.py` restructured into
   claim/watchdog parent + `RXYCODE_TURN_RUN_ID` confined child carrying
   `install_tui_context_hook`/`ProtocolTui`/`bind_prompt_context` with a
   persisted-identity `RunContext`; `compose.yaml` worker `security_opt:
   seccomp=unconfined` (scoped to worker, no caps/privileged/sock) +
   bubblewrap install + `RXYCODE_WORKER_EXECUTION=cloud-only`; unit-test
   validator scoping `security_opt` to worker-only plus `cap_add` refusal;
   module-test executed legs moved to tenant-bound `cloud:*` targets with
   `auto_edit`, refusal legs covering `local:*` + `sandbox:*`.

## What the remediation actually does (verified by hand)

- Drain end-to-end on host against dev PG (55432): create_run -> claim ->
  `worker.lease` event -> `event/agent_started` journaled -> real
  `Session.prompt` turn -> `notify.event/*` -> `event/agent_done` ->
  `usage.updated` -> `commit_terminal` (`succeeded` with the configured
  model; `failed` honestly without provider creds). Observed live.
- Same drain inside a real compose worker container (debug stack w7c05dbg):
  claim -> `worker.lease` -> `event/agent_started` -> provider call fails at
  the real network boundary -> `run.error` -> `failed`. Three real bugs were
  caught and fixed during this verification: (a) `AgentV2()` needs a
  configured model — worker now accepts `RXYCODE_LLM_BASE_URL`/`_MODEL`/
  `RXYCODE_API_KEY` and writes a real model entry when set; (b) the LLM
  client enforces https-with-credential except loopback — test uses
  `http://127.0.0.1:9/v1` (dead port => honest connection failure, no stub
  LLM); (c) a shell `${VAR}` inside the worker's `sh -c` script is
  interpolated by COMPOSE from the host env at `up` time (the test's
  RXYCODE_DATA_DIR temp path was baked into the container script) — the
  model-config write moved inside a python heredoc that reads the real
  container env.
- `serve(mode="local", host="0.0.0.0")` raises RuntimeError — the deployed
  api can never weaken mode; verified by the negative test against the real
  module, not a copy.
- Rate limiter driven at ASGI level: 2 allowed, 3rd -> 429 + Retry-After.
- Port validator: `8000:8000` (no host_ip) refused; `127.0.0.1:...` accepted;
  same check duplicated in the CI invariants lane.
- Module test: the run is claimed and terminated by the worker INSIDE the
  container (`lease_owner = drain-<container>-<pid>`), not the test process;
  stale-lease reclaim uses a planted expired-lease row while the worker is
  SIGKILLed (deterministic, no race); worker recreation + third run prove
  restart recovery; a `sandbox:`-targeted run commits `failed` with an
  honest `run.error` and NO `event/agent_started`.
- r2 host re-verification (dev PG 55432): a `sandbox:nope` run went
  `worker.lease` -> `usage.updated` -> `run.error` -> `failed` with no
  agent spawn; a `local:` run went `worker.lease` -> `event/agent_started`
  -> `assistant.delta`/`assistant.final` projections -> `event/agent_done`
  -> `usage.updated` -> `succeeded` (real answer "pong", 9165+1503 real
  tokens). Both legs observed live.
- r2 unit tests: `_lease_watchdog` driven against a monkeypatched
  `renew_lease` — one blip retries, an outage past TTL cancels the turn and
  raises `_LeaseRenewalLost`, `LeaseRejected`/`cancel_requested` are the
  intentional exits. `_projection_rows` asserted directly: final/delta/
  tool/needs_input/todo/plan all map to reducer vocabulary.
- r3 unit tests: `_execution_gate` matrix asserts the public rule in code
  (cloud-only accepts only tenant-bound `cloud:*` + non-full; refuses
  `local:*`/`sandbox:*`/cross-tenant/`full*`; `sandboxed-local` accepts
  `local:*` still confined); `build_sandbox_argv` shape asserts
  userns/pidns/clearenv/die-with-parent/workspace-only-writable; a
  cap-exhausted `_RunEmit` still persists `assistant.final`; the validator
  refuses `cap_add` everywhere and `security_opt` on any non-worker service.
- The sandbox boundary was probed live in `python:3.12-slim`:
  `bwrap --unshare-user --unshare-pid` works under `seccomp=unconfined`
  (the default profile forbids `unshare`/`mount` — the compose comment and
  validator document the scoping); a confined `sleep` tree dies with its
  killed supervisor (`--die-with-parent` verified, `CHILD_DEAD`).
- r3-fix live verification in a debug compose stack (real PG + worker):
  a `cloud:{tenant}:w1` run went `worker.lease -> event/agent_started ->
  notify.event/recovery_attempt x6 -> run.error (60s timeout at the dead
  loopback LLM endpoint) -> failed`; `/proc` showed zero leftover turn
  processes after the kill. Three real construction bugs were found by
  this live run and fixed: the probe bound only `/usr` (missing the
  `/lib*` loader), `_DEFAULT_RO_BINDS` lacked `/usr/local` (the slim
  interpreter prefix), and a caller's `ro_binds` replaced the system
  mounts (now unioned — a caller can never drop the interpreter mount).

## Known limitations (accepted, documented)

- Rate-limit window is per-process memory — single-replica demo only.
- Approval-gated runs (profiles outside the mode map -> `confirm_all`
  default) hit "no approval broker" inside the confined turn — refused
  honestly, not blocked forever. The approval-resume service is not part of
  this stack.
- `child.cancel` persisted commands get "no manager" — the drain is
  single-agent; undeliverable commands are logged, not dropped silently.
- On the shipped `cloud-only` mode, `local:*`/`sandbox:*`/empty targets are
  REFUSED — only tenant-bound `cloud:{tenant}:{workspace}` runs execute,
  always inside the userns boundary. Scheduled runs (`target_id=""`) are
  refused the same way until a placement is declared. `sandboxed-local`
  accepts `local:*` for dev drains — still confined.
- The turn's network namespace is inherited (the turn must reach Postgres +
  the LLM endpoint); fs/process/env are confined, egress is the
  `sandbox.egress` seam — not yet wired; documented in the runbook.
- The confined turn holds `RXYCODE_WEB_DATABASE_URL` for journal/command
  delivery — run code could in principle write run-events with it; residual
  accepted for this stack, an out-of-process journal broker is future work.
- Workspaces live under the `worker-data` volume (`/work/runs`) — survive
  container restart, die with `down -v` (documented).
- Browser E2E BLOCKED: no Playwright dep in apps/web; never claimed.

## r4 remediation self-check

- Deadline anchored at claim; every store call bounded inside remaining
  TTL; expiry cancels the child (bwrap kill -> tree reaped). Leg (e)
  reproduces the audit probe: failed renewal + 4.2s status stall on a 5s
  lease cancels at ~5s.
- No parent write enters the workspace except mkdir + bounded unlinks
  (guarded against a planted .data symlink). config.yaml travels
  parent-owned ro-bind -> child-side copy into <workdir>/.data.
- Result file: unlinked pre-spawn, carries run_id, succeeded requires
  rc==0. Stale/fake reports degrade to failed honestly.
- usage.delta heartbeats are cumulative; parent takes max(result, delta,
  agent_done) — killed paid turns keep their spend. Ledger failure still
  forces failed.
- bwrap mounts private /tmp before the workspace bind; the documented
  default workspaces root works unmodified.

## r5 remediation self-check

- Renewal deadline extends from request-START (conservative vs the store's
  in-transaction clock); probe timeouts are capped at remaining-0.05 — a
  stalling renew can no longer push past expiry.
- __RXY_USAGE__ stderr streaming: per-response cumulative metering reaches
  the parent's pipe before any kill; verified parse logic on host.
- usage.delta rows carry attempt=epoch; _usage_deltas_total sums the last
  cumulative value per attempt — retry keeps prior spend (unit: 105).
- agent_done merges via max — never shrinks a larger measured count.
- bwrap mounts --dev/--tmpfs before ALL binds — .sandboxes conf bind under
  a /tmp workspaces root stays visible (unit asserts ordering).

## r7 remediation self-check

- RunJournal stamps `attempt` (=RXYCODE_TURN_EPOCH, the lease epoch) into
  every journaled payload — agent_done snapshots are attributable to the
  attempt that produced them; non-web callers see one extra payload key.
- `_agent_done_by_attempt` buckets `event/agent_done` by attempt; the
  ledger now computes max(deltas, dones, streamed, result) per attempt
  then SUMS across epochs — A's done(100) + B's heartbeat(5) = 105.
- `_flush_streamed_usage` persists pipe-delivered spend as a final
  attempt-tagged `usage.delta` BEFORE the lost-lease early return —
  journaling not terminal state, so retries recover the spend and lease
  ownership stays untouched. Idempotent: no row when the cumulative
  heartbeat already covers it.
- Unit legs green 13/13 (incl. done-grouping + flush-once); module stack
  test re-running.

## r8 remediation self-check

- `_lease_epochs`/`_epoch_at_seq` attribute untagged `usage.delta` and
  `event/agent_done` rows to the lease epoch whose claim seq precedes the
  row — legacy data can no longer form a phantom `attempt=""` bucket that
  double-charges a tagged sibling (A=100 tagged + untagged done 100 + B=5
  → 105, covered by a unit leg).
- `_flush_streamed_usage` returns durable/not; the caller retries 3x then
  `_spool_streamed_usage` writes `{run}.{epoch}.usage.json` under
  `.sandboxes/.usage-spool/` (parent-owned). `drain_once` calls
  `_replay_usage_spool` every pass — files delete only on a journaled row.
- green.txt corrected: 14 non-contract legs; contract leg also passed when
  run with the stack up (13/13 earlier run).

## r9 remediation self-check

- All finalize-region `to_thread` DB calls bounded by `wait_for` with
  `_LEASE_IO_BUDGET` — flush retries, spool write, delta/done reads,
  ledger write, cancel confirm, terminal commit, spool replay.
- `_replay_usage_spool` now recomputes per-attempt totals after a
  journaled delta and calls `usage.service.adjust_terminal_usage` — a
  committed 5-token ledger rises to 105 when the crashed attempt's spool
  lands late. The file stays until reconcile succeeds.
- Untagged `agent_done` → earliest claimed epoch lacking a done row;
  untagged `usage.delta` → claimed epoch with the largest bucket <= its
  value. The r9 interleave (tagged delta 100 in e1 + claim e2 + delayed
  untagged done 100) records 105.

## r10 remediation self-check

- `_agent_done_by_attempt` now exact-matches an untagged `agent_done`
  against metered `usage.delta` buckets BEFORE the earliest-open-epoch
  fallback: e1 spends 5 and dies silently, e2 spends 100 and emits the
  only (untagged) done — it binds to e2, total 105. Without the match it
  would hit e1 and charge 200. Unit leg:
  `test_w7_c05_untagged_done_exact_metered_match`.
- `_replay_usage_spool` no longer deletes a file just because its delta
  was journaled: a `journaled` flag inside the payload marks that state;
  the file stays until a UsageRecord exists to reconcile. Terminal run +
  no ledger even after replay → dead-lettered (renamed .dead, never
  silently re-journaled, still logged).
- `adjust_terminal_usage` locks every UsageRecord for the run, computes
  `needed = recovered_total - sum(other rows)`, and assigns it to the
  largest row — reconciling a (model,price)-split ledger raises the
  aggregate to exactly the recovered total instead of double-counting
  one row at the full value. PG-backed leg seeds real 60+60 / 5 / none
  shapes on 127.0.0.1:55432.
- Non-stack legs 18/18 green; module stack test re-running.

## r11 remediation self-check

- `_agent_done_by_attempt` binds untagged dones by minimum surplus among
  feasible (metered <= value) open epochs — lagging heartbeats can no
  longer push e2's own 100-token completion onto a dead 5-token epoch 1
  (190 -> 105). Exact match is the surplus-0 special case; r9 and r10
  counterexamples still resolve correctly (verified by their legs).
- `_replay_usage_spool` re-runs `adjust_terminal_usage` after observing a
  terminal status before dead-lettering — ledger-then-status commit order
  guarantees any in-flight ledger is visible by then; the file survives
  the read-gap race.
- The `journaled` flag is written via tmp+replace (atomic), closing the
  truncate-on-crash malformed-file window.
- Non-stack legs 19/19 green; module stack test re-running.

## r12 remediation self-check

- Finalize captures `record_terminal_usage`'s return: an existing shorter
  ledger (prior attempt committed 100, crashed before terminal; retry
  recomputes 105) now triggers `adjust_terminal_usage` — the insert-once
  W2-C07 contract is untouched, reconciliation is a separate explicit
  step. PG-backed leg proves 100 -> 105.
- Post-terminal re-adjust failure now `continue`s — a transient error
  keeps the spool instead of dead-lettering on an unknown state.
- `_agent_done_by_attempt` returns `(buckets, ambiguities)`; ambiguous
  untagged done rows (multiple feasible epochs) journal a deduped
  `usage.attribution` event with candidates + chosen + source seq. The
  heuristic still binds min-surplus, but the record is honest about the
  uncertainty instead of silently emitting an inferred confirmed total.
- Non-stack legs 21/21 green; module stack test re-running.

## r13 remediation self-check

- Cancel-at-claim: `_has_prior_attempt_activity` gates
  `effects_known`; prior spend is upserted onto the ledger before
  confirm_cancel, and ambiguous rows journal usage.attribution.
- `upsert_terminal_usage` (new service fn) gives the drain run-level
  aggregate semantics — the cross-model second-row inflation can't
  happen; `record_terminal_usage` keeps its pinned insert-once contract.
- Lost-lease exit calls `_reconcile_lost_lease_ledger` — a committed
  short ledger lifts to the recomputed total before handoff.
- Attribution emit failures propagate inside replay (file retained,
  retried, deduped by attribution_seq) and are embedded in the ledger
  event payload for atomicity.
- Non-stack legs 23/23 green; module stack test re-running.

## r14 remediation self-check

- `_reconcile_lost_lease_ledger` rereads deltas fresh + merges max; a
  B-committed-5/A-flushed-100 interleave now reconciles to 105.
- `lost_lease` exit parks `_ensure_pending_reconcile_spool` when the
  reconcile is missing-or-failed — a retried short ledger can no longer
  slip past; the pending file replays until the ledger exists.
- Cancel fast-path upsert failure parks the same pending spool before
  `confirm_cancel` — recovery_required never lands with unrecoverable
  prior spend.
- Attribution emit failure in finalize also parks a pending spool; and
  both service fns embed `attribution` in the usage event even on a
  no-increase reconcile — the marker is atomic with ledger state.
- Non-stack legs 23/23 green; module stack test re-running.
