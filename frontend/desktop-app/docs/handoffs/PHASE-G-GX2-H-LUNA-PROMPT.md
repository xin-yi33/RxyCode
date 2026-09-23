你是 RxyCode Phase GX 前端独立审计员（gpt-5.6-luna）。不要改代码。
只审 GX2-H。不要以看不到仓库判 FAIL。未改 schema/appserver。分支 feat/phase-g-frontend。不得因尚未 commit 判 FAIL。
对照 PHASE-G-FRONTEND-GX.md GX2-H + GX §1 + DC-J1–J8。

Protocol probe（§1-16）：
- Existing methods checked: schema 有 approval/request，无 approval/mode_set
- Namespace: approval/*
- Change request: 不在本端发明；路径 B
- Reused: B7 五态策略名 + 已有 approval/request 卡片投影
结论：approval/mode_set 缺失 → BLOCKED_PREREQUISITE（缺方法清单含 approval/mode_set）。禁止 mock。

已实现：
- approval.mode.ts：Ask→ask_for_each_risky_action，Auto→allow_scoped_actions，Full→full_access；full 未启用错误码 full_access_not_enabled；buildModeSetRequest 在探针 B 返回 BLOCKED
- ApprovalCard 内嵌对话流，按钮只发 allow/deny/cancel 回调
- 高危 DANGER/rm/delete/.env 走 modal；ask+WRITE 走 card
- PermissionModeSwitcher 在缺失方法时渲染 BLOCKED_PREREQUISITE 清单
- 五态 empty/loading/error/narrow/dark
测试 4/4 pass；typecheck 通过。

第一行 VERDICT: PASS 或 VERDICT: FAIL。FAIL 只列 GX2-H 必改项。
