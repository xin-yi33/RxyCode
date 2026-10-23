# ADR-WEB-002-EVENT-SOURCE-OF-TRUTH · Accepted（设计草案）

- **Context / 决策问题**：EventStore 使用 PostgreSQL append-only + Outbox，通知不是真相。
- **Decision / 已确定**：SSE 从 DB replay，并通过数据库补齐 PubSub/Notify 的竞态与丢包；客户端 seq 去重。
- **Alternatives considered / 拒绝的方案**：只靠 Redis Pub/Sub 无法补齐断线历史；直接推 Worker stdout 不保证持久。
- **Consequences / 代价**：必须补严格接口、真实测试与迁移适配；生产可靠性优先于短期最小代码改动。
- **Implementation owner**：W2-C04（以 Wave 文件内完整 `WEB-W*-C*` 为准）。
- **Verification**：按 `tests/TEST-MATRIX.md`、原 CLI/Desktop regression、`13-CONFLICT-AUDIT.md` 开工复核，未实测前不得称已落地。
- **Compatibility**：继承旧 `docs/decisions/ARCH-001`～`004`，冲突须新增变更单，禁止暗改历史 ADR。
