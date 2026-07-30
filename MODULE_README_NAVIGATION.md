# RxyCode 模块 README 导航

这个文件用于快速定位每个功能模块 README：先看“位置”，再进入对应目录阅读详细说明。

| 模块 | README 位置 | 主要功能 |
|---|---|---|
| 缓存模块 | `cache/README.md` | 减少重复 LLM 请求：精确缓存处理完全相同的请求，语义缓存处理相似问法，PromptCacheManager 保持提示词前缀稳定以提高供应商侧 KV cache 命中率。 |
| 配置模块 | `config/README.md` | 读取、保存、迁移 RxyCode 的用户配置、模型配置、MCP 配置、调度器配置和输出目录。 |
| 核心 Agent 模块 | `core/README.md` | 定义 AgentV2、LangGraph 主流程、状态结构、系统提示词和 v2 配置，是项目的控制中枢。 |
| 运行时治理 | `docs/modules/governance.md` | Provider/model 进程内限流、用量预留结算、角色模型路由与敏感动作决策契约。 |
| 执行模块 | `execution/README.md` | 负责把任务节点调度出来、选择工具并完成单个任务执行。 |
| 前端模块 | `frontend/README.md` | React/Vite 前端界面目录，包含聊天面板、输入框、状态栏、命令面板、hooks 和构建产物；该目录没有 Python 文件。 |
| 历史追踪模块 | `history/README.md` | 记录文件修改前后的内容、时间、原因和 diff，支持查看历史与撤销。 |
| LSP 模块 | `lsp/README.md` | 通过 JSON-RPC 与语言服务器通信，获取 diagnostics 等代码诊断信息。 |
| MCP 客户端模块 | `mcp/README.md` | 连接 MCP server，列出外部工具并包装为 LangChain 可调用工具。 |
| 记忆模块 | `memory/README.md` | 管理短期会话、长期项目记忆、用户手动记忆、自动抽取、压缩和 BM25 搜索。 |
| 规划模块 | `planning/README.md` | 把用户输入变成结构化目标，再拆成可执行任务树。 |
| 错误恢复模块 | `recovery/README.md` | 处理执行异常、重试次数、失败状态和错误上下文。 |
| 定时任务模块 | `scheduler/README.md` | 解析 cron 表达式并在后台管理计划任务。 |
| 结果综合模块 | `synthesis/README.md` | 把多个叶子任务结果整理成最终回答。 |
| 工具模块 | `tools/README.md` | Agent 可调用的环境能力集合：文件、Shell、Git、搜索、下载、视觉、MCP、任务队列、技能等。 |
| 通用工具模块 | `utils/README.md` | 提供 CLI/TUI、国际化、输入框、队列、跨平台 Shell、流式输出等基础能力。 |
| 验证与重规划模块 | `validation/README.md` | 验证任务结果是否满足要求，并在失败时生成补救任务。 |
| 测试模块 | `tests/README.md` | 保存规划、执行、验证等核心链路的单元测试。 |
| 执行测试模块 | `tests/test_execution/README.md` | 测试 TaskScheduler 的 DAG 调度、依赖判断和取消级联。 |
| 规划测试模块 | `tests/test_planning/README.md` | 测试 HierarchicalDecomposer 的任务拆解行为。 |
| 综合测试模块 | `tests/test_synthesis/README.md` | synthesis 测试预留包，目前只有初始化文件。 |
| 验证测试模块 | `tests/test_validation/README.md` | 测试 RePlanner 对失败任务的二次拆解。 |

## 推荐阅读顺序

1. `core/README.md`：先理解 Agent 主流程和 LangGraph。
2. `tools/README.md`：再看 Agent 能调用哪些工具。
3. `memory/README.md`、`cache/README.md`：理解上下文、记忆和缓存如何降低成本。
4. `planning/README.md`、`execution/README.md`、`validation/README.md`：理解计划-执行-验证闭环。
5. `scheduler/README.md`、`mcp/README.md`、`lsp/README.md`：阅读扩展能力。
6. `tests/README.md`：用测试理解关键模块预期行为。

## 说明

- 每个模块 README 都包含：目录职责、核心原理、Python 文件总览、逐文件说明、关键对象/函数和实现方式示例代码。
- `frontend/README.md` 说明前端目录；该目录没有 `.py` 文件，因此示例以 npm/React 结构为主。
- `__pycache__`、`node_modules`、`dist` 等生成目录不纳入 Python 模块 README。
