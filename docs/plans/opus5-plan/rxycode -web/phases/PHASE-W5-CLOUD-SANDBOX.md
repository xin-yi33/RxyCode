# Phase W5 · CLOUD-SANDBOX（WEB 项目施工卡）

> **范围**：这是唯一可施工卡面，其他总设计文档不复制任务卡。执行旧项目卡时仍需服从旧 `DEV-ORDER.md`。每张卡独立分支/提交，严格遵守 `../00-WEB-EXECUTION-PLAN.md` WEB-R1–R12。

## §0 W5 前置与出口

共 6 张卡；开工先核实 upstream docs/code 与 `git status`，当前文件名只是目标设计，施工前须 `Test-Path`，不能因为示例而声称实现存在。

| 卡号 | 名称 | 前置 | owner |
|---|---|---|---|
| `WEB-W5-C01` | Cloud SandboxProvider 可替换控制面 | WEB-W2-C03,WEB-W1-C03 | backend/cloud |
| `WEB-W5-C02` | 云端文件/网络/CPU/进程/Secret 租户隔离 | WEB-W5-C01 | security/cloud |
| `WEB-W5-C03` | 工作区 Provision/Repo checkout/工件快照 | WEB-W5-C01,WEB-W5-C02 | backend/cloud |
| `WEB-W5-C04` | 隔离 Port Preview、浏览器会话和 API 代理 | WEB-W5-C01,WEB-W5-C03 | backend/browser |
| `WEB-W5-C05` | GitHub OAuth Repo/Branch/Commit/PR 闭环 | WEB-W5-C03,WEB-W5-C04 | backend/integrations |
| `WEB-W5-C06` | Cloud 并发、队列隔离、预览/沙箱费用上限 | WEB-W5-C01..C05 | backend/ops |

## §1 任务卡（TEST-first，可单卡施工）

### WEB-W5-C01 · Cloud SandboxProvider 可替换控制面
`优先级：P0` / 预计工时：0.5–2.5 工程日 / 依赖：WEB-W2-C03,WEB-W1-C03 · **owner: backend/cloud**

**背景与当前代码事实**
旧 OS sandbox 只包 Shell，云多租户需要真正隔离执行端，可选 Docker+gVisor，后期可替换 VM。

**涉及文件（白名单；`NEW` = 本卡新增，`VERIFY_EXISTING` = 本卡必须检查已有文件或前置卡产物；路径不符须 STOP/提交裁定）**
| 文件 | Grep 锚点/前置 | 允许的改法 |
|---|---|---|
| `packages/rxycode-runner/src/rxycode_runner/sandbox/provider.py` | `NEW` | create/attach/stop/destroy/health interface。裁定：锁定契约要在隔离资源里执行工具，所以同一文件提供 exec，不另开端点文件。 |
| `packages/rxycode-runner/src/rxycode_runner/sandbox/gvisor.py` | `NEW` | runc/runtimeClass adapter。裁定：daemon 有 runsc 时用 runsc；没有则用 runc 容器。点名的 runtime 不在 daemon 列表里就 fail-closed，不回退到宿主 subprocess。 |
| `packages/rxycode-runner/src/rxycode_runner/sandbox/__init__.py` | `rxycode_runner.sandbox` | 裁定：新目录必须是包，测试才能导入 provider 和 gvisor。空标记，不放逻辑。 |
| `packages/rxycode-server/src/rxycode_server/sandbox/__init__.py` | `rxycode_server.sandbox` | 裁定：新目录必须是包，测试才能导入控制面。空标记，不放逻辑。 |
| `packages/rxycode-server/src/rxycode_server/sandbox/control.py` | `NEW` | tenant→workspace map。裁定：sandboxd 工具入口、目标派生、启动/销毁/账单记在这个文件。Run 只记账，不拥有沙箱生命周期。 |
| `tests/web/w5/test_w5_c01_unit.py` | `NEW` | 严格单元契约，不得替生产降级 |
| `tests/web/w5/test_w5_c01_module.py` | `NEW` | 至少一个跨模块/进程/安全负测 |

**已经替你决定好的（不准自己发挥）**
Cloud 绝不 fallback 到 Server 宿主本机 subprocess；SandboxProvider 生命周期独立于 Run、支持保留或销毁策略；无隔离 capability 就 fail-closed。

**否定边界**：本卡不实现第二套 Agent Loop、不跨表外文件“顺手修复”、不降低旧 `RiskLevel`、不以 mock/live screenshot 替代契约验收。现有路径/版本/依赖不符即 `BLOCKED_PREREQUISITE`，提案修改先审计。

**操作步骤（依次执行；TEST-first）**
1. 在隔离工作树读本卡上游源文件及对应模块 README，`rg` 定位锚点，记录 baseline 与当前 commit；无锚点 STOP。
2. **先建 RED 测试**：在 `tests/web/w5/test_w5_c01_unit.py` 写 `test_w5_c01_contract`、`test_w5_c01_negative`，在 `tests/web/w5/test_w5_c01_module.py` 写 `test_w5_c01_integration`，先运行观察**预期失败**，保存日志。
3. 先写 runtime unavailable/attach-other-tenant RED
4. 实现 SandboxProvider 及显式能力错误
5. 实现 sandboxd 工具 endpoint 与目标派生
6. 记录启动/销毁/账单。
7. 同步必要协议/生成 TS、更新模块文档，复跑 Unit→Contract→Process/E2E，保存 diff 与证据，单卡可独立 revert。

**测试施工（函数名锁定；Given / When / Then）**
- Unit `tests/web/w5/test_w5_c01_unit.py::test_w5_c01_contract`：Given tenant A 创建 sandbox When 运行 exec Then 在隔离资源中执行而非 Server 主机。
- Module `tests/web/w5/test_w5_c01_module.py::test_w5_c01_integration`：Given Runtime unavailable When 创建 Run Then 阻止工具并明确目标不可用。
- 反向 `tests/web/w5/test_w5_c01_unit.py::test_w5_c01_negative`：Given tenant B 知道 A sandbox ID When attach Then 严格拒绝。
- E2E / Process：本卡无独立 UI E2E；由对应 Phase 出口跨进程测试承接。
- 旧回归：任何碰 `core/` 或工具选取的卡加跑 `tests/test_cache/test_s1_s2_split.py` 和 `tests/test_cache/test_stable_prefix.py`；碰协议则加 `tests/test_protocol_schema.py`。

**验收命令（PowerShell；新测试文件由本卡创建，开卡前不得误判为已存在）**
```powershell
Set-Location 'D:\agent-demo\RxyCode\RxyCode1_1_0'
git status --short
python -m pytest 'tests/web/w5/test_w5_c01_unit.py' -q
python -m pytest 'tests/web/w5/test_w5_c01_module.py' -q
git diff --check
git status --short
```

**完成判据**
- [x] `test_w5_c01_contract`、`test_w5_c01_negative` 与 `test_w5_c01_integration` 全部真绿且无无故 skip。
- [x] 当前行为满足本卡冻结决策、现有 CLI/Desktop 回归符合期望。
- [x] 安全拒绝、失败和取消按本卡约束实测，未开发路径标 `BLOCKED` 而不是 PASS。
- [x] `evidence/web/WEB-W5-C01/` 有红绿日志、协议快照（若适用）、diff、人工复审与交接。

**Commit（仅此卡）**
`feat(web): web-w5-c01 - Cloud SandboxProvider 可替换控制面`

---

### WEB-W5-C02 · 云端文件/网络/CPU/进程/Secret 租户隔离
`优先级：P0` / 预计工时：0.5–2.5 工程日 / 依赖：WEB-W5-C01 · **owner: security/cloud**

**背景与当前代码事实**
多租户公共 Demo 不可依赖 OS shell 黑名单，必须验证真正的文件、UID、网络、资源隔离。

**涉及文件（白名单；`NEW` = 本卡新增，`VERIFY_EXISTING` = 本卡必须检查已有文件或前置卡产物；路径不符须 STOP/提交裁定）**
| 文件 | Grep 锚点/前置 | 允许的改法 |
|---|---|---|
| `packages/rxycode-runner/src/rxycode_runner/sandbox/policy.py` | `NEW` | 租户资源限额/网络/secret policy |
| `infra/compose/sandbox-policy.yaml` | `NEW` | 候选运行时安全配置 |
| `packages/rxycode-runner/src/rxycode_runner/sandbox/egress.py` | `NEW` | 出站策略/metadata block |
| `packages/rxycode-runner/src/rxycode_runner/sandbox/gvisor.py` | `create` | 裁定：create 套用 SandboxPolicy 的 user、memory、cpu、pids、network 和 cap，并按 ttl 停止。不挂宿主路径，不把宿主环境变量送进容器。 |
| `tests/web/w5/test_w5_c02_unit.py` | `NEW` | 严格单元契约，不得替生产降级 |
| `tests/web/w5/test_w5_c02_module.py` | `NEW` | 至少一个跨模块/进程/安全负测 |

**已经替你决定好的（不准自己发挥）**
禁止 privileged、Docker socket、全宿主 mount；默认限制元数据/内网网络访问，CPU/memory/pids/TTL；sandbox 内运行 Full 也不能突破 OS 边界。

**否定边界**：本卡不实现第二套 Agent Loop、不跨表外文件“顺手修复”、不降低旧 `RiskLevel`、不以 mock/live screenshot 替代契约验收。现有路径/版本/依赖不符即 `BLOCKED_PREREQUISITE`，提案修改先审计。

**操作步骤（依次执行；TEST-first）**
1. 在隔离工作树读本卡上游源文件及对应模块 README，`rg` 定位锚点，记录 baseline 与当前 commit；无锚点 STOP。
2. **先建 RED 测试**：在 `tests/web/w5/test_w5_c02_unit.py` 写 `test_w5_c02_contract`、`test_w5_c02_negative`，在 `tests/web/w5/test_w5_c02_module.py` 写 `test_w5_c02_integration`，先运行观察**预期失败**，保存日志。
3. 写 host-path/net-metadata/memory bomb 模拟攻击预期拒绝
4. 实现 gVisor/VM 配置验证和资源观测
5. 扫描镜像的 secrets、uid 和进程边界
6. 失败永不降级。
7. 同步必要协议/生成 TS、更新模块文档，复跑 Unit→Contract→Process/E2E，保存 diff 与证据，单卡可独立 revert。

**测试施工（函数名锁定；Given / When / Then）**
- Unit `tests/web/w5/test_w5_c02_unit.py::test_w5_c02_contract`：Given cloud sandbox When 读取 host /etc 与其他项目 Then 不可见。
- Module `tests/web/w5/test_w5_c02_module.py::test_w5_c02_integration`：Given 资源超过 quota When 工具执行 Then sandbox 被限制而 Server/其他租户可用。
- 反向 `tests/web/w5/test_w5_c02_unit.py::test_w5_c02_negative`：Given 试图访问 169.254.169.254 或 Docker socket When 执行 Then 被阻断。
- E2E / Process：E2E-CLOUD-01 租户 A/B 双沙箱真实进程/文件/网络分离测试。
- 旧回归：任何碰 `core/` 或工具选取的卡加跑 `tests/test_cache/test_s1_s2_split.py` 和 `tests/test_cache/test_stable_prefix.py`；碰协议则加 `tests/test_protocol_schema.py`。

**验收命令（PowerShell；新测试文件由本卡创建，开卡前不得误判为已存在）**
```powershell
Set-Location 'D:\agent-demo\RxyCode\RxyCode1_1_0'
git status --short
python -m pytest 'tests/web/w5/test_w5_c02_unit.py' -q
python -m pytest 'tests/web/w5/test_w5_c02_module.py' -q
git diff --check
git status --short
```

**完成判据**
- [x] `test_w5_c02_contract`、`test_w5_c02_negative` 与 `test_w5_c02_integration` 全部真绿且无无故 skip。
- [x] 当前行为满足本卡冻结决策、现有 CLI/Desktop 回归符合期望。
- [x] 安全拒绝、失败和取消按本卡约束实测，未开发路径标 `BLOCKED` 而不是 PASS。
- [x] `evidence/web/WEB-W5-C02/` 有红绿日志、协议快照（若适用）、diff、人工复审与交接。

**Commit（仅此卡）**
`feat(web): web-w5-c02 - 云端文件/网络/CPU/进程/Secret 租户隔离`

---

### WEB-W5-C03 · 工作区 Provision/Repo checkout/工件快照
`优先级：P0` / 预计工时：0.5–2.5 工程日 / 依赖：WEB-W5-C01,WEB-W5-C02 · **owner: backend/cloud**

**背景与当前代码事实**
云端要能真实导入 GitHub repo、复现任务工作区和快照，而不是对 API 主机做 `git clone`。

**涉及文件（白名单；`NEW` = 本卡新增，`VERIFY_EXISTING` = 本卡必须检查已有文件或前置卡产物；路径不符须 STOP/提交裁定）**
| 文件 | Grep 锚点/前置 | 允许的改法 |
|---|---|---|
| `packages/rxycode-server/src/rxycode_server/workspaces/provision.py` | `NEW` | 从受限 repo URL 创建 workspace |
| `packages/rxycode-runner/src/rxycode_runner/sandbox/workspace.py` | `NEW` | checkout/snapshot/cleanup |
| `packages/rxycode-server/src/rxycode_server/workspaces/snapshots.py` | `NEW` | sha256 版本和归档 |
| `packages/rxycode-server/src/rxycode_server/workspaces/__init__.py` | `rxycode_server.workspaces` | 裁定：新目录必须是包，测试才能导入 provision。空标记，不放逻辑。 |
| `tests/web/w5/test_w5_c03_unit.py` | `NEW` | 严格单元契约，不得替生产降级 |
| `tests/web/w5/test_w5_c03_module.py` | `NEW` | 至少一个跨模块/进程/安全负测 |

**已经替你决定好的（不准自己发挥）**
Repo 检出在 Sandbox 内；凭证最小范围、无明文落入长生命周期镜像；工作区隔离、TTL 后清理；快照保留取决于项目授权，不偷偷 Git commit 用户主分支。

**否定边界**：本卡不实现第二套 Agent Loop、不跨表外文件“顺手修复”、不降低旧 `RiskLevel`、不以 mock/live screenshot 替代契约验收。现有路径/版本/依赖不符即 `BLOCKED_PREREQUISITE`，提案修改先审计。

**操作步骤（依次执行；TEST-first）**
1. 在隔离工作树读本卡上游源文件及对应模块 README，`rg` 定位锚点，记录 baseline 与当前 commit；无锚点 STOP。
2. **先建 RED 测试**：在 `tests/web/w5/test_w5_c03_unit.py` 写 `test_w5_c03_contract`、`test_w5_c03_negative`，在 `tests/web/w5/test_w5_c03_module.py` 写 `test_w5_c03_integration`，先运行观察**预期失败**，保存日志。
3. 先写恶意 repo URL/不同租户/相同任务重建 RED
4. Sandbox 内 checkout 指定 commit/worktree
5. 实现快照和 Artifact 化；记录源 commit/hash
6. 生命周期销毁验证。
7. 同步必要协议/生成 TS、更新模块文档，复跑 Unit→Contract→Process/E2E，保存 diff 与证据，单卡可独立 revert。

**测试施工（函数名锁定；Given / When / Then）**
- Unit `tests/web/w5/test_w5_c03_unit.py::test_w5_c03_contract`：Given 公开样例仓 When 导入 Then sandbox 中 revision 正确，可运行测试。
- Module `tests/web/w5/test_w5_c03_module.py::test_w5_c03_integration`：Given 同一任务两次执行 When 初始化 Then 可从固定 commit 复现基础文件。
- 反向 `tests/web/w5/test_w5_c03_unit.py::test_w5_c03_negative`：Given 私有仓 token 泄漏尝试 When 检查 artifact/日志 Then 不含密钥。
- E2E / Process：本卡无独立 UI E2E；由对应 Phase 出口跨进程测试承接。
- 旧回归：任何碰 `core/` 或工具选取的卡加跑 `tests/test_cache/test_s1_s2_split.py` 和 `tests/test_cache/test_stable_prefix.py`；碰协议则加 `tests/test_protocol_schema.py`。

**验收命令（PowerShell；新测试文件由本卡创建，开卡前不得误判为已存在）**
```powershell
Set-Location 'D:\agent-demo\RxyCode\RxyCode1_1_0'
git status --short
python -m pytest 'tests/web/w5/test_w5_c03_unit.py' -q
python -m pytest 'tests/web/w5/test_w5_c03_module.py' -q
git diff --check
git status --short
```

**完成判据**
- [x] `test_w5_c03_contract`、`test_w5_c03_negative` 与 `test_w5_c03_integration` 全部真绿且无无故 skip。
- [x] 当前行为满足本卡冻结决策、现有 CLI/Desktop 回归符合期望。
- [x] 安全拒绝、失败和取消按本卡约束实测，未开发路径标 `BLOCKED` 而不是 PASS。
- [x] `evidence/web/WEB-W5-C03/` 有红绿日志、协议快照（若适用）、diff、人工复审与交接。

**Commit（仅此卡）**
`feat(web): web-w5-c03 - 工作区 Provision/Repo checkout/工件快照`

---

### WEB-W5-C04 · 隔离 Port Preview、浏览器会话和 API 代理
`优先级：P0` / 预计工时：0.5–2.5 工程日 / 依赖：WEB-W5-C01,WEB-W5-C03 · **owner: backend/browser**

**背景与当前代码事实**
Web 平台的 Preview 应该能够显示 Agent 生成页面，却不能将用户机器/宿主/任意内部服务暴露到公网。

**涉及文件（白名单；`NEW` = 本卡新增，`VERIFY_EXISTING` = 本卡必须检查已有文件或前置卡产物；路径不符须 STOP/提交裁定）**
| 文件 | Grep 锚点/前置 | 允许的改法 |
|---|---|---|
| `packages/rxycode-server/src/rxycode_server/previews/proxy.py` | `NEW` | owner/target/port mapping auth reverse proxy |
| `packages/rxycode-runner/src/rxycode_runner/sandbox/browser.py` | `NEW` | sandbox browser profile/lifetime |
| `apps/web/src/features/preview/BrowserPreview.tsx` | `NEW` | 代理视图/失败状态 |
| `packages/rxycode-server/src/rxycode_server/previews/__init__.py` | `rxycode_server.previews` | 裁定：新目录必须是包，测试才能导入 proxy。空标记，不放逻辑。 |
| `packages/rxycode-server/src/rxycode_server/main.py` | `include_router` | 裁定：预览路由挂到现有 create_app。身份用现有 session cookie，不认客户端自报的 owner 头。 |
| `tests/web/w5/test_w5_c04_unit.py` | `NEW` | 严格单元契约，不得替生产降级 |
| `tests/web/w5/test_w5_c04_module.py` | `NEW` | 至少一个跨模块/进程/安全负测 |

**已经替你决定好的（不准自己发挥）**
Preview URL 只指向该租户 sandbox 已登记端口，需 owner auth/TTL/allowlist，阻断任意 URL 与 SSRF；Browser Agent profile 不共享 OAuth 登录凭证。

**否定边界**：本卡不实现第二套 Agent Loop、不跨表外文件“顺手修复”、不降低旧 `RiskLevel`、不以 mock/live screenshot 替代契约验收。现有路径/版本/依赖不符即 `BLOCKED_PREREQUISITE`，提案修改先审计。

**操作步骤（依次执行；TEST-first）**
1. 在隔离工作树读本卡上游源文件及对应模块 README，`rg` 定位锚点，记录 baseline 与当前 commit；无锚点 STOP。
2. **先建 RED 测试**：在 `tests/web/w5/test_w5_c04_unit.py` 写 `test_w5_c04_contract`、`test_w5_c04_negative`，在 `tests/web/w5/test_w5_c04_module.py` 写 `test_w5_c04_integration`，先运行观察**预期失败**，保存日志。
3. 先写任意内网 URL/port hijack/跨用户预览 RED
4. 实现端口登记和认证代理
5. Cloud Worker 在 sandbox 启动 dev server 后实时展示
6. 记录 iframe isolation 与内容安全策略。
7. 同步必要协议/生成 TS、更新模块文档，复跑 Unit→Contract→Process/E2E，保存 diff 与证据，单卡可独立 revert。

**测试施工（函数名锁定；Given / When / Then）**
- Unit `tests/web/w5/test_w5_c04_unit.py::test_w5_c04_contract`：Given本租户 dev server When expose_port Then 用户能在 Web 中查看真实页面。
- Module `tests/web/w5/test_w5_c04_module.py::test_w5_c04_integration`：Given port 关闭 When 重新访问 Then 显示 target unavailable。
- 反向 `tests/web/w5/test_w5_c04_unit.py::test_w5_c04_negative`：Given 攻击者构造 metadata/other tenant preview URL When 访问 Then 代理拒绝。
- E2E / Process：E2E-CLOUD-02 真启动 React dev server→preview→关闭后正确降级。
- 旧回归：任何碰 `core/` 或工具选取的卡加跑 `tests/test_cache/test_s1_s2_split.py` 和 `tests/test_cache/test_stable_prefix.py`；碰协议则加 `tests/test_protocol_schema.py`。

**验收命令（PowerShell；新测试文件由本卡创建，开卡前不得误判为已存在）**
```powershell
Set-Location 'D:\agent-demo\RxyCode\RxyCode1_1_0'
git status --short
python -m pytest 'tests/web/w5/test_w5_c04_unit.py' -q
python -m pytest 'tests/web/w5/test_w5_c04_module.py' -q
git diff --check
git status --short
```

**完成判据**
- [x] `test_w5_c04_contract`、`test_w5_c04_negative` 与 `test_w5_c04_integration` 全部真绿且无无故 skip。
- [x] 当前行为满足本卡冻结决策、现有 CLI/Desktop 回归符合期望。
- [x] 安全拒绝、失败和取消按本卡约束实测，未开发路径标 `BLOCKED` 而不是 PASS。
- [x] `evidence/web/WEB-W5-C04/` 有红绿日志、协议快照（若适用）、diff、人工复审与交接。

**Commit（仅此卡）**
`feat(web): web-w5-c04 - 隔离 Port Preview、浏览器会话和 API 代理`

---

### WEB-W5-C05 · GitHub OAuth Repo/Branch/Commit/PR 闭环
`优先级：P0` / 预计工时：0.5–2.5 工程日 / 依赖：WEB-W5-C03,WEB-W5-C04 · **owner: backend/integrations**

**背景与当前代码事实**
用户要 Agent 真正交付代码，GitHub PR 才能在简历面试中证明从任务到交付的闭环。

**涉及文件（白名单；`NEW` = 本卡新增，`VERIFY_EXISTING` = 本卡必须检查已有文件或前置卡产物；路径不符须 STOP/提交裁定）**
| 文件 | Grep 锚点/前置 | 允许的改法 |
|---|---|---|
| `packages/rxycode-server/src/rxycode_server/integrations/github.py` | `NEW` | 最小权限 OAuth/GitHub API+PR |
| `packages/rxycode-runner/src/rxycode_runner/sandbox/git_workflow.py` | `NEW` | branch/diff/commit/push 的审计 |
| `apps/web/src/features/git/PullRequestPanel.tsx` | `NEW` | PR URL/状态/权限错误 |
| `packages/rxycode-server/src/rxycode_server/integrations/__init__.py` | `rxycode_server.integrations` | 裁定：新目录必须是包，测试才能导入 github。空标记，不放逻辑。 |
| `tests/web/w5/test_w5_c05_unit.py` | `NEW` | 严格单元契约，不得替生产降级 |
| `tests/web/w5/test_w5_c05_module.py` | `NEW` | 至少一个跨模块/进程/安全负测 |

**已经替你决定好的（不准自己发挥）**
默认在工作分支，不直接 push protected main；GitHub token 只注入任务需要的短期调用、不进模型/日志；任何远端写操作走 Tool Journal；用户确认 PR 发布的策略由项目设置控制。

**否定边界**：本卡不实现第二套 Agent Loop、不跨表外文件“顺手修复”、不降低旧 `RiskLevel`、不以 mock/live screenshot 替代契约验收。现有路径/版本/依赖不符即 `BLOCKED_PREREQUISITE`，提案修改先审计。

**操作步骤（依次执行；TEST-first）**
1. 在隔离工作树读本卡上游源文件及对应模块 README，`rg` 定位锚点，记录 baseline 与当前 commit；无锚点 STOP。
2. **先建 RED 测试**：在 `tests/web/w5/test_w5_c05_unit.py` 写 `test_w5_c05_contract`、`test_w5_c05_negative`，在 `tests/web/w5/test_w5_c05_module.py` 写 `test_w5_c05_integration`，先运行观察**预期失败**，保存日志。
3. 写无权限/branch冲突/重复PR RED
4. 实现 create branch/commit/PR，回传真实 URL 和 id
5. 在 Web 呈现真实测试结果+Diff+PR
6. 故障保持 recovery_required。
7. 同步必要协议/生成 TS、更新模块文档，复跑 Unit→Contract→Process/E2E，保存 diff 与证据，单卡可独立 revert。

**测试施工（函数名锁定；Given / When / Then）**
- Unit `tests/web/w5/test_w5_c05_unit.py::test_w5_c05_contract`：Given 有授权样例 repo When 完成 Agent 修复 Then GitHub 上能找到同 branch 的 PR。
- Module `tests/web/w5/test_w5_c05_module.py::test_w5_c05_integration`：Given 同请求 retry When PR 已创建 Then 识别已有 PR 不重复创建。
- 反向 `tests/web/w5/test_w5_c05_unit.py::test_w5_c05_negative`：Given token 缺少写权限 When PR 请求 Then 明确拒绝且不碰 main。
- E2E / Process：E2E-CLOUD-03 使用专用测试 repo 完成从 Code→Tests→PR 的真实闭环。
- 旧回归：任何碰 `core/` 或工具选取的卡加跑 `tests/test_cache/test_s1_s2_split.py` 和 `tests/test_cache/test_stable_prefix.py`；碰协议则加 `tests/test_protocol_schema.py`。

**验收命令（PowerShell；新测试文件由本卡创建，开卡前不得误判为已存在）**
```powershell
Set-Location 'D:\agent-demo\RxyCode\RxyCode1_1_0'
git status --short
python -m pytest 'tests/web/w5/test_w5_c05_unit.py' -q
python -m pytest 'tests/web/w5/test_w5_c05_module.py' -q
git diff --check
git status --short
```

**完成判据**
- [x] `test_w5_c05_contract`、`test_w5_c05_negative` 与 `test_w5_c05_integration` 全部真绿且无无故 skip。
- [x] 当前行为满足本卡冻结决策、现有 CLI/Desktop 回归符合期望。
- [x] 安全拒绝、失败和取消按本卡约束实测，未开发路径标 `BLOCKED` 而不是 PASS。
- [x] `evidence/web/WEB-W5-C05/` 有红绿日志、协议快照（若适用）、diff、人工复审与交接。

**Commit（仅此卡）**
`feat(web): web-w5-c05 - GitHub OAuth Repo/Branch/Commit/PR 闭环`

---

### WEB-W5-C06 · Cloud 并发、队列隔离、预览/沙箱费用上限
`优先级：P0` / 预计工时：0.5–2.5 工程日 / 依赖：WEB-W5-C01..C05 · **owner: backend/ops**

**背景与当前代码事实**
公开 Demo 必须兼顾用户间隔离、LLM 费用和基础资源；“可多用户”需真实并发与隔离测试。

**涉及文件（白名单；`NEW` = 本卡新增，`VERIFY_EXISTING` = 本卡必须检查已有文件或前置卡产物；路径不符须 STOP/提交裁定）**
| 文件 | Grep 锚点/前置 | 允许的改法 |
|---|---|---|
| `packages/rxycode-server/src/rxycode_server/quotas/service.py` | `NEW` | tenant token/task/concurrency quotas |
| `packages/rxycode-server/src/rxycode_server/quotas/__init__.py` | `rxycode_server.quotas` | 裁定：新目录必须是包，测试才能导入 service。空标记，不放逻辑。 |
| `packages/rxycode-worker/src/rxycode_worker/scheduler/capacity.py` | `NEW` | 并发/冷启动/sandbox limits |
| `packages/rxycode-worker/src/rxycode_worker/scheduler/__init__.py` | `rxycode_worker.scheduler` | 裁定：新目录必须是包，测试才能导入 capacity。空标记，不放逻辑。 |
| `packages/rxycode-server/src/rxycode_server/runs/service.py` | `create_run` | 裁定：创建 Run 的生产入口。插入前调用 QuotaGate；拒绝时不插入、不调用模型、不保留 worker。成功后 worker 保持到终态或该 worker_id 的 TTL。释放只认这条 Run 载荷里的 worker_id。客户端 header 与 claimed_tenant_id 不能提高额度。 |
| `packages/rxycode-worker/src/rxycode_worker/supervisor.py` | `commit_terminal` | 裁定：Run 进入终态的生产入口。并发槽是数据库里仍活跃且未过 TTL 的 Run，不放在进程内存。同一用户的准入用 pg_advisory_xact_lock 串行，避免两个请求同时看到 0 个活跃 Run。commit_terminal 与 confirm_cancel 把状态写成终态后，另一个进程的下一次 create_run 不再计这个槽。 |
| `infra/compose/compose.yaml` | `NEW` | 自托管拓扑、healthchecks |
| `tests/web/w5/test_w5_c06_unit.py` | `NEW` | 严格单元契约，不得替生产降级 |
| `tests/web/w5/test_w5_c06_module.py` | `NEW` | 至少一个跨模块/进程/安全负测 |

**已经替你决定好的（不准自己发挥）**
限制按 user/tenant 计算，不可客户端改请求头绕过；触发配额要完成明确失败事件；资源释放有 TTL/GC；无凭证/预算不可继续调用模型。

**否定边界**：本卡不实现第二套 Agent Loop、不跨表外文件“顺手修复”、不降低旧 `RiskLevel`、不以 mock/live screenshot 替代契约验收。现有路径/版本/依赖不符即 `BLOCKED_PREREQUISITE`，提案修改先审计。

**操作步骤（依次执行；TEST-first）**
1. 在隔离工作树读本卡上游源文件及对应模块 README，`rg` 定位锚点，记录 baseline 与当前 commit；无锚点 STOP。
2. **先建 RED 测试**：在 `tests/web/w5/test_w5_c06_unit.py` 写 `test_w5_c06_contract`、`test_w5_c06_negative`，在 `tests/web/w5/test_w5_c06_module.py` 写 `test_w5_c06_integration`，先运行观察**预期失败**，保存日志。
3. 写同时 2 租户/限额竞争/失败清理 RED
4. 接入 budget guard 和队列并发门
5. 记录 sandbox cold-start P50/P95
6. 超时结束释放各类资源。
7. 同步必要协议/生成 TS、更新模块文档，复跑 Unit→Contract→Process/E2E，保存 diff 与证据，单卡可独立 revert。

**测试施工（函数名锁定；Given / When / Then）**
- Unit `tests/web/w5/test_w5_c06_unit.py::test_w5_c06_contract`：Given 访客超出额度 When 创建 Run Then 429/结构化错误而无新 Worker 占用。
- Module `tests/web/w5/test_w5_c06_module.py::test_w5_c06_integration`：Given A/B 同时运行 When 检查 workspace/事件 Then 完全隔离。
- 反向 `tests/web/w5/test_w5_c06_unit.py::test_w5_c06_negative`：Given Sandbox create 后异常 When GC 运行 Then 资源被清理而没有孤儿容器。
- E2E / Process：E2E-CLOUD-04 并行租户真实任务+强制停止后的资源清理。
- 旧回归：任何碰 `core/` 或工具选取的卡加跑 `tests/test_cache/test_s1_s2_split.py` 和 `tests/test_cache/test_stable_prefix.py`；碰协议则加 `tests/test_protocol_schema.py`。

**验收命令（PowerShell；新测试文件由本卡创建，开卡前不得误判为已存在）**
```powershell
Set-Location 'D:\agent-demo\RxyCode\RxyCode1_1_0'
git status --short
python -m pytest 'tests/web/w5/test_w5_c06_unit.py' -q
python -m pytest 'tests/web/w5/test_w5_c06_module.py' -q
git diff --check
git status --short
```

**完成判据**
- [x] `test_w5_c06_contract`、`test_w5_c06_negative` 与 `test_w5_c06_integration` 全部真绿且无无故 skip。
- [x] 当前行为满足本卡冻结决策、现有 CLI/Desktop 回归符合期望。
- [x] 安全拒绝、失败和取消按本卡约束实测，未开发路径标 `BLOCKED` 而不是 PASS。
- [x] `evidence/web/WEB-W5-C06/` 有红绿日志、协议快照（若适用）、diff、人工复审与交接。

**Commit（仅此卡）**
`feat(web): web-w5-c06 - Cloud 并发、队列隔离、预览/沙箱费用上限`

---

## §2 Wave 出口检查
- [x] W5 所有卡各有独立 commit 和 evidence，未勾选项不被宣称完成。
- [x] 既有行为回归没有被覆盖，新增 API 不依赖 mock/假状态。
- [x] 运行期错误、权限拒绝和用户可见状态有负向证据。
