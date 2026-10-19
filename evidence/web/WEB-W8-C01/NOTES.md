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
