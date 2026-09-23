# PhaseG-H15 自审

卡：会话栏三分类重构
分支：feat/phase-g-frontend
协议变化：none（pin/deleted 只投影；B17 未合入 → 回收站 BLOCKED_PREREQUISITE）

## 完成判据

1. 三分类：置顶 / 项目(workspaceRoot) / 最近；pin 来自 pinnedIds，不造后端数据。
2. 折叠 + `>`/`v` + 4px；折叠状态 localStorage `rxycode.desktop.sessionFold.v1`。
3. hover 取样 rgba(0,0,0,0.06)/rgba(255,255,255,0.08) 写入 CSS 与 data-hover-*；对照 docs/gx-screenshots/h15-hover-sample.md。
4. 回收站：listDeletedAvailable=false 时 BLOCKED，不 mock thread/list_deleted。
5. 五态：sessionVisualState 覆盖 empty/loading/error/narrow/dark；测试通过。

## 验收

- typecheck:web 通过
- SessionList.test.mts + sessionCategories.test.ts 通过

## DC

- 纯投影，不改 Thread 真相
- 不 mock B17
