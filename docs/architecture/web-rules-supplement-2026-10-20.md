# RxyCode Web 规则补充说明（2026-10-20）

本文统一 W7 与 W8 之间的当前规则。它是对 `web-system-design.md` 与 `docs/plans/opus5-plan/rxycode -web/` 的补充；冲突处以本文为准，并在被替代的旧条目上标注。

## 1. 职责边界（固定）

| 层 | 负责 | 不负责 |
|---|---|---|
| Harness（共享 `AgentV2` / `Session` / `ToolOrchestrator`） | 任务执行、进展判断、预算与时限、续期、从暂停点恢复 | 排队、身份、租户归属、传输 |
| Web（server 与 drain 父进程） | 排队、服务端身份（tenant/actor）、事件传输、fenced 租约的获取/续约/失效判定、部署隔离（沙箱、挂载、网络出口） | 判断任务是否成功、重新实现 Agent 循环 |

Web 不另建执行器，不另建第二套 Agent 循环。

## 2. 云端 Full 的口径

- 云端 Full = **隔离环境内自动批准**：`full` / `full_auto` 在有效的租户自有 `cloud:` 目标上解析为 `permission_mode=full_auto`，只表示免逐项审批。
- 它不是宿主权限，也不是隔离等级。沙箱创建、挂载、私有文件系统、网络限制、宿主权限限制均不因 Full 改变。
- `isolation_required` 恒为 true；租户与目标归属校验照旧。
- 本机 CLI 的 Full（宿主权限，`core/sandbox/policy.py`）语义不变，本文不改动它。

## 3. 旧条目替代（W7）

以下 W7 旧条目被 W8-C01 替代，原文保留，仅追加替代标注：

1. `PHASE-W7-SECURITY-EVAL-DELIVERY.md` 的 drain 放置闸描述：「`local:*` 与 `full`/`full_auto` profile 在 cloud-only 下拒绝」。替代后：`local:*` 仍拒绝；`full`/`full_auto` 在有效云目标上允许，解析为沙箱内 `full_auto`。
2. 同文件放置闸矩阵单测描述中的「拒 `full*`」。替代后：该断言改为「接受 `cloud:` 目标上的 `full*` 并解析为 `full_auto`」。
3. `web-system-design.md` 放置闸图示中的「拒 local/sandbox/full*」。替代后：拒 local 与 sandbox；`full*` 解析为沙箱内 `full_auto`。

**不被替代**（仍有效）：Remote Full（设备本机授权，W4-C05、W6-C06-N、W7-C01-N、RPC-04）、CW12「云端直接设置 Full 即控制本机」。这些描述的是设备权限，与云端沙箱内的自动批准不是同一件事。

## 4. W8 登记

| 编号 | 名称 | 状态 |
|---|---|---|
| WEB-W8-C01 | 云端执行语义与沙箱安全：Full=沙箱内自动批准，控制面凭据留在父进程，网络在执行环境层约束，配置清洗 | 进行中（本地提交至 `7a03dd82`） |
| W8-S1 | 统一规则（本文） | 完成 |
| W8-S2 | 初始化接回共享入口：`appserver/agent_worker.py::assemble_surface_agent`（子代理管理器 → broker → `bootstrap_agent` → `configure_agent_workspace`），Web 子进程改用它 | 代码与单测完成；子进程实机验证待 Docker/bwrap 环境 |
| W8-S3 | 共享 Harness 审批暂停点（检查点、续接、父进程持久化） | 已完成（`48a6005a`、本轮；见 NOTES Round 26） |
| W8-S4 | 审批恢复回到原工具循环直至 Final Answer | 已完成（`resume_harness_turn`；复合主链 chain 1 通过） |
| W8-S5 | 移除 drain 重复业务判断（时限交 Harness 预算；配置只构造所需字段；工具结果按实际状态判定） | 已完成：预算与 900 秒外层超时已移除，配置改为构造；循环判定改为 `call_outcome` 结构化状态（status/exit_code/approval），文本前缀仅存于无记录回退 |
| W8-S6 | 三条复合验收主链 | 已完成：复合主链 + 部署态 `test_w7_c05_integration` 在真实 compose 栈上通过（relay 独立线程修复后收敛） |

登记只说明这些卡存在，**不证明其功能已获授权，也不证明已通过验收**。验收以 `evidence/web/` 中的实测结果为准。

## 5. 三条复合验收主链

1. 网页提交任务 → 修改文件 → 审批 → 继续测试 → Final Answer；重复批准不重复执行。
2. 审批期间重启 → 恢复原任务；结果未知的写操作停止并明确提示用户。
3. 长任务持续有进展时正常运行；用户取消或租约失效时及时回收；两个租户互不影响。

## 6. 初始化来源

- CLI 与 Web 共用的 Agent 构造与记忆水合顺序，以 `appserver/bootstrap.py::bootstrap_agent` 为准。
- 子代理管理器、审批 broker、提问 broker 的装配顺序，以 `appserver/agent_worker.py` 为准。
- Web 只替换传输端：stdio JSON-RPC 换成父子进程的 ctl socket；组装逻辑不分叉。

## 7. 时限与结果判断

- Web 不设置整任务硬超时。任务时限交给 Harness 预算；租约失效、用户取消仍由外层强制停止。
- 工具结果以实际执行状态、退出码和错误信息为准；stdout 文本不作为整项任务成败的判据。
- 配置复制只构造本轮需要的字段；平台凭据留在父进程，不进入沙箱。

## 8. 当前已知缺口（截至本文）

- 已收口（S3/S4）：审批与提问挂起时携带共享 Harness 检查点，持久化在父进程（`approvals.checkpoint`，迁移 005）；续接回到原工具循环，直至 Final Answer。
- 已收口（B）：隔离 worker 的提问经控制通道写入 `question.requested` 与持久化行，`GET/POST /questions` 接入 `ApprovalCard` 同一接口；回答一次性消费。多问题批次在此通道上明确返回「每次只问一个问题」。
- 已收口（C）：整回合预算在共享 `AgentV2.run/resume` 入口执行，等待不计时，续期复用 `timeout_decision`；drain 的 900 秒外层超时与 `RXYCODE_WORKER_RUN_TIMEOUT` 已移除。
- 未收口：部署态 compose 的 W7 用例（`test_w7_c05_integration`）在本分支停在 `leased`，HEAD 在同一断言前进入终态；原因未定位，需要 `docker compose logs worker`。
- 未收口：工具循环内的结构化执行状态（退出码、错误类别）未替换 `_tool_output_is_error` 的文本判定；终态判定已不依赖输出文字。
- r25 十三条已逐项处置为「已替代」，证据见 NOTES Round 25（配置由构造产生，清洗树在生产路径上已无调用方）。
