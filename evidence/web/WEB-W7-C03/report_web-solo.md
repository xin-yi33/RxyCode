# WEB-W7-C03 Agent Eval Report

- generated: 2026-10-18T09:04:57.317355+00:00
- model: deepseek-flash
- code_commit: 606d76654015bdbf93b8753b07d2959af6ce9196
- taskset_sha256: b5aa349372abf990be262ffa50d7cd6fc8b1b8a2f1dd99821492f8dbaac5c94e
- price_version: 2026-10

## Cells

| cell | attempted | blocked | passed | failed | error | success | p50 (s) | p95 (s) | tok in | tok out | tok total | cost USD |
|---|---|---|---|---|---|---|---|---|---|---|---|
| web-solo | 1 | 0 | 1 | 0 | 0 | 100.0% | 243.119 | 243.119 | 2512759 | 21364 | 2534123 | 5.06824600 |
| **overall** | 1 | 0 | 1 | 0 | 0 | 100.0% | 243.119 | 243.119 | 2512759 | 21364 | 2534123 | 5.06824600 |

## Mode forcing (manifest)

- `web-solo`: mode=solo forcing=slash_prefix prefix=/solo

## Abnormal cost rows (>$1/task)

- w7c03-c01-hello [web-solo]: $5.06824600 via usage_records

Notes: `success` counts passed/(attempted) with failures in the denominator;
`blocked` tasks are excluded from the rate but reported above. Web cost rows
come from `usage_records` (ledger); CLI cost rows are price-table estimates.
## Gate

GATE: PASS
