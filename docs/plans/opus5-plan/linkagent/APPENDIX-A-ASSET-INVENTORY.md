# 附录 A · 可复用资产清单

> **LinkAgent 不是从零写的。** 这份清单说明：哪些代码已经存在、在哪、什么状态、能不能直接搬。
> 施工文档里凡是说"搬过来"的，具体搬什么看这里。
>
> **两个来源仓库**：
> - `D:\agent-demo\SkillForest` —— EKO 研究代码（共 5,940 行 Python）
> - `D:\agent-demo\RxyCode\RxyCode1_1_0` —— Agent 执行底座（pip 依赖，不改）
>
> **核对日期**：2026-07-31。行数为实测值。
> **提醒**：行号会漂移，定位一律用 Grep 锚点（见 [`../COMPOSER-2.5-PLAYBOOK.md`](../COMPOSER-2.5-PLAYBOOK.md) 规则 C3）。

---

## §1 SkillForest 三层分类

`src/skillforest/` 共 36 个模块。按"能不能搬进 LinkAgent"分成三类：

### 🟢 A 类 · 直接搬（v2 生产栈，2,957 行）

这些是论文实验实际跑的那条路径，测试覆盖充分，**互相之间闭环，不依赖 `experiments/`**。

| 模块 | 行数 | 干什么 | 搬到 LinkAgent 的 |
|---|---:|---|---|
| `eko_schema_v2.py` | 152 | `FormalEKO`（17 字段）/ `CandidateEKO` / `DistillationMetadata` / `EKOForestSnapshot` | `linkagent/eko/schema.py` |
| `eko_engine.py` | 888 | **核心引擎**：晋升、检索、修订、冲突、组合、SAG 授权、回滚 | `linkagent/eko/engine.py` |
| `storage/eko_forest.py` | 218 | 追加式森林存储（records + catalog + indices） | `linkagent/eko/forest.py` |
| `bptree_index.py` | 447 | SQLite 有序复合键索引 + 冲突判决缓存 + 置信度证据表 | `linkagent/eko/index.py` |
| `conflict_resolver.py` | 395 | 五级优先级 + 动态综合置信度（**只搬 `FormalConflictResolver`**） | `linkagent/eko/conflict.py` |
| `dependency_resolver.py` | 152 | PCDR（**只搬 `resolve_formal`**） | `linkagent/eko/dependency.py` |
| `safety_policy_checker.py` | 127 | 纯代码 SAG：FULL/PARTIAL/NONE 规则 | `linkagent/safety/checker.py` |
| `runtime_types.py` | 252 | Runtime 公共类型 + `ModelPlanner`/`ToolExecutor`/`RuntimeJournal` Protocol | `linkagent/runtime/types.py` |
| `exceptions.py` | 61 | 分类异常层次 | `linkagent/errors.py` |
| `telemetry.py` | 67 | 运行遥测收集 | `linkagent/runtime/telemetry.py` |
| `corpus.py` | 120 | 语料冻结与导出 | `linkagent/eko/corpus.py` |
| `export/skill_projection.py` | 204 | **出站映射**：`FormalEKO` → SKILL.md（字段映射表 + frontmatter + YAML 序列化） | `linkagent/export/skill_projection.py` |
| **`distillation/` 全包** | 651 | 见 §2 | `linkagent/distillation/` |

> **`export/skill_projection.py` 搬的时候只改三处**（详见 [`L10-1`](./L10-SKILL-INTEROP.md)）：换包名、frontmatter 加 `tier` 和 `body_sha256`、删掉三个 `corpus_*` 函数（那是论文冻结语料的装置，LinkAgent 走 `EKOForest` 读）。
>
> `_FIELD_SECTION_ORDER` / `_render_section` / `_dump_yaml_mapping` / `_yaml_scalar` **原样搬**——纯函数、已验证、零依赖。

### 🟡 B 类 · 参考实现，需要改写

| 模块 | 行数 | 为什么不能直接搬 |
|---|---:|---|
| `agent_runtime.py` | 1053 | 完整 turn 管线（检索→组合→冲突→规划→SAG→执行→反馈）。**结构对，但它的 planner/executor 是为沙箱实验写的**。LinkAgent 要把它接到 RxyCode 上，见 [`L2-RXYCODE-BRIDGE.md`](./L2-RXYCODE-BRIDGE.md) |
| `sandbox_tool_executor.py` | 247 | SQLite 沙箱执行器。LinkAgent 用 RxyCode 的真实工具，这个只在测试里留着当 fake |
| `providers.py` | 71 | httpx 裸 OpenAI 客户端。LinkAgent 走 RxyCode 的 LLM 层，不要这个 |
| `conflict_detection.py` | 294 | LLM 语义冲突检测。**默认不启用**（论文自己的数据：真冲突占比极低，LLM 过度预测） |

### 🔴 C 类 · 遗留，不要搬（1,559 行）

这些基于旧的 `schema.EKO`（含 `procedure_or_tool_pointer`），是 v2 之前的实现。**v2 生产路径完全不依赖它们。**

`schema.py`(174) · `planner.py`(263) · `semantic_router.py`(70) · `confidence.py`(100) · `lifecycle.py`(86) · `namespace.py`(104) · `user_interaction_reflection.py`(338) · `experience_distillation.py`(104) · `conflict_resolver.ConflictResolver`（同文件里的 legacy 类） · `dependency_resolver.resolve()`（legacy 方法）

> ⚠ **陷阱**：`conflict_resolver.py` 和 `dependency_resolver.py` 里 **v2 和 legacy 两套实现共存**。搬的时候只搬 `Formal*` 前缀的那套和 `resolve_formal`，别把整个文件复制过去——legacy 那套会把 `schema.py` 一起拖进来。

---

## §2 蒸馏子系统（全部已实现，无 stub）

`distillation/` 共 651 行，**从证据到 EKO 的完整链路都能跑**。

| 模块 | 行数 | 状态 | 说明 |
|---|---:|---|---|
| `protocol.py` | 78 | ✅ 完整 | `EvidencePacket` / `EvidenceRecord` / `GroundingResult` + `evidence_is_grounded()` |
| `runner.py` | 108 | ✅ 完整 | `CandidateGenerator`：LLM → `CandidateEKO` JSON，含一次修复重试 |
| `promotion.py` | 26 | ✅ 完整 | 薄包装 `EKOEngine.promote` |
| `batch.py` | 113 | ✅ 完整 | `DistillationBatchRunner`，JSONL 断点续跑 |
| `prompt_loader.py` | 30 | ✅ 完整 | 加载冻结 prompt（`prompts/eko_distillation/v1/`） |
| `mode_u_evidence.py` | 117 | ✅ 完整 | Mode U 证据构建（RecoReact 适配） |
| `aed_evidence.py` | 54 | ✅ 完整 | AED 轨迹 → EvidencePacket，**丢弃隐藏推理** |
| `bfcl_aed.py` | 83 | 🔬 实验适配 | BFCL 数据集专用，LinkAgent 要换成 RxyCode 轨迹 |
| `aed_tool_task.py` | 41 | 🔬 实验 | 单个种子任务 |
| `aed_controlled_suite.py` | 101 | 🔬 实验 | 6 域 × 16 任务受控套件 |

### 证据准入规则（`protocol.py` 的 `evidence_is_grounded`）

这是**防止垃圾进入经验库的第一道闸**，LinkAgent 必须原样保留：

| 模式 | 准入条件 |
|---|---|
| **Mode U** | 显式证据（`explicit_preference` / `correction` / `revocation`）**一条即可**；隐式证据（`implicit_preference`）需 **≥2 个不同 `session_id`** |
| **AED** | 必须含 `verified_success` 或 `verified_correction`——**没有验证过的轨迹不能进** |

---

## §3 EKO 数据模型（`FormalEKO` 17 字段）

搬代码时这张表是契约，字段一个都不能少也不能改名。

| # | 字段 | 类型 | 默认 | 作用 |
|---:|---|---|---|---|
| 1 | `id` | `str` | — | **跨版本稳定**的身份 |
| 2 | `version` | `str` | — | 语义版本，每次修订递增 |
| 3 | `parent_version` | `str \| None` | — | 版本链 |
| 4 | `description` | `str` | — | **检索唯一使用的文本** |
| 5 | `preconditions` | `list[str]` | `[]` | 使用前提 |
| 6 | `procedure` | `list[str]` | `[]` | **内联的过程**（不是指针） |
| 7 | `parameters` | `dict[str, Any]` | `{}` | 参数 |
| 8 | `path` | `str` | — | 域路径，决定落在哪棵树 |
| 9 | `dependencies` | `list[str]` | `[]` | 前置 EKO |
| 10 | `conflicts` | `list[str]` | `[]` | **对称**的互斥关系 |
| 11 | `scope` | `dict[str, list[str]]` | — | 适用范围（用户/任务类型等） |
| 12 | `provenance` | `list[str]` | — | 来源 |
| 13 | `validation_evidence` | `list[str]` | — | 验证证据 ID |
| 14 | `feedback_evidence` | `list[str]` | `[]` | 反馈证据 ID |
| 15 | `execution_stats` | `dict[str, int]` | `{}` | 执行统计（**不影响置信度**） |
| 16 | `distillation` | `DistillationMetadata \| None` | `None` | 蒸馏元数据（模型/prompt 版本/哈希） |
| 17 | `status` | `Literal[...]` | — | `validated` / `active` / `deprecated` / `rejected` |

**三条不变量**（搬代码时写成断言）：

1. **每个版本是不可变的完整记录**。修订 = 追加新版本，不是原地改
2. **"当前版本"由 catalog 指针决定**，不在 EKO 对象里。回滚 = 只改指针
3. **`conflicts` 必须对称**。A 列了 B，B 就得列 A

---

## §4 磁盘布局（`storage/eko_forest.py`）

```
{root}/
├── catalog.json                              ← 唯一可变的东西
│     {eko_id: {domain, versions[], current_version}}
├── records/{domain}/{eko_id}/{version}.json  ← 不可变，只追加
└── indices/{domain}.sqlite                   ← 纯索引，可从 records 重建
```

**复合键**（五段，2026-07-31 已与论文对齐）：

```
{path}/{scope_key}/{id}/{version}/{status}
```

`scope_key` 由 `_scope_key()` 确定性序列化，值里的 `/` 转义成 `%2F`，保证 `path` 前缀扫描不被破坏。

**关键性质：索引可从 records 完全重建**（`EKOForest.from_snapshot()`）。所以索引格式改动不影响已有数据——这是 LinkAgent 敢改索引实现的底气。

---

## §5 现成的冻结语料

`D:\agent-demo\SkillForest\artifacts\releases\eko_corpus_v2\`

| 项 | 值 |
|---|---|
| 当前 EKO 数 | **304**（Mode U 178 + AED 126） |
| 状态分布 | 254 active + 50 validated |
| 不可变版本记录 | **429** |
| 完整性 | `manifest.json` 里有 `active_ekos_sha256` / `formal_versions_sha256` |

**LinkAgent 的用法**：当作**契约测试的固定装置**，不是当作用户数据。真实用户的 EKO 由 LinkAgent 自己蒸馏产生。

好处是能验证"搬过来的引擎行为和论文一致"——同一份语料、同一个查询，应该得到同样的检索结果。

---

## §6 RxyCode 侧的接入点

LinkAgent 通过 `pip install rxycode` 依赖，**不 fork 源码**。以下是可用的扩展缝。

### 6.1 能直接用的（有公开 API）

| 能力 | 位置 | Grep 锚点 | 说明 |
|---|---|---|---|
| Agent 主入口 | `core/agent_v2.py` | `def run(self, user_input` | `run(user_input, mode="build")` |
| 生命周期钩子 | `core/agent_v2.py` | `def register_hook` | **实例级**，LinkAgent 的主要挂载点 |
| 工具注册 | `tools/registry.py` | `class ToolRegistry` | 有 `register/remove`，但注册表是**模块级全局** |
| 实例级工具注册 | `execution/tool_orchestrator.py` | `def register` | **实例级**，比全局 registry 干净 |
| 工具风险登记 | `core/safety/policy.py` | `def register_tool_risk` | 可给自定义工具定风险等级 |
| 审批 broker | `core/safety/approval.py` | `def set_approval_broker` | 可换成 LinkAgent 自己的实现 |
| Prompt 覆盖 | `core/prompts/registry.py` | `def register` | 可运行时替换模板（**全局单例，注意串扰**） |
| 记忆上下文 | `memory/manager.py` | `def get_context_for_prompt` | **EKO 注入的关键点**，见 L2 |

### 6.2 硬编码，改不了（除非 fork）

| 项 | 位置 | 影响 |
|---|---|---|
| LangGraph 拓扑 | `core/graph.py` 的 `build_graph` | 无插件 API，加节点必须 fork |
| 内置工具列表 | `core/agent_v2.py` 的 `_register_tools` | 硬编码 import；外部工具要在 Agent 构造**之前**注册 |
| 配置来源 | `config/settings.py` 的 `load_config` | 读 YAML 文件，**没有 `AgentV2(config=...)` 构造参数** |
| per-call 换模型 | — | 只有实例级 `switch_model`，没有干净的单次调用换模型接口 |
| **`skill` 工具默认注册** | `core/agent_v2.py:1499,1519` + `tools/skill_tool.py` | ⚠ **治理漏洞**，见下 |

> ⚠ **`skill(name)` 能绕过 LinkAgent 的全部治理。** `tools/skill_tool.py:12-31` 在 `~/.rxycode/skills`、`~/.claude/skills`、`~/.codex/skills`、`~/.mimocode/skills` 四个目录 `rglob` 任意 `SKILL.md` 并**整段返回**——没有域过滤、没有安全门、没有版本、没有 provenance。`core/agent_v2.py:1536` 的 `download_skill_tool` 更进一步，能从 URL 装。
>
> 因为不能改 RxyCode，**封法是在 approval broker 上加闸**（唯一能返回"拒绝"的缝）：见 [`L10-4`](./L10-SKILL-INTEROP.md)。这张卡的优先级是 P0。

### 6.3 ⚠ 全局单例清单（决定进程隔离策略）

**这是 LinkAgent 架构上最重要的一张表。** 以下都是**进程级共享**的：

| 单例 | 位置 | 后果 |
|---|---|---|
| 工具注册表 | `tools/registry.py` 的 `registry = ToolRegistry()` | 两个 Agent 共用一张表 |
| 精确缓存 | `cache/precise_cache.py` 的 `precise_cache` | 共享（有 namespace 可部分隔离） |
| 语义缓存 | `cache/semantic_cache.py` 的 `semantic_cache` | 共享 |
| Prompt 注册表 | `core/prompts/registry.py` 的 `_registry` | 一方覆盖模板会影响另一方 |
| TUI 实例 | `utils/tui.py` 的 `_tui_instance` | 进程级 |
| Token 统计 | `utils/streaming.py` 的 `token_stats` | 计数混在一起 |
| 审批 broker | `core/safety/approval.py` 的 `_broker` | 全局 |
| 提问 broker | `core/question.py` 的 `_broker` | 全局 |
| 审计日志 | `core/safety/audit.py` 的 `_default_logger` | 全局 |
| API 层 Agent | `api_server.py` 的 `_state["agent"]` | API 模式硬编码单 Agent |

**结论：同一进程里跑两个配置不同的 Agent 是不安全的。** LinkAgent 的隔离策略见 [`L2-RXYCODE-BRIDGE.md`](./L2-RXYCODE-BRIDGE.md)。

### 6.4 RxyCode 的包信息

| 项 | 值 |
|---|---|
| PyPI 名 | `rxycode` |
| 版本 | `1.2.3` |
| Python | `>=3.10` |
| 导入路径 | `from RxyCode.RxyCode1_1_0.core.agent_v2 import AgentV2` |
| 命令行 | `rxycode` |

```powershell
pip install -e D:\agent-demo\RxyCode\RxyCode1_1_0
```

> ⚠ SkillForest 要求 Python **>=3.12**，RxyCode 是 **>=3.10**。LinkAgent 取交集：**>=3.12**。

---

## §7 依赖对照

| | SkillForest | RxyCode | LinkAgent 取值 |
|---|---|---|---|
| Python | >=3.12 | >=3.10 | **>=3.12** |
| 数据模型 | `pydantic>=2.0` | （依赖 langchain 系） | `pydantic>=2.0` |
| HTTP | `httpx[socks]>=0.25` | — | 走 RxyCode 的 LLM 层，**不直接用** |
| 校验 | `jsonschema>=4.23` | — | 保留 |
| 数值 | `numpy>=1.24` | — | 保留（TF-IDF 用） |
| 索引 | SQLite（标准库） | — | 保留 |
| 图算法 | `networkx`（仅 legacy） | — | **不要**（只有 C 类代码用） |

---

## §8 测试资产

SkillForest 的 `tests/unit/` 有 91 个测试文件。**能直接搬的**（对应 A 类模块）：

`test_eko_schema_v2.py` · `test_eko_engine.py` · `test_eko_forest_snapshot.py` · `test_bptree_index.py` · `test_formal_conflict_resolution.py` · `test_dependency_resolver.py` · `test_safety_gated_activation.py` · `test_distillation_batch.py` · `test_rq3_distillation_protocol.py` · `test_rq3_promotion.py` · `test_rq3_sag_rules.py` · `test_rq3_candidate_generator.py` · `test_mode_u_evidence_builder.py` · `test_aed_evidence_builder.py` · `test_corpus_freeze.py`

**不要搬**的：所有 `test_rq[1-6]_*`、`test_end_to_end_*`、`test_*_experiment.py` —— 它们验证的是论文实验协议，不是库行为。

> ⚠ 已知：SkillForest 主干上有 **6 个测试是红的**（`test_feedback_rollback_experiment` / `test_plan2_public_package` ×2 / `test_rq1_current_artifacts` ×2 / `test_safety_activation_experiment`）。全部属于"不要搬"的实验类，与库代码无关。搬代码时不用管。
