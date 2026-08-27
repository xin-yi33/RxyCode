# GX2-H self-audit

- Probe: `approval/mode_set` absent on feat/phase-g-frontend schema → path B BLOCKED_PREREQUISITE
- No mock RPC. `buildModeSetRequest` returns missing-list.
- UI presets ask/auto/full map onto B7 policies only.
- ApprovalCard is inline, actions allow/deny/cancel only.
- High-risk (DANGER / rm / delete / .env) still modal; card/modal mutex by request_id + risk.
- Five states covered. typecheck + ApprovalCard.test.ts green.
