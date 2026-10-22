# RXYCode Web · Hybrid AI Agent Platform 施工文档总索引

> **状态**：开发计划 / NOT IMPLEMENTED。本文和所属文档**不是**已经交付的功能证明。
> **文档基线**：2026-10-16；输入为用户 `docs.zip`（本地 `docs/` 快照）及 2026-10-16 可读取的 RxyCode GitHub 当前代码摘要。
> **唯一落盘位置**：`D:\agent-demo\RxyCode\RxyCode1_1_0\docs\plans\opus5-plan\rxycode -web\`。注意 `rxycode -web` 是**带空格**的既有空目录，不是旧 `rxycode/`，也不是 `rxycode-web/`。
> **产品原则**：最好改动 ≠ 最小改动。允许正式重构和拆包，但不得以漂亮的目录代替真实、可追溯、可运行的产品能力。
> **研发原则**：Research first（PC0）、先锁契约再跨端实现、TEST-first、单卡单提交、证据验收、不可变历史、明确回滚。

## 权威阅读顺序

1. [00-WEB-EXECUTION-PLAN.md](00-WEB-EXECUTION-PLAN.md)：**本 Web 项目的唯一开发顺序**、卡号、前置、并发许可、阶段出口、停工条件。旧 `rxycode/architecture/DEV-ORDER.md` 对**旧项目主线**仍然权威，不能被本文件覆盖。
2. [01-PRODUCT-PRD.md](01-PRODUCT-PRD.md)：三种模式、最终用户路径、功能边界和产品验收；若实现与 PRD 冲突，提交 ADR 后才能更改。
3. [03-ARCHITECTURE-AND-BOUNDARIES.md](03-ARCHITECTURE-AND-BOUNDARIES.md)：真正的五部分结构、包边界、依赖方向、Full 与 Sandbox 区分。
4. [04-PROTOCOL-API-EVENT-RUNNER.md](04-PROTOCOL-API-EVENT-RUNNER.md)：唯一 API/事件/Runner 协议契约；变更先改 Pydantic/JSON Schema/TS，再改 UI。
5. [05-DATA-STATE-RECOVERY.md](05-DATA-STATE-RECOVERY.md)、[06-SECURITY-FULL-MODE.md](06-SECURITY-FULL-MODE.md)：可靠性、安全和外部副作用不可打折。
6. 每次施工仅阅读该卡所在的 `phases/PHASE-W*-*.md` 的对应任务卡，以及卡列明的上游资料；**避免为施工卡通读所有计划并耗尽上下文**。

## 文档结构

| 产物 | 责任 |
|---|---|
| `00-WEB-EXECUTION-PLAN.md` | 唯一施工顺序/串并行规则 |
| `01-PRODUCT-PRD.md` | 用户体验、MVP 不作为最终出口 |
| `02-AS-IS-REUSE-AUDIT.md` | 现有代码真相、可复用与须重构点 |
| `03-ARCHITECTURE-AND-BOUNDARIES.md` | 最终包依赖、执行拓扑 |
| `04-PROTOCOL-API-EVENT-RUNNER.md` | HTTP/SSE/WS/Pydantic 规范 |
| `05-DATA-STATE-RECOVERY.md` | DB、Checkpoint、Journal、Outbox |
| `06-SECURITY-FULL-MODE.md` | 本地 Full、远程授权、云端隔离 |
| `07-WEB-UX-WORKSPACE.md` | Web 产品工作台、状态和 A11y |
| `08-TOOLS-CAPABILITY-PLAN.md` | 既有 Tool 复用与增量能力 |
| `09-DEPLOY-RUNBOOK.md` | local/self-host/cloud、部署与运维 |
| `10-TEST-EVAL-ACCEPTANCE.md` | TEST-first、模块/进程/E2E/安全/评测 |
| `11-JOB-PORTFOLIO-DELIVERY.md` | 求职项目交付标准/演示/真实指标 |
| `12-REQUIREMENTS-TRACEABILITY.md` | 用户七大要求→卡→测试映射 |
| `13-CONFLICT-AUDIT.md` | 旧卡号/新契约/安全冲突登记 |
| `14-MIGRATION-AND-ROLLBACK.md` | 分包迁移、数据迁移、兼容和回滚 |
| `15-RESEARCH-VERDICTS.md` | Research first 与来源/证据等级 |
| `16-DOC-AUDIT-CHANGE-CONTROL.md` | 历史审读范围、文档质量门与变更记录 |
| `phases/PHASE-W0-*.md`～`PHASE-W7-*.md` | **唯一可施工卡面**；每卡白名单/锚点/TEST-first/验收/Commit |
| `tests/TEST-MATRIX.md`, `tests/E2E-FIXTURES.md` | 测试 ID、GWT、可重现 fixture |
| `templates/*` | 固定施工卡/交接模板 |
| `adr/*` | 设计决策记录（ADR，Accepted） |
| [`scripts/check_plan.py`](scripts/check_plan.py) | 计划包静态扫描：卡号、链接、测试规格 |
| [`FILE-MANIFEST.sha256`](FILE-MANIFEST.sha256) | 本包文件哈希 |
| [`.gitignore`](.gitignore) | 本目录内的密钥和压缩包不入库 |

## 已经冻结的产品决定

- `rxycode`：继续保留 CLI/TUI；`rxycode web`：本地 Web；`rxycode connect`：将本机以授权 Runner 连接云端；RXYCode Cloud：线上账号与云端沙箱。**产品能力共享同一 Agent 内核**。
- **Local Full**：本机 NativeBackend、无需沙箱、不逐项审批，真实操作文件/shell/桌面；**Remote Full**：本机确认会话授权后，Runner NativeBackend 同样跳过沙箱，云端无权自行扩大授权；**Cloud Full**：Full 仅在受隔离云端工作区生效，不是本机 Full。
- Server 管身份/Run/Event，Worker 管 Agent，Runner 管 OS 工具；ToolOrchestrator 和 Tool Journal 仍是唯一执行治理面；不得出现第二套 Agent Loop、两套 Session 真相或第二个 Tool Registry。
- 出口不是“有界面可聊天”，必须有 Demo、完整业务路径、断线和异常测试、真实 Agent Eval、工程化部署与求职证明。功能完成前不允许在 README 写“已支持”。

## 如何执行（强制）

- 本 Web 文件夹的卡号统一 `WEB-W{phase}-C{nn}`，与原计划 `F1`/`P8`/`U46` 等不重名。既有 Phase 不迁卡、不复制卡面。
- 每卡只允许白名单文件；真实目标路径由 `WEB-W0-C01` 搜索核实，路径未存在时不得伪造。新建文件写“新建”；现有代码用 grep 锚点定位。
- 真实执行每卡后，更新 `evidence/web/<卡号>/` 里的自审、测试日志、接口快照；**目前文档包不包含任何虚构的 PASS 或证据**。
- 当前仓库历史明确指出 `docs/plans/` 曾被 `.gitignore` 排除并发生过文档丢失事故：**WEB-W0-C01 必须先解决版本追踪**，未经追踪本包不进入正式施工。
- 源代码与当前文档可能已发生变化；以开工现场 `git status`/`rg`/真实测试为准；不符则 `BLOCKED_PREREQUISITE`，提交冲突单，不要猜。

## 文档包静态验收（先运行）

```powershell
Set-Location 'D:\agent-demo\RxyCode\RxyCode1_1_0\docs\plans\opus5-plan\rxycode -web'
python scripts\check_plan.py
```

预期显示 `AUDIT docs=37 cards=48 tests=173 errors=0`（将本包新增文档纳入统计时 `docs` 数量才会改变），它只验证**计划文档静态一致性**，不表示任何产品功能或施工测试已经通过。共 48 张正式任务卡、173 个具名 GWT 测试规格、25 个 E2E 场景；测试文件和功能均待后续工程施工。全部旧计划文本来源索引与哈希见 [`research/SOURCE-INDEX.md`](research/SOURCE-INDEX.md)。

## 快速开工命令（PowerShell）

```powershell
Set-Location 'D:\agent-demo\RxyCode\RxyCode1_1_0'
git status --short
git branch --show-current
Test-Path 'docs\plans\opus5-plan\rxycode -web\00-WEB-EXECUTION-PLAN.md'
git check-ignore -v 'docs/plans/opus5-plan/rxycode -web/README.md'
# 若被忽略，先由 WEB-W0-C01 的版本追踪方案处理，不可在未审查时直接改全仓 .gitignore。
```

**开工顺序**：从 `WEB-W0-C01` 开始，一次一张卡。每张卡执行后独立审计和 commit。不得直接跳到 Web UI 截图或 Runner Full 演示声称完成。

## 2026-10-22 · Web UI 增量需求

[前端改版需求包](requirements/UI-2026-10-22/README.md)：依据用户 `UI前端更改.md` 与38张参考图，定义侧栏、置顶/归档/删除、项目/搜索、定时任务、六个设置页、按钮行为、接口及复合验收。它是后续UI增量需求，不是重跑W0/W8的指令，也不是已完成功能证明；架构/安全和已有执行链继续复用。已有模型添加只改布局，不另造后端。涉及无业务源通知、SMS/身份提供服务的依赖与范围待确认项在包内明确登记。
