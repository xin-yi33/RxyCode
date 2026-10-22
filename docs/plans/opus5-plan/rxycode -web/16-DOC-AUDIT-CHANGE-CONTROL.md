# 旧文档审读审计、版本追踪与变更治理

> **来源**：用户 `docs.zip`，实收 zip entries 1066。`docs/plans/` 下共 889 archive entries（含目录、二进制、evidence）；其中可解析的非 `.git` 文本文件为 303 份（.json:2, .md:174, .py:41, .txt:86）。源文件目录树与 SHA 见 [`research/SOURCE-INDEX.md`](research/SOURCE-INDEX.md)。二进制 RAR、git 对象和 `docs/assets` 大媒体未当成开发规范正文。

## §1 审读与优先级说明

优先精读：
- `../MODEL-ASSIGNMENT.md`、`../COMPOSER-2.5-PLAYBOOK.md`、`../ENGINEERING-TIMELINE.md`：谁写、单卡、停工、交接、分支/评审规范。
- `../rxycode/README.md`、`../rxycode/00-EXECUTION-PLAN.md`：权威旧主路线、R1 现状、旧 Phase 施工卡固定格式。
- `../rxycode/architecture/DEV-ORDER.md`、`MODULE-BOUNDARIES.md`：活顺序、SP0–SP3、模块缝、禁止抢其他 owner。
- `../rxycode/phase-g/backend/PHASE-G-BACKEND.md`、`frontend/PHASE-G-FRONTEND.md` 与 conflict audit：协议/客户端双方施工、真实证据、不能有重复状态真相。
- `../rxycode/PHASE-UPDATE-01.md`、`PHASE-UPDATE-02.md`、`PHASE-UPDATE-02-TESTS.md`、`PHASE-P-AGENTIC-TIMEOUT-LOOP.md`：现有 Browser、CU、Todo、Context、Durability、Timeout 等现有卡不得双开。

**浏览规模声明**：对全部 303 个旧规划文本已完成程序读取、路径/字节数/哈希核对；针对主要执行规范、架构权威和任务卡样例进行了内容级精读。历史 evidence 和各 Phase 超大正文没有人工逐行复核，施工仍须按卡重新打开对应原文，这与 Composer Playbook “只读该卡”相一致。未将所有旧文本复制到新计划，避免双权威。

## §2 固定施工卡格式（本 Web 48 卡严格继承）

`卡号/标题 → 优先级/工时/依赖/owner → 背景与当前事实 → 文件白名单+Grep → 已经替你决定好的 → 否定边界 → TEST-first 操作步骤 → Unit/Module/Negative/E2E Given/When/Then → 可复制 PowerShell 命令 → 完成判据 → 一卡一 Commit`。

增加 Web 特有强制项：租户权限、Run/Event/Target/Grant/Checkpoint/Journal 多真相边界、SSE replay 竞态、Native Full 真实证据、面向求职的 Demo/Eval 真实性。所有卡处于未完成状态，禁止预填 PASS。

## §3 旧计划冲突教训继承

- 旧 `PHASE-G-CONFLICT-AUDIT` X14 记录 `docs/plans` 未跟踪导致文档丢失，W0-C01 首先解决版本追踪；不能只把 ZIP 存本地就称已入库。
- 旧文档出现卡号碰撞/章节锚点歧义，本项目卡号采用 `WEB-Wn-Cxx` 且可由脚本逐卡核对；引用不得只写 `P1`。
- `MODULE-BOUNDARIES.md` 不准为一个新表面增加第二套 Agent/Tool Loop；本 Web 包拆分必须兼容 ARCH-001。
- 旧测试包强制 Given/When/Then、没有证据不勾完成；本 Web `tests/TEST-MATRIX.md` 采取同样规则。

## §4 变更控制 / 审计门

- 改 PRD、Run 状态机、公开协议/Full 的任何设计，要新增或修改一个 ADR，记录理由、替代方案、负面影响，更新 `13-CONFLICT-AUDIT.md` 与需求映射。
- 每个卡的实现只允许其白名单文件；若发现需要表外文件，提交 `CONTRACT_CONFLICT` 等待批准，再修改本卡或新增卡，不在本次实现中偷改。
- `WEB-W0-C01` 核验 `git check-ignore -v` 和 `git ls-files`，对本 Web 目录建立独立可追踪规则，禁止一次性无审计把 `docs/plans` 的历史 RAR/私有 evidence 全部强行入 Git。
- 文档只有一次单项的写入源；不在 README、Wave、测试包维护第二份独立可执行卡面。权威卡面永远只在 `phases/PHASE-Wn-*.md`。

## §4.1 WEB-W0-C01 现场基线（2026-10-16）

父仓库 `D:\agent-demo\RxyCode\RxyCode1_1_0` 的 HEAD 是 `ed9cacb3228d0526936e25dfdaf911aaf20d89ed`，施工分支是 `feat/rxycode-web`，没有上游，未推送。旧权威 `docs/plans/opus5-plan/rxycode/architecture/DEV-ORDER.md` 首行仍是「活开发顺序」，本卡不改它。

`git check-ignore -q` 的实测：`rxycode -web/README.md` 在父仓库和 `docs/plans/opus5-plan` 内嵌仓库都不是忽略对象；`docs/plans/opus5-plan.rar`、`.env`、旧 `rxycode/architecture/DEV-ORDER.md` 仍被忽略。父仓库 `.gitignore` 只对 `rxycode -web/` 开了例外，没有把 `docs/plans` 整树放进来。

`docs/plans/opus5-plan` 自己有 `.git`（开工时 HEAD `5578d74`，无 remote）。父仓库因此把它看成内嵌仓库，不能把其中的 Markdown 收成父仓库 blob。Web 文档的内容提交在这个内嵌仓库的 `feat/rxycode-web`，父仓库的 `feat/rxycode-web` 提交 `.gitignore`、`tests/web/w0/` 和 `evidence/web/WEB-W0-C01/`。这不是第二套计划权威。

`CONTRACT_CONFLICT` 已在本卡白名单改正：`phases/PHASE-W0-RESEARCH-BASELINE.md` 的 WEB-W0-C01 文件表加入既有 `scripts/check_plan.py`。契约测试调用这个已有扫描器，不另建模块。

## §5 本次生成产物的范围

本次只**编写开发文档**和用于执行时创建的目标文件/命令规范；没有在用户 D 盘直接修改代码，没有跑用户 Windows 项目测试，没有部署 Cloud，没有提交 Git，也没有把 48 张卡标成完成。
