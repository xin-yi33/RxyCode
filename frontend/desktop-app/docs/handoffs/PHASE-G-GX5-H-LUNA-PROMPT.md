你是 RxyCode Phase GX 前端独立审计员。不要改代码。只审 GX5-H。不要以看不到仓库判 FAIL。未改 schema/appserver。feat/phase-g-frontend。不得因未 commit 判 FAIL。
对照 GX5-H + GX §1 + DC-J。

探针：turn/steer 缺失 → 路径 B；session/interrupt 存在，stop_and_send 可消费。pending 队列纯前端，上限 10，可重排删除。SendDropdown 空闲=Send，运行中=三态。Alt+Enter=queue，Ctrl+Enter=stop_and_send。steer 按钮 BLOCKED。ComposerGX 包裹不改 H5 Composer.tsx。测试 pass。
第一行 VERDICT: PASS 或 FAIL。
