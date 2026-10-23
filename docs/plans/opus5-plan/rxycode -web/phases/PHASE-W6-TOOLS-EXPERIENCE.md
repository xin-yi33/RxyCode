# Phase W6 · TOOLS-EXPERIENCE（WEB 项目施工卡）

> **范围**：这是唯一可施工卡面，其他总设计文档不复制任务卡。执行旧项目卡时仍需服从旧 `DEV-ORDER.md`。每张卡独立分支/提交，严格遵守 `../00-WEB-EXECUTION-PLAN.md` WEB-R1–R12。

## §0 W6 前置与出口

共 6 张卡；开工先核实 upstream docs/code 与 `git status`，当前文件名只是目标设计，施工前须 `Test-Path`，不能因为示例而声称实现存在。

| 卡号 | 名称 | 前置 | owner |
|---|---|---|---|
| `WEB-W6-C01` | Tool Registry 差距盘点与 Capability 动态选择 | WEB-W4全部,WEB-W5-C01 | backend/tools |
| `WEB-W6-C02` | 精准编辑 / 结构化测试 / LSP 开发闭环 | WEB-W6-C01,WEB-W3-C04 | tools/coding |
| `WEB-W6-C03` | Browser Agent / Web Preview / Browser Handoff 分离 | WEB-W5-C04,WEB-W6-C01 | tools/browser |
| `WEB-W6-C04` | 多 Agent Plan/Todo/Activity Tree + Follow-up/Steer | WEB-W3-C06,WEB-W2-C03 | agent/frontend |
| `WEB-W6-C05` | Artifacts/Memory/Schedule/Notifications/Usage 用户闭环 | WEB-W6-C02,WEB-W3-C06 | product/backend+frontend |
| `WEB-W6-C06` | 端到端 Onboarding 与产品综合验收 | WEB-W6-C01..C05 | product/qa |

## §1 任务卡（TEST-first，可单卡施工）

### WEB-W6-C01 · Tool Registry 差距盘点与 Capability 动态选择
`优先级：P1` / 预计工时：0.5–2.5 工程日 / 依赖：WEB-W4全部,WEB-W5-C01 · **owner: backend/tools**

**背景与当前代码事实**
旧仓已有很多工具及 U24/U46 CU/Browser，不允许为了增加简历关键词重新造同名工具。

**涉及文件（白名单；`NEW` = 本卡新增，`VERIFY_EXISTING` = 本卡必须检查已有文件或前置卡产物；路径不符须 STOP/提交裁定）**
| 文件 | Grep 锚点/前置 | 允许的改法 |
|---|---|---|
| `core/builtin_tool_registration.py` | `register` | 核对已注册工具及作用域 |
| `execution/tool_orchestrator.py` | `select_tools` | 动态目标能力筛选 |
| `packages/rxycode-core/src/rxycode_core/tools/capability_catalog.py` | `NEW` | 能力域 registry 的只读投影 |
| `packages/rxycode-core/src/rxycode_core/tools/__init__.py` | `rxycode_core.tools` | 裁定：新目录必须是包，测试才能导入 capability_catalog。空标记，不放逻辑。 |
| `pyproject.toml` | `rxycode_core.tools` | 裁定：setuptools 的 packages 与 package-dir 必须带上 rxycode_core.tools，安装后的 wheel 才能导入 capability_catalog。 |
| `tests/web/w6/test_w6_c01_unit.py` | `NEW` | 严格单元契约，不得替生产降级 |
| `tests/web/w6/test_w6_c01_module.py` | `NEW` | 至少一个跨模块/进程/安全负测 |

**已经替你决定好的（不准自己发挥）**
ToolSpec 不因 FULL 而全部塞 prompt；MCP annotations 不能下调风险；`capability` 由目标声明，但仍需 PermissionPolicy 生效。

**否定边界**：本卡不实现第二套 Agent Loop、不跨表外文件“顺手修复”、不降低旧 `RiskLevel`、不以 mock/live screenshot 替代契约验收。现有路径/版本/依赖不符即 `BLOCKED_PREREQUISITE`，提案修改先审计。

**操作步骤（依次执行；TEST-first）**
1. 在隔离工作树读本卡上游源文件及对应模块 README，`rg` 定位锚点，记录 baseline 与当前 commit；无锚点 STOP。
2. **先建 RED 测试**：在 `tests/web/w6/test_w6_c01_unit.py` 写 `test_w6_c01_contract`、`test_w6_c01_negative`，在 `tests/web/w6/test_w6_c01_module.py` 写 `test_w6_c01_integration`，先运行观察**预期失败**，保存日志。
3. 生成可验证 Tool inventory 含 tool_name/capability/target/risk/timeout/idempotent
4. 补动态筛选与可观察选择原因
5. 与 Agent Token/选择精度 Eval 对比
6. 复用原 `ToolOrchestrator`。
7. 同步必要协议/生成 TS、更新模块文档，复跑 Unit→Contract→Process/E2E，保存 diff 与证据，单卡可独立 revert。

**测试施工（函数名锁定；Given / When / Then）**
- Unit `tests/web/w6/test_w6_c01_unit.py::test_w6_c01_contract`：Given cloud target When 选择工具 Then 不暴露 local desktop Input。
- Module `tests/web/w6/test_w6_c01_module.py::test_w6_c01_integration`：Given remote target 能力不足 When 选择工具 Then 显示明确不可用原因。
- 反向 `tests/web/w6/test_w6_c01_unit.py::test_w6_c01_negative`：Given 新 MCP 仅标 readOnlyHint When 分类 Then 不能降低到 READ。
- E2E / Process：本卡无独立 UI E2E；由对应 Phase 出口跨进程测试承接。
- 旧回归：任何碰 `core/` 或工具选取的卡加跑 `tests/test_cache/test_s1_s2_split.py` 和 `tests/test_cache/test_stable_prefix.py`；碰协议则加 `tests/test_protocol_schema.py`。

**验收命令（PowerShell；新测试文件由本卡创建，开卡前不得误判为已存在）**
```powershell
Set-Location 'D:\agent-demo\RxyCode\RxyCode1_1_0'
git status --short
rg -n --fixed-strings 'register' 'core/builtin_tool_registration.py'
rg -n --fixed-strings 'select_tools' 'execution/tool_orchestrator.py'
python -m pytest 'tests/web/w6/test_w6_c01_unit.py' -q
python -m pytest 'tests/web/w6/test_w6_c01_module.py' -q
python -m pytest tests/test_cache/test_s1_s2_split.py tests/test_cache/test_stable_prefix.py -q
git diff --check
git status --short
```

**完成判据**
- [x] `test_w6_c01_contract`、`test_w6_c01_negative` 与 `test_w6_c01_integration` 全部真绿且无无故 skip。
- [x] 当前行为满足本卡冻结决策、现有 CLI/Desktop 回归符合期望。
- [x] 安全拒绝、失败和取消按本卡约束实测，未开发路径标 `BLOCKED` 而不是 PASS。
- [x] `evidence/web/WEB-W6-C01/` 有红绿日志、协议快照（若适用）、diff、人工复审与交接。

**Commit（仅此卡）**
`feat(web): web-w6-c01 - Tool Registry 差距盘点与 Capability 动态选择`

---

### WEB-W6-C02 · 精准编辑 / 结构化测试 / LSP 开发闭环
`优先级：P1` / 预计工时：0.5–2.5 工程日 / 依赖：WEB-W6-C01,WEB-W3-C04 · **owner: tools/coding**

**背景与当前代码事实**
AI 全栈核心 Demo 必须能够靠工具真实修改代码、定位问题、运行测试并展示 Diff，而不是输出建议文本。

**涉及文件（白名单；`NEW` = 本卡新增，`VERIFY_EXISTING` = 本卡必须检查已有文件或前置卡产物；路径不符须 STOP/提交裁定）**
| 文件 | Grep 锚点/前置 | 允许的改法 |
|---|---|---|
| `packages/rxycode-core/src/rxycode_core/tools/coding_workflow.py` | `NEW` | apply_patch/LSP/test orchestration adaptor |
| `tools/edit.py` | `edit` | 仅复用现有 edit，先核文件 |
| `apps/web/src/features/tests/TestResults.tsx` | `NEW` | pytest/jest structured results |
| `tests/web/w6/test_w6_c02_unit.py` | `NEW` | 严格单元契约，不得替生产降级 |
| `tests/web/w6/test_w6_c02_module.py` | `NEW` | 至少一个跨模块/进程/安全负测 |

**已经替你决定好的（不准自己发挥）**
保留现有 `edit/patch` 真执行路径，任何新增强通过 ToolOrchestrator 和 Runner；测试结果从真实进程 exit/status 与解析生成，不让模型伪造。

**否定边界**：本卡不实现第二套 Agent Loop、不跨表外文件“顺手修复”、不降低旧 `RiskLevel`、不以 mock/live screenshot 替代契约验收。现有路径/版本/依赖不符即 `BLOCKED_PREREQUISITE`，提案修改先审计。

**操作步骤（依次执行；TEST-first）**
1. 在隔离工作树读本卡上游源文件及对应模块 README，`rg` 定位锚点，记录 baseline 与当前 commit；无锚点 STOP。
2. **先建 RED 测试**：在 `tests/web/w6/test_w6_c02_unit.py` 写 `test_w6_c02_contract`、`test_w6_c02_negative`，在 `tests/web/w6/test_w6_c02_module.py` 写 `test_w6_c02_integration`，先运行观察**预期失败**，保存日志。
3. 写多文件 patch 冲突/LSP 目标不存在/测试不通过 RED
4. 实现结构化 adapter、pytest/jest 解析和 UI 卡
5. 全链跑一个固定的示例 repo。
6. 同步必要协议/生成 TS、更新模块文档，复跑 Unit→Contract→Process/E2E，保存 diff 与证据，单卡可独立 revert。

**测试施工（函数名锁定；Given / When / Then）**
- Unit `tests/web/w6/test_w6_c02_unit.py::test_w6_c02_contract`：Given 错误的代码 When Agent 修复并运行 pytest Then 文件真实改变且 exit_code=0。
- Module `tests/web/w6/test_w6_c02_module.py::test_w6_c02_integration`：Given LSP 无对应语言服务 When 请求 refs Then 返回 unavailable 而非编造引用。
- 反向 `tests/web/w6/test_w6_c02_unit.py::test_w6_c02_negative`：Given 失败测试 When 生成报告 Then UI 不能标 green success。
- E2E / Process：E2E-WEB-04 完整 Coding 修改+单测+Diff 审阅。
- 旧回归：任何碰 `core/` 或工具选取的卡加跑 `tests/test_cache/test_s1_s2_split.py` 和 `tests/test_cache/test_stable_prefix.py`；碰协议则加 `tests/test_protocol_schema.py`。

**验收命令（PowerShell；新测试文件由本卡创建，开卡前不得误判为已存在）**
```powershell
Set-Location 'D:\agent-demo\RxyCode\RxyCode1_1_0'
git status --short
rg -n --fixed-strings 'edit' 'tools/edit.py'
python -m pytest 'tests/web/w6/test_w6_c02_unit.py' -q
python -m pytest 'tests/web/w6/test_w6_c02_module.py' -q
python -m pytest tests/test_cache/test_s1_s2_split.py tests/test_cache/test_stable_prefix.py -q
git diff --check
git status --short
```

**完成判据**
- [x] `test_w6_c02_contract`、`test_w6_c02_negative` 与 `test_w6_c02_integration` 全部真绿且无无故 skip。
- [x] 当前行为满足本卡冻结决策、现有 CLI/Desktop 回归符合期望。
- [x] 安全拒绝、失败和取消按本卡约束实测，未开发路径标 `BLOCKED` 而不是 PASS。
- [x] `evidence/web/WEB-W6-C02/` 有红绿日志、协议快照（若适用）、diff、人工复审与交接。

**Commit（仅此卡）**
`feat(web): web-w6-c02 - 精准编辑 / 结构化测试 / LSP 开发闭环`

---

### WEB-W6-C03 · Browser Agent / Web Preview / Browser Handoff 分离
`优先级：P1` / 预计工时：0.5–2.5 工程日 / 依赖：WEB-W5-C04,WEB-W6-C01 · **owner: tools/browser**

**背景与当前代码事实**
Playwright MCP 与用户 Chrome CDP 是现有能力；要把 Web 自动化、网页预览与授权交接区分，不能静默附着用户日常浏览器。

**涉及文件（白名单；`NEW` = 本卡新增，`VERIFY_EXISTING` = 本卡必须检查已有文件或前置卡产物；路径不符须 STOP/提交裁定）**
| 文件 | Grep 锚点/前置 | 允许的改法 |
|---|---|---|
| `core/cu/` | `VERIFY_EXISTING` | 只核实已有 Computer Use 接线 |
| `packages/rxycode-runner/src/rxycode_runner/browser/session_manager.py` | `NEW` | 管理 agent browser context |
| `packages/rxycode-runner/src/rxycode_runner/browser/__init__.py` | `rxycode_runner.browser` | 裁定：新目录必须是包，测试才能导入 session_manager。空标记，不放逻辑。 |
| `pyproject.toml` | `rxycode_runner.browser` | 裁定：setuptools 的 packages 与 package-dir 必须带上 rxycode_runner.browser，安装后的 wheel 才能导入 session_manager。 |
| `apps/web/src/features/browser/BrowserHandoff.tsx` | `NEW` | 显示授权登录接管流程 |
| `apps/web/src/app/App.tsx` | `BrowserHandoff` | 裁定：应用壳必须挂上 `/browser/:sessionId`，授权按钮才是用户能打开的页面，而不是只被测试引用。 |
| `tests/web/w6/test_w6_c03_unit.py` | `NEW` | 严格单元契约，不得替生产降级 |
| `tests/web/w6/test_w6_c03_module.py` | `NEW` | 至少一个跨模块/进程/安全负测 |

**已经替你决定好的（不准自己发挥）**
Browser Agent profile 与 Web 预览隔离；登录接管需要用户明确授权；U24/U46 的工具名/注册表不重写；Browser 不等同于 webfetch。

**否定边界**：本卡不实现第二套 Agent Loop、不跨表外文件“顺手修复”、不降低旧 `RiskLevel`、不以 mock/live screenshot 替代契约验收。现有路径/版本/依赖不符即 `BLOCKED_PREREQUISITE`，提案修改先审计。

**操作步骤（依次执行；TEST-first）**
1. 在隔离工作树读本卡上游源文件及对应模块 README，`rg` 定位锚点，记录 baseline 与当前 commit；无锚点 STOP。
2. **先建 RED 测试**：在 `tests/web/w6/test_w6_c03_unit.py` 写 `test_w6_c03_contract`、`test_w6_c03_negative`，在 `tests/web/w6/test_w6_c03_module.py` 写 `test_w6_c03_integration`，先运行观察**预期失败**，保存日志。
3. 建立 cookie/profile 隔离/错误 URL/用户手动接管 RED
4. 对接现有 Playwright MCP adapter，添加会话生命周期
5. 串接 Web 预览和 Browser Handoff UI
6. 跑基线 E2E 测试。
7. 同步必要协议/生成 TS、更新模块文档，复跑 Unit→Contract→Process/E2E，保存 diff 与证据，单卡可独立 revert。

**测试施工（函数名锁定；Given / When / Then）**
- Unit `tests/web/w6/test_w6_c03_unit.py::test_w6_c03_contract`：Given 工具打开网页 When browser navigate/click Then 在隔离浏览器 profile 获取真实 DOM 结果。
- Module `tests/web/w6/test_w6_c03_module.py::test_w6_c03_integration`：Given用户点击接管 When 授权 Then Agent 可继续指定浏览器会话。
- 反向 `tests/web/w6/test_w6_c03_unit.py::test_w6_c03_negative`：Given 未授权 When 浏览器需要用户 cookie Then 不共享用户 Chrome 数据。
- E2E / Process：E2E-BROWSER-01 真实公开测试页面 navigate/click/snapshot，Cookie 不泄漏。
- 旧回归：任何碰 `core/` 或工具选取的卡加跑 `tests/test_cache/test_s1_s2_split.py` 和 `tests/test_cache/test_stable_prefix.py`；碰协议则加 `tests/test_protocol_schema.py`。

**验收命令（PowerShell；新测试文件由本卡创建，开卡前不得误判为已存在）**
```powershell
Set-Location 'D:\agent-demo\RxyCode\RxyCode1_1_0'
git status --short
if (!(Test-Path 'core/cu/')) { throw 'BLOCKED_PREREQUISITE: core/cu/' }
python -m pytest 'tests/web/w6/test_w6_c03_unit.py' -q
python -m pytest 'tests/web/w6/test_w6_c03_module.py' -q
python -m pytest tests/test_cache/test_s1_s2_split.py tests/test_cache/test_stable_prefix.py -q
git diff --check
git status --short
```

**完成判据**
- [x] `test_w6_c03_contract`、`test_w6_c03_negative` 与 `test_w6_c03_integration` 全部真绿且无无故 skip。
- [x] 当前行为满足本卡冻结决策、现有 CLI/Desktop 回归符合期望。
- [x] 安全拒绝、失败和取消按本卡约束实测，未开发路径标 `BLOCKED` 而不是 PASS。
- [x] `evidence/web/WEB-W6-C03/` 有红绿日志、协议快照（若适用）、diff、人工复审与交接。

**Commit（仅此卡）**
`feat(web): web-w6-c03 - Browser Agent / Web Preview / Browser Handoff 分离`

---

### WEB-W6-C04 · 多 Agent Plan/Todo/Activity Tree + Follow-up/Steer
`优先级：P1` / 预计工时：0.5–2.5 工程日 / 依赖：WEB-W3-C06,WEB-W2-C03 · **owner: agent/frontend**

**背景与当前代码事实**
RXYCode 已有 F 系列 Team、Todo、Activity、Follow-up，不该另建 Planner；Web 只需要统一事件/可操作计划。

**涉及文件（白名单；`NEW` = 本卡新增，`VERIFY_EXISTING` = 本卡必须检查已有文件或前置卡产物；路径不符须 STOP/提交裁定）**
| 文件 | Grep 锚点/前置 | 允许的改法 |
|---|---|---|
| `core/agents/` | `VERIFY_EXISTING` | 只核既有多 Agent 加载/消息路径 |
| `packages/rxycode-worker/src/rxycode_worker/agent_events.py` | `NEW` | parent/child events 映射 |
| `apps/web/src/features/agents/AgentTree.tsx` | `NEW` | parent/child DAG 投影, operator controls |
| `apps/web/src/features/chat/ChatPage.tsx` | `AgentTree` | 裁定：聊天页要把 parent_id 和 tokens 传给 AgentTree，生产页才显示这棵树。 |
| `apps/web/src/features/runs/eventReducer.ts` | `agent.started` | 裁定：运行投影保留 parent_id 与 tokens，树才有真实父子和花费。 |
| `core/tracing.py` | `format_team_tree` | 裁定：现有 replay 用 project_run 组父子，生产回放和网页树共用这一次投影。 |
| `packages/rxycode-server/src/rxycode_server/api/runs.py` | `/steer` | 裁定：网页 steer 和子会话取消走既有 run 的 server 命令，提交后交给已绑定的 worker。 |
| `appserver/agent_task.py` | `event/agent_started` | 裁定：AgentTask 在发出生命周期通知时，把同一条写入网页 run 日志。 |
| `appserver/agent_worker.py` | `bind_core_session` | 裁定：活会话绑上 worker，已提交的 steer 才能进入这个进程的队列。 |
| `appserver/agent_runtime.py` | `spawn` | 裁定：生产 spawn 把网页 run 日志挂到 AgentTask，生命周期事件才写入这次 run。 |
| `core/subagents/manager.py` | `get_tree` | 裁定：取会话树时登记 manager，并保留活着的子 runtime，子取消才能调到 cancel。 |
| `packages/rxycode-server/src/rxycode_server/main.py` | `create_app` | 裁定：网页进程用自己的 database_url 发布给 worker，不靠测试临时写三个环境变量。 |
| `tests/web/w6/test_w6_c04_unit.py` | `NEW` | 严格单元契约，不得替生产降级 |
| `tests/web/w6/test_w6_c04_module.py` | `NEW` | 至少一个跨模块/进程/安全负测 |

**已经替你决定好的（不准自己发挥）**
子 Agent 真有任务边界/角色/成本/取消；Plan 修改作为 server 命令，不能直接改 EventStore；solo/team 支出统计可解释。

**否定边界**：本卡不实现第二套 Agent Loop、不跨表外文件“顺手修复”、不降低旧 `RiskLevel`、不以 mock/live screenshot 替代契约验收。现有路径/版本/依赖不符即 `BLOCKED_PREREQUISITE`，提案修改先审计。

**操作步骤（依次执行；TEST-first）**
1. 在隔离工作树读本卡上游源文件及对应模块 README，`rg` 定位锚点，记录 baseline 与当前 commit；无锚点 STOP。
2. **先建 RED 测试**：在 `tests/web/w6/test_w6_c04_unit.py` 写 `test_w6_c04_contract`、`test_w6_c04_negative`，在 `tests/web/w6/test_w6_c04_module.py` 写 `test_w6_c04_integration`，先运行观察**预期失败**，保存日志。
3. 建立团队事件 parent_id/reasoning.summary/取消和 Followup 吞吐测试
4. adapter 现有 F3/F12/F14 事件，不改团队调度算法
5. 在 UI 展示子 Agent、Plan/Todo 和流中 steer
6. 比较 solo/team。
7. 同步必要协议/生成 TS、更新模块文档，复跑 Unit→Contract→Process/E2E，保存 diff 与证据，单卡可独立 revert。

**测试施工（函数名锁定；Given / When / Then）**
- Unit `tests/web/w6/test_w6_c04_unit.py::test_w6_c04_contract`：Given 真实 Team Run When 子 Agent 开始/结束 Then 树有真实 parent_id/status。
- Module `tests/web/w6/test_w6_c04_module.py::test_w6_c04_integration`：Given 用户运行时 steer When Worker 接受 Then 在原有 Run 内按明确顺序生效。
- 反向 `tests/web/w6/test_w6_c04_unit.py::test_w6_c04_negative`：Given child intermediate When render final Then 不进入主最终答复。
- E2E / Process：E2E-TEAM-01 真实 Team task 显示 delegated trace 且 refresh 重放无漏。
- 旧回归：任何碰 `core/` 或工具选取的卡加跑 `tests/test_cache/test_s1_s2_split.py` 和 `tests/test_cache/test_stable_prefix.py`；碰协议则加 `tests/test_protocol_schema.py`。

**验收命令（PowerShell；新测试文件由本卡创建，开卡前不得误判为已存在）**
```powershell
Set-Location 'D:\agent-demo\RxyCode\RxyCode1_1_0'
git status --short
if (!(Test-Path 'core/agents/')) { throw 'BLOCKED_PREREQUISITE: core/agents/' }
python -m pytest 'tests/web/w6/test_w6_c04_unit.py' -q
python -m pytest 'tests/web/w6/test_w6_c04_module.py' -q
python -m pytest tests/test_cache/test_s1_s2_split.py tests/test_cache/test_stable_prefix.py -q
git diff --check
git status --short
```

**完成判据**
- [x] `test_w6_c04_contract`、`test_w6_c04_negative` 与 `test_w6_c04_integration` 全部真绿且无无故 skip。
- [x] 当前行为满足本卡冻结决策、现有 CLI/Desktop 回归符合期望。
- [x] 安全拒绝、失败和取消按本卡约束实测，未开发路径标 `BLOCKED` 而不是 PASS。
- [x] `evidence/web/WEB-W6-C04/` 有红绿日志、协议快照（若适用）、diff、人工复审与交接。

**Commit（仅此卡）**
`feat(web): web-w6-c04 - 多 Agent Plan/Todo/Activity Tree + Follow-up/Steer`

---

### WEB-W6-C05 · Artifacts/Memory/Schedule/Notifications/Usage 用户闭环
`优先级：P1` / 预计工时：0.5–2.5 工程日 / 依赖：WEB-W6-C02,WEB-W3-C06 · **owner: product/backend+frontend**

**背景与当前代码事实**
只有聊天面板无法用于日常工作，用户要拿到产物、管理记忆、调度后台任务、查看费用及收到审批通知。

**涉及文件（白名单；`NEW` = 本卡新增，`VERIFY_EXISTING` = 本卡必须检查已有文件或前置卡产物；路径不符须 STOP/提交裁定）**
| 文件 | Grep 锚点/前置 | 允许的改法 |
|---|---|---|
| `apps/web/src/features/usage/UsagePage.tsx` | `NEW` | 模型费用/日期筛选 |
| `apps/web/src/features/memory/MemoryPage.tsx` | `NEW` | 记忆查看/编辑/删除 |
| `apps/web/src/features/schedule/SchedulePage.tsx` | `NEW` | 调度与通知开关 |
| `packages/rxycode-server/src/rxycode_server/notifications/service.py` | `NEW` | 审批/完成通知/隐私/退订 |
| `tests/web/w6/test_w6_c05_unit.py` | `NEW` | 严格单元契约，不得替生产降级 |
| `tests/web/w6/test_w6_c05_module.py` | `NEW` | 至少一个跨模块/进程/安全负测 |
| `packages/rxycode-server/src/rxycode_server/notifications/__init__.py` | `rxycode_server.notifications` | 裁定：新目录必须是包，测试才能导入通知服务。 |
| `packages/rxycode-server/src/rxycode_server/usage/service.py` | `usage_cost_kind` | 裁定：费用页沿用既有价表区分确认值和估算值。 |
| `packages/rxycode-server/src/rxycode_server/main.py` | `include_router` | 裁定：网页进程挂上用量、记忆、通知路由。 |
| `apps/web/src/app/App.tsx` | `/usage` | 裁定：应用壳挂上用量、记忆和调度页。 |
| `packages/rxycode-server/src/rxycode_server/runs/service.py` | `complete_run` | 裁定：Run 进入终态时由 complete_run 发一次通知。 |
| `packages/rxycode-worker/src/rxycode_worker/supervisor.py` | `commit_terminal` | 裁定：worker 提交终态后通知该调度的用户。 |

**已经替你决定好的（不准自己发挥）**
记忆归属按 tenant/project；Schedule 复用旧 `ScheduleService` 语义但不让 appserver 单进程做云端所有任务；通知基于 DB 终态幂等发送；费用显示为估算或确认值。

**否定边界**：本卡不实现第二套 Agent Loop、不跨表外文件“顺手修复”、不降低旧 `RiskLevel`、不以 mock/live screenshot 替代契约验收。现有路径/版本/依赖不符即 `BLOCKED_PREREQUISITE`，提案修改先审计。

**操作步骤（依次执行；TEST-first）**
1. 在隔离工作树读本卡上游源文件及对应模块 README，`rg` 定位锚点，记录 baseline 与当前 commit；无锚点 STOP。
2. **先建 RED 测试**：在 `tests/web/w6/test_w6_c05_unit.py` 写 `test_w6_c05_contract`、`test_w6_c05_negative`，在 `tests/web/w6/test_w6_c05_module.py` 写 `test_w6_c05_integration`，先运行观察**预期失败**，保存日志。
3. 先写跨租户 memory/重复通知/调度不存在目标 RED
4. 接真实 API 实现页
5. EventStore/usage_records 驱动完成和费用显示
6. 设置页支持设备/通知/密钥管理。
7. 同步必要协议/生成 TS、更新模块文档，复跑 Unit→Contract→Process/E2E，保存 diff 与证据，单卡可独立 revert。

**测试施工（函数名锁定；Given / When / Then）**
- Unit `tests/web/w6/test_w6_c05_unit.py::test_w6_c05_contract`：Given 用户有多 Run When 打开 Usage Then Token/成本与记录一致。
- Module `tests/web/w6/test_w6_c05_module.py::test_w6_c05_integration`：Given Schedule 触发 When 浏览器关闭 Then 创建持久 Run 并能收到状态通知。
- 反向 `tests/web/w6/test_w6_c05_unit.py::test_w6_c05_negative`：Given A 用户访问 B memory 或通知 When 请求 Then 不泄漏任何内容。
- E2E / Process：E2E-PRODUCT-01 创建定时任务→后台触发→通知→Web 展示产物和成本。
- 旧回归：任何碰 `core/` 或工具选取的卡加跑 `tests/test_cache/test_s1_s2_split.py` 和 `tests/test_cache/test_stable_prefix.py`；碰协议则加 `tests/test_protocol_schema.py`。

**验收命令（PowerShell；新测试文件由本卡创建，开卡前不得误判为已存在）**
```powershell
Set-Location 'D:\agent-demo\RxyCode\RxyCode1_1_0'
git status --short
python -m pytest 'tests/web/w6/test_w6_c05_unit.py' -q
python -m pytest 'tests/web/w6/test_w6_c05_module.py' -q
git diff --check
git status --short
```

**完成判据**
- [x] `test_w6_c05_contract`、`test_w6_c05_negative` 与 `test_w6_c05_integration` 全部真绿且无无故 skip。
- [x] 当前行为满足本卡冻结决策、现有 CLI/Desktop 回归符合期望。
- [x] 安全拒绝、失败和取消按本卡约束实测，未开发路径标 `BLOCKED` 而不是 PASS。
- [x] `evidence/web/WEB-W6-C05/` 有红绿日志、协议快照（若适用）、diff、人工复审与交接。

**Commit（仅此卡）**
`feat(web): web-w6-c05 - Artifacts/Memory/Schedule/Notifications/Usage 用户闭环`

---

### WEB-W6-C06 · 端到端 Onboarding 与产品综合验收
`优先级：P1` / 预计工时：0.5–2.5 工程日 / 依赖：WEB-W6-C01..C05 · **owner: product/qa**

**背景与当前代码事实**
产品最终应使首次登录的用户可以自行完成任务，不依赖开发者手动改环境或绕过一页功能。

**涉及文件（白名单；`NEW` = 本卡新增，`VERIFY_EXISTING` = 本卡必须检查已有文件或前置卡产物；路径不符须 STOP/提交裁定）**
| 文件 | Grep 锚点/前置 | 允许的改法 |
|---|---|---|
| `apps/web/src/features/onboarding/` | `VERIFY_EXISTING` | 综合用户旅程细节 |
| `apps/web/e2e/coding-workflow.spec.ts` | `NEW` | 完整 Cloud Coding |
| `apps/web/e2e/remote-full.spec.ts` | `NEW` | 本机 grant 和设备管理 |
| `docs/product/user-guide.md` | `NEW` | 面向终端用户的安装/疑难排查 |
| `tests/web/w6/test_w6_c06_unit.py` | `NEW` | 严格单元契约，不得替生产降级 |
| `tests/web/w6/test_w6_c06_module.py` | `NEW` | 至少一个跨模块/进程/安全负测 |
| `packages/rxycode-server/src/rxycode_server/release/__init__.py` | `rxycode_server.release` | 裁定：新目录必须是包，测试才能导入 journey。空标记，不放逻辑。 |
| `packages/rxycode-server/src/rxycode_server/release/journey.py` | `cloud_release_journey` | 裁定：首次旅程调用既有登录、导入白名单、create_run、真实 pytest 和产物下载。测试只断言这些结果。 |
| `.gitignore` | `docs/product` | 裁定：用户指南落在 docs/product。父仓 docs/* 会忽略它，必须重新纳入该目录才能提交。 |

**已经替你决定好的（不准自己发挥）**
所有用户步骤需要真实后端，不得使用 mocked tool events 冒充 Demo；Full UI 必须显示目前权限和执行目标；初次安装/断线/失败都能恢复。

**否定边界**：本卡不实现第二套 Agent Loop、不跨表外文件“顺手修复”、不降低旧 `RiskLevel`、不以 mock/live screenshot 替代契约验收。现有路径/版本/依赖不符即 `BLOCKED_PREREQUISITE`，提案修改先审计。

**操作步骤（依次执行；TEST-first）**
1. 在隔离工作树读本卡上游源文件及对应模块 README，`rg` 定位锚点，记录 baseline 与当前 commit；无锚点 STOP。
2. **先建 RED 测试**：在 `tests/web/w6/test_w6_c06_unit.py` 写 `test_w6_c06_contract`、`test_w6_c06_negative`，在 `tests/web/w6/test_w6_c06_module.py` 写 `test_w6_c06_integration`，先运行观察**预期失败**，保存日志。
3. 按 PRD 走真实新用户旅程找阻塞
4. 逐一修掉跨页面失败点但不越卡白名单（必要新卡）
5. 全流程 Desktop/CLI 回归
6. 制作用户指南和截图（标明版本/状态）。
7. 同步必要协议/生成 TS、更新模块文档，复跑 Unit→Contract→Process/E2E，保存 diff 与证据，单卡可独立 revert。

**测试施工（函数名锁定；Given / When / Then）**
- Unit `tests/web/w6/test_w6_c06_unit.py::test_w6_c06_contract`：Given新 Cloud 用户 When 依次登录、导入、创建 Run Then 完成真实测试及下载 Artifact。
- Module `tests/web/w6/test_w6_c06_module.py::test_w6_c06_integration`：Given新 Local 用户 When rxycode web + Full Then 可本机执行无害真实操作。
- 反向 `tests/web/w6/test_w6_c06_unit.py::test_w6_c06_negative`：Given用户未配对设备 When 选 Remote Full Then 不会在云端擅自 Full 执行。
- E2E / Process：E2E-RELEASE-01 Cloud/Local/Remote 三主场景均真跑，关页恢复对照日志。
- 旧回归：任何碰 `core/` 或工具选取的卡加跑 `tests/test_cache/test_s1_s2_split.py` 和 `tests/test_cache/test_stable_prefix.py`；碰协议则加 `tests/test_protocol_schema.py`。

**验收命令（PowerShell；新测试文件由本卡创建，开卡前不得误判为已存在）**
```powershell
Set-Location 'D:\agent-demo\RxyCode\RxyCode1_1_0'
git status --short
if (!(Test-Path 'apps/web/src/features/onboarding/')) { throw 'BLOCKED_PREREQUISITE: apps/web/src/features/onboarding/' }
python -m pytest 'tests/web/w6/test_w6_c06_unit.py' -q
python -m pytest 'tests/web/w6/test_w6_c06_module.py' -q
git diff --check
git status --short
```

**完成判据**
- [x] `test_w6_c06_contract`、`test_w6_c06_negative` 与 `test_w6_c06_integration` 全部真绿且无无故 skip。
- [x] 当前行为满足本卡冻结决策、现有 CLI/Desktop 回归符合期望。
- [x] 安全拒绝、失败和取消按本卡约束实测，未开发路径标 `BLOCKED` 而不是 PASS。
- [x] `evidence/web/WEB-W6-C06/` 有红绿日志、协议快照（若适用）、diff、人工复审与交接。

**Commit（仅此卡）**
`feat(web): web-w6-c06 - 端到端 Onboarding 与产品综合验收`

---

## §2 Wave 出口检查
- [ ] W6 所有卡各有独立 commit 和 evidence，未勾选项不被宣称完成。
- [ ] 既有行为回归没有被覆盖，新增 API 不依赖 mock/假状态。
- [ ] 运行期错误、权限拒绝和用户可见状态有负向证据。
