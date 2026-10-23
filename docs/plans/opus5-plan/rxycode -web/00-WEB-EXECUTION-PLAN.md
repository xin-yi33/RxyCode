# RXYCode Web · 活开发顺序与施工总手册（权威）

> **Scope**：`rxycode -web/` 全套新 Web 产品计划；**不是**覆盖旧 `rxycode/architecture/DEV-ORDER.md` 的主线变更单。旧主线相关文件开卡前仍须核对原先 Phase 和当前代码。
> **状态**：PLANNED；任何未真实执行的命令均不构成“已通过”。
> **单一代码主写**：遵守 `../COMPOSER-2.5-PLAYBOOK.md` 当前模型分工（模型名字作为历史施工约束；替换主写模型须 ADR；审查和视觉辅助可独立工作）。

## §0 先读规则：一张卡、一个唯一真相、一个可回滚提交

施工回路：`RESEARCH/VERDICT → LOCATE → PRECONDITION → TEST-FIRST(RED) → IMPLEMENT → UNIT → CONTRACT → PROCESS/E2E → SECURITY/RECOVERY → DIFF AUDIT → HANDOFF → COMMIT`。

**硬约束**：

1. **WEB-R1** 单卡单提交、独立回滚，禁止同卡迁包+大范围业务改写，除非该卡明确声明覆盖。
2. **WEB-R2** 当前代码与卡面锚点不符须 STOP，不能通过造一个假同名模块/Mock API/重写测试规避。
3. **WEB-R3** 任何跨端字段先进入 Pydantic→JSON Schema→TS 生成物与契约测试，之后才能写前端；旧 `protocol/schema.json` 的兼容版本机制不能被绕开。
4. **WEB-R4** Core、CLI、TUI、Desktop、Web 不得各自拥有 Agent Loop；所有工具经过现有 ToolOrchestrator、统一 Audit 与 Tool Journal。
5. **WEB-R5** Local/Remote Full 走 Native OS，禁止把“受限沙箱能访问映射目录”冒充本机 Full；远程 Full 的授予以本机同意为权威。
6. **WEB-R6** SSE EventStore 必须支持持久序列、掉线补齐与重连；Agent Worker 生命周期与 HTTP 连接解耦。
7. **WEB-R7** Worker Crash、Retry、LangGraph Interrupt、工具 side-effect unknown 状态必须覆盖 fail-closed 测试，禁止自动重复未知副作用。
8. **WEB-R8** 不允许跨租户访问路径、Run、SSE、设备、审批或产物；公网端口与 Preview 默认封闭。
9. **WEB-R9** 不准改掉旧 Session 前缀、模型 identity、团队隔离、工具风险分级、超时和缓存不变量；基准回归缺失则 BLOCKED。
10. **WEB-R10** 不允许复制历史卡正文形成双权威。交叉引用原 `rxycode/phase-g/`、UPDATE-01/02、PHASE-P、ARCH-001…004。
11. **WEB-R11** 每卡定义成功/拒绝/超时/取消/崩溃/重连中相关的负向测试，不可只证明 happy path。
12. **WEB-R12** 任务全部完成前，简历与官网只能使用真实具备的能力和实测数据，不得虚构成功率、吞吐/成本或“生产级”。

### §0.1 PowerShell 日常自检

```powershell
Set-Location 'D:\agent-demo\RxyCode\RxyCode1_1_0'
git status --short
git branch --show-current
python --version
python -m pytest tests/test_protocol_schema.py -q
Test-Path appserver
Test-Path protocol/schema.json
Test-Path execution/tool_orchestrator.py
Test-Path execution/tool_journal.py
Test-Path frontend/desktop-app
Test-Path 'docs/plans/opus5-plan/rxycode -web/README.md'
```

一旦 `git status` 显示未经授权的未提交改动，禁止清空工作树；隔离的工作树需先确定同仓并发写冲突策略。真实测试命令以当前仓库为准；缺依赖则 BLOCKED 并保存日志。

### §0.2 研发证据与停工码

每张卡在 `evidence/web/WEB-Wx-Cyy/` 保存：`baseline.txt`, `red.txt`, `unit.txt`, `contract.txt`, `integration.txt`, `security.txt`（若适用）, `diff.txt`, `self-audit.md`, `handoff.md`。**这个文件夹不是本文档包“已运行证据”**；在开发阶段创建。

STOP 格式：`BLOCKED_PREREQUISITE / CONTRACT_CONFLICT / UNSAFE_BOUNDARY / RESEARCH_REQUIRED / BASELINE_REGRESSION` + 卡号 + 真实现象 + 已验证输入 + 未修改内容 + 请求裁定。禁止三次盲修。

### §0.3 唯一权威关系

| 约束 | 原权威 | 新增 Web 权威 |
|---|---|---|
| 既有 Agent/CLI 功能 | `../rxycode/architecture/DEV-ORDER.md`, `MODULE-BOUNDARIES.md`, `AGENTS.md` | 仅增 Web 边界，冲突先登记 |
| 旧 Desktop 主链 | `../rxycode/phase-g/` 与 `docs/phase-g/` 被跟踪副本 | 仅 Web 工作台新增 |
| U24/U46 Browser，U20–23 CU | `../rxycode/PHASE-UPDATE-01.md` | 不复制工具实现 |
| Runtime/Tools 既有 side-effect | `execution/tool_orchestrator.py`, `execution/tool_journal.py` | Runner RPC 桥接，未知状态 fail-closed |
| Run/Event/HTTP/WS 新契约 | 无统一 Web 真相 | [`04-PROTOCOL-API-EVENT-RUNNER.md`](04-PROTOCOL-API-EVENT-RUNNER.md) |
| 数据和任务重启 | 原 `Session`/Desktop `TaskStore` 仅旧客户端 | [`05-DATA-STATE-RECOVERY.md`](05-DATA-STATE-RECOVERY.md) |
| Full 与 Remote Full | 当前 `appserver/permission.py` 部分支持权限档 | [`06-SECURITY-FULL-MODE.md`](06-SECURITY-FULL-MODE.md) |

## §1 唯一研发波次（按依赖，不按日历）

| Wave | 卡片文件 | 主要交付 | 开工前置 | 出口证明 |
|---|---|---|---|---|
| W0 | [PHASE-W0](phases/PHASE-W0-RESEARCH-BASELINE.md) | 文档版本追踪、实码审计、上游 Verdict、冻结初版接口 | 当前仓库可检查 | 文档入 git + 基线日志 + 冲突零 P0 |
| W1 | [PHASE-W1](phases/PHASE-W1-CORE-PROTOCOL.md) | 核心运行边界、统一上下文、能力路由与协议生成 | W0 | CLI/Desktop contract 全绿 |
| W2 | [PHASE-W2](phases/PHASE-W2-SERVER-RUNTIME.md) | FastAPI、PG、Run/Worker、SSE、审批、持久恢复 | W1 核心协议稳定 | 服务端断线、租约和崩溃测试全绿 |
| W3 | [PHASE-W3](phases/PHASE-W3-WEB-WORKSPACE.md) | 完整 Web 产品工作台 | W2 API 可真实运行 | 真实 Web→Server→Worker E2E |
| W4 | [PHASE-W4](phases/PHASE-W4-LOCAL-FULL-RUNNER.md) | 本机 Native Full、远程 Runner、CU、急停 | W2/W3 + W1 execution seam | 真实本机验证，不使用沙箱冒充 |
| W5 | [PHASE-W5](phases/PHASE-W5-CLOUD-SANDBOX.md) | 云端安全沙箱、多租户、预览与 GitHub PR | W2 + W4 RPC 契约 | 云端完成公开任务且租户隔离测试 |
| W6 | [PHASE-W6](phases/PHASE-W6-TOOLS-EXPERIENCE.md) | 完整工具闭环、多 Agent、记忆、用量、产品打磨 | W3/W4/W5 | 产品主路径、不同失败路径 E2E |
| W7 | [PHASE-W7](phases/PHASE-W7-SECURITY-EVAL-DELIVERY.md) | 安全、混沌、Agent Eval、可观测性、Demo、求职包 | W1–W6 | 发布 checklist 与实测报告 |
| W8 | [WEB-W8-C01 与补充说明](../../../architecture/web-rules-supplement-2026-10-20.md) | 云端执行语义、沙箱内 Full=自动批准、审批恢复、初始化共享入口（登记不证明授权） | W7 | 三条复合验收主链实测通过 |
| W9 | [PHASE-W9 §6 轨道 A/H/F/Q](phases/PHASE-W9-PRODUCT-CLOSURE-AND-DEPLOYMENT.md) | 邮箱注册登录、提交 Run、事件链修复、控制台/时间线/输入框、本地 E2E | W8 | Q1 报告 E-1–E-9 通过（M1） |
| W10 | [PHASE-W9 §6 轨道 D](phases/PHASE-W9-PRODUCT-CLOSURE-AND-DEPLOYMENT.md) | 生产镜像、生产 overlay、真实证书、备份、私有 staging、容量实测 | W9 | 服务器上 E-1–E-3 通过 + 容量表（M2） |
| W11 | [PHASE-W9 §7](phases/PHASE-W9-PRODUCT-CLOSURE-AND-DEPLOYMENT.md) | 邀请 3–5 人内测，每日修复 | W10 | 内测复盘决策点（M3） |

W2/W3 的前端视觉设计可与后端开发并行，但 **消费已冻结接口之前不能合并**；W4 的设备授权 UI 可在 W3 布局完成后并行。任何改 `protocol/` 的卡必须串行合并，避免生成 TS 类型丢同步。

### §1.1 看板与建议工程节奏

- W0 4 卡；W1 5 卡；W2 7 卡；W3 7 卡；W4 7 卡；W5 6 卡；W6 6 卡；W7 6 卡。**总计 48 张卡**。一张卡 0.5–2.5 工程日**只是粗估，不保证周期**。
- 正式交付目标是 W7 出口；W3 可内部 dogfood，W5 可先开放受限 Demo；不可把 W3 本地 Web 测试通过当成完整求职项目完成。
- 每个 Wave 结束生成 release/tag 和真实总结；每张卡仅在 `evidence/web/` 有证据且审核后才能 `[x]`。

### §1.2 并行 / 冲突

| 可并行 | 禁止并行合入 | 理由 |
|---|---|---|
| Web 视觉稿 / 无状态 UI / API 契约准备 | 同时改 `protocol/schema.json` 的两张卡 | 类型生成冲突 |
| Runner OS Spike 与 W2 数据库独立测试 | 两个 PR 同时改 `ToolOrchestrator.execute_tool` | 容易出现绕过审批 |
| Eval 任务集调研与 Web 工程 | 正在修改 `core/session.py` 的不同分支 | Runtime 与 prefix 生命周期敏感 |
| 部署文档/威胁建模与产品 UI | 公网部署未完成隔离就公开 Full 能力 | 安全事故 |

## §2 Phase 出口不得省略

每个 Wave 的卡片全部有：目标、允许文件、锚点、冻结设计、步骤、Unit/Contract/Process/Negative、命令、勾选项、独立 commit。卡文档中的新增测试路径是**施工目标**，不是声称原仓已存在。

W0 → W1：已有代码/上游研究有经过复核的 Verdict；版本追踪已确认，Baseline 记录真实。
W1 → W2：Core 不直接进行 OS 调用、协议新增 schema/TS 可重生，CLI/Desktop 无回归。
W2 → W3：同一 Run 有 durable event sequence、SSE replay、审批持久化、JWT/CSRF/租户访问控制与 API 样例。
W3 → W4：Web 主界面完整、设备 UI 有真实 API 契约、断线恢复基线通过。
W4 → W5：Local Full 真实 OS、WSS RPC、设备撤销、急停、工具未知结果拦截均过机测。
W5 → W6：云端资源边界闭环、端口预览不可直通宿主、授权 GitHub PR 路径可以演示。
W6 → W7：Coding / CU / Browser / Team / Artifact / Follow-up 以真实用户流程测试完成。
W7：公开 HTTPS Demo、可重建发行件、测试证据、真实 Benchmark、可观察 Trace、演示视频与简历材料；所有 SECURITY-P0 为 0。

## §3 本计划不授权的事情

- 不授权替 LinkAgent 改其独立仓库。不能把 LinkAgent 的 EKO/B+ tree 私有代码强行并入 RXYCode Web。
- 不授权为求职添加没有任务支撑的 K8s、pgvector、Celery 或重造框架；需要的时候开新的 ADR。
- 不授权推送到远程主分支、变更用户生产部署、在未隔离环境开通公网 Full。
- 不授权为了让测试通过修改既有断言、禁用 CI 或降低 `RiskLevel` 默认级别。
- 不承诺“一切工具恰好执行一次”或“Checkpoint 能恢复任意 OS 进程”。无法确定的副作用必须落在 `recovery_required`。
