# L1 · EKO 核心移植

> **前置**：[`L0-BOOTSTRAP.md`](./L0-BOOTSTRAP.md) 全部完成
> **产出**：一个能存、能取、能改版本、能回滚的 EKO 森林。**不含**检索优化、安全门、蒸馏
> **工时**：5 天
> **卡数**：6 张（L1-1 ~ L1-6）
>
> **干活前读** [`../MODEL-ASSIGNMENT.md`](../MODEL-ASSIGNMENT.md)；本文件卡多为 **owner: backend** → [`../COMPOSER-2.5-PLAYBOOK.md`](../COMPOSER-2.5-PLAYBOOK.md)。**一次只做一张卡。**

---

## §0 这份文档要解决什么

把 SkillForest 的 v2 生产栈搬进 LinkAgent，并用**契约测试**证明搬对了。

### 这是"搬"，不是"重写"

> ⚠ **最重要的一条纪律：不要"顺便优化"。**
>
> 搬过来的代码你可能觉得某处能写得更好。**不要动。** 现在的目标是让 LinkAgent 的行为和论文实验**逐字节一致**——这样才能用冻结语料验证搬对了。
>
> 想改的地方记在 `NOTES.md` 里，L3 之后再说。**L1 阶段唯一允许的改动是 import 路径和模块名。**

### 已经替你决定好的

| 决定 | 值 | 理由 |
|---|---|---|
| 只搬 v2 栈 | 见下表 | legacy 那套基于旧 `schema.EKO`，v2 完全不依赖它 |
| 模块重命名 | `eko_schema_v2.py` → `eko/schema.py` 等 | 新项目里不需要 `_v2` 后缀，它是历史包袱 |
| **不搬** `providers.py` | — | LinkAgent 走 RxyCode 的 LLM 层 |
| **不搬** `agent_runtime.py` | — | 它是 L2 的事，而且要大改 |
| **不搬** 任何 legacy 模块 | — | 见 [`APPENDIX-A §1`](./APPENDIX-A-ASSET-INVENTORY.md#-c-类--遗留不要搬1559-行) |
| 冻结语料的用途 | **只当测试装置** | 别人的偏好对新用户是噪声，而且 owner 对不上会被检索过滤掉 |

### 源 → 目标映射表

| 源（SkillForest） | 目标（LinkAgent） | 卡 |
|---|---|---|
| `src/skillforest/eko_schema_v2.py` | `src/linkagent/eko/schema.py` | L1-1 |
| `src/skillforest/exceptions.py` | `src/linkagent/errors.py` | L1-1 |
| `src/skillforest/bptree_index.py` | `src/linkagent/eko/index.py` | L1-2 |
| `src/skillforest/storage/eko_forest.py` | `src/linkagent/eko/forest.py` | L1-2 |
| `src/skillforest/conflict_resolver.py`（**只要 `Formal*`**） | `src/linkagent/eko/conflict.py` | L1-3 |
| `src/skillforest/dependency_resolver.py`（**只要 `resolve_formal`**） | `src/linkagent/eko/dependency.py` | L1-3 |
| `src/skillforest/distillation/protocol.py` | `src/linkagent/distillation/protocol.py` | L1-4 |
| `src/skillforest/safety_policy_checker.py` | `src/linkagent/safety/checker.py` | L1-4 |
| `src/skillforest/eko_engine.py` | `src/linkagent/eko/engine.py` | L1-5 |
| `src/skillforest/corpus.py` | `src/linkagent/eko/corpus.py` | L1-6 |

**顺序不能换。** `engine.py` 依赖前面全部，所以它在 L1-5。

---

## §1 任务卡

### L1-1 · 数据模型与异常

`P0` / 4h / 依赖：L0 全部

**背景**

`FormalEKO` 是整个项目的契约。搬错一个字段，后面全塌。

**涉及文件**

| 文件 | 来源 | 改法 |
|---|---|---|
| `src/linkagent/eko/schema.py` | `D:\agent-demo\SkillForest\src\skillforest\eko_schema_v2.py` | 复制，只改 docstring 里的项目名 |
| `src/linkagent/errors.py` | `D:\agent-demo\SkillForest\src\skillforest\exceptions.py` | 复制 |
| `tests/eko/test_schema.py` | `D:\agent-demo\SkillForest\tests\unit\test_eko_schema_v2.py` | 复制，改 import |

**已经替你决定好的**

- **字段一个都不许改**：不改名、不加、不删、不改类型、不改默认值
- **验证器原样保留**：`description_is_not_empty`、`evidence_ids_are_present_and_unique`、`required_text_is_not_empty`、`evidence_is_present`、`validate_history`
- `model_config = ConfigDict(extra="forbid")` **必须保留**——它挡住的是"蒸馏模型多吐了一个字段"这类静默错误
- `EKOForestSnapshot` 的 `frozen=True` 保留

**操作步骤**

1. 复制 `eko_schema_v2.py` 到 `src/linkagent/eko/schema.py`。

2. 只改这些：
   - 顶部 docstring：去掉"RQ3 distillation protocol"这类实验语境，改成说明它是 LinkAgent 的 EKO 契约
   - 去掉提到 `skillforest.schema` legacy 模型的那句（LinkAgent 里没有 legacy）

3. 复制 `exceptions.py` 到 `src/linkagent/errors.py`。

4. 复制测试，把 `from skillforest.eko_schema_v2 import` 改成 `from linkagent.eko.schema import`。

5. **加三个契约测试**（这是新增的，源仓库没有）：

```python
def test_formal_eko_has_exactly_seventeen_fields():
    """字段数锁死。

    这个测试存在的意义是:任何人加/删字段都会在这里红,强制他先来读
    APPENDIX-A §3 的字段表并更新它。EKO 的字段是跨模块契约,不是一个
    可以随手扩展的 dataclass。
    """
    assert len(FormalEKO.model_fields) == 17


def test_extra_fields_are_rejected():
    """蒸馏模型多吐一个字段必须报错,不能静默吞掉。"""


def test_field_names_match_the_documented_contract():
    """字段名逐个核对,防止重命名。"""
    expected = {
        "id", "version", "parent_version", "description", "preconditions",
        "procedure", "parameters", "path", "dependencies", "conflicts",
        "scope", "provenance", "validation_evidence", "feedback_evidence",
        "execution_stats", "distillation", "status",
    }
    assert set(FormalEKO.model_fields) == expected
```

**验收命令**

```powershell
cd "D:\agent-demo\LinkAgent"
python -m pytest tests/eko/test_schema.py -q
python -m ruff check src/linkagent/eko/schema.py src/linkagent/errors.py
python -c "from linkagent.eko.schema import FormalEKO; print(len(FormalEKO.model_fields))"
```

最后一条必须输出 `17`。

**完成判据**
- [ ] 源仓库的 `test_eko_schema_v2.py` 全部通过（改完 import 后）
- [ ] 三个新增契约测试通过
- [ ] `FormalEKO.model_fields` 正好 17 个
- [ ] `extra="forbid"` 保留且有测试
- [ ] **没有引入任何 `skillforest` 的 import**

**Commit**
```
feat(eko): port the FormalEKO contract from the research codebase

Fields are copied verbatim; a field-count and field-name test locks the
contract so a rename has to go through the documented field table first.
```

---

### L1-2 · 森林存储与索引

`P0` / 1 天 / 依赖：L1-1

**背景**

EKO 的磁盘表示。三条不变量都靠这一层实现：版本不可变、当前指针在 catalog、索引可重建。

**涉及文件**

| 文件 | 来源 | Grep 锚点 |
|---|---|---|
| `src/linkagent/eko/index.py` | `skillforest/bptree_index.py` | `class IndexEntry` / `class BPTreeIndex` |
| `src/linkagent/eko/forest.py` | `skillforest/storage/eko_forest.py` | `def _scope_key` / `class EKOForest` |
| `tests/eko/test_index.py` | `tests/unit/test_bptree_index.py` | — |
| `tests/eko/test_forest.py` | `tests/unit/test_eko_forest_snapshot.py` | — |

**已经替你决定好的**

| 项 | 值 | 理由 |
|---|---|---|
| 复合键 | **五段** `{path}/{scope_key}/{id}/{version}/{status}` | 与论文 `k_i(e)` 定义一致（2026-07-31 已在源仓库对齐） |
| `scope_key` 编码 | 排序后拼接，值里的 `/` 转义成 `%2F` | 不转义会破坏 `path` 前缀扫描 |
| 索引后端 | SQLite | 论文实测与自研 B+ 树同数量级，没必要自己写 |
| 目录布局 | `catalog.json` + `records/{domain}/{id}/{version}.json` + `indices/{domain}.sqlite` | 原样 |
| 路径来源 | **从 `Config.paths.forest` 取**，不要自己拼 | L0-4 定的规矩 |

**操作步骤**

1. 复制两个文件，改 import 路径。

2. **唯一允许的实质改动**：`EKOForest.__init__` 的 `root` 参数保持不变，但在 `linkagent` 侧新增一个构造入口：

```python
    @classmethod
    def from_config(cls, config: "Config") -> "EKOForest":
        """按 LinkAgent 配置定位森林目录。

        别的地方一律用这个,不要自己拼 ~/.linkagent/forest——L0-4 定的
        规矩是 Paths 是磁盘位置的唯一来源。
        """
        return cls(config.paths.ensure().forest)
```

3. 复制测试并改 import。

4. **加三个不变量测试**（新增）：

```python
def test_appending_a_version_never_rewrites_an_existing_record():
    """版本不可变。同一个 id@version 再写一次必须报错,不是覆盖。"""


def test_rollback_only_moves_the_catalog_pointer():
    """回滚不动任何 record 文件。

    断言方式:回滚前后对 records/ 下所有文件做哈希,必须完全相同。
    """


def test_index_can_be_rebuilt_from_records():
    """删掉 indices/ 之后能从 records/ 完全重建。

    这是「索引格式可以改」的底气所在——如果重建不出来,索引就变成了
    事实上的主数据。
    """
```

第三个测试用 `EKOForest.from_snapshot()` 实现。

**验收命令**

```powershell
cd "D:\agent-demo\LinkAgent"
python -m pytest tests/eko/test_index.py tests/eko/test_forest.py -q
python -m ruff check src/linkagent/eko/
```

**完成判据**
- [ ] 源仓库对应测试全部通过
- [ ] 三个不变量测试通过
- [ ] 复合键是五段（写测试断言分段数）
- [ ] `scope_key` 里的 `/` 被转义（写测试用含 `/` 的 scope 值验证前缀扫描仍正确）
- [ ] `from_config` 存在且被使用

**Commit**
```
feat(eko): port append-only forest storage and the SQLite ordered index

The five-part composite key matches the paper's k_i(e). Invariant tests
cover the three properties everything else relies on: versions are
immutable, rollback only moves the catalog pointer, and indices can be
rebuilt from records.
```

---

### L1-3 · 冲突裁决与依赖解析

`P0` / 1 天 / 依赖：L1-1

**背景**

这两个模块 L6 才会**启用**，但 L1 就要搬——因为 `engine.py`（L1-5）会 import 它们。

> ⚠ **这张卡最大的坑**：源文件里 **v2 和 legacy 两套实现在同一个文件里**。整个文件复制会把 `schema.py`（legacy）一起拖进来，然后你会发现 LinkAgent 里多了一套永远用不到的 EKO 模型。

**涉及文件**

| 文件 | 来源 | 只搬什么 |
|---|---|---|
| `src/linkagent/eko/conflict.py` | `skillforest/conflict_resolver.py` | **只搬** `FormalConflictResolver`、`FormalConflictCandidate`、`FormalConflictDecision`、优先级常量 |
| `src/linkagent/eko/dependency.py` | `skillforest/dependency_resolver.py` | **只搬** `resolve_formal`、`FormalResolvedPlan` |
| `tests/eko/test_conflict.py` | `tests/unit/test_formal_conflict_resolution.py` | 全部 |
| `tests/eko/test_dependency.py` | `tests/unit/test_dependency_resolver.py` | **只搬 `resolve_formal` 相关的** |

**已经替你决定好的**

- **不搬** `ConflictResolver`（legacy 类）、`resolve()`（legacy 方法）、`compute_closure`、`_compute_inherited_parameters`
- **不搬** `networkx` 依赖——只有 legacy `resolve()` 用它
- 五级优先级数值原样：`SAFETY=100` / `EXPLICIT_INSTRUCTION=80` / `TASK_CONTEXT=60` / `PERSISTENT_PERSONAL=40` / `DEFAULT=10`
- 动态置信度公式原样，但**权重要能配置**（论文 §5 自己说了固定权重未必适合所有用户）：

```
validation = (passes + 1) / (passes + fails + 2)
execution  = (success + 1) / (success + failure + 2)
user       = (support + 2) / (support + opposition + 4)
total      = 0.30 * applicability + 0.30 * validation + 0.20 * execution + 0.20 * user
```

- **完全同分必须请求用户确认**，不许按列表顺序隐式选一个。这是论文 RQ4 明确验证过的行为（2 组同分案例全部正确请求确认）

**操作步骤**

1. 新建 `conflict.py`，**只复制** `Formal` 前缀的类和优先级定义。复制完检查：文件里不应该出现 `from skillforest.schema import` 或任何 `EKO`（legacy 类名）。

2. 权重提成一个 frozen dataclass：

```python
@dataclass(frozen=True)
class ConfidenceWeights:
    """动态综合置信度的权重。

    论文 §5 的局限里明说「综合置信度的固定权重未必适合所有用户或任务」,
    所以这里做成可配置。默认值就是论文用的那组。
    """

    applicability: float = 0.30
    validation: float = 0.30
    execution: float = 0.20
    user: float = 0.20
```

`FormalConflictResolver.__init__` 接受它，默认用论文的值。

3. 新建 `dependency.py`，只复制 `resolve_formal` 和 `FormalResolvedPlan`。

4. 搬测试，**只搬 v2 相关的**。

5. 加两个测试（新增）：

```python
def test_complete_tie_requests_confirmation_instead_of_picking_first():
    """完全同分不许隐式选第一个。

    论文 RQ4 的 2 组同分案例都必须请求确认——这是「不许假装有答案」的
    设计立场,不是可以优化掉的开销。
    """


def test_confidence_weights_are_configurable():
    """权重可配置。论文 §5 自己说固定权重未必适合所有用户。"""
```

**验收命令**

```powershell
cd "D:\agent-demo\LinkAgent"
python -m pytest tests/eko/test_conflict.py tests/eko/test_dependency.py -q
python -m ruff check src/linkagent/eko/
python -c "import linkagent.eko.conflict, linkagent.eko.dependency; print('ok')"
```

**再加一条硬检查**——确认没把 legacy 拖进来：

```powershell
Select-String -Path "src\linkagent\**\*.py" -Pattern "skillforest|networkx|procedure_or_tool_pointer"
```

**必须零输出。**

**完成判据**
- [ ] v2 相关测试全部通过
- [ ] 两个新增测试通过
- [ ] **`Select-String` 检查零输出**（没有 legacy 残留）
- [ ] `networkx` 不在依赖里
- [ ] 权重可配置且默认值是论文的那组

**Commit**
```
feat(eko): port formal conflict resolution and dependency composition

Only the v2 code paths come over; the legacy schema.EKO resolver and its
networkx-backed closure stay behind. Confidence weights become
configurable because the paper flags the fixed weighting as a limitation.
```

---

### L1-4 · 证据协议与安全规则

`P0` / 4h / 依赖：L1-1

**背景**

`engine.py` 的 `promote()` 要调这两个东西：证据准入检查（grounding）和安全检查（SAG）。所以它们得先到位。

**这张卡只搬代码，不接线。** SAG 真正接进执行流程是 L4 的事。

**涉及文件**

| 文件 | 来源 |
|---|---|
| `src/linkagent/distillation/protocol.py` | `skillforest/distillation/protocol.py` |
| `src/linkagent/safety/checker.py` | `skillforest/safety_policy_checker.py` |
| `tests/distillation/test_protocol.py` | `tests/unit/test_rq3_distillation_protocol.py` |
| `tests/safety/test_checker.py` | `tests/unit/test_rq3_sag_rules.py` |

**已经替你决定好的**

**证据准入规则原样保留**，这是防垃圾进经验库的第一道闸：

| 模式 | 准入条件 |
|---|---|
| Mode U | 显式证据（`explicit_preference` / `correction` / `revocation`）**一条即可**；隐式证据需 **≥2 个不同 `session_id`** |
| AED | **必须含** `verified_success` 或 `verified_correction` |

**SAG 三档语义原样保留**：`FULL` → 阻断且不可覆盖；`PARTIAL` → 需用户确认；`NONE` → 放行。

- **不要**现在就改 SAG 的规则表。它现在的规则是通用危险内容（武器/毒品/恶意软件/密钥泄漏等），对编码场景确实不够贴切，但**改规则是 L4 的事**，L1 只管搬对
- **不要**引入 LLM 语义冲突检测（`conflict_detection.py`）。默认不启用

**操作步骤**

1. 复制两个文件，改 import。

2. 复制测试，改 import。

3. 加两个测试（新增）：

```python
def test_implicit_mode_u_evidence_needs_two_distinct_sessions():
    """单次隐式偏好不能形成 EKO。

    这是防「用户随口说一句就被记成永久偏好」的闸。同一个 session 里说
    三遍也不算——必须是不同会话里重复出现。
    """


def test_aed_without_verified_outcome_is_rejected():
    """没有验证过的轨迹不能进经验库。

    AED 的全部价值前提就是「这条经验被证明有效过」。放宽这一条,经验库
    会迅速被失败轨迹污染。
    """
```

**验收命令**

```powershell
cd "D:\agent-demo\LinkAgent"
python -m pytest tests/distillation/test_protocol.py tests/safety/test_checker.py -q
python -m ruff check src/linkagent/distillation/ src/linkagent/safety/
```

**完成判据**
- [ ] 源测试全部通过
- [ ] 两个新增准入测试通过
- [ ] SAG 三档语义有测试覆盖
- [ ] 没有引入 `conflict_detection.py`

**Commit**
```
feat: port the evidence grounding protocol and the code-only safety rules

Grounding is the first gate keeping noise out of the experience store:
implicit preferences need two distinct sessions, and AED traces need a
verified outcome. Rules are copied as-is; retuning them for coding tasks
belongs to L4.
```

---

### L1-5 · EKO 引擎

`P0` / 1.5 天 / 依赖：L1-2、L1-3、L1-4

**背景**

`eko_engine.py` 是 888 行的核心，依赖前面全部四张卡。

**这是 L1 里最大的一张卡。** 如果做到一半发现方向不对，按 Playbook C8 停下来。

**涉及文件**

| 文件 | 来源 | Grep 锚点 |
|---|---|---|
| `src/linkagent/eko/engine.py` | `skillforest/eko_engine.py` | `class EKOEngine` |
| `tests/eko/test_engine.py` | `tests/unit/test_eko_engine.py` | — |

**已经替你决定好的**

- **整个文件搬过来，一行逻辑都不改**。只改 import 路径
- **特别是 `_retrieval_text` 和 `_matches_context` 不要动**——它们是 L3 的改造目标，L1 阶段必须保持和源仓库一致，否则没法用冻结语料验证搬对了
- import 映射：

| 源 | 目标 |
|---|---|
| `from skillforest.conflict_resolver import ...` | `from linkagent.eko.conflict import ...` |
| `from skillforest.dependency_resolver import ...` | `from linkagent.eko.dependency import ...` |
| `from skillforest.distillation.protocol import ...` | `from linkagent.distillation.protocol import ...` |
| `from skillforest.eko_schema_v2 import ...` | `from linkagent.eko.schema import ...` |
| `from skillforest.safety_policy_checker import ...` | `from linkagent.safety.checker import ...` |
| `from skillforest.storage.eko_forest import ...` | `from linkagent.eko.forest import ...` |

**操作步骤**

1. 复制文件，逐条改 import。

2. **确认公开 API 齐全**。这些方法后面都会用到，缺一个都要回头补：

| 方法 | 用在哪 |
|---|---|
| `promote` | L5 蒸馏 |
| `search` / `retrieve` / `search_flat` | L3 检索 |
| `record_feedback` | L5 反馈演化 |
| `revise_content` | L5 |
| `upsert_user_experience` | L5 Mode U |
| `revise_dependencies` / `revise_conflict_pair` | L6 |
| `record_evidence` | L5 |
| `compose` | L6 |
| `resolve_conflict` | L6 |
| `authorize_activation` | L4 安全门 |
| `rollback` | L5 |

3. 复制测试并改 import。

4. **加一个 API 完整性测试**（新增）：

```python
def test_engine_exposes_the_full_public_api():
    """公开方法齐全。

    L2–L7 每一层都依赖其中几个。缺一个的话,要等到那一层才发现,而那时
    已经在写集成代码了。在这里一次性锁住。
    """
    expected = {
        "promote", "retrieve", "search", "search_flat", "record_feedback",
        "revise_content", "upsert_user_experience", "revise_dependencies",
        "revise_conflict_pair", "record_evidence", "compose",
        "resolve_conflict", "authorize_activation", "rollback",
    }
    actual = {name for name in dir(EKOEngine) if not name.startswith("_")}
    assert expected <= actual
```

**验收命令**

```powershell
cd "D:\agent-demo\LinkAgent"
python -m pytest tests/eko -q
python -m ruff check src/linkagent/
Select-String -Path "src\linkagent\**\*.py" -Pattern "skillforest"
```

最后一条**必须零输出**。

**完成判据**
- [ ] 源仓库 `test_eko_engine.py` 全部通过
- [ ] API 完整性测试通过
- [ ] 无 `skillforest` 残留 import
- [ ] `_retrieval_text` 和 `_matches_context` 与源仓库**逐字节相同**（L3 才改）
- [ ] `ruff` 零输出

**Commit**
```
feat(eko): port the EKO engine

Logic is copied verbatim so the frozen corpus can verify the port; only
imports change. Retrieval text and scope matching are deliberately left
untouched here — L3 owns those changes.
```

---

### L1-6 · 冻结语料契约测试

`P0` / 1 天 / 依赖：L1-5

**背景**

**这张卡是 L1 的意义所在。** 前面五张卡都是"复制粘贴改 import"，这一张才回答：**搬对了吗？**

方法：拿论文的冻结语料（304 EKO / 429 版本，带哈希），在 LinkAgent 里加载，跑和论文相同的检索查询，**结果必须一致**。

**涉及文件**

| 文件 | 说明 |
|---|---|
| `src/linkagent/eko/corpus.py` | 从 `skillforest/corpus.py` 搬 |
| `tests/fixtures/eko_corpus_v2/` | **复制**冻结语料（不是引用源仓库路径） |
| `tests/eko/test_corpus_contract.py` | 新建，核心 |

**已经替你决定好的**

- 语料**复制进 LinkAgent 仓库**，不要用绝对路径引用 SkillForest。理由：CI 里没有 SkillForest；而且语料是不可变的，复制不会有同步问题
- 语料只当**测试装置**，**绝不预置给用户**。那 304 条是别人的个人偏好，对新用户是负资产，而且 `scope.users` 对不上根本检索不到。预置给用户的是另一套东西——社区顶层 EKO，见 [`L8-PRESET-EKO-PACK.md`](./L8-PRESET-EKO-PACK.md)
- 语料路径：`tests/fixtures/eko_corpus_v2/`
- 如果语料太大不适合进 git，改用 git-lfs 或在 CI 里跳过这组测试——**但要在文档里写明**

**操作步骤**

1. 先看语料多大：

```powershell
$src = "D:\agent-demo\SkillForest\artifacts\releases\eko_corpus_v2"
"{0:N2} MB" -f ((Get-ChildItem $src -Recurse -File | Measure-Object Length -Sum).Sum / 1MB)
(Get-ChildItem $src -Recurse -File).Count
```

> 超过 50 MB 就**停下来报告**，讨论用 lfs 还是抽样。

2. 复制语料到 `tests/fixtures/eko_corpus_v2/`。

3. 搬 `corpus.py`。

4. `tests/eko/test_corpus_contract.py` —— **这是 L1 的验收核心**：

```python
"""冻结语料契约测试。

L1 的全部意义:证明搬过来的引擎和论文实验行为一致。

方法是拿论文冻结的 EKO Corpus v2(304 个当前 EKO / 429 条不可变版本,
manifest 里带 sha256),在 LinkAgent 里加载并跑相同的操作,结果必须一致。

这组测试**不许改宽松**。它红了只有两种可能:搬错了,或者你在 L1 阶段
动了不该动的逻辑。
"""


def test_corpus_loads_with_expected_shape():
    """304 个当前 EKO,254 active + 50 validated,429 条版本记录。"""


def test_corpus_hashes_match_the_manifest():
    """active_ekos_sha256 / formal_versions_sha256 与 manifest 一致。

    哈希对不上说明语料在复制过程中被改动了(最常见的原因是编辑器改了
    行尾或者 BOM)。
    """


def test_every_record_round_trips_through_the_schema():
    """429 条版本记录全部能用 FormalEKO 解析,且 model_dump 后一致。

    这是「字段搬对了」的最强证据——extra="forbid" 会让任何字段缺失或
    多余当场报错。
    """


def test_snapshot_export_is_deterministic():
    """导出快照两次,canonical_sha256 相同。"""


def test_retrieval_on_frozen_corpus_is_stable():
    """固定查询的检索结果稳定。

    不比对论文的具体数字(L3 会改检索语义,那时这个断言会失效),只比对
    「同一份语料 + 同一个查询 = 同一个结果」,把它作为 L3 改造的对照基线。

    实现:跑一组固定查询,把结果 id 列表写进 tests/fixtures/retrieval_baseline.json,
    后续每次都比对。L3 改检索时这个基线会变——那时**显式更新它并在
    commit message 里说明为什么**,不许静默覆盖。
    """
```

5. 生成检索基线文件，提交进 git。

**验收命令**

```powershell
cd "D:\agent-demo\LinkAgent"
python -m pytest tests/eko/test_corpus_contract.py -q
python -m pytest -q
python -m ruff check .
```

**完成判据**
- [ ] 语料加载出 304 个当前 EKO、429 条版本记录
- [ ] manifest 哈希对得上
- [ ] 429 条记录全部能 round-trip
- [ ] 检索基线文件已生成并提交
- [ ] **全量测试绿**

**Commit**
```
test(eko): verify the port against the frozen research corpus

304 EKOs and 429 immutable versions round-trip through the ported schema
and hash-match the manifest, which is the evidence that L1 copied the
engine correctly rather than approximately. The retrieval baseline is the
control for the L3 scope-semantics change.
```

---

## §2 L1 出口检查

```powershell
cd "D:\agent-demo\LinkAgent"
python -m ruff check .
python -m pytest -q
Select-String -Path "src\linkagent\**\*.py" -Pattern "skillforest|networkx|procedure_or_tool_pointer"
python -c "from linkagent.eko.schema import FormalEKO; assert len(FormalEKO.model_fields) == 17; print('contract ok')"
```

**L1 完成的定义：**
- 全部命令绿，`Select-String` **零输出**
- 冻结语料的 304 EKO / 429 版本能加载、哈希对得上、全部 round-trip
- 检索基线已落盘，作为 L3 的对照
- `_retrieval_text` / `_matches_context` 与源仓库逐字节相同
- 六个 commit，一张卡一个

**⚠ L1 之后仍然没有任何可用功能。** 有了森林、能存能取，但没接 RxyCode（L2）、检索还是老语义（L3）、安全门没接线（L4）、不会自己产生 EKO（L5）。

**下一步**：[`L2-RXYCODE-BRIDGE.md`](./L2-RXYCODE-BRIDGE.md)
