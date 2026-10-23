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

## Audit round 3 (gpt-6.1-sol, same session) — VERDICT: PROBLEMS

r2 repairs verified (journal continuity, reserved events, cancelled-ask
refusal, unbound/stale reservation refusal, overlay argv, missing-tool
classification; 15 pure legs green). Eight new findings against
`df18b514`; all remediated:

1. **[P1] teardown-probe timeout fell through into a fresh agent turn** —
   `execute_run` caught the `_pending_resume` wait_for exception as
   `resume_record=None` and spawned the ORIGINAL turn beside a possibly
   live namespace. The probe now raises `_ResumeSettled(
   "recovery_required")`: an unknown handoff stops execution.
2. **[P1] missing control socket was treated as death proof** — the ctl
   dir is rw-bound into the sandbox (a live child can unlink its socket)
   and a foreign claimant may lack the host-local path. The marker-only
   rule is now honest: `_paused_marker_seen` is the ONLY pass condition;
   `_old_namespace_alive` survives strictly as a positive-liveness log —
   `False`/`None` are inconclusive, never a green light.
3. **[P1] supported credential spellings survived the scrub** — MCP env
   LISTS (`["GITHUB_TOKEN=…"]` is a supported form,
   mcp/client.py:998-1006), run-together names (`PGPASSWORD`,
   `ACCESSTOKEN`), and `database_url`-style keys whose values carry
   `scheme://user:pass@` userinfo. `_scrub_credential_values` now
   redacts `KEY=confined` inside lists, matches bare credential
   suffixes (`password|passwd|pwd|secret|token|credential|dsn|
   privatekey`) and scans every scalar for URL-userinfo — while
   `max_tokens`/`sort_key`/credential-free URLs still survive.
4. **[P2] early-resume settle bypassed terminal bookkeeping** —
   `settle_run`+`return` skipped the metering flush, terminal usage
   upsert, attribution notes, span close, quota release and notify that
   `commit_terminal` performs. Early resume verdicts now raise
   `_ResumeSettled(status, detail)` caught in the shared except path —
   the SAME finalize runs (usage ledger, span, quota, notify,
   lease-fenced `commit_terminal`).
5. **[P2] error classification missed registered-tool formats** —
   `[workflow error:`, `[workflow timeout:`, `Download failed:`,
   `[search error`, `[agent error`, `[pipeline error`, `error:`,
   `failed to ` all read as success. `_tool_call_failed` now delegates
   to the codebase's canonical `log.log_helpers.classify_agent_result`
   (failed|timed_out|cancelled ⇒ failed); empty output stays
   unclassified-not-failed.
6. **[P2] approved MCP calls could not resolve on resume** — the resume
   orchestrator registered only builtins. `_execute_approved_call` now
   mirrors the original turn's surface: `subagents_enabled` from the
   real manager flag, `run_official_agent_enabled` from the merged
   config, and `load_mcp_servers(mcpServers)` registered with the same
   risk mapping + collision rules AgentV2 uses — clients disconnected
   in finally so no stdio server outlives the replay.
7. **[P2] normal-dev chain used an uncommitted tool API** — the module
   test invoked `edit` with `operation="write"`/`content`, which exists
   only in a dirty worktree. The leg now uses the SHIPPED contract
   (`filePath`+`oldString`+`newString` on a pre-created file) so the
   chain proves itself on the committed checkout.
8. **[P2] descendant sweep could target a reused pid** —
   `psutil.Process(proc.pid)` built lazily at kill time could enumerate
   a REPLACEMENT process's children. The spawn site now pins
   `psutil.Process(pid)` (pid+create_time) into `proc_identity` and both
   the cancel sweep and the finally tail-kill verify
   `is_running()` before signalling — a reaped-and-reused pid is never
   our child.

## Audit round 4 (gpt-6.1-sol, same session) — VERDICT: PROBLEMS

r3 repairs verified (18 committed legs green; probe→recovery_required,
marker-absent→unproven, CONNECT forwarding live). Three findings
against `74f4c9c7`; all remediated:

1. **[P1] MCP `args` lists still disclosed credentials** — the r3
   list-item handling only inspected `KEY=VALUE` strings. Positional
   args like `args: ["--dsn", "postgres://u:p@db/app"]` survived into
   the mounted YAML. The scrubber now redacts ANY scalar list item
   carrying URL userinfo, and `=`-form items additionally cover the
   `--flag=value` spelling (dash-stripped name match).
2. **[P2] resume never saw the MCP config** — the parent deletes
   `.data/config.yaml` before spawn and the resume branch returned
   BEFORE the child-side config copy, so `load_config()` inside
   `_execute_approved_call` read defaults with empty `mcpServers` —
   approved MCP tools still resolved "not found". The config
   copy+merge now runs BEFORE the resume branch in
   `run_sandboxed_turn`, so the replay registers the same tool surface
   the original turn saw.
3. **[P2] classifier false-positive on printed output** —
   `classify_agent_result` treats any "circuit breaker"/"模型调用已暂停"
   CONTENT as failure — agent-answer semantics that falsely
   terminalize a successful tool that merely prints the phrase.
   `_tool_call_failed` now uses only the canonical PREFIX tuples
   (`_CANCELLED/_TIMEOUT/_FAILED_RESULT_PREFIXES`), keeping the r3
   coverage of workflow/search/download error forms without the
   content-match hazard.

## Audit round 5 (gpt-6.1-sol, same session — terminated on quota before verdict)

r5 reproduced four findings plus a fifth caught by the W7 integration
gate on the deployed stack; all remediated:

1. **[P1] separated credential flag/value pairs survived the scrub** —
   `args: ["--api-key", "s3cr3t"]` is a supported MCP spelling: the r4
   list-item scrub only handled `=` forms and userinfo URLs, so the
   secret rode into the mounted config. The scrubber now redacts the
   item FOLLOWING a credential flag (a following `--` item is a new
   flag, not a value, and is left alone).
2. **[P1] ctl server dropped fragmented/oversized valid frames** —
   `_handle` read once (`reader.read(cap+1)` returns after the first
   chunk), so a >64KB ask/journal frame split across packets was parsed
   as partial JSON and rejected `not JSON`. The handler now reads to
   EOF (the client half-closes after its frame) with the same size cap
   and per-read timeout. Regression test drives a 300KB frame in two
   delayed writes.
3. **[P1] `.data` cleanup had a symlink check-then-use race** — the
   parent lstat-checked `.data` then unlinked by path BEFORE the
   teardown barrier proved the old confined child dead: a swapped
   `.data -> /host/path` symlink would make the UNCONFINED parent
   delete a host file. Cleanup moved after the resume probe (a missing
   turn.paused marker raises before it) and goes through
   `_safe_unlink_inside` — POSIX O_NOFOLLOW|O_DIRECTORY + dir_fd unlink
   (atomic on the opened inode), realpath-equality guard elsewhere.
4. **[P2] successful `Error:` stdout misclassified as failure** —
   `bash` formats exit-0 output as raw stdout; output starting with
   `Error: fixture text` was classed failed. The bare-error table now
   contains ONLY the codebase's real unbracketed tool errors
   (`Download failed:`, `Failed to install`, `Failed to add MCP`,
   `Failed to save config`, `Error: File exceeded`); generic
   `error:`/`failed to ` prefixes are ordinary output.
5. **[P1] overlay probe proved the wrong mount — deployed spawn died**
   — found by re-running the W7-C05 real-stack leg: `run.error` showed
   `bwrap: Can't make overlay mount on (null) ... Invalid argument`.
   Bisection inside `python:3.12-slim` + bwrap 0.12: the kernel
   EINVALs an `/etc` overlay lower inside a container (Docker injects
   file mounts for resolv.conf/hostname/hosts) while `/usr` and `/var`
   succeed — and the `--tmp-overlay` probe passed, so the drain added
   an argv bwrap could never mount. `overlay_dests(state_root)` now
   probes EVERY candidate with the production argv shape on the real
   state-root fs and returns only the dests that genuinely mount
   (container verdict: `usr`+`var` yes, `etc` no — it stays ro-bound).
   Verified live: `touch /usr/x` lands on the task overlay,
   `/etc` writes fail read-only, spawn proceeds.

## Test evidence (r5)

- `tests/web/w8`: 43 passed, 3 environment skips (no bwrap/userns, no
  AF_UNIX) — includes new legs: fragmented 300KB ctl frame, separated
  credential pair scrub, symlinked-`.data` refusal, `Error:` success
  output classification.
- Deployed-stack repro `python:3.12-slim`+bwrap 0.12.0: `/etc` overlay
  EINVAL reproduced at argv level; usr+var shape verified end-to-end.
- `tests/web/w7/test_w7_c05_module.py::test_w7_c05_integration`:
  PASSED post-fix (405s real stack: worker.lease ->
  event/agent_started -> honest provider-boundary failed). Full W7
  suite re-run: 71 passed + this leg = no regressions.

## Audit round 6 (gpt-6.1-sol, same session 01a140a7 — VERDICT: PROBLEMS, 3 findings)

r6 audited `e2121c18` and verified r1-r5 fixes end-to-end (separated-pair
scrub, `Error:` classification, dir_fd unlink, `overlay_dests` returning
`usr`+`var` live). Three findings, all remediated:

1. **[P1] credential URL with a query-string `=` survived the scrub** —
   a positional MCP arg like `postgres://audit:pw@db/app?sslmode=require`
   took the `KEY=VALUE` branch (the `=` belongs to the query, not an
   assignment) and leaked whole. The list-item scrub now partitions on
   `=` and only treats it as an assignment when the left side is a real
   KEY/`--flag` name (`_ASSIGN_KEY_RE`); otherwise the whole string is
   checked for userinfo first. `DATABASE_URL=postgres://u:p@...` keeps
   its key (`DATABASE_URL=confined`); the bare URL becomes `confined`.
   First attempt regressed the env-entry case (key name lost); caught
   by the same unit test and fixed via the key-shape gate.
2. **[P1] `/etc` stayed read-only — apt development needs a writable
   private /etc** — r5 honestly DROPPED the /etc overlay when the
   kernel rejected Docker's injected file mounts as a lower; that left
   `apt`/`update-ca-certificates` unable to write. `overlay_dests` now
   returns `{dest: "direct" | "seed"}`: a dest that EINVALs as a direct
   lower is retried SEEDED — a plain `copytree` of the tree (injected
   mounts gone) — and `build_sandbox_argv` accepts
   `(upper, work, dest, lower_src)` 4-tuples, ro-binding the seed at
   its own path and naming it in `--overlay-src`. In-container proof
   (python:3.12-slim, bwrap 0.12, named-volume state root):
   `{/usr: direct, /var: direct, /etc: seed}` -> `seed-content-ok`,
   `etc-write-ok`, `/usr-write-ok`, `/var-write-ok`. A state_root on
   overlayfs (`/tmp` inside a container) still honestly returns `{}`.
3. **[P2] per-sandbox overlay upper/work dirs persisted after
   destroy** — `retain=False` removed the sandbox record but left
   `{sandbox_id}-conf/-ctl/-ovl` trees under state_root forever.
   `execute_run` now tracks every per-claim dir and
   `_remove_claim_dirs` rmtree's them in teardown (after the child is
   dead, sockets closed, record destroyed). The run-keyed journal dir
   (`state_root/journals/<tenant>/<run>`) is deliberately NOT a claim
   dir — at-most-once replay needs it across worker reclamation.

## Test evidence (r6)

- `tests/web/w8`: 45 passed, 3 environment skips (no bwrap/userns, no
  AF_UNIX) — new legs: query-string credential URL scrub,
  seeded-overlay argv shape (`--ro-bind seed` + `--overlay-src seed` +
  `--overlay UPPER WORK /etc`), claim-dir teardown removal vs journal
  survival.
- In-container real-function verification (`python:3.12-slim` + bwrap
  0.12.0, ext4-backed volume state root): `overlay_dests` ->
  `{/usr: direct, /var: direct, /etc: seed}`; real
  `build_sandbox_argv` + exec -> writes land on task-private layers for
  all three dests; probe honestly returns `{}` on an overlayfs
  state_root.
- `python -m ruff check` on drain.py / userns.py / tests/web/w8:
  clean.

## Audit round 7 (gpt-6.1-sol, same session 01a140a7 — VERDICT: PROBLEMS, 2 findings)

r7 audited `71f88cf2`, re-ran the 19 targeted unit legs, and verified
the r6 fixes (query-url scrub, seeded-overlay argv shape, claim-dir
teardown preserving the run journal). Two new P1 findings, both
remediated and re-verified:

1. **[P1] Credentials inside opaque launcher strings reached the
   sandbox** — `_scrub_credential_values` only understood whole-item
   forms; `args: ["-c", "exec server --api-key K"]` kept the secret
   verbatim in the mounted YAML, readable without ever running MCP.
   `_scrub_inline_secrets` now performs the surgical pass on every
   surviving string — ``--flag VALUE``, ``--flag=VALUE`` and
   ``KEY=VALUE`` for credential names, and URL userinfo — replacing
   only the secret span. Bare credential URLs are still redacted
   whole (lead-anchored `_URL_CREDENTIAL_LEAD_RE`); composite strings
   keep their syntax. Shell separators (`;|&()` etc.) are excluded
   from the value charset so `export API_KEY=x; srv` keeps its `;`.
   Two grammar bugs were caught and fixed while wiring this: the
   separated-pair branch applied `_is_credential_key` to the WHOLE
   item (a composite `run --token=x` ends in `_token` and ate the
   NEXT item) — it now requires a pure `_ASSIGN_KEY_RE` flag item;
   and the early `=`/pair checks could starve the inline pass.
2. **[P1] Writable project dir could shadow the trusted worker
   entrypoint** — `python -m rxycode_worker.drain` ran with
   `--chdir <writable workdir>`; `sys.path[0]` resolved project-first,
   so a planted `rxycode_worker/drain.py` executed instead of the
   trusted module — still inside the sandbox, but bypassing
   durable approval and call-reservation. `build_sandbox_argv` now
   takes `chdir` (default workdir, exec callers unchanged); the
   drain spawns the worker with `chdir="/tmp"` — the private tmpfs
   mounted before every bind, nothing pre-plantable — plus `-P` on
   >=3.11 and `PYTHONSAFEPATH=1` for every descendant python. The
   child sets its real cwd itself via `set_working_directory`.
   Container proof (python:3.12-slim, bwrap 0.12): the UNHARDENED
   shape resolves `SHADOWED-PROJECT-COPY`
   (`/state/proj/rxycode_worker/drain.py` — the planted file); the
   hardened shape resolves
   `/repo/packages/rxycode-worker/src/rxycode_worker/drain.py` in
   both chdir modes.

## Test evidence (r7)

- `tests/web/w8`: 47 passed, 3 environment skips — new legs:
  inline launcher-string scrub (`-c` payloads, `--flag=V`, `KEY=V`,
  embedded userinfo, `==`/shell-separator negatives), spawn-chdir
  hardening (`--chdir /tmp` + workdir still bound + `-P -m`), and
  `PYTHONSAFEPATH=1` in the child env.
- In-container shadowing proof: planted `rxycode_worker/drain.py`
  inside the writable project wins UNHARDENED (`SHADOWED-PROJECT-COPY`
  printed) and loses under `chdir=/tmp` + `-P` + `PYTHONSAFEPATH=1`
  (trusted ro-bound module resolves).
- `python -m ruff check` on drain.py / userns.py / tests/web/w8:
  clean.

## Audit round 8 (gpt-6.1-sol, same session 01a140a7 — VERDICT: PROBLEMS, 3 findings)

r8 audited `f7490c24`, re-ran 20 targeted legs, and confirmed both r7
fixes (unquoted inline secrets, project-dir shadowing). Three new
findings, all remediated and re-verified:

1. **[P1] Quoted credential values survived the inline pass** —
   ``--api-key 'AUDIT KEY WITH SPACES'`` and ``API_KEY="K"`` passed
   verbatim because the value charset excluded quotes. The inline
   value pattern is now an alternation: a quoted span dies whole with
   its quotes for credential names, and a NON-credential flag/key with
   a quoted payload (``-c 'srv --password K'``) keeps its name while
   the quoted region is recursively re-scrubbed — quoted spans are
   opaque to the regex engine and previously swallowed inner secrets
   (``-c 'payload'`` matched `-c` and consumed the quote as its
   "value").
2. **[P1] Writable task HOME enabled a .pth startup hook** —
   ``HOME=<workdir>/.home`` is task-writable; a planted
   ``.local/lib/pythonX.Y/site-packages/*.pth`` executes at
   interpreter startup, before ``-m`` resolution — ``-P`` does not
   cover user-site. The trusted spawn now runs ``-s`` (all versions,
   not just >=3.11): user-site is the ONLY writable site-packages
   (system/PYTHONPATH dirs are ro-bound). Container proof: without
   ``-s`` a planted .pth writes its marker (`hook-ran: True`); with
   ``-s`` it never executes (`hook-ran: False`).
3. **[P2] PYTHONSAFEPATH=1 contagion broke ordinary task python** —
   forcing safe-path into every descendant meant a task's own
   ``python -c 'import solution'`` could no longer import workspace
   modules — normal development semantics destroyed for a protection
   descendants never needed (sandbox code is untrusted anyway;
   bootstrap hardening matters only for the trusted entrypoint).
   `_child_env` no longer sets PYTHONSAFEPATH/PYTHONNOUSERSITE; the
   hardening lives solely on `_trusted_child_argv()`: ``-P`` (>=3.11)
   + ``-s`` + ``-m`` + ``chdir=/tmp``.

## Test evidence (r8)

- `tests/web/w8`: 47 passed, 3 environment skips — extended legs:
  quoted flag/KEY values, quoted `-c` payload rescan (`-c 'srv
  postgres://u:p@db --password pw1'` -> userinfo and flag value
  die inside the quotes), ``_trusted_child_argv`` shape (``-s``
  unconditional, ``-P`` on >=3.11), no safe-path env in child env.
- In-container .pth-hook proof (python:3.12-slim, bwrap 0.12,
  HOME=<workdir>/.home): planted site-packages .pth executes
  UNHARDENED (`hook-ran: True`), never executes with `-s`
  (`hook-ran: False`).
- `python -m ruff check` on drain.py / tests/web/w8: clean.

## Audit round 9 (gpt-6.1-sol, same session 01a140a7 — VERDICT: PROBLEMS, 2 findings)

r9 audited `f67c72be`, re-ran 20 targeted legs, and confirmed all r8
fixes (quoted values, `-s` startup, descendant import semantics). Two
new P1 findings, both remediated and re-verified:

1. **[P1] Shell-expression values glued to credential flags leaked** —
   ``--api-key $(printf %s KEY)`` left ``(printf %s KEY)`` readable
   (the value charset stopped at ``(``); ``--api-key ""KEY`` left the
   glued ``KEY`` after an empty quote pair. Credential names now
   consume the whole shell WORD — quoted spans, ``$(...)``, ``${...}``
   and glued continuations count as one word — so nothing behind the
   flag survives. Non-credential flags/keys with compound values get
   the value recursively re-scrubbed (``-c 'payload'``, ``--flag
   $(cmd --token K)``), quoted spans keeping their quotes.
2. **[P1] Authorization headers in MCP args stayed verbatim** —
   ``--header "Authorization: Bearer KEY"`` hid the credential inside
   a quoted string the name tables never flagged. `_AUTH_HEADER_RE`
   / `_AUTH_HEADER_NAKED_RE` / `_AUTH_SCHEME_RE` now redact
   ``Authorization``/``X-Api-Key``-style headers (name + scheme kept,
   credential dropped) and bare ``Bearer|Basic|OAuth`` scheme values
   with a token-length floor — prose like "the bearer of bad news"
   survives.

## Test evidence (r9)

- `tests/web/w8`: 47 passed, 3 environment skips — extended legs:
  ``$(...)`` whole-word consumption, ``""SECRET`` glued-word
  consumption, ``Authorization: Bearer`` header redaction,
  ``X-Api-Key:`` naked header redaction, prose survival.
- Manual repro of every committed case via ``_scrub_inline_secrets``:
  ``--api-key $(printf %s KEY)`` -> ``--api-key confined``;
  ``--api-key ""KEY`` -> ``--api-key confined``;
  ``--header "Authorization: Bearer K"`` -> ``...Bearer confined"``.
- `python -m ruff check` on drain.py / tests/web/w8: clean.

## Audit round 10 (gpt-6.1-sol, same session 01a140a7 — VERDICT: PROBLEMS, 2 findings)

r10 audited `518cf502` and confirmed the r9 fixes hold (shell-word
consumption, auth-header scrub). Two new P1 findings, both remediated
and re-verified:

1. **[P1] Nested and backtick substitutions leak complete credentials** —
   the regex-based shell WORD could not balance nested ``$(...)``:
   ``--api-key $(printf %s $(printf ignored) AUDIT_NESTED_KEY)``
   stopped at the first ``)`` and left ``AUDIT_NESTED_KEY)`` mounted;
   a backtick substitution `` `printf %s AUDIT_BACKTICK_KEY` `` was
   not treated as substitution syntax at all, so its interior secret
   survived verbatim. The regex word matcher was replaced with a real
   scanner: ``_shell_word_end`` walks the word with a depth counter —
   single/double/backtick quoted spans, nested ``$(...)``, ``${...}``
   all count as one word, and the word ends only at unquoted
   whitespace or a shell separator. Flag tokens and ``KEY=`` leads are
   located by ``_FLAG_TOKEN_RE`` / ``_ASSIGN_LEAD_RE``, then the value
   is consumed by the scanner — credential names redact the whole
   word, non-credential names keep the name and get the value
   recursively re-scrubbed. An overlap guard skips flag/assign matches
   that start inside an already-consumed value word (a
   ``-c 'payload --password K'`` case where ``--password`` inside the
   quoted span was reprocessed and re-appended out of place — caught
   and fixed during remediation, not by the audit).
2. **[P1] Azure-style ``api-key`` headers stayed verbatim** —
   ``--header "api-key: TOKEN"`` used a header name absent from the
   auth-header table even though the egress gateway itself accepts
   the ``api-key`` header (egress.py). ``api-key``/``apikey`` added to
   ``_AUTH_HEADER_RE`` and ``_AUTH_HEADER_NAKED_RE`` — the header name
   and ``:`` survive, only the credential is redacted.

## Test evidence (r10)

- `tests/web/w8`: 52 passed, 3 environment skips — new legs:
  ``$(a $(b) KEY)`` nested substitution fully consumed,
  backtick substitution consumed, ``api-key: TOKEN`` redacted with
  header name kept, consumed-word overlap guard (no tail artifact),
  ``${VAR}`` glued word fully consumed.
- Manual repro of the audit counterexamples via
  ``_scrub_inline_secrets``: ``--api-key $(printf %s $(printf i) K)`` ->
  ``--api-key confined``; ``--api-key \`printf %s K\` `` -> ``--api-key
  confined``; ``--header "api-key: K"`` -> ``"api-key: confined"``.
- `python -m ruff check` on drain.py / tests/web/w8: clean.

## Audit round 11 (gpt-6.1-sol, same session 01a140a7 — VERDICT: PROBLEMS, 2 findings)

r11 audited `456842af` and confirmed the r10 fixes hold. Two new P1
findings, both remediated and re-verified:

1. **[P1] Continuation and process-substitution values still leaked** —
   ``--api-key \<newline>KEY``: the shell line-continuation ``\<nl>``
   is skipped whitespace, so the real value word lives on the next
   line — the scanner consumed only the ``\`` and left
   ``AUDIT_CONTINUED_KEY`` mounted. ``--api-key-file <(printf %s
   KEY)``: process substitution ``<(``/``>(`` was treated as a
   redirect separator, so the flag and its whole substitution word
   survived verbatim. Fixes: the SEP-value skipper now consumes
   ``\<newline>``/``\r\n`` continuations alongside whitespace;
   ``<(``/``>(`` open depth-tracked words in ``_shell_word_end``; the
   escape rule ``\x`` consumes both chars (``\$`` starts no
   substitution); and quoted-span detection ignores quotes preceded
   by an odd run of ``\`` (``\"`` inside ``"..."`` does not close the
   span — without this the Digest value was cut at ``username=\``
   and the rest of the pair list survived).
2. **[P1] Structured ``Digest`` authorization only partially
   redacted** — ``Authorization: Digest username="u", realm="r",
   nonce="n", uri="/mcp", response="..."`` is a comma-separated k=v
   list whose ENTIRE value is credential material; the generic
   header pattern consumed only the first fragment (``username=``)
   and left the full ``response=`` mounted. New ``_AUTH_DIGEST_RE``
   consumes the whole k=v pair list (plain ``"v"``, escaped ``\"v\"``
   and unquoted values) before the generic header rule — the scheme
   word survives, the list dies.

## Test evidence (r11)

- `tests/web/w8`: 55 passed, 3 environment skips — new legs:
  ``\<newline>`` continuation consumes the next-line secret,
  ``<(cmd)`` process substitution consumed, ``Digest`` k=v list
  consumed whole (real-quote and escaped-quote forms).
- End-to-end through ``_prepare_child_data_dir``-equivalent
  ``_scrub_credential_values`` on the audit repro: mounted YAML
  contains ``--api-key confined``, ``--api-key-file confined`` and
  ``Authorization: Digest confined`` — no ``AUDIT_*`` substring.
- `python -m ruff check` on drain.py / tests/web/w8: clean.

## Audit round 12 (gpt-6.1-sol, same session 01a140a7 — VERDICT: PROBLEMS, 3 findings)

r12 audited `3d40152f` (the depth-cap hardening `dbb83d7c` landed
mid-audit; the audit's own deep-nesting probe had already surfaced
the signal it fixes). Three new P1 findings, all remediated:

1. **[P1] Nested parameter defaults leaked** — ``--api-key
   ${_A:-${_B:-} KEY}``: the ``${...}`` handler searched for the
   first ``}`` and stranded ``KEY}``. ``${`` now opens a brace-depth
   counter in ``_shell_word_end`` (bare ``{``/``}`` inside count too,
   matching ``${x/{a}/b}``-style patterns; interleaved ``$(``/``${``
   depths are tracked independently).
2. **[P1] ANSI-C ``$'...'`` truncated redaction** — ``--password
   $'a\' KEY'`` is ONE argument in bash (``\'`` is an escaped quote);
   treating it as a POSIX single quote closed the span at ``\'`` and
   left ``KEY'`` mounted. A ``'`` preceded by ``$`` now takes the
   escape-aware scan used for ``"``/`````` `` — plain ``'...'`` keeps
   POSIX semantics (``\`` literal inside).
3. **[P1] Digest quoted pairs with ``\"`` still exposed
   ``response=``** — ``username="a\"b"`` is a valid Digest
   quoted-string; the pair-value alternative closed at the escaped
   quote and left the trailing ``response="..."`` mounted. The pair
   value now accepts ``\"(?:\.|[^"\])*\"`` — escaped chars inside
   the quoted value are skipped wholesale.

## Test evidence (r12)

- `tests/web/w8`: 58 passed, 3 environment skips — new legs:
  ``${_A:-${_B:-} KEY}`` nested expansion consumed,
  ``$'a\' KEY'`` ANSI-C word consumed, ``username="a\"b"`` escaped
  pair followed by ``response=`` fully consumed.
- Audit repro through ``_prepare_child_data_dir``-equivalent
  ``_scrub_credential_values`` verified for all three.
- `python -m ruff check`: clean.

## Audit round 13 (gpt-6.1-sol, same session 01a140a7 — VERDICT: PROBLEMS, 3 findings)

r13 audited `ea4c4ac1` (+depth-cap `dbb83d7c`) and confirmed the r12
fixes hold. Three new P1 findings, all remediated:

1. **[P1] Quotes inside ``$(...)`` closed outer quotes early** —
   ``--api-key "$(printf "%s " K | tr -d ' ')"`` is ONE argument: the
   inner ``"`` before ``%s`` terminated the outer quoted span in the
   escape-aware find, stranding ``K | tr -d ' ')"``. The
   depth-counter model could not express quote-inside-substitution;
   ``_shell_word_end`` is now a real context STACK — ``'``/``"``/
   ``````/``$'`` quote contexts plus ``(``/``{`` substitution
   contexts — where a ``"``/``$(``/``${``/```` `` inside ``"..."``
   pushes its own context and only the outer ``"`` at stack-empty
   ends the span.
2. **[P1] Heredoc bodies mounted verbatim** —
   ``--api-key-file /dev/fd/3 3<<'TAG'\nKEY\nTAG`` redacted the fd
   path but left the body text. ``_heredoc_pass`` finds ``<<TAG`` /
   ``<<-TAG`` / quoted-tag openers, locates the terminator line, and
   replaces the body between with ``confined`` — marker and
   terminator survive.
3. **[P1] RFC 7616 ``username*`` ext parameters broke the Digest
   pair grammar** — ``username*=UTF-8''J%C3%A4…``: the ``*`` was not
   a valid key char and the ``charset'lang'value`` value matched no
   alternative, so the pair list aborted before ``response=``. Key
   charset now allows a trailing ``*``; the pair value accepts
   ``[^,\s"]+`` covering ``'``-containing ext-values and quoted
   forms.

## Test evidence (r13)

- `tests/web/w8`: 61 passed, 3 environment skips — new legs:
  ``"$(printf "%s " K | tr -d ' ')"`` inner-quote word,
  ``3<<'TAG'\nKEY\nTAG`` body redaction (terminator survives),
  ``username*=UTF-8''J%…`` ext-value pair list fully consumed.
- `python -m ruff check`: clean.

## Audit round 14 (gpt-6.1-sol, same session 01a140a7 — VERDICT: PROBLEMS, 3 findings)

r14 audited `7c4a9b4e` and confirmed the r13 fixes hold. Three new P1
findings, all remediated (also confirmed: no cross-claim partial-seed
reuse — seed dirs are ``{sandbox_id}-ovl``-scoped and sandbox_id is a
fresh uuid per claim, so a crashed copytree can never be reused):

1. **[P1] ``case`` patterns terminated substitutions early** —
   ``$(case x in x) K;; esac)``: the pattern's ``)`` was popped as the
   substitution closer, stranding ``K;; esac)``. ``_shell_word_end``
   now tracks bare words in word/substitution contexts — ``case``
   inside a paren context pushes a ``case`` marker (pattern ``)``s
   literal), ``esac`` pops it; word accumulation spans quoted
   interiors (``cas'e'`` still detects the keyword).
2. **[P1] Heredoc delimiter variants + unterminated bodies** —
   ``<<'RXY-KEY'`` hyphenated delimiters missed the identifier-only
   tag charset (body kept); the terminator regex ``^[ \t]*TAG``
   over-accepted whitespace for plain ``<<`` (POSIX: exact line;
   ``<<-`` strips tabs; ``<<~`` strips whitespace — implemented per
   opener flag); unterminated bodies run to EOF in bash and are now
   redacted to EOF. Delimiter regex accepts quoted/``-``/``~``
   forms and arbitrary word chars.
3. **[P1] Queued heredocs on one command line** — ``3<<A 4<<B`` reads
   two bodies in order; the second opener fell inside the first
   body's consumed span and was skipped, leaving body B mounted.
   ``_heredoc_pass`` now collects every opener before the command
   line's newline and consumes queued bodies sequentially.

## Test evidence (r14)

- `tests/web/w8`: 65 passed, 3 environment skips — new legs:
  ``$(case x in x) K;; esac)`` consumed, ``<<'RXY-KEY'`` hyphen
  delimiter, ``3<<A 4<<B`` queued bodies, unterminated body to EOF.
- `python -m ruff check`: clean.

## Audit round 15 (gpt-6.1-sol, session 01a15592 — VERDICT: PROBLEMS, 6 findings)

r15 audited 16335bba. Session note: the accumulated r1–r14 context
in codex session 01a140a7 began tripping the provider content
filter mid-turn (twice — turn.failed before findings), so the
audit continued in fresh session 01a15592 with identical
model/effort/read-only settings; it re-verified the committed 20
scrub regressions itself before reporting. Six findings, all
remediated:

1. **[P1] Compound auth-header values stranded** — Authorization:
   Bearer $(printf %s K): the header value charset ate only $,
   leaving the command text mounted. Header matching now finds only
   the LEAD (name + separator + optional scheme); the value is a
   shell word located by _shell_word_end — $(…)/quoted words
   die whole; plain tokens use a bounded scan so an unterminated
   enclosing quote cannot swallow the tail.
2. **[P1] >256-char URL passwords bypassed redaction** — the
   {1,256} bounds in all three userinfo regexes are removed
   (unbounded charsets are linear; a 300-char password is still a
   password).
3. **[P2] Port+path faked userinfo** — https://host:443/@scope/pkg
   was redacted whole: the password charset admitted /, letting
   443/ pose as a password up to @scope. / now ends the
   userinfo span (RFC 3986 ends authority at / anyway).
4. **[P2] Bare-scheme prose destroyed** — Basic configuration
   matched the 8-char floor. Bare-scheme values (no header-name
   context) now require credential shape: a non-alpha char or >=32
   chars; Bearer eyJ… still dies, the bearer of bad news
   lives. Header-named forms keep their previous behavior — the
   header name is itself credential context.
5. **[P2] Cyclic YAML aliases RecursionError** — &x [*x] loads as
   a real object cycle; _scrub_credential_values now dedups
   containers by id() — shared DAG nodes are also processed once.
6. **[P2] Exponential rescan amplification** — nested compound values
   made flag/assign passes revisit overlapping text (292 chars →
   ~196k calls, ~5.2s). A per-string work budget (2048 rescan calls,
   max(64KiB, len*8) rescanned chars) fails closed: same input now
   ~0.03s with the inner payload confined.

## Test evidence (r15)

- tests/web/w8: 65 passed, 3 environment skips — new legs:
  Bearer $(…)/Bearer ${…:-…} whole-word, 300-char URL
  password, :443/@scope port+path preservation, bare-scheme prose
  vs token, cyclic id() dedup, work-budget bound.
- python -m ruff check: clean.

## Audit round 16 (gpt-6.1-sol, session 01a15592 — VERDICT: PROBLEMS, 5 findings)

r16 audited ``bd6aaacb``: all six r15 fixes re-verified against the
original reproductions (rescan amplification 196,417 -> 1,061 calls).
Five new findings, all remediated:

1. **[P1] Prefixed substitutions in header values** — ``Bearer
   prefix$(printf %s K)``: the value does not START with substitution
   syntax but is still ONE shell word; the bounded scan stopped before
   ``$(`` and left the command text mounted. ``_shell_word_end`` grew
   ``stop_at_unclosed_quote`` — a mid-word quote context that never
   closes is really the enclosing word's closer, so the word ends at
   the quote. Every header/bare-scheme value now uses the full word
   scanner with that flag: ``prefix$(…)`` dies whole while
   ``Bearer K" u`` still stops at ``"``.
2. **[P1] Empty-username credential URLs** — ``https://:SECRET@host``:
   the ``+`` username bound required a nonempty user; ``:pass@`` is a
   live password regardless. Username is now ``*``.
3. **[P1] Heredoc ``\<newline>`` joins** — inside an UNQUOTED heredoc,
   ``prefix\`` + newline joins with the next physical line before the
   terminator compare, so a physical ``EOF`` continuation line is body
   content. ``_find_term`` now scans logical lines for unquoted
   delimiters (odd trailing-backslash continuation tracking); quoted
   delimiters keep physical-line compare. Command lines ending in
   ``\<newline>`` also extend before body start is located.
4. **[P2] Query/fragment fake userinfo** — ``https://h:443?e=u@x`` and
   ``:443#c@x``: ``?``/``#`` now also end the userinfo span (RFC 3986
   authority boundary).
5. **[P2] Deep acyclic alias chain RecursionError** — a 1101-link
   ``*alias`` DAG is not a cycle, so id-dedup alone still overflowed;
   ``_scrub_credential_values`` traversal is now ITERATIVE (explicit
   stack) — cycles dedup by ``id()``, arbitrary depth cannot crash.

## Test evidence (r16)

- ``tests/web/w8``: 76 passed, 3 environment skips — new legs:
  ``prefix$(…)``/``pre${…:-…}`` whole-word header values, glued-quote
  value words, ``:SECRET@`` empty-user URLs, ``?``/``#`` authority
  boundaries, heredoc ``\<newline>`` logical-line terminators,
  1200-deep alias chain.
- ``python -m ruff check``: clean.

## Audit round 17 (gpt-6.1-sol, session 01a15592 — VERDICT: PROBLEMS, 4 findings)

r17 audited ``295b3d67``: all five r16 fixes re-verified (31 focused
regressions green). Four new findings, all remediated:

1. **[P1] Glued quote-closer words** — ``Bearer abc"SECRET``: a quote
   that is really the enclosing word's closer followed by glued bare
   text still forms ONE word — stopping at the quote left ``SECRET``
   mounted. ``stop_at_unclosed_quote`` is now two-tier: a word-level
   quote followed by a boundary/EOS returns the word end AT the
   quote (``Bearer K" u`` preserves ``" u``, and a following quoted
   arg like ``"https://example.org"`` is no longer eaten); a
   still-open quote mid-word rescans the glued tail for the real end,
   so ``abc"SECRET`` dies whole.
2. **[P1] Comment backslash continued the command line** — ``cat
   <<EOF # \<newline>SECRET``: the ``\`` inside a comment is not a
   continuation; the extended "command line" had swallowed body text
   verbatim. ``_comment_start`` locates the first unquoted
   word-boundary ``#`` outside ``(``/``{`` contexts and the
   continuation check only counts backslashes before it.
3. **[P2] Joined heredoc terminators** — ``E\`` + ``OF`` forms the
   logical line ``EOF``: a real terminator. ``_find_term`` now builds
   logical lines by joining ``\<newline>`` pairs and fullmatches
   those — joined terminators are recognized AND physical lines glued
   into their predecessor are skipped as candidates.
4. **[P2] ``yaml.safe_dump`` RecursionError** — a deep alias DAG can
   survive iterative scrubbing yet overflow the serializer; the
   write-side handler now catches ``RecursionError`` too — no config
   is written rather than crashing the turn.

## Test evidence (r17)

- ``tests/web/w8``: 76 passed, 3 environment skips — new legs:
  ``abc"SECRET`` glued word vs ``K" "url"`` boundary, comment
  ``\<newline>`` non-continuation, ``E\``+``OF`` joined terminator,
  deep-alias ``_prepare_child_data_dir`` fail-closed.
- ``python -m ruff check``: clean.

## Audit round 18 (gpt-6.1-sol, session 01a15592 — VERDICT: PROBLEMS, 4 findings)

r18 audited ``292a9a78``: r17 fixes re-verified (35 focused
regressions green). Four new findings, all remediated:

1. **[P1] Backtick+space mistaken for a closer** — ``Bearer ` printf
   %s K` ``: the word-level boundary shortcut treated a backtick
   followed by space as the enclosing word's closer, but backticks
   always OPEN a substitution (space is legal inside). Backticks are
   removed from the closer check; the word-level check also gained an
   ``i > start`` guard so a quote AT the value start is always an
   opener.
2. **[P1] ``#`` after operators starts comments too** — ``<<EOF;#
   \<newline>SECRET``: ``#`` begins a comment at ANY word boundary
   including ``;|&<>()`` — ``_comment_start``'s preceding-char set
   widened from whitespace to the shell separator set.
3. **[P2] Glued-word redaction dropped the enclosing closer** —
   ``abc"SECRET`` died whole but the consumed ``"`` was the enclosing
   word's closer, leaving the output quote-unbalanced
   (``...confined u``). ``_trailing_closer`` re-emits an unpaired
   ``"``/``'`` found past position 0 of the consumed value —
   ``confined"`` keeps the string balanced.
4. **[P2] Unclosed-quote rescan unbounded** — the
   ``stop_at_unclosed_quote`` fallback recursed once per unclosed
   quote, bypassing the rescan work guards (1100-deep →
   RecursionError). The recursive call now carries ``_qdepth`` with a
   64-frame cap — beyond it the tail is consumed as word content,
   fail-closed.

## Test evidence (r18)

- ``tests/web/w8``: 76 passed, 3 environment skips — new legs:
  backtick+space substitution, ``;#`` operator comments, closer
  re-emission on glued words, 1100-deep unclosed-quote chain.
- ``python -m ruff check``: clean.


## Round 19 — comment/newline boundaries, literal-brace delimiters, context-aware closers, continued delimiters

`VERDICT: PROBLEMS_REMAIN` (4 findings) on `fcb30b03`; all fixed.

| Finding | Root cause | Fix |
|---|---|---|
| `cat <<EOF \<nl># c \<nl>SECRET<nl>EOF` — comment after a continued line leaked the body | `_comment_start` did not treat `
` inside the segment as a word boundary and counted `{`/`(` as depth, so the `#` comment went unnoticed | comment detection is quote/escape-only now; `
` joins the boundary set and POSIX semantics are honoured (`#` inside `$(`/parens is still a comment) |
| `<<E{OF # \` — literal `{` in a delimiter word defeated comment detection | `{` inside a word is a literal char, not a nesting context | same `_comment_start` rewrite — no depth tracking at all |
| `Bearer $(printf %s K; : "x\"y")` dropped the outer closing quote | `_trailing_closer` paired quotes with naive `find`, mistaking `\"` and quotes inside `$(...)` for word-level closers | `_trailing_closer` reimplemented as a context-stack scanner (substitutions/ANSI-C/backticks/escapes) and emits the first truly unpaired quote |
| `<<E\<nl>OF` — delimiter assembled across a line join searched the wrong terminator | `_HEREDOC_RE` captured the physical `E\` token before joining | queue items re-extract flag/quoted/tag from the logical command line (`\<newline>` removed) before terminator search |

Focused r19 regressions: 4 new unit tests in `tests/web/w8/test_w8_c01_unit.py`.
Suite: `84 passed, 3 skipped` (bwrap/userns + AF_UNIX env skips), ruff clean.


## Round 20 — here-strings, composed delimiters, comments in substitutions, assembled names, container creds, paren/brace/quote edges

`VERDICT: PROBLEMS_REMAIN` (8 findings: 5xP1, 3xP2) on `ec57e943`; all fixed.

| Finding | Root cause | Fix |
|---|---|---|
| `3<<<SECRET` here-string operand stayed mounted | `<<<` never handled | `_heredoc_ops` reports `<<<` at command level; operand word replaced with `confined` in-place |
| `<<E"OF"`/`<<''` composed/empty delimiters | regex captured only `E`; quoted delimiter word not quote-removed | delimiter extracted via `_shell_word_end` + `_heredoc_delim` POSIX quote-removal (quoted flag preserved) |
| `$(printf x # )
SECRET
)` — `)` inside a comment closed the substitution | `#` comments inside command contexts not tracked | `_shell_word_end` skips `#`-comment to newline inside `(`, `case`, brace contexts; `${x#y}` unaffected (operator) |
| `API_\<nl>KEY=`/`--api-''key` assembled names | name regexes matched physical spelling only | `_NAME_SEG` allows `\<newline>`/`''`/`""` segments; `_cred_name` normalizes before checking |
| `{"credentials": [...]}`/`env.API_KEY: [K]` container values | container dispatch ran before credential-key check | dict branch: indirection/cred checks first; credential key redacts whole value including containers |
| `$(srv --token K)` lost the enclosing `)"` | word-level `)`/`(` were consumed as word chars | unmatched parens end the word at word level |
| `$((1 << 2))`/`"a<<EOF"` treated as heredocs | opener regex matched without shell context | `_heredoc_ops` context-stack scan: `<<` suppressed in quotes/`${}`/`$((`/comments, allowed in `$(`/subshells/backticks |
| `srv --token abc{ --verbose` ate `--verbose` | bare `{`/`}` pushed nesting context at word level | `{`/`}` are literal word chars at word level |

Suite: `88 passed, 3 skipped` (env skips unchanged), ruff clean. 8 new regressions appended.


## Round 21 — regex linearity, assembled names (quotes/escapes), nested redirs in ${}, enclosing-quote fidelity, arithmetic contexts, cross-line quote state, nested here-strings

`VERDICT: PROBLEMS_REMAIN` (7 findings: 3xP1, 4xP2) on `ac00ef2a`; all fixed.

| Finding | Root cause | Fix |
|---|---|---|
| `_NAME_SEG+` exponential backtracking (24 chars ~0.43s, 32-char config value >3s) | quantified alternatives over overlapping charsets | disjoint alternation: a backslash forces the 2-char escape branch; 100k chars scrubs in ~60ms |
| `--"api-key"` / `--api-\key` bypassed name check | name normalization covered only `''`/`""`/joins | `_cred_name` now applies `_heredoc_delim` POSIX quote-removal (`'x'`/`"x"`/`\x`/line-joins); flag pattern matches quoted name starts; `\=` accepted as escaped separator |
| `${x:-$(cat <<<SECRET)}` kept executable redirs | `_heredoc_ops` suppressed all `${}` contents | `${}` branch now recognizes `$(`/`$((`/`<(`/`>(`/quotes — `<<`/`<<<` inside a nested `$(` still count |
| `echo "srv --token K"` lost the closing `"` | flag/assign value scans ignored enclosing-quote context | value end uses `stop_at_unclosed_quote=True`; cred values re-emit `_trailing_closer` |
| `"$((1 << 2))"` and bare `((1 << 2))` misread as heredocs | `$((`/`((` pushed ordinary `(` contexts | `((` arithmetic context pushed in `"` and command-level scans (bare `((` vs `( (` distinguished) |
| `printf 'l1\na<<EOF\nl3'` false opener inside multi-line quote | `_heredoc_ops` scanned each line with fresh state | `stack` is carried across logical lines so an open quote still suppresses `<<` on the next |
| `cat <<<$(cat <<<SECRET)` double-replaced into `confinedconfined)` | ops inside a consumed operand were reprocessed | `<<<` ops inside a consumed operand word are skipped; `<<` ops still queue bodies |

Suite: `96 passed, 3 skipped`, ruff clean. 8 new regressions appended (name linearity is asserted via a 100k-char budget test).


## Round 22 — quote-state disambiguation, arithmetic nesting, ANSI-C names, multiline operands, literal `$'` in `"…"`, linear name scan

`VERDICT: PROBLEMS_REMAIN` (6 findings: 5xP1, 1xP2) on `42143a0f`; all fixed.

| Finding | Root cause | Fix |
|---|---|---|
| `srv --token abc" AUDIT_SECRET"` left `confined" AUDIT_SECRET"` | mid-word quote + boundary was always treated as the enclosing closer | `_quote_state` resolves the source-level enclosing quote via a bounded `_heredoc_ops` context scan: same quote open -> closer; a different quote open (`'` payload) -> literal glued char; bare -> opener iff an unescaped partner exists (keeps `K" u` closer semantics and the r18 next-arg case) |
| `echo $(( $(cat <<<SECRET) ))` kept the operand | arithmetic `((`/`((i` skipped all contents | arithmetic contexts now recognize nested `$(`/`${`/`$'`/`<(`/`>(`/quotes — `<<`/`<<<` inside a nested `$(` still count; pure `$((1<<2))` untouched |
| `srv --api-$'key' K` bypassed the name check | name segments lacked ANSI-C/`$"…"` forms | `_NAME_PART` accepts `$'…'`/`$"…"` segments; `{0,128}` caps bound the scan |
| `cat <<<"a
SECRET"` / `cat <<<\nSECRET` partially survived; final line with no trailing newline stayed OUTSIDE the logical line (`AUDIT_TAIL` survived); continuation/context joins were quadratic | logical-line join only covered `\<newline>`; `nxt == -1` broke before absorbing the last line; every iteration rescanned the growing segment | join loop scans each new physical line incrementally with carried state; `nxt == -1` joins the last line; a `#` comment line stops joins; >4096 joins absorb the rest of the input so a still-open operand dies whole — all linear |
| `echo "$'"; cat <<<SECRET` suppressed the `<<<` | `$'` pushed an ANSI-C context inside `"…"` where it is literal | `_shell_word_end`/`_heredoc_ops` `"` branches treat only `$(`/`${` as substitutions; `$'` is literal text there |
| `a\`*16000 name scan ~7.4s (quadratic) | name-part alternation allowed per-char rescan | disjoint alternation + length caps; 32k chars scrub in ~0.13s |

Suite: `109 passed, 3 skipped` (env skips unchanged), ruff clean. 6 new regressions appended.

## Round 23 — enclosing-quote preload, nested heredoc anchoring, ANSI-C names, cap fail-closed, `+=`/`[i]` assigns, dash values, header maps, colonless userinfo, sep fidelity, linear joins

`VERDICT: PROBLEMS_REMAIN` (13 findings) on `a4f32841`; all fixed.

| Finding | Root cause | Fix |
|---|---|---|
| `srv "--token=abc SECRET"` left ` SECRET` inside the outer quote | value scan treated the enclosing `"` as word-internal | `_shell_word_end` PRELOADS `_quote_state(text, start)` into the context stack — a value already inside quotes scans to the real closer |
| `srv --token a" SECRET` left ` SECRET` | unterminated quote was treated as an enclosing closer | no enclosing context -> the quote is an OPENER; POSIX reads the remainder as quoted text, so the word dies to EOS. The stale r17-era assertion (`confined" u`) was corrected to the POSIX reading |
| `echo $(cat <<E\nSECRET\nE\n)` kept the body and appended `confined` after `)` | heredoc pass anchored bodies at the OUTER command's line end | rewrite: per-op context depth from `_heredoc_ops`, body anchor starts after the logical line containing ITS OWN delimiter; absolute `(start,end,replacement)` events interleave with literal spans |
| `srv --token"="SECRET` emitted `--token"=confined` (unbalanced) | `=` was unquoted in the emit path | flag pass detects an OPEN quote at the name's end via a bounded `_heredoc_ops` scan; the quoted `"="` separator is re-emitted verbatim with the value dead after it |
| `srv --api-$'k\x65y' K` bypassed the name check | `$'…'` segments were quote-removed but not escape-decoded | `_ansic_decode` handles `\xHH`/`\uHHHH`/octal/`\cX`/simple escapes inside `_heredoc_delim`, used only for matching — output keeps the original spelling |
| 129-char `…_token` name survived | `{0,128}` part cap silently missed over-long names | flag pass: a matched name still touching name-charset chars fails closed and swallows the tail (bounded 4096); assign regex gained a `{129,4096}` long-name branch that is always credential |
| `TOKEN+=SECRET` / `export TOKEN[0]=SECRET` survived | `+=` and `[i]` were not assignment leads | `_ASSIGN_LEAD_RE` accepts `\+?=` and a `[…]` subscript; `_cred_name` strips the subscript before the key check |
| `srv --token -SECRET` kept `-SECRET` | any `-`-led word was treated as the next flag | only a `--` long-flag word stays a flag for credential names; a single-dash word is a legal getopt value and dies |
| `Authorization: Negotiate K` / `X-Api-Key: abc` survived | scheme list lacked `Negotiate`/`DPoP`/…; the 4-char naked floor applied to key-only headers | scheme list extended (`negotiate`, `dpop`, `hawk`, `aws4-hmac-sha256`, `signature`); `cookie`/`set-cookie` added as header names; the naked floor applies only to `authorization`/`proxy-authorization` — key-only header names die at any non-empty length |
| `headers: {api-key: SECRET}` / `headers: {Authorization: "Negotiate K"}` survived | dict traversal had no header-map semantics | `headers`/`http_headers`/`request_headers`/`extra_headers` dicts get header-name dispatch: `_HEADER_CRED_NAMES` values die wholesale, other values still get the inline pass |
| `https://SECRET@host` / `https://SECRET:@host` survived | userinfo regex required `user:pass@` | all three URL regexes accept colon-free and empty-password userinfo (`(?::…)?`); `@`-in-path URLs (`/@user`) still survive — no `://` before them |
| `echo --mode\=fast` was normalised to `--mode=fast` | cred/non-cred paths re-emitted `=` instead of the matched separator | both paths re-emit `src[sep_start:vstart]` verbatim — `\=`, `"="`, continuations, and whitespace all keep their original spelling |
| `cat <<E\n` + `x*100\<nl>`×16k ~5.03s (quadratic) | each join iteration rescanned the whole accumulated segment | incremental scan: each new physical line is scanned once with carried stack state; join cap absorbs the rest of the input fail-closed — 16k lines now ~0.28s |

Focused r23 regressions: 13 new unit tests in `tests/web/w8/test_w8_c01_unit.py`.
Suite: `122 passed, 3 skipped` (bwrap/userns + AF_UNIX env skips), ruff clean.

## Round 24 — escaped-boundary comments, body-context isolation for op rescan, comment-`\` joins, pass ordering, closer fidelity, ANSI-C `\U`/NUL, cap fail-closed, arrays, header argv values, far-quote context, linear terminator lookup

`VERDICT: PROBLEMS_REMAIN` (14 findings) on `e805e586`; all fixed.

| Finding | Root cause | Fix |
|---|---|---|
| `srv --token a\ #SECRET` → `confined#SECRET` | `#` after an escaped boundary char was treated as comment | `_escaped()` helper (odd backslash run) consulted in `_comment_start`, `_heredoc_ops` and `_shell_word_end` — escaped whitespace/separators are literal word content, no comment opens |
| `$(cat <<A\n'\nA\ncat <<B\nSECRET\nB\n)` — body B survived | the op scan walked BODY text as shell — the `'` inside body A faked a quote context that suppressed `<<B` | `_heredoc_ops` now returns per-op stack snapshots; after each eaten body the tail is RESCANNED on a context rebuilt from command text only (`op_stack` + the opener's line remainder), ops inside the body drop as literal text, and the rebuilt stack becomes the end-of-line carry |
| `echo $(cat <<E # \` + nl + `SECRET` + nl + `E` + nl + `)` inserted `confined` after `SECRET` | the nested body anchor counted a `\` inside a COMMENT as a continuation join | nested-anchor join loop now asks `_comment_start` whether the trailing `\` sits inside the line's comment — if so it is comment text, not a join |
| `cat <<E\nTOKEN="SECRET\nE\necho keep` → `cat <<E\nconfined\n` | assign pass read the BODY as an unterminated shell quote before the heredoc pass isolated it | pass order: `_heredoc_pass` runs FIRST — bodies are data, never syntax for other passes; terminator and following commands survive |
| `srv "--token=a'"` → `srv "--token=confined` (lost the enclosing `"`) | `_trailing_closer` scanned the value without its enclosing context — the `'` faked an unpaired opener | `_trailing_closer` seeds the context stack with the enclosing quote: other-type quotes inside are literal; the first char that pops the seeded frame is the glued closer and is re-emitted |
| `srv --api-$'\U0000006bey' K` / `--api-$'key\0junk' K` survived | `\U` (8-hex) not decoded; `\0` NUL not honoured | `_ansic_decode` handles `\U`+8 hex; a decoded NUL truncates the assembled name at exec semantics |
| `"X"*4091+"_TOKEN=S"`, `--`+`x`*4219+`_token S`, `TOKEN[`+`0`*33+`]=S` all survived | flag tail cap (4096) re-landed mid-name; subscript `{0,32}` missed | flag tail scan unbounded (C-speed run); subscript widened to `{0,4096}`; `[]` joined the run charsets so over-cap constructs still fail closed |
| `TOKEN=(SECRET)` / `TOKEN+=(S)` / `TOKEN[0]+=(S)` survived | `_shell_word_end` stops at `(` — array literals never scanned | `_array_end` balanced-paren scan (quote/escape aware); cred name redacts group contents as `(confined)`; unbalanced dies to EOF |
| `headers: {X-Custom-Token: SECRET}` / `{password: SECRET}` survived | header-map dispatch consulted only `_HEADER_CRED_NAMES` | header-map children also check `_is_credential_key` on the normalized name |
| `api-key: SECRET` survived standalone | hyphenated spellings never normalized for key checks | dict keys normalize `-`→`_` before indirection/credential checks (list items already did) |
| `args: ["-H","Cookie: a=F; b=SECRET"]` → `Cookie: confined; b=SECRET`; AWS4 `Signature=` survived | `;`/`,` inside an argv element ended the header value | `_auth_pass` extends the value across `;`/`,`-joined pairs to the element end (a word that already absorbed a `,` continues the same); `&`/`|`/newline still end it; auth/digest passes moved BEFORE assign so an `Authorization:` lead owns its whole `k=v, k=v` list |
| `curl -H "X-Amz-Security-Token: SECRET"` survived | header was map-only; `_AUTH_LEAD_RE` lacked it | `x-amz-security-token`/`x-goog-api-key` added to the inline lead table |
| `P + 'FIRST SECRET"'` (opener >8KB back) → `confined SECRET"` | `_quote_state` 8KB lookback lost the enclosing `"` | `_Enclosing` incremental scanner (r23 perf) is unbounded — the opener is found at any distance; verified `confined"` output |
| `"cat <<'E'\nx\nE\n" * n` — 27.99M chars copied at n=2000 (quadratic) | quoted-terminator search sliced `src[cursor:]` per opener | `_find_term` uses `pattern.search(src, cursor)` — no suffix copy; n=2000 now ~0.035s (linear) |

Focused r24 regressions: 14 new unit tests in `tests/web/w8/test_w8_c01_unit.py`.
Suite: `136 passed, 3 skipped` (bwrap/userns + AF_UNIX env skips), ruff clean.

## Round 25 — per-finding disposition after the data-flow change

Auditor verdict on `7a03dd82`: `PROBLEMS_REMAIN` (13 findings, full text kept by the reviewer). Every reproduction is a shell-shaped string carried by a HOST CONFIG field (`command`, `args`, `env`, `headers`, URL `base_url`), run through the value sanitizer during `_prepare_child_data_dir`.

**Data-flow change (this round).** The confined config is no longer a copy of the host `config.yaml` that is then scrubbed. `_build_child_config` CONSTRUCTS it: the sections of the product's own schema (`_default_config()`) are copied EXCEPT the excluded host/platform set (`mcpServers`, `rag`, `appserver`, `observability`, `evals`, `lsp`, `schedule`, `scheduler`, `computer_use`, `distillation`); `models` keeps only the used entry, and credential-bearing fields are removed by field NAME at any depth via the shared `_is_credential_key` matcher plus the indirection/header sets (`max_tokens`, `token_budget` survive); every other model entry never leaves the parent. The child-side `_merge_turn_config` no longer re-scrubs.

**Call-chain evidence (production code, `packages/` + `core/` + `appserver/` + `execution/` + `tools/` + `config/` + `utils/`).**

| Function | Production callers after this change |
|---|---|
| `_scrub_model_credentials` | none (was: `_prepare_child_data_dir`, `_merge_turn_config`) |
| `_scrub_credential_values` | only `_scrub_model_credentials` (tests call it directly) |
| `_scrub_inline_secrets`, `_shell_word_end`, `_array_end` | only the scrub tree above |

So the Shell parser has no production input from a confined turn. Each r25 reproduction takes a path that is no longer reachable from the confined data flow.

| # | Finding | Disposition | Evidence / note |
|---|---|---|---|
| 1 | `_array_end` closes inside `${…}` | 已替代 | `_array_end` only reachable from the scrub tree; the input field (`command` in a host config) is not copied |
| 2 | queued heredoc re-enters parser state | 已替代 | same chain |
| 3 | NUL truncation drops segments (leak + false positive) | 已替代 | same chain; the false-positive half is an availability defect, also unreachable |
| 4 | over-window assignment skips arrays | 已替代 | same chain |
| 5 | over-limit subscript with operators fails open | 已替代 | same chain |
| 6 | parameter-expanded flag names | 已替代 | same chain |
| 7 | substitutions inside URL userinfo | 已替代 | a model `base_url` with userinfo is no longer copied (only the gateway URL for the used model); the URL scrub is unreachable |
| 8 | unknown Authorization scheme leaks | 已替代 | `args`/`headers` of host MCP config are not copied |
| 9 | inline `-H` vs header-map recognition | 已替代 | same chain; quoted-name concatenation is the same class |
| 10 | literal `$'` inside `"…"` removes the closer | 已替代 | false rejection of a valid value = availability defect, unreachable in production |
| 11 | auth continuation consumes following commands | 已替代 | false positive = availability defect, unreachable in production |
| 12 | nested heredoc tail rescans quadratically | 已替代 | cost/DoS class in an unreachable parser; no production input |
| 13 | per-redirection stack snapshots quadratic memory | 已替代 | same as 12 |

**Pinned, not assumed.** `test_w8_c01_r25_inputs_never_reach_the_confined_config` feeds all seven shell-shaped r25 samples through an MCP/RAG/second-model config and asserts none of their secrets, and none of the `mcp`/`rag`/other-model fields, reach the child. `test_w8_c01_child_config_is_built_from_allowlist` pins the field-level rules.

**Residual (stated, not hidden).**
- The Shell parser code remains in the tree and keeps its unit tests; it is dead in production. Reviving it on any new input path requires re-opening this disposition.
- Values operator-authored inside an ALLOWLISTED section are copied as written. They are operator configuration, not platform credentials; the platform credentials (database URL, model key, egress allowlist, control-plane) never enter the child.
- Tool results still carry their status as text (see the remaining-work note below); the terminal verdict of a turn no longer depends on it.

**Release gate for r25:** no finding is open on a production path. No finding is marked OPEN.

## Round 26 — shared Harness park/resume, question channel, whole-turn budget, composite chains

Scope of this round (W8 execution plan A→B→C→D→E→F):

- **A. Park/resume.** An approval that needs a human raises `HarnessPaused` out of the shared tool loop WITH the loop's checkpoint (messages incl. AI tool calls and reasoning fields, the paused call, the calls after it, the loop counters, the consumed budget). The top-level turn persists the ask and the checkpoint through `pause_approval` (`checkpoint_z`, compressed, 8 MiB decompressed cap). Resume runs `_prepare_resume`: the approved call executes once through the parent journal (at-most-once), its outcome becomes the tool result, and `Session.prompt(harness_resume=…)` → `AgentV2.resume_harness_turn` continues the ORIGINAL loop to Final Answer. The original prompt is never replayed. Journal `completed`/`unknown` on re-claim → `recovery_required`; a parked turn with no resumable record → `recovery_required` (`unresolvable`), never a fresh turn.
- **B. Question channel.** The confined question broker parks one question (`question.requested` event + durable row). `GET /questions` merges durable pending questions with the in-process list; `POST /questions` answers durable rows through `answer_question` (option-value validation, run must be `waiting_approval`), the run becomes claimable, and `consume_answered_question` hands the answer to exactly one claimant. Multi-question batches on this channel are refused by the tool (`single_question_only`) with an explicit "one question per call" answer.
- **C. Whole-turn budget.** `AgentV2.run` and `resume_harness_turn` run under `_under_turn_budget`: execution time only (a parked turn exits its process; the checkpoint carries the consumed time), extensions asked from the shared `timeout_decision` engine, bounded by `turn.max_extensions` and `turn.hard_cap_seconds`, refusal cancels the work. The drain's 900-second outer `wait_for` is removed; `RXYCODE_WORKER_RUN_TIMEOUT` is no longer read. The lease alone is never treated as progress.
- **D. Configuration.** Construction instead of scrubbing (see r25 above). Tool-result status: the terminal verdict of a resumed turn is the child's result file (run/status/recovery), not stdout text; the approved-call outcome text is passed to the model unchanged. Full structured status (exit code, error class) for every tool result in the Harness loop is NOT done in this round (see remaining work).
- **E. r25.** See above.
- **F. Composite chains.** `tests/web/w8/test_w8_chain_composite_db.py`:
  - chain 1: a Build turn edits a file → the write parks with its checkpoint in Postgres → approval → a FRESH agent instance (restarted worker) claims the run → the approved write executes once → the loop reads the file back → Final Answer; a duplicate resume reuses the journal and never recreates the file.
  - chain 2: an unknown write (reserved, never completed) → `recovery_required`, nothing is retried.
  - Substitution at the process seam: the AF_UNIX hop is an in-process channel bound to the REAL parent handlers (packed exactly as the wire packs), and the OS sandbox is not run on this Windows host.

**Verification (this round).** `tests/web/w8` + `tests/test_config/test_timeouts_registry.py`: `166 passed, 3 skipped` (the 3 skips are bwrap/userns and AF_UNIX on Windows). `tests/test_core`+`tests/test_tools`+`tests/integration` subset (session/question/timeout/harness/approval/build_workflow): `333 passed`, 2 failures that are pre-existing on HEAD (`test_shell_output_capture::test_pipe_read_failure_…`, `test_idle_recycle_real_agent`). ruff: clean on the touched modules.

**Open — NOT done, NOT waived.**
1. ~~Deployed compose drain stall~~ — RESOLVED, see Round 27.
2. ~~Tool-result status as structured data~~ — RESOLVED, see Round 28.
3. Multi-question durable questions (one question per parked call is supported).
4. `tests/web/w2`, `w3`, `w4`, `w5`, `w6` non-W8 failures in the full web run are environmental or pre-existing on this host (shared containers, GUI, websockets, browser handoff); not attributed to this round, not re-verified against HEAD line by line.

## Round 27 — confined-turn self-deadlock: egress relay moved off the agent loop

**Symptom.** On this branch the deployed compose run (`test_w7_c05_integration`) stayed `leased` forever: claim → re-claim loop, child never exited, killing the child let the parent settle `failed` instantly. On HEAD the same run failed early at `agent_started` because the confined child died during config load (`api_key_env` unresolvable) — it never reached the model call, so the latent defect was invisible there.

**Root cause (thread stacks + socket queues, not inference).** The confined child's AgentV2 event loop synchronously called `_estimate_tokens` → `count_tokens` → `tiktoken.get_encoding("o200k_base")`. The BPE vocabulary is not shipped in the image, so tiktoken downloaded it with `requests` through the configured `HTTPS_PROXY` (the child's loopback egress relay). The CONNECT request sat in the accepted socket's receive queue: relay `_pump`/`_bridge` coroutines run on the SAME asyncio loop that was synchronously blocked inside tiktoken, so the relay could never forward the request it was supposed to serve. `requests` has no default timeout — a self-deadlock. Parent-side proof: a manual CONNECT to the same `net.sock` got `HTTP/1.1 200 Connection Established` instantly; the parent egress path was never the problem.

**Fix.** `netrelay.start_relay` now owns a dedicated daemon thread with its own asyncio event loop. The relay is the confined child's network lifeline; it must not share fate with the agent loop, which legitimately performs synchronous blocking work (tiktoken downloads, `requests`, anything non-async). `drain.py` calls it synchronously and closes the handle on turn cleanup — no `wait_closed()` await on the agent loop. The boundary itself is unchanged: private netns, loopback listener, parent-side allowlisted egress, credential injection still upstream-only.

**Deployed validation.** Manual repro stack (same compose env): run `60430262…` claimed, relay kept pumping while the agent loop was free, the configured endpoint's dead upstream produced bounded 502 retries → `recovery_attempt` events → terminal settle with `agent_done` + `usage.updated`. Thread dump after the fix shows the relay thread parked in its own `selectors.select` while the main loop idles in a separate `select`. `test_w7_c05_integration` on the full stack: PASSED.

**Test-env convergence (why the env changed).** With `RXYCODE_LLM_BASE_URL=http://127.0.0.1:9` the gateway answered 502, which `_is_transport_retryable` classifies TRANSIENT → exponential retries (bounded by the turn budget, but minutes — outside the test window). With no endpoint at all the turn fails `No model configured` before `agent_started`. The test now points the endpoint at the stack's own `api:8000`: a REAL configured upstream, reached through relay + gateway + a real upstream connection, answering a real HTTP 404 → PERMANENT → the turn fails at the real boundary in seconds, having journaled `agent_started`. No stub LLM; the exercised path is strictly more end-to-end than the refused-port variant.

**Residual honesty notes.** The synchronous-network-call class still exists in principle: any blocking call inside the confined child now reaches a relay that stays alive on its own loop and is governed by the egress policy — refused hosts get an instant 403, allowed ones a real hop. It can no longer freeze the relay itself. The unit regression (`relay_pumps_while_agent_loop_is_blocked`) is AF_UNIX-dependent and skips on Windows; Linux/compose is the authoritative proof.

## Round 28 — structured tool-call outcomes replace stdout-prefix guessing in the loop

**Change.** The orchestrator now records one ``ToolEvidence`` per call keyed by ``call_id`` (``_current_call_id`` contextvar bound at ``_execute_tool_gated``/``_invoke_and_finish`` so every ``_finish`` site — denial, timeout, exception, journal refusal — stamps it without new parameters). ``call_outcome(call_id)`` exposes it. ``AgentV2`` keeps ``_tool_call_outcomes`` and the loop verdict is ``_tool_is_error(call_id, text)``: ``failed`` is an error, ``rejected``/``dry_run``/``succeeded`` are not — except ``approval="not_found"`` (the historical ``[error: tool ... not found]`` shape stays an error). The ``[error`` text prefix remains ONLY as the no-record fallback (call sites with no call id, results produced off the orchestrator path, journal-reused texts — the durable journal stores outcome text only). The resumed approved call carries the recorded ``{status, executed, exit_code, approval}`` on the resume payload, so the continued loop judges it structurally too. Fallback spans use the recorded status instead of ``trace_status_for_result`` when a record exists.

**Explicitly unchanged.** Model-facing result text is byte-identical; ``_tool_output_is_error`` still classifies the model's own answer text for cache eligibility (that is text, not a tool outcome); ``_tool_call_failed`` still classifies journal-stored text on the reuse path; tools that return error-shaped bodies as their VALUE still classify by content at the evidence seam — that is the last remaining text-derived verdict, and it is computed once at the boundary rather than re-derived per consumer.

**Tests.** ``test_w8_c01_call_outcome_is_recorded_structurally`` (real orchestrator: succeeded/rejected/not-found, unknown id → None), ``test_w8_c01_tool_is_error_prefers_structured_status`` (mapping table incl. the not-found exception and the no-record fallback), the replay tests now assert the structured outcome rides the return, and the composite DB chains + full W8 suite re-verify end to end (168 passed, 4 skipped — skips are AF_UNIX/bwrap on Windows). The deployed compose run re-verified on Round 27's stack.

**Deployed re-verification (post-``e9e22768``).** ``test_w7_c05_integration`` re-run on the full compose stack: **PASSED** in 584 s (claim, restart/reclaim, stale-lease recovery, durable data). The first re-run failed in ``_wait_stack`` after 1510 s for an environmental reason, not code: containers could not reach pypi.org (``SSL: UNEXPECTED_EOF_WHILE_READING`` on every package fetch; deb.debian.org intermittently 502), so the one-shot ``migrate`` exited 1 and ``.migrate-done`` never dropped. Confirmed from inside the api container: pypi.org fails, tsinghua/aliyun mirrors answer. ``infra/compose/compose.yaml`` now passes ``PIP_INDEX_URL`` through to the three pip-bootstrap services (default ``https://pypi.org/simple`` -- unset means unchanged); the passing run used ``PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple``. npm (webbuild) was never affected.
