# WEB-W10-C02 handoff notes — production deploy + public demo

## What shipped

| File | Role |
|------|------|
| `infra/compose/compose.prod.yaml` | production overlay: prebuilt images, prod env, worker replicas (≤3) |
| `infra/scripts/build-images.ps1` | production image build (api / worker / web) |
| `docs/deploy/OPS-LOG.md` | deployment record: timeline, smoke results, manual browser E2E, operational notes |
| `docs/deploy/web-runbook.md` | bring-up / seed / migrations / certs / logs / upgrade / rollback |

## Verified behavior

- W10-D1: all three images built; api container smoke — `/api/v1/version` reports commit + image build stamp, `/api/v1/auth/capabilities` and `/api/v1/auth/csrf` return 200.
- W10-D3/D4: live deploy on a CentOS 7.6 VM; prod overlay, alembic head, queued run drained by the deployed worker.
- Public demo reachable at `https://rxycode.xyz`; manual browser E2E covered visitor shell, login modal, BYOK CRUD, device-lock takeover, cancel, file panel.
- Covered by `tests/web/w9/test_version.py` (image build stamp on `/api/v1/version`) and `tests/web/w9/test_e2e.py` (browser E2E suite).
- Recorded in `docs/release-notes/CHANGELOG_v1.4.4.md` W10-D1/D3/D4/D5 sections.
