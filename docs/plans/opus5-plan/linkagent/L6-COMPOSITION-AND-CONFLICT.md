# L6 · 依赖组合与冲突裁决（默认关闭）

> **前置**：[`L5-EVIDENCE-AND-EVOLUTION.md`](./L5-EVIDENCE-AND-EVOLUTION.md) 完成
> **⚠ 建议先做 [`L7-EVAL-HARNESS.md`](./L7-EVAL-HARNESS.md)**，理由见 §0
> **产出**：两个能力可用但**默认关闭**，等有证据再按域打开
> **工时**：4 天
> **卡数**：4 张（L6-1 ~ L6-4）
>
> **干活前读** [`../COMPOSER-2.5-PLAYBOOK.md`](../COMPOSER-2.5-PLAYBOOK.md) §2。

---

## §0 为什么排最后，而且默认关闭

端到端消融（依据见 [`APPENDIX-B §2`](./APPENDIX-B-PAPER-EVIDENCE.md#2-逐模块消融rq2-施工顺序的直接依据)）：

| 条件 | Overall | 相对 Full 的变化（配对 95% CI） |
|---|---:|---:|
| Full | 77.54% | — |
| w/o Dependency Composition | **78.00%** | +0.46 pp `[−0.73, +1.65]` ← 跨 0 |
| w/o Conflict Resolution | **77.88%** | +0.35 pp `[−0.69, +1.42]` ← 跨 0 |

**移除这两个模块，点估计反而更高。** 置信区间跨 0，所以严格说是"无显著差异"，但**至少可以确定它们没有正收益**。

### 那为什么还要做

因为组件级测试证明它们的目标能力很强：

| 模块 | 组件级结果 |
|---|---|
| 依赖组合 | 依赖完整计划率 16.67% → **100%**；识别出 2 个不可用依赖和 1 个循环依赖 |
| 冲突裁决 | 裁决准确率 40% → **100%**；不必要确认率 30.77% → **0%** |

**矛盾的解释在论文的实验设定里**：

> 「部分依赖与冲突案例采用**受控关系**」（论文 §5 Limitations）

**依赖组合的 100% 是在"EKO 里真的有 `dependencies` 字段"的前提下拿到的。** 而冻结语料里这个字段**全部为空**——论文的依赖关系是为那个实验人工写进森林工作副本的。

### 结论

> **代码搬过来（它们已经写好了），但默认关闭。**
>
> 打开的条件是：**某个域里真的积累出了带依赖关系的 EKO**，并且 L7 的评测证明打开之后有收益。
>
> 在那之前打开，只是白花 token 和延迟。

### 为什么建议先做 L7

L6 是**唯一一个"做了可能没用"的阶段**。没有评测就打开它，你无法判断它有没有帮倒忙。

**先建评测，再做 L6，然后用评测决定要不要打开。** 这个顺序能省掉一次可能白做的工。

### ⚠ [`L8`](./L8-PRESET-EKO-PACK.md) 的预置层改变了冲突裁决这一半的性价比

上面那些消融数字是在**只有个人层**的森林上跑的。预置社区层进来之后，情况不一样了：

| 森林形态 | 冲突的常见形态 | 需要什么 |
|---|---|---|
| 只有个人层（论文） | 同一优先级的两条个人经验打架——**罕见** | 动态置信度 `C(e,q)` |
| 个人层 + 社区层（L8 之后） | "社区说要写单测" vs "我们项目不写单测"——**系统性地常见** | **只要五级优先级就够** |

**注意这两半不是一回事**：

- **优先级裁决**（`PERSISTENT_PERSONAL(40) > DEFAULT(10)`）在 [`L1-3`](./L1-EKO-CORE.md) 就搬进来了，[`L8-4`](./L8-PRESET-EKO-PACK.md) 直接依赖它，**这部分本来就是开的，不在"默认关闭"的范围里**
- **本文档说的默认关闭，指的是 `C(e,q)` 动态置信度**——它只在同优先级打平时才被调用，而这种情况预置层并不会让它变多

论文的 Priority Only 消融拿到 73.33%，说明**光靠优先级就能处理跨层冲突**。所以预置层的引入**不构成打开 `C(e,q)` 的理由**。

> 别把这两半混起来。看到"社区经验被个人经验覆盖了"就以为是 L6 生效了——那是 L1-3 的优先级表在干活。

---

## §1 任务卡

### L6-1 · 依赖关系的获取

`P1` / 1.5 天 / 依赖：L5 全部

**背景**

**这张卡才是依赖组合的真正瓶颈。** `resolve_formal` 已经在 L1-3 搬好了，它工作得很好——**前提是 EKO 里有 `dependencies`**。

论文对这块的处理是（`eko_engine.py` 的 `_known_relations`）：

1. 蒸馏时模型给 `dependency_hints`，过滤成森林里已知的 EKO id
2. 运行期通过 `revise_dependencies` 修订

论文 §5 承认："**后续应提高关系自动发现能力**"。

**涉及文件**

| 文件 | 说明 |
|---|---|
| `src/linkagent/eko/relations.py` | 新建 |
| `tests/eko/test_relations.py` | 新建 |

**已经替你决定好的**

| 决定 | 理由 |
|---|---|
| 依赖**只从共现轨迹推断**，不调 LLM | LLM 推断依赖会大量过度预测——它倾向于认为什么都相关 |
| 推断条件 | 两个 EKO 在**≥3 条成功轨迹**里以固定顺序共现 |
| 推断出的依赖标记 `inferred` | 与用户显式声明的区分开 |
| 用户可以显式声明 | `linkagent eko depend <a> --on <b>` |
| **环必须拒绝** | `resolve_formal` 已有环检测，这里在写入前就拦 |

**为什么定"≥3 条成功轨迹 + 固定顺序"**：低于这个数，共现很可能是巧合。顺序不固定说明它们只是经常一起出现，不是真的有依赖。

**操作步骤**

1. 实现共现统计和依赖推断。

2. 测试：

```python
def test_three_ordered_cooccurrences_infer_a_dependency():
def test_two_cooccurrences_are_not_enough():
def test_unordered_cooccurrence_infers_nothing():
    """经常一起出现 ≠ 有依赖关系。"""
def test_inferred_dependencies_are_marked():
def test_cycle_is_rejected_before_write():
def test_user_declared_dependency_needs_no_evidence():
```

**验收命令**

```powershell
cd "D:\agent-demo\LinkAgent"
python -m pytest tests/eko/test_relations.py -q
python -m ruff check src/linkagent/eko/
```

**完成判据**
- [ ] 六个测试全绿
- [ ] 推断需要 ≥3 条有序共现
- [ ] 推断结果被标记
- [ ] 环在写入前被拒
- [ ] 零 LLM 调用

**Commit**
```
feat(eko): infer dependencies from repeated ordered co-occurrence

Composition scored 100% in the paper only because the dependency edges
were hand-written for that experiment; the frozen corpus has none. Edges
come from three ordered co-occurrences rather than a model's judgement,
because an LLM asked "does A depend on B" says yes far too often.
```

---

### L6-2 · 依赖组合接入

`P1` / 0.5 天 / 依赖：L6-1

**背景**

把 turn 第 2 步的占位换成真的。**代码已经在 L1-3 搬好了**，这张卡只是接线 + 开关。

**涉及文件**

| 文件 | Grep 锚点 |
|---|---|
| `src/linkagent/runtime/turn.py` | `def _compose` |
| `tests/runtime/test_turn.py` | — |

**已经替你决定好的**

- **默认关闭**（`Config.features.dependency_composition = False`，L0-4 已定）
- 开关可以**按域**打开，不是全局一刀切：某个域积累出依赖关系了，只开那个域
- 展开后的 EKO 总数仍受 **5 条上限**约束（L2-3 定的）。展开超了就截断并记 warning
- 依赖不可用或有环时**停止并报告**，不是跳过继续

**最后一条是论文验证过的行为**：15 个案例里有 2 个不可用依赖和 1 个循环依赖，系统都正确停止并报告了原因。

**操作步骤**

1. 实现 `_compose`，加按域开关。

2. 测试：

```python
def test_composition_is_off_by_default():
def test_enabled_domain_expands_dependencies():
def test_disabled_domain_is_unaffected():
def test_expansion_respects_the_five_eko_limit():
def test_unavailable_dependency_stops_with_a_reason():
def test_cycle_stops_with_a_reason():
```

**验收命令**

```powershell
cd "D:\agent-demo\LinkAgent"
python -m pytest tests/runtime -q
python -m ruff check .
```

**完成判据**
- [ ] 六个测试全绿
- [ ] 默认关闭
- [ ] 按域开关生效
- [ ] 5 条上限仍然生效
- [ ] 异常情况停止并报告原因

**Commit**
```
feat(runtime): enable dependency composition per domain, off by default

The ablation found no aggregate benefit, so this stays off until a domain
actually accumulates dependency edges and L7 shows it helps there.
```

---

### L6-3 · 冲突裁决接入

`P1` / 1 天 / 依赖：L5 全部

**背景**

同上，代码在 L1-3 已搬好。

**涉及文件**

| 文件 | Grep 锚点 |
|---|---|
| `src/linkagent/runtime/turn.py` | `def _resolve_conflicts` |
| `tests/runtime/test_conflict_integration.py` | 新建 |

**已经替你决定好的**

- **默认关闭**
- 五级优先级不变：`SAFETY(100) > EXPLICIT_INSTRUCTION(80) > TASK_CONTEXT(60) > PERSISTENT_PERSONAL(40) > DEFAULT(10)`
- 优先级由**当前请求中 EKO 的来源**决定，**不是写死在对象上的属性**（论文明确这一点）
- 完全同分**必须请求用户确认**，不许按列表顺序隐式选
- 确认走 RxyCode 的 `core/question.py` broker，不自己造 UI

**⚠ 关掉冲突裁决时不是"什么都不做"**：L2-3 注入的文本里那句"如果与当前请求冲突，以当前请求为准"仍然生效。那是零成本的兜底，覆盖了最常见的情况（显式指令 vs 持久偏好）。

**操作步骤**

1. 实现 `_resolve_conflicts`。

2. 测试：

```python
def test_conflict_resolution_is_off_by_default():
def test_safety_beats_persistent_personal():
def test_explicit_instruction_beats_persistent_personal():
def test_same_priority_uses_dynamic_confidence():
def test_complete_tie_asks_the_user():
    """同分必须问,不许按顺序选。"""
def test_priority_comes_from_the_request_not_the_object():
    """同一个 EKO 在不同请求里可以是不同优先级。"""
def test_disabled_still_relies_on_the_injected_precedence_hint():
    """关掉时靠注入文本里那句「以当前请求为准」兜底。"""
```

**验收命令**

```powershell
cd "D:\agent-demo\LinkAgent"
python -m pytest tests/runtime/test_conflict_integration.py -q
python -m ruff check .
```

**完成判据**
- [ ] 七个测试全绿
- [ ] 默认关闭
- [ ] 优先级来自请求不是对象
- [ ] 同分请求确认
- [ ] 关掉时兜底仍生效

**Commit**
```
feat(runtime): enable conflict resolution behind a flag, off by default

Priority is derived from how an EKO enters the current request rather
than stored on the object, so the same entry can rank differently across
requests. A complete tie asks the user instead of silently taking the
first match.
```

---

### L6-4 · 开关决策报告

`P1` / 1 天 / 依赖：L6-2、L6-3、L7 全部

**背景**

**这张卡回答一个问题：这两个模块到底要不要打开。**

需要 L7 的评测能力，所以放在最后。

**涉及文件**

| 文件 | 说明 |
|---|---|
| `evals/composition_conflict_report.py` | 新建 |
| `docs/decisions/L6-flags.md` | 新建，决策记录 |

**已经替你决定好的**

- 用 L7 的 A/B harness，**四个条件**：都关 / 只开组合 / 只开冲突 / 都开
- 统计单位与论文一致：**序列级**，配对置信区间
- **打开的门槛：置信区间不跨 0 且方向为正。** 跨 0 就保持关闭
- 结论写进 `docs/decisions/`，**不管结论是什么都要写**

**最后一条很重要**：如果结论是"两个都不该开"，那也是一个有价值的结论，要记下来——否则半年后有人会重新提议打开它们。

**操作步骤**

1. 跑四条件 A/B。

2. 写决策记录，模板：

```markdown
# L6 开关决策

**日期**：
**评测集**：<任务数、域分布>
**样本量**：<序列数>

## 结果

| 条件 | 成功率 | 相对基线（配对 95% CI） | Token | 延迟 |
|---|---:|---:|---:|---:|

## 决定

依赖组合：<开 / 关 / 按域开>
冲突裁决：<开 / 关>

## 理由

<为什么。如果是「关」,写清楚什么条件下会重新考虑。>
```

**验收命令**

```powershell
cd "D:\agent-demo\LinkAgent"
python -m evals.composition_conflict_report
```

**完成判据**
- [ ] 四个条件都跑了
- [ ] 置信区间按序列配对计算
- [ ] 决策记录已写，含"什么条件下重新考虑"
- [ ] 默认值按结论更新

**Commit**
```
docs: record the composition and conflict flag decision

Writing down a "keep it off" decision matters as much as a "turn it on"
one — otherwise the same proposal comes back in six months without the
measurement.
```

---

## §2 L6 出口检查

```powershell
cd "D:\agent-demo\LinkAgent"
python -m ruff check .
python -m pytest -q
python -m evals.composition_conflict_report
```

**L6 完成的定义：**
- 两个模块可用，**默认值由实测决定**（不是由直觉决定）
- 依赖能从共现推断，且需要 ≥3 条有序证据
- 决策记录已写
- 四个 commit

**如果评测结论是"两个都不该开"**：这是一个**完全可以接受的结果**。代码留着，开关留着，等经验库长大了再重新测。

**下一步**：[`L7-EVAL-HARNESS.md`](./L7-EVAL-HARNESS.md)（如果还没做）
