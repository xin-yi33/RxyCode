# ADR-WEB-001-ONE-CORE-MANY-SURFACES · Accepted（设计草案）

- **Context / 决策问题**：所有入口只有一份 AgentV2/Session/ToolOrchestrator 真相。
- **Decision / 已确定**：Web 不再创建 Agent Loop，使用 headless Session Facade + 独立 Worker；迁包时保留 Python class identity。
- **Alternatives considered / 拒绝的方案**：复制 Web AgentV2 简单但会导致缓存、审批、团队语义分叉；这与 ARCH-001 冲突。
- **Consequences / 代价**：必须补严格接口、真实测试与迁移适配；生产可靠性优先于短期最小代码改动。
- **Implementation owner**：W1-C01/C05（以 Wave 文件内完整 `WEB-W*-C*` 为准）。
- **Verification**：按 `tests/TEST-MATRIX.md`、原 CLI/Desktop regression、`13-CONFLICT-AUDIT.md` 开工复核，未实测前不得称已落地。
- **Compatibility**：继承旧 `docs/decisions/ARCH-001`～`004`，冲突须新增变更单，禁止暗改历史 ADR。

## WEB-W0-C02 api-boundary

- id: api-boundary
- version: 3df96b085c666b33d3775aa4e77219ec1ed828a0
- commit: 3df96b085c666b33d3775aa4e77219ec1ed828a0
- limit: 只借鉴 Codex 把 app-server 与 core 分开。不复制未公开的 Claude Code。Web、CLI、Desktop 共用一个 Agent Loop，工具执行仍走现有 Orchestrator。
