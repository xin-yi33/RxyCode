# WEB-W7-C03 Agent Eval Report

- generated: 2026-10-18T08:59:04.368996+00:00
- model: deepseek-flash
- code_commit: 606d76654015bdbf93b8753b07d2959af6ce9196
- taskset_sha256: b5aa349372abf990be262ffa50d7cd6fc8b1b8a2f1dd99821492f8dbaac5c94e
- price_version: 2026-10

## Cells

| cell | attempted | blocked | passed | failed | error | success | p50 (s) | p95 (s) | tok in | tok out | tok total | cost USD |
|---|---|---|---|---|---|---|---|---|---|---|---|
| cli-solo | 2 | 1 | 2 | 0 | 0 | 100.0% | 240.012 | 240.059 | 3349749 | 33493 | 3383242 | 6.76648400 |
| **overall** | 2 | 1 | 2 | 0 | 0 | 100.0% | 240.012 | 240.059 | 3349749 | 33493 | 3383242 | 6.76648400 |

## Mode forcing (manifest)

- `cli-solo`: mode=solo forcing=agent.run-direct

## Abnormal cost rows (>$1/task)

- w7c03-c01-hello [cli-solo]: $3.49609200 via price_table
- w7c03-c02-calc [cli-solo]: $3.27039200 via price_table

Notes: `success` counts passed/(attempted) with failures in the denominator;
`blocked` tasks are excluded from the rate but reported above. Web cost rows
come from `usage_records` (ledger); CLI cost rows are price-table estimates.
## Gate

GATE: FAIL
- cell cli-solo attempted 2 tasks — below the required min_tasks=3
