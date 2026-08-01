# LinkAgent 施工文档索引

> **项目**：LinkAgent —— 一个独立的桌面应用，在 RxyCode 之上加一层以 EKO 为中心的个性化经验治理
> **仓库**：待建，`D:\agent-demo\LinkAgent`（独立 repo）
> **来源**：SkillForest 研究代码 + *Individualized Agent* 论文
>
> **干活之前先读** [`../MODEL-ASSIGNMENT.md`](../MODEL-ASSIGNMENT.md)  
> 全部卡（L0–L8、L10、L9-1~L9-8）由 **Composer 主写** → [`../COMPOSER-2.5-PLAYBOOK.md`](../COMPOSER-2.5-PLAYBOOK.md)  
> 前端卡（L9-4~L9-7）内标注的「多模态环节」委托 Grok 辅助 → [`../GROK-FRONTEND-PLAYBOOK.md`](../GROK-FRONTEND-PLAYBOOK.md)

---

## 这个项目的一句话

**RxyCode 负责把活干了，LinkAgent 负责记住这个用户怎么干活、并在下次可靠地用上。**

**硬约束：RxyCode 一行都不改。** LinkAgent 通过 `pip install rxycode` 依赖它。任何一张卡如果需要改 RxyCode 源码，按 Playbook 规则 C8 停下来报告。

---

## 五条产品决策（已定，不要在施工中改）

| # | 决定 |
|---|---|
| 1 | **独立桌面应用，建在 RxyCode Desktop 之上**（Electron，fork 后加自己的视图）。`linkagent` CLI 保留但只是开发调试工具 |
| 2 | **模型全部由用户选**，包括蒸馏模型 |
| 3 | 数据目录 **`~/.linkagent/`**，与 `~/.rxycode/` 分开 |
| 4 | EKO **能看不能直接编辑**。改动只能通过跟 agent 对话完成 |
| 5 | **预置一批社区顶层 EKO**（来自开源高星多人维护的 skill），解决冷启动 |

展开论证见 [`00-OVERVIEW-AND-ARCHITECTURE.md §9–§11`](./00-OVERVIEW-AND-ARCHITECTURE.md#9-已定的产品决策2026-08-01)。

---

## 从哪开始读

| 你的情况 | 读这个 |
|---|---|
| 第一次接触这个项目 | [`00-OVERVIEW-AND-ARCHITECTURE.md`](./00-OVERVIEW-AND-ARCHITECTURE.md) —— 定位、EKO 是什么、一个 turn 长什么样 |
| 想知道"为什么先做 X 不先做 Y" | [`APPENDIX-B-PAPER-EVIDENCE.md`](./APPENDIX-B-PAPER-EVIDENCE.md) —— 实测数字与它的约束力 |
| 想知道"哪些代码是现成的" | [`APPENDIX-A-ASSET-INVENTORY.md`](./APPENDIX-A-ASSET-INVENTORY.md) —— 资产清单 |
| **想查某个字段/方法/事件叫什么** | [`APPENDIX-C-INTERFACE-CONTRACTS.md`](./APPENDIX-C-INTERFACE-CONTRACTS.md) —— **所有接口的权威定义** |
| **想知道下一张做哪个卡、另一个窗口能同时跑什么** | [`../ENGINEERING-TIMELINE.md`](../ENGINEERING-TIMELINE.md) —— 双窗口并行顺序与冲突表 |
| 准备动手写代码 | 从 [`L0-BOOTSTRAP.md`](./L0-BOOTSTRAP.md) 开始，一张卡一个会话 |

---

## 施工顺序

顺序**不是**按流程从左到右排的，是**按实测收益**排的。

```
地基（必做，无收益但绕不过）
  L0 建仓 ──► L1 EKO 核心 ──► L2 RxyCode 桥接
                                    │
                                    ├──────────► L9 Desktop（壳可以从这里并行起）
                                    ▼
按实测收益排序
  L3 情境化检索  ← 移除损失 −1.85 pp（最大）+ 修作用域语义
       │
       ├──────────────► L7 评测（建议从这里就并行开始）
       ├──────────────► L8 预置社区 EKO 包（并行，但要先有 L10-2）
       ▼
  L4 安全门控    ← 移除损失 −1.54 pp，纯代码零 LLM
       │
       ├──────────────► ⚠ L10-4 封住 skill 工具旁路（止血，紧跟 L4）
       ▼
  L5 经验采集与反馈演化  ← 移除损失 −1.46 pp，⚠ 硬依赖 L3
       │
       ├──────────────► L9 的 EKO 视图需要 L3 + L5
       ├──────────────► L10-3 运行期 Skill 导入
       ▼
  L6 依赖组合 + 冲突裁决  ← 端到端无显著效应，默认关闭

横切（不是阶段，六张卡散插在 L1~L5 之间，见 L10 §3）
  L10 EKO ↔ Skill 双向映射
```

**关键路径是 L0→L1→L2→L3→L5。** L7、L8、L9 都能并行，别串着做。

**L10 是横切的。** 它的六张卡各有各的位置：L10-1/2/5 只要 L1 就能做（而且 **L10-2 是 L8-2 的前置**），L10-4 紧跟 L4，L10-3 等 L5。

---

## 文档一览

| 阶段 | 文档 | 内容 | 卡数 | 工时 |
|---|---|---|---:|---:|
| — | [`00-OVERVIEW-AND-ARCHITECTURE.md`](./00-OVERVIEW-AND-ARCHITECTURE.md) | 定位、EKO 概念、turn 流程、复用边界、**产品决策、三层 EKO 模型、交付形态** | — | — |
| **L0** | [`L0-BOOTSTRAP.md`](./L0-BOOTSTRAP.md) | 建仓、依赖策略、目录骨架、数据目录、CI | 5 | 2 天 |
| **L1** | [`L1-EKO-CORE.md`](./L1-EKO-CORE.md) | 移植 EKO v2 栈，用冻结语料验证搬对了 | 6 | 5 天 |
| **L2** | [`L2-RXYCODE-BRIDGE.md`](./L2-RXYCODE-BRIDGE.md) | 契约测试、执行包装、上下文注入、审批 broker、轨迹回收、turn 骨架 | 6 | 6 天 |
| **L3** | [`L3-RETRIEVAL-AND-SCOPE.md`](./L3-RETRIEVAL-AND-SCOPE.md) | 情境推断、**domain 硬闸**、检索接入、跨域回归、可观测性 | 5 | 6 天 |
| **L4** | [`L4-SAFETY-GATE.md`](./L4-SAFETY-GATE.md) | 编码场景规则、**组合风险**、两道门接线、误报追踪 | 4 | 4 天 |
| **L5** | [`L5-EVIDENCE-AND-EVOLUTION.md`](./L5-EVIDENCE-AND-EVOLUTION.md) | 证据落盘、Mode U、AED、后台蒸馏、反馈演化、**只读查看 + 对话式修改** | 6 | 8.5 天 |
| **L6** | [`L6-COMPOSITION-AND-CONFLICT.md`](./L6-COMPOSITION-AND-CONFLICT.md) | 依赖推断、组合接入、冲突接入、**开关决策** | 4 | 4 天 |
| **L7** | [`L7-EVAL-HARNESS.md`](./L7-EVAL-HARNESS.md) | 任务集、A/B 运行器、评分器、统计报告、首次基线 | 5 | 6 天 |
| **L8** | [`L8-PRESET-EKO-PACK.md`](./L8-PRESET-EKO-PACK.md) | 包格式与装载、离线策展、首批内容、接进检索、更新安全 | 5 | 5 天 |
| **L9** | [`L9-DESKTOP-APP.md`](./L9-DESKTOP-APP.md) | 协议扩展、appserver、TS 类型、**fork RxyCode Electron 壳**、只读森林视图、检索解释、设置、打包 | 8 | 17 天 |
| **L10**<br>*横切* | [`L10-SKILL-INTEROP.md`](./L10-SKILL-INTEROP.md) | 出站映射、Skill 解析器、运行期导入、**封住 RxyCode 的 skill 旁路**、provenance 规范、往返测试 | 6 | 6 天 |
| 附 | [`APPENDIX-A-ASSET-INVENTORY.md`](./APPENDIX-A-ASSET-INVENTORY.md) | SkillForest / RxyCode 可复用资产清单 | — | — |
| 附 | [`APPENDIX-B-PAPER-EVIDENCE.md`](./APPENDIX-B-PAPER-EVIDENCE.md) | 论文实测数字与它对施工顺序的约束力 | — | — |
| 附 | [`APPENDIX-C-INTERFACE-CONTRACTS.md`](./APPENDIX-C-INTERFACE-CONTRACTS.md) | **五道边界的全部接口定义**，字段冲突时以它为准 | — | — |
| 归档 | [`ARCHIVE-PHASE-F-ORIGINAL-VISION.md`](./ARCHIVE-PHASE-F-ORIGINAL-VISION.md) | ⛔ **已作废**，结论被新论文推翻。只为追溯保留 | — | — |

**合计 60 张卡，约 69.5 天串行工时。** L7/L8/L9/L10 并行的话关键路径约 42 天。

---

## 五条最重要的约束

### ① L5 必须等 L3 做完

反馈演化的端到端效果在两个模型上**方向相反**（DeepSeek +2.69 pp，Doubao −5.62 pp，摆动 8.15 pp）。根因是作用域语义放行过宽导致的跨域负迁移。

**L3 修的就是这个。在 L3 之前打开 L5，等于放大一个已知缺陷**——经验库越大，负迁移越严重。

L5 动手前先跑：

```powershell
python -m pytest tests/eko/test_cross_domain_regression.py -v
```

跨域泄漏必须是 0。

### ② L6 默认关闭

依赖组合和冲突裁决在端到端消融里**没有显著效应**（置信区间跨 0，点估计甚至略高于完整系统）。它们的组件级测试很强，但那是在"EKO 里真的有依赖元数据"的前提下——而真实语料里那个字段是空的。

**代码搬过来，开关留着，等 L7 的评测说话。**

### ③ 拿到自己的数字之前不要声称有用

论文的 +5.27 pp 是在 100 条受控序列、两个特定模型、沙箱工具上测出来的。LinkAgent 的任务分布、工具、执行路径全都不同，而且**主动改了作用域机制**。

**只能测，不能推。**

### ④ "不能直接编辑 EKO"是协议层的保证，不是 UI 约定

如果只靠"前端不放编辑按钮"，这条迟早被绕过。

**做法**：三个入口里只有一个能写。

| 入口 | 能写吗 | 守它的测试 |
|---|---|---|
| 协议 `eko/*` | ❌ 全是查询方法 | `test_no_eko_mutation_methods_exist` |
| CLI `linkagent eko` | ❌ 只有 `list`/`show`/`export` | `test_cli_has_no_write_commands` |
| agent 工具 | ✅ **唯一入口** | `test_write_tools_require_approval` |

任何变更只能发生在一次 turn 内部，由 agent 调 [`L5-6`](./L5-EVIDENCE-AND-EVOLUTION.md) 的工具完成，走引擎的校验路径——版本链、证据、审批一个不少。完整定义见 [`APPENDIX-C §5`](./APPENDIX-C-INTERFACE-CONTRACTS.md#5-agent-工具边界)。

### ⑤ RxyCode 有一个能绕过全部治理的工具，必须封

**这条最容易被忽略，因为它不阻塞任何卡。**

RxyCode 默认注册了 `skill(name)`（`core/agent_v2.py:1499,1519`）。它在四个目录 `rglob` 任意 `SKILL.md` 并**整段返回**——没有域过滤、没有安全门、没有版本、没有 provenance。旁边 `:1536` 的 `download_skill_tool` 还能从 URL 装。

> **在 [`L10-4`](./L10-SKILL-INTEROP.md) 合并之前，L3 的域门、L4 的安全门、L5 的证据链全都可以被一句 `skill("xxx")` 抵消。**

**排期**：紧跟 L4（那时 approval broker 已接好，封的成本最低）。**必须早于 L7 首次基线**，否则基线测出来的"治理有效性"不可信。

**封法不是禁用它**——兼容 `~/.claude/skills` 是好设计。是加一道闸：有 EKO 背书的放行（且返回 Forest 内容而非磁盘内容），裸的拒绝并引导走 `skill_import`。

---

## 与 RxyCode 的排期关系

**LinkAgent 有两处硬依赖 RxyCode 的排期，都在这张表里。**

| 场景 | 结论 |
|---|---|
| RxyCode 做 Phase 0/1 | 无关，随便并行 |
| RxyCode 做 **Phase 2**（协议 + 核心重构，约 2026-10-23） | ⚠ 会改 `AgentV2` 的对外形态。**LinkAgent 的 L2 与 L9-1~L9-3 等它落地**，否则要返工 |
| RxyCode 做 **Phase 3**（Electron Desktop，约 2026-12-18） | ⚠ **LinkAgent 的 L9-4~L9-8 fork 它的壳**，必须等 |
| RxyCode 做 Phase A/B/C/D/E | 无关 |
| LinkAgent 做 L0/L1 | 完全不碰 RxyCode，随时可做 |

**双窗口并行的实际排法在** [`../ENGINEERING-TIMELINE.md`](../ENGINEERING-TIMELINE.md)。摘要：**Composer 主写全部（L0–L8、L10、L9-1~L9-8 / RxyCode Phase 3），Grok 只做前端卡标注的多模态环节（视觉验收）**；早期 Grok 经常空闲——正常，别让它写代码。L2 等 Phase 2；L9-4 等 Phase 3。

**两个真冲突点（都是 Composer 主写时自己的排期问题）**：`eko/engine.py`（L3-3 与 L8-4）和 `tools/eko_tools.py`（L5-6 与 L10-3），各自必须串行。

> ⚠ 如果 Phase 3 延期，**不要自己另起一个壳赶进度**。造出第二套桌面代码等于放弃了"基于 RxyCode desktop"这个决定的全部好处。

---

## 还没定的事

产品层面的五个问题已经全部拍板（见本文开头）。**剩下的都是需要用实测回答的，不是靠讨论能决定的：**

| 问题 | 谁来回答 |
|---|---|
| 经验层在编码任务上到底有没有收益？ | [`L7-5`](./L7-EVAL-HARNESS.md) 的首次基线 |
| 预置社区包对冷启动有没有帮助？ | [`L8 §5`](./L8-PRESET-EKO-PACK.md) 的四组对照 |
| L6 的动态置信度值不值得打开？ | [`L6-4`](./L6-COMPOSITION-AND-CONFLICT.md) 的开关决策报告 |

**这三个都可能得到"没用"的答案。** 每一个都配了能证伪自己的测量——这是有意的。
