VERDICT: PASS

- GX3-H 五档 Scope 已实现：unstaged / staged / commit / branch / last_turn。
- `InlineComment` 与 `ReviewScopeSelector` 五态已实现。
- 评论生命周期符合要求：`open → stale`（hunk 失效）→ `resolved`，且 `stale` 不可 reopen。
- 下达草稿可本地生成「请处理以下内联评论」。
- 探针 B 中 `buildCommentAdd` 返回 `BLOCKED_PREREQUISITE`，未 mock；路径 B 合规，不构成 FAIL。
- 测试 4/4 pass。
- 未因未 commit 判定失败；本端未发现 GX3-H 必改项。