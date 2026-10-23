# 迁包与兼容、数据迁移、双写禁止及回滚方案

> **目标**：允许全面最佳重构，但不能抛弃已有数千行 Agent、CLI/Desktop、多 Agent、prefix/cache 与可靠性成果。

## §1 迁移波次（受 W1/W2 开卡约束）

| 阶段 | 允许变更 | 不变合同 | 退出条件 |
|---|---|---|---|
| M0 冻结旧 HEAD | 写审计与测试基线、记录路径/版本 | 不改生产行为 | 基线日志 + Git SHA |
| M1 引入 packages/ | 新 pyproject/包入口/adapter | 原 imports/session identity 唯一 | installed wheel smoke + CLI smoke |
| M2 RunContext/ExecutionPort | Core 只留下接口，旧工具通过 adapter | ToolOrchestrator 安全门与 Journal | Unit+Contract/缓存不回归 |
| M3 协议迁移 | JSON Schema/TS 生成，旧 RPC additive | initialize/session/prompt/approval 旧协议兼容 | schema diff + TypeScript + 旧端 contract |
| M4 Server+PG | 旧 Desktop 目录读取与导入 adapter | 不在 API handler 跑第二 Loop | 迁移 rollback+复测 |
| M5 Runner Native/Remote | 新 LocalBackend、WSS、grant | Full 直通 Native；Old CLI 不丢能力 | 真机与安全 E2E |
| M6 Cloud+UI | Cloud workspace/CI/Artifact/UX | Cloud 不得 host subprocess | Demo E2E + tenant isolation |

不允许“复制 AgentV2 到新包，旧文件照跑”形成第二大脑；先统一 import alias/identity，再搬内容。`core/agent_v2.py` 拆分需遵守旧 `architecture/DEV-ORDER.md` SP0–SP3 的 tests-first 顺序，若与 W1 卡白名单冲突先登记 CW。

## §2 迁移数据的真实性

- 原有 Desktop `sessions/list`, `task_store` 与 `memory/chat_storage` 不是同一真相；迁移器只读原始文件、把符合版本的目录映射到 Session/Run/Event，校验 count/digest；不存在的历史事件不能凭想象补造。
- Migration 记录来源 path/hash/version 和迁移时间，具备 dry-run、resume、安全回滚策略；已经迁入 PG 的目标不能重复插入；未经用户批准不删除原 JSON。
- 模型配置/API Key 独立受保护，任何导入都不能把明文 secret 写到仓库、日志、浏览器；未知模式 `MIGRATION_REVIEW_REQUIRED`。

## §3 回滚与兼容

- 每张卡一个 commit，`git revert <single-card-commit>` 应能独立撤销代码变更（数据库不可逆迁移须另有手册与备份）；不把每张卡堆进一个大型 Merge commit。
- 在旧客户端兼容期保持 `initialize`, `session/new`, `session/prompt`, `approval/request` 和 schema min/max 协商；破坏版本时 bump major 并提供 adapter。
- 部署回滚前要校验数据库前向兼容；老版本程序不能读取新字段时必须停止回滚并走 `MIGRATION_BLOCKED`，不能 drop data。
- 旧 CLI/Team/Cache/Tool Journal 发现异常时立即 rollback 当前 Wave；保留带有失败证据的 Incident 与复现测试。
