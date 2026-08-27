# G-UPSTREAM-B15 · HARNESS.md vendor

```text
上游仓库: https://github.com/HKUDS/CLI-Anything
官方文档: cli-anything-plugin/HARNESS.md
锁定 commit: 6f372d36f8ea43dd2af23fda96646c8088ac7d2f (CLI-Anything HEAD 2026-08-19)
license: Apache-2.0 (docs/agents/harness/LICENSE 全文入库)
复用模式: vendor (HARNESS.md 正文) + semantic-port (7 阶段 + /refine /validate 技能模板)
实际复用文件: docs/agents/harness/HARNESS.md, docs/agents/harness/LICENSE
RxyCode 适配: appserver/harness_service.py, appserver/skills/harness/*/SKILL.md
不兼容证据: 上游是 agent SOP 文档 + OpenCode 命令插件，不是 appserver 技能注册表；生成成本依赖 Phase B 缓存（C8）
保留的上游语义: Analyze→Design→Implement→Plan Tests→Write Tests→Document→Publish；真实软件硬依赖；禁止 reimplement
RxyCode 独有扩展: BLOCKED_PREREQUISITE 门、B14 独立 venv 安装/launch、C-E handwritten-wrapper 回灌
验证命令: python -m pytest tests/test_harness_skill -q
升级风险: 上游 HARNESS.md 增补 preview 规范时需重 vendor
回滚: revert this card commit
owner: composer-2.5
```
