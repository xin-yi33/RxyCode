# WEB-W7-C03 self-audit

- [x] 30-task fixed taskset（coding/browser/recovery/remote），sha256 定版，含 designed-fail 任务；oracle 复用 evals CHECK_TYPES。
- [x] `test_w7_c03_contract`/`test_w7_c03_negative`/`test_w7_c03_integration` 真绿（连同追加测试共 16 passed），无无故 skip。
- [x] 指标真实：cli-solo/web-solo 两个 cell 用配置的 deepseek 端点真跑（真实 token 消耗、真实 wall-clock 超时如实记录），team 两格实现但未真跑并在 NOTES.md 明示；未使用 project_team 的建模数字。
- [x] 预算真执行：in-flight 取消 + budget_tokens 下推；超支任务记 budget_exceeded 且已耗 token 入账。
- [x] 失败计入分母；blocked 排除出分母但 spend 计入总量；异常成本单列不被均值吞掉。
- [x] 质量门禁真实拒绝：happy-demo-only / 未知 task_id / 空 blocked 理由 / 空结果 / 重复行 / 未声明 cell / manifest hash 不符，全部违规。
- [x] durable spine 失败不谎报：spine 写/读失败 → status=error，oracle_status 保留；逃逸异常经 spend_sink 保住 run 身份并尽力收尾（usage + fenced commit_terminal）。
- [x] 环境 reset：每个 (cell,task) 全新 workdir，陈旧产物不残留。
- [x] 可复核来源：manifest 记录 executed_sources sha256 + 脏树 diff。
- [x] 诚实标注：E2E-EVAL-01 部分覆盖（2/4 cell 真跑，规模 sample）；cli-team/web-team 未真跑不声称完成。
- [x] `git diff --check` 干净；evidence 文件 LF/UTF-8。
- [x] 审计结论：gpt-6.1-sol high（Codex 会话 01a140a7-2cc1-7f61-bdab-2af627f08e80）对父仓提交 1944203497016e010b8a8ab8d2bd63887b628f1d 返回 VERDICT: NO_REMAINING_PROBLEMS（w7c03-audit-5.json）。前 4 轮共修 14 条。