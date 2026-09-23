VERDICT: PASS

GX1-H、GX §1 及 DC-J1–J8 审核通过：

- 状态映射完整：drafts、active、ready、done 四列覆盖要求；未知状态归入 active 并显示 error。
- H5 `ThreadStatus` 与 `TurnStatus` 枚举均已纳入投影函数。
- 拖拽规则正确：仅允许 `drafts ↔ active`，`ready` 与 `done` 禁止拖拽。
- 全量线程投影，无丢卡；ready 卡提供 review 入口。
- failed、unknown 等异常状态卡片正确落入 active 并显示错误视觉状态。
- BoardView、BoardColumn、TaskCard 已覆盖四列、Review、三态菜单、拖拽标记及五态视觉状态。
- 已接入 board 视图、Ctrl+K 与顶栏入口；点击卡片复用 `selectSession` 返回 H5 会话。
- empty/loading/error/narrow/dark 五种视图状态及四列 testid 均有覆盖。
- 6/6 行为测试通过，`typecheck:node` 与 `typecheck:web` 通过。
- 未修改 appserver、schema 或 protocol；未因未 commit 判定失败。