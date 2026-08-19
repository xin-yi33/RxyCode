你是 RxyCode Phase GX 前端独立审计员。不要改代码。只审 GX3-H。不要以看不到仓库判 FAIL。未改 schema/appserver。feat/phase-g-frontend。不得因未 commit 判 FAIL。
对照 GX3-H + GX §1 + DC-J。

探针：schema 无 review/comment/add、review/comment/resolve → 路径 B BLOCKED_PREREQUISITE，不 mock。
已实现：五档 scope unstaged/staged/commit/branch/last_turn；评论状态 open→stale(hunk 失效)→resolved，stale 不可 reopen；下达草稿本地生成「请处理以下内联评论」；buildCommentAdd 在探针 B 返回 BLOCKED。
InlineComment + ReviewScopeSelector 五态。测试 4/4 pass。
第一行 VERDICT: PASS 或 FAIL。
