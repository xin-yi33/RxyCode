# lsp/ - LSP 模块

## 这个文件夹负责什么

通过 JSON-RPC 与语言服务器通信，获取 diagnostics 等代码诊断信息。

## 核心原理

按 LSP 协议用 Content-Length 头封装 JSON 消息，用 request id 匹配请求和响应。

## Python 文件总览

| 文件 | 写了什么 | 功能是什么 |
|---|---|---|
| `__init__.py` | LSP (Language Server Protocol) client module. | LSP (Language Server Protocol) client module. |
| `client.py` | 客户端实现：在 lsp 中是语言服务器客户端，在 mcp 中是 MCP stdio 客户端。 | LSP client - communicates with language servers via JSON-RPC. |

## 文件详解

### `__init__.py`

- 写了什么：LSP (Language Server Protocol) client module.
- 功能是什么：LSP (Language Server Protocol) client module.
- 核心原理：按 LSP 协议用 Content-Length 头封装 JSON 消息，用 request id 匹配请求和响应。
- 代码规模：约 5 行。

关键对象/函数：

- 无公开类/函数；通常用于包初始化、导入聚合或占位。

实现方式示例代码：

```python
# lsp\__init__.py 没有独立调用入口，通常通过导入所在包触发。
```

### `client.py`

- 写了什么：客户端实现：在 lsp 中是语言服务器客户端，在 mcp 中是 MCP stdio 客户端。
- 功能是什么：LSP client - communicates with language servers via JSON-RPC.
- 核心原理：按 LSP 协议用 Content-Length 头封装 JSON 消息，用 request id 匹配请求和响应。
- 代码规模：约 272 行。

关键对象/函数：

- 类 `Diagnostic`：LSP diagnostic (error/warning).
- 类 `LSPClient`：Language Server Protocol client.；常用方法：`start`、`stop`、`open_file`、`notify_change`、`get_diagnostics`、`get_diagnostics_summary`
- 函数 `create_lsp_client(language, workspace)`：Create and start an LSP client for the given language.

实现方式示例代码：

```python
from RxyCode.RxyCode1_1_0.lsp.client import Diagnostic

# 示例：根据真实业务传入依赖或配置
obj = Diagnostic(...)
# result = obj.<method>(...)
```

## 典型协作关系

主要给 diagnostics 工具提供语言服务器诊断能力。
