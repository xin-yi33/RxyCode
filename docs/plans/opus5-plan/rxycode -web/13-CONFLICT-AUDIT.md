# 旧 Phase / Web 新项目冲突登记（未验收项一律 OPEN）

> 参照旧 `rxycode/PHASE-G-CONFLICT-AUDIT.md` 的事实强度写法：**现有材料展示存在 ≠ 用户本机当前 HEAD 已证实**。所有新冲突状态为 `OPEN` 或 `NEEDS_VERIFICATION`；W0-C04 复核并变更。

| ID | 风险/矛盾 | 旧权威 | Web 决策/处理 owner | 状态 |
|---|---|---|---|---|
| CW01 | `docs/plans/` 被 gitignore，Web 文档可能未入 Git | 老冲突 X14 / DEV-ORDER | W0-C01 先决，追踪仅本 Web 文档 | OPEN |
| CW02 | W* 卡号与旧 `P8`/`U46`/`G-B` 碰撞 | 旧 PHASE-A…P | 唯一 `WEB-Wn-Cxx` | 设计已避免，待脚本核实 |
| CW03 | 单独 Web Agent loop 导致 Core 分叉 | ARCH-001 / `core/session.py` | W1-C01/C05 统一入口 | OPEN |
| CW04 | 两套协议 TS 类型 | `protocol/schema.json`, protocol-client | W1-C04 单源 codegen | OPEN |
| CW05 | 旧 HTTP 适配直接公网上线 | `api_server.py` loopback | W2-C02 另建认证 Server，旧接口本地兼容 | OPEN |
| CW06 | Desktop `TaskStore` 被当多租户 Run Store | `appserver/task_store.py`, sessions | W2-C01 PG authority + migration | OPEN |
| CW07 | `appserver/lifecycle.py` 单实例抢占与云端多 Worker 不兼容 | appserver 单实例策略 | W2-C03 数据库 lease/fencing | OPEN |
| CW08 | LangGraph Checkpoint 被误当副作用 exactly-once | `execution/tool_journal.py` | W2-C05 保留 at-most-once | OPEN |
| CW09 | U24/U46 Browser 与 CU 同名重复注册 | UPDATE-01 / `core/cu` | W6-C03 只适配，不重造 | OPEN |
| CW10 | 原 Sandbox 主要作用 shell，被误当完整云隔离 | `docs/modules/sandbox.md` | W5-C01/C02 云隔离独立供应 | OPEN |
| CW11 | Full 被 Sandbox 模拟替代 | 用户硬要求 | W4-C01 Native direct，实机测试 | OPEN |
| CW12 | 云端直接设置 Full 即控制本机 | permission.py/Remote trust | W4-C05 本机 grant 必须确认 | OPEN |
| CW13 | 旧 U63–72 snapshot/durability 与新 checkpoint 状态冲突 | UPDATE-01 | W2-C05 迁移边界/ADR | OPEN |
| CW14 | Team intermediates 泄漏主 final answer | appserver `intermediate` | W3-C03/W6-C04 按 parent/child reducer | OPEN |
| CW15 | `core/session.py` runtime 缓存丢失 | `reuse_or_create_session` | W1-C01/C02 保多轮缓存 | OPEN |
| CW16 | bare import identity 和目录搬迁导致同 class 两份 | PHASE-FIX2 | W1-C01 wheel/install/类型 identity | OPEN |
| CW17 | 旧端 CLI/TUI/Desktop 生成类型不同步 | frontend/protocol-client / appserver | W1-C04/C05 合同测试 | OPEN |
| CW18 | Sandbox 无法隔离时 fallback Host | 云多租户威胁 | W5-C01/C02 fail closed | OPEN |
| CW19 | `appserver/schedule_service` 与 Cloud distributed scheduler 双真相 | UPDATE-01 /旧 `ScheduleService` | W6-C05 只扩消费/桥接 | OPEN |
| CW20 | 从用户 Repo 中的 prompt injection 读取私人凭据 | Web + Local Full | W7-C01 Tool policy / 本机 scope / 审计 | OPEN |

**解冲流程**：LOCATE 旧真相→当前源码/测试复核→标 `CONFIRMED` 或 `FALSE_POSITIVE`→提出唯一 owner+CARD→评审通过→只改 owner 卡→真实测试结果→`RESOLVED`。**不能**仅凭写了计划就把 OPEN 改为 RESOLVED，也不能与旧 Phase 共享卡号或复制旧权威卡面。

## WEB-W0-C04 conflict rows

P0 且状态为 OPEN 时，W1 门禁返回 REJECTED。旧 JSON-RPC 方法名不被新 Web 命令复用。

| id | severity | status | command | ruling |
|---|---|---|---|---|
| CW03 | P0 | OPEN |  | OPEN |
| CW04 | P0 | OPEN | session/prompt | BLOCKED |
