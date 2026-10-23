# WEB-W7-C02 self-audit

- [x] 真实故障注入：worker 用独立子进程真杀（os.kill / taskkill 等价物），Redis 用 DEBUG SLEEP 制造超时，Postgres 用 docker pause 断连，Runner 断连后按 call_id 重放；无 mock 冒充崩溃。
- [x] 审批中崩溃：approval 保持 pending，恢复后恰好一次执行，无重复 tool run。
- [x] 副作用已执行但 ACK 丢失：journal_state=unknown、run recovery_required，重试不再执行（恰好一次写）。
- [x] 断线恢复：真实 uvicorn socket + httpx 流，运行中断连，Last-Event-ID 续传；事件以完整 SSE 帧计，seq 集合 1..final 恰好一次，终态保留，跨租户无泄漏。
- [x] stale lease：pause 后旧 epoch 在 commit_terminal 和 run_shell_before_ack 都被拒。
- [x] 资源释放：进程级 reaping Job（kill-on-close，无限额）由 worker 自指派继承，CreateProcess 原子入列——无 create->bind 窗口；按命令关闭句柄杀后台进程的回归已消除并有测试钉住；后台进程在 worker 存活时继续活、worker 被杀后 10s 内回收。
- [x] 并发安全：句柄在初始化（含自指派）完成后才发布；test_w7_c02_reaping_handle_published_last 钉住。
- [x] at-least-once：stream 逐事件上限 max(1, attempts)，无 exactly-once 声明；queue.py 未改。
- [x] 非权限边界：reaping Job 不限制写路径；attach_sandbox 仍 SANDBOX_FORBIDDEN；os_sandbox 启用路径 fail-closed 未动。
- [x] 红绿证据：red.txt 记录预期失败；green.txt 记录最终测试与三轮审计修复复跑；chaos-report.json 由 CLI 生成。
- [x] 诚实标注：E2E-CHAOS-01（浏览器真实 Run + 断连 + kill worker）标 BLOCKED（apps/web 无 Playwright 依赖、无浏览器线束），不以 mock 替代；同语义由真实 socket 层模块测试与 chaos CLI 覆盖。
- [x] 无泄漏：无 rxy-w7c02* 容器残留，无 c02marker/c02bg 进程残留。
- [x] `git diff --check` 干净；evidence 文件 LF/UTF-8。
- [x] 审计结论：gpt-6.1-sol high（Codex 会话 01a140a7-2cc1-7f61-bdab-2af627f08e80，与既往同一会话）对父仓提交 ebe2bc768104622306fc6ad721aac8e3505ce8cb 返回 VERDICT: NO_REMAINING_PROBLEMS（w7c02-audit-3.json）。前两轮各发现并修复 4/3 条。