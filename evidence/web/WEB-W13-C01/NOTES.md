# WEB-W13-C01 handoff notes — device bridge (cloud → paired local host)

## What shipped

| File | Role |
|------|------|
| `packages/rxycode-server/src/rxycode_server/devices/gateway.py` | pairing-code issuance, WSS device endpoint, `/api/v1/devices/{id}/invocations` dispatch, approval inbox |
| `packages/rxycode-server/src/rxycode_server/devices/grants.py` | device-side tool grant mirror (`confirm_all` / `full` modes) |
| `rxycode connect` CLI | local runner dials out over WSS and executes device-side tools inside the paired workspace root |

## Verified behavior

- Live E2E on a real Windows host (2026-10-22): pairing code → `rxycode connect` online → `POST /devices/{id}/invocations` (`tool=bash`) → `confirm_all` approval surfaced in `/approvals/pending` → approved → file created/rewritten/read back on the host (`D:\rxy-device-workspace\proof.txt`). Workspace-root escape was refused by the device-side sandbox.
- Two real bugs fixed during the live run and recorded in CHANGELOG_v1.4.4 W13 section: standalone invocations lacked `call_id`/`attempt_id` (500 on journal path), and `core/session_runtime.py` relative imports broke the flat layout used by the api image.
- Covered by `tests/web/w4/test_w4_c05_module.py` (`/devices/pairings` + `/devices/{id}/invocations` over the gateway) and `tests/web/w9/test_rate_and_device.py` (device lock).
- Known gaps still open: device token is not persisted across `connect` restarts; no web UI panel for pairing/devices; agent runs do not yet auto-route tools to a `local:<device>` target.
