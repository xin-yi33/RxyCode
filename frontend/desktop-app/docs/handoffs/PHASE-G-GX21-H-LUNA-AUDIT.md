VERDICT: PASS

GX21-H 审计结论：路径 B 合规，状态为 `BLOCKED_PREREQUISITE`。

- 未因看不到仓库判定 FAIL。
- 未修改 schema 或 appserver。
- 缺失清单包含 B17 方法：
  - `thread/list_deleted`
  - `thread/restore`
  - `thread/purge`
- 未以 `session/purge` 替代 B17 方法。
- 未 mock RPC。
- `TrashSection`、`TrashItem`、`PurgeConfirmDialog` 已实现，包含名称、删除时间、归属、永久删除文案、默认取消及二次确认。
- `buildThreadPurge(confirm=false)` 正确返回 `confirm_purge_required`。
- `confirm=true` 仍保持 BLOCKED，未虚构或发起 `thread/purge`。
- 回收站设置分区保持 blocked，符合 B17 尚未合入的前置条件。

测试可能因缺少 B17 探针或环境无法识别 `PurgeConfirmDialog` 而失败，但不改变路径 B 的合规结论。