# L7 · 评测

> **前置**：[`L3-RETRIEVAL-AND-SCOPE.md`](./L3-RETRIEVAL-AND-SCOPE.md) 完成（有东西可测了）
> **建议**：**与 L4/L5 并行做**，不要等全做完再建评测
> **产出**：能回答"LinkAgent 到底有没有用"，以及"哪一层有用"
> **工时**：6 天
> **卡数**：5 张（L7-1 ~ L7-5）
>
> **干活前读** [`../MODEL-ASSIGNMENT.md`](../MODEL-ASSIGNMENT.md)；本文件卡多为 **owner: backend** → [`../COMPOSER-2.5-PLAYBOOK.md`](../COMPOSER-2.5-PLAYBOOK.md)。**一次只做一张卡。**

---

## §0 为什么不能照搬论文的数字

论文的结论是 **+5.27 pp，代价 Token +25.32%**。**这个数字不能假定会在 LinkAgent 上复现**，理由论文自己列了（§5 Limitations）：

| 论文的条件 | LinkAgent 的条件 | 差异影响 |
|---|---|---|
| 100 条受控序列 × 13 个固定任务位置 | 真实编码任务 | 任务分布完全不同 |
| RecoReact + BFCL | 代码仓库 | 领域不同 |
| DeepSeek + Doubao | 用户自选 | 已观察到 **8 pp 的模型间分裂** |
| 沙箱工具、计划即执行 | 真实工具、AgentV2 自己规划 | 执行路径不同 |
| 作用域交集放行 | **L3 改成 domain 硬闸** | **我们主动改了机制** |

**最后一行尤其关键**：LinkAgent 修了论文的已知缺陷。这意味着 LinkAgent 的表现**可能比论文更好**（负迁移少了），也可能更差（召回严了）。**只能测，不能推。**

### 这份文档的立场

> **拿不到自己的数字之前，不要声称 LinkAgent 有用。**
>
> 论文的数字证明"这套机制在受控协议下有效"，不证明"它在你的编码任务上有效"。

---

## §1 评测设计（照抄论文的方法论，那部分是对的）

论文的实验方法有几条值得原样照搬：

| 方法 | 为什么对 |
|---|---|
| **配对消融共享原始输出** | Full 条件的记录按哈希复用，不重跑。省钱且消除运行间噪声 |
| **runtime 与 scoring 隔离** | 推理时不给参考答案，轨迹存完之后才由独立评分器加载 |
| **序列级为统计单位** | turn 级会高估样本量（同一序列内的 turn 不独立） |
| **配对置信区间** | 条件差异按序列配对算，不是两组独立比较 |
| **失败留在分母** | 崩溃、超时都算失败，不许剔除 |
| **温度设 0** | 减少运行间方差 |

**最后两条最容易被违反**，而违反它们能让任何系统看起来都有效。

---

## §2 任务卡

### L7-1 · 评测任务集

`P0` / 2 天 / 依赖：L3 全部

**背景**

**这张卡决定了后面所有数字的可信度。** 任务集设计错了，测出来的一切都没意义。

**涉及文件**

| 文件 | 说明 |
|---|---|
| `evals/tasks/` | 新建，任务定义 |
| `evals/schema.py` | 新建，任务格式 |
| `tests/evals/test_task_schema.py` | 新建 |

**已经替你决定好的**

**任务集必须是"序列"，不是孤立任务。** LinkAgent 的价值在于**跨会话复用经验**，用孤立任务测等于测不到核心能力。

| 项 | 值 | 理由 |
|---|---|---|
| 结构 | **序列**，每条 6–10 个连续任务 | 孤立任务测不到跨会话复用 |
| 序列数 | **≥30** | 论文用 100；30 是能出可用置信区间的下限 |
| 每条序列的构成 | 见下表 | 覆盖 LinkAgent 各层能力 |
| 评分 | **确定性事后评分器**，不用 LLM judge | LLM judge 引入额外方差和成本 |
| 参考答案 | **推理时不可见** | runtime/scoring 隔离 |

**每条序列的任务位置**（照论文的思路，改成编码场景）：

| 位置 | 任务类型 | 测什么 |
|---|---|---|
| 1–2 | 普通编码任务 | 基线能力 |
| 3 | 用户表达一个偏好 | Mode U 采集 |
| 4–5 | 同域任务，应该用上偏好 | 检索 + 复用 |
| 6 | **跨域任务，不应该用上偏好** | **L3 的作用域硬闸** |
| 7 | 用户纠正之前的偏好 | 反馈演化 |
| 8 | 同域任务，应该用上**纠正后的**偏好 | 版本演化 |
| 9 | 触碰安全边界的任务 | SAG |
| 10 | 跨会话复用 | 长期记忆 |

**第 6 个位置是重点**——它直接对应论文里掉到 0.15 的 turn 12。

**操作步骤**

1. 定义任务 schema：

```python
@dataclass(frozen=True)
class EvalTask:
    """一个评测任务。

    参考答案与任务分离:runtime 只看 prompt 和 setup,expected 由独立的
    评分器在轨迹存完之后加载。混在一起迟早会泄漏。
    """

    task_id: str
    position: int
    kind: TaskKind
    prompt: str
    #: 仓库初始状态
    setup: RepoSetup
    #: **runtime 不可见**
    expected: Expectation
```

2. 写 30 条序列。**这是体力活，但不能糊弄。**

> 觉得 30 条太多可以先写 10 条跑通流程，但**出正式结论前必须补齐**。10 条的置信区间会宽到什么都说明不了。

3. Schema 测试：

```python
def test_every_sequence_has_a_cross_domain_position():
    """每条序列必须有跨域位置。

    那是 L3 的核心验收点,漏了就测不到 LinkAgent 最主要的改进。
    """

def test_expectations_are_not_reachable_from_the_prompt():
    """参考答案不能出现在 prompt 里。"""

def test_task_ids_are_unique():
def test_positions_are_contiguous():
```

**验收命令**

```powershell
cd "D:\agent-demo\LinkAgent"
python -m pytest tests/evals -q
python -m evals.cli validate
```

**完成判据**
- [ ] ≥30 条序列（或明确记录当前是 N 条、何时补齐）
- [ ] 每条序列有跨域位置
- [ ] 参考答案 runtime 不可见（有测试）
- [ ] 评分是确定性的

**Commit**
```
feat(evals): define sequence-based evaluation tasks

Isolated tasks cannot measure cross-session reuse, which is the whole
point of the experience layer, so tasks come as sequences. Every sequence
carries a cross-domain slot: that position is where the paper's system
dropped to 0.15 and it is what L3 set out to fix.
```

---

### L7-2 · A/B 运行器与进程隔离

`P0` / 1.5 天 / 依赖：L7-1

**背景**

跑同一批任务，一边开 EKO 一边关。

**这里有个坑**：RxyCode 有一堆进程级全局单例（工具注册表、两个缓存、prompt 注册表、token 统计、三个 broker——完整清单见 [`APPENDIX-A §6.3`](./APPENDIX-A-ASSET-INVENTORY.md#63--全局单例清单决定进程隔离策略)）。**同进程里切配置会串扰**，尤其是那两个缓存——A 条件跑出来的结果会被 B 条件命中。

**涉及文件**

| 文件 | 说明 |
|---|---|
| `evals/runner.py` | 新建 |
| `evals/conditions.py` | 新建 |
| `tests/evals/test_runner.py` | 新建 |

**已经替你决定好的**

| 决定 | 值 | 理由 |
|---|---|---|
| **每个条件一个子进程** | 强制 | 全局单例会串扰，尤其是缓存 |
| 每个条件独立的数据目录 | `LINKAGENT_DATA_DIR` 指向临时目录 | 经验库不能互相污染 |
| **缓存必须禁用** | 通过 RxyCode 配置关掉 | 命中缓存的 turn 不反映真实能力 |
| 温度 | 0（或端点允许的最低值） | 减少方差 |
| 断点续跑 | 每条序列跑完就落盘 | 跑 30 条要很久，中断了不能从头来 |
| 失败 | **留在分母** | 崩溃、超时都算失败，不许剔除 |

**评测条件**（对应论文的四条件）：

| 条件 | 说明 |
|---|---|
| `baseline` | 纯 RxyCode，无 EKO |
| `flat` | 有 EKO，但不做作用域过滤（对应论文的 Flat EKO） |
| `no_governance` | 有检索，无安全门无反馈演化 |
| `full` | 全开 |

**加一个论文没有但我们需要的条件**：

| 条件 | 说明 |
|---|---|
| `full_legacy_scope` | 全开，但作用域用**论文的交集放行语义** |

**这个条件是用来量化 L3 改造价值的。** 没有它，你无法回答"改作用域语义到底带来多少收益"。

**操作步骤**

1. 实现子进程运行器。

2. 实现断点续跑（每序列一个 checkpoint）。

3. 测试：

```python
def test_each_condition_runs_in_its_own_process():
def test_conditions_do_not_share_a_data_dir():
def test_caches_are_disabled():
    """命中缓存的 turn 不反映真实能力,会让结果虚高。"""
def test_crashed_task_counts_as_failure():
    """失败留在分母。剔除失败能让任何系统看起来都有效。"""
def test_interrupted_run_resumes_from_checkpoint():
```

**验收命令**

```powershell
cd "D:\agent-demo\LinkAgent"
python -m pytest tests/evals/test_runner.py -q
python -m evals.cli run --condition baseline --limit 2
```

**完成判据**
- [ ] 五个测试全绿
- [ ] 每个条件独立子进程 + 独立数据目录
- [ ] 缓存已禁用（有测试）
- [ ] 失败留在分母
- [ ] 断点续跑可用
- [ ] `full_legacy_scope` 条件存在

**Commit**
```
feat(evals): run each condition in an isolated subprocess

RxyCode's caches and registries are process-global, so switching config
in-process lets one condition's results leak into another's. Caches are
off entirely: a cache hit measures the cache, not the agent.
```

---

### L7-3 · 确定性评分器

`P0` / 1.5 天 / 依赖：L7-1

**背景**

**评分器与 runtime 严格隔离。** 推理时不给参考答案，轨迹存完之后才加载。

**涉及文件**

| 文件 | 说明 |
|---|---|
| `evals/scorer.py` | 新建 |
| `tests/evals/test_scorer.py` | 新建 |

**已经替你决定好的**

| 决定 | 理由 |
|---|---|
| **确定性评分，不用 LLM judge** | LLM judge 引入方差和成本，而且它自己也会错 |
| 评分器**只读轨迹文件** | 物理隔离，不可能泄漏 |
| 主指标：**序列级平均任务成功率** | 与论文一致 |
| 辅助指标：token、延迟、跨域泄漏数、安全拦截数 | — |
| **跨域泄漏单独统计** | 这是 L3 的核心指标，不能埋在总成功率里 |

**各类任务的判定**：

| 任务类型 | 怎么判成功 |
|---|---|
| 普通编码 | 测试通过 / 构建成功 |
| 偏好应用 | 输出**符合**已表达的偏好（结构化检查，不是模糊匹配） |
| **跨域** | 输出**不含**无关域的偏好特征 ← 反向判定 |
| 安全边界 | 危险操作被拦且安全操作未被误伤 |
| 跨会话复用 | 用上了之前会话形成的经验 |

**操作步骤**

1. 实现各类判定。

2. 测试：

```python
def test_scorer_only_reads_trajectory_files():
    """评分器不 import runtime,物理隔离。"""

def test_cross_domain_leakage_is_counted_separately():
    """跨域泄漏不能埋在总成功率里。

    它是 L3 的核心指标,而且一条序列里只有 1 个跨域位置,埋进总分就
    被稀释到看不见了。
    """

def test_scoring_is_deterministic():
    """同一份轨迹评十次结果相同。"""

def test_missing_trajectory_scores_as_failure():

def test_preference_check_is_structural_not_fuzzy():
```

**验收命令**

```powershell
cd "D:\agent-demo\LinkAgent"
python -m pytest tests/evals/test_scorer.py -q
python -m evals.cli score --run <run-id>
```

**完成判据**
- [ ] 五个测试全绿
- [ ] 评分器不 import runtime
- [ ] 跨域泄漏单独统计
- [ ] 评分确定性
- [ ] 缺轨迹算失败

**Commit**
```
feat(evals): score trajectories deterministically and offline

The scorer reads only trajectory files and never imports runtime, which
makes reference-answer leakage structurally impossible. Cross-domain
leakage is reported separately because one slot per sequence would vanish
inside an aggregate success rate.
```

---

### L7-4 · 统计与报告

`P0` / 1 天 / 依赖：L7-2、L7-3

**背景**

把原始结果变成能下判断的报告。

**涉及文件**

| 文件 | 说明 |
|---|---|
| `evals/stats.py` | 新建 |
| `evals/report.py` | 新建 |
| `tests/evals/test_stats.py` | 新建 |

**已经替你决定好的**

| 决定 | 理由 |
|---|---|
| 统计单位：**序列 ID** | turn 级会高估样本量（同序列的 turn 不独立） |
| 条件差异：**按序列配对**的置信区间 | 不是两组独立比较 |
| 方法：bootstrap | 论文用的方法 |
| **必须报告 token 和延迟** | 论文 +5.27 pp 的代价是 +25% token，只报收益不报代价是误导 |
| **置信区间跨 0 就明说"无显著差异"** | 不许用"略有提升"这类话糊弄 |

**报告格式**：

```
LinkAgent 评测报告   run-20260815-a3f2
30 条序列 × 8 任务 · 执行模型 deepseek-v4-flash · 温度 0

条件                    成功率    相对 baseline(配对 95% CI)   Token    延迟
baseline                 71.2%    —                          62,104   48.2s
flat                     73.8%    +2.6 pp [+0.4, +4.9]       71,332   55.1s
no_governance            74.1%    +2.9 pp [+0.6, +5.2]       70,884   54.7s
full                     78.4%    +7.2 pp [+4.8, +9.7]       79,551   61.3s
full_legacy_scope        74.9%    +3.7 pp [+1.2, +6.1]       79,120   61.0s

跨域泄漏（越低越好）
  baseline           0 / 30
  flat              22 / 30
  full_legacy_scope 19 / 30    ← 论文的作用域语义
  full               0 / 30    ← L3 的 domain 硬闸

安全
  危险操作拦截    12 / 12
  安全操作误伤     0 / 45

结论
  完整系统比基线高 7.2 个百分点，代价是 Token +28.1%、延迟 +27.2%。
  L3 的作用域改造贡献了其中 3.5 个百分点（full vs full_legacy_scope），
  跨域泄漏从 19/30 降到 0/30。
```

> 上面是**格式示例**，数字是编的。真实数字要跑出来。

**操作步骤**

1. 实现 bootstrap 配对置信区间。

2. 实现报告生成。

3. 测试：

```python
def test_confidence_intervals_are_paired_by_sequence():
def test_sequence_is_the_statistical_unit():
    """30 条序列 × 8 任务的 n 是 30,不是 240。"""
def test_report_always_includes_cost():
    """只报收益不报代价是误导。"""
def test_interval_crossing_zero_is_reported_as_no_difference():
    """不许把跨 0 的结果说成「略有提升」。"""
```

**验收命令**

```powershell
cd "D:\agent-demo\LinkAgent"
python -m pytest tests/evals/test_stats.py -q
python -m evals.cli report --run <run-id>
```

**完成判据**
- [ ] 四个测试全绿
- [ ] 统计单位是序列
- [ ] 置信区间配对
- [ ] 报告含 token 和延迟
- [ ] 跨 0 明确说无显著差异

**Commit**
```
feat(evals): report paired sequence-level intervals with cost

Sequence is the statistical unit because turns within one sequence are
not independent. Cost is mandatory in the report: the paper's +5.27 pp
came with +25% tokens, and quoting the gain alone misleads.
```

---

### L7-5 · 首次基线与结论

`P0` / 1 天 / 依赖：L7-4

**背景**

**跑第一次完整评测，把结论写下来——不管结论是什么。**

**涉及文件**

| 文件 | 说明 |
|---|---|
| `evals/baselines/` | 结果落盘 |
| `docs/decisions/first-baseline.md` | 结论 |

**已经替你决定好的**

- 跑**全部五个条件**
- 结果落盘并提交进 git（**这是回归基线**）
- 结论写进 `docs/decisions/`，**不管好坏**
- 如果结论是"LinkAgent 没有明显收益"，**照实写**，然后讨论下一步

**最后一条是这张卡最重要的部分。** 一个只在结果好看时才写的报告没有价值。

**结论文档模板**：

```markdown
# 首次基线评测

**日期**：
**Run ID**：
**任务集**：<N 条序列 × M 任务>
**执行模型**：
**成本**：<总 token / 总耗时 / 大约花了多少钱>

## 结果

<报告表格>

## 结论

1. LinkAgent 相对裸 RxyCode：<有/无>显著收益，<+X.X pp，CI [...]>
2. L3 的作用域改造：贡献 <X.X pp>，跨域泄漏 <N → M>
3. 代价：Token +<X>%，延迟 +<Y>%

## 与论文的对比

| | 论文 | LinkAgent |
|---|---|---|
| 相对基线提升 | +5.27 pp | |
| Token 代价 | +25.32% | |
| 跨域负迁移 | 存在（turn 12 = 0.15） | |

<差异的解释>

## 下一步

<基于数字的决定,不是基于计划的>
```

**操作步骤**

1. 跑全量评测。**这会花不少钱和时间，先用 `--limit 2` 验证流程再全量跑。**

2. 写结论。

**验收命令**

```powershell
cd "D:\agent-demo\LinkAgent"
python -m evals.cli run --all-conditions
python -m evals.cli report --run <run-id> --save evals/baselines/
```

**完成判据**
- [ ] 五个条件全部跑完
- [ ] 结果落盘并提交
- [ ] 结论文档已写，**含与论文的对比**
- [ ] 下一步是基于数字的

**Commit**
```
docs: record the first LinkAgent baseline against plain RxyCode

Numbers first, plans second: whatever the result, it is written down and
compared against the paper's controlled protocol so later decisions argue
with measurements rather than intentions.
```

---

## §3 L7 出口检查

```powershell
cd "D:\agent-demo\LinkAgent"
python -m ruff check .
python -m pytest -q
python -m evals.cli run --all-conditions
python -m evals.cli report --run <run-id>
```

**L7 完成的定义：**
- ≥30 条序列，每条有跨域位置
- 五个条件都能跑，各自子进程隔离，缓存禁用
- 评分确定性，与 runtime 物理隔离
- 报告含配对置信区间 + 成本
- 首次基线已跑并落盘
- 结论已写，**不管好坏**
- 五个 commit

---

## §4 之后怎么用它

评测建好之后，它是**每个改动的守门人**：

| 场景 | 用法 |
|---|---|
| 改了检索逻辑 | 跑 `full` vs 上次基线，看有没有回归 |
| 想打开 L6 的开关 | 跑四条件对比（L6-4） |
| 换了执行模型 | 重跑全部条件——**模型间分裂是实测存在的**（论文里 8 pp） |
| 经验库长大了 | 定期重跑，看收益是否随库增长而变化 |

**最后一条值得单独说**：论文的 304 个 EKO 是一次性蒸馏出来的。真实使用中经验库会持续增长，**收益曲线的形状是未知的**——可能增长，可能饱和，也可能因为检索噪声增加而下降。这只能靠定期重测发现。
