# 用户七项需求 → 施工卡 → 自动化测试（双向追踪）

> 本表由用户对话中七项明确需求提炼；后续更改功能必须同步本表，不允许只是“某个 Phase 可能做了”。状态全部为 **PLANNED**，只有真实证据才可改为完成。

| R | 用户原始意图 | 权威设计 | 承接卡 | 功能验收/反证 |
|---|---|---|---|---|
| WEB-RQ01 | 用 Python 构建 | Core/Server/Worker/Runner 可安装五包；FastAPI | WEB-W1-C01..WEB-W1-C05、WEB-W2-C01..WEB-W2-C07 | PKG-01/RUN-01/E2E-WEB-01 |
| WEB-RQ02 | 明确合理技术栈 | LangGraph/FastAPI/Pydantic/PG/Redis/React/TS/Native/Cloud | WEB-W0-C02、WEB-W1-C01..WEB-W1-C04、WEB-W7-C05 | PROTO-01/DEPLOY-01 |
| WEB-RQ03 | 与传统后端的差异 | Durable Run、SSE、异步审批、Checkpoint、Journal、租约 | WEB-W2-C03..WEB-W2-C06 | SSE-01/02、RUN-02、REC-01/02 |
| WEB-RQ04 | Tools 增量并提升能力 | ToolSpec、动态 target，精准编辑、浏览器、Git、测试、CU | WEB-W1-C03、WEB-W6-C01..WEB-W6-C05 | TOOL-01/02、E2E-WEB-04、E2E-BROWSER-01 |
| WEB-RQ05 | 能真控制本机、Full 跳过 Sandbox | NativeBackend + Remote Grant + 急停；Cloud Sandbox 分开 | WEB-W4-C01..WEB-W4-C07、WEB-W5-C01..WEB-W5-C03 | E2E-FULL-01..06、RPC-04、SEC-GRANT-01 |
| WEB-RQ06 | 作为 AI 全栈求职项目 | Web 产品、Auth、任务闭环、CI、Eval、可复现 Demo | WEB-W3-C01..WEB-W3-C07、WEB-W5-C05、WEB-W7-C01..WEB-W7-C06 | E2E-RELEASE-01、EVAL-01、DEPLOY-01 |
| WEB-RQ07 | 最好改动，不要求最小改动 | 正式拆包但保单 Loop、可追溯数据/协议/权限、完整 UX | WEB-W0-C01..WEB-W0-C04、W1 全部、W2 全部、W3 全部 | PKG-01、PROTO-01、旧 CLI/Desktop regression |

## 追加隐含产品约束（继承之前的详细方案）

| R | 产品承诺 | 承接卡 |
|---|---|---|
| WEB-RQ08 | 三种入口 Local/Cloud/Hybrid 真运行 | WEB-W4-C01..WEB-W4-C05、WEB-W5-C01、WEB-W7-C06 |
| WEB-RQ09 | 设备离线/撤销、跨天审批、关闭浏览器仍运行 | WEB-W2-C03..WEB-W2-C06、WEB-W4-C03..WEB-W4-C06 |
| WEB-RQ10 | GitHub 实际 PR、文件 Diff、终端、浏览器预览 | WEB-W3-C04/C05、WEB-W5-C04/C05、WEB-W6-C02/C03 |
| WEB-RQ11 | 多 Agent 真委派、成本、Todo/Plan/记忆 | WEB-W6-C04/C05、WEB-W7-C03/C04 |
| WEB-RQ12 | 安全与云多租户、Prompt Injection、SSE IDOR | WEB-W5-C02/C06、WEB-W7-C01/C02 |
| WEB-RQ13 | Open source、部署、Demo、简历真实指标 | WEB-W7-C03..WEB-W7-C06 |

校验规则：每个 R 必须指向至少一个具体 `WEB-W*-C*` 卡与自动测试；每张卡必须至少指向一个产品/可靠性条目；漏链接视为文档门失败。由 `16-DOC-AUDIT-CHANGE-CONTROL.md` 规定的脚本核验。

## WEB-W0-C04 requirement rows

下面七行是本卡冻结的追踪。测试 ID 必须出现在 `tests/TEST-MATRIX.md`。这里不写“已落实”。

| id | owner | card | test_id |
|---|---|---|---|
| WEB-RQ01 | backend | WEB-W1-C01 | PKG-01 |
| WEB-RQ02 | architecture/research | WEB-W0-C02 | PROTO-01 |
| WEB-RQ03 | backend | WEB-W2-C03 | RUN-01 |
| WEB-RQ04 | backend | WEB-W1-C03 | TOOL-01 |
| WEB-RQ05 | backend | WEB-W4-C05 | SEC-GRANT-01 |
| WEB-RQ06 | product | WEB-W7-C03 | EVAL-01 |
| WEB-RQ07 | architecture | WEB-W0-C04 | PROTO-01 |
