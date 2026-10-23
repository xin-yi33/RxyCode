# WEB-W8-C01 self-audit / manual review

Audited commit: `<filled after the audited fix commit>`
Final verdict: `<filled by the Codex audit>` (session `01a140a7-2cc1-7f61-bdab-2af627f08e80`, `gpt-6.1-sol` high).

## Audit history

| round | verdict | findings fixed |
|---|---|---|
| r1 | (pending — submit after commit) | — |

## Verified by hand

- `_execution_gate("cloud:t-1:w1", "full")` → `full_auto`; cross-tenant
  targets refuse; non-cloud placements fail closed (unit tests).
- `build_sandbox_argv` shape: `--unshare-net` unconditional, private
  `/tmp` tmpfs precedes binds, ctl dir rw-bound, workspace rw-bound,
  `/repo`+config-src ro-bound, overlay roots on existing dirs.
- `_CHILD_ENV_PASS`: no `RXYCODE_WEB_DATABASE_URL`, no `RXYCODE_API_KEY`,
  no `RXYCODE_LLM_BASE_URL` (the gateway URL is injected per-run).
- `_merge_turn_config` on a real yaml: `api_key_env`/`api_key_secret`
  removed from every model entry, `api_key` forced to `confined`,
  used-model `base_url` → `http://127.0.0.1:<egress_port>`,
  `safety.enabled` forced true, `execution.os_sandbox.enabled` false.
- `egress.evaluate`: loopback/private/ULA/link-local/multicast/reserved/
  unresolvable refused; non-80/443 refused; allowlist admits in-cluster
  endpoints; rebinding-safe (parent resolves once, connects to IP).
- `_gateway_head`: Host rewritten, Authorization/x-api-key/api-key
  injected parent-side, every credential-shaped child header dropped.
- Approval chain on real Postgres: ask parks run (`waiting_approval`,
  lease NULL, `approval.requested` with verbatim arguments +
  `source_call_id`), approve → `pending`, decide-twice → stale,
  reject → `cancelled`, cancel-then-approve → `ApprovalStale`.
- `_execute_approved_call` on the real orchestrator+journal: bash write
  replays once; second call → `reuse` (file unchanged); a pending
  journal entry → `journal-uncertain` RuntimeError → `recovery_required`.
- `_RunPaused` is `BaseException` — no `except Exception` in the
  orchestrator can swallow it; the turn top-level catches it explicitly.

## Honestly out of scope on this machine

- bwrap/userns themselves are Linux-only; their argv/env/mount shape is
  asserted structurally, the live kernel boundary runs in the deployed
  worker container (compose) — no Windows substitute was invented.
- The full drain→claim→spawn→Session loop against a live model needs
  `RXYCODE_LLM_*` credentials (same BLOCKED leg as W7); the service-level
  chains above cover every code path except the kernel enforcement.
