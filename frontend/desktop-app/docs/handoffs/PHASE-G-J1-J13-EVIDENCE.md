# J1–J13 ↔ 完整 F 对应卡

附录 A 映射。每张前端卡引用完整 F 基线（PHASE-G-FRONTEND.md Part 1 §4 已写「对应基线」）。

| J | 前端卡 | 完整 F | 前端 commit | 前端测试 | 后端 pytest |
|---|---|---|---|---|---|
| J1 | H1 | H1 | 93311fa | tests/h1-baseline.test.mts | tests/test_protocol 6 passed |
| J2 | H2 | H2 | 1ff060d | tests/h2-handshake.test.mts + protocol-client handshake/errorModel | tests/test_protocol |
| J3 | H3 | H3 | 458a1d7 | tests/h3-supervisor.test.mts, ipc-allowlist, web-preferences, supervisor 20 次启停 | tests/test_appserver 只读观察 |
| J4 | H4 | H4 | decf5b3 | src/features/projects/projectRegistry.test.mts | **BLOCKED_PREREQUISITE** tests/test_projects 缺失 |
| J5 | H5 | H5 | 4b0b571 | src/features/threads/threadProjection.test.mts | **BLOCKED_PREREQUISITE** tests/test_threads 缺失 |
| J6 | H6 | H6 | af41897 | src/features/timeline/itemReducer.test.mts | Item events 由 H6 前端测试覆盖 |
| J7 | H7 | H7 | 236f5f6 | src/features/execution/toolCard.test.mts | **BLOCKED_PREREQUISITE** tests/test_execution 缺失 |
| J8 | H8 | H8 | 1ae7466 | src/features/approvals/approvalView.test.mts | **BLOCKED_PREREQUISITE** tests/test_approval 缺失 |
| J9 | H9 | H9 | b12b157 | src/features/review/reviewProjection.test.mts | **BLOCKED_PREREQUISITE** tests/test_review 缺失 |
| J10 | H10 | H10/H11 | 9de99c6 | src/features/files/pathGuard.test.mts | **BLOCKED_PREREQUISITE** test_file_preview / test_worktrees 缺失 |
| J11 | H11 | H12/H13 | 1252181 | src/features/settings/modelLimits.test.mts | **BLOCKED_PREREQUISITE** test_settings / test_capabilities 缺失 |
| J12 | H12 | H14/H15 | 52e33d2 | tests/a11y/a11y.test.mts | 前端 typecheck/test |
| J13 | H13 | H16 | 91d867f | src/features/release/compatibility.test.mts | **BLOCKED_PREREQUISITE** tests/test_release 缺失 |

前端 必须实现由上表测试覆盖；后端目录缺失不 mock。未改 protocol/schema.json。
