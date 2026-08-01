# L10 · EKO ↔ Skill 双向映射

> **设计来源**：[`../../2026-08-01-think-of-EKO-and-skill.md`](../../2026-08-01-think-of-EKO-and-skill.md)（设计备忘）。**这份文档是它的施工版本**，冲突时以本文档为准。
> **前置**：分卡不同，见 §3 的排期表。**L10-4 是治理漏洞，紧跟 [`L2`](./L2-RXYCODE-BRIDGE.md) 做，不要拖到最后。**
> **产出**：EKO 能导出成 SKILL.md；外面来的 SKILL.md 必须过闸门才能用；**裸 Skill 无法绕过治理层**
> **工时**：6 天
> **卡数**：6 张（L10-1 ~ L10-6）
>
> **干活前读** [`../MODEL-ASSIGNMENT.md`](../MODEL-ASSIGNMENT.md)；本文件卡多为 **owner: backend** → [`../COMPOSER-2.5-PLAYBOOK.md`](../COMPOSER-2.5-PLAYBOOK.md)。**一次只做一张卡。**
> **字段与前缀的权威定义在** [`APPENDIX-C`](./APPENDIX-C-INTERFACE-CONTRACTS.md)。

---

## §0 一句话

**EKO 是唯一权威对象。Skill 是它的打印件，或者是还没入库的原料——不是第二套知识库。**

```
        ┌──────────────────────────────────────────┐
        │            EKO Forest（权威）              │
        └───────┬──────────────────────▲───────────┘
                │ 出站映射              │ 反向映射
                │ L10-1（只读派生）     │ L10-3（必过闸门）
                ▼                      │
        ┌───────────────┐      ┌───────┴────────┐
        │  导出的 SKILL  │      │ 外面来的 SKILL  │
        │  带完整溯源     │      │  裸的、无背书    │
        └───────────────┘      └────────────────┘
                                       ▲
                                       │ L10-4 在这里设卡
                              ┌────────┴────────┐
                              │ RxyCode 的      │
                              │ skill(name) 工具 │
                              └─────────────────┘
```

**三条硬规则**（[APPENDIX-C](./APPENDIX-C-INTERFACE-CONTRACTS.md) 里有机器可验证的版本）：

| # | 规则 |
|---|---|
| ① | **EKO 内联，不做指针。** `procedure` / `preconditions` / `parameters` 全在 `FormalEKO` 字段里，不指向外部 skill 文件 |
| ② | **出站只读。** 导出不改 Forest、不写冻结语料，产物随时可重建 |
| ③ | **反向必过闸门。** 裸 Skill 要变成经验，必须走一遍 `CandidateEKO → 证据门 + 安全门 → promote`，和蒸馏同级 |

### 为什么不做 `skill_ref` 指针

这个问题之前讨论过，结论要写在这里免得反复：

**如果 `procedure` 在 skill 文件里、EKO 只存指针，版本链就分叉成两条**——修订内容到底是产生新 skill blob 还是新 EKO 版本？回滚是回 EKO 指针还是回 blob？论文附录 I.3 的"内容修订"语义会失效。

**内联的代价是重复存储，收益是版本语义只有一条链。** 对一个每次反馈都可能产生新版本的系统来说，这个交换是划算的。

---

## §1 ⚠ 已经存在的治理漏洞（这是 L10 最重要的部分）

**RxyCode 默认注册了一个能绕过全部治理的工具，LinkAgent 会原样继承它。**

### 实测证据（2026-08-01）

| 位置 | 事实 |
|---|---|
| `core/agent_v2.py:1499` | `from ...tools.skill_tool import skill_tool` |
| `core/agent_v2.py:1519` | `skill_tool` 进了默认注册列表 |
| `tools/skill_tool.py:12-17` | 搜索 `~/.rxycode/skills`、`~/.claude/skills`、`~/.codex/skills`、`~/.mimocode/skills` |
| `tools/skill_tool.py:22-31` | `rglob` 匹配名字，**整个文件当字符串返回** |
| `core/agent_v2.py:1536` | `download_skill_tool` 也注册了（`risk="danger"`，走审批） |

**后果**：模型可以调 `skill("anything")`，把任意 SKILL.md 的全文塞进上下文。这条路径上**没有**作用域过滤、**没有**安全门、**没有**版本、**没有** provenance。

> **如果不封住这个口子，LinkAgent 的治理层就是摆设。** 你辛苦做的域硬门（L3）、SAG（L4）、证据链（L5）全都可以用一句 `skill("xxx")` 绕过去。

### 但不能简单地禁掉它

`skill_tool.py:12-17` 兼容 `~/.claude/skills` 等其他工具的目录，**这个设计本身是好的**——用户在 Claude Code 里装的 skill 能在这里用。直接禁掉会砍掉真实价值。

**正确做法是加一道闸，不是拆掉门**：有 EKO 背书的照常放行，没有的引导用户走导入流程。这就是 L10-4。

---

## §2 三条路径与三层 tier

### 2.1 三条路径

| 路径 | 方向 | 何时发生 | 权威源 | 卡 |
|---|---|---|---|---|
| **蒸馏主路径** | 证据 → EKO | 正常运行、学习 | EKO Forest | [`L5`](./L5-EVIDENCE-AND-EVOLUTION.md) |
| **出站映射** | EKO → Skill | 用户想要可读副本 / 与其他 agent 工具互通 | EKO | L10-1 |
| **反向映射** | Skill → EKO | 手动放入、无 EKO 背书 | 入库后归 EKO | L10-3（运行期）· [`L8-2`](./L8-PRESET-EKO-PACK.md)（离线批量） |

**优先级：蒸馏主路径 > 反向映射（例外）> 出站映射（派生）。**

> **[`L8`](./L8-PRESET-EKO-PACK.md) 的策展脚本就是反向映射的离线批量版。** 它和 L10-3 共用同一个解析器（L10-2）和同一套闸门，区别只是 L8 是离线人工过、L10-3 是运行期用户触发。**不要写两套解析逻辑。**

### 2.2 三层 tier（把 [`L8`](./L8-PRESET-EKO-PACK.md) 的双层扩成三层）

反向映射引入了第三种来源，它既不是社区预置也不是蒸馏所得：

| tier | 来源 | 优先级 | `provenance` 前缀 | 森林视图里 |
|---|---|---|---|---|
| `community` | L8 预置包 | `DEFAULT(10)` | `preset:<pack_version>` | 一种颜色 |
| **`imported`** | **用户手动放的 SKILL.md** | **`DEFAULT(10)`** | **`user-add:<来源>`** | **第三种颜色** |
| `personal` | 蒸馏（Mode U / AED） | `PERSISTENT_PERSONAL(40)` | `grounding:<packet_id>` · `explicit-user:<evidence_id>` | 一种颜色 |

**为什么 `imported` 是 DEFAULT(10) 而不是 40**：它是用户显式放进来的，但**没有这个用户的执行证据支撑**。用户从网上下一个 skill 不等于这个 skill 适合他的项目。**让它压过蒸馏出来的个人经验是没有依据的。**

它可以随使用积累 `feedback_evidence`，走 [`L5-5`](./L5-EVIDENCE-AND-EVOLUTION.md) 的正常修订路径演化——**但优先级不会自动提升**，优先级是来源的属性，不是统计的函数。

---

## §3 卡的排期（不按编号顺序做）

**L10 是横切内容，不是一个阶段。** 每张卡的实际位置不同：

| 卡 | 最早能做 | **建议位置** | 为什么 |
|---|---|---|---|
| **L10-4** 封住 skill 旁路 | L2 + L4-3 | **紧跟 L4，在 L3 之前也行** | §1 的治理漏洞，越早封越好 |
| **L10-2** Skill 解析器 | L1 | **L8-2 之前** | L8-2 复用它，别写两遍 |
| **L10-5** provenance 规范 | L1 | 和 L10-2 一起 | 是数据契约，越早定死越好 |
| **L10-1** 出站映射 | L1 | 任意（很便宜，搬现成代码） | — |
| **L10-6** 往返测试 | L10-1 + L10-2 | 跟在 L10-2 后 | — |
| **L10-3** 运行期反向映射 | L4 + L5 全部 | L5 之后 | 需要完整的闸门 |

> **如果只能做一张，做 L10-4。** 其余五张是功能，L10-4 是止血。

---

## §4 任务卡

### L10-1 · 出站映射（EKO → SKILL.md）

`P1` / 1 天 / 依赖：L1 全部

**背景**

**这张卡基本是搬代码。** SkillForest 的 `src/skillforest/export/skill_projection.py`（204 行）已经实现了完整的出站映射，包括字段映射表、frontmatter 构造、YAML 序列化。

**涉及文件**

| 文件 | Grep 锚点 | 改法 |
|---|---|---|
| `src/linkagent/export/__init__.py` | 新建 | — |
| `src/linkagent/export/skill_projection.py` | 从 SkillForest 搬 | 见下面的三处改动 |
| `src/linkagent/cli.py` | `eko export` | 加 `--as skill` |
| `tests/export/test_skill_projection.py` | 新建 | — |

**搬过来之后要改的三处**

| # | 改什么 | 为什么 |
|---|---|---|
| ① | `from skillforest.eko_schema_v2 import FormalEKO` → `from linkagent.eko.schema import FormalEKO` | 换包名 |
| ② | frontmatter 加 **`tier`** 字段 | 三层 tier 是 LinkAgent 新增的，导出物要能看出来源层 |
| ③ | 删掉 `corpus_*` 相关的三个函数（`load_frozen_corpus_manifest` / `verify_frozen_corpus_hashes` / `read_formal_ekos_from_forest`） | 那是论文冻结语料的装置，LinkAgent 的森林在 `~/.linkagent/`，走 `EKOForest` 读，不重复实现 |

> `_FIELD_SECTION_ORDER`、`_render_section`、`_dump_yaml_mapping`、`_yaml_scalar` **原样搬，一个字符都不要改**。它们是纯函数、已验证、没有依赖。

**已经替你决定好的**

| 决定 | 理由 |
|---|---|
| **按需导出，不在 promote 时自动导出** | EKO 演化很频繁（每次反馈都可能产生新版本），自动导出会疯狂写盘。而且导出物是派生品，随时可重建 |
| 默认导出目录 `~/.linkagent/exports/skills/{eko_id}@{version}/SKILL.md` | 与森林目录隔离，**绝不写进 `records/`** |
| 默认只导出 `catalog.current_version` | 历史版用 `--scope all-versions` |
| 允许导出到 `~/.claude/skills/` 等互通目录，**但要显式指定路径 + 给出警告** | 这是真实价值（个人经验能被其他 agent 工具用上），但会和 L10-4 的闸交互，用户要知道 |
| 导出**不改 Forest 任何东西** | 硬规则 ② |

**验收命令**

```powershell
cd "D:\agent-demo\LinkAgent"
python -m pytest tests/export/ -q
linkagent eko export --as skill --out artifacts/skills/
python -m ruff check src/linkagent/export
```

**完成判据**
- [ ] 导出的 SKILL.md 有完整 frontmatter：`source` / `version` / `parent_version` / `status` / `path` / `tier` / `projection` / `distillation`
- [ ] 正文各 `##` 节与 EKO 字段一一对应
- [ ] 空字段不产生空节
- [ ] **导出前后 `records/` 与 `catalog.json` 逐字节不变**（这条要真的断言文件 hash）
- [ ] 同一个 EKO 导出两次，产物字节相同（幂等）
- [ ] `--scope all-versions` 能导出历史版

**禁止**

- ❌ 在 promote 里自动触发导出
- ❌ 导出时修改 EKO 或 catalog
- ❌ 重写那四个纯函数

---

### L10-2 · Skill 解析器（SKILL.md → CandidateEKO）

`P0` / 1.5 天 / 依赖：L1 全部　**排在 [`L8-2`](./L8-PRESET-EKO-PACK.md) 之前**

**背景**

反向映射的核心零件。**L8 的离线策展和 L10-3 的运行期导入共用它**，所以它要先做、要独立、要可测。

**涉及文件**

| 文件 | Grep 锚点 | 改法 |
|---|---|---|
| `src/linkagent/skillio/__init__.py` | 新建 | — |
| `src/linkagent/skillio/parser.py` | 新建 | 规则解析 |
| `src/linkagent/skillio/extractor.py` | 新建 | 模型抽取（兜底） |
| `tests/skillio/test_parser.py` | 新建 | — |

**已经替你决定好的**

| 决定 | 理由 |
|---|---|
| **两级策略：先规则，规则失败才上模型** | 规范的 SKILL.md（frontmatter + `##` 节）规则可直解析——确定性、零成本、可测。只有非结构化正文才值得花一次 LLM 调用 |
| 两条路径的**出口是同一个 `CandidateEKO`** | 否则两条路会长出不同的字段习惯 |
| 解析器**只产出 `CandidateEKO`，不 promote** | 闸门是别人的职责（L10-3 / L8）。解析器保持纯粹，好测 |
| 解析**永不猜** `scope` 和 `path` | 这两个字段决定检索行为，猜错会污染无关领域。留空，由调用方补（L8 人工填、L10-3 问用户） |
| 解析结果带 **`extraction_method`** 字段（`rule` / `llm`） | 排查问题时要知道这条是怎么来的 |
| 模型抽取的结果**必须过 `CandidateEKO` 的 pydantic 校验** | 模型会编字段 |

**操作步骤**

1. `skillio/parser.py`：

```python
"""把 SKILL.md 解析成 CandidateEKO。

## 为什么先规则后模型

规范的 SKILL.md 是 frontmatter + 一串 ## 节,规则解析是确定性的、零成本、
能写穷举测试。只有正文完全非结构化时才值得花一次 LLM 调用。

反过来做(一律送模型)的问题不是贵,是**不可复现**——同一个文件两次解析
可能得到不同的 procedure,而 EKO 是要进版本链的。

## 为什么不猜 scope 和 path

这两个字段决定这条经验会在什么情境下被检索出来。猜错的后果是跨域污染
(见 L3 §0 论文实测的负迁移)。宁可留空让调用方补,也不要模型编一个。

## 出口只有 CandidateEKO

解析器不 promote、不写 Forest、不过安全门。那些是闸门的职责。保持这个
边界,解析器才能被 L8(离线批量)和 L10-3(运行期)共用。
"""


class SkillParseError(ValueError):
    """SKILL.md 无法解析成 CandidateEKO。调用方要给出可读提示,不要吞掉。"""


def parse_skill_markdown(text: str, *, source: str) -> CandidateEKO:
    """规则解析。失败抛 SkillParseError,由调用方决定要不要退到模型抽取。"""
```

2. 字段映射（**和 L10-1 的导出表严格互逆**）：

| SKILL.md | `CandidateEKO` |
|---|---|
| frontmatter `name` | `id`（slugify + 加前缀） |
| frontmatter `source` | 若存在 → 说明它是导出物，见 L10-6 |
| `## Description` | `description` |
| `## Preconditions` | `preconditions` |
| `## Procedure` | `procedure` |
| `## Parameters` | `parameters` |
| `## Scope` | `scope`（**解析出来也要人工确认**） |
| `## Dependencies` / `## Conflicts` | 同名字段 |
| 无正文对应 | `path`、`status` 留空 |

3. `skillio/extractor.py`：模型抽取。**prompt 里明确禁止编造 scope 和 path。**

**完成判据**
- [ ] 规范 SKILL.md 规则解析成功，字段齐全
- [ ] 缺 `## Description` → `SkillParseError`（这是必填）
- [ ] 非结构化正文 → 规则失败 → 模型抽取兜底
- [ ] 两条路径都产出通过 pydantic 校验的 `CandidateEKO`
- [ ] `scope` / `path` **永远不被自动填充**（要有专门的测试）
- [ ] 解析器不碰磁盘、不调 Forest（纯函数，测试里不需要 fixture 目录）
- [ ] `extraction_method` 正确标注

**禁止**

- ❌ 解析器里 promote 或写 Forest
- ❌ 自动填 `scope` / `path`
- ❌ 模型输出不过 pydantic 校验就返回

---

### L10-3 · 运行期反向映射（用户手动放入的 Skill）

`P1` / 1.5 天 / 依赖：L10-2 + L4 全部 + L5 全部

**背景**

用户往 `~/.claude/skills/` 丢了一个从网上下的 skill。系统发现它**没有 EKO 背书**，要把它接回演化路径。

**涉及文件**

| 文件 | Grep 锚点 | 改法 |
|---|---|---|
| `src/linkagent/skillio/importer.py` | 新建 | 导入流程 |
| `src/linkagent/tools/eko_tools.py` | L5-6 建的 | 加 `skill_import` 工具 |
| `tests/skillio/test_importer.py` | 新建 | — |

**流程**

```
裸 SKILL.md（Forest 中查无对应 EKO）
  → L10-2 解析 → CandidateEKO
  → 补齐缺失字段：
      path        ← 问用户 / 由 agent 依据内容建议后确认
      scope       ← 问用户（domain 必填,见 L3）
      provenance  ← user-add:<来源路径或导入批次>
      validation_evidence ← skill-import:<内容 sha256>
      tier        ← imported
  → 过证据门 + 安全门（与蒸馏 promote 同级）
  → promote → FormalEKO v1.0.0 → 写入 Forest
  → 此后与蒸馏产物同等对待
```

**已经替你决定好的**

| 决定 | 理由 |
|---|---|
| **导入是 agent 工具（`skill_import`），不是自动后台行为** | 产品决策 #4：EKO 的变更走对话。而且 `scope` 必须问用户 |
| `domain` **必须由用户确认**，不接受模型自填 | 与 [`L3`](./L3-RETRIEVAL-AND-SCOPE.md) 的规则一致——最强的断言由最可信的一方下 |
| `validation_evidence` 记 **内容 sha256**，不伪造执行证据 | 这条 EKO 确实没被验证过，装作有证据是自欺 |
| 导入的 EKO 起始版本 **`1.0.0`**，`parent_version = None` | 它是新的一条链，不是谁的修订 |
| 过**和蒸馏同级**的证据门与安全门 | 硬规则 ③。降低标准就等于开后门 |
| 导入前先跑一遍 **L4 的 SAG 内容检查** | 网上下的 skill 可能带 `curl \| sh` 之类的东西 |
| **不自动扫描目录批量导入** | 用户放 100 个 skill 不代表他想要 100 条经验 |

**完成判据**
- [ ] 裸 SKILL.md 能通过对话导入，产出 `FormalEKO v1.0.0`
- [ ] `provenance` 是 `user-add:...`，`tier` 是 `imported`
- [ ] 不确认 `domain` 就无法完成导入
- [ ] 内容触发 SAG 规则时导入被拦（要有一个带 `curl | sh` 的测试样本）
- [ ] 导入后能被正常检索（在其 `domain` 内）、能被 `eko_forget`、能回滚
- [ ] 导入的 EKO 在冲突时**输给**同域的 `personal` EKO（独立测试）
- [ ] 没有任何自动批量扫描导入的代码路径

**禁止**

- ❌ 自动导入
- ❌ 模型自填 `domain`
- ❌ 伪造 `validation_evidence`
- ❌ 给导入路径放宽安全门

---

### L10-4 · 封住 RxyCode 的 skill 工具旁路

`P0` / 1 天 / 依赖：L2 全部 + L4-3　**这是止血卡，尽早做**

**背景**

见 §1。**不封这个口子，L3/L4/L5 的治理全部可以被一句 `skill("xxx")` 绕过。**

**涉及文件**

| 文件 | Grep 锚点 | 改法 |
|---|---|---|
| `src/linkagent/safety/rules.py` | L4-1 建的 | 加 `ungoverned_skill_load` 规则 |
| `src/linkagent/skillio/gate.py` | 新建 | 背书检查 |
| `tests/skillio/test_skill_gate.py` | 新建 | **核心** |

**为什么走 SAG 而不是改工具注册表**

[`L2 §1.2`](./L2-RXYCODE-BRIDGE.md) 的实测结论：**hooks 是观察性的，返回值不影响主流程；approval broker 是唯一能返回"拒绝"的缝。**

所以拦截 `skill()` 调用**必须走 broker**。这正好复用 [`L4-3`](./L4-SAFETY-GATE.md) 已经接好的线，不需要新机制。

> 如果发现 `ToolOrchestrator` 有实例级的工具覆盖能力（用 Grep 确认 `def register` 的行为），那用一个同名的受控 `skill` 工具替换掉是更干净的做法。**但先按 SAG 方案做**——它一定能工作。

**闸的逻辑**

```
拦截 skill(name) 调用：
  1. 定位目标 SKILL.md（复用 RxyCode 的四个搜索目录）
  2. 读 frontmatter 的 source 字段
  3. ┌ 有 source，且 Forest 里有该 EKO，且 status=active
     │   → 放行，但**返回 Forest 里的当前版本内容**，不是文件内容
     ├ 有 source，但 Forest 里查无 / 已 rejected
     │   → 拒绝 + 说明"这条经验已被移除"
     └ 无 source（裸 Skill）
         → 拒绝 + 提示"这个 skill 还没入库，要我导入吗？"并给出 skill_import 的调用方式
```

**已经替你决定好的**

| 决定 | 理由 |
|---|---|
| 放行时**返回 Forest 的当前版本，不是磁盘文件内容** | 文件可能被改过、或者是旧版本。**Forest 才是权威**（硬规则：EKO 是唯一权威对象） |
| 拒绝时**给出可执行的下一步**，不是干巴巴一句"被拒绝" | 用户装了个 skill 发现用不了却不知道怎么办，比直接不支持还糟 |
| 这条规则**级别是 PARTIAL（可覆盖）**，不是 FULL | 用户坚持要用裸 skill 时应该能一次性放行——但要让他知道这次没有治理 |
| `download_skill_tool`（`agent_v2.py:1536`）**同样受这条规则约束** | 从 URL 装的 skill 更没有背书 |
| **不修改 RxyCode 的搜索目录逻辑** | 兼容 `~/.claude/skills` 是好设计，保留它 |

**完成判据**
- [ ] 裸 SKILL.md → `skill()` 被拒 + 给出导入提示
- [ ] 有背书的 skill → 放行，且**返回的是 Forest 内容不是文件内容**（这条必须单独测：故意改磁盘文件，验证返回的还是 Forest 版本）
- [ ] `source` 指向已 `rejected` 的 EKO → 被拒
- [ ] 用户显式覆盖 → 能放行，且审计日志记了这次覆盖
- [ ] `download_skill` 装进来的 skill 同样受约束
- [ ] **端到端反证测试**：构造一条被 L3 域门排除的经验，写成裸 SKILL.md 放进 `~/.claude/skills/`，验证模型**无法**通过 `skill()` 拿到它

**禁止**

- ❌ 改 RxyCode 的 `skill_tool.py`（硬约束：RxyCode 一行不改）
- ❌ 直接禁用 skill 工具（会砍掉真实价值，见 §1）
- ❌ 放行时返回磁盘文件内容

---

### L10-5 · provenance 前缀规范与审计

`P1` / 0.5 天 / 依赖：L1 全部

**背景**

`provenance` 是 `list[str]`，格式全靠约定。**约定不写进代码就一定会漂移。**

**涉及文件**

| 文件 | Grep 锚点 | 改法 |
|---|---|---|
| `src/linkagent/eko/provenance.py` | 新建 | 前缀常量 + 校验 |
| `src/linkagent/eko/schema.py` | `class FormalEKO` | 加 `provenance` 的 validator |
| `tests/eko/test_provenance.py` | 新建 | — |

**四个前缀**（权威定义同步在 [`APPENDIX-C §4.6`](./APPENDIX-C-INTERFACE-CONTRACTS.md)）

| 前缀 | 含义 | 谁产生 |
|---|---|---|
| `grounding:<packet_id>` | 蒸馏自证据包 | [`L5-3`](./L5-EVIDENCE-AND-EVOLUTION.md) AED |
| `explicit-user:<evidence_id>` | 用户显式表达的偏好 | [`L5-2`](./L5-EVIDENCE-AND-EVOLUTION.md) Mode U |
| `user-add:<来源>` | 手动导入的 Skill | L10-3 |
| `preset:<pack_version>` | 社区预置包 | [`L8`](./L8-PRESET-EKO-PACK.md) |

**已经替你决定好的**

| 决定 | 理由 |
|---|---|
| 前缀是**封闭集合**，pydantic validator 里校验 | 自由字符串三个月后会有七种写法 |
| `provenance` **不能为空** | 一条不知道从哪来的经验不该存在 |
| 前缀与 `tier` 的对应关系**要能互相验证** | `tier=personal` 却带 `preset:` 前缀说明有 bug |
| 校验失败**拒绝入库**，不是警告 | provenance 是审计链的根 |

**完成判据**
- [ ] 四种前缀都能通过校验
- [ ] 未知前缀 → 拒绝入库
- [ ] 空 `provenance` → 拒绝
- [ ] `tier` 与前缀不匹配 → 拒绝（四组交叉测试）
- [ ] 现有的 L5 / L8 产出路径都符合规范（跑一遍它们的测试确认没打破）

**禁止**

- ❌ 允许自由格式的 provenance
- ❌ 校验失败只 warning

---

### L10-6 · 往返一致性测试

`P2` / 0.5 天 / 依赖：L10-1 + L10-2

**背景**

导出和解析是互逆的两个函数。**互逆关系必须有测试锁住**，否则改了一边忘了另一边，症状是"导出的 skill 别的工具读不了"或者"自己导出的自己解析不回来"。

**涉及文件**

| 文件 | 说明 |
|---|---|
| `tests/skillio/test_roundtrip.py` | 新建 |

**测什么**

```python
def test_export_then_parse_recovers_every_field():
    """导出再解析,字段应当全部还原。

    注意断言的是**语义等价**不是字节相同:解析结果是 CandidateEKO,
    没有 version / status / execution_stats 这些只有 Forest 才有的东西。
    比较范围限定在 description / preconditions / procedure / parameters /
    dependencies / conflicts。
    """

def test_importing_an_exported_skill_is_rejected_as_duplicate():
    """导出物带 source 字段,再导入应当被识别为已存在,而不是造一条重复 EKO。

    这是很容易踩的坑:用户把自己导出的 skill 放回 skills 目录,
    如果没有这层检查,森林里就会出现两条同样的经验。
    """

def test_roundtrip_is_stable_across_two_cycles():
    """导出→解析→再导出,两次导出的产物字节相同。"""

def test_parser_rejects_a_tampered_export():
    """导出物被手改过正文但 source 还在 —— 要能发现。

    对应设计备忘里的「provenance 链断裂」。做法:导出时在 frontmatter 记
    正文的 sha256,解析时比对。
    """
```

**已经替你决定好的**

| 决定 | 理由 |
|---|---|
| 导出物的 frontmatter 里加 **`body_sha256`** | 让篡改可检测。这是第四个测试的前提，**L10-1 要同步加这个字段** |
| 往返只比**语义字段**，不比全部 | `version` / `status` / `execution_stats` 是 Forest 侧的，解析结果里本来就没有 |
| 重复检测按 `source` 的 `<eko_id>@<version>` 判 | 不是按内容 hash——同一条经验的不同版本内容不同但不该算新经验 |

**完成判据**
- [ ] 四个测试全绿
- [ ] `body_sha256` 已加进 L10-1 的导出物（回去改那张卡的产物）
- [ ] 篡改测试真的能发现改动（手动改一个字符验证）

**禁止**

- ❌ 断言字节相同（会因为无关字段一直红）

---

## §5 完成标准

- [ ] EKO 能导出成带完整溯源的 SKILL.md，导出不改 Forest
- [ ] 裸 SKILL.md **无法**通过 `skill()` 被模型读到，且拒绝时给出导入路径
- [ ] 有 EKO 背书的 skill 放行，且返回的是 **Forest 内容**不是磁盘内容
- [ ] 用户能通过对话把一个下载来的 skill 导入成 `tier=imported` 的 EKO
- [ ] 导入的 EKO 在冲突时输给同域的 `personal` EKO
- [ ] 四种 provenance 前缀有校验，违规拒绝入库
- [ ] 往返测试锁住导出/解析的互逆关系
- [ ] **[`L8-2`](./L8-PRESET-EKO-PACK.md) 的策展脚本用的是 L10-2 的解析器**，不是自己写的一套

---

## §6 和其他文档的关系

| 文档 | 关系 |
|---|---|
| [`../../2026-08-01-think-of-EKO-and-skill.md`](../../2026-08-01-think-of-EKO-and-skill.md) | 设计来源。本文档是它的施工版，**并补上了它没覆盖的 L10-4（RxyCode skill 工具旁路）** |
| [`L8`](./L8-PRESET-EKO-PACK.md) | 离线批量反向映射，共用 L10-2 的解析器 |
| [`L5`](./L5-EVIDENCE-AND-EVOLUTION.md) | 蒸馏主路径。L10-3 复用它的 promote 闸门 |
| [`L4`](./L4-SAFETY-GATE.md) | L10-4 复用它的 SAG 接线 |
| [`APPENDIX-C`](./APPENDIX-C-INTERFACE-CONTRACTS.md) | provenance 前缀、tier、导出产物格式的权威定义 |
