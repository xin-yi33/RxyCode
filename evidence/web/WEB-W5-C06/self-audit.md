# WEB-W5-C06 self-audit

- RED: quotas and scheduler packages were missing. 3 failed in 0.32s. See red.txt. Parent HEAD at RED was f6e167e3.
- First green run: unit 2 passed in 3.84s, module 1 passed in 2.54s. Audit w5c06-audit-1.json then returned VERDICT: PROBLEMS. Admitted runs did not consume quota, create_run did not call the gate, and GC ran only when the test called it.
- After the quota-path fix, audit 2 still returned VERDICT: PROBLEMS because a successful insert never released the worker slot.
- Concurrency is the count of this user's runs that are still active and inside the TTL. Each create_run reads that count from the database. A fresh QuotaGate with an empty capacity list still returns 429 while the row is pending. commit_terminal marks it succeeded, and a different gate then admits the next run. A 1-second TTL ignores an older pending row. Latest unit 2 passed in 9.83s. Module 1 passed in 2.61s. No skip. tests/web/w2/test_w2_c03_unit.py passed with the contract, 3 passed in 10.95s.
- runs.service.create_run calls QuotaGate before insert. A refused call raises QuotaRefused, writes no Run, and does not call the model. Forged headers and claimed_tenant_id do not change the tenant. The stored row's tenant_id is the server argument.
- One admitted run records tokens, preview_fee, and sandbox_fee on run.created. The next create_run returns 429 for task, token, preview, sandbox, or concurrency. Capacity.acquire raises CapacityFull when the caller passes a held count already at the limit.
- Missing credentials, budget 0, or a message whose word count already exceeds the token ceiling returns 429 before the database is opened.
- Two tenants each get a runc container (runsc is not installed). Markers and events are files inside that container. Tenant A cannot read tenant B through the shipped exec path. Independent docker exec sees only that tenant's nonce. Network mode is none.
- A sandbox() that raises calls gc() and docker-rm's the container. A ttl of 1 second arms a timer that calls gc(). The negative test does not call gc(). docker inspect then fails for those ids. The healthy sibling was still running. destroy_all removed it. No rxy-sbx or rxy-w5c06-pg container was left.
- Cold-start p50 and p95 are the nearest-rank percentiles of the measured create durations.
- compose.yaml names postgres:16, redis:7, and minio/minio:latest with healthchecks and privileged false. load_compose refuses privileged true and a service with no healthcheck. docker compose up was not run.
- E2E-CLOUD-04 has no separate harness. The locked integration and negative tests are the parallel-tenant and forced-cleanup process evidence. No browser session. No live model provider. core/ was not touched. Not claimed as 已落实.
- gpt-6-luna max re-audit after the durable concurrency count is not recorded yet. Session 01a140a7-2cc1-7f61-bdab-2af627f08e80.
