# Architecture

本目录是 **G 之后的现行顺序与叠加施工卡**。体例对齐同级 [`PHASE-K`](../PHASE-K-PLUGIN-DUAL-MODE.md) / [`PHASE-L`](../PHASE-L-TEAM-ECOSYSTEM-DISTRO.md) / [`PHASE-N`](../PHASE-N-CLI-PARITY-LONGRUN.md)：§0 带「为什么」、任务卡带路径/步骤/代码草稿/可勾判据。不是摘要 README。

既有模块「现在做什么」仍看 [`docs/modules/`](../../../../modules/) 与 [`AGENTS.md`](../../../../../AGENTS.md)。PHASE-A…O / PHASE-FIX 卡正文 **不改逻辑**。

| 文件 | 角色 | 状态 |
|------|------|------|
| [DEV-ORDER.md](./DEV-ORDER.md) | **现行开发顺序**（每天流程、P0–P2、并行/串行、下一步、SP 卡） | Accepted |
| [MODULE-BOUNDARIES.md](./MODULE-BOUNDARIES.md) | 模块图、导入法、按缝变更预算、拆核 | Accepted |
| [PHASE-P-PRODUCT-INTENT.md](./PHASE-P-PRODUCT-INTENT.md) | 备忘叠加施工包（PP1…PP100，不是主链） | Accepted |
| [PHASE-L-TEAMS-INCREMENT.md](./PHASE-L-TEAMS-INCREMENT.md) | 加内置团可开工工作流（WFT0–WFT2） | Accepted |
| [CAPABILITY-MAP.md](./CAPABILITY-MAP.md) | 能力切分；CU 已按口述改口 | Accepted |
| [2026-09-01-as-is-audit.md](./2026-09-01-as-is-audit.md) | as-is 审计 | Evidence |
| [research/](./research/) | 前 20 核结构 + 愿望 Verdict | Evidence |
| [sources/RxyCode-产品意图备忘.md](./sources/RxyCode-产品意图备忘.md) | 备忘入库副本 | Source |

**怎么读：**

1. 现有模块「现在做什么」→ [`docs/modules/`](../../../../modules/) 与根目录 [`AGENTS.md`](../../../../../AGENTS.md)
2. 已冻结的协议增量 → [`docs/decisions/`](../../../../decisions/)（`G-PROTOCOL-*`）
3. Desktop/Phase G **已入库**产品卡 → [`docs/phase-g/`](../../../../phase-g/)；开工前先看冲突表
4. 本轮施工顺序与模块合同 → 本目录（已从 `docs/architecture/` 迁入 `docs/plans/opus5-plan/rxycode/architecture/`）

**现行顺序：** [DEV-ORDER.md](./DEV-ORDER.md)。架构决策 `ARCH-*` 在 [`docs/decisions/`](../../../../decisions/)。

**不要当现行施工图：** `docs/RxyCode_PLAN.md`、`docs/ENGINEERING_AUDIT.md`、未跟踪的 `00-EXECUTION-PLAN.md`。

**git：** 父仓 `.gitignore` 仍忽略 `docs/plans/`（不要改它）。本目录由嵌套仓 `docs/plans/opus5-plan` 跟踪。字母 PHASE 施工卡在磁盘同级目录。`docs/plans/opus5-plan/rxycode/phase-g/` 与已跟踪的 `docs/phase-g/` 是双份。
