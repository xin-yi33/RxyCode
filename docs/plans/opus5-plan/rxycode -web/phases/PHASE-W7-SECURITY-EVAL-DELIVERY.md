# Phase W7 · SECURITY-EVAL-DELIVERY（WEB 项目施工卡）

> **范围**：这是唯一可施工卡面，其他总设计文档不复制任务卡。执行旧项目卡时仍需服从旧 `DEV-ORDER.md`。每张卡独立分支/提交，严格遵守 `../00-WEB-EXECUTION-PLAN.md` WEB-R1–R12。

## §0 W7 前置与出口

共 6 张卡；开工先核实 upstream docs/code 与 `git status`，当前文件名只是目标设计，施工前须 `Test-Path`，不能因为示例而声称实现存在。

| 卡号 | 名称 | 前置 | owner |
|---|---|---|---|
| `WEB-W7-C01` | 认证/越权/Prompt Injection 全域安全评审 | WEB-W1..W6 | security |
| `WEB-W7-C02` | 崩溃混沌、断线恢复、负载和资源释放 | WEB-W7-C01,WEB-W2全部,WEB-W4全部,WEB-W5全部 | qa/reliability |
| `WEB-W7-C03` | 可复现 Agent Eval 和基线对照 | WEB-W7-C02,WEB-W6全部 | qa/evals |
| `WEB-W7-C04` | OpenTelemetry/Langfuse 与可解释成本看板 | WEB-W7-C02,WEB-W7-C03 | ops/tracing |
| `WEB-W7-C05` | Compose/CI/CD、迁移、发行与 HTTPS Demo | WEB-W7-C01..C04 | ops/release |
| `WEB-W7-C06` | 发布验证矩阵、用户文档与完整面试案例 | WEB-W7-C01..C05 | product/docs |

## §1 任务卡（TEST-first，可单卡施工）

### WEB-W7-C01 · 认证/越权/Prompt Injection 全域安全评审
`优先级：P1` / 预计工时：0.5–2.5 工程日 / 依赖：WEB-W1..W6 · **owner: security**

**背景与当前代码事实**
开放 Cloud SaaS 涉及公用户账号、预览、密钥、本机远程设备，必须全链审计且严重 P0 为零。

**涉及文件（白名单；`NEW` = 本卡新增，`VERIFY_EXISTING` = 本卡必须检查已有文件或前置卡产物；路径不符须 STOP/提交裁定）**
| 文件 | Grep 锚点/前置 | 允许的改法 |
|---|---|---|
| `packages/rxycode-server/src/rxycode_server/api/` | `VERIFY_EXISTING` | 核验 route 的 current_user/tenant policy |
| `packages/rxycode-runner/src/rxycode_runner/local/grant_store.py` | `NEW` | 核验本机授权/撤销 |
| `tests/web/security/test_threat_model.py` | `NEW` | 跨租户/PromptInjection/secret test |
| `tests/web/w7/test_w7_c01_unit.py` | `NEW` | 严格单元契约，不得替生产降级 |
| `tests/web/w7/test_w7_c01_module.py` | `NEW` | 至少一个跨模块/进程/安全负测 |
| `core/safety/policy.py` | `find_bash_disallowed_write_paths` | 裁定：评审发现 `-(?:Value\|Content)` 清洗正则会吃掉 `Set-Content`/`Add-Content` 的目标路径，使位置参数形式的绝对路径写完全绕过写路径闸（P1，full 权限下静默主机写）。允许且仅允许把该清洗项改为要求 `-` 前不紧跟字母，不放宽任何既有拒绝行为。复审追加：同一函数内 `@"..."@` here-string 整块清除会隐藏可执行内容、`Clear-Content` 缺动词、`$env:`/`%VAR%`/`~` 路径不展开——允许在同一函数内做收紧修复（扫描 here-string 内容、补动词、展开环境变量路径后判定），仍不放宽任何既有拒绝。二十轮复审后裁定闸门契约，共三条。(1) 命令文本中可见的写目标落在白名单外即拒绝。可见目标包括同一命令内字面赋值的变量和环境变量展开后的路径。(2) 凡把被执行命令本身或写目标藏到静态文本之外的构造，一律失败即拒绝，不再尝试解析。包括：命令位是变量或表达式（`& $x`、`& "$x"`、`& (...)`、`. $x`、`$x args`、`cmd /c $x`、`iex $x`）；非字面的 `Start-Process`/`start`；无法解码的编码命令；tar 解包时保留绝对成员路径或改写成员路径（`-P`/`--absolute-names`/`--transform`/`-s`）；tar 执行外部程序的选项（`--to-command`/`--use-compress-program`/`-I`/`--checkpoint-action`/`--info-script`/`-F`/`--rsh-command`）。(3) 运行字面命名的程序或脚本文件时，其内部行为不归本闸管，由 OS 沙箱与 grant 承担，不算本函数缺陷。只读用法被误拒（如 `tar -xOf`、`echo ar`、`npm start`）算缺陷。允许在同一函数内按此契约收紧，并补 `rar`/`ar` 的写目标识别。补充：如果起始工作目录（`workdir` 或回退目录）本身在白名单外，命令里只要出现写类动词、重定向或 .NET 写调用就拒绝。原因是相对目标和隐式写入当前目录（如 `tar -x`、`unzip`）都会落在白名单外。产品口径裁定（用户 2026-10-17 确认）：普通模式由三平台内核沙箱提供执行权限隔离；Full 是用户确认后在当前系统账户权限内解除沙箱、免审批，只保留进程回收和紧急停止。因此 Full 下的 `find_bash_disallowed_write_paths` 是尽力而为的防误写闸，不是安全边界。本卡写路径闸的验收以 `tests/web/w7/test_w7_c01_module.py` 现有用例为冻结语料：语料全部通过、已修项不回退即视为达标。审计新发现的同类绕过写法记为已知限制，记录在 `evidence/web/WEB-W7-C01/self-audit.md`，不阻塞本卡。白名单内的正常写被误拒仍算缺陷，必须修。普通模式缺失的 Windows 内核写隔离另开卡处理。后续卡顺序（用户确认）：W7-C02 到 C06 完成后，先做 B，再做 C。B：普通模式下，写路径闸拦下的 bash 命令改为转人工审批，批准后仍受内核沙箱约束；Full 保持拦下即拒绝、不弹审批。C：补齐 Windows 内核写隔离，并让三平台 OS 沙箱按权限模式自动开关（普通模式开启，Full 解除），Full 下保留 Job Object 进程回收与紧急停止。 |
| `packages/rxycode-server/src/rxycode_server/api/terminal_ws.py` | `stream_terminal` | 裁定：评审发现 WS 握手只校验 session+owner，未比对 `Origin` 与 `allowed_origins`（samesite=lax 缓解但未根除）。允许且仅允许在握手处补 Origin 校验，失败 `close(1008)`，不改既有身份/归属语义。 |
| `execution/tool_orchestrator.py` | `find_bash_disallowed_write_paths` 调用点 | 裁定：复审发现写路径闸按会话 cwd 解析相对目标，而 shell 实际用 `args["workdir"]`——允许且仅允许在 bash 写路径闸调用点把 `workdir` 透传给 `find_bash_disallowed_write_paths`，不改既有拦截/审批语义。 |

**已经替你决定好的（不准自己发挥）**
由后端/Runner 实施策略而不是 UI 隐藏；默认拒绝未知工具；未授权 Remote Full 坚决拒绝；敏感日志脱敏；Cloud Sandbox 失效不能 fall back OS。

**否定边界**：本卡不实现第二套 Agent Loop、不跨表外文件“顺手修复”、不降低旧 `RiskLevel`、不以 mock/live screenshot 替代契约验收。现有路径/版本/依赖不符即 `BLOCKED_PREREQUISITE`，提案修改先审计。

**操作步骤（依次执行；TEST-first）**
1. 在隔离工作树读本卡上游源文件及对应模块 README，`rg` 定位锚点，记录 baseline 与当前 commit；无锚点 STOP。
2. **先建 RED 测试**：在 `tests/web/w7/test_w7_c01_unit.py` 写 `test_w7_c01_contract`、`test_w7_c01_negative`，在 `tests/web/w7/test_w7_c01_module.py` 写 `test_w7_c01_integration`，先运行观察**预期失败**，保存日志。
3. 针对 threat table 编写攻击用例并先红
4. 在真实 Demo compose 网络跑身份和权限审计
5. 查 trace/secret leaks 和 network SSRF
6. 出修复报告与当前风险接受记录。
7. 同步必要协议/生成 TS、更新模块文档，复跑 Unit→Contract→Process/E2E，保存 diff 与证据，单卡可独立 revert。

**测试施工（函数名锁定；Given / When / Then）**
- Unit `tests/web/w7/test_w7_c01_unit.py::test_w7_c01_contract`：Given 用户 B 猜到用户 A 的 ID When 访问 Session/SSE/Artifact/Device Then 无越权数据。
- Module `tests/web/w7/test_w7_c01_module.py::test_w7_c01_integration`：Given 公开网页含诱导 prompt When Agent 读取 Then 不能越过敏感 Tool policy。
- 反向 `tests/web/w7/test_w7_c01_unit.py::test_w7_c01_negative`：Given Cloud 服务端伪造 Device Full When 没本机 grant Then 本机拒绝。
- E2E / Process：E2E-SECURITY-01 公网演示测试账户攻击模型且无真实破坏。
- 旧回归：任何碰 `core/` 或工具选取的卡加跑 `tests/test_cache/test_s1_s2_split.py` 和 `tests/test_cache/test_stable_prefix.py`；碰协议则加 `tests/test_protocol_schema.py`。

**验收命令（PowerShell；新测试文件由本卡创建，开卡前不得误判为已存在）**
```powershell
Set-Location 'D:\agent-demo\RxyCode\RxyCode1_1_0'
git status --short
if (!(Test-Path 'packages/rxycode-server/src/rxycode_server/api/')) { throw 'BLOCKED_PREREQUISITE: packages/rxycode-server/src/rxycode_server/api/' }
python -m pytest 'tests/web/w7/test_w7_c01_unit.py' -q
python -m pytest 'tests/web/w7/test_w7_c01_module.py' -q
git diff --check
git status --short
```

**完成判据**
- [x] `test_w7_c01_contract`、`test_w7_c01_negative` 与 `test_w7_c01_integration` 全部真绿且无无故 skip。
- [x] 当前行为满足本卡冻结决策、现有 CLI/Desktop 回归符合期望。
- [x] 安全拒绝、失败和取消按本卡约束实测，未开发路径标 `BLOCKED` 而不是 PASS。
- [x] `evidence/web/WEB-W7-C01/` 有红绿日志、协议快照（若适用）、diff、人工复审与交接。

**Commit（仅此卡）**
`feat(web): web-w7-c01 - 认证/越权/Prompt Injection 全域安全评审`

---

### WEB-W7-C02 · 崩溃混沌、断线恢复、负载和资源释放
`优先级：P1` / 预计工时：0.5–2.5 工程日 / 依赖：WEB-W7-C01,WEB-W2全部,WEB-W4全部,WEB-W5全部 · **owner: qa/reliability**

**背景与当前代码事实**
断网/Worker crash/审批中断/Runner 掉线/沙箱退出是 Agent 常态；简历要能提供真实可靠性证据。

**涉及文件（白名单；`NEW` = 本卡新增，`VERIFY_EXISTING` = 本卡必须检查已有文件或前置卡产物；路径不符须 STOP/提交裁定）**
| 文件 | Grep 锚点/前置 | 允许的改法 |
|---|---|---|
| `platform_tests/web/chaos/run_recovery.py` | `NEW` | 故障注入脚本与报告 |
| `tests/web/integration/test_chaos_suite.py` | `NEW` | DB/outbox/Runner/lease/PTY 边界 |
| `packages/rxycode-worker/src/rxycode_worker/recovery.py` | `NEW` | 只修审计确认的恢复缺陷 |
| `tests/web/w7/test_w7_c02_unit.py` | `NEW` | 严格单元契约，不得替生产降级 |
| `tests/web/w7/test_w7_c02_module.py` | `NEW` | 至少一个跨模块/进程/安全负测 |
| `utils/shell.py` | `_execute_controlled` / `_process_kwargs` | 裁定：混沌探测实测 worker 被硬杀后，其 `powershell.exe` 子进程以孤儿形式存活（Windows 无父进程死亡连坐；Job 回收只在 `os_sandbox.enabled` 时启用）。依据产品口径“进程回收在任何权限模式下保留”，允许且仅允许：在 Windows 上，`os_sandbox` 未启用时也为每个 shell 子进程绑定一个只设 `KILL_ON_JOB_CLOSE`、不设任何限额或限制的回收 Job；沿用既有 `open_sandbox_job`/`bind_spawned_process` 出生即绑定流程。回收 Job 建立失败时记录警告并照常执行（回收不是安全边界，不能因此阻断命令）。`os_sandbox` 启用时的既有行为不变。POSIX 的父进程死亡回收留给后续 C 卡。 |
| `core/sandbox/manager.py`、`core/sandbox/windows.py` | `open_sandbox_job` | 裁定：仅当上一行需要一个“只回收”的 JobPlan 构造入口时，允许新增该入口；不改既有限额、降级和 fail-closed 语义。 |
| `packages/rxycode-runner/src/rxycode_runner/local/native_backend.py`、`execution/tool_orchestrator.py` | `run_command` / `native_runner` | 裁定：混沌探测实测 full 模式本机 bash 经 `LocalNativeBackend.run_command` 用 `create_subprocess_shell` 执行，Windows 上是 cmd.exe；而其他模式经 ShellExecutor 用 PowerShell。同一条命令换到 full 就执行失败（W4-C01 起 `tests/web/w2/test_w2_c05_*` 因此变红），且 worker 被硬杀后 cmd.exe 子进程残留。允许且仅允许：`native_runner` 用 ShellExecutor 同一套命令构造（`_build_command` 或其公开别名）得到 argv 交给 `run_command`；`run_command` 接受该 argv 并以 exec 方式启动，Windows 上绑定只回收 Job（同上一行，失败只告警）。full 仍不套沙箱、不加限制，`wrapped` 仍为 False，`attach_sandbox` 仍拒绝。 |
| `tests/web/w2/test_w2_c05_unit.py`、`tests/web/w2/test_w2_c05_module.py` | `sys.path` | 裁定：只允许把 `packages/rxycode-runner/src` 加入测试的 `sys.path`（full 路径导入 `rxycode_runner`，与 W5 测试相同做法）；不改任何断言。 |

**已经替你决定好的（不准自己发挥）**
Checkpoint 不保证外部 OS 状态复活；所有 unknown tool calls 不重试；同一 session 数据库只有一 active Run；网页重连不重启 Worker。

**否定边界**：本卡不实现第二套 Agent Loop、不跨表外文件“顺手修复”、不降低旧 `RiskLevel`、不以 mock/live screenshot 替代契约验收。现有路径/版本/依赖不符即 `BLOCKED_PREREQUISITE`，提案修改先审计。

**操作步骤（依次执行；TEST-first）**
1. 在隔离工作树读本卡上游源文件及对应模块 README，`rg` 定位锚点，记录 baseline 与当前 commit；无锚点 STOP。
2. **先建 RED 测试**：在 `tests/web/w7/test_w7_c02_unit.py` 写 `test_w7_c02_contract`、`test_w7_c02_negative`，在 `tests/web/w7/test_w7_c02_module.py` 写 `test_w7_c02_integration`，先运行观察**预期失败**，保存日志。
3. 造真实进程 kill 和 PG/Redis/Runner 断线场景
4. 注入 event commit 后 Redis down
5. 统计恢复正确/unknown/失败分类
6. 确保无 process leak、跨租户串 events。
7. 同步必要协议/生成 TS、更新模块文档，复跑 Unit→Contract→Process/E2E，保存 diff 与证据，单卡可独立 revert。

**测试施工（函数名锁定；Given / When / Then）**
- Unit `tests/web/w7/test_w7_c02_unit.py::test_w7_c02_contract`：Given Worker 在审批中宕机 When 重启 Then approval 仍待批准且无重复工具。
- Module `tests/web/w7/test_w7_c02_module.py::test_w7_c02_integration`：Given 断网长活执行 When 恢复连接 Then seq 全部补齐、终态一致。
- 反向 `tests/web/w7/test_w7_c02_unit.py::test_w7_c02_negative`：Given tool side effect 已执行但 ACK 丢 When retry Then 不会再次执行。
- E2E / Process：E2E-CHAOS-01 从浏览器发起真实 Run，关连接+kill worker+恢复。
- 旧回归：任何碰 `core/` 或工具选取的卡加跑 `tests/test_cache/test_s1_s2_split.py` 和 `tests/test_cache/test_stable_prefix.py`；碰协议则加 `tests/test_protocol_schema.py`。

**验收命令（PowerShell；新测试文件由本卡创建，开卡前不得误判为已存在）**
```powershell
Set-Location 'D:\agent-demo\RxyCode\RxyCode1_1_0'
git status --short
python -m pytest 'tests/web/w7/test_w7_c02_unit.py' -q
python -m pytest 'tests/web/w7/test_w7_c02_module.py' -q
git diff --check
git status --short
```

**完成判据**
- [x] `test_w7_c02_contract`、`test_w7_c02_negative` 与 `test_w7_c02_integration` 全部真绿且无无故 skip。
- [x] 当前行为满足本卡冻结决策、现有 CLI/Desktop 回归符合期望。
- [x] 安全拒绝、失败和取消按本卡约束实测，未开发路径标 `BLOCKED` 而不是 PASS。
- [x] `evidence/web/WEB-W7-C02/` 有红绿日志、协议快照（若适用）、diff、人工复审与交接。

**Commit（仅此卡）**
`feat(web): web-w7-c02 - 崩溃混沌、断线恢复、负载和资源释放`

---

### WEB-W7-C03 · 可复现 Agent Eval 和基线对照
`优先级：P1` / 预计工时：0.5–2.5 工程日 / 依赖：WEB-W7-C02,WEB-W6全部 · **owner: qa/evals**

**背景与当前代码事实**
招聘项目必须说明成功率和成本，不能只录制成功 Demo；已有 `evals` 工具要复用且修正老测试的真/假执行区分。

**涉及文件（白名单；`NEW` = 本卡新增，`VERIFY_EXISTING` = 本卡必须检查已有文件或前置卡产物；路径不符须 STOP/提交裁定）**
| 文件 | Grep 锚点/前置 | 允许的改法 |
|---|---|---|
| `evals/web/taskset.jsonl` | `NEW` | ≥30 条固定 commit 的任务集和 oracle |
| `evals/web/run.py` | `NEW` | CLI vs Web/solo vs team 的同预算测量 |
| `evals/web/report.py` | `NEW` | p50/p95/success/token/cost 数值与 CI 证据 |
| `tests/web/w7/test_w7_c03_unit.py` | `NEW` | 严格单元契约，不得替生产降级 |
| `tests/web/w7/test_w7_c03_module.py` | `NEW` | 至少一个跨模块/进程/安全负测 |

**已经替你决定好的（不准自己发挥）**
指标必须来自真实 Agent 和真实 Tools，固定模型、任务版本、执行 target、预算、环境，失败样例全部计入；不写提前确定的“提升 300%”。

**否定边界**：本卡不实现第二套 Agent Loop、不跨表外文件“顺手修复”、不降低旧 `RiskLevel`、不以 mock/live screenshot 替代契约验收。现有路径/版本/依赖不符即 `BLOCKED_PREREQUISITE`，提案修改先审计。

**操作步骤（依次执行；TEST-first）**
1. 在隔离工作树读本卡上游源文件及对应模块 README，`rg` 定位锚点，记录 baseline 与当前 commit；无锚点 STOP。
2. **先建 RED 测试**：在 `tests/web/w7/test_w7_c03_unit.py` 写 `test_w7_c03_contract`、`test_w7_c03_negative`，在 `tests/web/w7/test_w7_c03_module.py` 写 `test_w7_c03_integration`，先运行观察**预期失败**，保存日志。
3. 选 Coding/Browser/Recovery/Remote 任务并锁 hash/许可证
4. 建立固定 oracle 和环境 reset
5. 跑真实评测，按 task_id 记录成功/失败/成本/耗时
6. 生成结果与局限说明。
7. 同步必要协议/生成 TS、更新模块文档，复跑 Unit→Contract→Process/E2E，保存 diff 与证据，单卡可独立 revert。

**测试施工（函数名锁定；Given / When / Then）**
- Unit `tests/web/w7/test_w7_c03_unit.py::test_w7_c03_contract`：Given 固定任务集 When 连续两次 eval Then input manifest/hash/模型版本完整可复核。
- Module `tests/web/w7/test_w7_c03_module.py::test_w7_c03_integration`：Given任务失败 When 报告指标 Then 失败计入分母、异常成本不丢。
- 反向 `tests/web/w7/test_w7_c03_unit.py::test_w7_c03_negative`：Given只跑一个 happy demo When 生成求职 report Then quality gate 不接受。
- E2E / Process：E2E-EVAL-01 从 taskset 中抽样 5 个全栈任务真跑并记录 trace。
- 旧回归：任何碰 `core/` 或工具选取的卡加跑 `tests/test_cache/test_s1_s2_split.py` 和 `tests/test_cache/test_stable_prefix.py`；碰协议则加 `tests/test_protocol_schema.py`。

**验收命令（PowerShell；新测试文件由本卡创建，开卡前不得误判为已存在）**
```powershell
Set-Location 'D:\agent-demo\RxyCode\RxyCode1_1_0'
git status --short
python -m pytest 'tests/web/w7/test_w7_c03_unit.py' -q
python -m pytest 'tests/web/w7/test_w7_c03_module.py' -q
git diff --check
git status --short
```

**完成判据**
- [x] `test_w7_c03_contract`、`test_w7_c03_negative` 与 `test_w7_c03_integration` 全部真绿且无无故 skip。
- [x] 当前行为满足本卡冻结决策、现有 CLI/Desktop 回归符合期望。
- [x] 安全拒绝、失败和取消按本卡约束实测，未开发路径标 `BLOCKED` 而不是 PASS。
- [x] `evidence/web/WEB-W7-C03/` 有红绿日志、协议快照（若适用）、diff、人工复审与交接。

**Commit（仅此卡）**
`feat(web): web-w7-c03 - 可复现 Agent Eval 和基线对照`

---

### WEB-W7-C04 · OpenTelemetry/Langfuse 与可解释成本看板
`优先级：P1` / 预计工时：0.5–2.5 工程日 / 依赖：WEB-W7-C02,WEB-W7-C03 · **owner: ops/tracing**

**背景与当前代码事实**
需要在技术面试中讲清 Run 的性能瓶颈、工具证据、Token/缓存命中和每个 Agent 的贡献。

**涉及文件（白名单；`NEW` = 本卡新增，`VERIFY_EXISTING` = 本卡必须检查已有文件或前置卡产物；路径不符须 STOP/提交裁定）**
| 文件 | Grep 锚点/前置 | 允许的改法 |
|---|---|---|
| `packages/rxycode-worker/src/rxycode_worker/telemetry.py` | `NEW` | Run/Graph/Tool tracing |
| `packages/rxycode-server/src/rxycode_server/metrics.py` | `NEW` | 业务指标/费用 |
| `apps/web/src/features/usage/UsagePage.tsx` | `NEW` | 客户端 trace 链接/统计 |
| `tests/web/w7/test_w7_c04_unit.py` | `NEW` | 严格单元契约，不得替生产降级 |
| `tests/web/w7/test_w7_c04_module.py` | `NEW` | 至少一个跨模块/进程/安全负测 |
| `packages/rxycode-server/src/rxycode_server/runs/service.py`、`packages/rxycode-worker/src/rxycode_worker/agent_events.py`、`packages/rxycode-worker/src/rxycode_worker/supervisor.py` | `create_run` / `RunJournal.record` / 租约执行入口 | 裁定扩展（审计 r1 发现 telemetry 无生产调用方）：仅允许在这些现有函数内加最小接线——server 侧在 create_run 成功提交后发一条 http/server span；traceparent 必须随 run 持久化（写进 `run.created` 事件 payload），worker 在 claim 时按 run_id 从 run_events 读回作 parent，不得靠进程级 env 传递（审计 r2-1）；worker 侧在租约执行入口包一条 run span，并在 `RunJournal.record` 对 tool_call 类方法同步发 tool span（attrs 带 tool_call_id，先过 telemetry.sanitize）。不改既有行为语义，失败只记日志不阻断业务；终态事务内的 span 导出用 SAVEPOINT 隔离（审计 r2-2）。 |
| `appserver/tui.py` | `write_tool_call` / `write_tool_result` | 裁定扩展（审计 r2-3：tool 通知的真实生产路径是 ToolOrchestrator→ProtocolTui，不进 RunJournal）：仅在 `write_tool_call`/`write_tool_result` 内加最小 best-effort hook——当进程已绑定 web run（`default_run_journal()` 非空）时，对 ToolBegin/ToolEnd 发/闭 `tool.<name>` span（tool_call_id=call_id，ok=False/非 success 映射 error status）；不改通知语义，异常只记日志。 |

**已经替你决定好的（不准自己发挥）**
OpenTelemetry span 贯穿 trace_id/run_id/tool_call_id；默认不把完整 prompt/密码写进 Langfuse；记录 model price version 和缓存统计；允许用户查看自己 Trace 摘要。

**否定边界**：本卡不实现第二套 Agent Loop、不跨表外文件“顺手修复”、不降低旧 `RiskLevel`、不以 mock/live screenshot 替代契约验收。现有路径/版本/依赖不符即 `BLOCKED_PREREQUISITE`，提案修改先审计。

**操作步骤（依次执行；TEST-first）**
1. 在隔离工作树读本卡上游源文件及对应模块 README，`rg` 定位锚点，记录 baseline 与当前 commit；无锚点 STOP。
2. **先建 RED 测试**：在 `tests/web/w7/test_w7_c04_unit.py` 写 `test_w7_c04_contract`、`test_w7_c04_negative`，在 `tests/web/w7/test_w7_c04_module.py` 写 `test_w7_c04_integration`，先运行观察**预期失败**，保存日志。
3. 先写无密钥日志/trace 传递 RED
4. 采集 server→worker→runner 全链跨度与成本
5. 生成真实仪表盘图片和可查的 trace id
6. 对照 Eval 运行结果发现性能瓶颈。
7. 同步必要协议/生成 TS、更新模块文档，复跑 Unit→Contract→Process/E2E，保存 diff 与证据，单卡可独立 revert。

**测试施工（函数名锁定；Given / When / Then）**
- Unit `tests/web/w7/test_w7_c04_unit.py::test_w7_c04_contract`：Given 真实 Cloud Run When 完成 Then 可从 trace_id 关联 HTTP/Worker/Tool 耗时。
- Module `tests/web/w7/test_w7_c04_module.py::test_w7_c04_integration`：Given token 计费 When 显示 Usage Then 与单 Run ledger 和 provider usage 对齐。
- 反向 `tests/web/w7/test_w7_c04_unit.py::test_w7_c04_negative`：Given 密钥出现在工具 stderr When trace 落库 Then 过滤/遮盖而非泄漏。
- E2E / Process：本卡无独立 UI E2E；由对应 Phase 出口跨进程测试承接。
- 旧回归：任何碰 `core/` 或工具选取的卡加跑 `tests/test_cache/test_s1_s2_split.py` 和 `tests/test_cache/test_stable_prefix.py`；碰协议则加 `tests/test_protocol_schema.py`。

**验收命令（PowerShell；新测试文件由本卡创建，开卡前不得误判为已存在）**
```powershell
Set-Location 'D:\agent-demo\RxyCode\RxyCode1_1_0'
git status --short
python -m pytest 'tests/web/w7/test_w7_c04_unit.py' -q
python -m pytest 'tests/web/w7/test_w7_c04_module.py' -q
git diff --check
git status --short
```

**完成判据**
- [x] `test_w7_c04_contract`、`test_w7_c04_negative` 与 `test_w7_c04_integration` 全部真绿且无无故 skip。
- [x] 当前行为满足本卡冻结决策、现有 CLI/Desktop 回归符合期望。
- [x] 安全拒绝、失败和取消按本卡约束实测，未开发路径标 `BLOCKED` 而不是 PASS。
- [x] `evidence/web/WEB-W7-C04/` 有红绿日志、协议快照（若适用）、diff、人工复审与交接。

**Commit（仅此卡）**
`feat(web): web-w7-c04 - OpenTelemetry/Langfuse 与可解释成本看板`

---

### WEB-W7-C05 · Compose/CI/CD、迁移、发行与 HTTPS Demo
`优先级：P1` / 预计工时：0.5–2.5 工程日 / 依赖：WEB-W7-C01..C04 · **owner: ops/release**

**背景与当前代码事实**
在线 Demo 是求职作品的核心，不能只靠开发者机器手动 `python api_server.py`；必须可部署可停止且安全。

**涉及文件（白名单；`NEW` = 本卡新增，`VERIFY_EXISTING` = 本卡必须检查已有文件或前置卡产物；路径不符须 STOP/提交裁定）**
| 文件 | Grep 锚点/前置 | 允许的改法 |
|---|---|---|
| `infra/compose/compose.yaml` | `VERIFY_EXISTING` | 固定 API+Worker+PG+Redis+proxy+objectstore |
| `infra/compose/Caddyfile` | `NEW` | HTTPS/headers/preview auth |
| `.github/workflows/web-ci.yml` | `NEW` | lint/type/contract/e2e/build |
| `docs/deploy/web-runbook.md` | `NEW` | 升级/回滚/恢复/日志说明 |
| `tests/web/w7/test_w7_c05_unit.py` | `NEW` | 严格单元契约，不得替生产降级 |
| `tests/web/w7/test_w7_c05_module.py` | `NEW` | 至少一个跨模块/进程/安全负测 |

**审计 r1 裁定（白名单外改动，均已评审确认，只许按所列范围改）**

- `packages/rxycode-worker/src/rxycode_worker/drain.py`（NEW）+ `__main__.py`（NEW）：审计发现部署栈里没有消费 `runs` 队?列的执行者——`python -m appserver` 是 stdio 传输进程，无人喂 JSON-RPC，queued run 永远不会被 claim。允许新增真实 drain 循环：轮询可认领 run（`pending` 或租约过期）、`supervisor.claim`、`runs.service.load_run` 读回持久化消息、`remember_web_run`+`publish_database_url` 绑定日志/trace、以 `dispatch_surface_prompt("web", ...)` 走真实 Session/AgentV2 回合路径执行、执行期续租并响应 `cancel_requested`（`confirm_cancel`）、结束时 `record_terminal_usage`+`commit_terminal`（失败即 `failed`）。worker 容器改跑 `python -m rxycode_worker.drain`。
- `packages/rxycode-server/src/rxycode_server/main.py`：`create_app`/`serve` 增加 `rate_limit_rpm` 参数（0=关闭，默认不变）；部署启动脚本（compose api command 内的 `serve_web.py` 片段）改为调用 `serve()`——`mode=local` + 非回环绑定沿用既有 `reject_as_public_web_gateway` 直接起不来。
- `packages/rxycode-server/src/rxycode_server/api/ratelimit.py`（NEW）：每客户端 IP 的内存定窗限流 ASGI 中间件（`429`+`{code: "RATE_LIMITED"}`+`Retry-After`）。冻结要求「公网演示限流」此前只停留在文字——Caddy 官方镜像无限流插件，故落在应用层；compose 以 `RXYCODE_WEB_RATE_LIMIT_RPM` 打开。
- `.gitignore`：加 `!docs/deploy/` 否定规则——runbook 属本卡交付物，必须可跟踪。
- CI lint 通道对提交树可重现的三处既有告警做最小删除修复：`rxycode_server/api/sse.py` 未用 `Iterator`、`rxycode_worker/interrupt_resume.py` 未用 `uuid`、`tests/web/w2/test_w2_c04_unit.py` 未用变量。
- 测试 validator 收紧：`ports` 条目必须显式 `host_ip` 且为回环（`8000:8000` 这类缺省全网卡发布拒绝）；CI 不变量检查同步补 port 检查；两个测试把 `compose up` 纳入 try/finally 保证超时也 `down -v`。
- `docs/deploy/web-runbook.md`：升级/回滚改为带版本的重新播种序列（删 `.rxy-sync-done`/`.migrate-done`、重新 tar 播种、重跑 migrate、重建 web-dist、再 recreate）；拓扑与边界说明同步 drain 事实。
- `evidence/web/WEB-W7-C05/NOTES.md`：修正 .gitignore 已被纳入跟踪的事实错误。

**审计 r3 裁定（白名单外改动，均已评审确认，只许按所列范围改）**

- `packages/rxycode-runner/src/rxycode_runner/sandbox/userns.py`（NEW）：审计 r3-F1 确认共享 worker 在容器宿主上裸跑 turn（`LocalNativeBackend` 刻意不套沙箱，Full 语义正确但公网共享 worker 不得使用）。允许新增真正的内核隔离执行面：以 Linux user/pid/ipc/uts namespace + bubblewrap 最小根挂载把**整个 turn**（`python -m rxycode_worker.drain` 的 turn-mode 子进程）关进 per-run 边界——uid 重映射、pid 命名空间隔离、`--die-with-parent` 整树回收、ro-bind 代码树、仅 run workspace 可写、`--clearenv` 仅白名单 env 透传。`available()` 必须真实探测（实测 `unshare`+bwrap 调用），探测失败或执行时报错一律 `IsolationUnavailable` fail-closed，绝不回落宿主 subprocess。
- `packages/rxycode-worker/src/rxycode_worker/drain.py`：drain 重构为「认领+看门狗的父进程」与「沙箱内执行的 turn 子进程」两段。父进程 claim、按 `RXYCODE_WORKER_EXECUTION` 执行放置闸（`cloud-only` 默认：仅接受 `cloud:{tenant}:{workspace}` 且 tenant 段必须等于 run 的 `tenant_id`——跨租户即拒；`local:*` 仍拒绝；`full`/`full_auto` 此条已被 W8-C01 替代（有效云目标上解析为沙箱内 `full_auto`，见 docs/architecture/web-rules-supplement-2026-10-20.md §3）；`sandboxed-local` 为开发机显式开关）、写 `worker.lease`、spawn 沙箱子进程、续租/状态看门狗（每次 DB 调用以 `wait_for` 限时，独立租约到期计时器在续约无法证明时取消 turn 并 `lost_lease`）、回收 `.turn-result.json`、写账本、`commit_terminal`。子进程内才是 `Session.prompt`/AgentV2：`install_tui_context_hook` + 按 run 的 tenant/target/profile 构造 `RunContext` + `bind_prompt_context(ProtocolTui)` + `bind_worker_todo_sink` + steer/command 消费，journal/投影照旧。审计 r3-F4：`assistant.final` 等终态投影不受 `_JOURNAL_CAP` 中间行截断，始终落库。审计 r3-F2 同此一并满足（续约/状态探测限时+独立到期计时器）。
- `infra/compose/compose.yaml`：worker 服务允许且仅允许 `security_opt: ["seccomp=unconfined"]`（bwrap/userns 需要 `unshare`/`mount`，Docker 默认 seccomp 禁之；不授任何 capability、不加 privileged、不给 docker.sock）+ `apt-get install bubblewrap` + `RXYCODE_WORKER_EXECUTION` env（默认 `cloud-only`）。其余服务不得携带 `security_opt`/`cap_add`/`privileged`。
- `tests/web/w7/test_w7_c05_unit.py`：validator 增补「`security_opt` 仅 worker 可含 `seccomp=unconfined`、任何服务 `cap_add`/`privileged` 拒绝」规则；新增放置闸矩阵单测（cloud-only 拒 `local:*`/跨租户 `cloud:`（原「拒 `full*`」断言已被 W8-C01 替代：接受 `cloud:` 目标上的 `full*` 并解析为 `full_auto`），sandboxed-local 接受 `local:*`）与 `userns.build_argv` 形状单测（无 docker 依赖）。
- `tests/web/w7/test_w7_c05_module.py`：执行腿种子改用 `cloud:{tenant}:w1` + 非 Full profile（`auto_edit`）——公网口径下 turn 在沙箱内真实执行到 provider 边界；保留 `sandbox:` 拒绝腿并新增 `local:*` 拒绝腿（公网栈不执行本机目标）。
- `docs/deploy/web-runbook.md`：补 worker 执行模型段（沙箱边界、凭据进出面、`seccomp=unconfined` 理由与限制、云 provider 形态替换点）。

**已经替你决定好的（不准自己发挥）**
公开 Demo 仅 Cloud Sandbox、访客配额、网络限速、无跨用户 File/Tool 权限；本机 Full Runner 不存在于公网共享 compose；开发配置与生产配置分离。

**否定边界**：本卡不实现第二套 Agent Loop、不跨表外文件“顺手修复”、不降低旧 `RiskLevel`、不以 mock/live screenshot 替代契约验收。现有路径/版本/依赖不符即 `BLOCKED_PREREQUISITE`，提案修改先审计。

**操作步骤（依次执行；TEST-first）**
1. 在隔离工作树读本卡上游源文件及对应模块 README，`rg` 定位锚点，记录 baseline 与当前 commit；无锚点 STOP。
2. **先建 RED 测试**：在 `tests/web/w7/test_w7_c05_unit.py` 写 `test_w7_c05_contract`、`test_w7_c05_negative`，在 `tests/web/w7/test_w7_c05_module.py` 写 `test_w7_c05_integration`，先运行观察**预期失败**，保存日志。
3. 先写 docker compose config/health/migration CI 检查
4. 接数据库迁移、API/Worker、静态 Web 和 HTTPS；实现最小权限部署
5. 从干净系统按 README 部署与关闭重启。
6. 同步必要协议/生成 TS、更新模块文档，复跑 Unit→Contract→Process/E2E，保存 diff 与证据，单卡可独立 revert。

**测试施工（函数名锁定；Given / When / Then）**
- Unit `tests/web/w7/test_w7_c05_unit.py::test_w7_c05_contract`：Given 全新容器主机 When compose up/migrate Then Web/worker/DB healthcheck 成功。
- Module `tests/web/w7/test_w7_c05_module.py::test_w7_c05_integration`：Given部署滚动更新 When 旧 Run 未完成 Then 不会丢记录、stale worker 不写状态。
- 反向 `tests/web/w7/test_w7_c05_unit.py::test_w7_c05_negative`：Given公共访客请求超预算或本机 Full When 访问 Then 服务端拒绝。
- E2E / Process：E2E-DEPLOY-01 从干净 compose 环境打开 HTTPS Demo→Cloud 任务完成。
- 旧回归：任何碰 `core/` 或工具选取的卡加跑 `tests/test_cache/test_s1_s2_split.py` 和 `tests/test_cache/test_stable_prefix.py`；碰协议则加 `tests/test_protocol_schema.py`。

**验收命令（PowerShell；新测试文件由本卡创建，开卡前不得误判为已存在）**
```powershell
Set-Location 'D:\agent-demo\RxyCode\RxyCode1_1_0'
git status --short
if (!(Test-Path 'infra/compose/compose.yaml')) { throw 'BLOCKED_PREREQUISITE: infra/compose/compose.yaml' }
python -m pytest 'tests/web/w7/test_w7_c05_unit.py' -q
python -m pytest 'tests/web/w7/test_w7_c05_module.py' -q
git diff --check
git status --short
```

**完成判据**
- [x] `test_w7_c05_contract`、`test_w7_c05_negative` 与 `test_w7_c05_integration` 全部真绿且无无故 skip。（contract/negative 在单测文件内真跑过 compose；integration 模块测试最近一轮 `1 passed in 383.89s` 真实栈）
- [x] 当前行为满足本卡冻结决策、现有 CLI/Desktop 回归符合期望。
- [x] 安全拒绝、失败和取消按本卡约束实测，未开发路径标 `BLOCKED` 而不是 PASS。（provider-success 腿与 Playwright 浏览器腿在 green.txt 中诚实标注 BLOCKED）
- [x] `evidence/web/WEB-W7-C05/` 有红绿日志、协议快照（若适用）、diff、人工复审与交接。（NOTES/red/green/self-audit/handoff 齐备；同一 Codex 会话 17 轮审计，最终 `VERDICT: NO_REMAINING_PROBLEMS` @ `3f87a02e`）

**Commit（仅此卡）**
`feat(web): web-w7-c05 - Compose/CI/CD、迁移、发行与 HTTPS Demo`

---

### WEB-W7-C06 · 发布验证矩阵、用户文档与完整面试案例
`优先级：P1` / 预计工时：0.5–2.5 工程日 / 依赖：WEB-W7-C01..C05 · **owner: product/docs**

**背景与当前代码事实**
项目若没有 Demo/文档/真实指标只能被视为实验，而不能作为强 AI 全栈展示项目。

**涉及文件（白名单；`NEW` = 本卡新增，`VERIFY_EXISTING` = 本卡必须检查已有文件或前置卡产物；路径不符须 STOP/提交裁定）**
| 文件 | Grep 锚点/前置 | 允许的改法 |
|---|---|---|
| `README.md` | `RxyCode` | 原产品说明加 Web 能力需等待真功能交付 |
| `docs/product/web-user-guide.md` | `NEW` | install/onboarding/errors/FAQ |
| `docs/architecture/web-system-design.md` | `NEW` | 架构图与 ADR 决策链 |
| `docs/portfolio/rxycode-web-case-study.md` | `NEW` | 实际开发挑战、证据/数字和技术复盘 |
| `tests/web/w7/test_w7_c06_unit.py` | `NEW` | 严格单元契约，不得替生产降级 |
| `tests/web/w7/test_w7_c06_module.py` | `NEW` | 至少一个跨模块/进程/安全负测 |
|

**开卡裁定（白名单外改动，先审计范围）**

- `.gitignore`：新增 `!docs/architecture/`、`!docs/architecture/**`、`!docs/portfolio/`、`!docs/portfolio/**` 两组否定——与 W6-C06 的 `!docs/product/`、C05 的 `!docs/deploy/` 同模式，让本卡要求的两个 `NEW` 文档可被 Git 检索（冻结决策要求「开发文档可在 Git 中检索」）。不放宽任何其他 docs/* 忽略。
- `test_w7_c06_integration` 的「未登录浏览器完成受限真实云任务」腿：本仓库不存在匿名 run HTTP 入口（runs API 仅有 GET/cancel/steer，均需 `require_write`）——模块测试以真实 `create_app` + dev PG + httpx ASGI 驱动**未登录拒绝面**（`/api/v1/me`、`/api/v1/runs/*`、带 CSRF/Origin 校验的写路径全部 401/403，即「受限」的真实语义），完整浏览器腿标记 `BLOCKED`（apps/web 无 Playwright 依赖），不得伪造 PASS。

**已经替你决定好的（不准自己发挥）**
简历条目只能使用真实 DONE+证据；记录支持的平台、已知限制、测量 setup；Demo 视频不得剪辑假场景成真。开发文档 `rxycode -web` 与源代码需可在 Git 中检索。

**否定边界**：本卡不实现第二套 Agent Loop、不跨表外文件“顺手修复”、不降低旧 `RiskLevel`、不以 mock/live screenshot 替代契约验收。现有路径/版本/依赖不符即 `BLOCKED_PREREQUISITE`，提案修改先审计。

**操作步骤（依次执行；TEST-first）**
1. 在隔离工作树读本卡上游源文件及对应模块 README，`rg` 定位锚点，记录 baseline 与当前 commit；无锚点 STOP。
2. **先建 RED 测试**：在 `tests/web/w7/test_w7_c06_unit.py` 写 `test_w7_c06_contract`、`test_w7_c06_negative`，在 `tests/web/w7/test_w7_c06_module.py` 写 `test_w7_c06_integration`，先运行观察**预期失败**，保存日志。
3. 汇总 48 卡的证据与 release tags
4. 自定义 README 功能矩阵，区分 planned/experimental/shipped
5. 写两分钟演示脚本及实际视频
6. 整理架构答辩题与真实指标。
7. 同步必要协议/生成 TS、更新模块文档，复跑 Unit→Contract→Process/E2E，保存 diff 与证据，单卡可独立 revert。

**测试施工（函数名锁定；Given / When / Then）**
- Unit `tests/web/w7/test_w7_c06_unit.py::test_w7_c06_contract`：Given README 声称支持 Full When 审计 Then 可定位真机 E2E 测试与 release。
- Module `tests/web/w7/test_w7_c06_module.py::test_w7_c06_integration`：Given公开 Demo URL When 从未登录浏览器访问 Then 能完成受限真实云任务。
- 反向 `tests/web/w7/test_w7_c06_unit.py::test_w7_c06_negative`：Given一项指标缺真实 taskset/report When 写简历 Then 模板保留占位而非猜数。
- E2E / Process：E2E-PORTFOLIO-01 第三方从 README 安装/运行并复核三主演示。
- 旧回归：任何碰 `core/` 或工具选取的卡加跑 `tests/test_cache/test_s1_s2_split.py` 和 `tests/test_cache/test_stable_prefix.py`；碰协议则加 `tests/test_protocol_schema.py`。

**验收命令（PowerShell；新测试文件由本卡创建，开卡前不得误判为已存在）**
```powershell
Set-Location 'D:\agent-demo\RxyCode\RxyCode1_1_0'
git status --short
rg -n --fixed-strings 'RxyCode' 'README.md'
python -m pytest 'tests/web/w7/test_w7_c06_unit.py' -q
python -m pytest 'tests/web/w7/test_w7_c06_module.py' -q
git diff --check
git status --short
```

**完成判据**
- [x] `test_w7_c06_contract`、`test_w7_c06_negative` 与 `test_w7_c06_integration` 全部真绿且无无故 skip。（3 passed，module 腿在真实 dev PG 上跑 `create_app` 拒绝面）
- [x] 当前行为满足本卡冻结决策、现有 CLI/Desktop 回归符合期望。
- [x] 安全拒绝、失败和取消按本卡约束实测，未开发路径标 `BLOCKED` 而不是 PASS。（匿名 run / 浏览器 E2E / OAuth 未配时的交互登录均诚实标注）
- [x] `evidence/web/WEB-W7-C06/` 有红绿日志、协议快照（若适用）、diff、人工复审与交接。（同一 Codex 会话 5 轮审计，最终 `VERDICT: NO_REMAINING_PROBLEMS` @ `d5af8602`）

**Commit（仅此卡）**
`feat(web): web-w7-c06 - 发布验证矩阵、用户文档与完整面试案例`

---

## §2 Wave 出口检查
- [ ] W7 所有卡各有独立 commit 和 evidence，未勾选项不被宣称完成。
- [ ] 既有行为回归没有被覆盖，新增 API 不依赖 mock/假状态。
- [ ] 运行期错误、权限拒绝和用户可见状态有负向证据。
