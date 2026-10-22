# 代码现状审计与“复用/替换/迁移”判决

> **证据等级**：2026-10-16 通过已连接 GitHub 仓库读取若干真实文件；通过用户 `docs.zip` 阅读本地计划。**这不是对用户本机工作树的实时 git diff 或全量代码行级审计**。W0-C01 / C02 必须在开发机核验源码和分支。

## §1 已确认存在的实现（禁止重复造）

| 原代码 | 已有能力 | Web 项目处置 |
|---|---|---|
| `core/session.py` | Headless `Session` / emit / PromptResult，`reuse_or_create_session` 保留 role runtimes | 迁入 `rxycode_core` 后维持复用与前缀缓存不变量 |
| `core/agent_v2.py`, `core/graph.py` | AgentV2 / LangGraph workflow / multi-agent | 按 SP0–SP3 先迁测试再拆责任，禁止新循环 |
| `execution/tool_orchestrator.py` | 动态工具注册、风险门、调用预算/审计、当前工具边界 | 保留唯一入口，仅增加 Target dispatch seam |
| `execution/tool_journal.py` | pending→completed 外部副作用 Journal，at-most-once replay | 保留语义，延伸到 Runner RPC，不许当 exactly-once |
| `core/safety/policy.py` | READ/WRITE/DANGER 和 shell 参数动态升级 | 映射到 ToolSpec + 实际 target gate，未知默认写操作 |
| `core/sandbox/*`, `utils/shell.py` | Shell 子进程 OS sandbox，Win Job/Linux bwrap/macOS Seatbelt | 保留给 Ask/Auto 或本地限制；Local Full 必须明确 bypass；云多租户另设容器/VM 边界 |
| `appserver/server.py`, `appserver/agent_host.py`, `appserver/agent_worker.py` | stdio JSON-RPC、每 Session killable 子进程、Watchdog | 本地兼容适配，云端演进成独立 Worker Service |
| `appserver/sessions.py`, `task_store.py` | 旧桌面 Session 目录和事件索引 | 导入/过渡映射；多用户 Web authority 交给 PG |
| `appserver/permission.py`, `approval.py` | Ask/Auto/Full 预设和 RPC 审批 | Web 审批落库；本机 Runner 独立授权；不复制安全真相 |
| `protocol/requests.py`, `protocol/notifications.py`, `protocol/schema.json` | Pydantic JSON-RPC Schema + TS codegen | 强化 Run / Target / Approval / Event，向旧协议兼容扩展 |
| `frontend/protocol-client/`, `frontend/desktop-app/` | React/Electron/协议客户端、相关组件与测试 | 共享纯视图组件，浏览器不 import Electron/preload/node APIs |
| `core/cu/`, Playwright MCP / Chrome CDP | 现有部分 CU / Browser 实现 | 在独立能力层注册，测试碰撞命名，禁止第二个 Browser 工具链 |
| `evals/`, `core/tracing.py`, `appserver/schedule_service.py` | Agent eval、trace、local 调度 | 改造成 Web 任务可观测 + 继承现有 schedule 语义 |

## §2 必须解除的真实结构风险

- `appserver/runtime.py` 利用 ContextVar 绑定 prompt 上下文。跨进程 RPC 需要显式 `RunContext`，不能用隐式全局对象传递租户/目标/授权。
- 旧 appserver 有锁与进程抢占，`appserver/lifecycle.py` 的单实例规则适合 Desktop；云端多用户/多 Worker 不可复用“抢旧进程”策略。
- `api_server.py` 现有本地 HTTP 适配含 loopback 前提；**绝不直接公网暴露旧端口**，必须以新 Server 认证和租户模型重写 HTTP 外围。
- 当前 `appserver/permission.py` `full_access` 的 `selectable` 不一定等于启用；新 Web UI 不得只改一个布尔字段绕过原有授权逻辑。
- 仓库部分代码使用 `RxyCode.RxyCode1_1_0.*` 与短模块别名；拆包前要锁住 import 身份不重复、同类不多份的测试。参照现有 `PHASE-FIX2-PROCESS-GLOBAL-STATE.md`。
- 当前 OS Sandbox 文档明确：主要覆盖 Shell，不覆盖普通 file write/edit、MCP/Playwright/Desktop 的全部 OS 行为；**不能宣称打开此开关就已有完整云端租户隔离**。

## §3 文件迁移判决矩阵

| 子系统 | Verdict | 原因 | 开发卡 |
|---|---|---|---|
| AgentV2/SOP/Teams | KEEP + REFACTOR | 已有模型推理与多代理能力，重复造浪费且破坏性能 | W1-C01/C02/C05 |
| ToolOrchestrator | KEEP + EXTEND | 唯一治理入口不可分叉 | W1-C03 |
| Protocol | EXTEND + VERSION | 已经是 Python/TS 唯一契约 | W1-C04 |
| Desktop TaskStore | MIGRATE/READ ADAPTER | 不能充当公网多租户数据库 | W2-C01/C02 |
| Browser/Computer Use | ADAPT/EXPOSE | 必须先核实既有能力/冲突 | W4-C02, W6-C03 |
| Web HTTP Server | NEW PUBLIC SERVER | 原 API 只适合 loopback / legacy compatibility | W2-C01/C02 |
| Native Device Runner | NEW | 旧 AgentHost 不是设备注册/出站 WS 服务 | W4-C01/C03/C04 |
| Cloud Isolation | NEW PROVIDER | 旧 OS sandbox 并非完整多租户隔离 | W5-C01/C02 |

## §4 旧计划的关联与绝不覆盖

- `../rxycode/architecture/DEV-ORDER.md` 是旧项目开发顺序；其模块边界与本设计不兼容时先 `13-CONFLICT-AUDIT.md` 标记。
- `../rxycode/PHASE-UPDATE-01.md` U24/U46 Browser/CU，U63–U72 durability/snapshot；不能重复定义 browser 工具或存储真相。
- `../rxycode/PHASE-UPDATE-02.md` V0–V46 Transport/Todo/Activity/Loop；不能另造这些功能的同名协议。
- `../rxycode/PHASE-P-AGENTIC-TIMEOUT-LOOP.md` `P8` 恢复判决：超时治理逻辑不在 Web 复制。
- Desktop 的 tracked 权威 `docs/phase-g/` 与本地 `rxycode/phase-g/` 可能出现内容差异，以施工当时 git 检验与 ADR 指向归属。

## §5 WEB-W0-C03 本机核对（2026-10-16）

四个锚点都在当前工作树里：`core/session.py` 的 `reuse_or_create_session`，`appserver/server.py` 的 `class AppServer`，`execution/tool_orchestrator.py` 的 `class ToolOrchestrator`，`execution/tool_journal.py` 的 `pending`。本卡没有改这四个文件的行为。

`reuse_or_create_session` 之后，第二次 `Session.prompt` 仍使用同一个对象和 `agent_runtimes`。第二次的 `FinalAnswer` 只进新的 `emit`。`appserver.emitter.model_to_notification` 把 `RecoveryStarted` 再 `FinalAnswer` 编成 JSON-RPC，`frontend/protocol-client` 的 `ProtocolClient.handleLine` 按这个顺序消费，`recovery_kind` 和 `session_schema_version` 不丢。`ToolExecutionJournal.reserve` 第一次是 `execute` 且 `has_pending`，同一参数的下一次是 `uncertain`，不会再执行。`ToolOrchestrator.execute_tool` 是 `execution/` 里唯一的 `async def execute_tool`。`AppServer._host_for_session` 对同一个 session 返回已经活着的 host；没有记录的另一个 session 不会借用这个 host。本卡没有改这两个方法。

变更预算：不新增 Agent Loop，不改 RiskLevel，不把缺文件的基线测试标成跳过通过。缺文件由 `baseline_file_status` 返回 `BLOCKED`。

旧缓存测试 `tests/test_cache/test_s1_s2_split.py` 与 `tests/test_cache/test_stable_prefix.py` 这次是 30 passed、2 skipped。两条 skip 的原因都是 `no tools registered in global test registry`，位于 `test_stable_prefix.py`，不是本卡新增。本卡自己的三份测试没有 skip。
