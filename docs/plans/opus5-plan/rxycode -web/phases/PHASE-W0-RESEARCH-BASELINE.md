# Phase W0 · RESEARCH-BASELINE（WEB 项目施工卡）

> **范围**：这是唯一可施工卡面，其他总设计文档不复制任务卡。执行旧项目卡时仍需服从旧 `DEV-ORDER.md`。每张卡独立分支/提交，严格遵守 `../00-WEB-EXECUTION-PLAN.md` WEB-R1–R12。

## §0 W0 前置与出口

共 4 张卡；开工先核实 upstream docs/code 与 `git status`，当前文件名只是目标设计，施工前须 `Test-Path`，不能因为示例而声称实现存在。

| 卡号 | 名称 | 前置 | owner |
|---|---|---|---|
| `WEB-W0-C01` | 原计划追溯、版本追踪与工作树锁定 | 无 | architecture/docs |
| `WEB-W0-C02` | 研究先行：Web Agent、Runner、云隔离的上游取舍 | WEB-W0-C01 | architecture/research |
| `WEB-W0-C03` | 单一 Agent 基线与旧端回归快照 | WEB-W0-C02 | backend/qa |
| `WEB-W0-C04` | Web 需求、接口和冲突冻结评审 | WEB-W0-C01,WEB-W0-C02,WEB-W0-C03 | architecture/product |

## §1 任务卡（TEST-first，可单卡施工）

### WEB-W0-C01 · 原计划追溯、版本追踪与工作树锁定
`优先级：P0` / 预计工时：0.5–2.5 工程日 / 依赖：无 · **owner: architecture/docs**

**背景与当前代码事实**
用户压缩包已有 303 份 docs/plans 下可解析文本，旧计划明确指出 docs/plans 被忽略造成文件丢失。必须先盘点本机 HEAD、Git 追踪和计划权威，避免重复灾难。

**涉及文件（白名单；`NEW` = 本卡新增，`VERIFY_EXISTING` = 本卡必须检查已有文件或前置卡产物；路径不符须 STOP/提交裁定）**
| 文件 | Grep 锚点/前置 | 允许的改法 |
|---|---|---|
| `AGENTS.md` | `Module Documentation Index` | 核对原规则和不可变约束 |
| `.gitignore` | `docs` | 最小范围解除本计划忽略或创建专属跟踪例外 |
| `docs/plans/opus5-plan/rxycode/architecture/DEV-ORDER.md` | `活开发顺序` | 仅阅读核验，不改旧施工优先级 |
| `docs/plans/opus5-plan/rxycode -web/16-DOC-AUDIT-CHANGE-CONTROL.md` | `NEW` | 记录基线与历史审读事实 |
| `docs/plans/opus5-plan/rxycode -web/scripts/check_plan.py` | `python scripts\check_plan.py` | 扩展本包已有静态扫描，不新建第二套扫描器 |
| `tests/web/w0/test_w0_c01_unit.py` | `NEW` | 严格单元契约，不得替生产降级 |
| `tests/web/w0/test_w0_c01_module.py` | `NEW` | 至少一个跨模块/进程/安全负测 |

**已经替你决定好的（不准自己发挥）**
保留旧主线 DEV-ORDER 的权威；Web 单独 `WEB-W*` 编号。通过 `git check-ignore -v` 实测再决定 git add -f 或定向 .gitignore 例外，避免一次性追踪敏感/巨型历史文件。

**否定边界**：本卡不实现第二套 Agent Loop、不跨表外文件“顺手修复”、不降低旧 `RiskLevel`、不以 mock/live screenshot 替代契约验收。现有路径/版本/依赖不符即 `BLOCKED_PREREQUISITE`，提案修改先审计。

**操作步骤（依次执行；TEST-first）**
1. 在隔离工作树读本卡上游源文件及对应模块 README，`rg` 定位锚点，记录 baseline 与当前 commit；无锚点 STOP。
2. **先建 RED 测试**：在 `tests/web/w0/test_w0_c01_unit.py` 写 `test_w0_c01_contract`、`test_w0_c01_negative`，在 `tests/web/w0/test_w0_c01_module.py` 写 `test_w0_c01_integration`，先运行观察**预期失败**，保存日志。
3. 先记录 git status/branch/commit 与 check-ignore 输出
4. 运行 doc 路径覆盖扫描和版本冲突扫描
5. 生成权威层级清单与忽略策略裁定
6. 仅将本 Web 文档纳入可追踪、可审阅变更。
7. 同步必要协议/生成 TS、更新模块文档，复跑 Unit→Contract→Process/E2E，保存 diff 与证据，单卡可独立 revert。

**测试施工（函数名锁定；Given / When / Then）**
- Unit `tests/web/w0/test_w0_c01_unit.py::test_w0_c01_contract`：Given 本 Web 计划存在 When 扫描索引 Then 无重复卡号且全部文件有索引链接。
- Module `tests/web/w0/test_w0_c01_module.py::test_w0_c01_integration`：Given 工作树的真实 .gitignore When 查询 Web 文档 Then 该文档确实可被 git 追踪且没有把遗留秘密打包。
- 反向 `tests/web/w0/test_w0_c01_unit.py::test_w0_c01_negative`：Given 缺少旧 DEV-ORDER When 扫描 Then BLOCKED_PREREQUISITE 而非建立虚假的权威替代。
- E2E / Process：本卡无独立 UI E2E；由对应 Phase 出口跨进程测试承接。
- 旧回归：任何碰 `core/` 或工具选取的卡加跑 `tests/test_cache/test_s1_s2_split.py` 和 `tests/test_cache/test_stable_prefix.py`；碰协议则加 `tests/test_protocol_schema.py`。

**验收命令（PowerShell；新测试文件由本卡创建，开卡前不得误判为已存在）**
```powershell
Set-Location 'D:\agent-demo\RxyCode\RxyCode1_1_0'
git status --short
rg -n --fixed-strings 'Module Documentation Index' 'AGENTS.md'
rg -n --fixed-strings 'docs' '.gitignore'
rg -n --fixed-strings '活开发顺序' 'docs/plans/opus5-plan/rxycode/architecture/DEV-ORDER.md'
python -m pytest 'tests/web/w0/test_w0_c01_unit.py' -q
python -m pytest 'tests/web/w0/test_w0_c01_module.py' -q
git diff --check
git status --short
```

**完成判据**
- [x] `test_w0_c01_contract`、`test_w0_c01_negative` 与 `test_w0_c01_integration` 全部真绿且无无故 skip。
- [x] 当前行为满足本卡冻结决策、现有 CLI/Desktop 回归符合期望。
- [x] 安全拒绝、失败和取消按本卡约束实测，未开发路径标 `BLOCKED` 而不是 PASS。
- [x] `evidence/web/WEB-W0-C01/` 有红绿日志、协议快照（若适用）、diff、人工复审与交接。

**Commit（仅此卡）**
`feat(web): web-w0-c01 - 原计划追溯、版本追踪与工作树锁定`

---

### WEB-W0-C02 · 研究先行：Web Agent、Runner、云隔离的上游取舍
`优先级：P0` / 预计工时：0.5–2.5 工程日 / 依赖：WEB-W0-C01 · **owner: architecture/research**

**背景与当前代码事实**
继承 PC0 research-first：OpenCode、Codex App Server、LangGraph、gVisor、Playwright、PTY 有现成模式，不能先盲写后端。内部依据来自 opus5-plan research 与 PHASE-P，外部引用需固定版本与 license。

**涉及文件（白名单；`NEW` = 本卡新增，`VERIFY_EXISTING` = 本卡必须检查已有文件或前置卡产物；路径不符须 STOP/提交裁定）**
| 文件 | Grep 锚点/前置 | 允许的改法 |
|---|---|---|
| `docs/plans/opus5-plan/rxycode/architecture/research/2026-09-01-top-coding-agents-core-architecture.md` | `top-coding-agents` | 阅读历史结论 |
| `docs/plans/opus5-plan/rxycode -web/15-RESEARCH-VERDICTS.md` | `NEW` | 为每个子系统补来源、固定 commit、采纳/拒绝、许可证表 |
| `docs/plans/opus5-plan/rxycode -web/scripts/check_plan.py` | `lookup_verdict` | 契约测试调用既有扫描器，不另建模块 |
| `docs/plans/opus5-plan/rxycode -web/adr/ADR-WEB-001-ONE-CORE-MANY-SURFACES.md` | `WEB-W0-C02 api-boundary` | 写入 API 边界的限制和钉住的 commit |
| `docs/plans/opus5-plan/rxycode -web/adr/ADR-WEB-003-RUNNER-BOUNDARY.md` | `WEB-W0-C02 linux-sandbox` | 写入 gVisor 的限制和版本 |
| `docs/plans/opus5-plan/rxycode -web/adr/ADR-WEB-005-DURABILITY-AND-SIDE-EFFECTS.md` | `WEB-W0-C02 storage-durability` | 写入 Journal 与 Checkpoint 的限制和 commit |

锚点裁定：`2026-09-01-top-coding-agents-core-architecture.md` 正文没有 `top-coding-agents`。文件存在，本卡只读不改。这不是文件名匹配通过。冻结来源改为 2026-10-16 的 GitHub commit。缺口记在证据里，不把该历史文件当成 SPDX 已核对来源。
| `tests/web/w0/test_w0_c02_unit.py` | `NEW` | 严格单元契约，不得替生产降级 |
| `tests/web/w0/test_w0_c02_module.py` | `NEW` | 至少一个跨模块/进程/安全负测 |

**已经替你决定好的（不准自己发挥）**
使用成熟上游架构理念，不抄专有产品未公开实现；第三方复制代码前核许可证和 commit。只采纳能改善 RXYCode 的接口，不为简历强堆 K8s/LiteLLM。

**否定边界**：本卡不实现第二套 Agent Loop、不跨表外文件“顺手修复”、不降低旧 `RiskLevel`、不以 mock/live screenshot 替代契约验收。现有路径/版本/依赖不符即 `BLOCKED_PREREQUISITE`，提案修改先审计。

**操作步骤（依次执行；TEST-first）**
1. 在隔离工作树读本卡上游源文件及对应模块 README，`rg` 定位锚点，记录 baseline 与当前 commit；无锚点 STOP。
2. **先建 RED 测试**：在 `tests/web/w0/test_w0_c02_unit.py` 写 `test_w0_c02_contract`、`test_w0_c02_negative`，在 `tests/web/w0/test_w0_c02_module.py` 写 `test_w0_c02_integration`，先运行观察**预期失败**，保存日志。
3. 列研究问题/alternatives
4. 列每个选型与拒绝理由/适用门槛
5. 对 Linux sandbox 与 Windows PTY 做可测 spike 方案
6. 冻结 API/Runner/Storage 的研究 Verdict。
7. 同步必要协议/生成 TS、更新模块文档，复跑 Unit→Contract→Process/E2E，保存 diff 与证据，单卡可独立 revert。

**测试施工（函数名锁定；Given / When / Then）**
- Unit `tests/web/w0/test_w0_c02_unit.py::test_w0_c02_contract`：Given 某子系统设计需求 When 查询 Verdict Then 能定位至少一个已验证来源及排除方案。
- Module `tests/web/w0/test_w0_c02_module.py::test_w0_c02_integration`：Given 审稿人检查设计来源 When 跳到 ADR Then 能从需求追溯到工程限制与版本号。
- 反向 `tests/web/w0/test_w0_c02_unit.py::test_w0_c02_negative`：Given 外部仓许可证未知 When 判定实现 Then 必须标 RESEARCH_REQUIRED 不能复制代码。
- E2E / Process：本卡无独立 UI E2E；由对应 Phase 出口跨进程测试承接。
- 旧回归：任何碰 `core/` 或工具选取的卡加跑 `tests/test_cache/test_s1_s2_split.py` 和 `tests/test_cache/test_stable_prefix.py`；碰协议则加 `tests/test_protocol_schema.py`。

**验收命令（PowerShell；新测试文件由本卡创建，开卡前不得误判为已存在）**
```powershell
Set-Location 'D:\agent-demo\RxyCode\RxyCode1_1_0'
git status --short
rg -n --fixed-strings 'top-coding-agents' 'docs/plans/opus5-plan/rxycode/architecture/research/2026-09-01-top-coding-agents-core-architecture.md'
python -m pytest 'tests/web/w0/test_w0_c02_unit.py' -q
python -m pytest 'tests/web/w0/test_w0_c02_module.py' -q
git diff --check
git status --short
```

**完成判据**
- [x] `test_w0_c02_contract`、`test_w0_c02_negative` 与 `test_w0_c02_integration` 全部真绿且无无故 skip。
- [x] 当前行为满足本卡冻结决策、现有 CLI/Desktop 回归符合期望。
- [x] 安全拒绝、失败和取消按本卡约束实测，未开发路径标 `BLOCKED` 而不是 PASS。
- [x] `evidence/web/WEB-W0-C02/` 有红绿日志、协议快照（若适用）、diff、人工复审与交接。

**Commit（仅此卡）**
`feat(web): web-w0-c02 - 研究先行：Web Agent、Runner、云隔离的上游取舍`

---

### WEB-W0-C03 · 单一 Agent 基线与旧端回归快照
`优先级：P0` / 预计工时：0.5–2.5 工程日 / 依赖：WEB-W0-C02 · **owner: backend/qa**

**背景与当前代码事实**
需确认 AGENTS.md 声称的 AgentV2/Session/AppServer/ToolJournal/Core sandbox 与现场实码一致；旧机器 Windows 路径可能与 GitHub 不同。

**涉及文件（白名单；`NEW` = 本卡新增，`VERIFY_EXISTING` = 本卡必须检查已有文件或前置卡产物；路径不符须 STOP/提交裁定）**
| 文件 | Grep 锚点/前置 | 允许的改法 |
|---|---|---|
| `core/session.py` | `reuse_or_create_session` | 测 session 复用/缓存 |
| `appserver/server.py` | `class AppServer` | 测单 Session Worker 现状 |
| `execution/tool_orchestrator.py` | `class ToolOrchestrator` | 证明唯一工具执行入口 |
| `execution/tool_journal.py` | `pending` | 检查副作用日志模型 |
| `docs/plans/opus5-plan/rxycode -web/02-AS-IS-REUSE-AUDIT.md` | `NEW` | 补证据和变更预算 |
| `tests/web/w0/test_w0_c03_unit.py` | `NEW` | 严格单元契约，不得替生产降级 |
| `tests/web/w0/test_w0_c03_module.py` | `NEW` | 至少一个跨模块/进程/安全负测 |
| `docs/plans/opus5-plan/rxycode -web/scripts/check_plan.py` | `baseline_file_status` | 缺失基线文件返回 BLOCKED，不另建模块 |

**已经替你决定好的（不准自己发挥）**
旧行为是基线，不因移动目录而改功能语义；必须保存真实 pytest/ruff/TS/installed wheel 输出，失败注明是原 baseline 还是当前提交新增。

**否定边界**：本卡不实现第二套 Agent Loop、不跨表外文件“顺手修复”、不降低旧 `RiskLevel`、不以 mock/live screenshot 替代契约验收。现有路径/版本/依赖不符即 `BLOCKED_PREREQUISITE`，提案修改先审计。

**操作步骤（依次执行；TEST-first）**
1. 在隔离工作树读本卡上游源文件及对应模块 README，`rg` 定位锚点，记录 baseline 与当前 commit；无锚点 STOP。
2. **先建 RED 测试**：在 `tests/web/w0/test_w0_c03_unit.py` 写 `test_w0_c03_contract`、`test_w0_c03_negative`，在 `tests/web/w0/test_w0_c03_module.py` 写 `test_w0_c03_integration`，先运行观察**预期失败**，保存日志。
3. 核对四处代码定位、import identity、bootstrap、RPC
4. 跑协议/缓存/工具/桌面等可运行测试并存 stdout
5. 形成 Active vs planned 列表
6. 记录 OS/runtime/版本/commit；不修无关红项。
7. 同步必要协议/生成 TS、更新模块文档，复跑 Unit→Contract→Process/E2E，保存 diff 与证据，单卡可独立 revert。

**测试施工（函数名锁定；Given / When / Then）**
- Unit `tests/web/w0/test_w0_c03_unit.py::test_w0_c03_contract`：Given 相同 session_id+workspace When 二次 prompt Then 保留 agent_runtimes 且只刷新 emit。
- Module `tests/web/w0/test_w0_c03_module.py::test_w0_c03_integration`：Given appserver 发送已有事件 When 旧协议客户端消费 Then 类型与生命周期不漂移。
- 反向 `tests/web/w0/test_w0_c03_unit.py::test_w0_c03_negative`：Given 基线缺失测试文件 When 评审 Then 明确 BLOCKED 而不是跳过报绿。
- E2E / Process：本卡无独立 UI E2E；由对应 Phase 出口跨进程测试承接。
- 旧回归：任何碰 `core/` 或工具选取的卡加跑 `tests/test_cache/test_s1_s2_split.py` 和 `tests/test_cache/test_stable_prefix.py`；碰协议则加 `tests/test_protocol_schema.py`。

**验收命令（PowerShell；新测试文件由本卡创建，开卡前不得误判为已存在）**
```powershell
Set-Location 'D:\agent-demo\RxyCode\RxyCode1_1_0'
git status --short
rg -n --fixed-strings 'reuse_or_create_session' 'core/session.py'
rg -n --fixed-strings 'class AppServer' 'appserver/server.py'
rg -n --fixed-strings 'class ToolOrchestrator' 'execution/tool_orchestrator.py'
rg -n --fixed-strings 'pending' 'execution/tool_journal.py'
python -m pytest 'tests/web/w0/test_w0_c03_unit.py' -q
python -m pytest 'tests/web/w0/test_w0_c03_module.py' -q
python -m pytest tests/test_cache/test_s1_s2_split.py tests/test_cache/test_stable_prefix.py -q
git diff --check
git status --short
```

**完成判据**
- [x] `test_w0_c03_contract`、`test_w0_c03_negative` 与 `test_w0_c03_integration` 全部真绿且无无故 skip。
- [x] 当前行为满足本卡冻结决策、现有 CLI/Desktop 回归符合期望。
- [x] 安全拒绝、失败和取消按本卡约束实测，未开发路径标 `BLOCKED` 而不是 PASS。
- [x] `evidence/web/WEB-W0-C03/` 有红绿日志、协议快照（若适用）、diff、人工复审与交接。

**Commit（仅此卡）**
`feat(web): web-w0-c03 - 单一 Agent 基线与旧端回归快照`

---

### WEB-W0-C04 · Web 需求、接口和冲突冻结评审
`优先级：P0` / 预计工时：0.5–2.5 工程日 / 依赖：WEB-W0-C01,WEB-W0-C02,WEB-W0-C03 · **owner: architecture/product**

**背景与当前代码事实**
旧 Phase G/Update 01/02/Phase P 已有大量协议、Todo、CU、Browser 卡；Web 需要新的 API/Run/Device，但不能复制旧权威。

**涉及文件（白名单；`NEW` = 本卡新增，`VERIFY_EXISTING` = 本卡必须检查已有文件或前置卡产物；路径不符须 STOP/提交裁定）**
| 文件 | Grep 锚点/前置 | 允许的改法 |
|---|---|---|
| `docs/plans/opus5-plan/rxycode -web/12-REQUIREMENTS-TRACEABILITY.md` | `NEW` | 逐条七项要求映射卡/测试 |
| `docs/plans/opus5-plan/rxycode -web/13-CONFLICT-AUDIT.md` | `NEW` | 登记重复编号、协议冲突与新 owner |
| `docs/plans/opus5-plan/rxycode -web/04-PROTOCOL-API-EVENT-RUNNER.md` | `NEW` | 锁事件和 API v1 草案 |
| `tests/web/w0/test_w0_c04_unit.py` | `NEW` | 严格单元契约，不得替生产降级 |
| `tests/web/w0/test_w0_c04_module.py` | `NEW` | 至少一个跨模块/进程/安全负测 |
| `docs/plans/opus5-plan/rxycode -web/scripts/check_plan.py` | `trace_requirements` | 追踪、重名裁定和 W1 门禁读这三份文档，不另建模块 |

**已经替你决定好的（不准自己发挥）**
冻结 Session/Run/AgentEvent/ExecutionTarget/ToolInvocation/DeviceGrant 语义；旧 Protocol JSON-RPC 保留。没有实际本机复核不许写“已落实”。

**否定边界**：本卡不实现第二套 Agent Loop、不跨表外文件“顺手修复”、不降低旧 `RiskLevel`、不以 mock/live screenshot 替代契约验收。现有路径/版本/依赖不符即 `BLOCKED_PREREQUISITE`，提案修改先审计。

**操作步骤（依次执行；TEST-first）**
1. 在隔离工作树读本卡上游源文件及对应模块 README，`rg` 定位锚点，记录 baseline 与当前 commit；无锚点 STOP。
2. **先建 RED 测试**：在 `tests/web/w0/test_w0_c04_unit.py` 写 `test_w0_c04_contract`、`test_w0_c04_negative`，在 `tests/web/w0/test_w0_c04_module.py` 写 `test_w0_c04_integration`，先运行观察**预期失败**，保存日志。
3. 对照 PRD/协议/旧卡列需求 trace
4. 记录未决架构争议与 ADR owner
5. 冻结事件字段/错误码和 import 方向
6. 经人审查通过 W0 总门后再进入 W1。
7. 同步必要协议/生成 TS、更新模块文档，复跑 Unit→Contract→Process/E2E，保存 diff 与证据，单卡可独立 revert。

**测试施工（函数名锁定；Given / When / Then）**
- Unit `tests/web/w0/test_w0_c04_unit.py::test_w0_c04_contract`：Given 用户七大要求 When 检查追踪表 Then 每条都有 owner、开发卡和自动测试 ID。
- Module `tests/web/w0/test_w0_c04_module.py::test_w0_c04_integration`：Given 一个新 Web 命令 When 与旧 protocol 重名 Then 有冲突裁定或 BLOCKED。
- 反向 `tests/web/w0/test_w0_c04_unit.py::test_w0_c04_negative`：Given 还有 unresolved P0 冲突 When 发起 W1 Then 门禁拒绝。
- E2E / Process：本卡无独立 UI E2E；由对应 Phase 出口跨进程测试承接。
- 旧回归：任何碰 `core/` 或工具选取的卡加跑 `tests/test_cache/test_s1_s2_split.py` 和 `tests/test_cache/test_stable_prefix.py`；碰协议则加 `tests/test_protocol_schema.py`。

**验收命令（PowerShell；新测试文件由本卡创建，开卡前不得误判为已存在）**
```powershell
Set-Location 'D:\agent-demo\RxyCode\RxyCode1_1_0'
git status --short
python -m pytest 'tests/web/w0/test_w0_c04_unit.py' -q
python -m pytest 'tests/web/w0/test_w0_c04_module.py' -q
git diff --check
git status --short
```

**完成判据**
- [x] `test_w0_c04_contract`、`test_w0_c04_negative` 与 `test_w0_c04_integration` 全部真绿且无无故 skip。
- [x] 当前行为满足本卡冻结决策、现有 CLI/Desktop 回归符合期望。
- [x] 安全拒绝、失败和取消按本卡约束实测，未开发路径标 `BLOCKED` 而不是 PASS。
- [x] `evidence/web/WEB-W0-C04/` 有红绿日志、协议快照（若适用）、diff、人工复审与交接。

**Commit（仅此卡）**
`feat(web): web-w0-c04 - Web 需求、接口和冲突冻结评审`

---

## §2 Wave 出口检查
- [ ] W0 所有卡各有独立 commit 和 evidence，未勾选项不被宣称完成。
- [ ] 既有行为回归没有被覆盖，新增 API 不依赖 mock/假状态。
- [ ] 运行期错误、权限拒绝和用户可见状态有负向证据。
