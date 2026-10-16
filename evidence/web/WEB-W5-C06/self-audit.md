# WEB-W5-C06 self-audit

- RED: quotas and scheduler packages were missing. 3 failed in 0.32s. See red.txt. Parent HEAD at RED was f6e167e3.
- Unit: 2 passed in 3.84s. Module: 1 passed in 2.54s. No skip. See unit.txt and integration.txt.
- Over task, preview, or sandbox quota returns http_status 429 and a quota.exceeded event for the server tenant and user. Forged x-quota-limit, x-tenant-id, x-user-id, x-budget, and x-preview-fee headers do not change that identity or the limit.
- Missing credentials or a budget of 0 returns 429 before the model callable and before Capacity.acquire. workers and live_ids stay empty. The bad database URL is not contacted on those paths.
- Admitted persistence calls rxycode_server.runs.service.create_run. The locked tests stay on the refusal path, so that database insert was not executed.
- Two tenants each get a runc container (runsc is not installed). Markers and events are files inside that container. Tenant A cannot read tenant B through the shipped exec path. Independent docker exec sees only that tenant's nonce. Network mode is none.
- GC docker-rm's a sandbox whose caller raised after create, and a sandbox whose TTL elapsed. docker inspect then fails. A healthy sibling was still running after that GC. destroy_all removed it. No rxy-sbx container was left.
- Cold-start p50 and p95 are the nearest-rank percentiles of the measured create durations.
- compose.yaml names postgres:16, redis:7, and minio/minio:latest with healthchecks and privileged false. load_compose refuses privileged true and a service with no healthcheck. docker compose up was not run.
- E2E-CLOUD-04 has no separate harness. The locked integration and negative tests are the parallel-tenant and forced-cleanup process evidence. No browser session. No live model provider. core/ was not touched. Not claimed as 已落实.
- gpt-6-luna max verdict is not recorded yet. Session 01a140a7-2cc1-7f61-bdab-2af627f08e80.
