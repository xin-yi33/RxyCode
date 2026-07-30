# memory/ - 记忆模块

## 这个文件夹负责什么

管理短期会话、长期项目记忆、用户手动记忆、自动抽取、压缩和 BM25 搜索。

## 核心原理

分层记忆：短期保留最近上下文，长期保存跨会话事实，压缩器折叠长上下文，搜索器按相关性召回。

工具侧的 `history` 检索把共享与会话记忆分开：共享范围仅为
`memory/user` 和 `memory/projects/global`，会话范围仅为当前
`memory/sessions/<session_id>`。它不会递归扫描其他 session 的自动事实，
因此并发会话不会通过 history 互相读取私有上下文。

## Python 文件总览

| 文件 | 写了什么 | 功能是什么 |
|---|---|---|
| `__init__.py` | 包初始化文件，标记该目录为 Python 包并承载导出入口。 | 包初始化文件，标记该目录为 Python 包并承载导出入口。 |
| `auto_memory.py` | Automatic memory extraction from conversations. | Automatic memory extraction from conversations. |
| `chat_storage.py` | Persistent chat storage for RxyCode - with text sanitization. | Persistent chat storage for RxyCode - with text sanitization. |
| `compressor.py` | 上下文压缩：把长对话折叠成可继续使用的摘要和关键事实。 | ContextCompressor: Codex-style three-tier context compression. |
| `long_term.py` | 定义 LongTermMemory 等对象。 | 定义 LongTermMemory 等对象。 |
| `manager.py` | 管理器：在不同模块中承担统一调度/记忆 façade/后台任务管理。 | 管理器：在不同模块中承担统一调度/记忆 façade/后台任务管理。 |
| `search.py` | BM25 搜索：在记忆文件里按相关性找内容。 | BM25-based memory search across all memory files. |
| `short_term.py` | 定义 ShortTermMemory 等对象。 | 定义 ShortTermMemory 等对象。 |
| `user_memory.py` | User-managed memory - add/remove/list persistent memories. | User-managed memory - add/remove/list persistent memories. |

## 文件详解

### `__init__.py`

- 写了什么：包初始化文件，标记该目录为 Python 包并承载导出入口。
- 功能是什么：包初始化文件，标记该目录为 Python 包并承载导出入口。
- 核心原理：分层记忆：短期保留最近上下文，长期保存跨会话事实，压缩器折叠长上下文，搜索器按相关性召回。
- 代码规模：约 3 行。

关键对象/函数：

- 无公开类/函数；通常用于包初始化、导入聚合或占位。

实现方式示例代码：

```python
# memory\__init__.py 没有独立调用入口，通常通过导入所在包触发。
```

### `auto_memory.py`

- 写了什么：Automatic memory extraction from conversations.
- 功能是什么：Automatic memory extraction from conversations.
- 核心原理：分层记忆：短期保留最近上下文，长期保存跨会话事实，压缩器折叠长上下文，搜索器按相关性召回。
- 代码规模：约 173 行。

关键对象/函数：

- 类 `AutoMemory`；常用方法：`extract_facts`、`store_facts`、`compress_old_messages`、`load_compressed`、`load_facts`、`get_context`

实现方式示例代码：

```python
from RxyCode.RxyCode1_1_0.memory.auto_memory import AutoMemory

# 示例：根据真实业务传入依赖或配置
obj = AutoMemory(...)
# result = obj.extract_facts(...)
```

### `chat_storage.py`

- 写了什么：Persistent chat storage for RxyCode - with text sanitization.
- 功能是什么：Persistent chat storage for RxyCode - with text sanitization.
- 核心原理：分层记忆：短期保留最近上下文，长期保存跨会话事实，压缩器折叠长上下文，搜索器按相关性召回。
- 代码规模：约 149 行。

关键对象/函数：

- 类 `ChatStorage`：Manages saved chat sessions with text sanitization.；常用方法：`save`、`load`、`delete`、`rename`、`list_chats`、`get_chat_preview`

实现方式示例代码：

```python
from RxyCode.RxyCode1_1_0.memory.chat_storage import ChatStorage

# 示例：根据真实业务传入依赖或配置
obj = ChatStorage(...)
# result = obj.save(...)
```

### `compressor.py`

- 写了什么：上下文压缩：把长对话折叠成可继续使用的摘要和关键事实。
- 功能是什么：ContextCompressor: Codex-style three-tier context compression.
- 核心原理：分层记忆：短期保留最近上下文，长期保存跨会话事实，压缩器折叠长上下文，搜索器按相关性召回。
- 代码规模：约 313 行。

关键对象/函数：

- 类 `ContextCompressor`：Three-tier context compression following Codex strategy.；常用方法：`count_tokens`、`needs_compression`、`compress_sync`、`compress_async`

实现方式示例代码：

```python
from RxyCode.RxyCode1_1_0.memory.compressor import ContextCompressor

# 示例：根据真实业务传入依赖或配置
obj = ContextCompressor(...)
# result = obj.count_tokens(...)
```

### `long_term.py`

- 写了什么：定义 LongTermMemory 等对象。
- 功能是什么：定义 LongTermMemory 等对象。
- 核心原理：分层记忆：短期保留最近上下文，长期保存跨会话事实，压缩器折叠长上下文，搜索器按相关性召回。
- 代码规模：约 77 行。

关键对象/函数：

- 类 `LongTermMemory`；常用方法：`save_session_context`、`load_session_context`、`append_session_context`、`save_history`、`load_history`、`save_global_memory`、`load_global_memory`、`append_error_log`

实现方式示例代码：

```python
from RxyCode.RxyCode1_1_0.memory.long_term import LongTermMemory

# 示例：根据真实业务传入依赖或配置
obj = LongTermMemory(...)
# result = obj.save_session_context(...)
```

### `manager.py`

- 写了什么：管理器：在不同模块中承担统一调度/记忆 façade/后台任务管理。
- 功能是什么：管理器：在不同模块中承担统一调度/记忆 façade/后台任务管理。
- 核心原理：分层记忆：短期保留最近上下文，长期保存跨会话事实，压缩器折叠长上下文，搜索器按相关性召回。
- 代码规模：约 161 行。

关键对象/函数：

- 类 `MemoryManager`：Memory manager with improved context retrieval.；常用方法：`initialize`、`close`、`add_interaction`、`get_context_for_prompt`、`save_session`、`load_session`、`clear`、`get_context`

实现方式示例代码：

```python
from RxyCode.RxyCode1_1_0.memory.manager import MemoryManager

# 示例：根据真实业务传入依赖或配置
obj = MemoryManager(...)
# result = obj.initialize(...)
```

### `search.py`

- 写了什么：BM25 搜索：在记忆文件里按相关性找内容。
- 功能是什么：BM25-based memory search across all memory files.
- 核心原理：分层记忆：短期保留最近上下文，长期保存跨会话事实，压缩器折叠长上下文，搜索器按相关性召回。
- 代码规模：约 161 行。

关键对象/函数：

- 类 `SearchResult`
- 类 `BM25`；常用方法：`add_document`、`search`、`build_index`
- 函数 `search_memory(query, top_k)`

实现方式示例代码：

```python
from RxyCode.RxyCode1_1_0.memory.search import SearchResult

# 示例：根据真实业务传入依赖或配置
obj = SearchResult(...)
# result = obj.<method>(...)
```

### `short_term.py`

- 写了什么：定义 ShortTermMemory 等对象。
- 功能是什么：定义 ShortTermMemory 等对象。
- 核心原理：分层记忆：短期保留最近上下文，长期保存跨会话事实，压缩器折叠长上下文，搜索器按相关性召回。
- 代码规模：约 125 行。

关键对象/函数：

- 类 `ShortTermMemory`：Short-term memory with improved context isolation.；常用方法：`add_user_message`、`add_ai_message`、`get_messages`、`get_messages_as_dicts`、`load_from_dicts`、`get_context_string`、`clear`、`message_count`

实现方式示例代码：

```python
from RxyCode.RxyCode1_1_0.memory.short_term import ShortTermMemory

# 示例：根据真实业务传入依赖或配置
obj = ShortTermMemory(...)
# result = obj.add_user_message(...)
```

### `user_memory.py`

- 写了什么：User-managed memory - add/remove/list persistent memories.
- 功能是什么：User-managed memory - add/remove/list persistent memories.
- 核心原理：分层记忆：短期保留最近上下文，长期保存跨会话事实，压缩器折叠长上下文，搜索器按相关性召回。
- 代码规模：约 100 行。

关键对象/函数：

- 类 `UserMemory`；常用方法：`add`、`remove`、`list_all`、`get`、`get_all_text`、`clear`

实现方式示例代码：

```python
from RxyCode.RxyCode1_1_0.memory.user_memory import UserMemory

# 示例：根据真实业务传入依赖或配置
obj = UserMemory(...)
# result = obj.add(...)
```

## 典型协作关系

被 Agent 和 memory_tool 调用，为回答提供上下文和长期偏好。
