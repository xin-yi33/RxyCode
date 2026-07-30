# config/ - 配置模块

## 这个文件夹负责什么

读取、保存、迁移 RxyCode 的用户配置、模型配置、MCP 配置、调度器配置和输出目录。

## 核心原理

默认值写在代码里，用户改动落到 YAML；启动时先定位用户数据目录，再迁移旧数据、加载配置、缺失字段补默认值。

## Python 文件总览

| 文件 | 写了什么 | 功能是什么 |
|---|---|---|
| `__init__.py` | 包初始化文件，标记该目录为 Python 包并承载导出入口。 | 包初始化文件，标记该目录为 Python 包并承载导出入口。 |
| `model_manager.py` | 模型管理：增删模型、列模型、切换 active model、测试连接。 | 模型管理：增删模型、列模型、切换 active model、测试连接。 |
| `settings.py` | 主配置入口：用户数据目录、config.yaml、默认配置、模型/MCP/scheduler 配置读取。 | 主配置入口：用户数据目录、config.yaml、默认配置、模型/MCP/scheduler 配置读取。 |

## 文件详解

### `__init__.py`

- 写了什么：包初始化文件，标记该目录为 Python 包并承载导出入口。
- 功能是什么：包初始化文件，标记该目录为 Python 包并承载导出入口。
- 核心原理：默认值写在代码里，用户改动落到 YAML；启动时先定位用户数据目录，再迁移旧数据、加载配置、缺失字段补默认值。
- 代码规模：约 0 行。

关键对象/函数：

- 无公开类/函数；通常用于包初始化、导入聚合或占位。

实现方式示例代码：

```python
# config\__init__.py 没有独立调用入口，通常通过导入所在包触发。
```

### `model_manager.py`

- 写了什么：模型管理：增删模型、列模型、切换 active model、测试连接。
- 功能是什么：模型管理：增删模型、列模型、切换 active model、测试连接。
- 核心原理：默认值写在代码里，用户改动落到 YAML；启动时先定位用户数据目录，再迁移旧数据、加载配置、缺失字段补默认值。
- 代码规模：约 117 行。

关键对象/函数：

- 函数 `add_model(name, api_key, base_url, model_name, max_tokens, temperature)`
- 函数 `remove_model(name)`
- 函数 `list_models()`
- 函数 `set_active_model(name)`
- 函数 `test_model_connection(name)`

实现方式示例代码：

```python
from RxyCode.RxyCode1_1_0.config.model_manager import add_model

result = add_model(name=..., api_key=..., base_url=..., model_name=..., max_tokens=..., temperature=...)
```

### `settings.py`

- 写了什么：主配置入口：用户数据目录、config.yaml、默认配置、模型/MCP/scheduler 配置读取。
- 功能是什么：主配置入口：用户数据目录、config.yaml、默认配置、模型/MCP/scheduler 配置读取。
- 核心原理：默认值写在代码里，用户改动落到 YAML；启动时先定位用户数据目录，再迁移旧数据、加载配置、缺失字段补默认值。
- 代码规模：约 147 行。

关键对象/函数：

- 函数 `get_data_dir()`
- 函数 `get_config_path()`
- 函数 `get_output_dir()`：Return the default output directory for generated files and downloads.
- 函数 `load_config()`
- 函数 `save_config(cfg)`
- 函数 `get_mcp_config(cfg)`：Get MCP servers configuration.
- 函数 `get_scheduler_config(cfg)`：Get scheduler configuration.
- 函数 `get_active_model_config(cfg)`
- 函数 `get_model_config(model_name, cfg)`

`execution.tool_timeout_seconds` 默认是 `1800`，作为 fast path、图执行和
workflow 共用的单次工具墙钟上限。`task_stall_timeout_seconds` 默认是 `0`，
因此不会再以“静默 600 秒”为由固定终止合法长任务；独立的
`task_max_time_seconds=7200` 仍限制单任务总时长。只有显式把相应正数上限
设为 `0` 才会禁用该层 deadline，外部取消仍始终传播。

实现方式示例代码：

```python
from RxyCode.RxyCode1_1_0.config.settings import get_data_dir

result = get_data_dir()
```

## 典型协作关系

被 main.py、api_server.py、core、tools、scheduler、mcp 等模块读取。
