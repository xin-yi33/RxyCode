# 测试计划与发布总门（TEST-first）

> 按既有 `PHASE-UPDATE-02` 的测试规范：每卡至少 Unit + Module，复杂卡要 Process + E2E；先 RED 后 GREEN，不能用“写了 pytest”冒充真实验收。

## §1 七层可验证测试

1. Unit：协议 DTO、ToolSpec、Reducer、Run transition 等纯逻辑。
2. Contract：Pydantic/JSON Schema/TS、HTTP 错误码、旧 JSON-RPC golden 消息。
3. Module：Server+PG、Worker+Queue、ToolOrchestrator+RunnerRPC、权限 ACL。
4. Process：真实 Worker/Runner 子进程、终止、重启、租约、ConPTY 等。
5. E2E：真实浏览器→Web→API→Worker→Runner→Artifact/PR，截图辅助。
6. Security/Chaos：IDOR、SSRF、cloud host escape、remote Full grant forgery、cancel/replay、secret 泄漏。
7. Agent Eval：30–50 个固定任务集、真实模型调用和 Tool loop、相同 baseline/预算、Token/成功率/耗时/成本。

**测试权威**：[`tests/TEST-MATRIX.md`](tests/TEST-MATRIX.md) 和 [`tests/E2E-FIXTURES.md`](tests/E2E-FIXTURES.md)。卡内每个 GWT 都必须有文件+函数名，先 RED 并保存原始输出。外部模型 key 不在时可标独立 live 测试 `WAIVED_LIVE`，但核心 contract、mockless local process/DB 与强制安全负测不能 waive。

## §2 PowerShell 必要回归（实际目录不在则 BLOCKED）

```powershell
Set-Location 'D:\agent-demo\RxyCode\RxyCode1_1_0'
python -m pytest tests/test_protocol_schema.py -q
python -m pytest tests/test_appserver -q
python -m pytest tests/test_tools -q
python -m pytest tests/test_cache/test_s1_s2_split.py tests/test_cache/test_stable_prefix.py -q
python -m pytest tests/system/test_installed_package.py -q
# WEB-W1 开始创建新路径后：
# python -m pytest tests/web -q
# Set-Location apps/web; npm run typecheck; npm run test; npm run build; npm run test:e2e
```

任何测试失败要证明是否在干净基线发生，不能为绿随意修改已有断言；全量测试未跑不写“all passed”。各卡 evidence 路径 `evidence/web/WEB-W*-C*/` 必须有 commit、测试输出、skip 解释和审计报告。

## §3 Agent Eval 数据与统计

任务集含编码/debug、unit tests、浏览器、恢复、Remote Full（隔离测试机）、multi-agent，每个任务固定 repo commit/Oracle、模型 ID/provider、token 预算、执行环境、超时、run_id/trace_id。指标 Success Rate、TTFE、P50/P95 Run Duration、Tool Calls、Tokens/Cache、Cost/Success、恢复率及失败分布。不公布未测数字；不剔除失败任务制造高成功率。

## §4 Release 不可妥协的门

- 48 卡实际 evidence 齐全且全部必要测试真实绿，跨租户安全 P0=0；旧 CLI/Desktop 兼容测试绿。
- Cloud 公网 Demo 在沙箱隔离中完成真实 Coding 和 PR；Local Full/Remote Full 在真机证明 Native 直通、授权与急停。
- SSE replay 与乱序测试、Worker kill/Journal unknown 负测、跨天审批完整演示均有 trace。
- README、安装与一键部署、限制说明、Live Demo URL、两分钟视频、实测 Eval 表均存在。只有具备上述证据，才允许写“已交付求职代表项目”。
