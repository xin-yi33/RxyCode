# Phase E · PersonaAgent 接口预留（Interface Reservation）

> **在整条路线中的位置**：[`00-EXECUTION-PLAN.md`](./00-EXECUTION-PLAN.md) 之后的**开放式扩展位**，编号 Phase E。
> **前置条件**：无硬前置。§4 的预留卡**要在 Phase B/C/D 执行过程中顺手做掉**，§5 的实现留到你想清楚再说。
>
> **这份文档和 A/B/C/D 不是一类东西。**
>
> A/B/C/D 是"照着做就能做完"的施工图。**Phase E 是一张地基预留图**——它不告诉你 PersonaAgent 怎么建，只保证你以后想建的时候，不用把已经盖好的楼拆掉。
>
> **创建**：2026-07-31
> **§4 预留卡工时**：合计约 6 天，分散在 Phase B/C/D 里做
> **§5 实现工时**：未估算（设计未定）
>
> ---
>
> **📌 2026-07-31 更新：PersonaAgent 已经独立成 LinkAgent 项目**
>
> 这份文档原来指向一份 `PHASE-F-SKILLFOREST-PERSONA-AGENT.md`，说"设计已经不是完全空白了"。两件事变了：
>
> **① PersonaAgent 不再是 RxyCode 的一个 Phase。** 它独立成了 **LinkAgent** 项目（独立仓库，把 RxyCode 当 pip 依赖）。施工文档在 [`../linkagent/`](../linkagent/README.md)，架构见 [`../linkagent/00-OVERVIEW-AND-ARCHITECTURE.md`](../linkagent/00-OVERVIEW-AND-ARCHITECTURE.md)。
>
> **② 原来引用的实测数字来自论文旧版，已被推翻。** 论文重写为 *Individualized Agent* 之后，结论变了：
>
> | 本文档原来写的 | 新论文实测 |
> |---|---|
> | AED 自动蒸馏同域成功率 62.5%，**输给**轨迹缓存的 75%，波动 75pp | AED 形成率 **78.8%**（126/160），**75 个在 held-out 任务中复用成功**；受控套件 48/48 |
> | 全系统绝对成功率 22.7% | 完整系统 **77.54%**，比纯 Prompt 高 **5.27 pp** |
>
> 准确的当前数字见 [`../linkagent/APPENDIX-B-PAPER-EVIDENCE.md`](../linkagent/APPENDIX-B-PAPER-EVIDENCE.md)。
>
> **对本文档的影响：§4 的六张预留卡全部照做不变。** 埋点、元数据、信任边界这三件事无论 PersonaAgent 在哪个仓库实现都需要，而且不提前做以后补不回来。
>
> 唯一要修正的是 **E1 的 `priority` 字段**：手填的数字只当**初始值**，真正的排序靠积累的证据（新论文的动态综合置信度按验证/执行/用户三类证据加权计算）。手填的数字会过期，证据不会。

---

## 目录

| 章节 | 内容 |
|---|---|
| [§1 这份文档要解决什么](#1-这份文档要解决什么) | 为什么现在只留接口不实现 |
| [§2 现状盘点](#2-现状盘点skill-系统已经有什么) | 已有的 skill 系统，附 file:line |
| [§3 两条能力线的接口面](#3-两条能力线的接口面) | Skill Management / 对话蒸馏 |
| [§4 预留卡 E1–E6](#4-预留卡现在就要做的) | **现在就要做的**，不做以后补不回来 |
| [§5 以后再说的](#5-以后再说的不要现在做) | 明确列出不要现在做的 |
| [§6 你需要决定的事](#6-你需要决定的事) | 设计未定的点，回头填 |

---

## §1 这份文档要解决什么

你的原话：

> 最后给我预留一个接口，适用于我接下来想改造我的 agent，让他变成 personaAgent。主要是 skill 的改造（通过 skill management 达到 personaAgent 的目的），还有关于模型对话的蒸馏。这个我具体没想好怎么写，你就给我留这么一个接口就可以了，让我回头可以再在这个项目上搭积木。

**接口预留的价值不在于"先写一点代码"，而在于识别出"以后补代价极高、现在补几乎不要钱"的那几个点。** 这份文档只做这件事。

判断标准就一条：

> **这件事如果不在 Phase B/C/D 里顺手做掉，以后要做就得改动大量已经稳定的代码，或者永久丢失数据。**

按这条标准筛完，只剩 6 张卡（§4），合计约 6 天。**其余全部推迟**（§5）。

### 1.1 最关键的一条

**蒸馏数据是有时效的。**

Skill 系统可以随时重构——代码在那儿，改就是了。但**蒸馏需要的训练数据只能在多 Agent 跑的时候产生**：哪个模型、给了什么输入、产出了什么、这次产出到底好不好。

如果 Phase B/C 跑了三个月才想起来要埋点，**这三个月最有价值的数据（真实任务 × 真实模型 × 真实质量标注）就永久没有了**，只能从头再跑一遍花真金白银去补。

**E3 和 E4 是这份文档里唯二"不做就真的亏钱"的卡。**

---

## §2 现状盘点：skill 系统已经有什么

RxyCode **已经有一套能用的 skill 系统**。做 PersonaAgent 不是从零开始。

### 2.1 已有的两个模块

| 模块 | 位置 | 干什么 |
|---|---|---|
| `skill_manager` | `tools/skill_manager.py` | 从 GitHub 搜索、下载、安装、卸载 skill |
| `skill_tool` | `tools/skill_tool.py` | LLM 可调用的 `skill(name)` 工具，读 SKILL.md 返回文本 |

存储位置 `~/.rxycode/skills/<name>/SKILL.md`（`skill_manager.py:174-178`）。加载时还会搜 `~/.claude/skills`、`~/.codex/skills`、`~/.mimocode/skills`（`skill_tool.py:12-17`）——**兼容其他工具的 skill 目录，这个设计很好，别改**。

**安全性做得不错**，不用重做：ZIP 路径穿越校验（`:67-81`）、成员类型校验（`:84-92`）、解压炸弹防护（`:95-133`，含压缩比上限 200、总量上限 100 MB）、原子发布（先解到 staging 再 `os.replace`，`:293`）、skill 名白名单正则（`:51`、`:60-64`）。

### 2.2 距离 PersonaAgent 差什么

| 缺口 | 现状 | 为什么挡住 PersonaAgent |
|---|---|---|
| **无元数据** | `load_skill` 直接返回整个文件（`skill_tool.py:26`） | 模型不知道有哪些 skill 可用，只能靠猜名字 |
| **纯拉取式** | 必须 LLM 主动调 `skill("xxx")` | Persona 应该是**常驻人格**，不是"想起来才加载" |
| **无工具绑定** | skill 说不了"我需要哪些工具" | Persona 的核心之一就是"这个人格该有什么本事" |
| **无模型绑定** | skill 说不了"我该用什么模型" | 同上 |
| **无组合规则** | 装了 5 个 skill，谁优先？冲突了听谁的？ | Persona 通常是多个 skill 的组合 |
| **与 AgentSpec 无关系** | Phase B 的 `AgentSpec` 完全不知道 skill 存在 | 多 Agent 下"给这个角色装这个 skill"做不到 |
| **无使用记录** | 加载了什么、效果如何，全部没记 | **蒸馏没有数据源** |
| **⚠ 信任面很大** | 从任意 GitHub 仓库下载文本，直接进 prompt | Persona 是常驻的，一个恶意 skill 会**长期**影响 Agent 行为 |

最后一条要单独说：`skill_manager.py:220-245` 会用 GitHub 搜索 API 找任意仓库，`_download_skill_async` 把找到的 markdown 直接落盘，`load_skill` 把它整个塞进 prompt。**文件层面的安全做得很好，但内容层面完全没有信任边界。** 现在影响范围是"这一次调用"，做成 Persona 之后就是"这个人格的每一次调用"。E5 处理这个。

---

## §3 两条能力线的接口面

### 3.1 Skill Management → PersonaAgent

一个可能的形态（**只是形态，不是定案**）：

```
Persona = 身份（我是谁）
        + Skill 集合（我会什么）
        + 工具集（我能碰什么）
        + 模型偏好（我用什么脑子）
        + 记忆域（我记得什么）
```

**看一眼就会发现：后三项 Phase B 的 `AgentSpec` 已经有了**（`tools` / `model` / `memory_scope`）。

所以 PersonaAgent 大概率**不是一个新系统，而是 `AgentSpec` 的一种生成方式**：

```
Persona 定义  ──►  解析 skill 元数据  ──►  生成 AgentSpec  ──►  Phase B 的 AgentRuntime
（用户写的）        （E1 提供）           （E6 提供的接口）      （已有，不用改）
```

**这个洞察决定了 §4 的所有预留卡**：我们不需要为 Persona 预留一个新的运行时，只需要保证 `AgentSpec` 能被程序化地构造，且 skill 有足够的元数据可供构造。

### 3.2 对话蒸馏

蒸馏的最小闭环：

```
① 采集   在多 Agent 跑真实任务时，记录 (输入, 输出, 模型, 质量信号)
                                                      ↑
                                    Phase B/C 已经在产生这个信号，见下表
② 筛选   只留高质量样本
③ 训练   微调或蒸馏出学生模型（离线，不在本项目内）
④ 验证   用 evals 证明学生 ≈ 教师，且更便宜
                    ↑
              主计划 Phase 1 已经有了
```

**关键发现：第 ① 步和第 ④ 步的基础设施，Phase B/C/主计划 Phase 1 已经全都建好了，只差把它们连起来。**

| 蒸馏需要的 | 已有的来源 |
|---|---|
| 输入 / 输出 | Phase B 的 `Blackboard`（结构化产出，比原始对话干净得多） |
| 模型标识 | Phase C 的 per-role model binding |
| **质量信号（最难的一环）** | Phase B 的机械验证门 + `VerdictRecord`；Phase C 的 `ArbitrationRecord` |
| 成本对比（教师 vs 学生） | Phase C 的 `CostAccountant` + 定价表 |
| 效果验证 | 主计划 Phase 1 的 evals harness |

**质量信号这一条特别值钱。** 一般项目做蒸馏最头疼的是"怎么知道这条样本好不好"，通常只能靠人工标注或者再花钱让大模型打分。而 Phase B 的流水线**天然会产生客观标注**：

```
机械验证通过（能编译、测试过、lint 干净）
    + 审计通过（VerdictRecord.passed=True，且绑定了正确的 diff 哈希）
    + 零次打回（没有 retry）
    ─────────────────────────────────────
    = 这是一条金标准样本
```

**这是免费的高质量标注，前提是 E3/E4 把它记下来。** 不记，它就随着进程结束消失了。

---

## §4 预留卡（现在就要做的）

> 六张卡，合计约 6 天。**不要一次做完**——按依赖插进 Phase B/C/D 的执行流程里。

| 卡 | 什么时候做 | 工时 | 不做的代价 |
|---|---|---|---|
| E1 | Phase B 开始前 | 1d | skill 永远没有元数据，后面全部悬空 |
| E2 | Phase B 的 B3 一起 | 0.5d | 协议 schema 要改，TS 类型要重生成，破坏兼容 |
| E3 | Phase B 的 B12 一起 | 1.5d | **蒸馏数据永久丢失** |
| E4 | Phase C 的 C11 一起 | 1.5d | **质量标注永久丢失** |
| E5 | Phase B 开始前 | 1d | Persona 上线后再补，等于承认之前有洞 |
| E6 | Phase B 全部做完后 | 0.5d | 无（这张只是写文档） |

---

### E1 · Skill 元数据 frontmatter

`P1` / 1d / **Phase B 开始前做**

**背景**
`load_skill`（`skill_tool.py:11-33`）把整个 SKILL.md 当字符串返回，没有任何结构。后面所有事——自动激活、工具绑定、模型偏好、组合优先级——**全都需要元数据**。

现在加成本极低（frontmatter 是可选的，老 skill 不写也能跑）。以后加就要处理"存量 skill 全都没有元数据"的兼容问题。

**操作步骤**

1. 约定 YAML frontmatter（与 Anthropic Agent Skills / Cursor Skills 的形状对齐，这样生态里现成的 skill 能直接用）：

```markdown
---
name: systematic-debugging
description: 遇到 bug、测试失败或非预期行为时使用，在提出修复方案之前先系统性定位
# --- 以下字段是 RxyCode 的扩展，其他工具会忽略 ---
rxycode:
  tools: [read_file, grep, run_shell]     # 这个 skill 需要哪些工具
  model_hint: reasoning                   # 倾向什么档位的模型，不绑死具体型号
  priority: 50                            # 多 skill 组合时的优先级，大的赢
  persona_capable: true                   # 能否作为常驻人格使用
---

（正文，也就是现在 load_skill 返回的全部内容）
```

2. `tools/skill_tool.py` 加解析：

```python
@dataclass(frozen=True)
class SkillMetadata:
    """SKILL.md 的 frontmatter。

    frontmatter 是**可选的**。没有 frontmatter 的 skill 必须照常工作——
    ~/.claude/skills 和 ~/.codex/skills 里有大量存量 skill 不会有我们的
    扩展字段，name 用目录名兜底，其余留空。

    rxycode 段是我们的扩展，放在独立 key 下是为了不污染通用字段，其他
    工具读到会直接忽略。
    """
    name: str
    description: str = ""
    tools: list[str] | None = None
    model_hint: str | None = None
    priority: int = 0
    persona_capable: bool = False
    #: 未识别的 frontmatter 字段原样保留，方便以后扩展而不丢数据
    raw: dict[str, Any] = field(default_factory=dict)


def parse_skill(path: Path) -> tuple[SkillMetadata, str]:
    """返回 (元数据, 正文)。frontmatter 缺失或损坏时不抛异常，降级返回。"""


def list_skill_metadata() -> list[SkillMetadata]:
    """扫描所有 skill 目录，只读 frontmatter，不读正文。

    这是"渐进式披露"的基础：把所有 skill 的 name + description 塞进
    system prompt（很短），模型就知道有什么可用；只有真正要用时才
    load 正文（很长）。
    """
```

3. **`load_skill` 的现有行为一个字都不能变**——它仍然返回完整文件内容（含 frontmatter 也无所谓，模型看得懂）。新增的是 `parse_skill` 和 `list_skill_metadata` 两个函数。

4. 测试：有 frontmatter、无 frontmatter、frontmatter 损坏（YAML 语法错）、只有通用字段没有 rxycode 段、未知字段进 `raw`、`load_skill` 行为不变。

**完成判据**
- [ ] `parse_skill` 对无 frontmatter 的 skill 不抛异常
- [ ] `load_skill` 行为逐字节不变（写测试守）
- [ ] `list_skill_metadata` 只读 frontmatter，不读正文（性能，写测试验证）
- [ ] 未知字段进 `raw` 不丢失

---

### E2 · 协议里预留 persona 命名空间

`P1` / 0.5d / **和 Phase B 的 B3 一起做**

**背景**
Phase B 的 `AgentSpec` 会进 `protocol/schema.json` 并生成 TypeScript 类型。**协议一旦稳定下来，加字段就要考虑向后兼容和前端同步。**

现在约定好一个扩展命名空间，以后加 persona 相关信息就不需要动 schema。

**操作步骤**

1. Phase B 的 `AgentSpec.extra`（B3 已有）**加一段命名空间约定的注释**：

```python
    #: 扩展字段。按命名空间约定使用，避免不同 Phase 的扩展互相踩：
    #:
    #:   pair.*      Phase C  结对编程（pair.with / pair.role）
    #:   vision.*    Phase D  视觉能力（vision.required）
    #:   persona.*   Phase E  人格（persona.id / persona.skills / persona.source）
    #:
    #: 用 extra 而不是加一等字段，是为了不让还没定型的功能污染协议 schema。
    #: 某个命名空间稳定之后，再提升为一等字段并同步生成 TS 类型。
    extra: dict[str, Any] = Field(default_factory=dict)
```

2. `docs/modules/agents.md`（B15 会创建）里写清这个约定。

3. 加一个测试，确认 `extra` 里的未知 key 能往返序列化不丢失：

```python
def test_extra_namespaces_survive_roundtrip():
    """extra 是几个 Phase 共用的扩展位，往返丢数据会很难查。"""
```

**完成判据**
- [ ] 命名空间约定写进代码注释和 `agents.md`
- [ ] 往返测试通过

---

### E3 · 蒸馏数据采集埋点

`P0` / 1.5d / **和 Phase B 的 B12（trace）一起做**

> ⚠ **这是这份文档里最重要的一张卡。** 不做的代价不是"以后多花点时间"，是**数据永久丢失**。

**背景**
§3.2 说了，蒸馏需要 `(输入, 输出, 模型, 质量信号)` 四元组。Phase B 跑起来之后，每一次真实任务都在产生这些数据——**但如果不落盘，它就随着进程结束消失了**。

三个月后想做蒸馏，只能重新花钱跑一遍来补数据。

**操作步骤**

1. Phase B 的 `core/tracing.py` span 里，除了 B12 要求的 `role` / `stage` / `delegation_depth` / `tokens`，**再加一组可选的原始 IO**：

```python
@dataclass
class LlmCallRecord:
    """一次 LLM 调用的完整记录。

    这是蒸馏数据集的原始素材。默认**不采集**（隐私 + 磁盘），由
    settings.distillation.collect 打开。

    为什么现在就埋点而不是以后再说：这些数据只在真实任务跑的时候产生。
    等想做蒸馏了再加埋点，之前所有真实任务的数据都补不回来，只能重新
    花钱跑一遍。埋点本身几乎零成本，采集开关默认关着。
    """
    role: str
    stage: str
    model: str
    provider: str
    #: 发给模型的完整消息（脱敏后，见 E5）
    messages: list[dict] | None = None
    #: 模型的完整响应
    response: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    duration_s: float = 0.0
    #: 质量信号由 E4 回填，采集时先留空
    quality: "QualitySignal | None" = None
```

2. **落盘格式用 JSONL**，每行一条，与 `core/tracing.py` 现有的 JSONL 持久化保持一致。目录 `~/.rxycode/distillation/<date>/<session_id>.jsonl`。

3. **默认关闭**。`settings.distillation.collect` 默认 `False`。打开时**必须在 UI 上明确提示正在采集什么**。

4. **采集失败绝不能影响主流程**。写盘出错就静默跳过并记一条 warning，不能让一次磁盘满导致用户的任务失败。

```python
def _record_safely(record: LlmCallRecord) -> None:
    """采集永远不能影响主流程。

    磁盘满、权限不足、路径不存在——任何异常都吞掉并记 warning。用户的
    任务比我们的训练数据重要。
    """
```

5. 测试：默认不采集（写一个断言不产生任何文件的测试）、打开后格式正确、写盘失败不影响主流程、JSONL 每行可独立解析。

**完成判据**
- [ ] 默认关闭，且有测试确认关闭时零文件零开销
- [ ] 打开时 UI 有明确提示
- [ ] 采集异常不影响主流程（写测试注入磁盘错误）
- [ ] JSONL 格式，每行独立可解析

---

### E4 · 质量信号回填

`P0` / 1.5d / **和 Phase C 的 C11（评测矩阵）一起做**

> ⚠ 与 E3 同等重要。E3 采集了数据但没有标注，**没有标注的数据对蒸馏几乎没用**。

**背景**
§3.2 的核心洞察：Phase B 的流水线天然产生客观质量标注，不用人工标、不用大模型打分。

**操作步骤**

1. 定义质量信号：

```python
@dataclass(frozen=True)
class QualitySignal:
    """一条样本的客观质量标注。

    这些信号全部来自 Phase B/C 已有的流水线产物，不需要额外的人工标注或
    LLM 打分——这是 RxyCode 相比一般项目做蒸馏的最大优势。

    金标准 = 机械验证全过 + 审计通过 + 零打回 + 零仲裁。
    """
    #: Phase B 机械验证门的结果（哪些检查过了、哪些挂了）
    mechanical_checks: dict[str, bool]
    #: Phase B 的审计结论
    audit_passed: bool | None
    #: 这个阶段被打回了几次（0 = 一次做对）
    retry_count: int
    #: Phase C 的归因仲裁次数（>0 说明这次协作有摩擦）
    arbitration_count: int
    #: 整个任务最终成功了吗
    task_succeeded: bool
    #: evals 里的任务 id（如果这次运行来自评测）
    eval_task_id: str | None = None

    @property
    def is_gold(self) -> bool:
        """是否金标准样本。"""
        return (
            all(self.mechanical_checks.values())
            and self.audit_passed is True
            and self.retry_count == 0
            and self.arbitration_count == 0
            and self.task_succeeded
        )
```

2. **回填时机**：任务结束时。因为 `task_succeeded` 和 `retry_count` 要等整个流程走完才知道。Coordinator 在 `run_team` 返回前统一回填。

3. **一个导出脚本**（就这一个，别的都不要做）：

```powershell
python -m core.distillation export --since 2026-08-01 --gold-only --out dataset.jsonl
```

它只做筛选和格式转换。**不要在这个项目里做训练、做蒸馏算法、做模型托管**——那些是完全不同的工程，等你想清楚了再说（§5）。

4. 测试：金标准判定的每个条件、回填时机（任务结束才有完整信号）、导出脚本的筛选正确性。

**完成判据**
- [ ] `is_gold` 的五个条件都有测试
- [ ] 回填在任务结束时发生，信号完整
- [ ] 导出脚本可用，`--gold-only` 筛选正确
- [ ] **跑一次 C11 的评测矩阵，看看金标准样本的实际比例是多少**（这个数字决定蒸馏可行不可行，写进文档）

---

### E5 · Skill 信任边界

`P1` / 1d / **Phase B 开始前做**

**背景**
§2.2 最后一条。`skill_manager.py` 的**文件安全做得很好**（ZIP 炸弹、路径穿越、原子发布都有），但**内容安全完全没有**——从任意 GitHub 仓库下载的 markdown 直接进 prompt。

现在的影响范围是"这一次工具调用"。做成 Persona 之后，一个恶意 skill 会**长期、隐蔽地**影响 Agent 的每一次行为。**Persona 上线之后再补这个洞，就是承认之前一直有洞。**

**操作步骤**

1. 安装时记录来源（skill 目录下写一个 `.provenance.json`）：

```python
@dataclass(frozen=True)
class SkillProvenance:
    """skill 的来源记录。

    skill 内容会直接进入 prompt，是一条提示注入路径。文件层面的防护
    skill_manager 已经做得很好，这里补的是"这段文本是谁写的、什么时候
    装的、有没有被改过"。
    """
    source: Literal["builtin", "github", "url", "local"]
    origin: str              # 仓库全名 / URL / 本地路径
    installed_at: str        # ISO 8601
    content_sha256: str      # 正文哈希，用于检测安装后被篡改
    trusted: bool = False    # 用户是否显式信任过
```

2. **安装 ≠ 信任**。默认 `trusted=False`。

3. **分级使用**（关键的一条）：

| 用途 | 要求 |
|---|---|
| 通过 `skill(name)` 一次性加载 | 不要求 trusted，但**首次加载时提示用户来源** |
| 作为 Persona 常驻 | **必须 `trusted=True`**，用户显式确认过 |

4. **篡改检测**：加载时比对 `content_sha256`。不一致就警告，并把 `trusted` 重置为 `False`。

5. `skill list` 命令显示每个 skill 的来源和信任状态。

6. 测试：来源记录正确、内置 skill 默认 trusted、下载的默认不 trusted、篡改能检测、未信任的 skill 不能作为 Persona。

**完成判据**
- [ ] 安装时记录来源
- [ ] 下载的 skill 默认不信任
- [ ] 篡改检测有效且会重置信任
- [ ] 未信任的不能作为 Persona 常驻（这条现在就写好，虽然 Persona 还没实现）

---

### E6 · 写下 AgentSpec 的构造契约

`P2` / 0.5d / **Phase B 全部做完后**

**背景**
§3.1 的结论：PersonaAgent 大概率就是"`AgentSpec` 的一种生成方式"。这张卡只做一件事：**把 `AgentSpec` 可以被程序化构造这件事写下来并测一下**，确保 Phase B 的实现没有偷偷依赖"spec 只能从 YAML 加载"。

**这是一张纯文档 + 一个测试的卡，别做多了。**

**操作步骤**

1. 在 `docs/modules/agents.md` 加一节"程序化构造 AgentSpec"：

```markdown
### 程序化构造 AgentSpec

AgentSpec 可以从三个来源构造，三者等价：

  1. 内置团队 YAML     core/agents/teams/*.yaml
  2. 用户团队 YAML     ~/.rxycode/teams/*.yaml
  3. 代码直接构造      AgentSpec(role=..., goal=..., ...)

第 3 种是给未来的 PersonaAgent 用的：persona 定义 + skill 元数据 →
生成 AgentSpec → 交给现有的 AgentRuntime。这条路径要求 AgentSpec 的
构造和校验不依赖文件系统。
```

2. 加一个测试守住这条：

```python
def test_agent_spec_can_be_built_without_any_file():
    """AgentSpec 的构造和校验不得依赖文件系统。

    这是给 PersonaAgent 预留的：persona 会在运行时程序化生成 spec，
    不经过 YAML。如果 Phase B 的实现偷偷依赖了文件加载路径，这个测试
    会红。
    """
    spec = AgentSpec(role="ad_hoc", display_name="临时", goal="测试",
                     prompt_stage="agent_coder")
    team = TeamSpec(name="t", display_name="t", members=[spec],
                    stages=[...], entry_stage="only")
    validate_team(team)     # 不读任何文件
```

3. 确认 `~/.rxycode/teams/` 这个用户级团队目录**存在且被扫描**（Phase B 的 §7 已经预留了这条）。

**完成判据**
- [ ] 文档写清三种等价的构造来源
- [ ] 测试证明不依赖文件系统
- [ ] 用户级团队目录可用

---

## §5 以后再说的（不要现在做）

**明确列出来，防止实现的时候顺手做多了。** 这些都不满足 §1 的判断标准——以后做代价不高。

| 不要现在做 | 为什么可以推迟 |
|---|---|
| Persona 的定义格式（YAML? 对话式生成?） | 纯新增文件格式，不影响任何已有代码 |
| Persona 的自动激活逻辑 | 需要先有 E1 的元数据和一批真实 skill 才知道怎么设计 |
| 多 skill 冲突消解 | 等真的装了 5 个 skill 打架了再说，现在设计是空想 |
| Skill 市场 / 分享机制 | 纯产品功能 |
| **蒸馏训练本身** | 这是完全不同的工程（数据清洗、训练框架、模型托管），不该在这个仓库里 |
| 学生模型托管 / 推理服务 | 同上。Phase A 的 provider 层已经能接任意 OpenAI 兼容端点，学生模型训好了直接配上去就行 |
| Persona 的 UI | 等有了才做 |
| skill 版本管理 / 依赖解析 | E5 的 `content_sha256` 已经够用一阵子了 |

**特别提醒蒸馏那两条**：训练一个模型和跑一个 Agent 是两个工种，混在一个仓库里会让两边都难维护。**这个项目该做的是"产出高质量数据集"和"验证学生模型效果"，训练本身放到别处。** E3/E4 的导出脚本 + 主计划 Phase 1 的 evals 就是这两件事的全部。

---

## §6 你需要决定的事

回头搭积木的时候，这几个问题绕不过去。**现在不用回答**，列在这里免得以后重新想一遍。

### 6.1 关于 Persona

| 问题 | 影响什么 |
|---|---|
| Persona 是**替换** AgentSpec 还是**修饰** AgentSpec？ | 替换 = persona 定义完整角色；修饰 = 在现有角色上叠加。**修饰更容易做，但表达力弱** |
| 一个会话能同时有多个 Persona 吗？ | 影响 Phase B 的团队模型。如果能，那"专家团 + 每个成员一个 persona"就是自然的形态 |
| Persona 能改变可用工具集吗？ | 能的话，Phase B 的 `AgentRuntime._build_scoped_registry` 要支持**运行时替换**，而不只是构造时确定。**这一条如果要，最好在 Phase B 就想清楚** |
| Persona 之间怎么切换？显式命令还是自动？ | 自动切换需要一个判断模型，和 Phase B 的 `ModeRouter` 是同一类问题，可以复用 |

**第三条是唯一可能反向影响 Phase B 设计的**。如果你倾向"Persona 要能改工具集"，在做 B4 的时候就把 `_build_scoped_registry` 设计成可运行时替换的，成本几乎为零；等 Phase B 做完再改，就要动 `AgentRuntime` 的核心。

### 6.2 关于蒸馏

| 问题 | 影响什么 |
|---|---|
| 蒸馏目标是什么？**降成本**还是**做专属模型**？ | 降成本 = 学生模型模仿教师在**本项目场景**的行为；专属模型 = 学习**你的**代码风格和偏好。两者的数据筛选策略完全不同 |
| 蒸馏哪一个角色？ | 架构师（贵、调用少）和编码员（便宜、调用多）的经济账完全不一样。**大概率编码员更值得蒸** |
| 数据里的代码要脱敏吗？ | 影响 E3 的采集实现。如果要，脱敏逻辑得在写盘之前 |
| 学生模型怎么接进来？ | Phase A 的 provider 层已经能接任意 OpenAI 兼容端点，**这条基本不用担心** |
| 金标准样本比例够吗？ | **E4 会给你这个数字。** 如果金标准比例低于 10%，蒸馏大概率不可行，得先想办法提高流水线的一次通过率 |

**最后一条是决定性的，而且 E4 做完就有答案。** 建议做完 E4 之后先看这个数字，再决定要不要继续往蒸馏方向投入。

---

## §7 一句话总结

**现在就做 §4 的六张卡，六天，分散在 Phase B/C/D 里。其余全部推迟。**

六张卡里，**E3 和 E4 是不做就真的亏钱的**——它们采集的数据只在真实任务跑的时候产生，补不回来。其余四张（E1/E2/E5/E6）是"现在做几乎不要钱，以后做要拆楼"。
