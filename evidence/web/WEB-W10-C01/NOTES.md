# WEB-W10-C01 handoff notes — BYOK key vault + per-run model snapshot

## What shipped

| File | Role |
|------|------|
| `packages/rxycode-server/src/rxycode_server/byok/crypto.py` | AES-256-GCM key vault; secrets are encrypted before they touch the database |
| `packages/rxycode-server/src/rxycode_server/byok/resolver.py` | per-user credential resolution; `RXYCODE_BYOK_ENFORCE=1` opts deployments into BYOK-only mode |
| `packages/rxycode-server/src/rxycode_server/api/models.py` | BYOK CRUD endpoints |
| `apps/web/src/` BYOK settings + composer | user key management UI + per-task model picker; visitor shell entry |
| `packages/rxycode-worker/src/rxycode_worker/` | worker resolves the run's model snapshot from BYOK or platform config |

## Verified behavior

- `cryptography` is a hard dependency of `rxycode_server` (module-level import in `api/models.py`); the compose `api` image installs it explicitly.
- Covered by `tests/web/w9/test_byok_api.py`, `tests/web/w9/test_byok_crypto.py`, `tests/web/w9/test_byok_runs.py`, `tests/web/w9/test_byok_worker.py`.
- Recorded in `docs/release-notes/CHANGELOG_v1.4.4.md` W10 BYOK 后端/前端/生产部署 sections.
