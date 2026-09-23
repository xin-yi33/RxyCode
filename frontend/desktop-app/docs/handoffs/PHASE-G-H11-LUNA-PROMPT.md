你是 RxyCode Phase G 前端独立审计员（gpt-5.6-luna）。不要改代码。
只审 PhaseG-H11 Settings/模型/Capabilities/MCP/Skills。分支 feat/phase-g-frontend。
不得因尚未 commit 或看不到仓库判 FAIL。后端 tests/test_settings 与 tests/test_capabilities 目录不存在 → BLOCKED_PREREQUISITE，不要要求前端造 pytest 或 mock。

对照 PHASE-G-FRONTEND.md PhaseG-H11：
- max token 只展示 Phase 3 resolver/summary，不从 model id 推断
- secret 只经 Main/secure storage；Key 不进日志/transcript/crash
- 未安装/未授权能力不显示为可用
- MCP/Skill 走普通 Tool/Approval/Review Item
- 未改 protocol/schema.json；Renderer 经 protocol-client

证据：
- modelLimits.ts displayMaxTokens 用 resolved_max_tokens + limit_source；inferMaxTokensFromId throw
- secretGuard stripSecrets / assertNoSecret
- capabilityPanel degraded unless isDeclaredCapability
- mcpPanel MCP_USES_TOOL_ITEMS = true
- modelLimits.test.mts 2 通过
- pytest tests/test_settings 与 test_capabilities：目录不存在 BLOCKED_PREREQUISITE

第一行必须是 VERDICT: PASS 或 VERDICT: FAIL。
