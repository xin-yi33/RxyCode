# WEB-W7-C06 notes — 发布验证矩阵、用户文档与完整面试案例

## What shipped

| File | Role |
|------|------|
| `README.md` | new `## 🌐 RxyCode Web` section: status-tagged capability matrix (shipped/experimental/planned/blocked) — every shipped row cites an existing evidence dir + test file |
| `docs/product/web-user-guide.md` | NEW — install/env vars, onboarding/login, permission-mode×target table, error dictionary, FAQ, honest limits |
| `docs/architecture/web-system-design.md` | NEW — component diagram + ADR decision chain (W0-C04 → W7-C05) with evidence refs; residual-risk list |
| `docs/portfolio/rxycode-web-case-study.md` | NEW — scale/audit/perf numbers with citations, real pitfalls, technical-tradeoff talking points, 2-min demo script |
| `tests/web/w7/test_w7_c06_unit.py` | contract (matrix↔evidence↔tests on disk; blocked rows name blockers; docs trackable) + negative (uncited metric → fail; placeholder required) |
| `tests/web/w7/test_w7_c06_module.py` | real `create_app` on dev PG: the unauthenticated refusal surface end-to-end (401 reads / 403 writes / forged cookie 401) |
| `evidence/web/WEB-W7-C06/` | this dir: red.txt (pre-docs failure), green.txt, NOTES, handoff, self-audit |

## Deviations / honest labels

- `.gitignore` gained `!docs/architecture/` + `!docs/portfolio/` negations — card-sanctioned ruling committed in the nested plan (`34e5d92`), same pattern as `!docs/product/`/`!docs/deploy/`.
- The card's "未登录浏览器完成受限真实云任务" leg has NO anonymous run entry in the codebase (runs API = GET/cancel/steer only, all authed). The module test asserts the actual security truth — unauthenticated refusal — and the browser leg is labeled `BLOCKED`, not fabricated. Ruling recorded in the card.
- README matrix deliberately lists "anonymous visitor cloud run" and "browser E2E" as `blocked` rows with named blockers — the matrix itself is regression-tested against silent claims.
- Case-study metrics are all cited to evidence files/test files/commits; unmeasured cells keep `TBD` placeholders (the negative test fails if a number appears without a citation).

## Quick verify

```bash
python -m pytest tests/web/w7/test_w7_c06_unit.py tests/web/w7/test_w7_c06_module.py -q
# 3 passed in ~1s (module uses the shared rxy-w2c01-pg dev container)
```


## Audit r1 remediation (2026-10-19, same Codex session)

Five findings, all fixed in pending commit:

- **Install docs claimed one-command auto-seed**: `reposync` only WAITS
  on `.rxy-sync-done`; the tar seed is mandatory. user-guide step 4/5 and
  the case-study demo script now show the real two-step sequence;
  README row reworded "two-step" instead of "one-command".
- **Demo path impossible as written**: cloud-mode compose rejects local
  login (403) and there is no run-creation HTTP endpoint. Guide now
  states the GitHub-OAuth prerequisite (`RXYCODE_GITHUB_*`) and the
  service-level seeding path; case-study demo script carries a real
  `create_run` seed snippet via `docker compose exec api`.
- **Shipped rows conflated standalone vs deployed**: approvals row now
  notes the deployed worker has no approval-answer channel; tenant
  fs/net isolation row now scopes net isolation to the standalone path
  (deployed turn needs DB/LLM egress).
- **Contract parser skipped `blocked: reason` rows** (exact-match bug):
  `_row_status` prefix-matches and the contract asserts ≥1 blocked row
  is actually parsed.
- **Negative test missed CN/token metric formats and dead citations**:
  `_METRIC` gains 行/张/轮/个/项/分钟/tokens/commits units;
  `（证据: …）` citations must resolve to ≥1 existing path; case-study
  token counts re-pointed to self-audit.md (which contains them) and
  stale numbers corrected (drain 2400 行, 17 轮/60 条审计).


## Audit r2 remediation (2026-10-19, same Codex session)

Four findings, all fixed in pending commit:

- **Mixed working dirs/compose files in docs**: every command now runs
  from the repo root with explicit `-f infra/compose/compose.yaml
  -p rxyweb` (root has an unrelated legacy `docker-compose.yml`).
- **Seeded demo tenant unreachable by the logged-in user**: demo script
  rewritten into two honest paths — OAuth login → `/api/v1/me` → seed
  the run into YOUR tenant/session, or (OAuth absent) an explicitly
  backend-only psql inspection path. No more fake `demo-tenant` SSE.
- **Finding total corrected**: 60 → 63 (per-round counts in NOTES.md:
  8+7+5+5+5+3+2+3+3+3+3+3+4+4+4+1).
- **`input/output tokens` metric format**: `_METRIC` now accepts an
  optional input|output|total qualifier before `tokens`.


## Audit r3 remediation (2026-10-19, same Codex session)

Two findings, fixed in pending commit:

- **Backend-only psql leg picked the wrong stack**: now uses the same
  `-f infra/compose/compose.yaml -p rxyweb` form plus the configured
  `psql -U rxycode -d rxycode` identity.
- **Permission table overpromised sandboxing on the local runner**:
  `LocalNativeBackend.attach_sandbox` raises `SANDBOX_FORBIDDEN` — the
  native run backend's real boundary is the ask/full approval profile.
  The table cell now says so explicitly and separates the shell-surface
  OS sandbox (`execution.os_sandbox` auto-toggle) from the run backend.


## Audit r4 remediation (2026-10-19, same Codex session)

Two findings, fixed in pending commit:

- **Ledger-failure terminal state overstated**: cancelled runs with a
  failed ledger write land `recovery_required` (confirm_cancel
  effects_known=False) with pending reconciliation — not `failed`.
  Guide and design ADR now qualify both branches.
- **Session TTL described as sliding**: it is a fixed 12h TTL from
  issuance (`AuthRecord.created`), no sliding renewal — guide corrected.


## FINAL — audit r5 verdict (2026-10-19)

Same Codex session `01a140a7-2cc1-7f61-bdab-2af627f08e80`, commit
`d5af8602`:

    VERDICT: NO_REMAINING_PROBLEMS

Auditor-verified: ledger-failure states + fixed 12h TTL match the
implementation; all 11 shipped rows reference real evidence dirs + test
files; both blocked rows parsed; metric/citation checks hold; deploy
commands and demo paths are executable as written.
