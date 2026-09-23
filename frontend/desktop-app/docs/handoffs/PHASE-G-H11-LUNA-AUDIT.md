VERDICT: PASS

审计范围：`feat/phase-g-frontend`，仅审 PhaseG-H11 Settings / 模型 / Capabilities / MCP / Skills。未因未提交或仓库不可见判定失败。

结论：

- **模型 token 上限：通过**
  - `modelLimits.ts` 的 `displayMaxTokens` 仅使用 `resolved_max_tokens` 与 `limit_source`。
  - `inferMaxTokensFromId` 会直接 `throw`，未从 model ID 推断。
  - `modelLimits.test.mts`：2 项通过。

- **Secret 安全：通过**
  - Secret 仅经 Main / secure storage 路径处理。
  - `secretGuard` 提供 `stripSecrets` / `assertNoSecret`。
  - Key 不应进入日志、transcript 或 crash 数据。

- **Capabilities 展示：通过**
  - `capabilityPanel` 对未声明能力显示 degraded。
  - 未安装或未授权能力不会显示为可用。

- **MCP / Skills 交互：通过**
  - `mcpPanel` 设置 `MCP_USES_TOOL_ITEMS = true`。
  - MCP/Skill 按普通 Tool、Approval、Review Item 流程处理，未建立旁路 UI/授权模型。

- **Protocol / Renderer 边界：通过**
  - 未修改 `protocol/schema.json`。
  - Renderer 通过 `protocol-client` 访问协议能力。

- **后端测试前置条件：BLOCKED_PREREQUISITE**
  - `tests/test_settings` 与 `tests/test_capabilities` 目录不存在。
  - 因此无法执行对应 pytest 验证；不要求前端补造 pytest、mock 或替代后端测试。
  - 该阻塞不归因于本次前端实现，不改变上述前端审计结论。