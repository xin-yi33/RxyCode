# ADR-WEB-005-DURABILITY-AND-SIDE-EFFECTS · Accepted（设计草案）

- **Context / 决策问题**：Graph Checkpoint、Run Store、Event Store、Tool Journal 各管不同事实。
- **Decision / 已确定**：unknown side effects at-most-once 阻重放、显式 recovery_required；不能宣称 exactly once。
- **Alternatives considered / 拒绝的方案**：只有 LangGraph Saver 不能判断外部操作已经发生。
- **Consequences / 代价**：必须补严格接口、真实测试与迁移适配；生产可靠性优先于短期最小代码改动。
- **Implementation owner**：W2-C03/C05/C06（以 Wave 文件内完整 `WEB-W*-C*` 为准）。
- **Verification**：按 `tests/TEST-MATRIX.md`、原 CLI/Desktop regression、`13-CONFLICT-AUDIT.md` 开工复核，未实测前不得称已落地。
- **Compatibility**：继承旧 `docs/decisions/ARCH-001`～`004`，冲突须新增变更单，禁止暗改历史 ADR。

## WEB-W0-C02 storage-durability

- id: storage-durability
- version: 5eb60aef6f3837a1fb632a8abc6cf8e8da81785b
- commit: 5eb60aef6f3837a1fb632a8abc6cf8e8da81785b
- limit: LangGraph checkpointer 只保存图状态。它不能证明外部副作用已经发生，所以 Git push 和文件写入仍由 Tool Journal 记录。
