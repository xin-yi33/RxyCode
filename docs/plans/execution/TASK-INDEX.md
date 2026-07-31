# RxyCode 任务索引

**给AI模型的说明：** 本文档列出了所有可执行的独立任务。每个任务都可以单独执行，有明确的输入输出和验证标准。

**执行方式：** 
1. 选择一个任务
2. 阅读该任务的详细说明（在对应文档中）
3. 遵循 AI-MODEL-GUIDE.md 的执行原则
4. 逐步执行并验证
5. 完成后在此文件标记 ✅

---

## Phase 1: 技术债务清理（40天）

### 1.1 AgentV2 分析和重构设计（3天）

#### 任务 T001: 分析 agent_v2.py 方法统计
- **文档：** `01-tech-debt-cleanup.md` - 任务1.1步骤1
- **输入：** core/agent_v2.py 存在
- **输出：** docs/analysis/agent_v2_methods.json
- **验证：** 文件包含44个方法的JSON数据
- **状态：** ⏳ 待执行

#### 任务 T002: 方法职责分类
- **文档：** `01-tech-debt-cleanup.md` - 任务1.1步骤2
- **输入：** docs/analysis/agent_v2_methods.json
- **输出：** docs/analysis/agent_v2_categories.json
- **验证：** 文件包含8个分类的方法
- **状态：** ⏳ 待执行

#### 任务 T003: 编写重构设计文档
- **文档：** `01-tech-debt-cleanup.md` - 任务1.1步骤3-4
- **输入：** docs/analysis/agent_v2_categories.json
- **输出：** docs/architecture/agent-v2-refactoring-detailed.md
- **验证：** 文档包含7个类的设计和20天的详细计划
- **状态：** ⏳ 待执行

---

### 1.2 创建 GoalPlanner 类（2天）

#### 任务 T004: 创建 GoalPlanner 目录结构
- **执行命令：**
  ```powershell
  cd D:\agent-demo\RxyCode\RxyCode1_1_0
  New-Item -ItemType Directory -Path "core\planner" -Force
  New-Item -ItemType Directory -Path "tests\unit\planner" -Force
  ```
- **验证：**
  ```powershell
  Test-Path "core\planner"           # True
  Test-Path "tests\unit\planner"     # True
  ```
- **状态：** ⏳ 待执行

#### 任务 T005: 创建 GoalPlanner 类骨架
- **文件：** core/planner/goal_planner.py
- **内容：** 包含 Goal dataclass 和 GoalPlanner 类
- **方法：** plan_goal, _extract_intent, _identify_constraints, _set_goal_context, _validate_goal
- **验证：**
  ```bash
  python -m py_compile core/planner/goal_planner.py
  ```
- **状态：** ⏳ 待执行

#### 任务 T006: 创建 GoalPlanner 单元测试
- **文件：** tests/unit/planner/test_goal_planner.py
- **测试数量：** 至少8个测试
- **验证：**
  ```bash
  python -m pytest tests/unit/planner/test_goal_planner.py -v
  ```
- **预期：** 8 passed
- **状态：** ⏳ 待执行

#### 任务 T007: GoalPlanner 测试覆盖率检查
- **验证：**
  ```bash
  python -m pytest tests/unit/planner/ --cov=core.planner --cov-report=term-missing
  ```
- **目标：** 覆盖率 ≥ 80%
- **状态：** ⏳ 待执行

#### 任务 T008: 提交 GoalPlanner 代码
- **Git操作：**
  ```bash
  git add core/planner/
  git add tests/unit/planner/
  git commit -m "feat(core): add GoalPlanner class"
  ```
- **验证：** `git log --oneline -1`
- **状态：** ⏳ 待执行

---

### 1.3 创建 TaskDecomposer 类（2天）

#### 任务 T009: 创建 TaskDecomposer 目录结构
- **执行命令：**
  ```powershell
  New-Item -ItemType Directory -Path "core\decomposer" -Force
  New-Item -ItemType Directory -Path "tests\unit\decomposer" -Force
  ```
- **状态：** ⏳ 待执行

#### 任务 T010: 创建 TaskDecomposer 类
- **文件：** core/decomposer/task_decomposer.py
- **依赖：** GoalPlanner
- **方法：** decompose_task, _split_into_subtasks, _create_dag, _estimate_complexity
- **状态：** ⏳ 待执行

#### 任务 T011: TaskDecomposer 测试和提交
- **测试文件：** tests/unit/decomposer/test_task_decomposer.py
- **验证：** 测试通过，覆盖率 ≥ 80%
- **Git提交：** feat(core): add TaskDecomposer class
- **状态：** ⏳ 待执行

---

### 1.4 创建 TaskExecutor 类（2天）

#### 任务 T012: 创建 TaskExecutor 类
- **文件：** core/executor/task_executor.py
- **依赖：** Tools, Safety
- **方法：** execute_task, _call_tool, _handle_result, _retry_on_failure
- **状态：** ⏳ 待执行

#### 任务 T013: TaskExecutor 测试和提交
- **测试：** tests/unit/executor/test_task_executor.py
- **状态：** ⏳ 待执行

---

### 1.5 创建 ResultValidator 类（2天）

#### 任务 T014: 创建 ResultValidator 类
- **文件：** core/validator/result_validator.py
- **状态：** ⏳ 待执行

#### 任务 T015: ResultValidator 测试和提交
- **状态：** ⏳ 待执行

---

### 1.6 创建 MemoryManager 类（2天）

#### 任务 T016: 创建 MemoryManager 类
- **文件：** core/memory/memory_manager.py
- **状态：** ⏳ 待执行

#### 任务 T017: MemoryManager 测试和提交
- **状态：** ⏳ 待执行

---

### 1.7 创建 CacheManager 类（2天）

#### 任务 T018: 创建 CacheManager 类
- **文件：** core/cache/cache_manager.py
- **状态：** ⏳ 待执行

#### 任务 T019: CacheManager 测试和提交
- **状态：** ⏳ 待执行

---

### 1.8 创建 SafetyManager 类（2天）

#### 任务 T020: 创建 SafetyManager 类
- **文件：** core/safety/safety_manager.py
- **状态：** ⏳ 待执行

#### 任务 T021: SafetyManager 测试和提交
- **状态：** ⏳ 待执行

---

### 1.9 创建新的 Agent 协调器（2天）

#### 任务 T022: 创建 Agent 协调器
- **文件：** core/agent.py（新版本）
- **职责：** 组合所有Manager，协调调用
- **状态：** ⏳ 待执行

#### 任务 T023: 集成测试
- **测试：** tests/integration/test_agent_refactored.py
- **状态：** ⏳ 待执行

---

### 1.10 循环依赖修复（15天）

#### 任务 T024: 依赖分析
- **工具：** pydeps
- **执行：**
  ```bash
  pip install pydeps
  pydeps core --max-bacon=2 -o deps.svg
  ```
- **输出：** deps.svg（依赖图）
- **状态：** ⏳ 待执行

#### 任务 T025: 解耦 validation ← execution
- **方案：** 创建 interfaces/validator.py
- **状态：** ⏳ 待执行

#### 任务 T026: 解耦 core ← planning
- **方案：** 创建 core/types.py
- **状态：** ⏳ 待执行

#### 任务 T027: 解耦 tools ← agent
- **方案：** 依赖注入
- **状态：** ⏳ 待执行

#### 任务 T028: 解耦 memory ← agent
- **方案：** 依赖注入
- **状态：** ⏳ 待执行

#### 任务 T029: 解耦 cache ← memory
- **方案：** 构造参数传递
- **状态：** ⏳ 待执行

#### 任务 T030: 验证无循环依赖
- **验证：**
  ```bash
  pydeps core --max-bacon=2
  ```
- **预期：** 无循环依赖警告
- **状态：** ⏳ 待执行

---

### 1.11 测试覆盖率提升（12天）

#### 任务 T031: 当前覆盖率分析
- **执行：**
  ```bash
  pytest --cov=core --cov=execution --cov=planning --cov-report=html
  ```
- **输出：** htmlcov/index.html
- **状态：** ⏳ 待执行

#### 任务 T032-T040: 补充单元测试
- **目标模块：** core, execution, planning, tools, memory, cache, validation, safety
- **目标覆盖率：** 每个模块 ≥ 75%
- **状态：** ⏳ 待执行（9个任务）

#### 任务 T041: 更新 CI 覆盖率门槛
- **文件：** .github/workflows/ci.yml
- **修改：** 将覆盖率要求从67%改为75%
- **状态：** ⏳ 待执行

---

### 1.12 统一命令系统（8天）

#### 任务 T042: 设计统一命令接口
- **文档：** docs/architecture/command-system.md
- **内容：** 命令注册机制、基类设计
- **状态：** ⏳ 待执行

#### 任务 T043: 创建命令系统基础
- **文件：** core/commands/registry.py, core/commands/base.py
- **状态：** ⏳ 待执行

#### 任务 T044: 迁移 main.py 命令
- **数量：** 32个命令
- **状态：** ⏳ 待执行

#### 任务 T045: 迁移 api_server.py 命令
- **数量：** 32个命令
- **状态：** ⏳ 待执行

#### 任务 T046: 删除重复代码
- **验证：** main.py 和 api_server.py 共享命令实现
- **状态：** ⏳ 待执行

---

## Phase 2: Desktop MVP 开发（30天）

### 2.1 Electron 项目初始化（2天）

#### 任务 T047: 创建 Desktop 目录
- **执行：**
  ```bash
  mkdir desktop
  cd desktop
  npm init -y
  ```
- **状态：** ⏳ 待执行

#### 任务 T048: 安装 Electron 依赖
- **执行：**
  ```bash
  npm install electron electron-builder --save-dev
  npm install react react-dom typescript --save
  ```
- **状态：** ⏳ 待执行

#### 任务 T049: 配置 package.json
- **内容：** scripts, build配置, electron-builder配置
- **状态：** ⏳ 待执行

#### 任务 T050: 创建基础 Electron 主进程
- **文件：** desktop/src/main/index.ts
- **功能：** 创建窗口、IPC通信
- **状态：** ⏳ 待执行

---

### 2.2 React 前端设置（3天）

#### 任务 T051: 配置 Vite
- **文件：** desktop/vite.config.ts
- **状态：** ⏳ 待执行

#### 任务 T052: 创建 React 入口
- **文件：** desktop/src/renderer/App.tsx
- **状态：** ⏳ 待执行

#### 任务 T053: 配置 TailwindCSS
- **文件：** desktop/tailwind.config.js
- **状态：** ⏳ 待执行

---

### 2.3 主窗口 UI（5天）

#### 任务 T054-T060: 创建 UI 组件
- Sidebar (T054)
- ChatView (T055)
- MessageList (T056)
- InputBox (T057)
- ToolCallCard (T058)
- SettingsModal (T059)
- FilePreview (T060)
- **状态：** ⏳ 待执行（7个任务）

---

### 2.4 WebSocket 通信（3天）

#### 任务 T061: 实现 WebSocket Hook
- **文件：** desktop/src/renderer/hooks/useWebSocket.ts
- **状态：** ⏳ 待执行

#### 任务 T062: 实现消息协议
- **类型定义：** desktop/src/shared/types.ts
- **状态：** ⏳ 待执行

#### 任务 T063: 连接后端测试
- **验证：** 成功连接到 api_server.py
- **状态：** ⏳ 待执行

---

### 2.5 流式消息渲染（3天）

#### 任务 T064-T066: 流式消息功能
- 实现消息流解析 (T064)
- 实现增量渲染 (T065)
- 实现代码高亮 (T066)
- **状态：** ⏳ 待执行

---

### 2.6 跨平台打包（3天）

#### 任务 T067: Windows 打包
- **执行：** `npm run build:win`
- **输出：** dist/RxyCode-Setup.exe
- **状态：** ⏳ 待执行

#### 任务 T068: macOS 打包
- **执行：** `npm run build:mac`
- **输出：** dist/RxyCode.dmg
- **状态：** ⏳ 待执行

#### 任务 T069: Linux 打包
- **执行：** `npm run build:linux`
- **输出：** dist/RxyCode.AppImage
- **状态：** ⏳ 待执行

---

## Phase 3: 差异化功能（30天）

### 3.1 Skills 自动创建（15天）

#### 任务 T070: 设计 Skills 自动创建系统
- **文档：** docs/architecture/skills-auto-creation.md
- **状态：** ⏳ 待执行

#### 任务 T071-T075: 实现核心功能
- 轨迹分析器 (T071)
- 模式提取引擎 (T072)
- Skill代码生成器 (T073)
- 自动测试系统 (T074)
- A/B测试框架 (T075)
- **状态：** ⏳ 待执行

---

### 3.2 Telegram 集成（10天）

#### 任务 T076-T080: Telegram Bot
- Bot初始化 (T076)
- 消息处理 (T077)
- 会话管理 (T078)
- 文件处理 (T079)
- 部署测试 (T080)
- **状态：** ⏳ 待执行

---

## 任务执行统计

**总任务数：** 80+ 个
**已完成：** 0
**进行中：** 0
**待执行：** 80+

---

## 给 AI 模型的执行指南

### 如何开始

1. **选择第一个任务：** 建议从 T001 开始
2. **阅读任务详情：** 查看对应文档
3. **检查输入条件：** 确保前置条件满足
4. **执行任务：** 遵循 AI-MODEL-GUIDE.md 原则
5. **验证结果：** 运行验证命令
6. **标记完成：** 在此文件将 ⏳ 改为 ✅
7. **进入下一任务：** 按顺序继续

### 执行命令模板

```bash
# 任务开始
echo "开始执行任务 T001"

# 工作目录
cd D:\agent-demo\RxyCode\RxyCode1_1_0

# 执行任务命令
[具体命令]

# 验证
[验证命令]

# 报告
echo "任务 T001 完成" 或 "任务 T001 失败：[原因]"
```

### 任务状态说明

- ⏳ **待执行** - 还未开始
- 🔄 **进行中** - 正在执行
- ✅ **已完成** - 验证通过
- ❌ **失败** - 需要修复
- ⏭️ **跳过** - 暂时跳过

---

**更新日期：** 2026-07-30
**版本：** 1.0
