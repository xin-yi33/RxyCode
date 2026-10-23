# ADR-WEB-006-MONOREPO-MIGRATION · Accepted（设计草案）

- **Context / 决策问题**：长期采用五包结构，但迁移逐卡并保持旧客户端可用。
- **Decision / 已确定**：先冻结合同/测试，再可安装包/adapter，再迁类；旧 CLI/Desktop 兼容并测试类型 identity。
- **Alternatives considered / 拒绝的方案**：全量复制移动代码一口气重构容易出现重复类、旧缓存失效、wheel 缺包。
- **Consequences / 代价**：必须补严格接口、真实测试与迁移适配；生产可靠性优先于短期最小代码改动。
- **Implementation owner**：W1-C01/C05（以 Wave 文件内完整 `WEB-W*-C*` 为准）。
- **Verification**：按 `tests/TEST-MATRIX.md`、原 CLI/Desktop regression、`13-CONFLICT-AUDIT.md` 开工复核，未实测前不得称已落地。
- **Compatibility**：继承旧 `docs/decisions/ARCH-001`～`004`，冲突须新增变更单，禁止暗改历史 ADR。
