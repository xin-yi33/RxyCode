# Research first / 上游复用与工程选型 Verdict（PC0）

> 上方路线表是开工前的候选。下方 `WEB-W0-C02 frozen rows` 是 2026-10-16 用 GitHub API 钉住的 commit 和 SPDX。没有在本机跑过 gVisor 或 ConPTY，那些 spike 只是以后可执行的检查，不是已通过的运行。

| 研究主题 | 既有内部输入 | 优先可研究项目/文档 | 候选裁定 | 开工时还需验证 |
|---|---|---|---|---|
| 唯一 Agent Loop + thin clients | ARCH-001, `core/session.py`, appserver | Codex App Server、OpenCode server | 保留 RXYCode AgentV2，借鉴协议边界，不移植整个框架 | license/具体 commit/接口比较 |
| Pydantic→JSON Schema→TS | `protocol/schema.py`, protocol-client | Pydantic v2、TypeScript generator | EXTEND | 旧 schema digest + 生成命令 |
| LangGraph Durable execution | `core/graph.py`, `tool_journal.py` | LangGraph checkpointer/interrupt 官方文档 | ADOPT checkpointer，但不取代 Journal | import 版本、恢复时节点重执行实际验证 |
| SSE/WSS | `appserver/task_store.py` ordered event | FastAPI/sse-starlette/WebSockets | SSE for events、WS for runner/PTY | replay-race test 与 proxy buffering |
| 数据库/队列 | 本地 task_store、旧 scheduler | PostgreSQL / Redis Streams / arq | ADOPT for cloud，local 可轻量 DB adapter | 多 worker fencing/Outbox 实测 |
| Native Full / Windows | `core/sandbox/`, `core/cu/` | Win32 SendInput、ConPTY、mss、Playwright | Native 本机直通，未授权不执行 Remote Full | Windows 锁屏、UAC、多屏、权限真实限制 |
| Sandbox isolation | `docs/modules/sandbox.md` | gVisor, Firecracker, E2B | gVisor 优先验证，保持 Provider 可替换 | 相容性/开销/宿主逃逸/许可证 |
| Browser/Preview | UPDATE-01 U24/U46 | Playwright MCP/Chrome CDP | 先复用现有实现，区分 Agent Browser 与 Preview | Cookie 隔离/端口校验 |
| Git workflow | 原 Git Tool | GitHub App/OAuth、GitHub REST API | Branch+PR 闭环 | scope、重复 PR、安全保护 |
| React Workbench | Electron Desktop React | React/Vite/Monaco/xterm/shadcn | 复用纯 UI，重构浏览器 transport | 组件许可证/Node preload 污染 |
| Observability/Eval | `core/tracing.py`, `evals/` | OpenTelemetry / Langfuse | EXTEND 实测 | 是否泄露 secret、任务集许可证 |

**强制 Verdict 结构（每个候选）**：研究问题→上游 URL/固定 SHA/许可证→已有 RXYCode 路径与测试→`ADOPT / ADAPT / REJECT / DEFER`→为什么→反例/负面数据→owner 卡→安全/性能测试。如果无法确认则 `RESEARCH_REQUIRED`，不可因为 README 上看起来有功能就标已复用。

**旧资料优先**：`../rxycode/architecture/DEV-ORDER.md`（当前旧主链）、`MODULE-BOUNDARIES.md`、`research/2026-09-01-top-coding-agents-core-architecture.md`、`PHASE-P-PRODUCT-INTENT.md`、`PHASE-UPDATE-01/02`、`PHASE-G-CONFLICT-AUDIT.md`、`../COMPOSER-2.5-PLAYBOOK.md`。旧测试确证的功能不因新增 Web 卡而重新施工。

旧调研文件名含 `top-coding-agents`，正文没有这个固定字符串。本卡不改那份只读文件。正文缺失记为锚点缺口，不把它写成已经核对过的 SPDX 来源。

## WEB-W0-C02 frozen rows

许可证和 commit 来自 2026-10-16 的 `gh api`：`repos/<owner>/<repo>` 的 `license.spdx_id`，以及默认分支的 `commits/<branch>.sha`。gVisor 与 Playwright 的版本号用同一天的 `releases/latest`。

| id | requirement | source_url | commit | license | decision | rejected | adr | version | why | threshold |
|---|---|---|---|---|---|---|---|---|---|---|
| api-boundary | 一个 Agent Loop，Web 只做薄客户端 | https://github.com/openai/codex | 3df96b085c666b33d3775aa4e77219ec1ed828a0 | Apache-2.0 | ADAPT | 复制未公开的 Claude Code 实现 | adr/ADR-WEB-001-ONE-CORE-MANY-SURFACES.md | 3df96b085c666b33d3775aa4e77219ec1ed828a0 | Codex 把 app-server 与 core 分成不同 crate，许可证是 Apache-2.0。Claude Code 没有可钉住的公开实现，所以不复制。 | 只约束 Web、CLI、Desktop 的入口。工具执行不改走第二套循环。 |
| linux-sandbox | 云端执行与宿主进程分开，Provider 可替换 | https://github.com/google/gvisor | d4d3e28027b4b6c94848a95bb7ada24bf82be84c | Apache-2.0 | ADAPT | 把 Firecracker 写成唯一沙箱 | adr/ADR-WEB-003-RUNNER-BOUNDARY.md | release-20261005.0 | gVisor 是进程级沙箱且为 Apache-2.0。Firecracker 是另一套虚拟机启动和设备模型，成本不同，所以保留为可替换 Provider，不写成唯一后端。 | 仅 Linux 云端 worker。Local Full 和 Windows 不用 runsc。 |
| storage-durability | Checkpoint 不能代替 Tool Journal | https://github.com/langchain-ai/langgraph | 5eb60aef6f3837a1fb632a8abc6cf8e8da81785b | MIT | ADAPT | 只用 LangGraph Saver 判断外部副作用 | adr/ADR-WEB-005-DURABILITY-AND-SIDE-EFFECTS.md | 5eb60aef6f3837a1fb632a8abc6cf8e8da81785b | LangGraph checkpointer 是 MIT，适合保存图状态。它不知道宿主上的 Git push 或写文件是否已经发生，所以 Journal 仍是副作用记录。 | 只覆盖图状态。副作用仍走 Tool Journal。 |
| windows-pty | Windows 终端用系统 ConPTY，不内置来源不明的 PTY | https://learn.microsoft.com/windows/console/creating-a-pseudoconsole-session | none | UNKNOWN | RESEARCH_REQUIRED | 拷贝来源不明的 ConPTY 示例树 | adr/ADR-WEB-003-RUNNER-BOUNDARY.md | none | 系统 ConPTY 文档可以按 API 调用。第三方示例没有 SPDX 和 commit，不能拷进仓库。 | 仅 Windows runner，且只使用文档中的 API。 |

## Spike plans

这些命令本卡没有执行。

Linux sandbox：在 Linux CI 里把 gVisor checkout 固定到 `d4d3e28027b4b6c94848a95bb7ada24bf82be84c`，运行 `runsc --version`，期望含 `release-20261005.0`。再跑一个夹具进程，确认它读不到宿主 home。失败就保持 Provider 可替换，不把 gVisor 写成唯一后端。

Windows PTY：用系统文档里的 ConPTY 打开、改尺寸、读回一段已知提示。`reuse_decision("UNKNOWN")` 对第三方 PTY 样本返回 `RESEARCH_REQUIRED`，因此不把那些样本拷进仓库。
