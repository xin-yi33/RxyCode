你是 GX 前端审计员。只审 GX11-H 修复。不要以看不到仓库判 FAIL。未改 schema。
filterSessions：projectId 空串或缺省 = 全部项目，不得把有 projectId 的会话滤掉。
用例：sessions=[{id:'1',status:'running',projectId:'p1'}], query={status:'all',projectId:''} 必须仍返回该会话。
running 锁定配置/历史，Composer 保留。测试 pass。
第一行必须逐字：VERDICT: PASS 或 VERDICT: FAIL。
路径 B / 对端缺失不是 FAIL。
