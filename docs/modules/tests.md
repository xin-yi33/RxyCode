# tests/ - 分层测试体系

RxyCode 的测试分为确定性常规门禁、平台专项测试和显式 opt-in 的 live 测试。普通 CI 不访问收费模型或公网。

测试规模随 Phase A/B/C 持续增长。已记录的确定性全量基线：`10412 passed / 3 skipped`
（v1.2.8 release 记录，`python -m pytest tests -q`）；Phase 4 子代理桥接合入后的
核心回归为 `530 passed / 1 skipped`（`tests/test_subagents tests/test_appserver
tests/test_core/test_agent_tool_contracts.py tests/test_safety_gate.py
tests/stress_test/test_phase4_harness.py`，跳过项为需要 `RXYCODE_APPSERVER_LIVE=1`
的真实 appserver live 测试）。前端基线：`28 files / 153 tests`；thinking/SSE 聚焦契约
`12 tests`；Windows ConPTY `19 + 2` 个场景通过。

## 测试层

| 层 | 位置 | 边界与当前代表场景 |
|---|---|---|
| `unit` | `tests/unit/` | 纯逻辑和状态契约；当前覆盖工具 evidence、打包元数据和跨平台安装器契约 |
| `integration` | `tests/integration/` | 跨生产模块但替换不稳定依赖；当前覆盖 scripted LLM 主链和会话 fixture round-trip |
| `contract` | `tests/contract/` | HTTP、FastAPI、SSE、审批和协议兼容性；当前覆盖 Unicode token、terminal event 关联和错误顺序 |
| `system` | `tests/system/` | 真实本地进程及副作用；自动增加 `serial` marker，当前覆盖 Uvicorn 生命周期及 wheel 构建、隔离安装和 fresh-home CLI |
| `live` | `tests/live/` | 真实 provider/公网，单独预算和超时；缺少显式开关或 API key 时自动跳过 |
| `pty` | `frontend/e2e/` | 编译后 Ink TUI 的 PTY/Windows ConPTY 生命周期、输入、终端恢复，以及长 assistant/tool 输出不进入 scrollback 的原始输出门禁 |

`tests/conftest.py` 根据 `tests/<layer>/` 目录自动增加同名 marker，并把 system 层标为 `serial`。仍位于 `tests/test_*.py`、`tests/test_core/` 等旧目录的测试属于 legacy regression 集；Linux CI 用排除所有分层 marker 的表达式补跑，避免迁移期间漏测或重复执行。并行 lane 使用两个 xdist worker 和 `loadscope` 分发；串行 lane 从整个测试树选择 `serial`，因此不限于当前的 system 层。

## 进程全局状态门（RL5 / RL11）

短名 `core` / `protocol` / `utils` 与 `RxyCode.RxyCode1_1_0.*` 必须是同一模块对象。包 `__init__.py` 在版本包导入后调用 `unify_bare_package_aliases()`，并在 `core` 已经是版本包时把 `core.foo` 指到同一对象。不要用「比 class 名字符串」掩盖双重 import。

每个测试结束后，`tests/conftest.py` 的 autouse fixture 再检查两件事：

1. 进程 CWD 与测试开始时一致；
2. 新增的裸顶层包键（清单与 `RxyCode.RxyCode1_1_0._BARE_PACKAGES` 同源，import 不重抄；`appserver` 除外，因为它在 `python -m appserver` 下故意可以是另一份对象）是否与 `RxyCode.RxyCode1_1_0.<同名>` **不是同一个模块对象**（或规范键根本不存在）。键存在本身无害：`unify` / finder 会让两种拼写指向同一对象。有害的是两个键指向两个对象。

失败信息带测试 nodeid 以及旧值/新值（或分裂的模块名）。不要写 `Path("config/...")` 这类依赖 CWD 的相对路径（RLI-3）；资源路径用 `REPO_ROOT`。

需要在测试体内改 CWD、且自己负责还原的，可以标 `@pytest.mark.allows_cwd_change`。只豁免 CWD 检查，不豁免身份分裂。这个 marker 只用于进程入口或明确要验证 chdir 的用例，不能用来掩盖库函数里的 `os.chdir`。每个测试还会 reset `utils.tui` 单例并恢复 cwd。

## Scripted LLM

项目中的 ScriptedLLM 实现名为 `ScriptedChatModel`，位于 `tests/support/scripted_llm.py`。它基于 LangChain `GenericFakeChatModel`，按固定顺序返回 `AIMessage`，同时保留生产代码使用的 `bind_tools()` 接口。

`tests/integration/test_agent_main_chain.py` 使用它驱动真实的 `AgentV2 -> LangGraph -> Executor -> ToolOrchestrator -> Validator` 路径。只有模型响应被脚本化；工具、安全门、审计、产物写入和验证仍走生产实现。响应耗尽、调用顺序变化或最终产物不匹配都会使测试失败。

## Fixtures

| 目录 | 内容 |
|---|---|
| `tests/fixtures/responses/` | Scripted LLM 的结构化 `AIMessage` 和 tool call |
| `tests/fixtures/sessions/` | 会话恢复、存储和迁移样本 |
| `tests/fixtures/artifacts/` | 工具执行后的确定性期望文件 |

`load_scripted_messages` fixture 会读取 response JSON，并使用 `string.Template.safe_substitute` 替换调用方显式传入的变量。完整格式和更新规则见 `tests/fixtures/README.md`。

Fixtures 必须是项目自己生成的最小样本，不能包含 API key、Authorization header、用户目录、真实会话或上游仓库的 provider cassette。

## 本地运行

首次运行先安装完整仓库和测试依赖：

```powershell
python -m pip install -e .
python -m pip install -r requirements.txt -r requirements-dev.txt
```

从 `RxyCode1_1_0` 目录运行各层：

```powershell
python scripts/scan_secrets.py .
python -m pytest tests/unit -m "unit and not serial" -n 2 --dist loadscope
python -m pytest tests/integration -m "integration and not serial" -n 2 --dist loadscope
python -m pytest tests/contract -m "contract and not serial" -n 2 --dist loadscope
python -m pytest tests/system -m "system and serial" -n 0
python -m pytest tests -m "not live and not pty and not serial" -n 2 --dist loadscope --timeout=180
python -m pytest tests -m "serial and not live and not pty" -n 0 --timeout=180
```

分发入口必须再通过真实产物验证，不能用源码 import 或静态 README
断言代替：

```powershell
python -m pytest tests/unit/test_packaging_contract.py tests/unit/test_installers.py -q
python -m pytest tests/system/test_installed_package.py -m "system and serial" -n 0 -q
python -m build
python -m twine check dist/*
```

`test_installed_package.py` 在临时目录构建 wheel 和 sdist，创建带空格的独立 venv，
使用 `pip --no-deps` 安装后清空 `PYTHONPATH` 并离开源码 CWD。它验证
`rxycode --version`、`--help`、`python -m RxyCode` 和无模型首启，还会
检查 wheel / sdist 没有夹带 tests、evals、scripts、`.coveragerc`、`AGENTS.md`、
data、runtime logs、credentials、artifacts 或 `node_modules`。

CI coverage 不用单次 pytest 混跑共享状态。`.github/workflows/ci.yml` 依次运行 unit、integration、contract、serial、legacy regression，并为每层设置独立 `COVERAGE_FILE`，最后执行 `coverage combine`。本地生成合并报告时沿用该五 lane 命令，再运行：

```powershell
$env:COVERAGE_FILE = "artifacts/coverage-data/.coverage"
python -m coverage combine --keep artifacts/coverage-data
python -m coverage xml -o artifacts/coverage.xml
python -m coverage html -d artifacts/htmlcov
```

前端确定性测试：

```powershell
Set-Location frontend
npm ci
npm run build
npm test
```

Windows ConPTY E2E 必须在真实 Windows runner/终端执行：

```powershell
Set-Location frontend
npm run build
npm run e2e
```

Desktop GUI 真实业务与确定性套件在 `frontend/desktop-app/`，走真实 Electron + CDP，不进入普通 CI。验收记录见 `docs/RXYCODE-GUI-REAL-E2E-REPORT-2026-08-13.md`。

```powershell
Set-Location frontend/desktop-app
node --test scripts/real-business-suite.test.mts scripts/cdp-harness.test.mts
node scripts/real-business-suite.mts --batch=A --artifacts=<dir>
node scripts/real-business-suite.mts --batch=B --artifacts=<dir>
node scripts/desktop-cd-suite.mts --mode=deterministic --rounds=3 --artifacts=<dir>
node scripts/plan-goal-screenshots.mts
```

## Live 测试

Live 测试默认跳过。只有在隔离预算和测试专用凭据准备完成后才应启用：

```powershell
# 前置条件：运行环境已通过安全机制注入 RXYCODE_RUN_LIVE_TESTS、
# RXYCODE_LIVE_API_KEY，以及用例需要的可选模型变量。
python -m pytest tests/live -m live -v
```

不要把 key 写入 fixture、YAML 的 `api_key` 字段、文档、命令历史 artifact、仓库或
日志。Live 临时配置只保存 `api_key_env: RXYCODE_LIVE_API_KEY`，运行时由
`resolve_model_config()` 解析；不得先展开环境变量再序列化。本地未显式启用 live 或
未配置 key 时，用例自动报告 skip。

Provider 适配证据必须分开记录：

- 官方资料：只证明文档中公开的模型 ID、端点和政策；
- mock/wire：证明 RxyCode/SDK 实际构造的 URL、body 和终态处理；
- 历史 live：保留日期与外部错误，不冒充本轮结果；
- 本轮 live：只有本轮实际运行且返回成功才标记通过；
- 外部权限阻塞：DataPolicy/Region 等错误既不是通过，也不能直接归因成代码缺陷。

OpenCode Go 的 HY3/Muse live 测试不得把模型能力、Provider 家族识别和 `/models` 当前
公开可用性混为一谈。HY3 只验证正式版 Chat 路径；范围外型号不进入本阶段承诺。

通用接口路由的本地门禁位于
`tests/test_providers/test_transport_routing.py`：覆盖明确 endpoint-not-found 的 Responses 404→Chat、403/DataPolicy
不回退、部分输出后不回退、双接口均不支持的组合错误，以及预设的 Responses-first / Chat
审计矩阵。`tests/test_api_security_onboarding.py` 的 custom probe 用例验证配置前探测遵守
同一分类器且不泄露凭据。`tests/test_providers/test_hy3_provider.py` 只覆盖正式版 `hy3`；
preview 不进入 Provider 或 catalog 承诺。

负责人 2026-08-25 新增 P0 的确定性门禁为：

- `tests/test_providers/test_transport_routing.py`：三种规范协议、旧值迁移、候选去重、
  非法/空候选保护和 OpenAI 窄回退；
- `tests/test_providers/test_model_endpoints.py`：Chat/Responses/Messages 的 API root
  规范化、完整资源去重、冲突、安全 URL 和持久化/探测共用路径；
- `tests/test_providers/test_anthropic_transport.py`：通过 `httpx.MockTransport` 驱动真实
  `ChatAnthropic`/Anthropic SDK，核对 `/v1/messages`、鉴权与版本头、system、图像、
  tool schema、tool use/result、文本/工具流、usage、stop reason、错误与缺失终态。

可只运行这组三协议专项：

```powershell
python -m pytest -q -p no:cacheprovider tests/test_providers/test_transport_routing.py tests/test_providers/test_model_endpoints.py tests/test_providers/test_anthropic_transport.py
```

这些用例使用运行时生成的合成凭据，只断言 header 是否存在，不打印 header 值。它们属于
mock/wire 证据，不能替代 Anthropic、OpenCode Go、HY3 或 Muse 的本轮 live。

Muse Responses 归一层的本地压力测试不访问公网、不读取 key，可直接运行：

```powershell
python scripts/stress_muse_provider.py --requests 200 --chunks 32 --concurrency 1 2 4 8 16
```

输出包含各并发档的成功数、吞吐、P50/P95/P99、本地内存峰值和 pending task
leak。它只衡量 RxyCode 内部适配器，不能写成真实模型或 OpenCode Go 容量结果。

## 编写规则

- 优先使用事件、barrier、端口探测和明确的进程退出通知，不用固定长时间 `sleep` 证明并发或启动完成。
- pytest session 把 HOME 与 data/config 放入独立根目录；`isolated_runtime` 进一步隔离 CWD 和 cache。autouse fixture 在每个测试前后清理并恢复 approval broker、audit logger、token stats、run monitor 和 tracer。
- 网络、模型、时间、ID、token/cost 等不确定数据必须脚本化或规范化。
- 测试应断言外部行为和协议顺序；不得通过弱化断言、无理由 `skip/xfail` 或吞掉异常制造绿色结果。
- 子进程和 PTY 必须在 `finally` 中终止并等待退出；失败 artifact 不得包含 secret。
- 新分层测试放入对应目录；只有仍未迁移的旧回归测试保留在 legacy 位置。

## 覆盖率策略

v1.2.8 release 记录核心包范围分支覆盖率为 `77.1%`（workflow 核心门槛 `67%`）、
全项目分支覆盖率为 `71.7%`（门槛 `60%`）。覆盖率数字随 Phase 新增代码持续演进，
具体以 CI 实际采集为准。双门槛让 `main.py`、`api_server.py`、evals、MCP、RAG、
scheduler 和 LSP 的低覆盖代码保持可见且不可回退。CI 仍按 unit、integration、
contract、serial、legacy regression 五 lane 采集。提升流程是：连续多次 CI 记录
稳定结果后，通过 workflow 评审小步提高；不得下调。覆盖率数字不能替代主链、权限、
恢复和终端协议的行为断言。

当前目录没有 `.git`，没有 GitHub-hosted workflow 运行证据；当前机器也没有 Docker 二进制。上述数字来自本地等价命令，live provider 与镜像构建不能写成已通过。
