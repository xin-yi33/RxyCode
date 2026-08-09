# LinkAgent · 定位、架构与复用边界

> **读这份文档之前**：先读 [`../MODEL-ASSIGNMENT.md`](../MODEL-ASSIGNMENT.md)；主写纪律（全部卡归 Composer）[`../COMPOSER-2.5-PLAYBOOK.md`](../COMPOSER-2.5-PLAYBOOK.md)，多模态环节辅助纪律 [`../GROK-FRONTEND-PLAYBOOK.md`](../GROK-FRONTEND-PLAYBOOK.md)。
> **这份文档不含任务卡**，它回答"我们到底要建什么、为什么这么建"。任务卡在 `L0`–`L7`。
>
> **创建**：2026-07-31

---

## §1 一句话定位

**LinkAgent = RxyCode（执行底座）+ EKO（个性化经验治理层）。**

RxyCode 负责"把活干了"，LinkAgent 负责"记住这个用户怎么干活、并且在下次可靠地用上"。

```
         用户请求
             │
             ▼
   ┌─────────────────────┐
   │   LinkAgent          │  ← 新项目：检索什么经验、允不允许用、用完学到什么
   │   EKO 治理层         │
   └──────────┬──────────┘
              │ 注入经验上下文 + 安全约束
              ▼
   ┌─────────────────────┐
   │   RxyCode            │  ← pip 依赖，一行不改
   │   Agent 执行底座     │
   └──────────┬──────────┘
              │ 执行轨迹
              ▼
   ┌─────────────────────┐
   │   LinkAgent          │  ← 从轨迹里提取证据，更新经验库
   │   证据回收 + 演化    │
   └─────────────────────┘
```

---

## §2 为什么是独立项目，不是 RxyCode 的一个 Phase

三条理由，任一条都成立：

| 理由 | 说明 |
|---|---|
| **风险隔离** | RxyCode 有用户、在跑。EKO 层是研究成果转化，不确定性高。把它塞进 RxyCode 意味着每次实验都在动生产代码 |
| **演进节奏不同** | RxyCode 的路线（协议化、多 Agent、多模态）和 EKO 的路线（经验治理）没有依赖关系，绑在一起只会互相拖累 |
| **代码来源不同** | EKO 层有 ~3000 行现成的研究代码要搬。混进 RxyCode 会让那个仓库同时背两套抽象 |

**硬约束：RxyCode 不因为 LinkAgent 改动一行。**

LinkAgent 通过 `pip install rxycode` 依赖它，用它公开的扩展缝接入。任何一张卡如果需要改 RxyCode 源码，按 Playbook 规则 C8 **停下来报告**。

---

## §3 EKO 是什么（这个必须先搞清楚）

**EKO = Executable Knowledge Object，可执行知识对象。** 它是整个项目的中心抽象——经验从产生到使用，全程只以 EKO 的形式存在。

一个 EKO 就是一条**有版本、有来源、有适用范围、能直接拿来执行**的经验。17 个字段（完整表见 [`APPENDIX-A-ASSET-INVENTORY.md §3`](./APPENDIX-A-ASSET-INVENTORY.md#3-eko-数据模型formaleko-17-字段)），关键的几个：

| 字段 | 为什么关键 |
|---|---|
| `procedure` | **过程内联在对象里**，不是指向别处的指针。这决定了版本语义只有一条链 |
| `path` | 域路径，决定它落在森林的哪棵树上 |
| `scope` | 适用范围。**这是 LinkAgent 要重点改造的字段**，见 §6 |
| `version` + `parent_version` | 每个版本不可变，修订 = 追加新版本 |
| `status` | `validated` / `active` / `deprecated` / `rejected` |
| `dependencies` / `conflicts` | 关系。`conflicts` 必须**对称** |

### 三条不变量

1. **每个版本是不可变的完整记录。** 改内容 = 生成新版本，不是原地修改
2. **"当前版本"是 catalog 里的一个指针，不在 EKO 对象里。** 回滚 = 只改指针，不动任何 record
3. **EKO 是经验进入行动的唯一中间表示。** 没有旁路——不存在"这条经验不走 EKO 直接塞进 prompt"

第 3 条是设计纪律，不是技术限制。破坏它，整套治理（检索过滤、冲突裁决、安全门、版本回滚）就全部失效。

### EKO 不是什么

| 不是 | 区别 |
|---|---|
| **不是 tool** | tool 有能力但没有生命周期元数据（谁的、什么时候适用、验证过没有） |
| **不是 memory** | memory 是原始记录，不可直接执行。EKO 是提炼后的可执行单元 |
| **不是 skill.md** | skill 是给模型看的自然语言文本，没有版本链、没有作用域、没有证据 |

---

## §4 一个 turn 长什么样

这是 LinkAgent 的核心流程。**七步里只有第 5 步是 RxyCode 的，其余都是 LinkAgent。**

```
┌─ 1 ─────────────────────────────────────────────────────┐
│ 情境化检索                          【L3】收益最大        │
│ 用 path + scope + status 联合过滤,再按 description 排序  │
│ 输出:适用于当前请求的 EKO 候选                            │
└──────────────────────┬───────────────────────────────────┘
                       ▼
┌─ 2 ─────────────────────────────────────────────────────┐
│ 依赖组合(PCDR)                     【L6】默认关闭         │
│ 从目标 EKO 递归展开 dependencies,拓扑排序                │
└──────────────────────┬───────────────────────────────────┘
                       ▼
┌─ 3 ─────────────────────────────────────────────────────┐
│ 冲突裁决                            【L6】默认关闭         │
│ 五级优先级;同级用动态置信度;完全同分必须问用户            │
└──────────────────────┬───────────────────────────────────┘
                       ▼
┌─ 4 ─────────────────────────────────────────────────────┐
│ 安全门控(SAG)                      【L4】纯代码零 LLM    │
│ 检查计划里的工具、参数、组合风险 → killed/warning/safe    │
└──────────────────────┬───────────────────────────────────┘
                       ▼
┌─ 5 ═════════════════════════════════════════════════════┐
│ ▓▓ RxyCode 执行 ▓▓                  【L2】桥接层          │
│ AgentV2.run(请求 + 注入的 EKO 上下文)                     │
│ 工具调用经过 LinkAgent 装的 approval broker(第二道 SAG)  │
└──────────────────────┬───────────────────────────────────┘
                       ▼
┌─ 6 ─────────────────────────────────────────────────────┐
│ 证据回收                            【L5】                │
│ 轨迹 → EvidencePacket。Mode U 从用户交互,AED 从已验证轨迹 │
└──────────────────────┬───────────────────────────────────┘
                       ▼
┌─ 7 ─────────────────────────────────────────────────────┐
│ 反馈演化                            【L5】                │
│ 成功/失败写回 EKO;内容变化生成新版本;失效则回滚指针        │
└──────────────────────────────────────────────────────────┘
```

### 安全门为什么有两道

第 4 步的 SAG 检查的是**计划**，第 5 步里 approval broker 检查的是**实际发生的工具调用**。

论文只有第一道，因为它的执行器是沙箱、计划即执行。**LinkAgent 接的是真实 Agent，AgentV2 内部会自己做规划**，LinkAgent 在第 4 步看不到最终的工具调用。所以必须在工具层再拦一道。

好在 RxyCode 已经有 `set_approval_broker` 这个缝，装进去成本很低。详见 [`L4-SAFETY-GATE.md`](./L4-SAFETY-GATE.md)。

---

## §5 建设顺序（依据在附录 B）

顺序**不是**按流程图从左到右，而是**按实测收益排**。完整论证见 [`APPENDIX-B-PAPER-EVIDENCE.md`](./APPENDIX-B-PAPER-EVIDENCE.md)。

| 阶段 | 内容 | 实测依据 | 状态 |
|---|---|---|---|
| **L0** | 建仓、依赖、包结构、CI | 地基 | 必做 |
| **L1** | EKO 核心移植（schema/engine/forest/index） | 地基 | 必做 |
| **L2** | RxyCode 桥接（执行、上下文注入、轨迹回收） | 地基 | 必做 |
| **L3** | **情境化检索 + 修作用域语义** | **移除损失 −1.85 pp**（最大）；Recall@5 28%→98% | **第一优先** |
| **L4** | **安全门控** | **移除损失 −1.54 pp**；纯代码零 LLM，危险激活 100%→0% | 第二优先 |
| **L5** | **证据采集 + 反馈演化** | **移除损失 −1.46 pp**；但有模型间 8pp 分裂，**必须先做完 L3** | 第三优先 |
| **L6** | 依赖组合 + 冲突裁决 | 端到端**无显著效应**（CI 跨 0），组件级很强 | **代码搬过来，默认关闭** |
| **L7** | 评测 harness | 论文的数字不能假定在编码任务上复现 | 与 L3 并行开始 |
| **L8** | 预置社区 EKO 包 | 解决冷启动：新用户第一天就有可用经验层 | L3 之后可并行 |
| **L9** | Desktop 应用 | 产品交付形态（见 §11） | 壳可在 L2 后并行，EKO 视图等 L3/L5 |

### 三条明确不做的

| ❌ 不做 | 理由 |
|---|---|
| 先搞个"简单版经验库"看看效果 | 实测：Flat EKO 74.96%，治理版 77.54%。**没有治理的经验库不值得做** |
| 一上来就打开依赖组合和冲突裁决 | 端到端无收益且有开销。等有真实依赖元数据的域再按域打开 |
| 在修好作用域语义之前打开反馈演化 | DeepSeek 上实测是**净负收益**（−2.69 pp） |

---

## §6 LinkAgent 相对论文的第一个改进：作用域语义

**这是必须做的，不是可选优化。**

### 问题

论文方法论说：作用域不满足时**直接排除**。

代码实现的是**集合交集放行**（`eko_engine.py` 的 `_value_overlap`）——只要有一个值重合就通过。

论文如实记录了后果（§3.2 slot 级诊断）：

| Turn 类型 | 完整系统 | 关掉反馈演化 |
|---|---:|---:|
| turn 12 **跨领域边界** | **0.15**（DeepSeek 0.01） | 0.525 |
| turn 13 跨会话复用 | 0.565 | 0.02 |

同一个偏好 EKO，在目标域内是正迁移，在无关域上是**严重负迁移**。

### 为什么对 LinkAgent 更致命

论文的任务分布是受控的。**编码任务天然跨域**——今天写 React，明天调 SQL，后天写 CI 脚本。

如果照搬交集放行的语义，"用户在前端项目里说过喜欢函数式写法"这条 EKO，会因为 scope 里有个 `code_generation` 就注入到数据库迁移任务里。DeepSeek 上那个 −2.69 pp 就是这么来的。

### 怎么改

在 [`L3-RETRIEVAL-AND-SCOPE.md`](./L3-RETRIEVAL-AND-SCOPE.md) 里展开。核心是把"任一维度有交集就放行"改成"**每个声明的维度都必须满足**"，并且区分"未声明"（不约束）和"声明了但不匹配"（排除）。

---

## §7 复用边界

### 从 SkillForest 搬什么

详见 [`APPENDIX-A-ASSET-INVENTORY.md`](./APPENDIX-A-ASSET-INVENTORY.md)。摘要：

| 类别 | 内容 | 行数 |
|---|---|---:|
| 🟢 **直接搬** | v2 生产栈：schema / engine / forest / index / conflict / dependency / SAG / distillation | ~2,957 |
| 🟡 **参考改写** | `agent_runtime.py`（结构对，但要接 RxyCode） | 1,053 |
| 🔴 **不要搬** | 所有基于旧 `schema.EKO` 的 legacy 模块 | ~1,559 |

> ⚠ 最大的坑：`conflict_resolver.py` 和 `dependency_resolver.py` 里 **v2 和 legacy 两套实现在同一个文件里**。只搬 `Formal*` 那套和 `resolve_formal`，整个文件复制会把 legacy 依赖链一起拖进来。

### 从 RxyCode 用什么

**只用公开接口，不 fork。**

| 用途 | 接口 |
|---|---|
| 执行 | `AgentV2.run(user_input, mode)` |
| 挂钩子 | `AgentV2.register_hook`（实例级） |
| 注入 EKO 上下文 | 包装 `MemoryManager.get_context_for_prompt` |
| 装第二道安全门 | `core.safety.approval.set_approval_broker` |
| 注册自定义工具 | `ToolOrchestrator.register`（实例级，比全局 registry 干净） |

### 进程隔离

RxyCode 有一串**进程级全局单例**（工具注册表、两个缓存、prompt 注册表、TUI、token 统计、三个 broker）。完整清单见附录 A §6.3。

**对 LinkAgent 的影响比想象中小**，因为 LinkAgent 是**个人 agent**：一个用户、一个进程、一个 AgentV2。单例冲突需要"同进程两个不同配置的 Agent"才会发生。

唯一会撞上的场景是 **L7 的 A/B 评测**（同时跑 EKO 开 / EKO 关）。解决办法是**子进程隔离**，不要在同进程里切配置。这一条写进 L7。

---

## §8 目标目录结构

```
linkagent/
├── eko/                    ← L1，从 SkillForest 搬
│   ├── schema.py              FormalEKO / CandidateEKO
│   ├── engine.py              EKOEngine
│   ├── forest.py              森林存储
│   ├── index.py               SQLite 复合键索引
│   ├── conflict.py            五级优先级 + 动态置信度
│   ├── dependency.py          PCDR
│   └── corpus.py              语料冻结
├── distillation/           ← L5
│   ├── protocol.py            EvidencePacket + grounding
│   ├── runner.py              CandidateGenerator
│   ├── promotion.py
│   ├── mode_u.py              用户交互反思
│   └── aed.py                 已验证轨迹蒸馏
├── safety/                 ← L4
│   ├── checker.py             SAG 规则
│   └── broker.py              RxyCode ApprovalBroker 适配
├── bridge/                 ← L2，全新
│   ├── agent.py               AgentV2 包装
│   ├── context.py             EKO → prompt 注入
│   └── harvest.py             轨迹 → EvidencePacket
├── runtime/
│   ├── types.py               Protocol 定义
│   ├── turn.py                七步编排
│   └── telemetry.py
├── preset/                 ← L8
│   ├── loader.py              预置包装载与校验
│   ├── curate.py              离线策展脚本（skill → EKO）
│   └── packs/                 随应用分发的冻结包
├── tools/                  ← L5-6，agent 用来改 EKO 的工具
│   └── eko_tools.py
├── protocol/               ← L9-1，RxyCode 协议的扩展
│   ├── eko_requests.py        eko/* 查询方法（**没有写方法**）
│   ├── eko_events.py          event/eko_* 通知
│   ├── schema.py              合并导出
│   └── schema.json            冻结产物，提交进 git
├── appserver/              ← L9-2，桌面端唯一后端入口
│   ├── __main__.py            stdio JSON-RPC
│   ├── dispatch.py
│   └── handlers/
├── config.py
└── cli.py                     开发调试用，不是产品界面

desktop/                    ← L9-4，从 RxyCode Desktop fork
├── FORK-POINT.md              fork 自哪个 commit、改了什么、怎么 rebase
├── packages/protocol/         从合并 schema 生成的 TS 类型
└── src/                       Electron + React
```

**这个结构不要改。** 施工文档里每张卡都按这个路径写文件。

---

## §9 已定的产品决策（2026-08-01）

五个待定问题已经全部拍板。**这些是产品决策，不要在施工过程中改动。**

| # | 问题 | 决定 | 影响哪些文档 |
|---|---|---|---|
| 1 | 交付形态 | **独立 Desktop 应用，建在 RxyCode Desktop 之上**。不是 CLI，不是 RxyCode 的插件模式 | [`L9`](./L9-DESKTOP-APP.md)；CLI 降级为开发调试工具 |
| 2 | 模型选择 | **全部由用户选**，包括蒸馏模型。系统只提供默认建议 | [`L5`](./L5-EVIDENCE-AND-EVOLUTION.md)、[`L9`](./L9-DESKTOP-APP.md) |
| 3 | 数据目录 | **独立** `~/.linkagent/`，不与 `~/.rxycode/` 混用 | [`L0`](./L0-BOOTSTRAP.md) |
| 4 | 用户能否编辑 EKO | **能看，不能直接编辑。** 需要做 UI，但**只读**。改动只能通过与 agent 对话完成 | [`L5`](./L5-EVIDENCE-AND-EVOLUTION.md)、[`L9`](./L9-DESKTOP-APP.md) |
| 5 | 是否预置 EKO | **要预置，但不是别人的个人偏好**——预置的是**分区用的顶层 EKO**，由开源、可复用、高星、多人维护的 skill 构成 | [`L8`](./L8-PRESET-EKO-PACK.md) |

### 关于第 4 条：为什么只读 UI + 对话式修改

这个组合看起来别扭，其实是最稳的：

| 如果允许直接编辑 | 只读 + 对话式修改 |
|---|---|
| 用户手改 `procedure`，版本链断了 | 所有改动走 `EKOEngine` 的正式路径，版本链完整 |
| 手改绕过安全检查 | 改动经过 SAG 和审批 |
| 改完没有证据支撑，`provenance` 变成谎话 | 用户的话本身就是一条 `explicit_preference` 证据 |
| 用户要学 EKO 的 17 个字段 | 用户只需要说"别再用 os.path 了" |

**实现方式**：把 EKO 管理能力做成 **agent 的工具**（`eko_forget` / `eko_revise` / `eko_pause_learning` 等），用户用自然语言表达，agent 调工具，工具走引擎的校验路径。UI 只负责展示。

**而且这条不靠"前端不放按钮"来保证**：三个入口里只有工具能写——协议的 `eko/*` 全是查询方法，CLI 的 `eko` 子命令只有 `list`/`show`/`export`。前端就算想改也没有方法可调。契约测试见 [`APPENDIX-C §5.3`](./APPENDIX-C-INTERFACE-CONTRACTS.md#53-契约测试)。

### 关于第 5 条：我原来的建议是错的

我之前说"别预置，别人的偏好对新用户是噪声"。**那个判断只对个人偏好成立，对这里说的东西不成立。**

预置的不是"某个人喜欢用 tab 还是空格"，而是**领域分区的顶层锚点**——从社区维护的高质量 skill 提炼出来的通用工程实践。这类东西：

- 不属于任何个人，对所有用户都适用
- 有大量真实使用验证（高星 + 多人维护本身就是证据）
- 正好填补冷启动的空白：新用户第一天就有可用的经验层

**而且它和五级优先级天然契合**（见 §10）。

---

## §10 三层 EKO 模型

预置 EKO（L8）和手动导入（L10）的引入让森林变成三层。**这是核心数据模型，先理解它再看施工文档。**

```
┌─────────────────────────────────────────────────────────────┐
│  tier = community · 社区层（预置）                            │
│  来源：开源高星 skill 仓库,离线策展后随应用分发                │
│  owner：shared（对所有用户可见）                               │
│  优先级：DEFAULT (10)                                        │
│  path： <domain>/community/<slug>                            │
│  可变性：不可变。更新 = 整包替换                               │
│  例：python/community/test-driven-development                │
├─────────────────────────────────────────────────────────────┤
│  tier = imported · 导入层（用户手动放的 SKILL.md）             │
│  来源：用户下载或手写的 skill,过反向映射闸门入库                │
│  owner：当前用户                                              │
│  优先级：DEFAULT (10)  ← 和社区同级,因为没有执行证据            │
│  path： <domain>/imported/<slug>                             │
│  可变性：可随反馈演化,但优先级不会自动提升                      │
└────────────────────────┬────────────────────────────────────┘
                         │  两层都被个人经验覆盖
                         ▼
┌─────────────────────────────────────────────────────────────┐
│  tier = personal · 个人层（蒸馏产生）                         │
│  来源：Mode U 用户交互 + AED 已验证轨迹                        │
│  owner：当前用户                                              │
│  优先级：PERSISTENT_PERSONAL (40)                            │
│  path： <domain>/personal/<slug>                             │
│  可变性：随反馈演化,可回滚                                     │
│  例：python/personal/prefer-pathlib-over-ospath              │
└─────────────────────────────────────────────────────────────┘
```

> **`imported` 为什么和社区同级而不是和个人同级**：它虽然是用户主动放进来的，但**没有这个用户的执行证据**。从网上下一个 skill 不等于它适合这个项目——让它压过蒸馏出来的个人经验没有依据。分层的判据是"有没有该用户的证据"，不是"是不是用户放的"。

### 为什么这个分层不需要新机制

**五级优先级已经把它表达好了**（`conflict.py` 里现成的）：

```
SAFETY(100) > EXPLICIT_INSTRUCTION(80) > TASK_CONTEXT(60) > PERSISTENT_PERSONAL(40) > DEFAULT(10)
                                                                   ↑                      ↑
                                                              个人经验         社区预置 + 手动导入
```

**个人经验永远压过社区默认和手动导入，当次请求的显式指令又压过个人经验。** 这正是我们想要的语义，一行新代码都不用写。

### 两条必须守住的隔离

| 隔离 | 规则 | 为什么 |
|---|---|---|
| **id 命名空间** | 社区 EKO 的 id 前缀 `eko-community-`，个人的 `eko-modeu-` / `eko-aed-`，导入的 `eko-import-` | 整包替换社区层时，绝不能碰到用户的东西 |
| **owner 通配** | 社区 EKO 的 `scope.users = ["*"]`；**只有预置包构建流程能设这个值**，蒸馏路径和导入路径设了都要拒绝 | 否则模型可以自己造一条"所有人都适用"的经验 |

第二条和 L3 定的 `domain: ["*"]` 是同一类规则：**最强的断言必须由最可信的一方下**。

### EKO 与 Skill 的关系（一句话）

**EKO 是唯一权威对象。Skill 是它的打印件，或者是还没入库的原料。** EKO **不做 `skill_ref` 指针**——`procedure` / `preconditions` / `parameters` 全部内联在 `FormalEKO` 字段里，这样版本链只有一条。

三条路径、两条禁令、以及"RxyCode 的 `skill()` 工具能绕过全部治理"这个必须封的口子，全在 [`L10`](./L10-SKILL-INTEROP.md)。

---

## §11 交付形态：建在 RxyCode Desktop 之上的桌面应用

LinkAgent 是一个**独立的桌面应用**，而这个应用**建在 RxyCode 的 Desktop 上**——不是另起炉灶。

```
┌──────────────────────────────────────────────────────┐
│  LinkAgent Desktop（Electron + Vite + React）         │
│                                                       │
│  从 RxyCode Desktop fork：                            │
│    壳 / 子进程管理 / 打包 / 对话区 / 流式渲染          │
│    工具卡片 / 中断 / 审批模态框 / 设置页骨架            │
│                                                       │
│  LinkAgent 新增：                                     │
│    EKO 森林视图（只读）/ 检索解释面板 / 经验设置        │
└───────────────────────┬──────────────────────────────┘
                        │  JSON-RPC over stdio
                        │  （RxyCode 协议 + eko/* 扩展）
                        ▼
┌──────────────────────────────────────────────────────┐
│  python -m linkagent.appserver                        │
│  内部走 LinkAgent 的 TurnOrchestrator                  │
└───────────────────────┬──────────────────────────────┘
                        │  pip 依赖，不改源码
                        ▼
                    RxyCode
```

### 技术选型（跟随 RxyCode Phase 4，不重新讨论）

| 选择 | 理由 |
|---|---|
| **Electron** 而非 Tauri | RxyCode Phase 4 选了 Electron（团队没有 Rust 经验）。既然基于它做就得跟 |
| **JSON-RPC over stdio** 而非本地 HTTP | RxyCode 的协议就是 stdio。而且**没有端口就没有攻击面**——不需要绑 loopback、随机端口、会话令牌那一整套 |
| **协议类型从合并 schema 重新生成** | 类型只能有一个真源。手抄必然漂移 |
| **Electron 壳与 UI 组件 fork，钉住 commit** | LinkAgent 一定会分叉（多两个视图）。硬撑着共用只会两边都别扭 |

### ⚠ 这是整个 LinkAgent 唯一一处"等别人"的地方

| LinkAgent | 等 RxyCode | 约在 |
|---|---|---|
| L9-1 ~ L9-3（协议 + appserver + 类型） | **Phase 2**（`protocol/`、`appserver/`） | 2026-10-23 |
| L9-6 ~ L9-7（模型/成本摘要和设置显示） | **Phase 3**（ModelCatalog、resolver 和摘要协议） | W13–W15 |
| L9-4 ~ L9-8（Electron 壳与视图） | **主计划 Phase 4**（基础 Electron 壳、协议接入和最小交互） | W16–W23 |
| L9-4 ~ L9-8（Electron 壳与视图） | **Phase D**（完整 Desktop D1–D16） | Phase D 完成后 |

**这段等待期投给 L4/L5/L7/L8**——它们一个都不依赖桌面端。

> 如果 RxyCode Phase 4 延期，**不要自己另起一个壳赶进度**。造出第二套桌面代码等于放弃了"基于 RxyCode desktop"的全部好处。

### CLI 的定位

`linkagent` 命令**保留，但降级为开发调试工具**，不是给最终用户的产品界面。

它仍然有用——跑评测、查经验库、排查检索问题都靠它，而且比 UI 早几个月就能用。但**产品交付的是 Desktop**。

---

## §12 一句话总结

**LinkAgent 是一个独立的桌面应用：把 RxyCode 当执行底座，在它外面套一圈以 EKO 为中心的经验治理——检索什么经验、允不允许用、用完学到什么。**

经验分两层：社区预置的顶层分区 EKO（冷启动就能用）+ 用户自己蒸馏出来的个人经验（永远压过社区默认）。用户能在 UI 里看到整片森林，但改动只能通过跟 agent 说话完成。

施工顺序按实测收益排：先检索（收益最大，且必须先修作用域语义），再安全门（最便宜），再反馈演化（有前置依赖），依赖组合和冲突裁决代码搬过来但默认关掉。
