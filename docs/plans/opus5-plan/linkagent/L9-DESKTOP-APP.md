# L9 · Desktop 应用（基于 RxyCode Desktop）

> **前置（后端侧 L9-1 ~ L9-3）**：LinkAgent [`L3`](./L3-RETRIEVAL-AND-SCOPE.md) 完成 + **RxyCode Phase 2 落地**（`protocol/` 与 `appserver/` 存在）
> **前置（前端侧 L9-4 ~ L9-8）**：**RxyCode Phase 3 落地**（有 Electron 壳可以 fork），排期约 2026-12-18
> **产出**：一个能装、能跑、能看见自己经验层的桌面应用
> **工时**：17 天
> **卡数**：8 张（L9-1 ~ L9-8）
>
> **干活前读** [`../COMPOSER-2.5-PLAYBOOK.md`](../COMPOSER-2.5-PLAYBOOK.md) §2。**一次只做一张卡。**
> **接口字段的权威定义在** [`APPENDIX-C-INTERFACE-CONTRACTS.md`](./APPENDIX-C-INTERFACE-CONTRACTS.md)，这份文档不重复。

---

## §0 产品形态

**LinkAgent 是独立桌面应用，而这个应用建在 RxyCode 的 Desktop 之上。**

```
┌─────────────────────────────────────────────────────────────┐
│  LinkAgent Desktop（Electron + Vite + React）                │
│                                                              │
│  从 RxyCode Desktop fork 来的：                               │
│    · Electron 壳、子进程管理、打包                             │
│    · 对话区、流式渲染、工具卡片、中断                           │
│    · 审批模态框、设置页骨架                                    │
│                                                              │
│  LinkAgent 新增的：                                           │
│    · EKO 森林视图（只读）                                      │
│    · 检索解释面板                                             │
│    · 经验相关设置                                             │
└────────────────────────┬────────────────────────────────────┘
                         │  JSON-RPC over stdio（RxyCode 协议 + LinkAgent 扩展）
                         ▼
┌─────────────────────────────────────────────────────────────┐
│  python -m linkagent.appserver                               │
│  实现 RxyCode 的协议表面 + eko/* 扩展方法                      │
│  内部走 LinkAgent 的 TurnOrchestrator（L2-6）                 │
└────────────────────────┬────────────────────────────────────┘
                         │  pip 依赖，不改源码
                         ▼
                     RxyCode
```

### 三个"抄"的边界

| 东西 | 怎么处理 | 理由 |
|---|---|---|
| **协议类型** | **不 fork，从合并 schema 重新生成** | 类型只能有一个真源。手抄一份必然漂移 |
| **JSON-RPC 传输客户端** | 依赖 `@rxycode/protocol-client`；实在拿不到就 vendor 传输层 | 它是通用 JSON-RPC，不含业务语义，vendor 的风险低 |
| **Electron 壳与 UI 组件** | **fork，钉住 commit** | LinkAgent 一定会分叉（多两个视图、不同品牌）。硬撑着共用只会两边都别扭 |

**记录 fork 点**：`desktop/FORK-POINT.md` 写清 fork 自 RxyCode 哪个 commit、改了哪些文件、怎么 rebase。**这个文件不写，半年后没人知道该怎么跟上游。**

---

## §1 我上一版设计错了两处，这里改过来

上一版 L9 是在不知道 RxyCode Phase 3 细节的情况下写的，有两个决定要推翻：

| 上一版 | 现在 | 为什么 |
|---|---|---|
| Tauri 2 | **Electron** | RxyCode Phase 3 选了 Electron（团队没有 Rust 经验）。既然要基于它做，就得跟 |
| 本地 HTTP + SSE + 会话令牌 | **JSON-RPC over stdio** | RxyCode 的协议就是 stdio。跟着它反而**更安全**——见下 |

### stdio 顺带解决了一整类安全问题

我上一版花了一整张卡处理"本地 HTTP 服务谁都能连"：绑 loopback、随机端口、一次性令牌、handshake 文件权限。

**换成 stdio，这些全部消失。** 管道由父进程持有，没有端口，没有监听，本机其他进程连不上，不需要认证。

> 这不是"少写点代码"的问题，是**攻击面直接没了**。一个能执行代码和写文件的本地服务不监听任何端口，是明显更好的姿态。

### 审批 UI 保持 RxyCode 的模态框

上一版我说"审批卡片内联在对话流里，不要模态框"。**现在改成沿用 fork 来的模态框。**

理由是 fork 的分叉成本比这个 UI 偏好更重要——改掉审批交互意味着每次 rebase 都要处理冲突。**只在模态框上加一件事**：FULL 级不渲染"允许"按钮（[`L4`](./L4-SAFETY-GATE.md) 定的不可覆盖）。

如果实际用下来 SAG 触发频繁、模态框打断感太强，再单独立卡改。**别在第一版就为了假想的问题制造分叉。**

---

## §2 排期上的硬依赖

**这是整个 LinkAgent 里唯一一处"等别人"的地方，必须提前知道。**

| LinkAgent 卡 | 等 RxyCode 的什么 | RxyCode 排期 |
|---|---|---|
| L9-1 ~ L9-3（后端 + 类型） | **Phase 2**：`protocol/`、`appserver/`、`frontend/protocol-client/` | W9–W12，约 2026-10-23 |
| L9-4 ~ L9-8（Electron 壳与视图） | **Phase 3**：D1–D6 的 Electron 壳、对话区、审批、设置、打包 | W13–W20，约 2026-12-18 |

**建议排法**：L9-1 ~ L9-3 跟在 L3 后面做（那时 Phase 2 已经落地），前端侧等到 12 月。中间这段时间投 [`L4`](./L4-SAFETY-GATE.md)、[`L5`](./L5-EVIDENCE-AND-EVOLUTION.md)、[`L7`](./L7-EVAL-HARNESS.md)、[`L8`](./L8-PRESET-EKO-PACK.md)——**它们一个都不依赖桌面端**。

> ⚠ 如果 RxyCode Phase 3 延期，**不要自己另起一个壳去赶进度**。宁可晚，也别造出第二套桌面代码——那等于放弃了"基于 RxyCode desktop"这个决定的全部好处。

---

## §3 两件最容易做错的事

### 错误一：把"只读"当成 UI 层的约定

用户不能直接编辑 EKO（产品决策 #4）。**如果这条只靠"前端不放编辑按钮"来保证，它迟早会被破坏。**

> **正确做法：协议里根本不存在 EKO 的写方法。**
>
> `linkagent/protocol/` 的 `eko/*` **只有查询方法**（`eko/list`、`eko/show`、`eko/history`）。EKO 的任何变更都只能发生在一次 turn 内部，由 agent 调 [`L5-6`](./L5-EVIDENCE-AND-EVOLUTION.md) 定义的工具完成，走引擎的校验路径——版本链、证据、安全门一个不少。
>
> 这样"不能直接编辑"是**协议层的保证**，不是 UI 约定。前端就算想改也没有方法可调。

用户想改？跟 agent 说"以后别再用 `os.path` 了"，agent 调 `eko_revise`，产生新版本，带完整 provenance。

### 错误二：给空数据做炫酷的关系图

[`L6`](./L6-COMPOSITION-AND-CONFLICT.md) 默认关闭，意味着**绝大多数 EKO 的 `dependencies` 和 `conflicts` 是空的**。

所以"EKO 架构图"的主体是**森林的层级结构**（域 → EKO → 版本历史），不是依赖关系网。

| 优先做 | 别一开始做 |
|---|---|
| 域层级的可折叠树 + 详情面板 | 力导向依赖关系图 |
| 版本历史时间线 | 冲突关系的可视化编辑 |
| 检索命中的高亮 | 3D / 动画 |

依赖图留一个位置，等 L6 在某个域真的打开了再填。

---

## §4 任务卡

### L9-1 · 协议扩展与 schema 合并契约

`P0` / 2 天 / 依赖：L3 全部 + RxyCode Phase 2

**背景**

LinkAgent 要说 RxyCode 的协议，**再多说几句自己的**。关键是"多说的那几句"不能让原来的话变味。

**涉及文件**

| 文件 | Grep 锚点 | 改法 |
|---|---|---|
| `src/linkagent/protocol/__init__.py` | 新建 | — |
| `src/linkagent/protocol/eko_requests.py` | 新建 | `eko/*` 查询方法 |
| `src/linkagent/protocol/eko_events.py` | 新建 | `event/eko_*` 通知 |
| `src/linkagent/protocol/schema.py` | 新建 | 合并导出 |
| `src/linkagent/protocol/schema.json` | 新建，**提交进 git** | 冻结产物 |
| `tests/protocol/test_schema_superset.py` | 新建 | **核心契约测试** |

**已经替你决定好的**

| 决定 | 理由 |
|---|---|
| **复用 RxyCode 的 pydantic 模型**，`from rxycode.protocol import ...`，不重新定义 | 重新定义等于手抄一份协议，必然漂移 |
| LinkAgent 只定义**新增的**模型 | 同上 |
| 导出的是**合并 schema**（RxyCode 的 + LinkAgent 的） | 前端只需要认一份 schema，不用拼两份 |
| 扩展方法一律 `eko/` 前缀，扩展事件一律 `event/eko_` 前缀 | 一眼能看出哪些是 LinkAgent 加的 |
| **`eko/*` 只有查询方法**，没有任何写方法 | §3 说的协议层保证 |
| `schema.json` 提交进 git + 冻结测试 | 与 RxyCode P1 的做法一致 |

**核心契约测试**（这张卡的价值全在这里）：

```python
def test_merged_schema_is_a_superset_of_rxycode_schema():
    """LinkAgent 的协议必须完整包含 RxyCode 的协议。

    RxyCode 升级后如果改了协议,这个测试会红,而且能指出改了哪个模型的
    哪个字段。这比运行时发现「桌面端某个事件不显示了」早得多,也具体
    得多。

    注意断言的是「超集」不是「相等」——LinkAgent 本来就多几个方法。
    """

def test_extension_methods_do_not_shadow_rxycode_methods():
    """LinkAgent 的方法名不能和 RxyCode 的撞车。"""

def test_no_eko_mutation_methods_exist():
    """协议里不存在任何修改 EKO 的方法。

    这是产品决策 #4 的机器可验证形式。前端就算想改 EKO 也没有方法可调。
    """
```

**验收命令**

```powershell
cd "D:\agent-demo\LinkAgent"
python -m linkagent.protocol.schema | Out-File -Encoding utf8 src\linkagent\protocol\schema.json
python -m pytest tests/protocol/ -q
python -m ruff check src/linkagent/protocol
```

**完成判据**
- [ ] 超集测试通过；**故意改一个 RxyCode 模型能让它变红**（要真的试一次）
- [ ] 方法名无冲突
- [ ] `eko/*` 下 grep 不到任何写方法
- [ ] `schema.json` 已生成并提交
- [ ] 每个新模型有 docstring 说明字段来源

**禁止**

- ❌ 重新定义 RxyCode 已有的协议模型
- ❌ 加任何 EKO 写方法
- ❌ 手改 `schema.json`

---

### L9-2 · LinkAgent appserver

`P0` / 2.5 天 / 依赖：L9-1、L2-6

**背景**

`python -m linkagent.appserver` 是桌面端唯一的后端入口。

**这不是一个代理。** LinkAgent 已经拥有外层循环（[`L2-6`](./L2-RXYCODE-BRIDGE.md) 的 `TurnOrchestrator`），所以 appserver 直接把协议方法映射到 LinkAgent 自己的 turn 流程上，turn 内部再调 RxyCode。

**涉及文件**

| 文件 | Grep 锚点 | 改法 |
|---|---|---|
| `src/linkagent/appserver/__main__.py` | 新建 | 入口 |
| `src/linkagent/appserver/dispatch.py` | 新建 | 方法分发 |
| `src/linkagent/appserver/handlers/session.py` | 新建 | RxyCode 协议表面 |
| `src/linkagent/appserver/handlers/eko.py` | 新建 | `eko/*`，**只读** |
| `tests/appserver/test_dispatch.py` | 新建 | — |

**已经替你决定好的**

| 决定 | 理由 |
|---|---|
| **stdio JSON-RPC**，不开任何端口 | 攻击面为零，见 §1 |
| `stdout` **只走协议**，日志一律 `stderr` + 落盘 | 往 stdout 打一行 print 就会毁掉整条管道。这是 stdio 协议最经典的坑 |
| 日志落 `~/.linkagent/logs/` | 桌面端没有终端 |
| 分发表**数据驱动**（方法名 → handler 的字典），不是一串 `if/elif` | Composer 加方法时不容易改坏别的 |
| 未知方法返回标准 JSON-RPC `-32601`，**不崩** | 客户端版本比服务端新时要能优雅降级 |
| handler 里**不写业务逻辑**，只做协议 ↔ 领域对象的翻译 | 业务在 `runtime/turn.py`。handler 一旦长胖就会和 CLI 行为漂移 |

**操作步骤**

1. `appserver/__main__.py`：

```python
"""LinkAgent 的 app server。桌面端唯一的后端入口。

## 为什么 stdout 只能走协议

传输是 JSON-RPC over stdio。任何一行 print、任何一个把日志写到 stdout
的库,都会插进协议流里让客户端解析失败,而且报错现场离真凶很远。

所以:进程启动的第一件事就是把 logging 的 handler 全部指到 stderr 和
文件,并且在测试里断言 stdout 除了协议什么都没有。

## 这不是代理

LinkAgent 拥有外层循环(runtime/turn.py)。session/prompt 进来之后走的是
LinkAgent 的七步 turn,turn 内部才调 RxyCode。所以这里实现的是「同一份
协议表面的另一个实现」,不是「把请求转发给 RxyCode 的 appserver」。
"""
```

2. `handlers/eko.py` 顶部写死一句注释：**这个文件永远只有查询**。

**完成判据**
- [ ] 手工用管道发 `initialize` + `session/new` + `session/prompt`，能收到流式事件
- [ ] **stdout 纯净测试**：跑完一轮，stdout 每一行都能被 JSON 解析
- [ ] 未知方法返回 `-32601` 且进程存活
- [ ] `eko/list`、`eko/show`、`eko/history` 可用
- [ ] 日志在 `~/.linkagent/logs/` 里，不在 stdout
- [ ] handler 全部 30 行以内（超了说明业务逻辑漏进来了）

**禁止**

- ❌ 往 stdout 写任何非协议内容
- ❌ 在 handler 里写业务逻辑
- ❌ 开监听端口

---

### L9-3 · TypeScript 类型生成与传输客户端

`P0` / 1.5 天 / 依赖：L9-1

**背景**

前端要有类型。**类型从合并 schema 生成，不从 RxyCode 抄。**

**涉及文件**

| 文件 | 说明 |
|---|---|
| `desktop/packages/protocol/package.json` | 新建 |
| `desktop/packages/protocol/src/generated/types.ts` | **生成物，不手改** |
| `desktop/packages/protocol/src/index.ts` | 导出 |

**已经替你决定好的**

| 决定 | 理由 |
|---|---|
| 类型从 **LinkAgent 的合并 schema** 生成，用 `json-schema-to-typescript` | 与 RxyCode P2 同一套工具链，单一真源 |
| 传输层优先 **依赖 `@rxycode/protocol-client`** | 它是通用 JSON-RPC，含双向请求支持（审批要用），没必要重写 |
| 拿不到 npm 包就 **vendor 传输层**（只 vendor `client.ts`，**不 vendor 类型**），并在 `desktop/VENDORED.md` 记录来源 commit | 传输层不含业务语义，vendor 风险低；类型 vendor 一定漂移 |
| CI 检查**生成物新鲜度**：重新生成后 `git diff --exit-code` | 与 RxyCode P2 一致 |

**完成判据**
- [ ] `npm run generate` 能从 `schema.json` 产出类型
- [ ] 类型里同时有 RxyCode 的事件和 LinkAgent 的 `event/eko_*`
- [ ] 传输客户端能处理**服务端发起的请求**（审批）
- [ ] CI 有新鲜度检查
- [ ] 如果 vendor 了传输层，`VENDORED.md` 记录了来源 commit

**禁止**

- ❌ 手改 `generated/types.ts`
- ❌ vendor 类型定义

---

### L9-4 · fork RxyCode Desktop 壳

`P0` / 2 天 / 依赖：L9-3 + **RxyCode Phase 3 的 D1–D5**

**背景**

把 RxyCode Desktop 搬过来，改成连 LinkAgent 的 appserver。**这张卡的目标是"能跑起来且分叉最小"，不是重新设计。**

**涉及文件**

| 文件 | 说明 |
|---|---|
| `desktop/` | 从 RxyCode `frontend/desktop/`（Phase 3 产物）复制 |
| `desktop/FORK-POINT.md` | **必须写**：fork 自哪个 commit、改了哪些文件、怎么 rebase |
| `desktop/src/platform/` | 子进程改指 `linkagent.appserver` |

**已经替你决定好的**

| 决定 | 理由 |
|---|---|
| **整目录复制，钉住 commit**，不用 git submodule / subtree | submodule 在 Windows 上的体验一言难尽，而且我们本来就要改 |
| 第一次 fork **只改一处**：子进程命令换成 `python -m linkagent.appserver` | 一次改一件事。壳先跑通，视图下一张卡 |
| **保留 RxyCode 的审批模态框**，只加 FULL 级不渲染"允许"按钮 | 见 §1。分叉成本比 UI 偏好重要 |
| **遵守 RxyCode 的 DC1–DC5**（协议唯一通道、不复制业务逻辑、平台能力隔离在 `src/platform/`、密钥进钥匙链、不留孤儿进程） | 这些约束对 LinkAgent 同样成立，而且遵守它们才能继续 rebase |
| 品牌改动集中在**一个主题文件 + 资源目录** | 散在各处的话每次 rebase 都要手动挑 |

**完成判据**
- [ ] `npm run dev` 能起来，连上 LinkAgent 的 appserver，跑完一轮对话
- [ ] 关窗口后 **Python 进程消失**（任务管理器/`ps` 真的看一眼）
- [ ] 审批模态框工作；FULL 级**没有允许按钮**
- [ ] `FORK-POINT.md` 写全了三项内容
- [ ] `git diff` 相对上游只有预期内的改动（要真的过一遍）

**禁止**

- ❌ 借这次 fork 顺手重构 RxyCode 的 UI 代码
- ❌ 破坏 DC1–DC5
- ❌ 品牌改动散落各处

---

### L9-5 · EKO 森林只读视图

`P0` / 3 天 / 依赖：L9-4、L8-4

**背景**

用户能看见自己的经验层。**只读**——见 §3。

**界面结构**

```
┌───────────────┬──────────────────────────────────┐
│ 域树（可折叠）  │  详情面板                          │
│               │                                  │
│ ▼ engineering │  eko-modeu-prefer-pathlib        │
│   ▼ community │  v1.0.2 · 个人 · 活跃              │
│     TDD       │  ─────────────────────────────   │
│     增量实现   │  描述 / 前置条件 / 步骤            │
│   ▼ personal  │  作用域 · 来源 · 使用统计          │
│     用 pathlib│  ─────────────────────────────   │
│ ▶ python      │  版本历史                         │
│ ▶ typescript  │   v1.0.2 ← v1.0.1 ← v1.0.0       │
└───────────────┴──────────────────────────────────┘
```

**已经替你决定好的**

| 决定 | 理由 |
|---|---|
| 主视图是**层级树**不是关系图 | §3：`dependencies` 大多是空的 |
| **社区层和个人层视觉上一眼可分** | 用户必须知道哪些是自己的、哪些是预置的 |
| 详情面板显示**完整 provenance** | "agent 为什么这么做"的答案在这里 |
| 版本历史是**只读时间线**，可查看任意历史版本内容 | EKO 版本不可变，天然适合时间线 |
| 数据全部来自 `eko/list`、`eko/show`、`eko/history` | DC1：只走协议 |
| 大森林用**虚拟化列表** | 几千条时不能卡 |
| **界面上没有任何编辑控件** | 协议层也没有写方法，两层都堵死 |
| 每条 EKO 旁边有"想改这条？跟 agent 说" + 一键带进对话 | 只读不等于没有出口 |

**完成判据**
- [ ] 树能展开折叠，域层级正确
- [ ] 社区/个人层视觉可区分
- [ ] 详情面板字段完整，provenance 可读
- [ ] 版本历史能看任意历史版本
- [ ] 1000 条 EKO 滚动不掉帧
- [ ] **界面上找不到任何编辑/删除按钮**
- [ ] "带进对话"能把该 EKO 的引用塞进输入框

**禁止**

- ❌ 任何直接编辑入口
- ❌ 一开始就做力导向关系图
- ❌ 绕过协议直接读文件

---

### L9-6 · 检索解释面板

`P1` / 2 天 / 依赖：L9-5、L3-5

**背景**

[`L3-5`](./L3-RETRIEVAL-AND-SCOPE.md) 已经把检索遥测记下来了。这张卡把它显示出来。

**这是 LinkAgent 最有说服力的一个界面**——它回答"agent 为什么这么做"，而这正是普通编码 agent 答不了的问题。

**面板要回答四个问题**

| 问题 | 数据来源 |
|---|---|
| 这轮推断出的情境是什么？（域、任务类型） | L3-1 的 `RetrievalContext` |
| 哪些 EKO 被检索出来了？排序分数多少？ | L3-3 |
| 哪些**被作用域挡掉了**？为什么？ | L3-2 的域硬门，**逐条记录 id + 原因** |
| 最终注入了哪几条？ | L2-3 |

> 第三条最有价值。用户发现"我明明有一条相关经验但没被用上"时，这里能直接给出答案。

**已经替你决定好的**

| 决定 | 理由 |
|---|---|
| 实时数据走 `event/eko_retrieved` 通知，历史数据走 `eko/retrieval_log` 查询 | 当前 turn 要即时，历史 turn 不该占推送通道 |
| 被拒条目的文案是**人话**，不是 `ExclusionReason` 的枚举名 | `DOMAIN` 对用户没有意义 |
| 面板默认收起 | 大多数时候用户只想聊天 |

**完成判据**
- [ ] 跑一个 turn，面板显示推断出的域和任务类型
- [ ] 命中列表带分数，可点进森林视图
- [ ] 被作用域挡掉的条目**有列出且有人话理由**
- [ ] 空检索时显示"没有匹配的经验"而不是空白
- [ ] 可查看历史 turn 的检索记录

**禁止**

- ❌ 只显示命中不显示被拒
- ❌ 拿枚举名当理由文案

---

### L9-7 · 设置扩展

`P1` / 2 天 / 依赖：L9-4、L5 全部、L8-4

**背景**

RxyCode 的设置页（D5）已经有模型和工作区。LinkAgent 在它上面**加一个"经验"分组**。

**要新增的设置**

| 分组 | 项 | 默认 |
|---|---|---|
| 模型 | **蒸馏模型**（可与执行模型不同） | 与执行模型相同 |
| 经验 | 检索开关、top-k | 开 / 5 |
| 经验 | 反馈演化开关 | 开 |
| 经验 | **依赖组合、冲突裁决**（L6） | **关**——见 [`L6`](./L6-COMPOSITION-AND-CONFLICT.md) |
| 预置 | 预置包总开关、按域关闭、钉住版本 | 开 |
| 安全 | SAG 审批超时 | 60s |
| 数据 | 数据目录、导出、清空个人经验 | `~/.linkagent/` |

**已经替你决定好的**

| 决定 | 理由 |
|---|---|
| **所有模型由用户选**，系统只给建议文案，不硬编码 | 产品决策 #2 |
| 蒸馏模型**单独可选** | 论文特意用不同模型蒸馏和执行以减少偏差；但选哪个由用户定 |
| 执行模型、API Key 等**沿用 RxyCode 的设置页**，不重做 | 少一处分叉 |
| L6 两项标注"**实验性，默认关闭**"并给出理由链接 | 不解释的话用户会以为是没做完 |
| "清空个人经验"**二次确认 + 先自动导出** | 不可逆操作必须有后悔药 |
| 设置**即时生效**（数据目录除外） | — |
| 不做云同步 | 经验库是个人数据，同步是另一个量级的问题 |

**完成判据**
- [ ] 改蒸馏模型后，下一次蒸馏用的是新模型（看日志确认）
- [ ] 关掉检索后，`event/eko_retrieved` 不再出现
- [ ] L6 开关有"实验性"标注和理由链接
- [ ] 清空个人经验有二次确认，且先落了一份导出
- [ ] 改数据目录提示需要重启
- [ ] 新增设置集中在**独立的组件文件**里（rebase 友好）

**禁止**

- ❌ 硬编码任何模型
- ❌ 重做 RxyCode 已有的设置项
- ❌ 不可逆操作不给导出

---

### L9-8 · 打包与分发

`P2` / 2 天 / 依赖：L9-1 ~ L9-7

**背景**

沿用 RxyCode D6 的打包流程，改成打 LinkAgent。

**已经替你决定好的**

| 决定 | 理由 |
|---|---|
| 只支持 **Windows + macOS** | Linux 桌面分发碎片化，先放着。RxyCode D6 打三平台，LinkAgent 少一个 |
| Python 后端**内嵌运行时**，沿用 RxyCode D6 的做法 | 目标机器不能假定有 Python |
| **预置包嵌进安装包**，不联网下载 | 见 [`L8 §2`](./L8-PRESET-EKO-PACK.md) |
| `THIRD-PARTY-NOTICES.md` **进安装包**并在关于页可查 | License 合规是硬要求（预置包来自 MIT/Apache 项目） |
| 首次启动做**环境自检**（磁盘、目录权限、RxyCode 可导入）并给出可读报错 | 桌面用户没有终端看 traceback |
| 暂不做自动更新（RxyCode D7 的对应能力） | 自动更新是独立工程，别塞进第一版 |

**完成判据**
- [ ] Windows 干净虚拟机装完能跑完整一轮对话
- [ ] macOS 同上
- [ ] 目标机器**没有 Python** 也能跑
- [ ] 首次启动创建 `~/.linkagent/` 并装载预置包
- [ ] 关于页能看到 `THIRD-PARTY-NOTICES`
- [ ] 卸载后用户数据保留（不静默删经验库）

**禁止**

- ❌ 假定目标机器有 Python / Node
- ❌ 联网下载预置包
- ❌ 卸载时删用户数据

---

## §5 完成标准

- [ ] 干净机器装包 → 启动 → 完成一轮编码任务
- [ ] 森林视图里能看到预置 EKO 和自己新产生的个人 EKO
- [ ] 检索解释面板能说清这轮用了什么、没用什么、为什么
- [ ] 触发一次安全拦截，审批模态框工作正常，FULL 级无允许按钮
- [ ] 跟 agent 说"以后别用 X 了"→ 森林视图里出现新版本，**全程没碰过任何编辑控件**
- [ ] 全局检查：协议里没有任何 EKO 写方法；appserver 的 stdout 只有协议
- [ ] `FORK-POINT.md` 与 `VENDORED.md`（如果有）都是最新的

---

## §6 下一步

Desktop 完成后，[`L7`](./L7-EVAL-HARNESS.md) 的评测结论就有了展示载体。**下一个值得投入的方向是把 L7 的 A/B 结果做进关于页**——让用户看到"开经验层比不开好多少"。这是这个产品最需要证明的一句话，也是它唯一无法靠界面掩饰的地方。
