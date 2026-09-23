VERDICT: PASS

GX7-H 审计通过：

- `event/token_usage` 存在，路径 A 可消费。
- `event/agent_usage` 缺失，不构成失败条件。
- `cost` 无定价字段时显示为隐藏的 `PENDING_PRICING`。
- 未硬编码 `8192`。
- Statusline 默认支持配置 `model/context/tokens`。
- 窄窗口仅保留 `model + ring`。
- 使用量超过 50% 时显示 warn。
- 无会话时隐藏 Statusline。
- 测试通过。
- 未涉及 schema 修改。