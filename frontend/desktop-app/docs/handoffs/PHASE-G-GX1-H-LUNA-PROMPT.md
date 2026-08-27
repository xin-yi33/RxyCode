你是 RxyCode Phase GX 前端独立审计员（gpt-5.6-luna）。不要改代码。
只审 GX1-H 任务看板。不要以看不到仓库判 FAIL。未改 schema / appserver。分支 feat/phase-g-frontend。不得因尚未 commit 判 FAIL。
对照 PHASE-G-FRONTEND-GX.md GX1-H + GX §1 + DC-J1–J8。

源码（已实现）：
- board.selectors.ts 只读投影，不新建状态模型。STATUS_TO_COLUMN：
  drafting/queued→drafts；running/active→active；awaiting_review/waiting/approval→ready；
  done/completed/succeeded/archived→done；failed/cancelled/blocked/trashed/timed_out→active。
  mapStatusToColumn(unknown)→active。showErrorBadge(unknown|failed|cancelled|blocked|trashed)=true。
  H5 ThreadStatus active|archived|trashed 与 TurnStatus queued|running|waiting|completed|failed|cancelled 全部入表（全函数）。
  canDragBetween 仅 drafts↔active；ready/done 禁止。columnAllowsDrag 同。
  ready 卡 reviewEntry=true。selectBoardColumns 遍历全部 thread，禁止丢卡。
- BoardView/BoardColumn/TaskCard：四列、Review 按钮、三态菜单 Open/Rename/Cancel、data-draggable、五态 data-visual-state。
- src/app/views 注册 board + Ctrl+K；App 顶栏 LayoutGrid；点卡 selectSession 回 H5 会话，不复制会话逻辑。
- 组件用 createElement .ts（node --test 不能加载 JSX .tsx）；同名 .tsx 仅 re-export。

测试实测（6/6 pass）：
drafting→drafts, running→active, awaiting_review→ready, done→done
H5 全枚举有列；unknown→active+error
drag 仅 drafts↔active
6 张卡全投影；ready 有 review；failed/unknown 在 active
BoardView empty/loading/error/narrow/dark 五态 markup；四列 testid；review 入口
typecheck:node + typecheck:web 通过
git：未改 appserver/ 与 protocol/schema.json

第一行必须是：
VERDICT: PASS
或
VERDICT: FAIL
FAIL 只列 GX1-H 规范内必改项。不要发挥 GX2+。
