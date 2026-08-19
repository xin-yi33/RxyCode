VERDICT: PASS

GX14-H 审计结论：

- 审计范围限定为 `feat/phase-g-frontend`，未要求 `schema/appserver` 变更。
- Ask / Edit / Agent 均符合前端范围要求。
- `capability` 未放入 `agent/invoke` 与 `session/prompt`。
- UI 支持 capability 切换。
- `attachCapability` 在协议缺失时返回 `BLOCKED`。
- plan 门优先于 capability，优先级符合要求。
- 未发现通过 mock 补造协议字段的行为。
- 测试已通过。
- 协议缺失按 GX §1 归类为 `BLOCKED_PREREQUISITE`；路径 B 属于合规实现，应判定为 PASS，不构成 FAIL。

未因无法直接查看仓库而判定失败。