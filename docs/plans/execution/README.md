> ## ⛔ 本文件已作废（2026-07-31）
>
> **请改读 [`2026-07-31-EXECUTION-PLAN.md`](./2026-07-31-EXECUTION-PLAN.md)。**
>
> 本文件及 `00-master-plan.md`、`01-tech-debt-cleanup.md`、`QUICKSTART.md`、
> `DAILY-CHECKLIST.md`、`DELIVERY-SUMMARY.md` 派生自
> `docs/plans/2026-07-30-comprehensive-review-and-roadmap.md`，该报告存在多处
> 未经实测的事实错误（评测分数无效、AgentV2 方法数错误、竞品品类混淆），
> 且按 6 人团队 / $630,740 预算编写，与实际的 2–3 人团队不匹配。
>
> 勘误明细见新文件的 §2.3。以下内容仅作历史记录保留，**不要按它执行**。

---

# RxyCode 工程项目执行总览

**创建日期：** 2026-07-30
**项目周期：** 2026年8月1日 - 2027年1月31日（6个月）
**总预算：** $630,740

---

## 📁 文档索引

本目录包含RxyCode项目的完整执行计划，分为7个独立模块：

### 已创建文档

1. **[00-master-plan.md](./00-master-plan.md)** - 项目总览和主计划
   - 项目目标、里程碑、团队配置
   - 预算估算、风险管理、KPI
   - 开发流程、文档体系

2. **[01-tech-debt-cleanup.md](./01-tech-debt-cleanup.md)** - 技术债务清理计划
   - AgentV2重构（20天）
   - 循环依赖修复（15天）
   - 测试覆盖率提升（12天）
   - 统一命令系统（8天）

### 待创建文档（请使用以下模板）

3. **02-desktop-mvp.md** - Desktop应用MVP开发
   - Electron脚手架（2天）
   - 主窗口UI（5天）
   - WebSocket通信（3天）
   - 流式消息渲染（3天）
   - 设置页面（3天）
   - 工具调用显示（4天）
   - 跨平台打包（3天）
   - 测试（3天）

4. **03-skills-auto-creation.md** - Skills自动创建
   - 轨迹分析模块（5天）
   - 模式提取引擎（8天）
   - Skill代码生成（10天）
   - 自动测试系统（5天）
   - A/B测试框架（2天）

5. **04-messaging-platform.md** - 消息平台集成
   - Telegram Bot（10天）
   - Discord Bot（8天）
   - 消息路由系统（5天）
   - 跨平台会话同步（5天）
   - 语音消息支持（2天）

6. **05-visual-workflow-editor.md** - 可视化工作流编辑器
   - React Flow集成（10天）
   - 节点库开发（8天）
   - 工作流保存加载（3天）
   - 执行可视化（5天）
   - 调试功能（5天）
   - 模板市场（4天）

7. **06-enterprise-deployment.md** - 企业级部署方案
   - 多租户架构（15天）
   - Kubernetes部署（10天）
   - Helm Chart（5天）
   - 监控告警（8天）
   - 备份恢复（5天）
   - 安全加固（2天）

8. **07-integration-and-release.md** - 集成测试与发布
   - 端到端测试（15天）
   - 性能测试（10天）
   - 安全测试（5天）
   - 用户验收测试（10天）
   - 文档完善（5天）
   - Beta发布（5天）
   - 正式发布（5天）

---

## 🎯 快速开始指南

### 第一周必做事项（2026年8月1-7日）

#### Day 1: 项目启动
```bash
# 1. 创建项目管理看板
- 在GitHub Projects或Jira中创建项目
- 添加所有里程碑和任务
- 分配责任人

# 2. 设置开发环境
git clone <repo-url>
cd RxyCode
git checkout -b feature/phase1-tech-debt

# 3. 配置CI/CD
- 审查 .github/workflows/ci.yml
- 添加新的检查项
- 配置通知

# 4. 团队会议
- 项目启动会（2小时）
- 技术方案评审（1小时）
```

#### Day 2-3: 技术预研
```bash
# 1. AgentV2重构预研
cd core
python -c "import ast; tree = ast.parse(open('agent_v2.py').read()); print(len([n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]))"
# 输出：44个方法

# 2. 依赖分析
pip install pydeps
pydeps core --max-bacon=2 -o deps.svg
# 查看deps.svg，标记循环依赖

# 3. Desktop技术栈验证
mkdir -p desktop-poc
cd desktop-poc
npm create vite@latest . -- --template react-ts
npm install electron vite-plugin-electron
# 验证Electron + Vite能否正常工作
```

#### Day 4-5: 编写设计文档
```bash
# 创建架构设计文档
touch docs/architecture/agent-v2-refactoring.md
touch docs/architecture/dependency-refactoring.md
touch docs/architecture/desktop-architecture.md

# 填写设计内容（参考各模块执行计划）
```

#### Day 6-7: Sprint 1启动
```bash
# 1. Sprint计划会
- 确定Sprint 1目标：完成AgentV2重构设计
- 任务拆分和估算
- 提交第一批PR

# 2. 开始编码
git checkout -b refactor/agent-v2-phase1
# 开始创建新的类文件
```

---

## 📊 进度跟踪

### 每周报告模板

复制以下模板用于每周进度报告：

```markdown
# 周报 - 第X周（日期）

## 本周完成
- [ ] 任务1：描述 - 完成度X%
- [ ] 任务2：描述 - 完成度X%

## 下周计划
- [ ] 任务1：描述
- [ ] 任务2：描述

## 风险和阻碍
- 风险1：描述 - 影响：高/中/低
- 阻碍1：描述 - 需要的支持

## 数据指标
- 代码提交数：X
- PR合并数：X
- 测试覆盖率：X%
- Bug数量：X

## 团队动态
- 人员变动：无/有（说明）
- 需要的资源：无/有（说明）
```

### 里程碑检查清单

#### M1: 技术债务清理（2026-09-10）
```markdown
验收清单：
- [ ] AgentV2拆分为7个类
- [ ] 所有类单元测试覆盖率>80%
- [ ] 0处循环依赖（pydeps验证）
- [ ] 测试覆盖率达到75%
- [ ] 所有CI检查通过
- [ ] 文档更新完成
- [ ] Code Review通过
- [ ] 合并到main分支

交付物：
- [ ] docs/architecture/agent-v2-refactoring.md
- [ ] docs/architecture/dependency-refactoring.md
- [ ] core/planner/goal_planner.py + tests
- [ ] core/decomposer/task_decomposer.py + tests
- [ ] core/executor/task_executor.py + tests
- [ ] core/validator/result_validator.py + tests
- [ ] core/memory/memory_manager.py + tests
- [ ] core/cache/cache_manager.py + tests
- [ ] core/safety/safety_manager.py + tests
- [ ] core/commands/（统一命令系统）
```

#### M2: Desktop MVP（2026-09-15）
```markdown
验收清单：
- [ ] Windows打包成功（.exe）
- [ ] macOS打包成功（.dmg）
- [ ] Linux打包成功（.AppImage）
- [ ] 基础对话功能可用
- [ ] WebSocket连接稳定
- [ ] 流式消息正常显示
- [ ] 设置页面可用
- [ ] 工具调用可视化
- [ ] 至少5个用户测试通过

交付物：
- [ ] desktop/（完整Electron项目）
- [ ] docs/architecture/desktop-architecture.md
- [ ] docs/user-guide/desktop-quickstart.md
- [ ] 安装包（3个平台）
- [ ] 发布说明
```

---

## 🔧 开发规范

### Git工作流

```bash
# 1. 创建功能分支
git checkout -b feature/module-name

# 2. 提交代码（使用Conventional Commits）
git commit -m "feat(core): 添加GoalPlanner类

- 从agent_v2.py中提取目标规划逻辑
- 添加单元测试
- 更新架构文档

Refs: #123"

# 3. 推送并创建PR
git push origin feature/module-name
gh pr create --title "feat(core): 添加GoalPlanner类" --body "详细描述..."

# 4. Code Review后合并
gh pr merge --squash
```

### 提交信息规范

```
<type>(<scope>): <subject>

<body>

<footer>
```

**Type类型：**
- `feat`: 新功能
- `fix`: Bug修复
- `refactor`: 重构
- `test`: 测试
- `docs`: 文档
- `chore`: 构建/工具
- `style`: 代码格式

**Scope范围：**
- `core`: 核心模块
- `desktop`: Desktop应用
- `api`: API服务器
- `tools`: 工具系统
- `tests`: 测试

**示例：**
```
feat(core): 实现Skills自动创建

- 添加轨迹分析器
- 实现模式提取算法
- 集成LLM代码生成
- 添加自动测试框架

测试覆盖率：85%
Refs: #156
```

### Code Review清单

审查者在批准PR前必须检查：

```markdown
## 功能正确性
- [ ] 功能符合需求
- [ ] 边界条件处理正确
- [ ] 错误处理完善

## 代码质量
- [ ] 代码清晰易读
- [ ] 命名规范
- [ ] 无重复代码
- [ ] 注释充分

## 测试
- [ ] 单元测试覆盖率>75%
- [ ] 测试用例充分
- [ ] 所有测试通过

## 文档
- [ ] API文档更新
- [ ] 架构文档更新
- [ ] README更新（如需要）

## 性能
- [ ] 无明显性能问题
- [ ] 无内存泄漏

## 安全
- [ ] 无安全漏洞
- [ ] 敏感信息已脱敏
```

---

## 📞 沟通机制

### 会议日历

| 会议 | 频率 | 时间 | 参与者 | 议程 |
|------|------|------|--------|------|
| 每日站会 | 每天 | 10:00-10:15 | 全体 | 进度同步、阻碍讨论 |
| Sprint计划 | 每2周 | 周一 9:00-11:00 | 全体 | 任务规划、估算 |
| Sprint评审 | 每2周 | 周五 15:00-16:00 | 全体 | 演示、反馈 |
| Sprint回顾 | 每2周 | 周五 16:00-17:00 | 全体 | 流程改进 |
| 技术评审 | 按需 | - | 架构师+相关人员 | 技术方案评审 |
| 周报会议 | 每周 | 周五 11:00-11:30 | PM+Tech Lead | 进度、风险 |

### 紧急事项升级

```
Level 1（轻微）→ 在Slack中讨论
↓ 30分钟未解决
Level 2（一般）→ 创建GitHub Issue，@相关人员
↓ 2小时未解决
Level 3（严重）→ 拉紧急会议，PM参与
↓ 1天未解决
Level 4（致命）→ 升级到CTO，调整计划
```

---

## 📦 交付清单

每个模块完成后必须交付：

### 代码交付物
- [ ] 源代码（已合并到main分支）
- [ ] 单元测试（覆盖率>75%）
- [ ] 集成测试（关键路径）
- [ ] E2E测试（核心场景）

### 文档交付物
- [ ] 架构设计文档
- [ ] API文档（如有）
- [ ] 开发者文档
- [ ] 用户手册（如需要）
- [ ] 发布说明

### 其他交付物
- [ ] 数据库迁移脚本（如有）
- [ ] 配置文件示例
- [ ] Docker镜像（如有）
- [ ] 部署脚本

---

## 🎓 参考资源

### 技术文档
- [LangGraph官方文档](https://langchain-ai.github.io/langgraph/)
- [Electron官方文档](https://www.electronjs.org/docs)
- [React官方文档](https://react.dev/)
- [TypeScript官方文档](https://www.typescriptlang.org/docs/)

### 竞品参考
- [Hermes Agent](https://github.com/NousResearch/hermes-agent)
- [Langflow](https://github.com/langflow-ai/langflow)
- [OpenHands](https://github.com/OpenHands/OpenHands)

### 内部文档
- [之前的审查报告](../2026-07-30-comprehensive-review-and-roadmap.md)
- [稳定化计划Phase 0+1](../2026-07-27-stabilization-phase0-1.md)

---

**下一步：** 请项目经理组织项目启动会，确认团队成员和第一个Sprint的目标。

**文档维护：** 本文档应每月更新一次，反映最新进展和调整。
