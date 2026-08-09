# 附录 C · 接口契约

> **这份文档是所有跨边界接口的权威定义。** 施工文档（L0–L9）里凡是提到某个接口的字段、方法名、事件名，都以这里为准，不在各自文档里重复定义。
>
> **改接口的规矩**：先改这份文档，再改代码，再改契约测试。**顺序反了就会出现"文档说 A、代码做 B、测试测 C"的三方不一致。**
>
> **创建**：2026-08-01

---

## §0 一共有几道边界

LinkAgent 有五道跨边界接口。**每一道都有对应的契约测试，红了就说明边界被破坏了。**

```
        ┌──────────────────────────────┐
        │   LinkAgent Desktop（TS）     │
        └───────────────┬──────────────┘
                        │ ① 协议边界（JSON-RPC over stdio）
        ┌───────────────▼──────────────┐
        │   linkagent.appserver         │
        └───────────────┬──────────────┘
                        │ ② 内部模块边界（Python Protocol）
        ┌───────────────▼──────────────┐
        │   runtime / eko / safety /    │
        │   distillation / preset       │
        └───────┬───────────────┬──────┘
                │ ③ RxyCode 边界 │ ④ 磁盘边界
        ┌───────▼──────┐ ┌──────▼───────┐
        │   RxyCode    │ │ ~/.linkagent │
        └──────────────┘ └──────────────┘

        ⑤ agent 工具边界（模型 ↔ EKO 引擎）
```

| # | 边界 | 契约测试 | 定义在 |
|---|---|---|---|
| ① | Desktop ↔ appserver | `tests/protocol/test_schema_superset.py` | §1 |
| ② | LinkAgent 内部模块 | 各模块的 `Protocol` 定义 + mypy | §2 |
| ③ | LinkAgent ↔ RxyCode | `tests/bridge/test_rxycode_contract.py` | §3 |
| ④ | 内存 ↔ 磁盘 | `tests/eko/test_corpus_contract.py` | §4 |
| ⑤ | 模型 ↔ EKO 引擎 | `tests/tools/test_eko_tools.py` | §5 |

---

## §1 协议边界（Desktop ↔ appserver）

**传输**：JSON-RPC 2.0 over stdio。没有端口，没有认证——管道由父进程持有。

**版本**：LinkAgent 的协议版本独立于 RxyCode，格式 `linkagent/<major>.<minor>.<patch>`。`initialize` 时双方交换。

### 1.1 沿用 RxyCode 的部分（不重新定义）

从 `rxycode.protocol` 直接 import，**LinkAgent 不得重新声明这些模型**：

| 类别 | 方法 / 事件 |
|---|---|
| 请求 | `initialize`、`session/new`、`session/prompt`、`session/interrupt` |
| 通知 | `event/message_delta`、`event/task_started`、`event/task_complete`、`event/tool_begin`、`event/tool_end`、`event/token_usage` |
| 服务端请求 | `approval/request` ↔ `ApprovalResponse` |

> ⚠ 这张表是**从 RxyCode Phase 2 的 P1 抄下来的快照**。RxyCode 加了方法这里不会自动更新——靠 §1.4 的超集测试发现。

### 1.2 LinkAgent 新增的查询方法

**全部只读。协议里不存在任何 EKO 写方法**——这是产品决策 #4 的机器可验证形式。

| 方法 | 入参 | 返回 | 用在哪 |
|---|---|---|---|
| `eko/list` | `domain?`, `tier?`, `status?`, `limit`, `offset` | `EkoSummary[]` + `total` | [`L9-5`](./L9-DESKTOP-APP.md) 森林树 |
| `eko/show` | `eko_id`, `version?` | `EkoDetail` | L9-5 详情面板 |
| `eko/history` | `eko_id` | `EkoVersionRef[]` | L9-5 版本时间线 |
| `eko/retrieval_log` | `session_id`, `turn_index?`, `limit` | `RetrievalRecord[]` | [`L9-6`](./L9-DESKTOP-APP.md) 历史检索 |
| `preset/status` | — | `PresetPackStatus` | [`L9-7`](./L9-DESKTOP-APP.md) 设置页 |
| `settings/get` · `settings/set` | 见 §1.5 | — | L9-7 |

`EkoSummary` 字段：`id`、`version`、`description`、`domain`、`tier`（`community` \| `imported` \| `personal`，见 §4.6）、`status`、`use_count`。**不含 `procedure`**——列表不需要，省带宽。

`EkoDetail` = `FormalEKO` 全部 17 字段（见 §4.1）+ `tier` + `use_count`。

### 1.3 LinkAgent 新增的通知

| 事件 | 何时发 | 关键字段 |
|---|---|---|
| `event/eko_retrieved` | 每轮检索结束 | `session_id`、`turn_index`、`context`、`hits[]`、`excluded[]`、`injected_ids[]` |
| `event/eko_changed` | agent 工具改了 EKO | `eko_id`、`old_version`、`new_version`、`change_kind` |
| `event/safety_verdict` | SAG 出裁决 | `level`、`rule_name`、`explanation`、`overridable` |

`event/eko_retrieved` 的 `excluded[]` **必须逐条给出 `{eko_id, reason, human_reason}`**，不能只给统计分布。理由见 [`L9-6`](./L9-DESKTOP-APP.md)：用户要问的是"我那条经验为什么没被用上"。

`human_reason` 是人话，`reason` 是枚举名。**UI 显示 `human_reason`**，`reason` 只给日志和测试用。

### 1.4 三条契约测试

```python
def test_merged_schema_is_a_superset_of_rxycode_schema():
    """RxyCode 改协议时这个测试会红,并指出改了哪个模型的哪个字段。"""

def test_extension_methods_do_not_shadow_rxycode_methods():
    """方法名不能撞车。"""

def test_no_eko_mutation_methods_exist():
    """协议里不存在任何修改 EKO 的方法。产品决策 #4 的机器验证。"""
```

### 1.5 设置项键名

`settings/get` 与 `settings/set` 用的扁平键名。**这张表是权威**，[`L9-7`](./L9-DESKTOP-APP.md) 只引用不重复。

| 键 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `models.distillation` | `str \| null` | `null`（= 跟随执行模型） | 蒸馏模型，用户自选 |
| `retrieval.enabled` | `bool` | `true` | 检索总开关 |
| `retrieval.top_k` | `int` | `5` | — |
| `evolution.enabled` | `bool` | `true` | 反馈演化 |
| `composition.enabled` | `bool` | **`false`** | L6 依赖组合，实验性 |
| `conflict.dynamic_confidence` | `bool` | **`false`** | L6 动态置信度，实验性 |
| `preset.enabled` | `bool` | `true` | 预置包总开关 |
| `preset.disabled_domains` | `str[]` | `[]` | 按域关闭 |
| `preset.pinned_version` | `str \| null` | `null` | 钉住版本 |
| `safety.approval_timeout_s` | `int` | `60` | 超时默认拒绝 |
| `data.root` | `str` | `~/.linkagent` | **改了要重启** |

> 执行模型、API Key、工作区等**沿用 RxyCode 的设置**，不在这张表里。LinkAgent 不重做它们。

---

## §2 内部模块边界

LinkAgent 内部用 `typing.Protocol` 定义模块边界。**这样做的目的是让每一层都能被单独测试**——测 turn 编排时不需要真的调模型。

### 2.1 五个核心 Protocol

| Protocol | 定义在 | 实现 | 测试替身 |
|---|---|---|---|
| `Executor` | `bridge/types.py` | `RxyCodeExecutor` | `ScriptedExecutor`（返回预设答案） |
| `Retriever` | `eko/types.py` | `EKOEngine` | `StaticRetriever` |
| `SafetyGate` | `safety/types.py` | `SAGChecker` | `AllowAllGate` |
| `DistillationPipeline` | `distillation/types.py` | `AsyncPipeline` | `SyncPipeline`（测试里同步跑） |
| `TelemetrySink` | `runtime/types.py` | `JSONLSink` | `MemorySink` |

```python
class Executor(Protocol):
    """把一个请求交出去执行,拿回一条轨迹。

    LinkAgent 拥有外层循环,所以这一层只负责「执行」,不负责决定执行什么。
    """
    async def execute(self, request: str, *, mode: str = "build") -> Trajectory: ...
    def cancel(self) -> bool: ...
```

**每个 Protocol 必须有一个测试替身，且替身要进 CI。** 只有真实现的话，测 turn 编排就得起真模型，慢且不稳。

### 2.2 一个 turn 的调用顺序

这七步的顺序是契约，[`L2-6`](./L2-RXYCODE-BRIDGE.md) 实现，后续所有阶段都往这个骨架里填：

| # | 步骤 | 调用 | 加在哪个阶段 |
|---|---|---|---|
| 1 | 情境推断 | `infer_context(request)` | L3 |
| 2 | 检索 | `Retriever.retrieve(context)` | L3 |
| 3 | 安全裁决 | `SafetyGate.authorize(ekos, context)` | L4 |
| 4 | 上下文注入 | `install_injector(agent, provider)` | L2 |
| 5 | 执行 | `Executor.execute(request)` | L2 |
| 6 | 轨迹回收 | `Harvester.take()` | L2 |
| 7 | 蒸馏（异步） | `DistillationPipeline.submit(packet)` | L5 |

**第 7 步必须是异步的**，不能阻塞用户拿到答案。

---

## §3 RxyCode 边界

> **硬约束：RxyCode 一行都不改。** 下面每一项都是它的公开接口（`_memory` 除外，见 3.2）。

### 3.1 用到的接口（2026-07-31 实测）

| 能力 | 签名 | Grep 锚点 |
|---|---|---|
| 执行 | `async def run(self, user_input: str, mode: str = "build") -> str` | `async def run(self, user_input` |
| 构造 | `def __init__(self, model_name: Optional[str] = None)` | `def __init__(self, model_name` |
| 挂钩子 | `def register_hook(self, phase, callback, **kwargs) -> str` | `def register_hook` |
| 摘钩子 | `def unregister_hook(self, hook_id: str) -> bool` | `def unregister_hook` |
| 切会话 | `def set_session(self, session_id: str) -> str` | `def set_session` |
| 换模型 | `def switch_model(self, configured_name: str) -> dict` | `def switch_model` |
| 取消 | `def cancel(self) -> bool` | `def cancel` |
| 装审批 broker | `def set_approval_broker(broker) -> None` | `def set_approval_broker` |

### 3.2 唯一的私有依赖

**`agent._memory`** —— EKO 上下文注入要包装 `MemoryManager.get_context_for_prompt`（[`L2-3`](./L2-RXYCODE-BRIDGE.md) 的 D3 决策）。

这是私有属性，**RxyCode Phase 2 重构可能改掉它**。

> **缓解办法就是契约测试**：`test_memory_context_injection_seam_exists` 专门守这条缝。它红了说明 RxyCode 变了，需要人来适配——比运行时静默失效好得多（EKO 注入不进去，但一切看起来正常，只是效果消失了）。

### 3.3 四条已知限制

| # | 限制 | 后果 |
|---|---|---|
| ① | `run()` 只吃字符串，没有结构化输入 | EKO 上下文只能走 memory 通道 |
| ② | hooks 是观察性的，返回值不影响主流程 | **SAG 的拦截能力不能靠 hooks**，必须走 approval broker |
| ③ | 配置无构造参数，来自全局 `load_config()` | 同进程跑两套配置不安全 → [`L7`](./L7-EVAL-HARNESS.md) 的 A/B 必须子进程隔离 |
| ④ | **默认注册了绕过治理的 `skill` 工具** | 见下 |

**关于 ④（2026-08-01 实测）**：

| 位置 | 事实 |
|---|---|
| `core/agent_v2.py:1499` / `:1519` | `skill_tool` 进了默认注册列表 |
| `tools/skill_tool.py:12-17` | 搜 `~/.rxycode/skills`、`~/.claude/skills`、`~/.codex/skills`、`~/.mimocode/skills` |
| `tools/skill_tool.py:22-31` | `rglob` 匹配名字，**整个文件当字符串返回** |
| `core/agent_v2.py:1536` | `download_skill_tool` 也注册了（`risk="danger"`） |

> **模型可以调 `skill("anything")` 把任意 SKILL.md 全文塞进上下文——没有域过滤、没有安全门、没有版本、没有 provenance。不封这个口子，L3/L4/L5 的治理就是摆设。**
>
> 封法见 [`L10-4`](./L10-SKILL-INTEROP.md)：走 approval broker（因为限制 ② 说了那是唯一能拒绝的缝），不是改 RxyCode、也不是禁用工具。

### 3.4 审批 broker 的形状

```python
class ApprovalBroker(ABC):
    async def request_approval(self, request: ApprovalRequest) -> ApprovalDecision:
        ...  # 有一层 always-allow 缓存,然后调 _ask
    async def _ask(self, request: ApprovalRequest) -> ApprovalDecision: ...
```

`ApprovalRequest` 字段：`tool_name` / `args_summary` / `risk` / `approval_id`。

> ⚠ **`args_summary` 是被截断过的**（`__post_init__` 里调了 `summarize_args`）。SAG 要做内容级检查时这里拿到的可能不够，[`L4`](./L4-SAFETY-GATE.md) 会处理。

---

## §4 磁盘边界

### 4.1 `FormalEKO` 的 17 个字段

**这是所有 EKO 相关接口的基础类型。** 字段一个都不能少、不能改名。

| # | 字段 | 类型 | 默认 | 作用 |
|---:|---|---|---|---|
| 1 | `id` | `str` | — | **跨版本稳定**的身份 |
| 2 | `version` | `str` | — | 语义版本 |
| 3 | `parent_version` | `str \| None` | — | 版本链 |
| 4 | `description` | `str` | — | **检索唯一使用的文本** |
| 5 | `preconditions` | `list[str]` | `[]` | 使用前提 |
| 6 | `procedure` | `list[str]` | `[]` | **内联的过程**（不是指针） |
| 7 | `parameters` | `dict[str, Any]` | `{}` | 参数 |
| 8 | `path` | `str` | — | 域路径 |
| 9 | `dependencies` | `list[str]` | `[]` | 前置 EKO |
| 10 | `conflicts` | `list[str]` | `[]` | **对称**的互斥关系 |
| 11 | `scope` | `dict[str, list[str]]` | — | 适用范围，见 §4.2 |
| 12 | `provenance` | `list[str]` | — | 来源，**前缀是封闭集合**，见 §4.6 |
| 13 | `validation_evidence` | `list[str]` | — | 验证证据 ID |
| 14 | `feedback_evidence` | `list[str]` | `[]` | 反馈证据 ID |
| 15 | `execution_stats` | `dict[str, int]` | `{}` | 执行统计（**不影响置信度**） |
| 16 | `distillation` | `DistillationMetadata \| None` | `None` | 蒸馏元数据 |
| 17 | `status` | `Literal[...]` | — | `validated`/`active`/`deprecated`/`rejected` |

**三条不变量**（写成断言）：

1. **每个版本是不可变的完整记录**。修订 = 追加新版本，不是原地改
2. **"当前版本"由 catalog 指针决定**，不在 EKO 对象里。回滚 = 只改指针
3. **`conflicts` 必须对称**。A 列了 B，B 就得列 A

### 4.2 `scope` 的四个维度

| 维度 | 必填 | 语义 |
|---|---|---|
| `users` | ✅ | 谁的经验。`["*"]` = 共享，**只有预置包能设** |
| `domain` | ✅ | 哪个域。**精确匹配，不匹配就排除**（[`L3`](./L3-RETRIEVAL-AND-SCOPE.md) 的核心改造） |
| `languages` | ❌ | — |
| `task_types` | ❌ | — |

**两个通配符的授权来源不同，别搞混**：

| 通配 | 谁能设 | 谁不能设 |
|---|---|---|
| `domain: ["*"]` | 用户显式指定；L8 预置包构建流程 | **蒸馏路径一律拒绝** |
| `users: ["*"]` | **只有** L8 预置包构建流程 | 用户和蒸馏路径都不能 |

> 这两条规则是同一个原则的两次应用：**最强的断言必须由最可信的一方下。**

### 4.3 磁盘布局

```
~/.linkagent/
├── catalog.json                              ← 唯一可变的东西
│     {eko_id: {domain, versions[], current_version}}
├── records/{domain}/{eko_id}/{version}.json  ← 不可变，只追加
├── indices/{domain}.sqlite                   ← 纯索引，可从 records 重建
├── evidence/                                 ← L5 的证据包
├── telemetry/<date>.jsonl                    ← 检索与安全遥测
├── logs/                                     ← appserver 日志
└── runtime/                                  ← 进程态，退出即清
```

**预置包不在这里。** 它随应用分发，装载是内存合并——用户目录里只有用户自己的东西。见 [`L8-1`](./L8-PRESET-EKO-PACK.md)。

**复合键**（五段，2026-07-31 已与论文对齐）：

```
{path}/{scope_key}/{id}/{version}/{status}
```

### 4.4 遥测记录

`telemetry/<date>.jsonl` 每行一条，字段：

| 字段 | 说明 |
|---|---|
| `ts` / `session_id` / `turn_index` | 定位 |
| `context` | 推断出的 `{domain, task_type, languages}` |
| `candidates_total` | 候选总数 |
| `hits[]` | `{eko_id, score, tier}` |
| `excluded[]` | `{eko_id, reason, human_reason}`，**逐条，不是分布** |
| `injected_ids[]` | 最终注入的 |
| `safety[]` | `{rule_name, level, overridable}` |

**不记录 EKO 完整内容**，只记 id + `description` 前 80 字符。

`ExclusionReason` 枚举：`status` / `owner` / `domain` / `language` / `task_type` / `precondition` / `below_limit`。

### 4.5 预置包格式

见 [`L8-1`](./L8-PRESET-EKO-PACK.md) §3。要点：单 JSON 文件、带 `pack_version` 与 `content_sha256`、每条带 `source_url`/`source_license`/`source_commit`、id 前缀 `eko-community-`。

**四类校验失败一律整包拒绝**：hash 不符、id 前缀错、`scope.users != ["*"]`、缺 License。

### 4.6 `provenance` 前缀与 `tier`（封闭集合）

**`provenance` 是审计链的根**。它是 `list[str]`，格式全靠约定——约定不写进 validator 就一定会漂移成七种写法。

**四个合法前缀，没有第五个**：

| 前缀 | 含义 | 谁产生 | 对应 `tier` |
|---|---|---|---|
| `grounding:<packet_id>` | 蒸馏自验证过的执行轨迹 | [`L5-3`](./L5-EVIDENCE-AND-EVOLUTION.md) AED | `personal` |
| `explicit-user:<evidence_id>` | 用户显式表达的偏好 | [`L5-2`](./L5-EVIDENCE-AND-EVOLUTION.md) Mode U | `personal` |
| `user-add:<来源路径或批次>` | 用户手动导入的 Skill | [`L10-3`](./L10-SKILL-INTEROP.md) | `imported` |
| `preset:<pack_version>` | 社区预置包 | [`L8`](./L8-PRESET-EKO-PACK.md) | `community` |

**三层 `tier` 与优先级**：

| tier | 优先级 | 有该用户的执行证据吗 |
|---|---|---|
| `community` | `DEFAULT(10)` | ❌ 别人验证的 |
| `imported` | `DEFAULT(10)` | ❌ 用户放进来但没验证过 |
| `personal` | `PERSISTENT_PERSONAL(40)` | ✅ 从这个用户的行为里学到的 |

> **`imported` 为什么不是 40**：用户从网上下一个 skill，不等于这个 skill 适合他的项目。**让它压过蒸馏出来的个人经验没有依据。** 它可以随使用积累 `feedback_evidence` 并走正常修订演化，但**优先级不会自动提升**——优先级是来源的属性，不是统计的函数。

**四条校验**（pydantic validator，失败**拒绝入库**而不是 warning）：

1. 每个 `provenance` 条目必须匹配四个前缀之一
2. `provenance` 不能为空——不知道从哪来的经验不该存在
3. `tier` 必须与前缀一致（`tier=personal` 却带 `preset:` 说明有 bug）
4. 前缀后面的部分不能为空

### 4.7 导出产物格式（EKO → SKILL.md）

由 [`L10-1`](./L10-SKILL-INTEROP.md) 产生。**只读派生物，随时可重建，不是权威源。**

目录：`~/.linkagent/exports/skills/{eko_id}@{version}/SKILL.md`

**frontmatter 必备字段**：

| 字段 | 说明 |
|---|---|
| `name` | = `eko.id` |
| `source` | `{eko_id}@{version}` ← **有无这个字段决定它是不是"裸 Skill"** |
| `version` / `parent_version` / `status` / `path` / `tier` | 直接映射 |
| `distillation` | 有则带上 |
| `projection` | 固定 `eko-to-skill-v1` |
| `body_sha256` | 正文哈希，**让篡改可检测** |

**正文**：每个 EKO 字段一个 `##` 节，顺序固定（`Description` / `Preconditions` / `Procedure` / `Parameters` / `Scope` / `Dependencies` / `Conflicts` / `Provenance` / `Validation Evidence` / `Feedback Evidence` / `Execution Stats`），空字段不产生空节。

**两条不变量**：

1. **导出不改 Forest**。导出前后 `records/` 与 `catalog.json` 逐字节不变
2. **幂等**。同一个 EKO 导出两次字节相同

---

## §5 Agent 工具边界

**这是用户修改 EKO 的唯一途径**（产品决策 #4）。协议和 CLI 都没有写入口，只有这里有。

### 5.1 工具清单

| 工具 | 用户会怎么说 | 参数 | 效果 |
|---|---|---|---|
| `eko_forget` | "忘掉你记的那个类型注解的事" | `eko_id`, `reason` | status 置 `rejected`，**不删记录** |
| `eko_restore` | "把刚才让你忘的那条恢复" | `eko_id` | 撤销 forget |
| `eko_revise` | "以后别用 `os.path` 了，用 `pathlib`" | `eko_id`, `new_procedure`, `rationale` | 走内容修订，产生新版本 |
| `eko_pause_learning` | "这段时间别记东西了" | `scope?` | 暂停蒸馏，**证据照常落盘** |
| `eko_resume_learning` | — | — | 恢复 |
| `skill_import` | "把我刚下的那个 skill 加进来" | `skill_path`, `domain`, `scope?` | 反向映射入库，见 [`L10-3`](./L10-SKILL-INTEROP.md) |

> `skill_import` 的 `domain` **是必填且必须由用户确认的**，不接受模型自填——理由同 §4.2 的"最强的断言由最可信的一方下"。

### 5.2 四条硬规则

| 规则 | 为什么 |
|---|---|
| **参数里不出现** `provenance` / `validation_evidence` / `execution_stats` | 这些是系统记录的事实，不是用户意见。不是运行时校验，是签名里根本没有这个入口 |
| **每个写工具都过审批**，并在对话里回显改了什么 | 用户说的和 agent 理解的可能不一致，要给纠正机会 |
| **用实例级 `ToolOrchestrator.register` 注册** | 全局注册表会影响同进程所有 Agent |
| **`forget` 不删记录** | 版本不可变是硬不变量。置 `rejected` 后检索不到，但审计链完整 |

### 5.3 契约测试

```python
def test_tools_cannot_touch_provenance():
    """工具签名里根本没有 provenance 参数。"""
def test_write_tools_require_approval():
def test_revise_via_tool_creates_new_version_with_evidence():
def test_cli_has_no_write_commands():
def test_protocol_has_no_eko_write_methods():
```

**最后两条是同一个约束在两个边界上的投影。** 三个入口（协议、CLI、工具）里只有工具能写，另外两个都要有测试守着。

---

## §6 版本与兼容策略

| 接口 | 版本号 | 破坏性变更怎么办 |
|---|---|---|
| 协议 | `linkagent/<semver>` | 升 major；appserver 保留旧版本处理至少一个发布周期 |
| EKO schema | 跟 LinkAgent 版本 | **不允许破坏性变更**。加字段可以（给默认值），改语义要新字段名 |
| 预置包 | `pack_version`（日历版本 `YYYY.MM.N`） | 整包替换，用户可钉住旧版本 |
| RxyCode 依赖 | `pyproject.toml` 里**钉次版本区间** | 契约测试红了才升，不自动跟 |

### 为什么 EKO schema 不允许破坏性变更

因为磁盘上的 `records/` 是**不可变历史**。改字段语义意味着老记录的含义变了，而它们已经写进去了、改不动。

**唯一安全的演进方式是加字段。** 需要改语义就加新字段、老字段标 deprecated，读的时候两个都认。

---

## §7 这份文档和施工文档的关系

| 你在找什么 | 去哪 |
|---|---|
| 某个字段叫什么、什么类型 | **这里** |
| 为什么这么设计 | 对应的 L 文档 |
| 怎么一步步实现 | 对应的 L 文档的任务卡 |
| 排序和优先级的依据 | [`APPENDIX-B-PAPER-EVIDENCE.md`](./APPENDIX-B-PAPER-EVIDENCE.md) |
| 哪些代码是现成的 | [`APPENDIX-A-ASSET-INVENTORY.md`](./APPENDIX-A-ASSET-INVENTORY.md) |

**施工文档里的字段表如果和这里冲突，以这里为准，并且回去把施工文档改对。**
