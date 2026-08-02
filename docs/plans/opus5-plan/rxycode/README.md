# RxyCode 施工文档索引

> **项目**：RxyCode —— 一个已经在跑的 AI 编码助手
> **仓库**：`D:\agent-demo\RxyCode\RxyCode1_1_0`
> **目标形态**：headless 核心 + 类型化协议 + 多个薄客户端（Codex App Server 式）
>
> **干活之前先读** [`../MODEL-ASSIGNMENT.md`](../MODEL-ASSIGNMENT.md)  
> 全部卡由 **Composer 主写**（后端 + 前端）→ [`../COMPOSER-2.5-PLAYBOOK.md`](../COMPOSER-2.5-PLAYBOOK.md) · 前端卡内标注的「多模态环节」委托 Grok → [`../GROK-FRONTEND-PLAYBOOK.md`](../GROK-FRONTEND-PLAYBOOK.md)

---

## 这个项目最大的风险是回归

RxyCode 有存量代码、有用户。这里的每一次改动都在动**已经能跑的东西**——`core/agent_v2.py` 一个文件就 3700 行。

所以本项目所有任务卡在通用验收之外，**额外强制一条**：

```powershell
python -m evals.cli run --backend agent --compare-baseline evals\baselines\latest-agent.json
```

**基线不绿，这张卡就没做完。** 不管你觉得改动多无害。

> Phase 1 之前基线还不可信（评测 harness 本身有问题，见主计划 §1.4）。
> 那之前用 `python -m pytest tests -q --timeout=600` 兜底。

---

## 路线全景

```
Phase 0 止血 ──► Phase 1 Harness ──► Phase 2 协议与核心 ──► Phase 3 Desktop 基础壳
  W1–W2            W3–W5               W6–W12                W13–W20
                                          │
                                          └──► Phase A 模型适配
                                                   │
                                                   └──► Phase B 隔离式子代理
                                                            │
                                                            └──► Phase C 专家团编排
                                                                     │
                                                                     └──► Phase D RxyCode Desktop 完整工作台
                                                                              │
                                                                              └──► Phase E 多模型协作
                                                                                       │
                                                                                       └──► Phase F 多模态

Phase G 的六张预留卡不在主链上，插进 B/C/D/E 里顺手做
```

---

## 文档一览

| 顺序 | 文档 | 内容 | 前置 | 工期 |
|---|---|---|---|---|
| **1** | [`00-EXECUTION-PLAN.md`](./00-EXECUTION-PLAN.md) | **主计划**。Phase 0 止血 / Phase 1 评测 / Phase 2 协议与核心解耦 / Phase 3 Desktop。含事实基线、历史复盘、排期、维护手册 | — | 20 周 |
| **2** | [`PHASE-A-MODEL-ADAPTATION-LAYER.md`](./PHASE-A-MODEL-ADAPTATION-LAYER.md) | 模型适配层：provider 策略、能力元数据、per-model 优化（DeepSeek / Claude / Qwen） | Phase 0 + 1 | 3 周 |
| **3** | [`PHASE-B-ISOLATED-SUBAGENT.md`](./PHASE-B-ISOLATED-SUBAGENT.md) | **隔离式子代理**：Primary/Subagent、Child Session、独立上下文、权限、预算、Task、`@`、事件和恢复 | Phase 0–3 + A | 8–12 周 |
| **4** | [`PHASE-C-MULTI-AGENT-ORCHESTRATION.md`](./PHASE-C-MULTI-AGENT-ORCHESTRATION.md) | 多 Agent 专家团：Coordinator、AgentSpec / SOP 状态机 / 机械验证门 / 成本熔断 / 难度路由；复用 Phase B Runtime | Phase 0–3 + A + B | 8 周 |
| **5** | [`PHASE-D-RXYCODE-DESKTOP.md`](./PHASE-D-RXYCODE-DESKTOP.md) | **完整 Desktop 工作台**：项目、workspace、Thread、工具执行、审批、diff/review、文件预览、worktree、恢复、扩展契约、打包发布 | 主计划 Phase 0–3 + A + B + C 公共契约 | 12–16 周 |
| **6** | [`PHASE-E-MULTI-MODEL-COLLABORATION.md`](./PHASE-E-MULTI-MODEL-COLLABORATION.md) | 多 Agent × 多模型：每角色不同模型、master 模型、跨模型交接、成本核算、结对编程、归因仲裁 | Phase A + B + C；Desktop 交互接入依赖 D | 6 周 |
| **7** | [`PHASE-F-MULTIMODAL.md`](./PHASE-F-MULTIMODAL.md) | 多模态：ContentBlock 全链路、附件存储、视觉 Agent 角色 | 主计划 Phase 3 + A + B + C + D + E | 6 周 |
| **附** | [`PHASE-G-PERSONA-AGENT-INTERFACE.md`](./PHASE-G-PERSONA-AGENT-INTERFACE.md) | PersonaAgent 接口预留（**不是施工图**）：skill 元数据、蒸馏数据埋点、信任边界。六张卡插进 B/C/D/E 里做 | 无硬前置 | 6 天 |

---

## Phase 排期（来自主计划 §3.2）

> **下面的周次是按"人写代码"估的，实际执行是两个 Composer 窗口，按卡走不按日历走。** 真实的执行顺序、并行度和文件冲突表见 [`../ENGINEERING-TIMELINE.md`](../ENGINEERING-TIMELINE.md)。这张表现在只能当"Phase 之间的相对大小和依赖顺序"读。

| Phase | 周次 | 日期 | 出口标准 |
|---|---|---|---|
| Phase 0 止血 | W1–W2 | 08-03 ~ 08-14 | `ruff check .` 进 CI；CORS 收紧；无跟踪的 `.bak`；CI 双 Python 版本 |
| Phase 1 Harness | W3–W5 | 08-17 ~ 09-04 | evals 跑真实 Agent；坏任务修完；evals 进 CI；基线落盘 |
| Phase 2 协议与核心 | W6–W12 | 09-07 ~ 10-23 | `protocol/` 有 schema 且能生成 TS 类型；stdio JSON-RPC 可跑；`api_server.py` 变薄 |
| Phase 3 Desktop | W13–W20 | 10-26 ~ 12-18 | 三平台打包；对话/流式/审批/设置可用 |

---

## 关于已移出路线的旧设想

原来这里有一份 `PHASE-F-SKILLFOREST-PERSONA-AGENT.md`。它已经**移到** [`../linkagent/ARCHIVE-PHASE-F-ORIGINAL-VISION.md`](../linkagent/ARCHIVE-PHASE-F-ORIGINAL-VISION.md)。

原因有两个：

1. 那部分内容后来独立成了 **LinkAgent 项目**，不再是 RxyCode 的一个 Phase
2. 它基于的是论文的**旧版本**，结论已被新版论文的实测数据推翻（详见 [`../linkagent/APPENDIX-B-PAPER-EVIDENCE.md`](../linkagent/APPENDIX-B-PAPER-EVIDENCE.md)）

**不要按那份文档施工。** 它保留下来只为追溯当时的判断依据。

---

## 这条路线上明确不做的事

出自主计划 §3.4。看到旧文档里提这些，忽略：

Kubernetes / Helm / 多租户、Telegram / Discord Bot、Skills 自动创建、可视化工作流编辑器、LSP 深度集成。

---

## 与 LinkAgent 的关系

**RxyCode 不因为 LinkAgent 改动任何一行。** LinkAgent 通过 `pip install rxycode` 依赖本项目，桌面端应基于本项目 Phase D 的稳定 Desktop 壳和扩展契约 fork；Phase 3 只提供壳的基础前置。

**这不需要 RxyCode 做任何额外工作，但有三处值得知道**：

| Phase | LinkAgent 怎么用它 | 对本项目的要求 |
|---|---|---|
| **Phase 2** | 桥接层依赖 `AgentV2` 的公开方法；appserver 复用 `protocol/` 的 pydantic 模型 | 改公开签名或协议模型时，**在 PR 描述里提一句**。LinkAgent 有超集契约测试会发现，但提前说能省一次排查 |
| **Phase D** | fork 完整 Desktop 壳，钉住扩展契约和 commit | **DC-A1/DC-A3（协议边界与 capability）值钱得多了**——它同时决定 LinkAgent 的 rebase 成本 |
| **Phase 2 的 `protocol-client`** | 优先作为 npm 依赖使用；拿不到就 vendor 传输层 | 如果顺手能发布到 npm，LinkAgent 那边会省一点事。**不发布也不影响** |

除此之外，两条路线互不干涉。**不要为了 LinkAgent 的方便去改 RxyCode 的设计**——那正是把它们拆成两个项目要避免的事。
