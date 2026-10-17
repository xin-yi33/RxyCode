# WEB-W7-C01 handoff — 认证/越权/Prompt Injection 全域安全评审

## Scope verified (reviewed, not modified)

| Surface | Control observed |
|---|---|
| `api/auth.py` | `current_record` → 401 missing/expired/forged session; `require_write` → 403 wrong Origin or missing CSRF pair; local login cloud-forbidden; GitHub OAuth state+nonce+PKCE |
| `api/projects.py` / `sessions` | all rows filtered `tenant_id == record.tenant_id`; forged `tenant_id` in body ignored; 404 cross-tenant |
| `api/runs.py` / `sse.py` | run events `/api/v1/runs/{id}/events` tenant-filtered → 404 |
| `api/artifacts.py` | list → 403 `ARTIFACT_FORBIDDEN`; download via `read_download` tenant+HMAC signature |
| `api/approvals.py` | `_owned_run` → 404 cross-tenant |
| `api/terminal_ws.py` | `_owns(tenant_id, user_id)` on read and WS close-1008 for foreign |
| `devices/gateway.py` | invocations → 404 other-tenant/unpaired; `list_for(tenant_id)`; pairing `DEVICE_OWNED` reject; token digest match |
| `previews/proxy.py` | `current_record` + per-tenant+owner grant mirror `_same_caller`; missing grant → 403 |
| `grant_store.py` | GRANT_REQUIRED / SESSION_MISMATCH / RUN_MISMATCH / CAPABILITY_MISMATCH / WORKSPACE_MISMATCH / GRANT_EXPIRED / GRANT_REVOKED; `_within` resolves+rejects escapes; `evaluate` audits every call |
| `devices/grants.py` | `GrantMirror` = browser view only; `forge_full` writes only the mirror — real store unchanged |
| `utils/safe_http.py` | refuses credentials, non-http(s), private/loopback/link-local/single-label hosts (SSRF) |
| `core/safety/audit.py` + `log/log_helpers.py` | `sanitize_args` masks sensitive keys; `redact_sensitive` masks sk-/ark-, Bearer, api_key/token/secret/password values |
| `utils/shell.py` | workspace/docker mode: workdir outside `execution.workspace_root` raises — no host fallback |

## Finding fixed this card (P1)

`core/safety/policy.py` `find_bash_disallowed_write_paths`: the payload scrubber
`-(?:Value|Content)\s+"..."` matched the `-Content` inside the verbs
`Set-Content`/`Add-Content`, deleting the target path before the mutating-target
regex ran. `Set-Content "C:\Windows\Temp\x" "y"` therefore bypassed the
write-path gate entirely — under `permission_mode="full"` it ran with no
approval. The observed RED is an unblocked execution attempt: the command
passed the gate and reached cmd, which failed it only because `Set-Content`
is not a cmd builtin; a PowerShell-capable shell would have written the file.
Fix: require the `-` not be preceded by a letter
(`(?<![A-Za-z])`), so only real `-Value`/`-Content` *arguments* are scrubbed.
`Set-Content report.txt -Value "C:\..."` still correctly passes (relative
target). Ruling rows added to the card whitelist table.

Second-round audit findings, same root function and WS surface:

- **Executable here-strings**: `@"..."@` was erased whole, hiding
  `iex @"Set-Content C:\x"@` and `$p=@"..."@; iex $p`. Delimiters are now
  stripped but contents stay visible to the scan.
- **Missing verb + env paths**: `Clear-Content` added to mutating verbs;
  `$env:X`, `%X%`, `$HOME`, `~` targets are expanded before the whitelist
  check (unresolvable forms fail closed).
- **Word boundary**: verbs now match on `\b...\b` — `rm` inside "harmless"
  no longer false-blocks report text.
- **Terminal WS Origin**: `stream_terminal` now compares `Origin` against
  `allowed_origins` and closes 1008 `ORIGIN_FORBIDDEN` before any session
  work. Session cookie is `samesite=lax`, which already mitigates cross-site
  WS, but the Origin check closes the same-site-hostile-origin gap.

## Tests (all real backends)

- `test_w7_c01_contract` — two real GitHub tenants (MockTransport only at the
  github.com boundary, same as W2-C02), real Postgres; attacker 404/403 on
  project, session, run events, artifact list+download, device invocation;
  forged `tenant_id` ignored; anonymous → 401; missing CSRF → 403.
- `test_w7_c01_negative` — `GrantMirror.forge_full` + empty `GrantStore` →
  `_run_remote_full` raises `GRANT_REQUIRED`, audit.jsonl records
  `allowed:false`, no file written.
- `test_w7_c01_integration` — real `http.server` page with injected prompt;
  `validate_public_url` refuses the private URL; injected `Set-Content`
  absolute write refused even under `full`; `Add-Content` and
  powershell-wrapped variants refused; unregistered tool → `not found`.
- `tests/web/security/test_threat_model.py` — 6 attack cases: cross-tenant
  workspace/approvals/preview, forged+expired session & foreign Origin,
  injected grant scope replay (RUN/SESSION/CAPABILITY/WORKSPACE mismatch +
  audit), audit-log secret redaction, SSRF URL battery, sandbox workdir escape
  fail-closed.

## Results

- red.txt: `2 failed, 7 passed` — the integration failure was the real P1
  bypass; the second was a test-helper unpack bug (fixed).
- green.txt: `9 passed`.
- Regressions: `tests/test_safety_policy.py` + `tests/test_cache/test_s1_s2_split.py`
  + `tests/test_cache/test_stable_prefix.py` → 168 passed, 2 skipped
  (documented pre-existing skips); `tests/web/w4/test_w4_c05_*` → 3 passed.
- Ruff on changed files: clean.

## Risk acceptance / open items

- "真实 Demo compose 网络" identity audit: **BLOCKED_PREREQUISITE** — no
  docker-compose target exists yet (Compose is W7-C05's deliverable). The same
  identity/authz checks ran against the real FastAPI + Postgres stack
  in-process; only the github.com edge is transport-mocked.
- E2E-SECURITY-01 public-demo attack test: **BLOCKED** — requires the W7-C05
  deployed demo; no mock substituted.
- `bash_tool` risk level unchanged; no `RiskLevel` lowered.
- Audit file is append-only best-effort by design (never breaks a run) — kept.

## Audit verdict

- gpt-6-luna max, Codex session 01a140a7-2cc1-7f61-bdab-2af627f08e80, audited
  parent commit a6e8fa56f3bf3324f26ba3b5dbd6a24dbd943183 and returned
  VERDICT: NO_REMAINING_PROBLEMS (w7c01-audit-30.json).
- Rounds 1-29 returned PROBLEMS. Each finding was fixed or adjudicated in its own
  commit; the commits from 174f345c to a6e8fa56 are on feat/rxycode-web.
- Round 20 switched the write-path gate to a fail-closed contract (nested ruling
  33d16493, extended by d2586fcd). From round 24 on, the gate was accepted against
  the frozen corpus in tests/web/w7/test_w7_c01_module.py (nested rulings c9dc4d86
  and f011d1cc). Full mode is the user-confirmed lifting of the sandbox within the
  current OS account, so the gate there is best-effort, not a security boundary.
- Known gate limitations (non-blocking) are listed in self-audit.md.
- Follow-up cards, in order after W7-C02..C06: B (normal mode: gate hits go to
  approval instead of rejection) and C (Windows kernel write isolation; OS sandbox
  switched by permission mode on all three platforms).
- Browser E2E stays BLOCKED. No jest. No screenshots. The Postgres-backed tests
  were run by the implementer (green.txt); the auditor judged them from code and
  assertions because its sandbox is read-only.