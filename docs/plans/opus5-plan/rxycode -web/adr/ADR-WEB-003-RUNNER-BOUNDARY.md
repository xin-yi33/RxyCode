# ADR-WEB-003-RUNNER-BOUNDARY · Accepted（设计草案）

- **Context / 决策问题**：Core 决策与 Runner 操作 OS 分离，Target 与 Capabilities 独立。
- **Decision / 已确定**：Local/Remote/Cloud ToolBackend 由 ExecutionPort 统一桥接，Local Full Native 无 Sandbox。
- **Alternatives considered / 拒绝的方案**：把所有 Tools 写进 AgentV2 或在 Cloud Worker 内跑 host subprocess 会混淆执行环境。
- **Consequences / 代价**：必须补严格接口、真实测试与迁移适配；生产可靠性优先于短期最小代码改动。
- **Implementation owner**：W1-C03/W4-C01/W5-C01（以 Wave 文件内完整 `WEB-W*-C*` 为准）。
- **Verification**：按 `tests/TEST-MATRIX.md`、原 CLI/Desktop regression、`13-CONFLICT-AUDIT.md` 开工复核，未实测前不得称已落地。
- **Compatibility**：继承旧 `docs/decisions/ARCH-001`～`004`，冲突须新增变更单，禁止暗改历史 ADR。

## WEB-W0-C02 linux-sandbox

- id: linux-sandbox
- version: release-20261005.0
- commit: d4d3e28027b4b6c94848a95bb7ada24bf82be84c
- limit: gVisor 只作为 Linux 云端 Provider 候选。Local Full 不加这层沙箱。本卡没有测量宿主逃逸成本。Firecracker 仍可做另一个 Provider，不能写成唯一后端。
