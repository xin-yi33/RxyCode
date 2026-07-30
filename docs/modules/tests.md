# tests/ - 分层测试体系

RxyCode 的测试分为确定性常规门禁、平台专项测试和显式 opt-in 的 live 测试。普通 CI 不访问收费模型或公网。

2026-07-25 本地最终基线：`2320 collected`，其中 `2319` 个确定性 Python 测试通过（`2311` 个常规/并行用例和 `8` 个串行用例），`1` 个 live 测试因没有测试专用 provider 凭据而未运行。2026-07-26 本次 TUI 回归验证：前端为 `28 files / 153 tests`，thinking/SSE 聚焦契约为 `12 tests`，Windows ConPTY 为 `19 + 2` 个场景通过。

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
检查 wheel 没有夹带 tests、data、runtime logs、credentials、artifacts 或
`node_modules`。

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

## Live 测试

Live 测试默认跳过。只有在隔离预算和测试专用凭据准备完成后才应启用：

```powershell
$env:RXYCODE_RUN_LIVE_TESTS = "1"
$env:RXYCODE_LIVE_API_KEY = "<test-only-key>"
$env:RXYCODE_LIVE_MODEL = "<model-id>"
python -m pytest tests/live -m live -v
```

不要把 key 写入 fixture、文档、命令历史 artifact 或仓库。GitHub Actions 中使用 `RXYCODE_LIVE_API_KEY` secret；CI 会在收集 live 测试前校验它并在缺失时明确失败。本地未显式启用 live 或未配置 key 时，用例仍自动报告 skip。

## 编写规则

- 优先使用事件、barrier、端口探测和明确的进程退出通知，不用固定长时间 `sleep` 证明并发或启动完成。
- pytest session 把 HOME 与 data/config 放入独立根目录；`isolated_runtime` 进一步隔离 CWD 和 cache。autouse fixture 在每个测试前后清理并恢复 approval broker、audit logger、token stats、run monitor 和 tracer。
- 网络、模型、时间、ID、token/cost 等不确定数据必须脚本化或规范化。
- 测试应断言外部行为和协议顺序；不得通过弱化断言、无理由 `skip/xfail` 或吞掉异常制造绿色结果。
- 子进程和 PTY 必须在 `finally` 中终止并等待退出；失败 artifact 不得包含 secret。
- 新分层测试放入对应目录；只有仍未迁移的旧回归测试保留在 legacy 位置。

## 覆盖率策略

2026-07-25 在新增分发测试之前生成的确定性并行/串行覆盖率快照中，核心包范围分支覆盖率为 `77.1%`，workflow 核心门槛为 `67%`；全项目分支覆盖率为 `71.7%`，门槛为 `60%`。新增分发测试不降低门槛，但不能把旧快照冒充为 2319 个确定性测试重新合并后的结果。双门槛让 `main.py`、`api_server.py`、evals、MCP、RAG、scheduler 和 LSP 的低覆盖代码保持可见且不可回退。CI 仍按 unit、integration、contract、serial、legacy regression 五 lane 采集。提升流程是：连续多次 CI 记录稳定结果后，通过 workflow 评审小步提高；不得下调。覆盖率数字不能替代主链、权限、恢复和终端协议的行为断言。

当前目录没有 `.git`，没有 GitHub-hosted workflow 运行证据；当前机器也没有 Docker 二进制。上述数字来自本地等价命令，live provider 与镜像构建不能写成已通过。
