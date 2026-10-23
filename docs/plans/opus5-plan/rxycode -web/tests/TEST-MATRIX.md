# Web Agent TEST / Contract / Process / Negative 测试唯一目录

> **施工原则**：文件/函数名已按卡号冻结；所有路径都属于施工时应创建的目标文件，未实现前**不得宣称测试已存在或已通过**。强制 Given/When/Then，Red→Green→Integration→真实 E2E。受控本机 Full 负测不得执行破坏性命令。

## §1 专项硬门（每项同时含触发和可观测断言）

| Test ID | 层级 | 预定路径 | Given / When / Then | 对应卡 |
|---|---|---|---|---|
| `PKG-01` | Process | `tests/system/test_installed_package.py` | Given wheel 安装 When 全新虚拟环境运行 Then 所有包/import identity/资源可用 | `W1-C01` |
| `PROTO-01` | Contract | `tests/test_protocol_schema.py` | Given 旧 JSON-RPC fixture When Pydantic 生成 schema/TS Then 旧方法兼容并字段值稳定 | `W1-C04` |
| `SSE-01` | E2E | `tests/web/w2/test_w2_c04_module.py` | Given 1..42 events When after_seq=40 Then exactly 41,42 after browser reconnect | `W2-C04` |
| `SSE-02` | Chaos | `tests/web/w2/test_w2_c04_module.py` | Given DB replay 尾部与订阅之间 commit seq43 When 通知丢失 Then 仍由 DB catchup 收到43 | `W2-C04` |
| `SSE-03` | Contract | `tests/web/w3/test_w3_c03_unit.py` | Given PubSub 重复通知 When reducer 接收 Then 同 seq 只渲染一次 | `W3-C03` |
| `RUN-01` | Integration | `tests/web/w2/test_w2_c03_module.py` | Given 相同 tenant+request_id When 双并发请求 Then 仅一个 Run 和唯一初始 Event | `W2-C03` |
| `RUN-02` | Chaos | `tests/web/w2/test_w2_c03_module.py` | Given epoch 过期 Worker When commit Then 拒绝旧 lease 写入 | `W2-C03` |
| `APV-01` | Integration | `tests/web/w2/test_w2_c06_module.py` | Given 已决定的 approval When 重复 approve Then 409, 无工具二次执行 | `W2-C06` |
| `APV-02` | Process | `tests/web/w2/test_w2_c06_module.py` | Given 持久 waiting_approval When Worker/API 重启并隔天 resume Then 任务继续且非重复调用 | `W2-C06` |
| `REC-01` | Process | `tests/web/w2/test_w2_c05_module.py` | Given 纯读 checkpoint 后 Worker 终止 When 恢复 Then 能继续正确执行 | `W2-C05` |
| `REC-02` | Chaos | `tests/web/w4/test_w4_c04_module.py` | Given 外部操作已成功但 ack 丢 When retry Then unknown 阻止第二次副作用 | `W4-C04` |
| `RPC-01` | Security | `tests/web/w4/test_w4_c05_unit.py` | Given 无本机 grant When 云端 invoke Then Native Runner 拒绝 | `W4-C05` |
| `RPC-02` | Process | `tests/web/w4/test_w4_c04_module.py` | Given Runner 断线重连 When 相同 call_id 到达 Then 查询历史而不重复执行 | `W4-C04` |
| `RPC-03` | Integration | `tests/web/w4/test_w4_c04_module.py` | Given 并发 tool chunk When WS 发送 Then 单写者且顺序/限流正确 | `W4-C04` |
| `RPC-04` | Security | `tests/web/w4/test_w4_c05_module.py` | Given 云端仅声称 permission full When 无可信本机授权 Then Runner 拒绝 | `W4-C05` |
| `SEC-IDOR-01` | Security | `tests/web/security/test_threat_model.py` | Given A/B 租户 When B 猜 A 的 Run/Events/Artifact/Device Then 不泄漏 | `W7-C01` |
| `SEC-GRANT-01` | Security | `tests/web/security/test_threat_model.py` | Given 云端服务端被控制 When 修改 DB grant/full 标志 Then Runner 仍要求本机确认 | `W7-C01` |
| `SEC-REVOKE-01` | Security | `tests/web/w4/test_w4_c05_module.py` | Given grant 撤销 When 旧 WS 仍有效 Then 拒绝新调用/处理中调用 | `W4-C05` |
| `SEC-PI-01` | Security | `tests/web/security/test_threat_model.py` | Given 仓库含恶意提示 When Agent 看文件 Then 敏感工具仍走本机 policy | `W7-C01` |
| `SEC-PORT-01` | Security | `tests/web/w5/test_w5_c04_module.py` | Given Preview 的 URL 指向元数据/他人端口 When 用户访问 Then auth proxy 拒绝 | `W5-C04` |
| `SEC-PATH-01` | Security | `tests/web/security/test_threat_model.py` | Given 非 Full workspace 路径 symlink/.. When 文件操作 Then 拒绝 escape | `W7-C01` |
| `SEC-SECRET-01` | Security | `tests/web/security/test_threat_model.py` | Given API key 在 stderr When Trace/Artifact 输出 Then 明文脱敏 | `W7-C01` |
| `SEC-RPC-01` | Security | `tests/web/w4/test_w4_c04_module.py` | Given 攻击者重放 call_id/epoch When 收到 invoke Then 仅返回原状态/拒绝 | `W4-C04` |
| `SEC-DEVICE-01` | Security | `tests/web/w4/test_w4_c03_module.py` | Given 本机 Runner 在 NAT 后 When 启动 Then 仅出站 WSS，不需公网入站端口 | `W4-C03` |
| `SEC-LOG-01` | Security | `tests/web/w7/test_w7_c04_module.py` | Given 敏感 prompt/API key When 保存监控事件 Then 只显示可公开字段 | `W7-C04` |
| `TOOL-01` | Contract | `tests/web/w1/test_w1_c03_module.py` | Given 无 capability When 提交 ToolInvocation Then 无 executor side effects | `W1-C03` |
| `TOOL-02` | Integration | `tests/web/w6/test_w6_c01_module.py` | Given MCP readOnlyHint When classify Then 不降低 WRITE 默认风险 | `W6-C01` |
| `EVAL-01` | Eval | `evals/web/run.py` | Given 固定任务集 When 真实跑 Agent Then 每个任务计入分母+成本、保存 oracle/hash | `W7-C03` |
| `DEPLOY-01` | E2E | `apps/web/e2e/coding-workflow.spec.ts` | Given 全新 Compose When 启动并迁移 Then Cloud 真实任务在 HTTPS 完成 | `W7-C05` |

## §2 全卡 Unit / Module / Negative 唯一测试清单

每张施工卡同时含固定 `test_wN_cNN_contract`, `test_wN_cNN_integration`, `test_wN_cNN_negative` 三层，`W` 对应其 Wave；不要改成 `test_all`，测试失败不能删除。

| Test ID | 测试层 | 文件和函数 | Given / When / Then | 卡 |
|---|---|---|---|---|
| `WEB-W0-C01-U` | Unit | `tests/web/w0/test_w0_c01_unit.py::test_w0_c01_contract` | Given 本 Web 计划存在 When 扫描索引 Then 无重复卡号且全部文件有索引链接。 | `WEB-W0-C01` |
| `WEB-W0-C01-M` | Module | `tests/web/w0/test_w0_c01_module.py::test_w0_c01_integration` | Given 工作树的真实 .gitignore When 查询 Web 文档 Then 该文档确实可被 git 追踪且没有把遗留秘密打包。 | `WEB-W0-C01` |
| `WEB-W0-C01-N` | Negative | `tests/web/w0/test_w0_c01_unit.py::test_w0_c01_negative` | Given 缺少旧 DEV-ORDER When 扫描 Then BLOCKED_PREREQUISITE 而非建立虚假的权威替代。 | `WEB-W0-C01` |
| `WEB-W0-C02-U` | Unit | `tests/web/w0/test_w0_c02_unit.py::test_w0_c02_contract` | Given 某子系统设计需求 When 查询 Verdict Then 能定位至少一个已验证来源及排除方案。 | `WEB-W0-C02` |
| `WEB-W0-C02-M` | Module | `tests/web/w0/test_w0_c02_module.py::test_w0_c02_integration` | Given 审稿人检查设计来源 When 跳到 ADR Then 能从需求追溯到工程限制与版本号。 | `WEB-W0-C02` |
| `WEB-W0-C02-N` | Negative | `tests/web/w0/test_w0_c02_unit.py::test_w0_c02_negative` | Given 外部仓许可证未知 When 判定实现 Then 必须标 RESEARCH_REQUIRED 不能复制代码。 | `WEB-W0-C02` |
| `WEB-W0-C03-U` | Unit | `tests/web/w0/test_w0_c03_unit.py::test_w0_c03_contract` | Given 相同 session_id+workspace When 二次 prompt Then 保留 agent_runtimes 且只刷新 emit。 | `WEB-W0-C03` |
| `WEB-W0-C03-M` | Module | `tests/web/w0/test_w0_c03_module.py::test_w0_c03_integration` | Given appserver 发送已有事件 When 旧协议客户端消费 Then 类型与生命周期不漂移。 | `WEB-W0-C03` |
| `WEB-W0-C03-N` | Negative | `tests/web/w0/test_w0_c03_unit.py::test_w0_c03_negative` | Given 基线缺失测试文件 When 评审 Then 明确 BLOCKED 而不是跳过报绿。 | `WEB-W0-C03` |
| `WEB-W0-C04-U` | Unit | `tests/web/w0/test_w0_c04_unit.py::test_w0_c04_contract` | Given 用户七大要求 When 检查追踪表 Then 每条都有 owner、开发卡和自动测试 ID。 | `WEB-W0-C04` |
| `WEB-W0-C04-M` | Module | `tests/web/w0/test_w0_c04_module.py::test_w0_c04_integration` | Given 一个新 Web 命令 When 与旧 protocol 重名 Then 有冲突裁定或 BLOCKED。 | `WEB-W0-C04` |
| `WEB-W0-C04-N` | Negative | `tests/web/w0/test_w0_c04_unit.py::test_w0_c04_negative` | Given 还有 unresolved P0 冲突 When 发起 W1 Then 门禁拒绝。 | `WEB-W0-C04` |
| `WEB-W1-C01-U` | Unit | `tests/web/w1/test_w1_c01_unit.py::test_w1_c01_contract` | Given legacy import 和新 package import When 导入 Session Then 类型 identity 是同一实现。 | `WEB-W1-C01` |
| `WEB-W1-C01-M` | Module | `tests/web/w1/test_w1_c01_module.py::test_w1_c01_integration` | Given wheel 安装到独立 venv When 启动 CLI/AppServer Then 没有遗漏子包/资源。 | `WEB-W1-C01` |
| `WEB-W1-C01-N` | Negative | `tests/web/w1/test_w1_c01_unit.py::test_w1_c01_negative` | Given 两份 AgentV2 对象被创建 When import audit Then 测试失败并阻止合并。 | `WEB-W1-C01` |
| `WEB-W1-C02-U` | Unit | `tests/web/w1/test_w1_c02_unit.py::test_w1_c02_contract` | Given 同一个 Session 的两轮 Run When 创建 context Then run_id 不同而 session identity 不重建。 | `WEB-W1-C02` |
| `WEB-W1-C02-M` | Module | `tests/web/w1/test_w1_c02_module.py::test_w1_c02_integration` | Given 两个并发项目 When 运行上下文穿透 ToolOrchestrator Then tenant_id/target_id 不串。 | `WEB-W1-C02` |
| `WEB-W1-C02-N` | Negative | `tests/web/w1/test_w1_c02_unit.py::test_w1_c02_negative` | Given 客户端伪造 tenant_id When 服务端构造 RunContext Then 忽略请求体、以鉴权身份为准。 | `WEB-W1-C02` |
| `WEB-W1-C03-U` | Unit | `tests/web/w1/test_w1_c03_unit.py::test_w1_c03_contract` | Given target 缺 desktop capability When 模型请求 screenshot Then 被统一门拒绝。 | `WEB-W1-C03` |
| `WEB-W1-C03-M` | Module | `tests/web/w1/test_w1_c03_module.py::test_w1_c03_integration` | Given MCP 工具标 readOnlyHint When 走现有 gate Then 仍按默认 WRITE 审批或授权。 | `WEB-W1-C03` |
| `WEB-W1-C03-N` | Negative | `tests/web/w1/test_w1_c03_unit.py::test_w1_c03_negative` | Given invoke 未经 ToolOrchestrator When 尝试 NativeBackend Then 合同测试检测绕行。 | `WEB-W1-C03` |
| `WEB-W1-C04-U` | Unit | `tests/web/w1/test_w1_c04_unit.py::test_w1_c04_contract` | Given 已有 JSON-RPC fixture When 用新 schema parse Then 与旧版结构一致。 | `WEB-W1-C04` |
| `WEB-W1-C04-M` | Module | `tests/web/w1/test_w1_c04_module.py::test_w1_c04_integration` | Given Python Pydantic 模型导出 When 编译 TS Client Then 类型和版本 digest 匹配。 | `WEB-W1-C04` |
| `WEB-W1-C04-N` | Negative | `tests/web/w1/test_w1_c04_unit.py::test_w1_c04_negative` | Given 新 required 字段破坏旧客户端 When 解析 legacy fixture Then 兼容测试红。 | `WEB-W1-C04` |
| `WEB-W1-C05-U` | Unit | `tests/web/w1/test_w1_c05_unit.py::test_w1_c05_contract` | Given 各入口相同测试任务 When 初始化 core Then 仅同一受测试 AgentRuntime 实现被使用。 | `WEB-W1-C05` |
| `WEB-W1-C05-M` | Module | `tests/web/w1/test_w1_c05_module.py::test_w1_c05_integration` | Given 原 CLI/Web 参数 When 查看 `--help` Then 原命令未消失、新命令有明确说明。 | `WEB-W1-C05` |
| `WEB-W1-C05-N` | Negative | `tests/web/w1/test_w1_c05_unit.py::test_w1_c05_negative` | Given Web 代码依赖 Electron preload When 构建浏览器入口 Then 静态检查拒绝依赖。 | `WEB-W1-C05` |
| `WEB-W2-C01-U` | Unit | `tests/web/w2/test_w2_c01_unit.py::test_w2_c01_contract` | Given 空 PostgreSQL When upgrade head Then 业务表/唯一索引/约束完整可查询。 | `WEB-W2-C01` |
| `WEB-W2-C01-M` | Module | `tests/web/w2/test_w2_c01_module.py::test_w2_c01_integration` | Given 两个 tenant 同名 project When 插入 Then 相互隔离且所有 FK 一致。 | `WEB-W2-C01` |
| `WEB-W2-C01-N` | Negative | `tests/web/w2/test_w2_c01_unit.py::test_w2_c01_negative` | Given 同 tenant 相同 request_id When 创建两 Run Then 数据库拒绝第二次创建。 | `WEB-W2-C01` |
| `WEB-W2-C02-U` | Unit | `tests/web/w2/test_w2_c02_unit.py::test_w2_c02_contract` | Given 用户登录 When GET /me Then 返回真实授权组织和用户信息。 | `WEB-W2-C02` |
| `WEB-W2-C02-M` | Module | `tests/web/w2/test_w2_c02_module.py::test_w2_c02_integration` | Given 两个用户 When A 访问 B 的 project/session Then 返回受控 403/404 无泄漏。 | `WEB-W2-C02` |
| `WEB-W2-C02-N` | Negative | `tests/web/w2/test_w2_c02_unit.py::test_w2_c02_negative` | Given CSRF 缺失或恶意 Origin When 写入项目 Then 拒绝且无 DB 变化。 | `WEB-W2-C02` |
| `WEB-W2-C03-U` | Unit | `tests/web/w2/test_w2_c03_unit.py::test_w2_c03_contract` | Given 同请求幂等键 When 两次 POST Then 只有一个 Run 并返回同一 ID。 | `WEB-W2-C03` |
| `WEB-W2-C03-M` | Module | `tests/web/w2/test_w2_c03_module.py::test_w2_c03_integration` | Given 两 Worker 同时 claim When DB 锁竞争 Then 只有一个拥有任务和有效 epoch。 | `WEB-W2-C03` |
| `WEB-W2-C03-N` | Negative | `tests/web/w2/test_w2_c03_unit.py::test_w2_c03_negative` | Given 旧 Worker 租约已失效 When 写终态 Then CAS 拒绝。 | `WEB-W2-C03` |
| `WEB-W2-C04-U` | Unit | `tests/web/w2/test_w2_c04_unit.py::test_w2_c04_contract` | Given seq=1..42 When 断线用 after_seq=40 重连 Then 正好 41,42 一次。 | `WEB-W2-C04` |
| `WEB-W2-C04-M` | Module | `tests/web/w2/test_w2_c04_module.py::test_w2_c04_integration` | Given Redis notify 丢失 When DB seq=43 已提交 Then 心跳/轮询仍补齐 43。 | `WEB-W2-C04` |
| `WEB-W2-C04-N` | Negative | `tests/web/w2/test_w2_c04_unit.py::test_w2_c04_negative` | Given B 用户订阅 A Run 或返回 cursor_expired When 访问 Then 无数据泄露/不静默跳到最新。 | `WEB-W2-C04` |
| `WEB-W2-C05-U` | Unit | `tests/web/w2/test_w2_c05_unit.py::test_w2_c05_contract` | Given Node 纯读 When Worker 重启 Then 从 Checkpoint 正确恢复。 | `WEB-W2-C05` |
| `WEB-W2-C05-M` | Module | `tests/web/w2/test_w2_c05_module.py::test_w2_c05_integration` | Given Shell 写操作完成但结果 ACK 丢失 When 恢复 Then 不自动重复执行。 | `WEB-W2-C05` |
| `WEB-W2-C05-N` | Negative | `tests/web/w2/test_w2_c05_unit.py::test_w2_c05_negative` | Given checkpointer 不可用 When 收到 Run Then fail closed 不新建无记录副作用。 | `WEB-W2-C05` |
| `WEB-W2-C06-U` | Unit | `tests/web/w2/test_w2_c06_unit.py::test_w2_c06_contract` | Given 用户第二天登录 When 查看 pending approval Then 原请求和权限范围仍存在。 | `WEB-W2-C06` |
| `WEB-W2-C06-M` | Module | `tests/web/w2/test_w2_c06_module.py::test_w2_c06_integration` | Given 决定 approve 后 Worker 重启 When graph resume Then 工具最多执行一次。 | `WEB-W2-C06` |
| `WEB-W2-C06-N` | Negative | `tests/web/w2/test_w2_c06_unit.py::test_w2_c06_negative` | Given 过期/取消 approval When 重复 approve Then 409 APPROVAL_STALE，不产生副作用。 | `WEB-W2-C06` |
| `WEB-W2-C07-U` | Unit | `tests/web/w2/test_w2_c07_unit.py::test_w2_c07_contract` | Given 工具产生文件 When 完成 Then Artifact 可在项目工作区下载、digest 匹配。 | `WEB-W2-C07` |
| `WEB-W2-C07-M` | Module | `tests/web/w2/test_w2_c07_module.py::test_w2_c07_integration` | Given同一 Run usage 重放 When 算成本 Then 不重复增加记录。 | `WEB-W2-C07` |
| `WEB-W2-C07-N` | Negative | `tests/web/w2/test_w2_c07_unit.py::test_w2_c07_negative` | Given B 用户持有 A artifact id When 请求 Then 严格拒绝。 | `WEB-W2-C07` |
| `WEB-W3-C01-U` | Unit | `tests/web/w3/test_w3_c01_unit.py::test_w3_c01_contract` | Given 页面 API 未就绪 When 登录 Web Then 明确显示 error/retry，不白屏。 | `WEB-W3-C01` |
| `WEB-W3-C01-M` | Module | `tests/web/w3/test_w3_c01_module.py::test_w3_c01_integration` | Given Desktop 纯 React 组件 When Web 构建 Then 不引入 Electron/preload/node builtins。 | `WEB-W3-C01` |
| `WEB-W3-C01-N` | Negative | `tests/web/w3/test_w3_c01_unit.py::test_w3_c01_negative` | Given Browser 环境 When 搜索 bundle Then 无 secret、fs/child_process/Electron API。 | `WEB-W3-C01` |
| `WEB-W3-C02-U` | Unit | `tests/web/w3/test_w3_c02_unit.py::test_w3_c02_contract` | Given 登录用户 When 导入 Repo Then Server 返回真实 Project 可在刷新后复现。 | `WEB-W3-C02` |
| `WEB-W3-C02-M` | Module | `tests/web/w3/test_w3_c02_module.py::test_w3_c02_integration` | Given 用户选 Local 模式 When 访问 localhost Then 不强迫公网账户才能建 Session。 | `WEB-W3-C02` |
| `WEB-W3-C02-N` | Negative | `tests/web/w3/test_w3_c02_unit.py::test_w3_c02_negative` | Given OAuth 失败或 Key 保存失败 When 跳转 Then 显示失败并不得伪建 Project。 | `WEB-W3-C02` |
| `WEB-W3-C03-U` | Unit | `tests/web/w3/test_w3_c03_unit.py::test_w3_c03_contract` | Given events 1,2,2,4,3 When reducer 消费 Then 最终顺序一致且重复2仅出现一次。 | `WEB-W3-C03` |
| `WEB-W3-C03-M` | Module | `tests/web/w3/test_w3_c03_module.py::test_w3_c03_integration` | Given SSE 重连 When Web 重新加载 Then Run 真实状态/审批/工具卡一致。 | `WEB-W3-C03` |
| `WEB-W3-C03-N` | Negative | `tests/web/w3/test_w3_c03_unit.py::test_w3_c03_negative` | Given intermediate child text 乱序 When final 到达 Then 主答复末尾只有最终用户答案。 | `WEB-W3-C03` |
| `WEB-W3-C04-U` | Unit | `tests/web/w3/test_w3_c04_unit.py::test_w3_c04_contract` | Given 工具真实改了文件 When 打开 Diff Then hunk 与工作区实际变化匹配。 | `WEB-W3-C04` |
| `WEB-W3-C04-M` | Module | `tests/web/w3/test_w3_c04_module.py::test_w3_c04_integration` | Given 文件变更与用户提交审阅竞态 When base_revision 过期 Then 拒绝并提示刷新。 | `WEB-W3-C04` |
| `WEB-W3-C04-N` | Negative | `tests/web/w3/test_w3_c04_unit.py::test_w3_c04_negative` | Given 未授权其他 Workspace When 使用路径猜测 Then 只能收到拒绝。 | `WEB-W3-C04` |
| `WEB-W3-C05-U` | Unit | `tests/web/w3/test_w3_c05_unit.py::test_w3_c05_contract` | Given PTY 启动 python -i When 输入 print Then 输出与交互一致且 exit_code 已知。 | `WEB-W3-C05` |
| `WEB-W3-C05-M` | Module | `tests/web/w3/test_w3_c05_module.py::test_w3_c05_integration` | Given浏览器刷新 When PTY 还活着 Then 可重新附着或正确提示不支持。 | `WEB-W3-C05` |
| `WEB-W3-C05-N` | Negative | `tests/web/w3/test_w3_c05_unit.py::test_w3_c05_negative` | Given 权限不足 When WS 连接别人 PTY Then 握手拒绝且无进程泄漏。 | `WEB-W3-C05` |
| `WEB-W3-C06-U` | Unit | `tests/web/w3/test_w3_c06_unit.py::test_w3_c06_contract` | Given waiting_approval When 显示审批卡 Then 用户能看目标工具/路径/时限。 | `WEB-W3-C06` |
| `WEB-W3-C06-M` | Module | `tests/web/w3/test_w3_c06_module.py::test_w3_c06_integration` | Given 用户批准 When server 尚未确认 Then UI 不立即标记 succeeded。 | `WEB-W3-C06` |
| `WEB-W3-C06-N` | Negative | `tests/web/w3/test_w3_c06_unit.py::test_w3_c06_negative` | Given 审批已过期 When 再点批准 Then UI 呈现冲突不假继续。 | `WEB-W3-C06` |
| `WEB-W3-C07-U` | Unit | `tests/web/w3/test_w3_c07_unit.py::test_w3_c07_contract` | Given 键盘用户 When 打开审批弹窗 Then 焦点受控且可返回原位置。 | `WEB-W3-C07` |
| `WEB-W3-C07-M` | Module | `tests/web/w3/test_w3_c07_module.py::test_w3_c07_integration` | Given 375px viewport When 打开活动 Run Then 可查看状态/审批/取消。 | `WEB-W3-C07` |
| `WEB-W3-C07-N` | Negative | `tests/web/w3/test_w3_c07_unit.py::test_w3_c07_negative` | Given API 不可达 When 访问工作台 Then 显示可恢复错误而非白屏。 | `WEB-W3-C07` |
| `WEB-W4-C01-U` | Unit | `tests/web/w4/test_w4_c01_unit.py::test_w4_c01_contract` | Given local full When shell 启动 Then pid 属于当前用户 native session、没有 sandbox wrapper。 | `WEB-W4-C01` |
| `WEB-W4-C01-M` | Module | `tests/web/w4/test_w4_c01_module.py::test_w4_c01_integration` | Given target=local permission=ask When 相同命令 Then 仍按原审批限制。 | `WEB-W4-C01` |
| `WEB-W4-C01-N` | Negative | `tests/web/w4/test_w4_c01_unit.py::test_w4_c01_negative` | Given 强制注入 SandboxBackend When full mode Then 测试失败证明不会误走沙箱。 | `WEB-W4-C01` |
| `WEB-W4-C02-U` | Unit | `tests/web/w4/test_w4_c02_unit.py::test_w4_c02_contract` | Given 两显示器与 DPI 值 When 点击目标窗口控件 Then 坐标转换正确。 | `WEB-W4-C02` |
| `WEB-W4-C02-M` | Module | `tests/web/w4/test_w4_c02_module.py::test_w4_c02_integration` | Given 可访问桌面 When 截图/打开普通应用 Then 返回真实像素/窗口 ID。 | `WEB-W4-C02` |
| `WEB-W4-C02-N` | Negative | `tests/web/w4/test_w4_c02_unit.py::test_w4_c02_negative` | Given 锁屏/Wayland 不具备能力 When 请求 click Then 明确 CAPABILITY_UNAVAILABLE、不偷用别的工具。 | `WEB-W4-C02` |
| `WEB-W4-C03-U` | Unit | `tests/web/w4/test_w4_c03_unit.py::test_w4_c03_contract` | Given 本机跑 connect When 授权配对 Then Devices API 显示正确设备/OS/capability。 | `WEB-W4-C03` |
| `WEB-W4-C03-M` | Module | `tests/web/w4/test_w4_c03_module.py::test_w4_c03_integration` | Given 云端断开 When Runner reconnect Then 使用合法新会话而不自动升级授权。 | `WEB-W4-C03` |
| `WEB-W4-C03-N` | Negative | `tests/web/w4/test_w4_c03_unit.py::test_w4_c03_negative` | Given 错误 token/过期码 When 握手 Then 拒绝且无运行工具权限。 | `WEB-W4-C03` |
| `WEB-W4-C04-U` | Unit | `tests/web/w4/test_w4_c04_unit.py::test_w4_c04_contract` | Given call_id 重复到达 When Runner 上次已 completed Then 回传原结果且不执行第二次。 | `WEB-W4-C04` |
| `WEB-W4-C04-M` | Module | `tests/web/w4/test_w4_c04_module.py::test_w4_c04_integration` | Given stdout 多 chunk When 断线重连 Then chunk seq 去重/重放或有明确截断提示。 | `WEB-W4-C04` |
| `WEB-W4-C04-N` | Negative | `tests/web/w4/test_w4_c04_unit.py::test_w4_c04_negative` | Given 写操作 ACK 消失 When 远端重试 Then 标 unknown 不重复写。 | `WEB-W4-C04` |
| `WEB-W4-C05-U` | Unit | `tests/web/w4/test_w4_c05_unit.py::test_w4_c05_contract` | Given 云端请求 Remote Full When 本机明确确认 Then 范围内 shell/click 可无逐项审批。 | `WEB-W4-C05` |
| `WEB-W4-C05-M` | Module | `tests/web/w4/test_w4_c05_module.py::test_w4_c05_integration` | Given 本机批准临时 grant When 到期或 revoke Then 后续工具被拒绝。 | `WEB-W4-C05` |
| `WEB-W4-C05-N` | Negative | `tests/web/w4/test_w4_c05_unit.py::test_w4_c05_negative` | Given Server 伪造 permission=full When 本机没 grant Then 拒绝且写审计。 | `WEB-W4-C05` |
| `WEB-W4-C06-U` | Unit | `tests/web/w4/test_w4_c06_unit.py::test_w4_c06_contract` | Given Full Runner 运行有子进程的命令 When 本机按急停 Then 主/子进程终止且新命令不执行。 | `WEB-W4-C06` |
| `WEB-W4-C06-M` | Module | `tests/web/w4/test_w4_c06_module.py::test_w4_c06_integration` | Given 云端不可达 When 本机急停 Then 仍然成功并保留审计。 | `WEB-W4-C06` |
| `WEB-W4-C06-N` | Negative | `tests/web/w4/test_w4_c06_unit.py::test_w4_c06_negative` | Given audit 写入 When 读取日志 Then 不包含 API Key、剪贴板明文。 | `WEB-W4-C06` |
| `WEB-W4-C07-U` | Unit | `tests/web/w4/test_w4_c07_unit.py::test_w4_c07_contract` | Given Windows 新 venv When 安装 connect Then entrypoint/WSS 能启动。 | `WEB-W4-C07` |
| `WEB-W4-C07-M` | Module | `tests/web/w4/test_w4_c07_module.py::test_w4_c07_integration` | Given macOS 不具备 Accessibility grant When 查询 capabilities Then desktop input 不被报告 available。 | `WEB-W4-C07` |
| `WEB-W4-C07-N` | Negative | `tests/web/w4/test_w4_c07_unit.py::test_w4_c07_negative` | Given 仅 Windows 跑过 E2E When 发版 Then mac/Linux 显示 unverified 而非 supported。 | `WEB-W4-C07` |
| `WEB-W5-C01-U` | Unit | `tests/web/w5/test_w5_c01_unit.py::test_w5_c01_contract` | Given tenant A 创建 sandbox When 运行 exec Then 在隔离资源中执行而非 Server 主机。 | `WEB-W5-C01` |
| `WEB-W5-C01-M` | Module | `tests/web/w5/test_w5_c01_module.py::test_w5_c01_integration` | Given Runtime unavailable When 创建 Run Then 阻止工具并明确目标不可用。 | `WEB-W5-C01` |
| `WEB-W5-C01-N` | Negative | `tests/web/w5/test_w5_c01_unit.py::test_w5_c01_negative` | Given tenant B 知道 A sandbox ID When attach Then 严格拒绝。 | `WEB-W5-C01` |
| `WEB-W5-C02-U` | Unit | `tests/web/w5/test_w5_c02_unit.py::test_w5_c02_contract` | Given cloud sandbox When 读取 host /etc 与其他项目 Then 不可见。 | `WEB-W5-C02` |
| `WEB-W5-C02-M` | Module | `tests/web/w5/test_w5_c02_module.py::test_w5_c02_integration` | Given 资源超过 quota When 工具执行 Then sandbox 被限制而 Server/其他租户可用。 | `WEB-W5-C02` |
| `WEB-W5-C02-N` | Negative | `tests/web/w5/test_w5_c02_unit.py::test_w5_c02_negative` | Given 试图访问 169.254.169.254 或 Docker socket When 执行 Then 被阻断。 | `WEB-W5-C02` |
| `WEB-W5-C03-U` | Unit | `tests/web/w5/test_w5_c03_unit.py::test_w5_c03_contract` | Given 公开样例仓 When 导入 Then sandbox 中 revision 正确，可运行测试。 | `WEB-W5-C03` |
| `WEB-W5-C03-M` | Module | `tests/web/w5/test_w5_c03_module.py::test_w5_c03_integration` | Given 同一任务两次执行 When 初始化 Then 可从固定 commit 复现基础文件。 | `WEB-W5-C03` |
| `WEB-W5-C03-N` | Negative | `tests/web/w5/test_w5_c03_unit.py::test_w5_c03_negative` | Given 私有仓 token 泄漏尝试 When 检查 artifact/日志 Then 不含密钥。 | `WEB-W5-C03` |
| `WEB-W5-C04-U` | Unit | `tests/web/w5/test_w5_c04_unit.py::test_w5_c04_contract` | Given本租户 dev server When expose_port Then 用户能在 Web 中查看真实页面。 | `WEB-W5-C04` |
| `WEB-W5-C04-M` | Module | `tests/web/w5/test_w5_c04_module.py::test_w5_c04_integration` | Given port 关闭 When 重新访问 Then 显示 target unavailable。 | `WEB-W5-C04` |
| `WEB-W5-C04-N` | Negative | `tests/web/w5/test_w5_c04_unit.py::test_w5_c04_negative` | Given 攻击者构造 metadata/other tenant preview URL When 访问 Then 代理拒绝。 | `WEB-W5-C04` |
| `WEB-W5-C05-U` | Unit | `tests/web/w5/test_w5_c05_unit.py::test_w5_c05_contract` | Given 有授权样例 repo When 完成 Agent 修复 Then GitHub 上能找到同 branch 的 PR。 | `WEB-W5-C05` |
| `WEB-W5-C05-M` | Module | `tests/web/w5/test_w5_c05_module.py::test_w5_c05_integration` | Given 同请求 retry When PR 已创建 Then 识别已有 PR 不重复创建。 | `WEB-W5-C05` |
| `WEB-W5-C05-N` | Negative | `tests/web/w5/test_w5_c05_unit.py::test_w5_c05_negative` | Given token 缺少写权限 When PR 请求 Then 明确拒绝且不碰 main。 | `WEB-W5-C05` |
| `WEB-W5-C06-U` | Unit | `tests/web/w5/test_w5_c06_unit.py::test_w5_c06_contract` | Given 访客超出额度 When 创建 Run Then 429/结构化错误而无新 Worker 占用。 | `WEB-W5-C06` |
| `WEB-W5-C06-M` | Module | `tests/web/w5/test_w5_c06_module.py::test_w5_c06_integration` | Given A/B 同时运行 When 检查 workspace/事件 Then 完全隔离。 | `WEB-W5-C06` |
| `WEB-W5-C06-N` | Negative | `tests/web/w5/test_w5_c06_unit.py::test_w5_c06_negative` | Given Sandbox create 后异常 When GC 运行 Then 资源被清理而没有孤儿容器。 | `WEB-W5-C06` |
| `WEB-W6-C01-U` | Unit | `tests/web/w6/test_w6_c01_unit.py::test_w6_c01_contract` | Given cloud target When 选择工具 Then 不暴露 local desktop Input。 | `WEB-W6-C01` |
| `WEB-W6-C01-M` | Module | `tests/web/w6/test_w6_c01_module.py::test_w6_c01_integration` | Given remote target 能力不足 When 选择工具 Then 显示明确不可用原因。 | `WEB-W6-C01` |
| `WEB-W6-C01-N` | Negative | `tests/web/w6/test_w6_c01_unit.py::test_w6_c01_negative` | Given 新 MCP 仅标 readOnlyHint When 分类 Then 不能降低到 READ。 | `WEB-W6-C01` |
| `WEB-W6-C02-U` | Unit | `tests/web/w6/test_w6_c02_unit.py::test_w6_c02_contract` | Given 错误的代码 When Agent 修复并运行 pytest Then 文件真实改变且 exit_code=0。 | `WEB-W6-C02` |
| `WEB-W6-C02-M` | Module | `tests/web/w6/test_w6_c02_module.py::test_w6_c02_integration` | Given LSP 无对应语言服务 When 请求 refs Then 返回 unavailable 而非编造引用。 | `WEB-W6-C02` |
| `WEB-W6-C02-N` | Negative | `tests/web/w6/test_w6_c02_unit.py::test_w6_c02_negative` | Given 失败测试 When 生成报告 Then UI 不能标 green success。 | `WEB-W6-C02` |
| `WEB-W6-C03-U` | Unit | `tests/web/w6/test_w6_c03_unit.py::test_w6_c03_contract` | Given 工具打开网页 When browser navigate/click Then 在隔离浏览器 profile 获取真实 DOM 结果。 | `WEB-W6-C03` |
| `WEB-W6-C03-M` | Module | `tests/web/w6/test_w6_c03_module.py::test_w6_c03_integration` | Given用户点击接管 When 授权 Then Agent 可继续指定浏览器会话。 | `WEB-W6-C03` |
| `WEB-W6-C03-N` | Negative | `tests/web/w6/test_w6_c03_unit.py::test_w6_c03_negative` | Given 未授权 When 浏览器需要用户 cookie Then 不共享用户 Chrome 数据。 | `WEB-W6-C03` |
| `WEB-W6-C04-U` | Unit | `tests/web/w6/test_w6_c04_unit.py::test_w6_c04_contract` | Given 真实 Team Run When 子 Agent 开始/结束 Then 树有真实 parent_id/status。 | `WEB-W6-C04` |
| `WEB-W6-C04-M` | Module | `tests/web/w6/test_w6_c04_module.py::test_w6_c04_integration` | Given 用户运行时 steer When Worker 接受 Then 在原有 Run 内按明确顺序生效。 | `WEB-W6-C04` |
| `WEB-W6-C04-N` | Negative | `tests/web/w6/test_w6_c04_unit.py::test_w6_c04_negative` | Given child intermediate When render final Then 不进入主最终答复。 | `WEB-W6-C04` |
| `WEB-W6-C05-U` | Unit | `tests/web/w6/test_w6_c05_unit.py::test_w6_c05_contract` | Given 用户有多 Run When 打开 Usage Then Token/成本与记录一致。 | `WEB-W6-C05` |
| `WEB-W6-C05-M` | Module | `tests/web/w6/test_w6_c05_module.py::test_w6_c05_integration` | Given Schedule 触发 When 浏览器关闭 Then 创建持久 Run 并能收到状态通知。 | `WEB-W6-C05` |
| `WEB-W6-C05-N` | Negative | `tests/web/w6/test_w6_c05_unit.py::test_w6_c05_negative` | Given A 用户访问 B memory 或通知 When 请求 Then 不泄漏任何内容。 | `WEB-W6-C05` |
| `WEB-W6-C06-U` | Unit | `tests/web/w6/test_w6_c06_unit.py::test_w6_c06_contract` | Given新 Cloud 用户 When 依次登录、导入、创建 Run Then 完成真实测试及下载 Artifact。 | `WEB-W6-C06` |
| `WEB-W6-C06-M` | Module | `tests/web/w6/test_w6_c06_module.py::test_w6_c06_integration` | Given新 Local 用户 When rxycode web + Full Then 可本机执行无害真实操作。 | `WEB-W6-C06` |
| `WEB-W6-C06-N` | Negative | `tests/web/w6/test_w6_c06_unit.py::test_w6_c06_negative` | Given用户未配对设备 When 选 Remote Full Then 不会在云端擅自 Full 执行。 | `WEB-W6-C06` |
| `WEB-W7-C01-U` | Unit | `tests/web/w7/test_w7_c01_unit.py::test_w7_c01_contract` | Given 用户 B 猜到用户 A 的 ID When 访问 Session/SSE/Artifact/Device Then 无越权数据。 | `WEB-W7-C01` |
| `WEB-W7-C01-M` | Module | `tests/web/w7/test_w7_c01_module.py::test_w7_c01_integration` | Given 公开网页含诱导 prompt When Agent 读取 Then 不能越过敏感 Tool policy。 | `WEB-W7-C01` |
| `WEB-W7-C01-N` | Negative | `tests/web/w7/test_w7_c01_unit.py::test_w7_c01_negative` | Given Cloud 服务端伪造 Device Full When 没本机 grant Then 本机拒绝。 | `WEB-W7-C01` |
| `WEB-W7-C02-U` | Unit | `tests/web/w7/test_w7_c02_unit.py::test_w7_c02_contract` | Given Worker 在审批中宕机 When 重启 Then approval 仍待批准且无重复工具。 | `WEB-W7-C02` |
| `WEB-W7-C02-M` | Module | `tests/web/w7/test_w7_c02_module.py::test_w7_c02_integration` | Given 断网长活执行 When 恢复连接 Then seq 全部补齐、终态一致。 | `WEB-W7-C02` |
| `WEB-W7-C02-N` | Negative | `tests/web/w7/test_w7_c02_unit.py::test_w7_c02_negative` | Given tool side effect 已执行但 ACK 丢 When retry Then 不会再次执行。 | `WEB-W7-C02` |
| `WEB-W7-C03-U` | Unit | `tests/web/w7/test_w7_c03_unit.py::test_w7_c03_contract` | Given 固定任务集 When 连续两次 eval Then input manifest/hash/模型版本完整可复核。 | `WEB-W7-C03` |
| `WEB-W7-C03-M` | Module | `tests/web/w7/test_w7_c03_module.py::test_w7_c03_integration` | Given任务失败 When 报告指标 Then 失败计入分母、异常成本不丢。 | `WEB-W7-C03` |
| `WEB-W7-C03-N` | Negative | `tests/web/w7/test_w7_c03_unit.py::test_w7_c03_negative` | Given只跑一个 happy demo When 生成求职 report Then quality gate 不接受。 | `WEB-W7-C03` |
| `WEB-W7-C04-U` | Unit | `tests/web/w7/test_w7_c04_unit.py::test_w7_c04_contract` | Given 真实 Cloud Run When 完成 Then 可从 trace_id 关联 HTTP/Worker/Tool 耗时。 | `WEB-W7-C04` |
| `WEB-W7-C04-M` | Module | `tests/web/w7/test_w7_c04_module.py::test_w7_c04_integration` | Given token 计费 When 显示 Usage Then 与单 Run ledger 和 provider usage 对齐。 | `WEB-W7-C04` |
| `WEB-W7-C04-N` | Negative | `tests/web/w7/test_w7_c04_unit.py::test_w7_c04_negative` | Given 密钥出现在工具 stderr When trace 落库 Then 过滤/遮盖而非泄漏。 | `WEB-W7-C04` |
| `WEB-W7-C05-U` | Unit | `tests/web/w7/test_w7_c05_unit.py::test_w7_c05_contract` | Given 全新容器主机 When compose up/migrate Then Web/worker/DB healthcheck 成功。 | `WEB-W7-C05` |
| `WEB-W7-C05-M` | Module | `tests/web/w7/test_w7_c05_module.py::test_w7_c05_integration` | Given部署滚动更新 When 旧 Run 未完成 Then 不会丢记录、stale worker 不写状态。 | `WEB-W7-C05` |
| `WEB-W7-C05-N` | Negative | `tests/web/w7/test_w7_c05_unit.py::test_w7_c05_negative` | Given公共访客请求超预算或本机 Full When 访问 Then 服务端拒绝。 | `WEB-W7-C05` |
| `WEB-W7-C06-U` | Unit | `tests/web/w7/test_w7_c06_unit.py::test_w7_c06_contract` | Given README 声称支持 Full When 审计 Then 可定位真机 E2E 测试与 release。 | `WEB-W7-C06` |
| `WEB-W7-C06-M` | Module | `tests/web/w7/test_w7_c06_module.py::test_w7_c06_integration` | Given公开 Demo URL When 从未登录浏览器访问 Then 能完成受限真实云任务。 | `WEB-W7-C06` |
| `WEB-W7-C06-N` | Negative | `tests/web/w7/test_w7_c06_unit.py::test_w7_c06_negative` | Given一项指标缺真实 taskset/report When 写简历 Then 模板保留占位而非猜数。 | `WEB-W7-C06` |

## §3 测试证据、暂停与不能作假的门

- 每卡在新 `evidence/web/<WEB-Wn-Cnn>/` 保存原始 `red.txt`, `green.txt`, `integration.txt`, `e2e.txt`（若适用）、`git-diff.txt`, `self-audit.md`, `handoff.md`，带 Git SHA、OS、依赖版本、退出码。**本包没有编造这些日志**。
- 引入 DB/Redis/Runner/Sandbox 的卡要启动真实进程或隔离容器，不能只给 Python Fake Redis + Fake PG 就称“可靠”。
- `WAIVED_LIVE` 仅可用于没有第三方付费模型 Key 的真实网络评测，必须列出不受影响的 Unit/Module/Process 合同，并在最终求职发布前补齐必要指标。
- Phase/Wave 验收与 `10-TEST-EVAL-ACCEPTANCE.md` 共同为总门；真实崩溃、异步取消、权限撤销与乱序为硬性 test，不可只跑 happy-path。
