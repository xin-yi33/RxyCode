你是 GX 前端审计员。只审 GX7-H。不要以看不到仓库判 FAIL。未改 schema。feat/phase-g-frontend。
探针：event/token_usage 存在（路径 A 消费）；event/agent_usage 缺失。cost 无定价字段 → PENDING_PRICING 隐藏。禁止硬编码 8192。
Statusline 默认可配 model/context/tokens；窄窗只留 model+ring；超 50% warn。无会话隐藏。测试 pass。
第一行 VERDICT: PASS 或 FAIL。
