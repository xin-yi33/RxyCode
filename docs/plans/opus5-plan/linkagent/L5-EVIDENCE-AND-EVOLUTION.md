# L5 · 经验采集与反馈演化

> **前置**：[`L4-SAFETY-GATE.md`](./L4-SAFETY-GATE.md) 全部完成
> **⚠ 硬前置**：[`L3-RETRIEVAL-AND-SCOPE.md`](./L3-RETRIEVAL-AND-SCOPE.md) 的作用域改造**必须已经完成并验证**。理由见 §0
> **产出**：LinkAgent 能自己产生 EKO，并根据执行结果演化它们
> **工时**：8 天
> **卡数**：6 张（L5-1 ~ L5-6）
>
> **干活前读** [`../COMPOSER-2.5-PLAYBOOK.md`](../COMPOSER-2.5-PLAYBOOK.md) §2。**一次只做一张卡。**

---

## §0 为什么必须等 L3 做完

**这是全项目最重要的一条排序约束。**

反馈演化的端到端消融结果是 **−1.46 pp**（显著），但拆开看两个模型：

```
w/o Feedback Evolution
  DeepSeek  80.15%   ← 比完整系统的 77.46% 高 2.69 pp
  Doubao    72.00%   ← 比完整系统的 77.62% 低 5.62 pp
```

**在 DeepSeek 上，关掉反馈演化反而更好。** 方向相反，摆动 8.15 pp。

根因论文写得很清楚（slot 级诊断）：反馈演化产生的偏好 EKO，在目标域内是正迁移（turn 13：0.565 vs 0.02），**在无关域边界上是严重负迁移**（turn 12：0.15 vs 0.525）。

**逻辑链是这样的：**

```
反馈演化 → 产生更多偏好 EKO → 作用域语义放行过宽 → 污染无关域任务
                                       ↑
                                  L3 修的就是这里
```

**在 L3 之前打开 L5，等于放大一个已知缺陷。** 经验库越大，负迁移越严重。

> **动手前先跑一遍确认 L3 真的做完了：**
>
> ```powershell
> python -m pytest tests/eko/test_cross_domain_regression.py -v
> ```
>
> 跨域泄漏必须是 **0 组**。不是 0 就**停下来**（Playbook 规则 C7）。

---

## §1 两条采集路径

论文的双模式经验获取。**都是现成代码**（L1-4 已搬 `protocol.py`），L5 做的是把它们接到 RxyCode 的真实交互上。

| | Mode U | AED |
|---|---|---|
| **来源** | 用户交互中的偏好表达 | 已验证成功的执行轨迹 |
| **触发** | 用户纠正、明确要求、重复偏好 | 任务成功完成 |
| **准入** | 显式一条即可；隐式需 **≥2 个不同 session** | **必须**有 `verified_success` 或 `verified_correction` |
| **论文形成率** | 90.4%（178/197） | 78.8%（126/160） |
| **论文复用验证** | held-out 第三轮 | **75 个在新任务中直接复用成功** |

### 准入规则不许放宽

`protocol.py` 的 `evidence_is_grounded` 是**防垃圾进经验库的第一道闸**：

- 隐式偏好要 **2 个不同 session** —— 防"用户随口说一句就被记成永久偏好"。同一个 session 里说三遍也不算
- AED 要 **验证过的结果** —— AED 的全部价值前提是"这条经验被证明有效过"

**这两条放宽任何一条，经验库会迅速被噪声填满，而且很难清理。**

---

## §2 关键设计决策（已定）

### D1 · 蒸馏是异步的，不在 turn 里做

**用户不该为了让 agent 学东西而等待。**

```
turn 结束 → 证据落盘(快,同步) → 返回结果给用户
                  ↓
            后台队列 → 蒸馏(慢,要调 LLM) → 候选 → 晋升
```

论文里蒸馏是离线批处理的，LinkAgent 做成后台任务，语义等价但用户无感。

### D2 · 蒸馏模型与执行模型分开

论文特意分开：`mimo-v2.5-pro` 蒸馏，DeepSeek / Doubao 执行。**理由是减少"同一个模型既生成又评价"的偏差。**

LinkAgent 保留这个设计，但**模型由用户配置**。默认：蒸馏用配置里的 `distillation_model`，没配就退回执行模型并**记一条 warning**。

### D3 · 用户对经验库有完全控制权

论文没覆盖这块（它的用户是数据集）。真实产品必须有：

| 能力 | 命令 |
|---|---|
| 看有哪些经验 | `linkagent eko list` |
| 看一条的详情和来源 | `linkagent eko show <id>` |
| 删一条 | `linkagent eko forget <id>` |
| 暂停学习 | `linkagent eko pause` |

**"忘记"不是删记录**——是把 status 置为 `rejected`。版本不可变是硬不变量。

### D4 · 反馈演化默认只写证据，不改内容

`record_feedback` 只往 `feedback_evidence` / `execution_stats` 里追加。

**改 `procedure` / `parameters` / `scope`（`revise_content`）需要更强的触发条件**——论文里那两个"错误修订导致任务失败然后回滚"的案例就是这么来的。内容修订要么用户显式要求，要么连续多次同向失败。

---

## §3 任务卡

### L5-1 · 证据落盘

`P0` / 1 天 / 依赖：L4 全部 + L3 验证通过

**背景**

turn 结束后把证据存下来。**这一步必须快且不能失败**——它在用户等待的路径上。

**涉及文件**

| 文件 | 说明 |
|---|---|
| `src/linkagent/distillation/store.py` | 新建 |
| `tests/distillation/test_store.py` | 新建 |

**已经替你决定好的**

| 决定 | 值 | 理由 |
|---|---|---|
| 格式 | JSONL 追加写 | 追加是原子的，崩溃不会毁掉已有数据 |
| 位置 | `~/.linkagent/evidence/<date>.jsonl` | L0-4 定的 `Paths.evidence` |
| 写入失败 | **吞掉 + warning** | 磁盘满不该让用户的任务失败 |
| **不存** 完整对话 | 只存证据记录 | 隐私 + 体积 |
| **不存** 隐藏推理 | — | AED 硬约束，L2-1 的类型层面已经保证 |
| 敏感值 | 复用 L2-5 的脱敏 | 不要写第二套 |

**操作步骤**

1. `src/linkagent/distillation/store.py`：

```python
"""证据落盘。

这一步在用户等待的路径上,所以两条硬要求:**快**(JSONL 追加,不做任何
索引或压缩)、**不能失败**(任何异常都吞掉记 warning——磁盘满不该让用户
的任务失败)。

蒸馏本身是异步的(见 L5 文档 §2 D1),这里只负责把原料存下来。
"""


class EvidenceStore:
    def append(self, packet: EvidencePacket) -> bool:
        """追加一个证据包。返回是否成功,失败不抛异常。"""

    def iter_pending(self) -> Iterator[EvidencePacket]:
        """遍历尚未蒸馏的证据包。"""

    def mark_processed(self, packet_id: str) -> None:
        """标记已处理。用单独的 processed.jsonl 记,不改原文件——
        原文件保持只追加。
        """
```

2. 测试：

```python
def test_append_is_atomic_under_concurrent_writes():
def test_write_failure_does_not_raise():
    """磁盘满时返回 False,不抛异常。"""
def test_sensitive_values_are_redacted():
def test_original_file_is_never_rewritten():
    """mark_processed 不改原文件。"""
def test_pending_excludes_processed_packets():
```

**验收命令**

```powershell
cd "D:\agent-demo\LinkAgent"
python -m pytest tests/distillation/test_store.py -q
python -m ruff check src/linkagent/distillation/
```

**完成判据**
- [ ] 五个测试全绿
- [ ] 写失败返回 `False` 不抛异常
- [ ] 原文件只追加不重写
- [ ] 敏感值脱敏

**Commit**
```
feat(distillation): append evidence to JSONL on the hot path

Persisting sits in the user's wait path, so it stays append-only and
swallows its own failures: a full disk should not fail the task. Actual
distillation happens off the turn.
```

---

### L5-2 · Mode U 证据构建

`P0` / 1.5 天 / 依赖：L5-1

**背景**

从真实对话里识别"用户在表达偏好"。

**这张卡最难的地方是判断"什么算偏好表达"。** 判宽了会记一堆噪声，判严了什么都学不到。

**涉及文件**

| 文件 | 说明 |
|---|---|
| `src/linkagent/distillation/mode_u.py` | 新建（参考 `skillforest/distillation/mode_u_evidence.py`） |
| `tests/distillation/test_mode_u.py` | 新建 |

**已经替你决定好的**

**三类证据，识别方式各不同**：

| 类型 | 怎么识别 | 准入 |
|---|---|---|
| `explicit_preference` | 用户显式说"以后都..."、"我喜欢..."、"总是用..." | **一条即可** |
| `correction` | 用户否定了 agent 的输出并给出替代 | **一条即可** |
| `implicit_preference` | 同一模式在多个会话中重复出现 | **≥2 个不同 session** |

**识别用确定性规则 + 关键词，不调 LLM**。理由同 L3-1：这在 turn 的收尾路径上。

> ⚠ **规则会漏，这是可接受的。** 漏掉一条偏好的代价，远小于把用户随口一句记成永久偏好。宁可少学。

- **`revocation`（撤销）必须支持**：用户说"不要再..."时要能撤销已有 EKO。这是用户控制权的一部分
- 识别到偏好**不立刻建 EKO**，只生成 `EvidenceRecord` 落盘。建 EKO 是蒸馏的事

**操作步骤**

1. 关键词表（中英文都要）：

```python
_EXPLICIT_MARKERS = (
    "以后都", "以后请", "总是", "每次都", "我喜欢", "我倾向", "统一用", "记住",
    "always", "from now on", "i prefer", "i like", "remember to",
)

_REVOCATION_MARKERS = (
    "不要再", "别再", "取消", "忘掉", "不用了",
    "stop", "no longer", "forget that", "don't",
)
```

2. 纠正的识别更微妙——**不能只看否定词**（"这个不对"可能是在说代码不对，不是在表达偏好）。判据是：

```
用户否定 + 给出了具体的替代方案 + 替代方案是一个可复用的做法
```

第三条是关键。"改成 3 不是 5" 不是偏好，"改成用 pathlib 不要用 os.path" 是。

3. 测试：

```python
def test_explicit_preference_forms_evidence_from_one_utterance():

def test_implicit_preference_needs_two_distinct_sessions():
    """同一 session 里说三遍不算。

    重复出现的信号价值来自「跨会话仍然成立」,同一会话里的重复很可能
    只是同一件事说了几遍。
    """

def test_correction_requires_a_reusable_alternative():
    """「改成 3 不是 5」不是偏好,「用 pathlib 不要用 os.path」是。

    区别在于替代方案能不能复用到别的任务上。
    """

def test_revocation_is_recognised():

def test_ordinary_conversation_produces_no_evidence():
    """普通问答不产生证据。

    这条守的是「宁可少学」——识别规则宁可漏,不可滥。
    """

def test_recognition_is_deterministic_and_offline():
```

**验收命令**

```powershell
cd "D:\agent-demo\LinkAgent"
python -m pytest tests/distillation/test_mode_u.py -q
python -m ruff check src/linkagent/distillation/
```

**完成判据**
- [ ] 六个测试全绿
- [ ] 隐式偏好需要跨 session（有测试）
- [ ] 纠正需要可复用的替代方案
- [ ] 撤销能识别
- [ ] **普通对话零证据**
- [ ] 零 LLM 调用

**Commit**
```
feat(distillation): recognise user preference signals in conversation

Recognition is keyword-and-rule based and deliberately conservative:
missing a preference costs far less than recording an offhand remark as a
permanent one. Implicit signals need two distinct sessions, and a
correction only counts when the alternative is reusable.
```

---

### L5-3 · AED 轨迹蒸馏

`P0` / 1.5 天 / 依赖：L5-1

**背景**

从**已验证成功**的执行轨迹里提炼可复用的做法。

论文数据：160 条轨迹 → 126 个 EKO（78.8%），**75 个在 held-out 任务中直接复用成功**。受控套件更干净：48 条种子轨迹全部通过验证，44 条提升，held-out **48/48**。

**涉及文件**

| 文件 | 说明 |
|---|---|
| `src/linkagent/distillation/aed.py` | 新建（参考 `skillforest/distillation/aed_evidence.py`） |
| `tests/distillation/test_aed.py` | 新建 |

**已经替你决定好的**

**"验证成功"的判据**——这是这张卡的核心难点。论文用的是沙箱里的确定性检查，编码场景没那么干净。按可信度排序：

| 信号 | 可信度 | 说明 |
|---|---|---|
| 测试通过（`pytest` / `npm test` 等退出码 0） | ⭐⭐⭐ **最强** | 客观、可复现 |
| 构建/编译成功 | ⭐⭐⭐ | 客观 |
| lint / typecheck 通过 | ⭐⭐ | 客观但弱 |
| 用户明确说"对了""可以" | ⭐⭐ | 主观但直接 |
| 用户没有反对 | ⭐ | **不算**，见下 |

> **"用户没有反对"不算验证成功。** 用户可能只是没看、放弃了、或者去别处解决了。把沉默当成功会污染经验库——而这正是最难清理的一类噪声，因为它看起来完全正常。

其他决定：
- **只从轨迹的可观测部分提炼**：任务 → 状态 → 工具调用 → 观测 → 结果。隐藏推理严禁使用（类型层面已保证）
- 一条轨迹最多产生 **1 个** EKO 候选。产生多个说明轨迹太长，应该先拆
- 轨迹超过 **20 次工具调用**就不蒸馏，记 warning。太长的轨迹提炼不出可复用的东西

**操作步骤**

1. 实现验证信号检测：

```python
def detect_verification(trajectory: Trajectory) -> Verification | None:
    """从轨迹里找验证成功的证据。

    按可信度排序返回最强的那个。找不到就返回 None——**没有验证过的
    轨迹不能进经验库**,这是 AED 的全部价值前提。

    特别注意:「用户没有反对」不算验证成功。用户可能只是没看、放弃了、
    或者去别处解决了。把沉默当成功会污染经验库,而且这类噪声看起来
    完全正常,极难清理。
    """
```

2. 测试：

```python
def test_passing_tests_count_as_verification():
def test_user_silence_is_not_verification():
    """沉默不是成功。这条守的是经验库最难清理的一类污染。"""
def test_unverified_trajectory_produces_no_evidence():
def test_hidden_reasoning_is_never_included():
def test_overlong_trajectory_is_skipped():
def test_one_trajectory_yields_at_most_one_candidate():
```

**验收命令**

```powershell
cd "D:\agent-demo\LinkAgent"
python -m pytest tests/distillation/test_aed.py -q
python -m ruff check src/linkagent/distillation/
```

**完成判据**
- [ ] 六个测试全绿
- [ ] 未验证的轨迹零证据
- [ ] **沉默不算成功**（有测试）
- [ ] 隐藏推理不出现
- [ ] 超长轨迹跳过

**Commit**
```
feat(distillation): distil verified trajectories into EKO evidence

Verification is ranked by how objective the signal is, and user silence
does not count: a user may simply have stopped looking. Treating silence
as success pollutes the store with entries that look entirely normal,
which is the hardest kind of noise to clean up later.
```

---

### L5-4 · 后台蒸馏与晋升

`P0` / 1.5 天 / 依赖：L5-2、L5-3

**背景**

把证据交给 LLM 生成 `CandidateEKO`，再经过校验晋升为 `FormalEKO`。

**这一步在后台跑，用户不等它。**

**涉及文件**

| 文件 | 说明 |
|---|---|
| `src/linkagent/distillation/pipeline.py` | 新建 |
| `src/linkagent/distillation/prompts/` | 新建，蒸馏 prompt |
| `tests/distillation/test_pipeline.py` | 新建 |

**已经替你决定好的**

| 决定 | 值 | 理由 |
|---|---|---|
| 触发时机 | turn 结束后的后台任务 | 用户不等 |
| 蒸馏模型 | 配置 `distillation_model`，缺省退回执行模型 + warning | 论文特意分开以减少偏差 |
| Prompt | **版本化 + 哈希**，记进 `DistillationMetadata` | 可复现 |
| 失败重试 | 一次 JSON 修复重试（`CandidateGenerator` 已有） | 照搬 |
| **domain 必填** | 候选没有 domain 就拒绝 | L3-2 的硬闸 |
| **domain 不能是 `*`** | 模型不许自己决定跨域 | L3-2 |
| 晋升前 | 走 `evidence_is_grounded` + `SafetyPolicyChecker` | `EKOEngine.promote` 已实现 |
| 蒸馏失败 | 记 warning，证据留着下次再试 | 不要丢证据 |

**操作步骤**

1. 写蒸馏 prompt，**放独立文件并计算哈希**：

```
src/linkagent/distillation/prompts/v1/mode_u/system.md
src/linkagent/distillation/prompts/v1/aed/system.md
```

参考 `D:\agent-demo\SkillForest\prompts\eko_distillation\v1\`，但要改：**必须要求模型输出 `domain`，且明确禁止 `*`**。

2. `pipeline.py`：

```python
"""后台蒸馏管线。

证据 → CandidateEKO(LLM) → 校验 → FormalEKO。

**跑在后台。** 用户不该为了让 agent 学东西而等待——蒸馏要调 LLM,可能
几秒到几十秒。

蒸馏模型与执行模型分开是论文的设计(mimo 蒸馏、DeepSeek/Doubao 执行),
目的是减少同一个模型既生成又评价的偏差。没配 distillation_model 时退回
执行模型并记 warning——能跑,但要让人知道这里有偏差风险。
"""


class DistillationPipeline:
    async def process_pending(self) -> DistillationReport:
        """处理待蒸馏的证据。幂等,可重复调用。"""
```

3. 测试（用假 LLM，**不调真实模型**）：

```python
def test_candidate_without_domain_is_rejected():
    """L3-2 的硬闸:没有 domain 不许入库。"""

def test_candidate_with_wildcard_domain_is_rejected():
    """模型不许自己决定一条经验能跨域。"""

def test_ungrounded_evidence_never_reaches_the_forest():

def test_unsafe_candidate_is_rejected_before_promotion():

def test_distillation_metadata_records_prompt_hash():
    """可复现:模型、prompt 版本、哈希都记进去。"""

def test_llm_failure_leaves_evidence_pending():
    """蒸馏失败不丢证据,下次再试。"""

def test_pipeline_is_idempotent():
    """重复跑不会产生重复 EKO。"""
```

**验收命令**

```powershell
cd "D:\agent-demo\LinkAgent"
python -m pytest tests/distillation/test_pipeline.py -q
python -m ruff check src/linkagent/distillation/
```

**完成判据**
- [ ] 七个测试全绿
- [ ] 无 domain / domain 为 `*` 的候选被拒
- [ ] 未 grounded 的证据不入库
- [ ] prompt 哈希记进元数据
- [ ] 失败不丢证据
- [ ] 幂等

**Commit**
```
feat(distillation): promote evidence into formal EKOs off the turn

Distillation calls an LLM and can take tens of seconds, so it runs in the
background. Candidates without a domain, or claiming a wildcard domain,
are rejected: deciding that an experience generalises across domains is
the strongest claim in the system and not one the model gets to make.
```

---

### L5-5 · 反馈演化与回滚

`P0` / 1.5 天 / 依赖：L5-4

**背景**

EKO 用过之后，根据结果更新它。论文 RQ4：更新/回滚/恢复三项全 100%。

**涉及文件**

| 文件 | Grep 锚点 |
|---|---|
| `src/linkagent/runtime/evolution.py` | 新建 |
| `src/linkagent/runtime/turn.py` | `def _evolve` |
| `tests/runtime/test_evolution.py` | 新建 |

**已经替你决定好的**

| 决定 | 值 | 理由 |
|---|---|---|
| 默认只写证据 | `record_feedback` 追加，不改内容 | §2 D4 |
| 内容修订的触发 | 用户显式要求，**或**连续 3 次同向失败 | 论文那两个"错误修订导致失败"的案例就是修订太激进 |
| 回滚触发 | 新版本连续 2 次失败且旧版本成功率更高 | — |
| 回滚方式 | **只改 catalog 指针** | L1-2 的不变量 |
| 归因 | 只有**被注入过**的 EKO 才记反馈 | 没参与的不能算它头上 |

**最后一条容易做错**：一个 turn 失败了，不能把所有检索到的 EKO 都记一次失败——只有真正注入进 prompt 的那几条才算。

**操作步骤**

1. 实现 `_evolve`：

```python
    def _evolve(self, result: TurnResult) -> None:
        """根据执行结果演化 EKO。

        只对**实际注入过**的 EKO 记反馈。检索到但没进 prompt 的不算——
        它没有机会影响结果,把失败记在它头上是错误归因,而错误归因会
        让好经验被逐步降权直到淘汰。
        """
```

2. 内容修订的保守触发：

```python
def should_revise_content(eko: FormalEKO, recent: Sequence[FeedbackEvent]) -> bool:
    """是否该修订内容(而不只是记证据)。

    保守:需要用户显式要求,或连续 3 次同向失败。

    论文里那两个「错误修订导致任务失败然后回滚」的案例说明修订太激进
    的代价是实打实的——修订会改变 procedure/parameters,一改错就直接
    让原本能用的经验失效。
    """
```

3. 测试：

```python
def test_only_injected_ekos_receive_feedback():
    """检索到但没注入的 EKO 不记反馈。错误归因会淘汰好经验。"""

def test_success_appends_evidence_without_changing_content():

def test_content_revision_needs_three_consecutive_failures():

def test_user_request_triggers_immediate_revision():

def test_rollback_only_moves_the_pointer():
    """回滚前后 records/ 下所有文件哈希不变。"""

def test_rolled_back_eko_recovers_the_original_task():
    """回滚后原任务重新可用。论文 RQ4 的核心验证。"""

def test_evolution_failure_does_not_break_the_turn():
```

**验收命令**

```powershell
cd "D:\agent-demo\LinkAgent"
python -m pytest tests/runtime/test_evolution.py -q
python -m pytest -q
python -m ruff check .
```

**完成判据**
- [ ] 七个测试全绿
- [ ] 只有注入过的 EKO 记反馈
- [ ] 内容修订触发保守
- [ ] 回滚只动指针（哈希验证）
- [ ] 演化失败不影响 turn

**Commit**
```
feat(runtime): evolve EKOs from execution feedback with pointer rollback

Feedback lands only on EKOs that actually reached the prompt: blaming a
retrieved-but-unused entry is misattribution, and misattribution slowly
demotes good experience out of existence. Content revision needs three
consecutive failures because the paper's two bad-revision cases show how
directly a wrong edit disables a working entry.
```

---

### L5-6 · 用户控制：只读查看 + 对话式修改

`P0` / 1.5 天 / 依赖：L5-5

**背景**

**论文完全没覆盖这块**（它的"用户"是数据集）。但真实产品里，用户必须能看到和控制 agent 记住了什么。

**这不是锦上添花。** 一个会偷偷记住你习惯、你却看不到也删不掉的 agent，是个信任问题。

> ⚠ **产品决策（[`00-OVERVIEW`](./00-OVERVIEW-AND-ARCHITECTURE.md) §9 #4）：用户能看，但不能直接编辑 EKO。**
>
> 所有**读**操作走只读界面（这张卡做 CLI，[`L9-5`](./L9-DESKTOP-APP.md) 做 UI）。
> 所有**写**操作走 **agent 工具**——用户用自然语言说，agent 调工具，工具走引擎的正式路径。
>
> **三个入口里只有工具能写**：协议的 `eko/*` 全是查询方法，CLI 的 `eko` 子命令只有 `list`/`show`/`export`。工具参数与契约测试的权威定义在 [`APPENDIX-C §5`](./APPENDIX-C-INTERFACE-CONTRACTS.md#5-agent-工具边界)。

**为什么这么设计**

| 允许直接编辑 | 只读 + 对话式修改 |
|---|---|
| 手改 `procedure`，版本链断了 | 走 `EKOEngine`，版本链完整 |
| 绕过安全门 | 经过 SAG 和审批 |
| `provenance` 变成谎话（没有证据支撑这次改动） | 用户的话本身就是一条 `explicit_preference` 证据 |
| 用户得学 EKO 的 17 个字段 | 用户只需要说"别再用 `os.path` 了" |

**涉及文件**

| 文件 | 说明 |
|---|---|
| `src/linkagent/cli.py` | `eko` 子命令组，**只读** |
| `src/linkagent/tools/eko_tools.py` | 新建，agent 用来改 EKO 的工具 |
| `tests/test_cli_eko.py` | 新建 |
| `tests/tools/test_eko_tools.py` | 新建 |

**A. 只读命令（CLI，也是 L9-5 的数据来源）**

| 命令 | 行为 |
|---|---|
| `linkagent eko list` | 列出当前 EKO（id、domain、description 摘要、状态、用过几次） |
| `linkagent eko show <id>` | 详情：完整内容、来源证据、版本历史 |
| `linkagent eko export` | 导出全部为 JSON |

**B. 写操作（agent 工具，不是 CLI 命令）**

用 RxyCode 的**实例级** `ToolOrchestrator.register` 注册，不碰全局注册表（理由见 [`00-OVERVIEW`](./00-OVERVIEW-AND-ARCHITECTURE.md) §7）。

| 工具 | 用户会怎么说 | 行为 |
|---|---|---|
| `eko_forget` | "忘掉你记的那个类型注解的事" | status 置 `rejected`，**不删记录** |
| `eko_restore` | "把刚才让你忘的那条恢复" | 撤销 forget |
| `eko_revise` | "以后别用 `os.path` 了，用 `pathlib`" | 走 L5-5 的内容修订，产生新版本 |
| `eko_pause_learning` / `eko_resume_learning` | "这段时间别记东西了" | 暂停/恢复蒸馏 |

**几条硬要求**

- `forget` **不删记录**——版本不可变是硬不变量。置 `rejected` 后检索不到，但审计链完整
- `show` 必须能回答**"这条经验是怎么来的"**——列出支撑它的证据和当时的会话
- `export` 要能导出全部，**这是用户的数据**
- `pause` 期间证据**照常落盘**，只是不蒸馏。这样用户 resume 之后不会丢掉这段时间的信号
- **每个写工具都要经过审批**，并在对话里回显改了什么。用户说的话和 agent 的理解可能不一致，要给纠正的机会
- **写工具不能改 `provenance` / `validation_evidence` / `execution_stats`**——这些是系统记录的事实，不是用户意见。工具参数里就不该有这些字段

**操作步骤**

1. 实现只读子命令组。

2. `list` 的输出：

```
ID                    域          描述                             状态    用过
eko-modeu-a1b2c3d4    python      函数签名加类型注解                active   12
eko-aed-e5f6g7h8      database    改 schema 前先备份                active    3
eko-modeu-i9j0k1l2    frontend    CSS 用 rem 不用 px               active    7
eko-modeu-m3n4o5p6    general     提交信息用祈使句                  rejected  0

4 条经验（3 active，1 rejected）· 学习中
```

3. `show` 的输出必须包含来源：

```
eko-modeu-a1b2c3d4  v1.0.2  active

描述：函数签名加类型注解
域：  python
范围：users=[you] domain=[python] task_types=[code_generation]

做法：
  1. 定义函数时给所有参数和返回值加类型注解
  2. 复杂类型用 typing 里的别名

来源：
  这条经验来自你的 3 次交互
  · 2026-07-18 会话 s-4f2a  你说"以后函数都加上类型注解"
  · 2026-07-22 会话 s-9c1e  你把我写的函数改成带注解的
  · 2026-07-29 会话 s-2b7d  你说"记得加注解"

版本：
  1.0.0  2026-07-18  首次形成
  1.0.1  2026-07-22  追加证据
  1.0.2  2026-07-29  追加证据

使用：12 次（成功 11 · 失败 1）
```

4. `tools/eko_tools.py`：

```python
"""让 agent 代替用户修改 EKO 的工具。

## 为什么改 EKO 要走工具,不给用户直接编辑

用户直接编辑会绕过三样东西:版本链、证据、安全门。手改一次 procedure,
这条 EKO 的 provenance 就变成了谎话——它声称自己来自某几次交互,实际
内容已经不是那几次交互支撑的了。

走工具的话,用户那句「以后别用 os.path 了」本身就是一条
explicit_preference 证据,修订有据可查,版本链完整,而且用户不需要知道
EKO 有 17 个字段。

## 工具不能碰的字段

provenance / validation_evidence / execution_stats 是系统记录的事实,
不是用户意见。工具的参数签名里就不该出现它们——不是运行时校验,是根本
没有这个入口。
"""
```

5. 用**实例级** `ToolOrchestrator.register` 注册，**不要碰全局工具注册表**。

6. 测试：

```python
# 只读
def test_forget_marks_rejected_without_deleting_records():
    """forget 后 records/ 下的文件仍然存在。"""
def test_forgotten_eko_is_not_retrieved():
def test_restore_reverses_forget():
def test_show_lists_the_supporting_evidence():
    """必须能回答「这条经验是怎么来的」。"""
def test_pause_keeps_collecting_evidence():
    """暂停学习期间证据照常落盘,resume 后不丢信号。"""
def test_export_includes_every_eko():

# agent 工具
def test_revise_via_tool_creates_new_version_with_evidence():
    """对话式修订产生新版本,且新版本带得住这次用户发言作为证据。"""
def test_tools_cannot_touch_provenance():
    """工具签名里根本没有 provenance 参数。"""
def test_write_tools_require_approval():
def test_cli_has_no_write_commands():
    """CLI 只读——grep 子命令表,不该有 forget/revise/restore。"""
def test_protocol_has_no_eko_write_methods():
    """协议里也没有写方法。与上一条是同一约束在另一个边界上的投影。
    L9-1 会重复这个测试,两边都要有。"""
```

**验收命令**

```powershell
cd "D:\agent-demo\LinkAgent"
python -m pytest tests/test_cli_eko.py tests/tools/test_eko_tools.py -q
linkagent eko list
python -m ruff check .
```

**完成判据**
- [ ] 十个测试全绿
- [ ] `forget` 不删记录
- [ ] `show` 能说清来源
- [ ] `pause` 期间证据仍落盘
- [ ] `export` 完整
- [ ] **CLI 里没有任何写命令**
- [ ] 对话里说"以后别用 X 了"能真的产生新版本
- [ ] 写工具走审批，且在对话里回显改了什么

**禁止**

- ❌ 在 CLI 里加 `forget` / `revise` / `restore`（写操作只走 agent 工具）
- ❌ 工具参数暴露 `provenance` / `validation_evidence` / `execution_stats`
- ❌ 用全局工具注册表注册

**Commit**
```
feat: let users inspect their experience store and change it by talking

An agent that quietly accumulates habits the user cannot see or delete is
a trust problem, and the paper never had to face it because its users
were datasets. Reads go through a read-only surface; writes go through
agent tools so every change keeps its version chain, its evidence, and
its approval trail. Forget marks an entry rejected rather than deleting
it, so the audit chain survives while retrieval stops seeing it.
```

---

## §4 L5 出口检查

```powershell
cd "D:\agent-demo\LinkAgent"
python -m ruff check .
python -m pytest -q
python -m pytest tests/eko/test_cross_domain_regression.py -v
linkagent eko list
```

**L5 完成的定义：**
- 全部命令绿
- **跨域回归仍然 0 泄漏**（L5 加了更多 EKO，这条更容易破）
- 能从真实对话里产生 EKO
- 未验证的轨迹不入库，沉默不算成功
- 反馈只记在注入过的 EKO 上
- 回滚只动指针
- 用户能看、能导出；能通过**对话**让 agent 忘掉或修订，**不能直接编辑**
- 六个 commit

**⚠ 到这里 LinkAgent 才是一个完整的系统。** 能学、能用、能忘、能回滚。

**下一步**：[`L6-COMPOSITION-AND-CONFLICT.md`](./L6-COMPOSITION-AND-CONFLICT.md)（默认关闭）或直接 [`L7-EVAL-HARNESS.md`](./L7-EVAL-HARNESS.md)（**建议先做 L7**，见 L6 §0）
