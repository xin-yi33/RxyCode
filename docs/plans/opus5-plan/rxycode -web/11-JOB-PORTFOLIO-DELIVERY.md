# AI 全栈求职成果验收（不是宣传稿）

> **定位**：AI Full Stack Developer / Agent Engineer / LLM App Engineer 的代表项目。不能保证录用，也不能假装具有真实商业用户或企业级性能。一个可真实体验、可复现、可追问的全栈作品更有说服力。

## §1 三个必须真实运行的 Demo

| Demo | 可见的用户流程 | 所验证的能力 |
|---|---|---|
| Cloud Coding | GitHub 登录→导入样例 Repo→运行修复→真实 pytest→Monaco Diff→GitHub PR | React、FastAPI、Worker、PG、Sandbox、Git API |
| Remote Native Full | `rxycode connect` 配对→本机确认→Web 发任务→桌面截图/键鼠/终端→急停 | Runner/WSS/RPC、本机 OS、权限、审计 |
| Durable Team | 发起长任务→关闭 Web→重新进入→重放事件→审批→恢复→Team Trace | SSE、Checkpoint、Journal、异步任务、多 Agent |

公共 Demo 提供访客受限额度与固定测试仓，未授权的访客绝不能获得宿主 Full 权限。

## §2 招聘能力→可面试证据

| 能力 | 产物 |
|---|---|
| Python/FastAPI | OpenAPI、Pydantic 契约、状态机和授权测试 |
| PostgreSQL/Redis | migration、Outbox、lease fencing、SSE replay 测试 |
| React/TS | Web 真状态工作台、错误/响应式、前端 E2E |
| LangGraph / Agent | 单一 AgentV2 loop、真正 Tool RPC、Checkpoint、Team Agent Trace |
| OS/Distributed | Native Full、WSS、Grant、ConPTY、急停、设备重连 |
| Cloud/Security | Sandbox 多租户隔离、SSRF/IDOR、CI/部署、审计 |
| Evaluation | 固定任务集、真实成功率、Token/成本/耗时、失败统计 |

## §3 面试能讲清的问题

为什么 Run 是 202 异步任务而不是 HTTP 等模型？为什么 SSE+WSS、为何不能只 Redis pubsub？为什么 LangGraph Checkpoint 不替代 Tool Journal？为什么 ToolOrchestrator 一处安全门？Full 怎么真正在本机 Native OS 跑却不把远程授权交给 Cloud Server？多租户怎么保护 Device/Preview/Artifact？如何比较 Solo 与 Team 而不是只贴效果视频？K8s/pgvector 为什么没有未经证据就滥加？

## §4 简历文案（**只有功能做完才能使用，数字必须真测**）

**RXYCode — 自研本地/云端混合 AI Agent 全栈平台**。设计 Core/Server/Worker/Runner/Web 架构；用 Python/FastAPI、LangGraph、React/TS、PostgreSQL、Redis 构建持久化 Run/事件与跨端工具执行；实现具备本机授权的 Remote Full Native Runner、云端隔离工作区及真实 Coding→Test→Diff→PR 工作流；使用真实任务集测得 `[成功率]`、`[P95]`、`[token/费用]` 并公开可复现报告。

发布证据清单：公开 HTTPS Demo、GitHub README/ADR/部署说明、CI 状态、测试与 Eval 报告、两分钟真实演示视频、威胁模型、release tags；若某项未完成，简历删除对应声称而不是补造。
