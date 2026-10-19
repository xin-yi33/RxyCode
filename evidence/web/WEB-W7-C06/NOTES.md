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
