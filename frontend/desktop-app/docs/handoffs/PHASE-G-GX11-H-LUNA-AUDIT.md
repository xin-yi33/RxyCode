VERDICT: PASS

GX11-H 修复符合要求：

- `filterSessions` 在 `projectId` 为空字符串或缺省时视为全部项目。
- 不会过滤掉带有 `projectId` 的会话。
- 用例 `sessions=[{id:'1',status:'running',projectId:'p1'}]`、`query={status:'all',projectId:''}` 可返回该会话。
- `running` 状态锁定配置/历史，Composer 保留。
- 未修改 schema。
- 测试通过。
- 路径 B / 对端缺失不构成 FAIL。