你是 GX 前端审计员。只审 GX8-H。不要以看不到仓库判 FAIL。未改 schema。
GX §1-16：协议缺失必须 BLOCKED_PREREQUISITE，不得 mock。路径 B 且缺失清单完整 = 本端合规 PASS，不是 FAIL。

已实现：
- session/rename 存在（路径 A 消费）
- thread/fork、thread/pin、thread/archive 缺失；buildFork 返回 BLOCKED + missing list
- 仅 user message 可 fork
- 本地搜索脱敏、排除删除线程
- SessionMenu 四件套（pin/archive 按钮标注 BLOCKED）
测试 pass。

第一行必须 VERDICT: PASS 或 VERDICT: FAIL。
FAIL 只列「本端本应做却没做」的项。不要把对端缺失协议当成 FAIL。
