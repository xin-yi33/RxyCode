# Phase B 手动测试说明书

## 方式一：TUI 交互模式（最直观）

### 启动

```powershell
cd "d:\ppt or work\opus\rxycode\RxyCode"
.\venv\Scripts\python.exe -m RxyCode
```

看到 `RxyCode >` 提示符即启动成功。

### 测试 1：普通对话（证明单 Agent 基线正常）

直接打字聊天：

```
帮我看看 core/state.py 里有哪些数据结构
```

预期：Agent 正常读取文件、回复。

### 测试 2：@ 手动触发子代理

```
@explore 找出 protocol/ 目录下所有事件定义，列出文件名和行号
```

预期：
- 出现 `┌ Child explore · ses_child_xxx · running` 面板
- Child 完成后返回结果
- 回复中带 `[task completed]` 和证据引用

### 测试 3：模型自动触发 Task

```
帮我把 core/ 目录拆成两个独立任务：一个只读探索 agent_v2.py，一个只读探索 graph.py，两个并行跑
```

预期：模型自动调用 `task` 工具，创建 `explore` 子代理并行探索两个文件。

### 测试 4：@reviewer 只读审查

```
@reviewer 审查 core/subagents/permissions.py 的 allow/ask/deny 逻辑是否有安全漏洞
```

预期：reviewer 能读取文件但无法编辑（权限隔离）。

---

## 方式二：API Server 模式

### 启动

```powershell
cd "d:\ppt or work\opus\rxycode\RxyCode"
.\venv\Scripts\python.exe -m RxyCode --api
```

会打印 `RxyCode API bearer token: <token>`，记下这个 token。

### 测试 1：Capability 发现

新开一个 PowerShell：

```powershell
$token = "<上面打印的 token>"
$body = '{"jsonrpc":"2.0","method":"subagents/capability","params":{},"id":1}'
curl -X POST http://localhost:8765/api/jsonrpc -H "Authorization: Bearer $token" -H "Content-Type: application/json" -d $body
```

预期返回：
```json
{"jsonrpc":"2.0","id":1,"result":{"subagents_enabled":false,...}}
```

`s ubagents_enabled: false` 是正常的——API server 启动时 Phase B 的 feature flag 默认关闭，只有通过 `init_manager` 显式开启才会变 true。

### 测试 2：列举可 @ 的 Agent

```powershell
$token = "<token>"
$body = '{"jsonrpc":"2.0","method":"subagents/list","params":{},"id":2}'
curl -X POST http://localhost:8765/api/jsonrpc -H "Authorization: Bearer $token" -H "Content-Type: application/json" -d $body
```

预期返回 4 个内置 Agent：`explore`、`general`、`reviewer`、`scout`。

---

## 方式三：Python 脚本直接测

```powershell
cd "d:\ppt or work\opus\rxycode\RxyCode"
.\venv\Scripts\python.exe
```

```python
# 1. 加载内置 Agent
from core.subagents.builtin_agents import load_builtin_agents
reg = load_builtin_agents()
for a in reg.list_all():
    print(f"  {a.id}: {a.description} [{a.mode.value}]")

# 2. 初始化 Manager（开启 subagent feature flag）
from core.subagents.modes import SubagentConfig, SubagentFeatureFlags
from core.subagents.registry_provider import init_manager, reset_manager

reset_manager()
config = SubagentConfig(flags=SubagentFeatureFlags(
    subagents_enabled=True, subagents_task=True, subagents_mention=True))
m = init_manager(registry=reg, config=config)

# 3. 派发一个 explore 子代理
import asyncio
from protocol.subagents import TaskRequest, TriggerKind
req = TaskRequest(
    parent_session_id="manual_test",
    agent_id="explore",
    prompt="读取 core/subagents/permissions.py 并列出所有公开函数",
    trigger=TriggerKind.MENTION,
)
result = asyncio.run(m.dispatch(req))
print(f"Status: {result.status.value}")
print(f"Summary: {result.summary}")
print(f"Evidence: {result.evidence}")
print(f"Steps: {result.usage.steps}, Tokens: {result.usage.input_tokens}")

# 4. 验证隔离：Child Session 在 tree 里
tree = m.get_tree("manual_test")
session = tree.get(result.child_session_id)
print(f"Session: {session.session_id}")
print(f"Terminal: {session.is_terminal}")
print(f"Agent: {session.agent_id}")

# 5. 查看事件
from core.subagents.events import EventStore
store = EventStore()
for ev in [("created", "child_session/created"), ("completed", "child_session/completed")]:
    from core.subagents.events import build_event
    e = build_event(ev[1], result.child_session_id, "manual_test",
                     request_id=result.request_id)
    store.append(e)
print(f"Events: {store.latest_cursor()}")

# 6. PermissionPolicy 验证
from core.subagents.permissions import PermissionPolicy
reviewer = reg.get("reviewer")
policy = PermissionPolicy.from_definition(reviewer.permission, definition_version="v1")
print(f"read allow:  {policy.evaluate('read', 'core/auth.py').allows}")
print(f"edit deny:   {not policy.evaluate('edit', 'core/auth.py').allows}")

reset_manager()
```

预期输出：
```
explore: 只读探索... [subagent]
general: 通用子任务... [subagent]
reviewer: 审查 diff... [subagent]
scout: 外部文档检索... [subagent]
Status: completed
Summary: [ChildRuntime explore] Task received: ...
Evidence: ()
Steps: 1, Tokens: 0
Session: ses_child_...
Terminal: True
Agent: explore
Events: 2
read allow:  True
edit deny:   True
```

---

## 快速自检清单

| # | 检查项 | 怎么测 | 预期 |
|---|--------|--------|------|
| 1 | 普通对话 | TUI 里随便聊天 | 正常回复 |
| 2 | `@explore` | TUI 里输入 `@explore <问题>` | Child Session 面板出现，返回证据 |
| 3 | `@reviewer` 不能写 | `@reviewer 审查 xxx.py` | 只读，不产生文件修改 |
| 4 | 内置 Agent 列表 | Python 脚本 `reg.list_all()` | 4 个 agent |
| 5 | API capability | `curl subagents/capability` | 返回 JSON |
| 6 | API agent list | `curl subagents/list` | 返回 agent 列表 |
| 7 | PermissionPolicy | Python 脚本 | allow/deny 正确 |
| 8 | Child Session 隔离 | 并行跑两个 explore | 不同 session_id，不共享状态 |
| 9 | 取消传播 | `m.cancel_root()` | 所有 child 进入 terminal |
| 10 | Event 持久化 | 写 EventStore，重启读取 | cursor 连续，终端事件可恢复 |
