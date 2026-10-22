# ADR-WEB-004-PERMISSION-LOCAL-AUTHORITY · Accepted（设计草案）

- **Context / 决策问题**：云端没有权限独自授权 Remote Full 操作本机。
- **Decision / 已确定**：本机先确认 Session Grant，Runner 每次校验 scope/TTL/revocation；范围内无逐项审批。
- **Alternatives considered / 拒绝的方案**：云端传 `permission=full` 字符串并比较 max_permission 不能抗服务端沦陷。
- **Consequences / 代价**：必须补严格接口、真实测试与迁移适配；生产可靠性优先于短期最小代码改动。
- **Implementation owner**：W4-C05（以 Wave 文件内完整 `WEB-W*-C*` 为准）。
- **Verification**：按 `tests/TEST-MATRIX.md`、原 CLI/Desktop regression、`13-CONFLICT-AUDIT.md` 开工复核，未实测前不得称已落地。
- **Compatibility**：继承旧 `docs/decisions/ARCH-001`～`004`，冲突须新增变更单，禁止暗改历史 ADR。
