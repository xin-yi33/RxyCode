# WEB-W7-C06 handoff — 发布验证矩阵、用户文档与完整面试案例

Audited commit: `<filled after the audited fix commit>`
Audit: Codex session `01a140a7-2cc1-7f61-bdab-2af627f08e80`, model `gpt-6.1-sol`, reasoning `high`.

## What shipped

- README `## 🌐 RxyCode Web` — 13-row status matrix; every `shipped` row cites an existing `evidence/web/WEB-W?-C??` dir + test file; blocked rows name the blocker (no Playwright / no anonymous run entry / no hosted URL).
- `docs/product/web-user-guide.md` — install/env/compose bring-up, login/onboarding, permission×target truth table, error dictionary, FAQ, honest limits.
- `docs/architecture/web-system-design.md` — diagram + ADR chain W0→W7 with evidence links; residual risks.
- `docs/portfolio/rxycode-web-case-study.md` — cited metrics only; pitfalls (bind mounts, GBK decode, bwrap loader/prefix binds, approval face, ledger loss) all trace to evidence; TBD placeholders kept.
- Tests: unit contract (matrix↔artifacts on disk + docs git-trackable), unit negative (uncited metric fails; placeholder required), module integration (real `create_app` unauth refusal surface on dev PG).

## Evidence

`red.txt` (pre-docs contract failure), `green.txt` (3/3 + leg descriptions), `NOTES.md` (deviations + rulings), `self-audit.md`.

## Status

- 3/3 focused tests green; ruff + ruff-format clean on new files.
- Browser E2E and hosted-demo legs: BLOCKED/planned — labeled, not claimed.
- `.gitignore` negations (`docs/architecture`, `docs/portfolio`) per nested-plan ruling `34e5d92`.


## FINAL — audit r5 verdict (2026-10-19)

Same Codex session `01a140a7-2cc1-7f61-bdab-2af627f08e80`, commit
`d5af8602`:

    VERDICT: NO_REMAINING_PROBLEMS

Auditor-verified: ledger-failure states + fixed 12h TTL match the
implementation; all 11 shipped rows reference real evidence dirs + test
files; both blocked rows parsed; metric/citation checks hold; deploy
commands and demo paths are executable as written.
