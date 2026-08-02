# opus5-plan · 两个项目的施工文档总索引

> **这里有两个独立的项目。** 别把它们的文档混着读。
>
> **更新**：2026-08-01（**Composer 主写全部 · Grok 辅助前端多模态**；新增 L10；森林三层 tier）

---

## 先读这个

1. **[`MODEL-ASSIGNMENT.md`](./MODEL-ASSIGNMENT.md)** —— **谁主写、谁辅助**（权威）
2. 按角色读纪律：
   - 主写（后端 + 前端都归它）→ [`COMPOSER-2.5-PLAYBOOK.md`](./COMPOSER-2.5-PLAYBOOK.md)
   - 辅助（前端多模态环节）→ [`GROK-FRONTEND-PLAYBOOK.md`](./GROK-FRONTEND-PLAYBOOK.md)
3. **排期与双开** → [`ENGINEERING-TIMELINE.md`](./ENGINEERING-TIMELINE.md)

**一句话分工：Composer 主写全部代码（Python / schema / appserver / Electron / React / TS UI）；Grok 只在写前端用到多模态（视觉）时才辅助。**

---

## 两个项目是什么关系

```
┌─────────────────────────────────────────────────────────────┐
│  RxyCode                                                     │
│  一个 AI 编码助手。已经在跑，有用户，代码要继续演进。          │
│  目标形态：headless 核心 + 类型化协议 + 多个薄客户端           │
│                                                              │
│  仓库：D:\agent-demo\RxyCode\RxyCode1_1_0                    │
│  路线：Phase 0/1/2/3 → Phase A/B/C/D                        │
└────────────────────────┬────────────────────────────────────┘
                         │
                         │  pip install rxycode
                         │  （只依赖，不修改）
                         ▼
┌─────────────────────────────────────────────────────────────┐
│  LinkAgent                                                   │
│  一个新的独立**桌面应用**。把 RxyCode 当作"执行底座"，       │
│  在上面加一层以 EKO 为中心的个性化经验治理。                  │
│                                                              │
│  仓库：待建（独立 repo）                                      │
│  来源：SkillForest 研究代码 + Individualized Agent 论文       │
│  路线：L0 → L9                                               │
│  形态：fork RxyCode Desktop（Electron）+ 自己的 appserver     │
└─────────────────────────────────────────────────────────────┘
```

**两处排期硬依赖**：LinkAgent 的 L2 与 L9-1~L9-3 等 RxyCode **Phase 2**（协议）；L9-4~L9-8 等 **Phase C**（完整 Desktop 壳、扩展契约和基础工作台）。主计划 **Phase 3** 只是 Phase C 的基础壳前置。

**关键约束：RxyCode 本体不因为 LinkAgent 而改动一行。**

这是"套壳"的全部含义——LinkAgent 通过 `pip install` 依赖 RxyCode，用它公开的扩展缝（hook、memory 包装、工具注册、审批 broker）接入，而不是 fork 它的源码。任何一张 LinkAgent 的卡如果需要改 RxyCode 源码，都要停下来先讨论。

---

## 目录结构

```
docs/plans/opus5-plan/
├── README.md                        ← 你在这里
├── MODEL-ASSIGNMENT.md              ← 模型分工权威（Composer 主写全部 / Grok 辅助前端多模态）
├── COMPOSER-2.5-PLAYBOOK.md         ← 主写纪律（后端 + 前端）
├── GROK-FRONTEND-PLAYBOOK.md        ← 辅助纪律（前端多模态环节）
├── ENGINEERING-TIMELINE.md          ← 双窗口并行顺序、门与冲突表
│
├── rxycode/                         ← RxyCode 的施工文档
│   ├── README.md                       路线索引与排期
│   ├── 00-EXECUTION-PLAN.md            主计划 Phase 0–3
│   ├── PHASE-A-MODEL-ADAPTATION-LAYER.md
│   ├── PHASE-B-MULTI-AGENT-ORCHESTRATION.md
│   ├── PHASE-C-RXYCODE-DESKTOP.md     ← 完整桌面端工作台
│   ├── PHASE-D-MULTI-MODEL-COLLABORATION.md
│   ├── PHASE-E-MULTIMODAL.md
│   └── PHASE-F-PERSONA-AGENT-INTERFACE.md
│
└── linkagent/                       ← LinkAgent 的施工文档
    ├── README.md                       路线索引与排期
    ├── 00-OVERVIEW-AND-ARCHITECTURE.md 定位、架构、复用边界
    ├── L0-BOOTSTRAP.md                 建仓与骨架
    ├── L1-EKO-CORE.md                  EKO 核心移植
    ├── L2-RXYCODE-BRIDGE.md            与 RxyCode 对接
    ├── L3-RETRIEVAL-AND-SCOPE.md       情境化检索（收益最大）
    ├── L4-SAFETY-GATE.md               安全门控
    ├── L5-EVIDENCE-AND-EVOLUTION.md    经验采集与反馈演化
    ├── L6-COMPOSITION-AND-CONFLICT.md  依赖组合与冲突裁决
    ├── L7-EVAL-HARNESS.md              评测
    ├── L8-PRESET-EKO-PACK.md           预置社区 EKO 包（冷启动）
    ├── L9-DESKTOP-APP.md               桌面应用（产品交付形态）
    ├── L10-SKILL-INTEROP.md            EKO ↔ Skill 双向映射（横切，含治理止血卡）
    ├── APPENDIX-A-ASSET-INVENTORY.md   可复用资产清单
    ├── APPENDIX-B-PAPER-EVIDENCE.md    论文实测数字与它的约束力
    ├── APPENDIX-C-INTERFACE-CONTRACTS.md  五道边界的接口权威定义
    └── ARCHIVE-PHASE-F-ORIGINAL-VISION.md  历史文档（结论已被推翻，见文件内说明）
```

---

## 我该读哪个

| 你要做的事 | 去哪 |
|---|---|
| 干活之前先搞清谁主写、谁辅助 | [`MODEL-ASSIGNMENT.md`](./MODEL-ASSIGNMENT.md) |
| 主写纪律（后端卡 + 前端卡） | [`COMPOSER-2.5-PLAYBOOK.md`](./COMPOSER-2.5-PLAYBOOK.md) |
| 辅助纪律（前端多模态环节） | [`GROK-FRONTEND-PLAYBOOK.md`](./GROK-FRONTEND-PLAYBOOK.md) |
| **搞清下一张做什么、两个窗口怎么不打架** | [`ENGINEERING-TIMELINE.md`](./ENGINEERING-TIMELINE.md) |
| RxyCode 的任何开发 | [`rxycode/README.md`](./rxycode/README.md) |
| LinkAgent 的任何开发 | [`linkagent/README.md`](./linkagent/README.md) |
| 搞清 LinkAgent 到底要建什么 | [`linkagent/00-OVERVIEW-AND-ARCHITECTURE.md`](./linkagent/00-OVERVIEW-AND-ARCHITECTURE.md) |
| 想知道"为什么先做 X 不先做 Y" | [`linkagent/APPENDIX-B-PAPER-EVIDENCE.md`](./linkagent/APPENDIX-B-PAPER-EVIDENCE.md) |
| 想知道 LinkAgent 的产品形态定成什么样了 | [`linkagent/00-OVERVIEW-AND-ARCHITECTURE.md §9–§11`](./linkagent/00-OVERVIEW-AND-ARCHITECTURE.md#9-已定的产品决策2026-08-01) |
| 查某个字段/方法/事件的准确定义 | [`linkagent/APPENDIX-C-INTERFACE-CONTRACTS.md`](./linkagent/APPENDIX-C-INTERFACE-CONTRACTS.md) |
| 搞清 EKO 和 SKILL.md 到底什么关系 | [`linkagent/L10-SKILL-INTEROP.md`](./linkagent/L10-SKILL-INTEROP.md) |

---

## 两条路线能并行吗

> **完整的周级排期与双窗口分工在** [`ENGINEERING-TIMELINE.md`](./ENGINEERING-TIMELINE.md)**。下面只讲耦合点。**

**可以，而且推荐并行。** 两个仓库、两套代码，物理隔离。

唯一的耦合点是：**LinkAgent 依赖 RxyCode 的公开接口**。所以：

| 场景 | 结论 |
|---|---|
| RxyCode 做 Phase 0/1（止血、评测） | 与 LinkAgent 完全无关，随便并行 |
| RxyCode 做 Phase 2（协议 + Session 重构） | ⚠ 会改 `AgentV2` 的对外形态，LinkAgent 的 L2 桥接层要跟着调整。**LinkAgent 的 L2 与 L9-1~L9-3 等 Phase 2 落地**，否则要返工 |
| RxyCode 做 **Phase 3**（Electron 壳） | 只提供 Desktop 的基础壳、协议接入和最小交互；不等于完整桌面工作台 |
| RxyCode 做 **Phase C**（完整 Desktop） | ⚠ **LinkAgent 的 L9-4~L9-8 应基于 Phase C 的扩展契约和稳定壳 fork**，否则会重复实现项目、Thread、审批和 diff 基础设施 |
| RxyCode 做 Phase A/B/D/E/F | LinkAgent 只要不用这些新能力就不受影响；涉及多模型/多模态时以 capability 兼容为准 |
| LinkAgent 做 L0/L1（建仓、EKO 核心） | 完全不碰 RxyCode，随时可做 |

**最省事的排法**：LinkAgent 先做 L0 + L1（纯自己的代码，零依赖），这段时间 RxyCode 推进 Phase 0–2 和 Phase A/B；协议稳定后做 L2→L3；等 RxyCode Phase C 的 Desktop 扩展契约冻结后，再做 L9 桌面前端。L4/L5/L7/L8 可在等待窗口并行推进。

---

## 历史文档

`docs/plans/` 下还有更早的文档（`2026-07-02-*`、`2026-07-27-*`、`2026-07-30-*`、`execution/`）。它们**已经不是权威版本**，保留只为追溯。以本目录为准。
