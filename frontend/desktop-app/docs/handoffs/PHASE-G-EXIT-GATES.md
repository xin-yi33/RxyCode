# Phase G §7 机械门真实输出

日期：2026-08-19
分支：feat/phase-g-frontend

## git diff --check

无输出（通过）。

## python -m pytest tests/test_protocol -q

`6 passed, 7 warnings in 0.46s`

`tests/test_projects` / `test_threads` / `test_execution` / `test_approval` / `test_review` / `test_file_preview` / `test_worktrees` / `test_settings` / `test_capabilities` / `test_release`：**BLOCKED_PREREQUISITE**（目录不存在，不 mock）。

## frontend/protocol-client bun test

`29 pass / 0 fail`（handshake、errorModel、stdio pipe）。

## cd frontend/desktop-app && npm run typecheck

通过（typecheck:node + typecheck:web）。

## npm test

`337 pass / 0 fail`。覆盖：

- unit/component：timeline/thread/approval/settings/i18n/session list
- IPC：`src/main/ipc-allowlist.test.mts` 未知方法拒绝
- E2E 契约：CDP harness、screenshot capture、appserver.integration
- 视觉：`tests/visual/phaseg-visual-states.test.mts`

本卡修复：

- H1 断言改为 `webPreferencesSafe` + `web-preferences.ts` 的 DC-J7 字面量
- composer geometry 正则接受 `overflow` 与 z-index 20，仍要求 flex 底栏不覆盖 transcript

## npm run build

electron-vite production 通过：

- `out/main/index.js` 613.46 kB
- `out/preload/index.js` 2.88 kB
- `out/renderer/assets/index-Cfn0Ul_e.js` 833.74 kB
