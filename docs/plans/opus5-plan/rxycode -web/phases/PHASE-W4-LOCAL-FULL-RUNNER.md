# Phase W4 · LOCAL-FULL-RUNNER（WEB 项目施工卡）

> **范围**：这是唯一可施工卡面，其他总设计文档不复制任务卡。执行旧项目卡时仍需服从旧 `DEV-ORDER.md`。每张卡独立分支/提交，严格遵守 `../00-WEB-EXECUTION-PLAN.md` WEB-R1–R12。

## §0 W4 前置与出口

共 7 张卡；开工先核实 upstream docs/code 与 `git status`，当前文件名只是目标设计，施工前须 `Test-Path`，不能因为示例而声称实现存在。

| 卡号 | 名称 | 前置 | owner |
|---|---|---|---|
| `WEB-W4-C01` | Local NativeBackend：Full 直接在当前机器执行 | WEB-W1-C03,WEB-W2-C03 | backend/runner |
| `WEB-W4-C02` | Desktop Computer Use OS 适配 | WEB-W4-C01 | runner/cu |
| `WEB-W4-C03` | `rxycode connect` 设备配对、身份与出站 WSS | WEB-W2-C02,WEB-W1-C04 | backend/runner |
| `WEB-W4-C04` | 远程 ToolRPC 流式结果、重试去重与 side-effect | WEB-W4-C03,WEB-W2-C05 | backend/runner |
| `WEB-W4-C05` | 本机 Full Grant 权威、Scope 与远程授权 UX | WEB-W4-C03,WEB-W4-C04 | security/runner+frontend |
| `WEB-W4-C06` | 本机急停、进程杀树、审计与托盘 | WEB-W4-C01,WEB-W4-C04,WEB-W4-C05 | runner/security |
| `WEB-W4-C07` | Runner 平台能力表与本机发行件验证 | WEB-W4-C01..C06 | release/runner |

## §1 任务卡（TEST-first，可单卡施工）

### WEB-W4-C01 · Local NativeBackend：Full 直接在当前机器执行
`优先级：P0` / 预计工时：0.5–2.5 工程日 / 依赖：WEB-W1-C03,WEB-W2-C03 · **owner: backend/runner**

**背景与当前代码事实**
用户要求 Full 绕过 sandbox；现有 `core/sandbox` 主要包装 shell，不能在 Full 里调用它，也不能把 Docker mount 假扮 Native。

**涉及文件（白名单；`NEW` = 本卡新增，`VERIFY_EXISTING` = 本卡必须检查已有文件或前置卡产物；路径不符须 STOP/提交裁定）**
| 文件 | Grep 锚点/前置 | 允许的改法 |
|---|---|---|
| `packages/rxycode-runner/src/rxycode_runner/local/native_backend.py` | `NEW` | 原生 shell/file/process dispatch |
| `packages/rxycode-core/src/rxycode_core/runtime/execution_port.py` | `VERIFY_EXISTING` | 核对端口注册 |
| `core/sandbox/manager.py` | `def wrap_command` | 仅作为负向比对不修改 |
| `tests/web/w4/test_w4_c01_unit.py` | `NEW` | 严格单元契约，不得替生产降级 |
| `tests/web/w4/test_w4_c01_module.py` | `NEW` | 至少一个跨模块/进程/安全负测 |
| `execution/tool_orchestrator.py` | `_invoke_through_port` | 本机 full 的 shell 改走 LocalNativeBackend。裁定：端口调用已经在这里 |

**已经替你决定好的（不准自己发挥）**
`local + full` 选择 native OS；不调用 `SandboxBackend`/wrap_command；正常授权的本地 Full 跳过逐工具 Ask，但保留 trace/audit/kill；OS 权限不足就真实报错。

**否定边界**：本卡不实现第二套 Agent Loop、不跨表外文件“顺手修复”、不降低旧 `RiskLevel`、不以 mock/live screenshot 替代契约验收。现有路径/版本/依赖不符即 `BLOCKED_PREREQUISITE`，提案修改先审计。

**操作步骤（依次执行；TEST-first）**
1. 在隔离工作树读本卡上游源文件及对应模块 README，`rg` 定位锚点，记录 baseline 与当前 commit；无锚点 STOP。
2. **先建 RED 测试**：在 `tests/web/w4/test_w4_c01_unit.py` 写 `test_w4_c01_contract`、`test_w4_c01_negative`，在 `tests/web/w4/test_w4_c01_module.py` 写 `test_w4_c01_integration`，先运行观察**预期失败**，保存日志。
3. 写 sandbox factory spy 和当前 OS native pid/目录红测
4. 实现 native exec/read/write/cancel + 日志
5. LocalWorker target 注入并与 ToolOrchestrator gate 集成
6. 真 Windows 空目录测试 full path 不在容器。
7. 同步必要协议/生成 TS、更新模块文档，复跑 Unit→Contract→Process/E2E，保存 diff 与证据，单卡可独立 revert。

**测试施工（函数名锁定；Given / When / Then）**
- Unit `tests/web/w4/test_w4_c01_unit.py::test_w4_c01_contract`：Given local full When shell 启动 Then pid 属于当前用户 native session、没有 sandbox wrapper。
- Module `tests/web/w4/test_w4_c01_module.py::test_w4_c01_integration`：Given target=local permission=ask When 相同命令 Then 仍按原审批限制。
- 反向 `tests/web/w4/test_w4_c01_unit.py::test_w4_c01_negative`：Given 强制注入 SandboxBackend When full mode Then 测试失败证明不会误走沙箱。
- E2E / Process：E2E-FULL-01 Windows 本机真实进程+file+OS owner 证据，禁止破坏性命令。
- 旧回归：任何碰 `core/` 或工具选取的卡加跑 `tests/test_cache/test_s1_s2_split.py` 和 `tests/test_cache/test_stable_prefix.py`；碰协议则加 `tests/test_protocol_schema.py`。

**验收命令（PowerShell；新测试文件由本卡创建，开卡前不得误判为已存在）**
```powershell
Set-Location 'D:\agent-demo\RxyCode\RxyCode1_1_0'
git status --short
if (!(Test-Path 'packages/rxycode-core/src/rxycode_core/runtime/execution_port.py')) { throw 'BLOCKED_PREREQUISITE: packages/rxycode-core/src/rxycode_core/runtime/execution_port.py' }
rg -n --fixed-strings 'def wrap_command' 'core/sandbox/manager.py'
python -m pytest 'tests/web/w4/test_w4_c01_unit.py' -q
python -m pytest 'tests/web/w4/test_w4_c01_module.py' -q
python -m pytest tests/test_cache/test_s1_s2_split.py tests/test_cache/test_stable_prefix.py -q
git diff --check
git status --short
```

**完成判据**
- [x] `test_w4_c01_contract`、`test_w4_c01_negative` 与 `test_w4_c01_integration` 全部真绿且无无故 skip。
- [x] 当前行为满足本卡冻结决策、现有 CLI/Desktop 回归符合期望。
- [x] 安全拒绝、失败和取消按本卡约束实测，未开发路径标 `BLOCKED` 而不是 PASS。
- [x] `evidence/web/WEB-W4-C01/` 有红绿日志、协议快照（若适用）、diff、人工复审与交接。

**Commit（仅此卡）**
`feat(web): web-w4-c01 - Local NativeBackend：Full 直接在当前机器执行`

---

### WEB-W4-C02 · Desktop Computer Use OS 适配
`优先级：P0` / 预计工时：0.5–2.5 工程日 / 依赖：WEB-W4-C01 · **owner: runner/cu**

**背景与当前代码事实**
已有 `core/cu` 与 Playwright MCP，但真正 Native Full 的桌面控制需按 OS 声明截图/键鼠/窗口和能力不足行为。

**涉及文件（白名单；`NEW` = 本卡新增，`VERIFY_EXISTING` = 本卡必须检查已有文件或前置卡产物；路径不符须 STOP/提交裁定）**
| 文件 | Grep 锚点/前置 | 允许的改法 |
|---|---|---|
| `core/cu/` | `VERIFY_EXISTING` | 核实现有适配实现，不能重造旧 Tool 名 |
| `packages/rxycode-runner/src/rxycode_runner/desktop/windows_adapter.py` | `NEW` | Windows screenshot/sendinput/window |
| `packages/rxycode-runner/src/rxycode_runner/desktop/capabilities.py` | `NEW` | DPI/monitor/lock-screen/permissions |
| `tests/web/w4/test_w4_c02_unit.py` | `NEW` | 严格单元契约，不得替生产降级 |
| `tests/web/w4/test_w4_c02_module.py` | `NEW` | 至少一个跨模块/进程/安全负测 |
| `pyproject.toml` | `rxycode_runner.desktop` | 登记新包。裁定：setuptools 只打包显式列出的包 |

**已经替你决定好的（不准自己发挥）**
先做 Windows 可演示的真实能力；mac/Linux 显式 degraded/unavailable，不假称全平台可用；操作必须有 task-bound capability，不静默附着私人 Chrome。

**否定边界**：本卡不实现第二套 Agent Loop、不跨表外文件“顺手修复”、不降低旧 `RiskLevel`、不以 mock/live screenshot 替代契约验收。现有路径/版本/依赖不符即 `BLOCKED_PREREQUISITE`，提案修改先审计。

**操作步骤（依次执行；TEST-first）**
1. 在隔离工作树读本卡上游源文件及对应模块 README，`rg` 定位锚点，记录 baseline 与当前 commit；无锚点 STOP。
2. **先建 RED 测试**：在 `tests/web/w4/test_w4_c02_unit.py` 写 `test_w4_c02_contract`、`test_w4_c02_negative`，在 `tests/web/w4/test_w4_c02_module.py` 写 `test_w4_c02_integration`，先运行观察**预期失败**，保存日志。
3. 写 OS capability 矩阵/虚假坐标/多屏 red tests
4. 实现截图、窗口枚举/聚焦、键鼠、剪贴板局部能力
5. 保存截图压缩与坐标元信息；接 native tool registry
6. 用辅助测试应用真机验证。
7. 同步必要协议/生成 TS、更新模块文档，复跑 Unit→Contract→Process/E2E，保存 diff 与证据，单卡可独立 revert。

**测试施工（函数名锁定；Given / When / Then）**
- Unit `tests/web/w4/test_w4_c02_unit.py::test_w4_c02_contract`：Given 两显示器与 DPI 值 When 点击目标窗口控件 Then 坐标转换正确。
- Module `tests/web/w4/test_w4_c02_module.py::test_w4_c02_integration`：Given 可访问桌面 When 截图/打开普通应用 Then 返回真实像素/窗口 ID。
- 反向 `tests/web/w4/test_w4_c02_unit.py::test_w4_c02_negative`：Given 锁屏/Wayland 不具备能力 When 请求 click Then 明确 CAPABILITY_UNAVAILABLE、不偷用别的工具。
- E2E / Process：E2E-FULL-02 有人监管的真机点击/窗口焦点回读，禁止系统设置破坏性操作。
- 旧回归：任何碰 `core/` 或工具选取的卡加跑 `tests/test_cache/test_s1_s2_split.py` 和 `tests/test_cache/test_stable_prefix.py`；碰协议则加 `tests/test_protocol_schema.py`。

**验收命令（PowerShell；新测试文件由本卡创建，开卡前不得误判为已存在）**
```powershell
Set-Location 'D:\agent-demo\RxyCode\RxyCode1_1_0'
git status --short
if (!(Test-Path 'core/cu/')) { throw 'BLOCKED_PREREQUISITE: core/cu/' }
python -m pytest 'tests/web/w4/test_w4_c02_unit.py' -q
python -m pytest 'tests/web/w4/test_w4_c02_module.py' -q
python -m pytest tests/test_cache/test_s1_s2_split.py tests/test_cache/test_stable_prefix.py -q
git diff --check
git status --short
```

**完成判据**
- [x] `test_w4_c02_contract`、`test_w4_c02_negative` 与 `test_w4_c02_integration` 全部真绿且无无故 skip。
- [x] 当前行为满足本卡冻结决策、现有 CLI/Desktop 回归符合期望。
- [x] 安全拒绝、失败和取消按本卡约束实测，未开发路径标 `BLOCKED` 而不是 PASS。
- [x] `evidence/web/WEB-W4-C02/` 有红绿日志、协议快照（若适用）、diff、人工复审与交接。

**Commit（仅此卡）**
`feat(web): web-w4-c02 - Desktop Computer Use OS 适配`

---

### WEB-W4-C03 · `rxycode connect` 设备配对、身份与出站 WSS
`优先级：P0` / 预计工时：0.5–2.5 工程日 / 依赖：WEB-W2-C02,WEB-W1-C04 · **owner: backend/runner**

**背景与当前代码事实**
用户不应开放公网 IP/端口，本机 Runner 需要主动连接 Cloud，并与网页登录和 Runner 凭证分离。

**涉及文件（白名单；`NEW` = 本卡新增，`VERIFY_EXISTING` = 本卡必须检查已有文件或前置卡产物；路径不符须 STOP/提交裁定）**
| 文件 | Grep 锚点/前置 | 允许的改法 |
|---|---|---|
| `main.py` | `def cli` | 接入 connect Click 命令 |
| `packages/rxycode-runner/src/rxycode_runner/remote/client.py` | `NEW` | WSS 心跳/重连、单写者 |
| `packages/rxycode-server/src/rxycode_server/devices/gateway.py` | `NEW` | 设备握手/online/TTL |
| `packages/rxycode-server/src/rxycode_server/devices/pairing.py` | `NEW` | 单次配对、令牌轮换 |
| `tests/web/w4/test_w4_c03_unit.py` | `NEW` | 严格单元契约，不得替生产降级 |
| `tests/web/w4/test_w4_c03_module.py` | `NEW` | 至少一个跨模块/进程/安全负测 |
| `pyproject.toml` | `rxycode_runner.remote` | 登记新包。裁定：setuptools 只打包显式列出的包 |
| `packages/rxycode-server/src/rxycode_server/main.py` | `include_router` | 挂上设备路由。裁定：Devices API 在现有 create_app |

**已经替你决定好的（不准自己发挥）**
设备凭证与浏览器会话独立，设备 token 不输出日志；WSS TLS 不关验证；配对码一次性有时限；重复设备连接旧连接失效；无公网入站本机端口。

**否定边界**：本卡不实现第二套 Agent Loop、不跨表外文件“顺手修复”、不降低旧 `RiskLevel`、不以 mock/live screenshot 替代契约验收。现有路径/版本/依赖不符即 `BLOCKED_PREREQUISITE`，提案修改先审计。

**操作步骤（依次执行；TEST-first）**
1. 在隔离工作树读本卡上游源文件及对应模块 README，`rg` 定位锚点，记录 baseline 与当前 commit；无锚点 STOP。
2. **先建 RED 测试**：在 `tests/web/w4/test_w4_c03_unit.py` 写 `test_w4_c03_contract`、`test_w4_c03_negative`，在 `tests/web/w4/test_w4_c03_module.py` 写 `test_w4_c03_integration`，先运行观察**预期失败**，保存日志。
3. 先造过期配对码、重复连接、错误版本负测
4. 实现 WSS hello/caps/heartbeat/reconnect
5. 完成设备验证与 token 吊销
6. 确保 WS writer 单独任务串行发送。
7. 同步必要协议/生成 TS、更新模块文档，复跑 Unit→Contract→Process/E2E，保存 diff 与证据，单卡可独立 revert。

**测试施工（函数名锁定；Given / When / Then）**
- Unit `tests/web/w4/test_w4_c03_unit.py::test_w4_c03_contract`：Given 本机跑 connect When 授权配对 Then Devices API 显示正确设备/OS/capability。
- Module `tests/web/w4/test_w4_c03_module.py::test_w4_c03_integration`：Given 云端断开 When Runner reconnect Then 使用合法新会话而不自动升级授权。
- 反向 `tests/web/w4/test_w4_c03_unit.py::test_w4_c03_negative`：Given 错误 token/过期码 When 握手 Then 拒绝且无运行工具权限。
- E2E / Process：E2E-FULL-03 浏览器 Device 配对与设备离线/重连页面。
- 旧回归：任何碰 `core/` 或工具选取的卡加跑 `tests/test_cache/test_s1_s2_split.py` 和 `tests/test_cache/test_stable_prefix.py`；碰协议则加 `tests/test_protocol_schema.py`。

**验收命令（PowerShell；新测试文件由本卡创建，开卡前不得误判为已存在）**
```powershell
Set-Location 'D:\agent-demo\RxyCode\RxyCode1_1_0'
git status --short
rg -n --fixed-strings 'def cli' 'main.py'
python -m pytest 'tests/web/w4/test_w4_c03_unit.py' -q
python -m pytest 'tests/web/w4/test_w4_c03_module.py' -q
git diff --check
git status --short
```

**完成判据**
- [x] `test_w4_c03_contract`、`test_w4_c03_negative` 与 `test_w4_c03_integration` 全部真绿且无无故 skip。
- [x] 当前行为满足本卡冻结决策、现有 CLI/Desktop 回归符合期望。
- [x] 安全拒绝、失败和取消按本卡约束实测，未开发路径标 `BLOCKED` 而不是 PASS。
- [x] `evidence/web/WEB-W4-C03/` 有红绿日志、协议快照（若适用）、diff、人工复审与交接。

**Commit（仅此卡）**
`feat(web): web-w4-c03 - `rxycode connect` 设备配对、身份与出站 WSS`

---

### WEB-W4-C04 · 远程 ToolRPC 流式结果、重试去重与 side-effect
`优先级：P0` / 预计工时：0.5–2.5 工程日 / 依赖：WEB-W4-C03,WEB-W2-C05 · **owner: backend/runner**

**背景与当前代码事实**
远程工具可能在 ACK 丢失时已经对本机做了写操作，必须把已有 Tool Journal 扩展到跨 WebSocket 的 call_id。

**涉及文件（白名单；`NEW` = 本卡新增，`VERIFY_EXISTING` = 本卡必须检查已有文件或前置卡产物；路径不符须 STOP/提交裁定）**
| 文件 | Grep 锚点/前置 | 允许的改法 |
|---|---|---|
| `packages/rxycode-runner/src/rxycode_runner/transport/tool_rpc.py` | `NEW` | invoke/chunk/result/ack/status/cancel |
| `packages/rxycode-worker/src/rxycode_worker/runner_client.py` | `NEW` | Target dispatch RPC |
| `execution/tool_journal.py` | `pending` | 原 at-most-once status adapter |
| `tests/web/w4/test_w4_c04_unit.py` | `NEW` | 严格单元契约，不得替生产降级 |
| `tests/web/w4/test_w4_c04_module.py` | `NEW` | 至少一个跨模块/进程/安全负测 |
| `pyproject.toml` | `rxycode_runner.transport` | 登记新包。裁定：setuptools 只打包显式列出的包 |
| `packages/rxycode-runner/src/rxycode_runner/remote/client.py` | `_read_downstream` | 出站连接上读 ToolRPC。裁定：工具帧走已配对的设备通道 |
| `packages/rxycode-server/src/rxycode_server/devices/gateway.py` | `send_tool` | Worker 经设备 socket 下发。裁定：不另开本机监听端口 |
| `packages/rxycode-worker/src/rxycode_worker/supervisor.py` | `attempt_tool` | 设备目标走 dispatch_device_call。裁定：Worker 现有入口下发 ToolRPC |

**已经替你决定好的（不准自己发挥）**
同 `(device_id,call_id)` 一次执行，未知结果必须查询后恢复或进入 recovery_required；WS 多并发共享单一发送队列；chunk 限大小并有 seq/backpressure。

**否定边界**：本卡不实现第二套 Agent Loop、不跨表外文件“顺手修复”、不降低旧 `RiskLevel`、不以 mock/live screenshot 替代契约验收。现有路径/版本/依赖不符即 `BLOCKED_PREREQUISITE`，提案修改先审计。

**操作步骤（依次执行；TEST-first）**
1. 在隔离工作树读本卡上游源文件及对应模块 README，`rg` 定位锚点，记录 baseline 与当前 commit；无锚点 STOP。
2. **先建 RED 测试**：在 `tests/web/w4/test_w4_c04_unit.py` 写 `test_w4_c04_contract`、`test_w4_c04_negative`，在 `tests/web/w4/test_w4_c04_module.py` 写 `test_w4_c04_integration`，先运行观察**预期失败**，保存日志。
3. 写 ACK 丢包/repeated invoke/断线后 status query RED
4. 实现 toolRPC envelope 与 stream buffer 限流
5. Journal 预约在 dispatch 前，确认结果后 commit；stop/cancel 跨设备传播。
6. 同步必要协议/生成 TS、更新模块文档，复跑 Unit→Contract→Process/E2E，保存 diff 与证据，单卡可独立 revert。

**测试施工（函数名锁定；Given / When / Then）**
- Unit `tests/web/w4/test_w4_c04_unit.py::test_w4_c04_contract`：Given call_id 重复到达 When Runner 上次已 completed Then 回传原结果且不执行第二次。
- Module `tests/web/w4/test_w4_c04_module.py::test_w4_c04_integration`：Given stdout 多 chunk When 断线重连 Then chunk seq 去重/重放或有明确截断提示。
- 反向 `tests/web/w4/test_w4_c04_unit.py::test_w4_c04_negative`：Given 写操作 ACK 消失 When 远端重试 Then 标 unknown 不重复写。
- E2E / Process：E2E-FULL-04 Cloud Worker→本机执行真实无害写操作，模拟断线查重。
- 旧回归：任何碰 `core/` 或工具选取的卡加跑 `tests/test_cache/test_s1_s2_split.py` 和 `tests/test_cache/test_stable_prefix.py`；碰协议则加 `tests/test_protocol_schema.py`。

**验收命令（PowerShell；新测试文件由本卡创建，开卡前不得误判为已存在）**
```powershell
Set-Location 'D:\agent-demo\RxyCode\RxyCode1_1_0'
git status --short
rg -n --fixed-strings 'pending' 'execution/tool_journal.py'
python -m pytest 'tests/web/w4/test_w4_c04_unit.py' -q
python -m pytest 'tests/web/w4/test_w4_c04_module.py' -q
python -m pytest tests/test_cache/test_s1_s2_split.py tests/test_cache/test_stable_prefix.py -q
git diff --check
git status --short
```

**完成判据**
- [x] `test_w4_c04_contract`、`test_w4_c04_negative` 与 `test_w4_c04_integration` 全部真绿且无无故 skip。
- [x] 当前行为满足本卡冻结决策、现有 CLI/Desktop 回归符合期望。
- [x] 安全拒绝、失败和取消按本卡约束实测，未开发路径标 `BLOCKED` 而不是 PASS。
- [x] `evidence/web/WEB-W4-C04/` 有红绿日志、协议快照（若适用）、diff、人工复审与交接。

**Commit（仅此卡）**
`feat(web): web-w4-c04 - 远程 ToolRPC 流式结果、重试去重与 side-effect`

---

### WEB-W4-C05 · 本机 Full Grant 权威、Scope 与远程授权 UX
`优先级：P0` / 预计工时：0.5–2.5 工程日 / 依赖：WEB-W4-C03,WEB-W4-C04 · **owner: security/runner+frontend**

**背景与当前代码事实**
若云端能任意将 max_permission=full 发给设备，会让 Server 攻破后变成无授权本机执行。Remote Full 应按用户批准一次会话范围免逐项审批。

**涉及文件（白名单；`NEW` = 本卡新增，`VERIFY_EXISTING` = 本卡必须检查已有文件或前置卡产物；路径不符须 STOP/提交裁定）**
| 文件 | Grep 锚点/前置 | 允许的改法 |
|---|---|---|
| `packages/rxycode-runner/src/rxycode_runner/local/grant_store.py` | `NEW` | 本机 grant/expiry/revoke |
| `packages/rxycode-runner/src/rxycode_runner/transport/tool_rpc.py` | `local_tool` | 裁定：`permission=full` 的设备调用先问本机 GrantStore。grant 覆盖 session/run/capability/workspace/expiry/revoke_epoch 时，shell 走现有 `run_bash`，click 走现有 `click()`，不再逐项审批。没有本机 grant 时拒绝并写审计，不信云端字符串。 |
| `packages/rxycode-server/src/rxycode_server/devices/grants.py` | `NEW` | 云端 grant request+审计镜像 |
| `apps/web/src/features/devices/DeviceGrants.tsx` | `NEW` | 待本机确认状态、已授权 scope |
| `tests/web/w4/test_w4_c05_unit.py` | `NEW` | 严格单元契约，不得替生产降级 |
| `tests/web/w4/test_w4_c05_module.py` | `NEW` | 至少一个跨模块/进程/安全负测 |

**已经替你决定好的（不准自己发挥）**
Runner 本机权威，只认自己保存并确认的 grant，逐调用验证 session/run/capability/workspace/expiry/revoke_epoch；云端不能单方面升级。Local Full 与 Remote Full 都无逐工具审批，但授权入口不同。

**否定边界**：本卡不实现第二套 Agent Loop、不跨表外文件“顺手修复”、不降低旧 `RiskLevel`、不以 mock/live screenshot 替代契约验收。现有路径/版本/依赖不符即 `BLOCKED_PREREQUISITE`，提案修改先审计。

**操作步骤（依次执行；TEST-first）**
1. 在隔离工作树读本卡上游源文件及对应模块 README，`rg` 定位锚点，记录 baseline 与当前 commit；无锚点 STOP。
2. **先建 RED 测试**：在 `tests/web/w4/test_w4_c05_unit.py` 写 `test_w4_c05_contract`、`test_w4_c05_negative`，在 `tests/web/w4/test_w4_c05_module.py` 写 `test_w4_c05_integration`，先运行观察**预期失败**，保存日志。
3. 先写伪造 Full/重放 Grant/范围越权 RED
4. 构建本机托盘或可信 UI grant 确认流程
5. 实现本地持久化/撤销/expiry
6. Web 仅显示 Server 真实状态并等待 Runner ACK。
7. 同步必要协议/生成 TS、更新模块文档，复跑 Unit→Contract→Process/E2E，保存 diff 与证据，单卡可独立 revert。

**测试施工（函数名锁定；Given / When / Then）**
- Unit `tests/web/w4/test_w4_c05_unit.py::test_w4_c05_contract`：Given 云端请求 Remote Full When 本机明确确认 Then 范围内 shell/click 可无逐项审批。
- Module `tests/web/w4/test_w4_c05_module.py::test_w4_c05_integration`：Given 本机批准临时 grant When 到期或 revoke Then 后续工具被拒绝。
- 反向 `tests/web/w4/test_w4_c05_unit.py::test_w4_c05_negative`：Given Server 伪造 permission=full When 本机没 grant Then 拒绝且写审计。
- E2E / Process：E2E-FULL-05 真实设备 grant approve→正常工具→revoke→拒绝。
- 旧回归：任何碰 `core/` 或工具选取的卡加跑 `tests/test_cache/test_s1_s2_split.py` 和 `tests/test_cache/test_stable_prefix.py`；碰协议则加 `tests/test_protocol_schema.py`。

**验收命令（PowerShell；新测试文件由本卡创建，开卡前不得误判为已存在）**
```powershell
Set-Location 'D:\agent-demo\RxyCode\RxyCode1_1_0'
git status --short
python -m pytest 'tests/web/w4/test_w4_c05_unit.py' -q
python -m pytest 'tests/web/w4/test_w4_c05_module.py' -q
git diff --check
git status --short
```

**完成判据**
- [x] `test_w4_c05_contract`、`test_w4_c05_negative` 与 `test_w4_c05_integration` 全部真绿且无无故 skip。
- [x] 当前行为满足本卡冻结决策、现有 CLI/Desktop 回归符合期望。
- [x] 安全拒绝、失败和取消按本卡约束实测，未开发路径标 `BLOCKED` 而不是 PASS。
- [x] `evidence/web/WEB-W4-C05/` 有红绿日志、协议快照（若适用）、diff、人工复审与交接。

**Commit（仅此卡）**
`feat(web): web-w4-c05 - 本机 Full Grant 权威、Scope 与远程授权 UX`

---

### WEB-W4-C06 · 本机急停、进程杀树、审计与托盘
`优先级：P0` / 预计工时：0.5–2.5 工程日 / 依赖：WEB-W4-C01,WEB-W4-C04,WEB-W4-C05 · **owner: runner/security**

**背景与当前代码事实**
Full Native 直通本机必须有不依赖云端 Web 的退出与止损操作，尤其 Shell 可能启动多个子进程。

**涉及文件（白名单；`NEW` = 本卡新增，`VERIFY_EXISTING` = 本卡必须检查已有文件或前置卡产物；路径不符须 STOP/提交裁定）**
| 文件 | Grep 锚点/前置 | 允许的改法 |
|---|---|---|
| `packages/rxycode-runner/src/rxycode_runner/local/supervisor.py` | `NEW` | 进程树/工具取消/退出证据 |
| `packages/rxycode-runner/src/rxycode_runner/transport/tool_rpc.py` | `_run_remote_full` | 裁定：已授权的 Remote Full shell 仍走 `run_bash`，并让该次 shell 进入 ProcessSupervisor 的 Job。急停置位后不再启动。 |
| `utils/shell.py` | `_execute_controlled` | 裁定：被标记的 Full shell 在恢复主线程前加入急停 Job。失败的云端 ACK 不阻止本机结束进程。 |
| `packages/rxycode-runner/src/rxycode_runner/local/emergency.py` | `NEW` | 托盘/本机热键与 kill switch |
| `packages/rxycode-runner/src/rxycode_runner/local/grant_store.py` | `revoke_all` | 裁定：急停对已安装的 GrantStore 调用 `revoke_all`，提升 `revoke_epoch`。重启后的新 supervisor 不能靠旧 grant 恢复 Full。 |
| `packages/rxycode-runner/src/rxycode_runner/local/audit.py` | `NEW` | 脱敏 JSONL，审计回放 |
| `tests/web/w4/test_w4_c06_unit.py` | `NEW` | 严格单元契约，不得替生产降级 |
| `tests/web/w4/test_w4_c06_module.py` | `NEW` | 至少一个跨模块/进程/安全负测 |

**已经替你决定好的（不准自己发挥）**
急停必须由本机先执行，不等云端 ACK；杀进程树并阻止新工具；远程设备断线不会静默恢复 Full；audit 中不记完整 secret/剪贴板正文。

**否定边界**：本卡不实现第二套 Agent Loop、不跨表外文件“顺手修复”、不降低旧 `RiskLevel`、不以 mock/live screenshot 替代契约验收。现有路径/版本/依赖不符即 `BLOCKED_PREREQUISITE`，提案修改先审计。

**操作步骤（依次执行；TEST-first）**
1. 在隔离工作树读本卡上游源文件及对应模块 README，`rg` 定位锚点，记录 baseline 与当前 commit；无锚点 STOP。
2. **先建 RED 测试**：在 `tests/web/w4/test_w4_c06_unit.py` 写 `test_w4_c06_contract`、`test_w4_c06_negative`，在 `tests/web/w4/test_w4_c06_module.py` 写 `test_w4_c06_integration`，先运行观察**预期失败**，保存日志。
3. 写后台子进程/网络离线/本机急停过程红测
4. 实现 OS 进程组/WinJob 仅作为 kill-tree 管理（**不是沙箱**）
5. 独立托盘/热键执行取消与授权吊销
6. 合并云端审计事件。
7. 同步必要协议/生成 TS、更新模块文档，复跑 Unit→Contract→Process/E2E，保存 diff 与证据，单卡可独立 revert。

**测试施工（函数名锁定；Given / When / Then）**
- Unit `tests/web/w4/test_w4_c06_unit.py::test_w4_c06_contract`：Given Full Runner 运行有子进程的命令 When 本机按急停 Then 主/子进程终止且新命令不执行。
- Module `tests/web/w4/test_w4_c06_module.py::test_w4_c06_integration`：Given 云端不可达 When 本机急停 Then 仍然成功并保留审计。
- 反向 `tests/web/w4/test_w4_c06_unit.py::test_w4_c06_negative`：Given audit 写入 When 读取日志 Then 不包含 API Key、剪贴板明文。
- E2E / Process：E2E-FULL-06 真机启动无害长命令→离线→急停，确认子进程不残留。
- 旧回归：任何碰 `core/` 或工具选取的卡加跑 `tests/test_cache/test_s1_s2_split.py` 和 `tests/test_cache/test_stable_prefix.py`；碰协议则加 `tests/test_protocol_schema.py`。

**验收命令（PowerShell；新测试文件由本卡创建，开卡前不得误判为已存在）**
```powershell
Set-Location 'D:\agent-demo\RxyCode\RxyCode1_1_0'
git status --short
python -m pytest 'tests/web/w4/test_w4_c06_unit.py' -q
python -m pytest 'tests/web/w4/test_w4_c06_module.py' -q
git diff --check
git status --short
```

**完成判据**
- [x] `test_w4_c06_contract`、`test_w4_c06_negative` 与 `test_w4_c06_integration` 全部真绿且无无故 skip。
- [x] 当前行为满足本卡冻结决策、现有 CLI/Desktop 回归符合期望。
- [x] 安全拒绝、失败和取消按本卡约束实测，未开发路径标 `BLOCKED` 而不是 PASS。
- [x] `evidence/web/WEB-W4-C06/` 有红绿日志、协议快照（若适用）、diff、人工复审与交接。

**Commit（仅此卡）**
`feat(web): web-w4-c06 - 本机急停、进程杀树、审计与托盘`

---

### WEB-W4-C07 · Runner 平台能力表与本机发行件验证
`优先级：P0` / 预计工时：0.5–2.5 工程日 / 依赖：WEB-W4-C01..C06 · **owner: release/runner**

**背景与当前代码事实**
用户是 Windows 路径环境，必须先确保 Windows 真机可用；Linux/macOS 不可用不能假 PASS。

**涉及文件（白名单；`NEW` = 本卡新增，`VERIFY_EXISTING` = 本卡必须检查已有文件或前置卡产物；路径不符须 STOP/提交裁定）**
| 文件 | Grep 锚点/前置 | 允许的改法 |
|---|---|---|
| `packages/rxycode-runner/src/rxycode_runner/desktop/capabilities.py` | `VERIFY_EXISTING` | Win/mac/Linux support matrix |
| `packages/rxycode-runner/pyproject.toml` | `NEW` | uv tool/安装入口 |
| `packages/rxycode-runner/src/rxycode_runner/remote/client.py` | `_publish_approvals` | 裁定：只有 runner 包的安装环境没有 `RxyCode` 时，hello 之后的审批发布和 tool_rpc 导入失败不拆掉已经建立的出站 WSS。装了完整树时行为不变。 |
| `tests/system/test_installed_package.py` | `test_` | 加入隔离 venv 安装验证 |
| `tests/web/w4/test_w4_c07_unit.py` | `NEW` | 严格单元契约，不得替生产降级 |
| `tests/web/w4/test_w4_c07_module.py` | `NEW` | 至少一个跨模块/进程/安全负测 |

**已经替你决定好的（不准自己发挥）**
Windows Local Full+ConPTY+CU 是首要可验证 Release；macOS Accessibility/Linux Wayland 必须显式 capability/unsupported；签名/打包按平台证据推进。

**否定边界**：本卡不实现第二套 Agent Loop、不跨表外文件“顺手修复”、不降低旧 `RiskLevel`、不以 mock/live screenshot 替代契约验收。现有路径/版本/依赖不符即 `BLOCKED_PREREQUISITE`，提案修改先审计。

**操作步骤（依次执行；TEST-first）**
1. 在隔离工作树读本卡上游源文件及对应模块 README，`rg` 定位锚点，记录 baseline 与当前 commit；无锚点 STOP。
2. **先建 RED 测试**：在 `tests/web/w4/test_w4_c07_unit.py` 写 `test_w4_c07_contract`、`test_w4_c07_negative`，在 `tests/web/w4/test_w4_c07_module.py` 写 `test_w4_c07_integration`，先运行观察**预期失败**，保存日志。
3. 建立 Windows/macOS/Linux 功能矩阵与自动 smoke
4. 用 uv tool build/安装真机进程
5. 验证卸载/托盘退出/凭证存储
6. 禁将发布版本标 cross-platform supported 若没真机验证。
7. 同步必要协议/生成 TS、更新模块文档，复跑 Unit→Contract→Process/E2E，保存 diff 与证据，单卡可独立 revert。

**测试施工（函数名锁定；Given / When / Then）**
- Unit `tests/web/w4/test_w4_c07_unit.py::test_w4_c07_contract`：Given Windows 新 venv When 安装 connect Then entrypoint/WSS 能启动。
- Module `tests/web/w4/test_w4_c07_module.py::test_w4_c07_integration`：Given macOS 不具备 Accessibility grant When 查询 capabilities Then desktop input 不被报告 available。
- 反向 `tests/web/w4/test_w4_c07_unit.py::test_w4_c07_negative`：Given 仅 Windows 跑过 E2E When 发版 Then mac/Linux 显示 unverified 而非 supported。
- E2E / Process：本卡无独立 UI E2E；由对应 Phase 出口跨进程测试承接。
- 旧回归：任何碰 `core/` 或工具选取的卡加跑 `tests/test_cache/test_s1_s2_split.py` 和 `tests/test_cache/test_stable_prefix.py`；碰协议则加 `tests/test_protocol_schema.py`。

**验收命令（PowerShell；新测试文件由本卡创建，开卡前不得误判为已存在）**
```powershell
Set-Location 'D:\agent-demo\RxyCode\RxyCode1_1_0'
git status --short
if (!(Test-Path 'packages/rxycode-runner/src/rxycode_runner/desktop/capabilities.py')) { throw 'BLOCKED_PREREQUISITE: packages/rxycode-runner/src/rxycode_runner/desktop/capabilities.py' }
rg -n --fixed-strings 'test_' 'tests/system/test_installed_package.py'
python -m pytest 'tests/web/w4/test_w4_c07_unit.py' -q
python -m pytest 'tests/web/w4/test_w4_c07_module.py' -q
git diff --check
git status --short
```

**完成判据**
- [x] `test_w4_c07_contract`、`test_w4_c07_negative` 与 `test_w4_c07_integration` 全部真绿且无无故 skip。
- [x] 当前行为满足本卡冻结决策、现有 CLI/Desktop 回归符合期望。
- [x] 安全拒绝、失败和取消按本卡约束实测，未开发路径标 `BLOCKED` 而不是 PASS。
- [x] `evidence/web/WEB-W4-C07/` 有红绿日志、协议快照（若适用）、diff、人工复审与交接。

**Commit（仅此卡）**
`feat(web): web-w4-c07 - Runner 平台能力表与本机发行件验证`

---

## §2 Wave 出口检查
- [x] W4 所有卡各有独立 commit 和 evidence，未勾选项不被宣称完成。
- [x] 既有行为回归没有被覆盖，新增 API 不依赖 mock/假状态。
- [x] 运行期错误、权限拒绝和用户可见状态有负向证据。
