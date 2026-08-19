# Phase G 文档目录

Phase G 所有施工与基线文档集中在这里，避免主链 / 增强 / 前后端抢同一份文件再解冲突。

| 文件 | 谁写 | 在哪条分支改 |
|---|---|---|
| [`PHASE-G-DESKTOP.md`](./PHASE-G-DESKTOP.md) | 公共基线（只读，除非改产品定义） | 尽量不动 |
| [`backend/PHASE-G-BACKEND.md`](./backend/PHASE-G-BACKEND.md) | 主链 B1–B13 + P3 B14–B18 | `feat/phase-g-backend` |
| [`backend/PHASE-G-BACKEND-GX.md`](./backend/PHASE-G-BACKEND-GX.md) | 增强 GX*-B | `feat/phase-g-backend` |
| [`frontend/PHASE-G-FRONTEND.md`](./frontend/PHASE-G-FRONTEND.md) | 主链 H1–H13 + P3 H14–H19 | `feat/phase-g-frontend` |
| [`frontend/PHASE-G-FRONTEND-GX.md`](./frontend/PHASE-G-FRONTEND-GX.md) | 增强 GX*-H | `feat/phase-g-frontend` |
| [`PHASE-G-CONFLICT-AUDIT.md`](./PHASE-G-CONFLICT-AUDIT.md) | 登记表 | 谁改谁提交 |
| [`BRANCHING.md`](./BRANCHING.md) | 分支怎么走 | 两端都遵守 |

旧路径 `docs/plans/opus5-plan/rxycode/PHASE-G-*.md` 只留跳转。
