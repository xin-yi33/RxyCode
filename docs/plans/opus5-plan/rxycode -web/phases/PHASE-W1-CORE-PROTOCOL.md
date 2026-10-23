# Phase W1 · CORE-PROTOCOL（WEB 项目施工卡）

> **范围**：这是唯一可施工卡面，其他总设计文档不复制任务卡。执行旧项目卡时仍需服从旧 `DEV-ORDER.md`。每张卡独立分支/提交，严格遵守 `../00-WEB-EXECUTION-PLAN.md` WEB-R1–R12。

## §0 W1 前置与出口

共 5 张卡；开工先核实 upstream docs/code 与 `git status`，当前文件名只是目标设计，施工前须 `Test-Path`，不能因为示例而声称实现存在。

| 卡号 | 名称 | 前置 | owner |
|---|---|---|---|
| `WEB-W1-C01` | 正式可安装包与唯一 Session 兼容迁移 | W0全部 | backend/core |
| `WEB-W1-C02` | 显式 RunContext 与 Session 生命周期 | WEB-W1-C01 | backend/core |
| `WEB-W1-C03` | ExecutionPort + ToolSpec 能力域与唯一安全门 | WEB-W1-C02 | backend/tools |
| `WEB-W1-C04` | Pydantic 统一协议/Schema 与 TS Codegen | WEB-W1-C03 | protocol |
| `WEB-W1-C05` | 统一 CLI/Desktop/Web 核心入口与包测试 | WEB-W1-C01,WEB-W1-C02,WEB-W1-C03,WEB-W1-C04 | integration/core |

## §1 任务卡（TEST-first，可单卡施工）

### WEB-W1-C01 · 正式可安装包与唯一 Session 兼容迁移
`优先级：P0` / 预计工时：0.5–2.5 工程日 / 依赖：W0全部 · **owner: backend/core**

**背景与当前代码事实**
核心 Session 当前引用 `RxyCode.RxyCode1_1_0` 绝对包名并有双导入身份历史事故。最终要五包清晰结构，而不是复制 AgentV2。

**涉及文件（白名单；`NEW` = 本卡新增，`VERIFY_EXISTING` = 本卡必须检查已有文件或前置卡产物；路径不符须 STOP/提交裁定）**
| 文件 | Grep 锚点/前置 | 允许的改法 |
|---|---|---|
| `pyproject.toml` | `[project]` | 在兼容 wheel 的前提下注册包布局 |
| `core/session.py` | `reuse_or_create_session` | 抽公共接口、保持历史代理调用 |
| `packages/rxycode-core/src/rxycode_core/__init__.py` | `NEW` | 建立包 identity 转接入口 |
| `tests/system/test_installed_package.py` | `test_` | 增加 wheel smoke（不改旧断言） |
| `tests/web/w1/test_w1_c01_unit.py` | `NEW` | 严格单元契约，不得替生产降级 |
| `tests/web/w1/test_w1_c01_module.py` | `NEW` | 至少一个跨模块/进程/安全负测 |

**已经替你决定好的（不准自己发挥）**
采用 Strangler migration：先可安装包+旧兼容导出，逐卡迁入，别一次性搬走上千 Python 文件；同一 Session class 在所有客户端只有一个 Python identity；第三方插件可过渡 1 个发布周期。

**否定边界**：本卡不实现第二套 Agent Loop、不跨表外文件“顺手修复”、不降低旧 `RiskLevel`、不以 mock/live screenshot 替代契约验收。现有路径/版本/依赖不符即 `BLOCKED_PREREQUISITE`，提案修改先审计。

**操作步骤（依次执行；TEST-first）**
1. 在隔离工作树读本卡上游源文件及对应模块 README，`rg` 定位锚点，记录 baseline 与当前 commit；无锚点 STOP。
2. **先建 RED 测试**：在 `tests/web/w1/test_w1_c01_unit.py` 写 `test_w1_c01_contract`、`test_w1_c01_negative`，在 `tests/web/w1/test_w1_c01_module.py` 写 `test_w1_c01_integration`，先运行观察**预期失败**，保存日志。
3. 冻结兼容 import 表
4. 在新包建立薄接口/adapter
5. 建立 wheel build/install smoke；将 legacy root import 指向单一实现
6. 核对 CLI/Desktop、缓存与供应商 registry 后再迁源。
7. 同步必要协议/生成 TS、更新模块文档，复跑 Unit→Contract→Process/E2E，保存 diff 与证据，单卡可独立 revert。

**测试施工（函数名锁定；Given / When / Then）**
- Unit `tests/web/w1/test_w1_c01_unit.py::test_w1_c01_contract`：Given legacy import 和新 package import When 导入 Session Then 类型 identity 是同一实现。
- Module `tests/web/w1/test_w1_c01_module.py::test_w1_c01_integration`：Given wheel 安装到独立 venv When 启动 CLI/AppServer Then 没有遗漏子包/资源。
- 反向 `tests/web/w1/test_w1_c01_unit.py::test_w1_c01_negative`：Given 两份 AgentV2 对象被创建 When import audit Then 测试失败并阻止合并。
- E2E / Process：本卡无独立 UI E2E；由对应 Phase 出口跨进程测试承接。
- 旧回归：任何碰 `core/` 或工具选取的卡加跑 `tests/test_cache/test_s1_s2_split.py` 和 `tests/test_cache/test_stable_prefix.py`；碰协议则加 `tests/test_protocol_schema.py`。

**验收命令（PowerShell；新测试文件由本卡创建，开卡前不得误判为已存在）**
```powershell
Set-Location 'D:\agent-demo\RxyCode\RxyCode1_1_0'
git status --short
rg -n --fixed-strings '[project]' 'pyproject.toml'
rg -n --fixed-strings 'reuse_or_create_session' 'core/session.py'
rg -n --fixed-strings 'test_' 'tests/system/test_installed_package.py'
python -m pytest 'tests/web/w1/test_w1_c01_unit.py' -q
python -m pytest 'tests/web/w1/test_w1_c01_module.py' -q
python -m pytest tests/test_cache/test_s1_s2_split.py tests/test_cache/test_stable_prefix.py -q
git diff --check
git status --short
```

**完成判据**
- [x] `test_w1_c01_contract`、`test_w1_c01_negative` 与 `test_w1_c01_integration` 全部真绿且无无故 skip。
- [x] 当前行为满足本卡冻结决策、现有 CLI/Desktop 回归符合期望。
- [x] 安全拒绝、失败和取消按本卡约束实测，未开发路径标 `BLOCKED` 而不是 PASS。
- [x] `evidence/web/WEB-W1-C01/` 有红绿日志、协议快照（若适用）、diff、人工复审与交接。

**Commit（仅此卡）**
`feat(web): web-w1-c01 - 正式可安装包与唯一 Session 兼容迁移`

---

### WEB-W1-C02 · 显式 RunContext 与 Session 生命周期
`优先级：P0` / 预计工时：0.5–2.5 工程日 / 依赖：WEB-W1-C01 · **owner: backend/core**

**背景与当前代码事实**
现有 `appserver/runtime.py` ContextVar 可处理本地异步，但不能安全跨 Worker/Runner 传 tenant/run/target 与 trace。

**涉及文件（白名单；`NEW` = 本卡新增，`VERIFY_EXISTING` = 本卡必须检查已有文件或前置卡产物；路径不符须 STOP/提交裁定）**
| 文件 | Grep 锚点/前置 | 允许的改法 |
|---|---|---|
| `core/session.py` | `class PromptResult` | 接入不可变 RunContext 并保留现有 emit |
| `appserver/runtime.py` | `bind_prompt_context` | 过渡为适配显式上下文 |
| `appserver/agent_worker.py` | `bind_prompt_context` | 正式 prompt 用服务端 RunContext，忽略请求体里的 tenant/run id。裁定：适配点在 worker，不在 runtime 的调用方之外 |
| `pyproject.toml` | `[project]` | 注册 `rxycode_protocol`，否则安装后的 Session.open_run 无法导入。裁定：C01 只注册了 rxycode_core |
| `packages/rxycode-protocol/src/rxycode_protocol/run_context.py` | `NEW` | 定义 DTO 和序列化 |
| `tests/web/w1/test_w1_c02_unit.py` | `NEW` | 严格单元契约，不得替生产降级 |
| `tests/web/w1/test_w1_c02_module.py` | `NEW` | 至少一个跨模块/进程/安全负测 |

**已经替你决定好的（不准自己发挥）**
RunContext 字段是 `tenant_id,actor_id,project_id,session_id,run_id,target_id,permission_profile,deadline_at,trace_id`；不携带 API Key 或明文设备 token；不能用 os.chdir 切换多租户 workspace。

**否定边界**：本卡不实现第二套 Agent Loop、不跨表外文件“顺手修复”、不降低旧 `RiskLevel`、不以 mock/live screenshot 替代契约验收。现有路径/版本/依赖不符即 `BLOCKED_PREREQUISITE`，提案修改先审计。

**操作步骤（依次执行；TEST-first）**
1. 在隔离工作树读本卡上游源文件及对应模块 README，`rg` 定位锚点，记录 baseline 与当前 commit；无锚点 STOP。
2. **先建 RED 测试**：在 `tests/web/w1/test_w1_c02_unit.py` 写 `test_w1_c02_contract`、`test_w1_c02_negative`，在 `tests/web/w1/test_w1_c02_module.py` 写 `test_w1_c02_integration`，先运行观察**预期失败**，保存日志。
3. 写 RunContext DTO 和 validation 失败样本
4. 给 Session.prompt 增加兼容注入（旧签名仍可用）
5. 在 appserver adapter 将现有 session 参数转换为 RunContext
6. 明确终态/取消 propagation。
7. 同步必要协议/生成 TS、更新模块文档，复跑 Unit→Contract→Process/E2E，保存 diff 与证据，单卡可独立 revert。

**测试施工（函数名锁定；Given / When / Then）**
- Unit `tests/web/w1/test_w1_c02_unit.py::test_w1_c02_contract`：Given 同一个 Session 的两轮 Run When 创建 context Then run_id 不同而 session identity 不重建。
- Module `tests/web/w1/test_w1_c02_module.py::test_w1_c02_integration`：Given 两个并发项目 When 运行上下文穿透 ToolOrchestrator Then tenant_id/target_id 不串。
- 反向 `tests/web/w1/test_w1_c02_unit.py::test_w1_c02_negative`：Given 客户端伪造 tenant_id When 服务端构造 RunContext Then 忽略请求体、以鉴权身份为准。
- E2E / Process：本卡无独立 UI E2E；由对应 Phase 出口跨进程测试承接。
- 旧回归：任何碰 `core/` 或工具选取的卡加跑 `tests/test_cache/test_s1_s2_split.py` 和 `tests/test_cache/test_stable_prefix.py`；碰协议则加 `tests/test_protocol_schema.py`。

**验收命令（PowerShell；新测试文件由本卡创建，开卡前不得误判为已存在）**
```powershell
Set-Location 'D:\agent-demo\RxyCode\RxyCode1_1_0'
git status --short
rg -n --fixed-strings 'class PromptResult' 'core/session.py'
rg -n --fixed-strings 'bind_prompt_context' 'appserver/runtime.py'
python -m pytest 'tests/web/w1/test_w1_c02_unit.py' -q
python -m pytest 'tests/web/w1/test_w1_c02_module.py' -q
python -m pytest tests/test_protocol_schema.py -q
python -m pytest tests/test_cache/test_s1_s2_split.py tests/test_cache/test_stable_prefix.py -q
git diff --check
git status --short
```

**完成判据**
- [x] `test_w1_c02_contract`、`test_w1_c02_negative` 与 `test_w1_c02_integration` 全部真绿且无无故 skip。
- [x] 当前行为满足本卡冻结决策、现有 CLI/Desktop 回归符合期望。
- [x] 安全拒绝、失败和取消按本卡约束实测，未开发路径标 `BLOCKED` 而不是 PASS。
- [x] `evidence/web/WEB-W1-C02/` 有红绿日志、协议快照（若适用）、diff、人工复审与交接。

**Commit（仅此卡）**
`feat(web): web-w1-c02 - 显式 RunContext 与 Session 生命周期`

---

### WEB-W1-C03 · ExecutionPort + ToolSpec 能力域与唯一安全门
`优先级：P0` / 预计工时：0.5–2.5 工程日 / 依赖：WEB-W1-C02 · **owner: backend/tools**

**背景与当前代码事实**
现有 ToolOrchestrator 有完整 READ/WRITE/DANGER、Tool Journal、timeout、MCP 统一路径，新增目标不能绕过它。

**涉及文件（白名单；`NEW` = 本卡新增，`VERIFY_EXISTING` = 本卡必须检查已有文件或前置卡产物；路径不符须 STOP/提交裁定）**
| 文件 | Grep 锚点/前置 | 允许的改法 |
|---|---|---|
| `execution/tool_orchestrator.py` | `async def execute_tool` | 增加 target dispatch 在批准/Journaling 之后 |
| `core/safety/policy.py` | `class RiskLevel` | 复用风险层级 |
| `packages/rxycode-core/src/rxycode_core/runtime/execution_port.py` | `NEW` | 定义 ExecutionPort/Capabilities/ToolSpec |
| `packages/rxycode-core/src/rxycode_core/runtime/__init__.py` | `NEW` | runtime 子包标记。裁定：setuptools 需要它才能安装 execution_port |
| `pyproject.toml` | `[project]` | 注册 `rxycode_core.runtime`。裁定：显式 packages 列表不会自动带上子包 |
| `packages/rxycode-protocol/src/rxycode_protocol/tool_rpc.py` | `NEW` | 固定调用/分片结果 |
| `tests/web/w1/test_w1_c03_unit.py` | `NEW` | 严格单元契约，不得替生产降级 |
| `tests/web/w1/test_w1_c03_module.py` | `NEW` | 至少一个跨模块/进程/安全负测 |

**已经替你决定好的（不准自己发挥）**
`target` 与 `capability` 分离；unknown MCP 默认 WRITE，destructiveHint 只能升级风险；ToolSpec declaration 不授予执行权限；返回结构化 ToolEvent。

**否定边界**：本卡不实现第二套 Agent Loop、不跨表外文件“顺手修复”、不降低旧 `RiskLevel`、不以 mock/live screenshot 替代契约验收。现有路径/版本/依赖不符即 `BLOCKED_PREREQUISITE`，提案修改先审计。

**操作步骤（依次执行；TEST-first）**
1. 在隔离工作树读本卡上游源文件及对应模块 README，`rg` 定位锚点，记录 baseline 与当前 commit；无锚点 STOP。
2. **先建 RED 测试**：在 `tests/web/w1/test_w1_c03_unit.py` 写 `test_w1_c03_contract`、`test_w1_c03_negative`，在 `tests/web/w1/test_w1_c03_module.py` 写 `test_w1_c03_integration`，先运行观察**预期失败**，保存日志。
3. 写 capability+version 序列化与校验的 RED tests
4. 将 shell/read/edit 等的末端 OS 操作改从 port 经过，而不是修改 Agent loop
5. 保留日志、Journal、期限与取消；核对选择的工具集不漂。
6. 同步必要协议/生成 TS、更新模块文档，复跑 Unit→Contract→Process/E2E，保存 diff 与证据，单卡可独立 revert。

**测试施工（函数名锁定；Given / When / Then）**
- Unit `tests/web/w1/test_w1_c03_unit.py::test_w1_c03_contract`：Given target 缺 desktop capability When 模型请求 screenshot Then 被统一门拒绝。
- Module `tests/web/w1/test_w1_c03_module.py::test_w1_c03_integration`：Given MCP 工具标 readOnlyHint When 走现有 gate Then 仍按默认 WRITE 审批或授权。
- 反向 `tests/web/w1/test_w1_c03_unit.py::test_w1_c03_negative`：Given invoke 未经 ToolOrchestrator When 尝试 NativeBackend Then 合同测试检测绕行。
- E2E / Process：本卡无独立 UI E2E；由对应 Phase 出口跨进程测试承接。
- 旧回归：任何碰 `core/` 或工具选取的卡加跑 `tests/test_cache/test_s1_s2_split.py` 和 `tests/test_cache/test_stable_prefix.py`；碰协议则加 `tests/test_protocol_schema.py`。

**验收命令（PowerShell；新测试文件由本卡创建，开卡前不得误判为已存在）**
```powershell
Set-Location 'D:\agent-demo\RxyCode\RxyCode1_1_0'
git status --short
rg -n --fixed-strings 'async def execute_tool' 'execution/tool_orchestrator.py'
rg -n --fixed-strings 'class RiskLevel' 'core/safety/policy.py'
python -m pytest 'tests/web/w1/test_w1_c03_unit.py' -q
python -m pytest 'tests/web/w1/test_w1_c03_module.py' -q
python -m pytest tests/test_protocol_schema.py -q
python -m pytest tests/test_cache/test_s1_s2_split.py tests/test_cache/test_stable_prefix.py -q
git diff --check
git status --short
```

**完成判据**
- [x] `test_w1_c03_contract`、`test_w1_c03_negative` 与 `test_w1_c03_integration` 全部真绿且无无故 skip。
- [x] 当前行为满足本卡冻结决策、现有 CLI/Desktop 回归符合期望。
- [x] 安全拒绝、失败和取消按本卡约束实测，未开发路径标 `BLOCKED` 而不是 PASS。
- [x] `evidence/web/WEB-W1-C03/` 有红绿日志、协议快照（若适用）、diff、人工复审与交接。

**Commit（仅此卡）**
`feat(web): web-w1-c03 - ExecutionPort + ToolSpec 能力域与唯一安全门`

---

### WEB-W1-C04 · Pydantic 统一协议/Schema 与 TS Codegen
`优先级：P0` / 预计工时：0.5–2.5 工程日 / 依赖：WEB-W1-C03 · **owner: protocol**

**背景与当前代码事实**
仓库已有 `protocol/requests.py`、notifications 与 schema/codegen，Web 需增加 Run、Event、Device 和错误码，必须保证旧 CLI/桌面不崩。

**涉及文件（白名单；`NEW` = 本卡新增，`VERIFY_EXISTING` = 本卡必须检查已有文件或前置卡产物；路径不符须 STOP/提交裁定）**
| 文件 | Grep 锚点/前置 | 允许的改法 |
|---|---|---|
| `protocol/requests.py` | `class PromptRequest` | 仅 additive 兼容字段 |
| `protocol/notifications.py` | `class` | 统一 event envelope 的旧映射 |
| `protocol/schema.py` | `export_schema` | 新增版本化导出 |
| `protocol/schema.json` | `$defs` | 由脚本再生不得手改 |
| `frontend/protocol-client/` | `VERIFY_EXISTING` | 只在真实可迁移条件下新增生成 type 消费（旧目录存在则 STOP 核实） |
| `packages/rxycode-protocol/src/rxycode_protocol/tool_rpc.py` | `ToolCall` | 再导出 protocol.requests 的同一 ToolCall/ToolChunk。裁定：否则 schema 与运行时各有一套 DTO |
| `tests/web/w1/test_w1_c04_unit.py` | `NEW` | 严格单元契约，不得替生产降级 |
| `tests/web/w1/test_w1_c04_module.py` | `NEW` | 至少一个跨模块/进程/安全负测 |

**已经替你决定好的（不准自己发挥）**
Python schema 为唯一来源；旧 initialize、session/prompt、approval/request 的名称和行为不更改；Run/Event/ToolRPC 须能从 schema 生成 TS，无第二套手写 DTO。

**否定边界**：本卡不实现第二套 Agent Loop、不跨表外文件“顺手修复”、不降低旧 `RiskLevel`、不以 mock/live screenshot 替代契约验收。现有路径/版本/依赖不符即 `BLOCKED_PREREQUISITE`，提案修改先审计。

**操作步骤（依次执行；TEST-first）**
1. 在隔离工作树读本卡上游源文件及对应模块 README，`rg` 定位锚点，记录 baseline 与当前 commit；无锚点 STOP。
2. **先建 RED 测试**：在 `tests/web/w1/test_w1_c04_unit.py` 写 `test_w1_c04_contract`、`test_w1_c04_negative`，在 `tests/web/w1/test_w1_c04_module.py` 写 `test_w1_c04_integration`，先运行观察**预期失败**，保存日志。
3. 补新增 Pydantic 模型与兼容 golden
4. 导出 JSON schema 并生成 TS
5. 写旧客户端回归；冻结 event names、errors、capabilities 并记录版本 digest。
6. 同步必要协议/生成 TS、更新模块文档，复跑 Unit→Contract→Process/E2E，保存 diff 与证据，单卡可独立 revert。

**测试施工（函数名锁定；Given / When / Then）**
- Unit `tests/web/w1/test_w1_c04_unit.py::test_w1_c04_contract`：Given 已有 JSON-RPC fixture When 用新 schema parse Then 与旧版结构一致。
- Module `tests/web/w1/test_w1_c04_module.py::test_w1_c04_integration`：Given Python Pydantic 模型导出 When 编译 TS Client Then 类型和版本 digest 匹配。
- 反向 `tests/web/w1/test_w1_c04_unit.py::test_w1_c04_negative`：Given 新 required 字段破坏旧客户端 When 解析 legacy fixture Then 兼容测试红。
- E2E / Process：本卡无独立 UI E2E；由对应 Phase 出口跨进程测试承接。
- 旧回归：任何碰 `core/` 或工具选取的卡加跑 `tests/test_cache/test_s1_s2_split.py` 和 `tests/test_cache/test_stable_prefix.py`；碰协议则加 `tests/test_protocol_schema.py`。

**验收命令（PowerShell；新测试文件由本卡创建，开卡前不得误判为已存在）**
```powershell
Set-Location 'D:\agent-demo\RxyCode\RxyCode1_1_0'
git status --short
rg -n --fixed-strings 'class PromptRequest' 'protocol/requests.py'
rg -n --fixed-strings 'class' 'protocol/notifications.py'
rg -n --fixed-strings 'export_schema' 'protocol/schema.py'
rg -n --fixed-strings '$defs' 'protocol/schema.json'
if (!(Test-Path 'frontend/protocol-client/')) { throw 'BLOCKED_PREREQUISITE: frontend/protocol-client/' }
python -m pytest 'tests/web/w1/test_w1_c04_unit.py' -q
python -m pytest 'tests/web/w1/test_w1_c04_module.py' -q
python -m pytest tests/test_protocol_schema.py -q
git diff --check
git status --short
```

**完成判据**
- [x] `test_w1_c04_contract`、`test_w1_c04_negative` 与 `test_w1_c04_integration` 全部真绿且无无故 skip。
- [x] 当前行为满足本卡冻结决策、现有 CLI/Desktop 回归符合期望。
- [x] 安全拒绝、失败和取消按本卡约束实测，未开发路径标 `BLOCKED` 而不是 PASS。
- [x] `evidence/web/WEB-W1-C04/` 有红绿日志、协议快照（若适用）、diff、人工复审与交接。

**Commit（仅此卡）**
`feat(web): web-w1-c04 - Pydantic 统一协议/Schema 与 TS Codegen`

---

### WEB-W1-C05 · 统一 CLI/Desktop/Web 核心入口与包测试
`优先级：P0` / 预计工时：0.5–2.5 工程日 / 依赖：WEB-W1-C01,WEB-W1-C02,WEB-W1-C03,WEB-W1-C04 · **owner: integration/core**

**背景与当前代码事实**
目标不是建立第二套 Web Agent；必须验证四入口在同一 Session、ToolOrchestrator、Provider 路径上。

**涉及文件（白名单；`NEW` = 本卡新增，`VERIFY_EXISTING` = 本卡必须检查已有文件或前置卡产物；路径不符须 STOP/提交裁定）**
| 文件 | Grep 锚点/前置 | 允许的改法 |
|---|---|---|
| `main.py` | `def cli` | 增加 web/connect 子命令接线预留（不在本卡实现设备）；entrypoint.py|cli|维持入口兼容 |
| `appserver/agent_worker.py` | `Session` | 过渡调用同一 Session |
| `frontend/protocol-client/` | `VERIFY_EXISTING` | 若已有路径仅添加 Web transport adapter 前置声明 |
| `tests/web/w1/test_w1_c05_unit.py` | `NEW` | 严格单元契约，不得替生产降级 |
| `tests/web/w1/test_w1_c05_module.py` | `NEW` | 至少一个跨模块/进程/安全负测 |

**已经替你决定好的（不准自己发挥）**
CLI、OpenTUI、Desktop 的原有启动命令/模型设置/前缀缓存语义不更改；Web 新入口走 core facade；monorepo 的分包只会发生一次 Agent 对象创建。

**否定边界**：本卡不实现第二套 Agent Loop、不跨表外文件“顺手修复”、不降低旧 `RiskLevel`、不以 mock/live screenshot 替代契约验收。现有路径/版本/依赖不符即 `BLOCKED_PREREQUISITE`，提案修改先审计。

**操作步骤（依次执行；TEST-first）**
1. 在隔离工作树读本卡上游源文件及对应模块 README，`rg` 定位锚点，记录 baseline 与当前 commit；无锚点 STOP。
2. **先建 RED 测试**：在 `tests/web/w1/test_w1_c05_unit.py` 写 `test_w1_c05_contract`、`test_w1_c05_negative`，在 `tests/web/w1/test_w1_c05_module.py` 写 `test_w1_c05_integration`，先运行观察**预期失败**，保存日志。
3. 建立 smoke fixture 比较三个旧入口与新 headless 路径
4. 补 `rxycode web --help` 的 CLI 占位（明确未完整交付）
5. 核对 installed wheel、typecheck、缓存与团队隔离。
6. 同步必要协议/生成 TS、更新模块文档，复跑 Unit→Contract→Process/E2E，保存 diff 与证据，单卡可独立 revert。

**测试施工（函数名锁定；Given / When / Then）**
- Unit `tests/web/w1/test_w1_c05_unit.py::test_w1_c05_contract`：Given 各入口相同测试任务 When 初始化 core Then 仅同一受测试 AgentRuntime 实现被使用。
- Module `tests/web/w1/test_w1_c05_module.py::test_w1_c05_integration`：Given 原 CLI/Web 参数 When 查看 `--help` Then 原命令未消失、新命令有明确说明。
- 反向 `tests/web/w1/test_w1_c05_unit.py::test_w1_c05_negative`：Given Web 代码依赖 Electron preload When 构建浏览器入口 Then 静态检查拒绝依赖。
- E2E / Process：本卡无独立 UI E2E；由对应 Phase 出口跨进程测试承接。
- 旧回归：任何碰 `core/` 或工具选取的卡加跑 `tests/test_cache/test_s1_s2_split.py` 和 `tests/test_cache/test_stable_prefix.py`；碰协议则加 `tests/test_protocol_schema.py`。

**验收命令（PowerShell；新测试文件由本卡创建，开卡前不得误判为已存在）**
```powershell
Set-Location 'D:\agent-demo\RxyCode\RxyCode1_1_0'
git status --short
rg -n --fixed-strings 'def cli' 'main.py'
rg -n --fixed-strings 'Session' 'appserver/agent_worker.py'
if (!(Test-Path 'frontend/protocol-client/')) { throw 'BLOCKED_PREREQUISITE: frontend/protocol-client/' }
python -m pytest 'tests/web/w1/test_w1_c05_unit.py' -q
python -m pytest 'tests/web/w1/test_w1_c05_module.py' -q
git diff --check
git status --short
```

**完成判据**
- [x] `test_w1_c05_contract`、`test_w1_c05_negative` 与 `test_w1_c05_integration` 全部真绿且无无故 skip。
- [x] 当前行为满足本卡冻结决策、现有 CLI/Desktop 回归符合期望。
- [x] 安全拒绝、失败和取消按本卡约束实测，未开发路径标 `BLOCKED` 而不是 PASS。
- [x] `evidence/web/WEB-W1-C05/` 有红绿日志、协议快照（若适用）、diff、人工复审与交接。

**Commit（仅此卡）**
`feat(web): web-w1-c05 - 统一 CLI/Desktop/Web 核心入口与包测试`

---

## §2 Wave 出口检查
- [ ] W1 所有卡各有独立 commit 和 evidence，未勾选项不被宣称完成。
- [ ] 既有行为回归没有被覆盖，新增 API 不依赖 mock/假状态。
- [ ] 运行期错误、权限拒绝和用户可见状态有负向证据。
