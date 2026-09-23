VERDICT: PASS

GX8-H 本端审计结果：

- `session/rename` 已实现，满足路径 A 消费要求。
- `thread/fork`、`thread/pin`、`thread/archive` 协议缺失，已按 `BLOCKED_PREREQUISITE` 处理，未进行 mock。
- `buildFork` 返回 `BLOCKED`，并提供完整 `missing list`；路径 B 处理符合要求，不构成 FAIL。
- 已限制仅 user message 可 fork。
- 本地搜索已脱敏，并排除已删除线程。
- `SessionMenu` 四件套已具备；pin/archive 按钮明确标注 `BLOCKED`。
- 测试通过。

本端不存在“应做但未做”的项。