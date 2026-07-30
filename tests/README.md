# tests/ - 测试套件

## 这个文件夹负责什么

为 RxyCode 提供 Python 后端的自动化测试覆盖，包括核心 Agent 逻辑、缓存系统、流式输出、API 端点、路由一致性和规划/验证管道。测试使用 pytest 框架，通过 `conftest.py` 提供共享 fixture 和 stdout 保护。

## 核心原理

**隔离测试**：每个测试用 `object.__new__` 绕过 `__init__` 构造最小实例，注入 mock 的 `_index`/`_save_index`，不触碰磁盘或网络。测试之间无状态泄漏。

**stdout 保护**：`conftest.py` 的 `_protect_stdio` fixture（`autouse=True, scope="module"`）在每个测试模块前后保存/恢复 `sys.stdout`/`sys.stderr`，防止 `api_server.py` 在 Windows 上的 UTF-8 重配置破坏 pytest capture 机制（曾导致 174 个 "I/O operation on closed file" 级联错误）。

## Python 文件总览

| 文件 | 写了什么 | 功能是什么 |
|---|---|---|
| `conftest.py` | pytest 配置：stdout 保护 + 共享 fixture | 防止 api_server 的 Windows I/O 重配置破坏 pytest capture |
| `test_streaming.py` | 流式输出相关测试：cache_control 保留、注入、usage 提取 | 验证 P2 修复（流式路径缓存注入 + 三路 usage 提取） |
| `test_cache.py` | 缓存系统测试：PreciseCache、SemanticCache、PromptCacheManager | 验证三层缓存的 key 稳定性、TTL、命中率统计 |
| `test_agent_run.py` | Agent 核心逻辑测试：_is_simple_query、token 统计、进度消息 | 验证简单/复杂路由分类和 token 预算预警 |
| `test_api.py` | API 端点测试：/status、/chat/stream、/command | 验证 FastAPI SSE 端点的响应格式和路由 |
| `test_routing_consistency.py` | 路由一致性回归测试 | 防止 "跑酷游戏报错、蜘蛛卡牌正常" 类问题再次出现 |
| `test_cache_and_concurrency.py` | 缓存与并发测试 | 验证 cache_control 注入在 UsageTrackingLLM 中正确触发 |
| `test_build_timeout_handling.py` | 构建超时处理测试 | 验证超时后 fallback 消息格式正确 |
| `test_fileops_e2e.py` | 文件操作端到端测试 | 验证 read/write/list 工具的实际执行 |
| `test_logging_observability.py` | 日志可观测性测试 | 验证日志格式和 quiet path 过滤 |
| `test_parkour_pipeline_smoke.py` | 跑酷管线冒烟测试 | 验证完整 Plan-and-Execute 管线能走通 |
| `__init__.py` | 包初始化 | 标记该目录为 Python 包 |
| `test_execution/` | 执行层测试子目录 | 测试任务执行器的行为 |
| `test_planning/` | 规划层测试子目录 | 测试任务分解器和 DAG 导出 |
| `test_synthesis/` | 综合层测试子目录 | 测试最终答案合成 |
| `test_validation/` | 验证层测试子目录 | 测试重规划逻辑和重试上限 |
| `_fixtures/` | 共享测试夹具 | 测试用的 mock 数据和辅助函数 |
| `r3_subdir/` | R3 相关子目录测试 | 第三轮迭代的特定测试 |

## 文件详解

### `conftest.py`

- 写了什么：pytest 全局配置和共享 fixture
- 核心原理：`_protect_stdio` autouse fixture 保存/恢复 `sys.stdout`/`sys.stderr`，隔离 api_server.py 的 Windows I/O 重配置副作用
- 代码规模：约 30 行

关键对象/函数：

- fixture `_protect_stdio`（autouse, scope="module"）：每个测试模块前后保存/恢复原始 stdio

### `test_streaming.py`

- 写了什么：流式输出路径的核心逻辑测试
- 核心原理：验证 P2 修复的三个关键点——`_to_openai_messages` 保留 `cache_control`、`_apply_cache_control` 正确注入/不重复/跳过禁用、`_record_usage` 从三种来源提取 usage
- 代码规模：约 200 行，15 个测试

关键测试类：

- `TestToOpenAIMessages`：验证消息转换中 cache_control 字段被保留
- `TestApplyCacheControl`：验证缓存断点注入逻辑（注入/不重复/禁用/非system首条/空消息）
- `TestRecordUsage`：验证三路径 usage 提取（DeepSeek raw chunk / OpenAI raw chunk / tiktoken fallback / LangChain metadata / zero usage）

### `test_cache.py`

- 写了什么：三层缓存系统的完整测试
- 核心原理：PreciseCache 用哈希做精确匹配，SemanticCache 用相似度+实体重叠做模糊匹配，PromptCacheManager 稳定 system prompt 前缀
- 代码规模：约 210 行，23 个测试

关键测试类：

- `TestPreciseCache`：key 稳定性、filler 规范化、TTL、工具指纹、stats、clear
- `TestSemanticCache`：命中/不命中/实体重叠过滤/错误响应不缓存/TTL/clear
- `TestPromptCacheManager`：消息顺序、system prompt 稳定、reset、history 追加

### `test_agent_run.py`

- 写了什么：AgentV2 核心逻辑测试（无真实 LLM 调用）
- 核心原理：`_is_simple_query` 分类简单/复杂请求，`TokenStats` 跟踪 token 用量和缓存命中率
- 代码规模：约 165 行，24 个测试

关键测试类：

- `TestIsSimpleQuery`：简单/复杂分类（9 个用例覆盖中文/英文/文件操作/游戏生成/项目创建）
- `TestBuildProgressMessage`：超时 fallback 消息格式
- `TestEstimateTokens`：tiktoken 估算
- `TestExtractCacheRead`：DeepSeek/OpenAI/无信息/空 resp 的 cache read 提取
- `TestTokenStatsIntegration`：命中率计算/累积/reset/阈值预警

### `test_api.py`

- 写了什么：FastAPI 端点的集成测试
- 核心原理：直接注入 mock agent 到 `_state` 字典，绕过 `TestClient` 的 startup 生命周期（避免 agent 初始化触发网络调用）
- 代码规模：约 90 行，7 个测试

关键测试类：

- `TestStatusEndpoint`：/status 返回 model 和 cache 信息
- `TestChatStreamEndpoint`：/chat/stream 返回 SSE 格式且包含 done 事件
- `TestCommandEndpoint`：/clear、/models、未知命令的路由

## 运行方式

```bash
# 安装依赖
pip install -r requirements.txt
pip install pytest pytest-asyncio

# 运行全部测试
python -m pytest tests/ -v

# 运行单个测试文件
python -m pytest tests/test_streaming.py -v

# 运行特定测试类
python -m pytest tests/test_cache.py::TestPreciseCache -v

# 生成 JUnit XML 报告（CI 用）
python -m pytest tests/ --junitxml=test-results.xml
```

## 测试覆盖统计

| 模块 | 测试文件 | 测试数 | 覆盖的关键路径 |
|---|---|---|---|
| 流式输出 | test_streaming.py | 15 | cache_control 保留/注入/三路 usage |
| 缓存系统 | test_cache.py | 23 | 精确/语义/前缀缓存的 key/TTL/统计 |
| Agent 核心 | test_agent_run.py | 24 | 路由分类/token 统计/进度消息 |
| API 端点 | test_api.py | 7 | SSE 流/CORS/命令路由 |
| 路由一致性 | test_routing_consistency.py | 5 | 回归防护 |
| 并发缓存 | test_cache_and_concurrency.py | 3 | cache_control 注入触发 |
| 超时处理 | test_build_timeout_handling.py | 2 | fallback 消息 |
| 管线冒烟 | test_parkour_pipeline_smoke.py | 2 | Plan-and-Execute 全流程 |
| 规划/验证 | test_planning/ + test_validation/ | 9 | 分解器/重规划 |
| **合计** | | **111** | |
