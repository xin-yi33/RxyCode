# Phase C · 多 Agent × 多模型协作（Multi-Model Collaboration）

> **在整条路线中的位置**：[`00-EXECUTION-PLAN.md`](./00-EXECUTION-PLAN.md) 的后继扩展，编号 Phase C。
> **前置条件**：主计划 Phase 0/1/2 + [`PHASE-A-MODEL-ADAPTATION-LAYER.md`](./PHASE-A-MODEL-ADAPTATION-LAYER.md) + [`PHASE-B-MULTI-AGENT-ORCHESTRATION.md`](./PHASE-B-MULTI-AGENT-ORCHESTRATION.md) 全部完成。
> **后继**：[`PHASE-D-MULTIMODAL.md`](./PHASE-D-MULTIMODAL.md)
>
> **一句话目标**：让专家团的每个角色跑在**不同的模型**上——Opus 做架构、Grok 写代码、GPT 做审计——由一个独立的 master 模型监测全局、中转消息、在跨模型分歧时仲裁。
>
> **执行模型**：编排与定价逻辑 **Composer 主写**；设置页多模型 UI 卡由 **Composer 主写，多模态环节委托 Grok 辅助**。权威见 [`../MODEL-ASSIGNMENT.md`](../MODEL-ASSIGNMENT.md)。
> **创建**：2026-07-31
> **预计工时**：6 周（1 名后端 + 0.5 名前端）
>
> ⚠️ **Phase C 单独看几乎没有新架构**。它把 Phase A 的模型适配层和 Phase B 的专家团接起来。**真正的难点不是"让不同模型跑起来"，而是"让一个模型的产出对另一个模型有用"**（§2.2）和"成本核算"（§2.3）。

---

## 目录

| 章节 | 内容 |
|---|---|
| [§0 执行手册](#0-执行手册必读) | 执行协议、模型分工、硬性规则 |
| [§1 前置盘点](#1-前置盘点phase-ab-给了什么) | Phase A/B 已经给了什么，还缺什么 |
| [§2 三个真问题](#2-三个真问题) | 跨模型交接、成本核算、失败归因 |
| [§3 目标架构](#3-目标架构) | master 模型、模型绑定、pair-program |
| [§4 任务卡 C1–C12](#4-任务卡) | 逐个执行 |
| [§5 出口检查](#5-phase-c-出口检查) | 怎么算做完 |
| [§6 扩展手册](#6-扩展手册) | 加模型组合、调切换点 |
| [§7 与后续 Phase 的接口](#7-与后续-phase-的接口) | Phase D/E 的预留 |

---

## §0 执行手册（必读）

### 0.1 执行协议

Phase B 的 10 步基础上，加两条：

```
11. COST      跑成本核算测试（C4 之后每张卡都要跑）
              python -m pytest tests/test_agents/test_cost_accounting.py -q

12. HANDOFF   跑跨模型交接测试（C3 之后每张卡都要跑）
              python -m pytest tests/test_agents/test_handoff.py -q
```

### 0.2 三个模型的分工

| 模型 | 干什么 | 不要干什么 |
|---|---|---|
| **Composer 2.5** | **主写全部**：编排路由、master、交接协议；设置页多模型 UI 也由它主写 | 自己编造定价数字 |
| **Grok 4.5** | **查每个模型的真实定价**（C4 必需）、查各家 API 的并发限制、查跨模型 prompt 兼容性；被委托的设置页 UI **多模态环节**（视觉验收）时写前端 | 改编排 Python / 写没有多模态环节的卡本体 |
| **Sonnet 5** | 审 C3（跨模型交接）的 diff——这是最容易出微妙 bug 的一张。写文档（C12） | 长任务连续实现 |

### 0.3 前置自检

```powershell
cd "D:\agent-demo\RxyCode\RxyCode1_1_0"
Test-Path core\providers\__init__.py, config\model_capabilities.py      # Phase A → True True
Test-Path core\agents\coordinator.py, core\agents\budget.py             # Phase B → True True
Test-Path core\agents\teams\software_dev.yaml                           # Phase B → True
python -m pytest tests/test_agents -q                                   # 全绿
python -m evals.cli run --backend agent --mode team --compare-baseline evals\baselines\latest-team.json
```

**最危险的误判是"Phase B 差不多了就开始 C"。** Phase C 会同时暴露 Phase B 所有没测到的隔离问题——只不过这次每个角色用不同模型，症状会更难懂。

### 0.4 硬性规则

| # | 规则 | 依据 |
|---|---|---|
| MC1 | **所有角色 `model=None` 时，行为与 Phase B 逐字节相同** | 回归保护 |
| MC2 | **跨模型交接只传结构化产出，不传原始对话历史** | §2.2 |
| MC3 | **审计角色的模型必须与被审角色不同**，配成一样要报错 | karajan-code 的 cross-AI review |
| MC4 | **预算按成本（美元）核算，token 只是中间量** | §2.3，Opus 与 Grok 单价差一个数量级 |
| MC5 | **模型切换点由 architect 在方案里显式声明**，coder 不得自行切换 | 你的原始要求 |
| MC6 | **pair-program 的 navigator 不得编辑文件** | atmux 的做法 |
| MC7 | **master 模型不参与业务产出**，只调度、中转、仲裁 | Phase B 的 DB2 延续 |
| MC8 | 一张卡一个 commit，可独立 revert | 风险控制 |

---

## §1 前置盘点：Phase A/B 给了什么

### 1.1 已经有的

| 能力 | 来自 | 位置 |
|---|---|---|
| Provider 策略层（DeepSeek / Claude / Qwen / OpenAI） | Phase A | `core/providers/` |
| `ModelCapabilities`（上下文窗口、tokenizer、能力位） | Phase A | `config/model_capabilities.py` |
| per-model prompt variant | Phase A | `core/prompts/` |
| `AgentSpec.model` 字段 | Phase B | `protocol/agents.py`（**Phase B 里全是 `None`**） |
| `AgentRuntime` 隔离运行时 | Phase B | `core/agents/runtime.py` |
| Coordinator 团长（建团/派活/中转/收口） | Phase B | `core/agents/coordinator.py` |
| `ConsultRequest` 跨角色咨询 | Phase B | `core/agents/mailbox.py` |
| 机械验证门 | Phase B | `core/agents/verifier.py` |
| `BudgetGuard`（token / 时长 / 次数） | Phase B | `core/agents/budget.py` |
| `ExecutionMode.TEAM_MULTI_MODEL`（占位） | Phase B | `core/agents/router.py` |
| `ModelRole` + `ModelRouter`（旧的角色→模型映射） | 既有 | `core/governance.py:370-374`、`:409-487` |

### 1.2 Phase C 要补的

| 缺口 | 落在哪张卡 |
|---|---|
| `AgentSpec.model` 真正生效，每个 runtime 用自己的模型 | C1 |
| master 模型独立配置，与业务角色分离 | C2 |
| 跨模型交接：结构化产出 + 上下文转译 | C3 |
| 成本核算：按美元而非 token | C4 |
| 跨模型审计：强制审计模型 ≠ 编码模型 | C5 |
| 模型切换点：architect 在方案里声明 | C6 |
| pair-program：driver + navigator | C7 |
| 失败归因仲裁：master 判"架构错还是实现错" | C8 |
| 并发限制：不同 provider 的 rate limit 各不相同 | C9 |
| Settings / CLI 每角色选模型 | C10 |
| 模型组合评测矩阵 | C11 |

---

## §2 三个真问题

> Phase C 的架构本身很浅。**真正会让你踩坑的是这三件事**，每一件都对应一张重点任务卡。

### 2.1 你的设想与开源现状的对照

你描述的方案，AgentMux（Phase B §2.4 已引用）的配置文件几乎一模一样：

```yaml
roles:
  architect: { model: opus }
  coder:     { provider: codex }
  reviewer:  { model: sonnet }
```

它支持 `claude` / `codex` / `copilot` / `gemini` / `opencode` / `qwen` 六种 CLI。但**它是 tmux 驱动 CLI 进程**，不是 API 调用——它靠的是"你已经买了各家的订阅"，规避了 API 计费。我们走 API，所以成本问题（§2.3）对我们更尖锐。

`local-ai-agent-orchestrator` 的配置更接近我们要的形状：`models` 段分别定义 `planner` / `coder` / `reviewer` / `analyst` / `embedder`，加上 `orchestration` 段管阶段门控与重试。

`atmux` 的 `pair-program` 团队角色对应你说的"grok 和 composer 共同写代码"：

> driver：pair-programming 工作流中负责实现的那一半，快模型，写代码、跑测试、响应 navigator 的反馈。
> navigator：负责审查的那一半，强模型，盯着共享 worktree 的滚动 diff，在实现漂移时打断 driver 并给出修正意见，**自己不编辑文件**。

**结论：你的设想在业界有对应实现，不需要发明新范式。Phase C 是工程活，不是研究活。**

### 2.2 真问题一：跨模型交接

**这是 Phase C 最大的技术难点，也最容易被低估。**

同一个模型内部，上一轮的输出和这一轮的输入是同构的——同样的对话格式、同样的推理风格、同样的隐含约定。**跨模型时这些全都不成立**：

| 差异 | 后果 |
|---|---|
| 推理痕迹格式不同（reasoning content、thinking block） | 直接把 Claude 的 thinking 塞给 DeepSeek，是纯噪音 |
| 对 markdown / XML / JSON 的偏好不同 | Opus 产出的嵌套 XML 方案，Grok 可能解析得很差 |
| 工具调用格式不同 | Phase A 的 provider 层已解决，但**历史里的工具调用记录**格式仍不通用 |
| 上下文窗口差一个数量级 | Opus 写的 30k token 方案，塞不进小窗口模型 |
| 隐含约定不同 | "按上面说的做"这种指代，换个模型就断了 |

**解法（MC2）：跨模型交接只传结构化产出，不传原始对话历史。**

这正好是 MetaGPT 的做法——*"agents communicate via structured documents and diagrams published to a shared message pool"*，而不是自由对话。Phase B 的黑板（`blackboard.py`）已经是这个形状，Phase C 只需要**强制**它。

具体地：

```
Phase B（同模型）：
  architect 产出 → 黑板 → coder 读黑板 + 可能还带一些上下文

Phase C（跨模型）：
  architect 产出 → 【交接转译】→ 黑板 → coder 只能读黑板
                      ↑
              目标模型窗口装不下时在这里压缩
              带推理痕迹时在这里剥离
              格式偏好不同时在这里规范化
```

### 2.3 真问题二：成本核算

Phase B 的预算是 token 数。**跨模型时 token 数几乎没有意义**，因为单价差一个数量级以上：

| | 相对单价量级 |
|---|---|
| 顶级推理模型（Opus 级） | 高 |
| 主力编码模型（Sonnet / Grok 级） | 中 |
| 国产高性价比模型（DeepSeek / Qwen 级） | 低 |

> **具体数字由 Grok 在 C4 查证后填入**，不要在文档里写死过期价格。C4 的 Grok prompt 见任务卡。

一个"500k token 预算"在全 Opus 的团队和全 DeepSeek 的团队之间，实际花费可能差 20 倍。

**解法（MC4）：预算按美元核算。** `ModelCapabilities` 加定价字段，每次 LLM 调用换算成成本累加，`BudgetGuard` 检查的是成本。

这还带来一个附加价值：**你可以做"便宜模型先试，失败了才升级"的策略**——这是多模型协作真正省钱的地方，而不只是"用不同模型"。

### 2.4 真问题三：失败归因

你的原话：

> 当我测试或者审计的时候发现问题，我 gpt 就要和架构和代码编写沟通问题，看看是架构出了问题还是代码编写出了问题。

Phase B 的 `ConsultRequest` 给了通道，`software_dev.yaml` 的 auditor 也被要求把每条发现标注「方案问题」或「实现问题」。**但审计员的判断可能是错的**——它说"方案问题"，架构师说"不，是你实现的时候没按方案来"。

**这时候需要仲裁，而仲裁正是你说的 master 的职责。**

Phase B 的 Coordinator 只做机械的中转。Phase C 要给它一个**独立的模型**和一项**仲裁职责**：当审计员和架构师对同一个问题的归因不一致时，master 读双方陈述 + 方案原文 + 实际 diff，做出裁决，然后把任务打回给正确的角色。

**这是 Phase C 里唯一新增的 LLM 决策点。** 和 Phase B 的 DB4 一样，它必须是显式标注、进 trace 的。

---

## §3 目标架构

### 3.1 全景图

```
ModeRouter → TEAM_MULTI_MODEL
   │
   ▼
┌──────────────────────────────────────────────────────────────────┐
│ Coordinator「团长 / master」                                       │
│  模型：settings.agents.master_model（用户自选，独立于所有业务角色） │
│                                                                    │
│  Phase B 的四项职责：建团 / 派活 / 中转 / 收口                      │
│  Phase C 新增：                                                    │
│    ⑤ 交接转译   跨模型时压缩、剥离推理痕迹、规范化格式（C3）        │
│    ⑥ 成本守门   按美元核算，接近上限时降级或停止（C4）              │
│    ⑦ 归因仲裁   审计员与架构师归因冲突时裁决（C8）                  │
│                                                                    │
│  它自己不写代码、不产出业务成果（MC7）                              │
└───┬────────────────────────────────────────────────────────────┬─┘
    │                                                             │
    ▼                                                             ▼
┌───────────────────────┐                          ┌──────────────────────┐
│ HandoffTranslator     │                          │ CostGuard            │
│  剥离推理痕迹          │                          │  按 $ 而非 token     │
│  窗口不够时压缩        │                          │  per-role 成本可见   │
│  格式规范化            │                          │  接近上限时降级      │
└───────────────────────┘                          └──────────────────────┘
    │
    ▼
┌──────────────────────────────────────────────────────────────────┐
│ Blackboard「唯一的跨模型通道」                                     │
│  跨模型时，成员**只能**读黑板，读不到别人的对话历史（MC2）          │
└───┬──────────────────────────────────────────────────────────────┘
    │
    ├────────────┬──────────────┬─────────────┬─────────────┐
    ▼            ▼              ▼             ▼             ▼
 architect     coder         navigator     verifier      auditor
 Opus 级       Grok 级       Composer 级    无模型         GPT 级
 只读工具      全部工具       只读工具       纯确定性       只读工具
                  ↑              │
                  └── pair-program ──┘
                  driver 写 · navigator 盯 diff 不写（MC6）

              审计模型必须 ≠ 编码模型（MC3）
```

### 3.2 七条不可违反的设计约束

| # | 约束 | 依据 |
|---|---|---|
| DC1 | 全 `model=None` 时行为与 Phase B 逐字节相同 | 回归保护 |
| DC2 | **跨模型交接只走黑板的结构化产出**，成员读不到别的模型的对话历史 | §2.2 |
| DC3 | **审计模型 ≠ 被审模型**，配置阶段就校验 | karajan-code |
| DC4 | **预算按美元**，`ModelCapabilities` 必须带定价 | §2.3 |
| DC5 | **模型切换点由 architect 在方案里声明**，落在 `plan` 的结构化字段里，不是自然语言 | 你的要求 + 可校验 |
| DC6 | **navigator 不得持有写工具**，构造时校验 | atmux |
| DC7 | **master 不产出业务成果**，只调度/中转/仲裁 | Phase B DB2 延续 |

### 3.3 文件布局（**不要改**）

```
core/agents/
  handoff.py                 # C3 跨模型交接转译
  cost.py                    # C4 成本核算（BudgetGuard 的成本维度）
  arbiter.py                 # C8 归因仲裁
  pairing.py                 # C7 driver/navigator
  teams/
    software_dev_multi.yaml  # C10 多模型版软件开发专家团
config/
  model_pricing.py           # C4 定价表
tests/test_agents/
  test_multi_model.py
  test_handoff.py            # C3 之后每张卡都跑
  test_cost_accounting.py    # C4 之后每张卡都跑
  test_arbiter.py
  test_pairing.py
```

---

## §4 任务卡

### C1 · 让 `AgentSpec.model` 真正生效

`P0` / 4d / 依赖 Phase A + Phase B

**背景**
Phase B 已经有 `AgentSpec.model` 字段，但全是 `None`。这张卡让它接上 Phase A 的 provider 层。**改动很小，但它是后面所有卡的地基。**

**涉及文件**
- 改 `core/agents/runtime.py`、`core/agents/spec.py`
- 新建 `tests/test_agents/test_multi_model.py`

**操作步骤**

1. `AgentRuntime._build_llm` 按 `spec.model` 解析：

```python
    def _build_llm(self, spec: AgentSpec):
        """按角色解析模型。

        spec.model is None → 用会话默认模型，行为与 Phase B 完全一致（DC1）。
        否则走 Phase A 的 provider 层解析，每个角色拿到自己的 llm /
        provider / capabilities 三元组。

        注意 capabilities 是 per-role 的：不同角色的上下文窗口、tokenizer、
        是否支持 function calling 都可能不同，后续所有跟 token 计数、上下文
        压缩相关的逻辑都必须用 self._capabilities，不能用全局默认。
        """
        model_name = spec.model or self._session.default_model
        provider = resolve_provider(model_name)
        caps = provider.capabilities(load_model_config(model_name))
        llm = build_llm(model_name, provider, caps)
        return llm, provider, caps
```

2. **把所有硬编码的"默认上下文窗口"改成读 `runtime._capabilities`**。用 Grep 找：

```powershell
Select-String -Path core\*.py,core\agents\*.py,memory\*.py -Pattern "context_window|compaction_threshold|max_tokens|256_000|232_000" -Recurse |
  ForEach-Object { "$($_.Path -replace '.*RxyCode1_1_0\\',''):$($_.LineNumber): $($_.Line.Trim())" }
```

**每一处都要确认它用的是当前角色的能力，不是全局默认。** 这是 Phase C 最容易漏的地方——症状是"小窗口模型的角色莫名其妙超上下文"。

3. `validate_team` 加校验：`spec.model` 不为 `None` 时，该模型必须在配置里存在。**配错模型名要在加载时就报错**，不能等到跑到那个阶段才炸。

4. `tests/test_agents/test_multi_model.py`：

```python
def test_all_none_models_behave_identically_to_phase_b():   # DC1
def test_each_runtime_gets_its_own_llm():
def test_each_runtime_gets_its_own_capabilities():
def test_unknown_model_name_fails_at_team_load_time():
def test_context_window_comes_from_role_capabilities_not_global():
```

**验收命令**

```powershell
python -m pytest tests/test_agents/test_multi_model.py -q
python -m pytest tests/test_agents -q
python -m evals.cli run --backend agent --mode team --compare-baseline evals\baselines\latest-team.json
```

**完成判据**
- [ ] 全 `None` 时 evals 零回归（DC1）
- [ ] 每个 runtime 有独立的 llm 和 capabilities
- [ ] 第 2 步的 grep 清单逐条核对完，贴进 PR
- [ ] 错误模型名在加载时报错

**Commit**
```
feat(agents): bind per-role models through the Phase A provider layer
```

---

### C2 · master 模型独立配置

`P0` / 3d / 依赖 C1

**背景**
你要的"master model 进行整个业务的监测"。它必须能独立选型——master 需要的是判断力和长上下文，与写代码的模型要求不同。

**操作步骤**

1. `TeamSpec` 加 `master_model: str | None = None`（`None` = 用会话默认）。

2. `Coordinator` 用 master 模型构造自己的 LLM，**且它的工具集依然是空的**（Phase B 的约束，Phase C 不放松）。

3. **加一条显式校验（MC7）**：

```python
def _assert_master_produces_nothing(coordinator: Coordinator) -> None:
    """master 不得产出业务成果。

    它可以调度、中转、压缩、仲裁，但不能往黑板写业务产出（黑板写入的
    author_role 必须是某个成员角色，不能是 master）。

    这条约束存在的理由：master 一旦开始干活，就会和成员抢它最宝贵的全局
    上下文，而且它的产出没有经过机械验证门和审计。
    """
```

在 `Blackboard.put` 里校验 `author_role != "master"`，违反直接抛异常。

4. master 自己的 token / 成本单独统计，在 trace 里可见——**因为它会调用得很频繁（每次中转、每次转译都是一次调用），很容易变成成本大头**。

**完成判据**
- [ ] master 模型可独立配置
- [ ] master 工具集为空（有断言）
- [ ] master 不能往黑板写业务产出（有测试）
- [ ] master 的成本单独可见

---

### C3 · 跨模型交接转译

`P0` / 1.5 周 / 依赖 C1 C2

**背景**
§2.2 的解法。**这是 Phase C 技术含量最高的一张卡，让 Sonnet 5 重点审。**

**操作步骤**

1. `core/agents/handoff.py`：

```python
"""跨模型交接转译。

同模型内部，上一轮输出和下一轮输入是同构的。跨模型时不成立：推理痕迹格式
不同、markdown/XML 偏好不同、上下文窗口差一个数量级、"按上面说的做"这类
指代会断掉。

解法参考 MetaGPT：agents 通过发布到共享消息池的**结构化文档**通信，而不是
自由对话。Phase B 的黑板已经是这个形状，这里强制它并补上转译。

三个步骤，按顺序：
  1. strip   剥离源模型特有的推理痕迹（thinking block、reasoning content）
  2. shape   规范化成目标模型偏好的格式
  3. fit     目标窗口装不下时压缩
"""

class HandoffTranslator:
    def translate(
        self,
        content: str,
        *,
        source_caps: ModelCapabilities,
        target_caps: ModelCapabilities,
    ) -> HandoffResult:
        ...
```

2. **步骤 1 · strip**——按 `source_caps.provider` 剥离：

| 源 provider | 要剥离的 |
|---|---|
| Anthropic | `<thinking>` 块 |
| DeepSeek(reasoner) | `reasoning_content` 字段 |
| OpenAI(o 系列) | reasoning summary |
| 通用 | 工具调用的原始 JSON 记录（保留人类可读的摘要） |

**具体字段名让 Grok 查**（见下方 prompt）。

3. **步骤 2 · shape**——按 `target_caps.prompt_variant` 规范化。保守起见，**第一版统一转成 markdown**（所有模型都能处理），不做 per-model 精细适配。等 C11 的评测显示某个组合有问题再优化。

4. **步骤 3 · fit**——用 `target_caps.tokenizer` 计数（Phase A 已有），超过 `target_caps.compaction_threshold` 的一定比例时压缩。**压缩要保留结构**：

```python
    def _fit(self, content: str, target_caps: ModelCapabilities) -> str:
        """压缩到目标窗口内。

        压缩必须保结构。实现方案的"文件清单"和"验收标准"是后续阶段和机械
        验证门要用的，压没了整条流水线就断了。

        优先级（从最该保留到最先丢弃）：
          1. 文件清单与验收标准     绝不压缩
          2. 每个文件的改动要点     可以精简措辞
          3. 背景说明与权衡讨论     可以大幅压缩
          4. 示例代码               超长时先丢
        """
```

5. **`Coordinator` 在跨模型派发时调用它**。同模型时（`source_caps is target_caps`）**直接跳过**，保证 DC1。

6. `tests/test_agents/test_handoff.py`（**C3 之后每张卡都跑**）：

```python
def test_same_model_handoff_is_a_no_op():                    # DC1 关键
def test_anthropic_thinking_blocks_are_stripped():
def test_deepseek_reasoning_content_is_stripped():
def test_output_is_markdown_regardless_of_source_format():
def test_fit_respects_target_context_window():
def test_fit_never_drops_the_file_list():                    # 最关键
def test_fit_never_drops_acceptance_criteria():              # 最关键
def test_translation_is_recorded_in_trace():
def test_members_cannot_read_other_models_raw_history():     # MC2
```

**Grok 的调研 prompt**

```
我需要三家 API 在响应里返回"推理痕迹"的准确字段名和格式，用于在跨模型交接
时剥离它们。请只依据 2026 年当前的官方 API 文档回答，给出文档链接。

1) Anthropic Messages API：extended thinking 在响应 content 数组里的
   block type 叫什么？完整的 JSON 结构是什么？
2) DeepSeek deepseek-reasoner：响应里承载推理链的字段名是什么？它在
   message 对象的哪一层？
3) OpenAI o 系列 / GPT-5 系列：reasoning summary 在响应里的字段路径是什么？

另外回答：把 A 模型带推理痕迹的原始响应直接作为 B 模型的输入上下文，各家
文档里有没有明确的警告或建议？

只回答文档里明确写了的。不确定的标"未找到"，不要推测。
```

**完成判据**
- [ ] 同模型交接是 no-op（DC1 关键）
- [ ] 三家的推理痕迹都能剥离，字段名有 Grok 的文档出处
- [ ] 压缩绝不丢文件清单和验收标准（两个专门的测试）
- [ ] 成员读不到别的模型的对话历史（MC2 的测试）
- [ ] 转译进 trace
- [ ] Sonnet 5 审过 diff

---

### C4 · 成本核算

`P0` / 1 周 / 依赖 C1

**背景**
§2.3。Phase B 的 token 预算跨模型时几乎没有意义。

**操作步骤**

1. `ModelCapabilities` 加定价字段（**扩展 Phase A 的结构**）：

```python
@dataclass(frozen=True)
class ModelPricing:
    """每百万 token 的美元单价。

    定价会变。这张表是"参考值"，用途是成本预算和相对比较，不是账单。
    实际账单以各家控制台为准。表里带 as_of 日期，过期太久要提醒更新。
    """
    input_per_mtok: float
    output_per_mtok: float
    cached_input_per_mtok: float | None = None
    as_of: str = ""              # YYYY-MM-DD
```

2. `config/model_pricing.py` 存表，**每条都要有 `as_of` 和来源链接注释**。未知模型的定价缺失时：**不要静默当 0**，要么用一个保守的高估值，要么明确警告"该模型无定价数据，成本统计不准"。

3. `core/agents/cost.py`：

```python
"""成本核算。

Phase B 的 BudgetGuard 按 token 计数。跨模型时 token 数没有可比性——顶级
推理模型和高性价比模型的单价能差一个数量级，同样 500k token 的预算实际花费
可能差 20 倍。

这里把 token 换算成美元，BudgetGuard 检查的是美元。
"""

class CostAccountant:
    def record(self, role: str, usage: dict, caps: ModelCapabilities) -> float:
        """记一次调用，返回本次成本（美元）。

        用 provider 的 extract_* 方法（Phase A）拿真实的 input/output/cached
        token 数——各家字段名不同，不能假设是 OpenAI 格式。
        """

    def by_role(self) -> dict[str, float]:
        """按角色的成本分布。这是用户最想看的数字。"""
```

4. `BudgetGuard` 加成本闸门：`TeamSpec.total_cost_budget_usd`（默认给一个保守值，例如 1.0）。

5. **接近上限时的降级策略**（这是多模型真正省钱的地方）：

```python
    def on_approaching_limit(self) -> DegradeAction:
        """成本接近上限时的降级。

        按代价从小到大：
          1. 跳过可选阶段（例如 pair-program 的 navigator）
          2. 把还没跑的角色降到更便宜的模型
          3. 停止并返回部分结果

        每一步都要通知用户，不能悄悄降级——用户以为在用 Opus 结果跑的是
        便宜模型，这比直接失败更糟。
        """
```

6. `tests/test_agents/test_cost_accounting.py`（**C4 之后每张卡都跑**）：

```python
def test_cost_is_computed_from_provider_specific_usage_fields():
def test_missing_pricing_does_not_silently_count_as_zero():
def test_cached_input_is_priced_differently():
def test_cost_budget_stops_the_team():
def test_by_role_breakdown_sums_to_total():
def test_degradation_notifies_the_user():
def test_stale_pricing_emits_a_warning():
```

**Grok 的调研 prompt**

```
我需要以下模型 2026 年当前的官方 API 定价，单位美元每百万 token，分别给出
输入价、输出价、缓存输入价（如果有）。**只用各家官方定价页**，给出链接和
你查阅的日期。

- Anthropic: Claude 的旗舰级与主力级模型
- OpenAI: GPT 旗舰与 mini 档
- DeepSeek: chat 与 reasoner
- xAI: Grok 当前主力
- 阿里云: Qwen 主力商用档

另外回答：
1) 有没有哪家的缓存输入是按"写入"和"读取"分别计价的？
2) 有没有哪家对推理 token（reasoning tokens）单独计价或计入输出？

不确定的标"未找到"，不要用训练数据里的旧价格。
```

**完成判据**
- [ ] 定价表每条有 `as_of` 和来源
- [ ] 定价缺失不静默当 0
- [ ] 成本闸门能触发
- [ ] 按角色的成本分布可见
- [ ] 降级会通知用户
- [ ] 定价过期有警告

---

### C5 · 强制跨模型审计

`P0` / 3d / 依赖 C1

**背景**
MC3。抄 karajan-code：审查结论要来自**一个不同的 AI**。同一个模型审自己写的代码，会系统性地漏掉同一类错误。

**操作步骤**

1. `validate_team` 加校验：

```python
def _check_auditor_uses_a_different_model(team: TeamSpec) -> None:
    """审计角色的模型必须与它审查的角色不同。

    抄 karajan-code 的 cross-AI review：审查结论绑定到 diff 的哈希，且必须
    来自不同的 AI。同模型自审会系统性地漏掉同一类错误——它看不出自己的
    盲区，因为那正是盲区的定义。

    只在多模型模式下强制。Phase B 的同模型专家团豁免（那时候审计的价值主要
    来自不同的 prompt 和不同的上下文，而不是不同的模型）。
    """
```

2. 审计阶段和被审阶段的模型解析到同一个 `(provider, model)` 时，**加载团队就报错**，错误信息要明确说清怎么改。

3. Phase B 的 `VerdictRecord` 加 `auditor_model: str`，让审计结论可追溯到具体模型。

4. 测试：同模型配置被拒、不同模型通过、同模型但 Phase B 模式不拒、`VerdictRecord` 带模型名。

**完成判据**
- [ ] 同模型审计在加载时被拒，错误信息可操作
- [ ] Phase B 同模型模式不受影响
- [ ] `VerdictRecord` 记录审计模型

---

### C6 · 模型切换点由架构师声明

`P1` / 1 周 / 依赖 C1 C3

**背景**
你的原话：

> 我 opus5 中就要写清楚到哪个地方就要切换模型进行代码编写。

MC5。关键设计选择：**切换点必须是结构化字段，不能是自然语言**。写在自然语言里就只能靠正则去猜，而且没法校验。

**操作步骤**

1. `plan` 阶段的 `expected_output` 要求架构师产出结构化的切换点声明。在黑板里存成：

```python
class ModelSwitchPoint(BaseModel):
    """架构师声明的模型切换点。

    结构化而非自然语言，理由：能校验（角色存在吗、模型配了吗）、能 trace、
    能在 UI 上展示。自然语言的切换指示只能靠正则去猜，而且没法在执行前
    发现"你指定的模型根本没配"。
    """
    #: 从计划的第几个子任务开始生效
    from_task_index: int
    #: 切给哪个角色
    role: str
    #: 用哪个模型。必须在配置里存在。
    model: str
    #: 为什么切（进 trace 和 UI，也帮你事后判断这个切换值不值）
    reason: str
```

2. 架构师用 function calling / structured output 产出（Phase A 的 `structured_output` 能力位在这里派上用场）。**架构师模型不支持结构化输出时，退回到"不切换"并警告**，不要用正则从自然语言里抠。

3. `Coordinator` 在派发前应用切换点：给对应角色临时换模型，**换模型时必须走 C3 的交接转译**（因为源和目标 capabilities 变了）。

4. **校验**：切换点里的 `role` 必须在团队里、`model` 必须在配置里、`from_task_index` 必须在范围内。任何一条不满足就**忽略该切换点并警告**，不要让整个流程失败。

5. 测试：合法切换点生效、非法角色被忽略并警告、未配置模型被忽略并警告、切换时触发交接转译、架构师不支持结构化输出时的退化路径。

**完成判据**
- [ ] 切换点是结构化数据
- [ ] 三类非法切换点都被忽略并警告，不导致流程失败
- [ ] 切换触发交接转译
- [ ] 架构师模型不支持结构化输出时有明确的退化路径
- [ ] 切换点和理由进 trace

---

### C7 · pair-program：driver + navigator

`P1` / 1 周 / 依赖 C1 C3

**背景**
你的原话：

> 我代码编写想用 grok 和 composer 共同协作。

抄 atmux 的 `pair-program` 团队角色：driver（快模型）写代码，navigator（强模型）盯 diff、发现漂移就打断，**自己不编辑文件**。

**操作步骤**

1. `AgentSpec.extra` 用 Phase B 预留的字段：

```yaml
  - role: coder
    model: <快模型>
    extra:
      pair_with: navigator

  - role: navigator
    model: <强模型>
    tools: [read_file, grep, list_dir]     # 只读，MC6 会校验
    extra:
      pair_role: navigator
      review_every_n_edits: 3
```

2. `core/agents/pairing.py`：

```python
"""driver / navigator 结对。

抄 atmux 的 pair-program 团队角色：driver 是快模型，写代码、跑测试；
navigator 是强模型，盯着滚动 diff，在实现漂移时打断并给出修正意见，
**自己不编辑文件**（MC6）。

打断不是抢占——driver 的当前工具调用会跑完，navigator 的意见作为下一轮
的输入注入。真正的抢占式打断在我们的执行模型里做不了，也没必要。
"""
```

3. **触发时机**：每 N 次文件编辑之后，或者机械验证失败之后。**不要每次工具调用都触发**——navigator 用的是贵模型，频繁触发会让成本失控。

4. **MC6 的强制校验**：navigator 的工具集含任何写工具（`write_file` / `edit_file` / `run_shell` 等）时，**加载团队就报错**。

5. **成本上必须是可选的**：C4 的降级策略第一步就是跳过 navigator。

6. 测试：navigator 有写工具时被拒、按编辑次数触发、navigator 的意见进入 driver 下一轮、navigator 不产生文件改动、降级时被跳过。

**完成判据**
- [ ] navigator 持有写工具时加载失败
- [ ] 触发频率可配置，默认不过密
- [ ] navigator 的意见能影响 driver
- [ ] 降级时能跳过
- [ ] 测出 pair-program 相比单 driver 的成本增量，写进文档

---

### C8 · 归因仲裁

`P1` / 1 周 / 依赖 C2 C3

**背景**
§2.4。审计员说"方案问题"，架构师说"是实现没按方案来"——**master 裁决**。这是你说的 master 传话人职责的最高形态。

**操作步骤**

1. `core/agents/arbiter.py`：

```python
"""归因仲裁。

审计员会给每条发现标注「方案问题」或「实现问题」（见 software_dev.yaml 的
auditor constraints）。架构师可能不同意。这时候需要裁决，否则任务会在
implement 和 plan 之间反复打回，直到撞上 max_delegations。

master 拿到四份材料：
  1. 审计发现（含它给的归因）
  2. 架构师对该发现的反驳（通过 ConsultRequest 拿到）
  3. 方案原文（黑板 plan 条目）
  4. 实际 diff

裁决三选一：
  PLAN_ISSUE   → 打回 plan 阶段，架构师改方案
  IMPL_ISSUE   → 打回 implement 阶段，coder 按原方案重做
  NOT_AN_ISSUE → 驳回该条发现，继续流程

这是 Phase C 唯一新增的 LLM 决策点。它必须进 trace（和 Phase B 的 DB4
同一条规则）。
"""
```

2. **只在真的有分歧时触发**。审计员说"实现问题"、架构师没有异议时，直接打回 coder，**不要浪费一次 master 调用**。

3. **仲裁次数上限**（默认 3 次）。超了就按审计员的归因走，并告知用户"仲裁次数用尽，按审计意见处理"。**这是防止 master 自己陷入循环**。

4. 仲裁结论要写进黑板，**带完整理由**——这样后续阶段能看到"这个问题已经裁决过了，是实现问题"，不会重复争论。

5. 测试：无分歧时不调用 master、有分歧时三种裁决各自的后续动作、仲裁次数上限、仲裁结论进黑板、仲裁进 trace。

**完成判据**
- [ ] 无分歧时不调用 master（有测试）
- [ ] 三种裁决都有正确的后续动作
- [ ] 仲裁次数上限能触发
- [ ] 仲裁结论和理由进黑板与 trace

---

### C9 · 并发与限流

`P1` / 5d / 依赖 C1

**背景**
不同 provider 的 rate limit 各不相同。多模型团队会同时打几家 API，**一家被限流不该拖垮全队**。

**操作步骤**

1. **per-provider 并发信号量**，不是全局一个。配置在 provider 层（Phase A）。
2. **per-provider 重试策略**：各家的 429 响应头和建议退避时间不同（让 Grok 查 `Retry-After` / `x-ratelimit-*` 的具体形式）。
3. Phase B 的 breaker key 已经按 agent 分了，**这里再按 provider 分一层**——同一个 provider 的多个角色应该共享熔断状态（因为限流是 provider 级的），但不同 provider 之间不连坐。
4. 一家 provider 熔断时，Coordinator 的处理：该角色的阶段失败 → 走 SOP 的 `next_on_failure` → 如果配了降级模型就换，没配就报明确的错。

**完成判据**
- [ ] per-provider 并发限制可配
- [ ] 一家 429 不影响其他 provider 的角色
- [ ] provider 级熔断与 agent 级熔断的关系有测试和文档说明

---

### C10 · Settings 与 CLI 适配

`P1` / 1 周 / 依赖 C1–C8，依赖主计划 Phase 2

**背景**
你的原话：

> 无论是 desktop 的前端还是 cli 我们都要做一定的适配……可以做一个按钮，在 setting 中确认这种多 agent+多模型协作模式是否打开，如果打开才需要填写那么多。

**操作步骤**

1. **Settings 三层折叠**（Phase B 的两层再加一层）：

```
[ ] 启用多 Agent 专家团                          ← Phase B，默认关
    专家团        [软件开发 ▾]
    路由模式      (•) 自动判断
    难度判断模型  [不使用 ▾]
    成本预算      [$1.00]

    [ ] 启用多模型协作                            ← Phase C，默认关
        └─ 打开后才显示：
           Master 模型   [___________ ▾]   ← 调度、中转、仲裁
           架构师        [___________ ▾]
           编码员        [___________ ▾]
           审计员        [___________ ▾]   ← 会校验不能与编码员相同
           [ ] 启用结对编程
               └─ Navigator [_______ ▾]

           预估成本：$0.42 / 次   ← 按当前组合和历史均值实时算
           ⚠ 审计员与编码员不能是同一个模型
```

2. **实时预估成本**（用 C4 的定价表 + 历史平均 token 用量）。这是让用户对多模型的代价有直观感受的最有效手段。

3. **配置校验即时反馈**：审计员 = 编码员时当场标红，不等到运行时。

4. **CLI（OpenTUI）**：

| 命令 | 效果 |
|---|---|
| `/team-multi <任务>` | 强制多模型专家团 |
| `/models` | 显示当前各角色的模型绑定 |
| `/cost` | 显示本次会话按角色的成本分布 |

状态行显示当前角色 + 模型 + 累计成本：

```
[coder · grok] 正在实现... 45.2s · $0.18/$1.00
```

5. **Desktop**（主计划 Phase 3 完成后）：委派树上每个节点标注模型和成本；成本饼图按角色分。

6. 协议：`ModelSwitchPoint`、`CostBreakdown`、`ArbitrationRecord` 进 `protocol/`，重新生成 TS 类型。

**完成判据**
- [ ] 三层折叠，关闭时完全隐藏
- [ ] 实时成本预估可用
- [ ] 审计员=编码员即时标红
- [ ] 三个 CLI 命令可用
- [ ] 状态行显示角色、模型、成本
- [ ] TS 类型已生成并提交

---

### C11 · 模型组合评测矩阵

`P1` / 1 周 / 依赖 C1–C9

**背景**
**这张卡回答一个价值上万元的问题：哪个模型组合最划算？**

**操作步骤**

1. `evals/cli.py` 加 `--team-config <yaml>`，能跑指定的模型组合。

2. 至少测五组：

| 组合 | 架构 | 编码 | 审计 | 假设 |
|---|---|---|---|---|
| all-cheap | 便宜 | 便宜 | 便宜 | 成本下限基线 |
| all-strong | 强 | 强 | 强 | 质量上限基线 |
| **你的设想** | 顶级推理 | 主力编码 | 另一家 | 假设这个最优 |
| cheap-arch | 便宜 | 强 | 强 | 架构真的需要贵模型吗 |
| cheap-audit | 强 | 强 | 便宜 | 审计真的需要贵模型吗 |

3. 产出矩阵：

```
Combo          Pass rate   Cost/task   Duration   Arbitrations   Retries
solo(baseline)     68%       $0.09       41.7s          —           —
all-cheap          ??%       $?.??       ??.?s         ?.?         ?.?
all-strong         ??%       $?.??       ??.?s         ?.?         ?.?
your-design        ??%       $?.??       ??.?s         ?.?         ?.?
cheap-arch         ??%       $?.??       ??.?s         ?.?         ?.?
cheap-audit        ??%       $?.??       ??.?s         ?.?         ?.?
```

4. **重点看两个派生指标**：
   - **每提升 1 个百分点通过率的边际成本**——这是决定"值不值"的唯一数字
   - **仲裁次数**——高说明架构和编码模型"合不来"，这个组合有摩擦

5. **诚实写结论。** 三种可能的结果都要能接受：
   - 多模型明显更好 → 写进推荐配置
   - 多模型不比全强模型好但更便宜 → 也是胜利，写进推荐
   - **多模型又贵又不好 → 把它默认关闭，在文档里明说，并保留能力给用户自己选**

**完成判据**
- [ ] 五组配置都跑过，矩阵已提交
- [ ] 边际成本和仲裁次数已分析
- [ ] 推荐配置写进 settings 默认值
- [ ] 结论（含负面结论）写进文档

---

### C12 · 文档

`P1` / 5d / 依赖 C1–C11

1. 新建 `docs/modules/multi_model.md`：
   - §2 的三个真问题及解法
   - 七条设计约束（§3.2）
   - 跨模型交接的三步（strip / shape / fit）
   - 成本核算与降级策略
   - **C11 的评测矩阵和推荐配置**
   - **明确写"什么时候不该用多模型"**
2. 更新 `docs/modules/agents.md`（多模型章节）、`config.md`（定价表维护）、`frontend.md`（三层 settings）。
3. 更新 `AGENTS.md`。
4. **`config/model_pricing.py` 加一条 README 说明谁负责定期更新定价**——这是唯一会自然过期的数据。

---

## §5 Phase C 出口检查

```powershell
cd "D:\agent-demo\RxyCode\RxyCode1_1_0"
python -m ruff check .
python -m pytest tests -q --timeout=900
python -m pytest tests/test_agents -q
python -m evals.cli run --backend agent --mode solo --compare-baseline evals\baselines\latest-agent.json
python -m evals.cli run --backend agent --mode team  --compare-baseline evals\baselines\latest-team.json
python -m evals.cli run --backend agent --mode team_multi --save-baseline
```

**Phase C 完成的定义：**
- 前 5 条全绿，**solo 和 team 两条基线都零回归**（DC1）
- 每角色不同模型能端到端跑通
- master 模型独立配置，且不产出业务成果
- 跨模型交接不丢文件清单和验收标准
- 成本按美元核算，降级会通知用户
- 审计模型 ≠ 编码模型有强制校验
- 架构师声明的切换点能生效
- pair-program 可用且 navigator 不写文件
- 归因仲裁只在有分歧时触发
- **C11 的矩阵已产出，推荐配置和负面结论都写进了文档**

---

## §6 扩展手册

### 6.1 加一个模型组合

1. 复制 `core/agents/teams/software_dev_multi.yaml`
2. 改各角色的 `model`
3. 静态校验（会检查审计≠编码、模型存在、navigator 只读）：

```powershell
python -c "from pathlib import Path; from core.agents.spec import load_team; load_team(Path('core/agents/teams/<新组合>.yaml')); print('ok')"
```

4. 跑评测并加进 C11 的矩阵
5. **边际成本算不过账就不要留在默认配置里**

### 6.2 更新定价

1. 改 `config/model_pricing.py`，**同时更新 `as_of`**
2. 跑 `python -m pytest tests/test_agents/test_cost_accounting.py -q`
3. 重跑 C11 矩阵——定价变了，最优组合可能也变了

### 6.3 调整交接转译

1. 改 `core/agents/handoff.py`
2. **`test_fit_never_drops_the_file_list` 和 `test_fit_never_drops_acceptance_criteria` 必须还绿**——这两条是流水线不断的保证
3. 跑跨模型 evals 确认没退化

---

## §7 与后续 Phase 的接口

| 预留 | 给谁 | 约束 |
|---|---|---|
| `HandoffTranslator` 的输入类型 | **Phase D** 多模态 | 现在是 `str`，Phase D 会拓宽成 content block。**不要在别处假设它一定是纯文本** |
| `AgentSpec.extra` | **Phase D / E** | Phase D 放 `requires_vision`；Phase E 放 `persona_id` 和 `skills` |
| `ModelCapabilities.supports_vision`（Phase A 已有） | **Phase D** | Phase D 的视觉角色靠它做能力校验 |
| `CostAccountant` | **Phase D** | 图像 token 计费方式与文本不同，Phase D 要扩展 |
| `ModelSwitchPoint` | **Phase E** | Persona 会需要"按 persona 切模型"，复用这个结构 |
| 定价表 `as_of` 机制 | **Phase E** | 蒸馏需要对比"教师模型成本 vs 学生模型成本"，直接用这张表 |
| `Blackboard` 的结构化产出 | **Phase E** | 蒸馏的训练数据来源就是黑板上的高质量产出 —— 见 `PHASE-E-PERSONA-AGENT-INTERFACE.md` §3.2 |
