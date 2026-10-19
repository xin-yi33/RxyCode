# WEB-W8-C01 handoff — state before first audit

Branch: feat/rxycode-web (no push, no PR — same as W7).

## Landed in this card's working set

- `packages/rxycode-worker/src/rxycode_worker/drain.py` — two trust
  domains (parent drain / confined turn), `_execution_gate` Full
  decoupling, `_ctl_handlers` (tenant/run/lease-bound ops), `_CtlApproval`
  (channel broker → durable ask → `_RunPaused`), durable call-id
  derivation (`call_[0-9a-f]{32}` + `att_[0-9a-f]{32}`), `_resume_turn` +
  `_execute_approved_call` (exact-call replay, grant broker,
  `safety.enabled` forced), `_merge_turn_config` (write-domain merge +
  credential scrub + base_url rewrite), `_task_turn_env`/`_writable_domain`,
  ctl+egress lifecycle in `execute_run`, paused early-return, journal-truth
  settle (`completed`/`unknown` → succeeded/`recovery_required`).
- `ctl.py` (new) — CtlServer unix socket + sync TurnChannel client.
- `egress.py` (new) — filtered CONNECT/forward proxy + ModelGateway
  (parent-injected auth headers), allowlist, `_ip_blocked` covering
  private/loopback/link-local/multicast/reserved/non-global + ports.
- `netrelay.py` (new) — in-child lo bring-up + loopback↔unix relay.
- `agent_events.py`, `telemetry.py` — emitter transport seam (channel
  mode never imports the platform store).
- `supervisor.py` — `commit_terminal` accepts `recovery_required`.
- `packages/rxycode-runner/.../userns.py` — `--unshare-net` always,
  `rw_binds`, tmpfs `overlay_roots`, mount-order fixes.
- `packages/rxycode-server/.../approvals/service.py` — `source_call_id`
  param + payload passthrough; `decide_approval` stale guard
  (`waiting_approval` required).
- `infra/compose/compose.yaml`, `docs/architecture/web-system-design.md`
  — Full semantics comments updated.
- `tests/web/w8/` — conftest (shared PG), 17 unit + 6 module tests.
- `evidence/web/WEB-W8-C01/` — this file set.

## Test state

- tests/web/w8: 22 passed / 1 skipped (AF_UNIX on Windows).
- tests/web/w7 regression: 71 passed, 1 deselected (port 56390 held by a
  local IDE process — pre-existing environment flake).
- ruff clean; py_compile clean; git diff --check clean.

## Open items for the audit session

- Same Codex session `01a140a7-2cc1-7f61-bdab-2af627f08e80`,
  `gpt-6.1-sol` high, until `VERDICT: NO_REMAINING_PROBLEMS`.
- The compose-level live turn (real bwrap + real model) still needs
  `RXYCODE_LLM_*` — same BLOCKED leg as W7; honestly recorded, not faked.
