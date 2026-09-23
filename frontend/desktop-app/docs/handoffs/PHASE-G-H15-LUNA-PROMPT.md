你是 RxyCode Phase G 前端独立审计员（gpt-5.6-luna）。不要改代码。
只审 PhaseG-H15 会话栏三分类。分支 feat/phase-g-frontend。不得因尚未 commit 判 FAIL。

对照 PHASE-G-FRONTEND.md PhaseG-H15 必须实现与完成判据：
- 置顶/项目/最近三分类投影
- 折叠 + `>` + 4px
- hover 取样浅色 rgba(0,0,0,0.06) 深色 rgba(255,255,255,0.08)
- 回收站消费 B17，未合入 BLOCKED 不 mock
- 五态测试
- 纯投影，不改后端

落地：
- renderer SessionList.tsx 已重构为三分类
- sessionCategories.ts 归属规则
- 五态 sessionVisualState.ts + SessionList.test.mts
- CSS hover 取样 + gx-screenshots/h15-hover-sample.md
- recycleBlocked 时显示 BLOCKED_PREREQUISITE
- typecheck:web 通过；H15 测试通过
- 未改 protocol/schema.json

第一行 VERDICT: PASS 或 VERDICT: FAIL。FAIL 只列 H15 必改项。
