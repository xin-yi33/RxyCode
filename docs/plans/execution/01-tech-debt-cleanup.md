> ## [DEPRECATED] 本文件已作废（2026-07-31）
>
> 请改读 [`2026-07-31-EXECUTION-PLAN.md`](./2026-07-31-EXECUTION-PLAN.md)。
> 作废原因见该文件 §2.3。以下仅作历史记录保留。

---

# 技术债务清理详细执行计划

## 项目信息
- 模块编号：01
- 工期：2026年8月1日 - 9月10日（40天）
- 负责人：后端架构师
- 优先级：P0

## 目标
清理RxyCode核心技术债务，为后续开发打下坚实基础

## 具体任务清单

### 任务1：AgentV2上帝类重构（20天）

**当前状态：**
- core/agent_v2.py: 3720行代码
- 44个方法
- 10个职责域混合

**目标状态：**
- 拆分为7个独立的类
- 每个类<500行
- 单一职责原则

**详细步骤：**

Day 1-3：重构设计
- [ ] 分析agent_v2.py的44个方法，按职责分类
- [ ] 设计新的类结构
- [ ] 画出类图和交互图
- [ ] 编写重构设计文档：docs/architecture/agent-v2-refactoring.md

Day 4-7：创建新类（第一批）
- [ ] 创建 core/planner/goal_planner.py
- [ ] 创建 core/decomposer/task_decomposer.py  
- [ ] 创建 core/executor/task_executor.py
- [ ] 为每个类编写单元测试

Day 8-11：创建新类（第二批）
- [ ] 创建 core/validator/result_validator.py
- [ ] 创建 core/memory/memory_manager.py
- [ ] 创建 core/cache/cache_manager.py
- [ ] 为每个类编写单元测试

Day 12-15：创建新类（第三批）  
- [ ] 创建 core/safety/safety_manager.py
- [ ] 重构 core/agent.py 作为协调器
- [ ] 更新所有import语句
- [ ] 运行完整测试套件

Day 16-18：迁移测试
- [ ] 迁移 tests/test_core/test_agent_v2.py 到新结构
- [ ] 确保测试覆盖率不降低
- [ ] 修复所有测试失败

Day 19-20：文档和收尾
- [ ] 更新架构文档
- [ ] 更新开发者文档
- [ ] Code Review
- [ ] 合并到main分支

**验收标准：**
- ✅ agent_v2.py删除或重命名为legacy
- ✅ 7个新类全部通过测试
- ✅ 测试覆盖率 ≥ 67%（不降低）
- ✅ 所有CI检查通过

**风险：**
- 迁移过程中引入bug
- 缓解：每次重构后立即运行测试，小步快跑

### 任务2：打破5处循环依赖（15天）

**当前状态：**
- validation/final_output.py:19 ← execution/executor.py:9
- core/state.py ← planning/decomposer.py  
- tools/orchestrator.py ← agent/agent.py
- memory/manager.py ← agent/agent.py
- cache/semantic.py ← memory/manager.py

导致400+处函数内延迟import

**目标状态：**
- 0处循环依赖
- 所有import都在文件顶部
- 清晰的依赖层次

**详细步骤：**

Day 1-2：依赖分析
- [ ] 使用 pydeps 或 import-analyzer 生成依赖图
- [ ] 识别循环路径
- [ ] 设计解耦方案
- [ ] 编写解耦设计文档：docs/architecture/dependency-refactoring.md

Day 3-5：解耦validation ← execution
- [ ] 方案：引入接口抽象层 interfaces/validator.py
- [ ] executor依赖接口而非具体实现
- [ ] validation实现接口
- [ ] 运行测试

Day 6-8：解耦core ← planning
- [ ] 方案：将共享类型移到 core/types.py
- [ ] 更新import语句
- [ ] 运行测试

Day 9-11：解耦tools ← agent, memory ← agent
- [ ] 方案：使用依赖注入
- [ ] agent在初始化时注入tools和memory
- [ ] 运行测试

Day 12-13：解耦cache ← memory  
- [ ] 方案：cache作为memory的构造参数
- [ ] 运行测试

Day 14-15：验证和收尾
- [ ] 使用静态分析工具验证无循环依赖
- [ ] 删除所有函数内延迟import
- [ ] 更新文档
- [ ] Code Review
- [ ] 合并到main

**验收标准：**
- ✅ pydeps报告0处循环依赖
- ✅ 无函数内import（除特殊情况需注释说明）
- ✅ 所有测试通过
- ✅ 构建时间减少20%

### 任务3：提升测试覆盖率（12天）

**当前状态：**
- 核心模块：67%
- 整体项目：60%

**目标状态：**  
- 核心模块：75%
- 整体项目：70%

**详细步骤：**

Day 1-2：覆盖率分析
- [ ] 运行 pytest --cov --cov-report=html
- [ ] 分析未覆盖的代码
- [ ] 优先级排序（关键路径优先）
- [ ] 编写测试补充计划

Day 3-6：补充单元测试
- [ ] 为core/agent*.py补充测试
- [ ] 为execution/executor.py补充测试
- [ ] 为tools/orchestrator.py补充测试
- [ ] 目标：核心模块达到75%

Day 7-9：补充集成测试
- [ ] 增加端到端场景测试
- [ ] 增加异常处理测试
- [ ] 增加边界条件测试

Day 10-11：补充契约测试
- [ ] 为API端点补充测试
- [ ] 为WebSocket补充测试

Day 12：验证和提交
- [ ] 验证覆盖率达标
- [ ] 更新CI配置（提高门槛到75%）
- [ ] 合并到main

**验收标准：**
- ✅ 核心模块覆盖率 ≥ 75%
- ✅ 整体覆盖率 ≥ 70%  
- ✅ CI配置更新
- ✅ 所有新测试通过

### 任务4：统一slash命令实现（8天）

**当前状态：**
- main.py:289 有32个命令
- api_server.py:1120 有32个命令（重复实现）
- 4个命令单边存在，已漂移

**目标状态：**
- 统一命令注册表
- 单一实现源
- CLI和API共享

**详细步骤：**

Day 1-2：命令系统设计
- [ ] 设计统一命令接口
- [ ] 设计命令注册机制
- [ ] 编写设计文档：docs/architecture/command-system.md

Day 3-5：实现统一命令系统
- [ ] 创建 core/commands/ 目录
- [ ] 创建 core/commands/registry.py
- [ ] 创建 core/commands/base.py（基类）
- [ ] 迁移10个常用命令作为示例

Day 6-7：迁移所有命令
- [ ] 迁移main.py中的命令
- [ ] 迁移api_server.py中的命令
- [ ] 删除重复代码
- [ ] 更新调用点

Day 8：测试和验证
- [ ] 测试CLI命令
- [ ] 测试API命令
- [ ] 确保行为一致
- [ ] 合并到main

**验收标准：**
- ✅ 所有命令在core/commands/下注册
- ✅ main.py和api_server.py共享同一实现
- ✅ 无重复代码
- ✅ 所有命令测试通过

## 资源需求

**人力：**
- 后端架构师：1人全职（40天）
- 后端工程师：1人兼职（20天，协助测试）
- QA工程师：0.5人（测试验证）

**工具：**
- pydeps（依赖分析）
- pytest-cov（覆盖率）
- mypy（类型检查）

## 风险和缓解

| 风险 | 概率 | 影响 | 缓解措施 |
|------|------|------|----------|
| 重构引入bug | 高 | 高 | 小步重构+即时测试 |
| 时间超期 | 中 | 中 | 每周评审，及时调整 |
| 测试不足 | 中 | 高 | Code Review强制检查测试 |

## 每周检查点

**Week 1（8月1-7日）：**
- AgentV2重构设计完成
- 新类结构第一批创建

**Week 2（8月8-14日）：**
- 新类结构第二、三批创建
- 循环依赖分析完成

**Week 3（8月15-21日）：**
- AgentV2重构基本完成
- 循环依赖解耦进行中

**Week 4（8月22-28日）：**
- 循环依赖全部解耦
- 测试覆盖率提升进行中

**Week 5（8月29-9月4日）：**
- 测试覆盖率达标
- 统一命令系统实现

**Week 6（9月5-10日）：**
- 所有任务收尾
- 文档完善
- 最终验收

## 交付物清单

- [ ] docs/architecture/agent-v2-refactoring.md
- [ ] docs/architecture/dependency-refactoring.md  
- [ ] docs/architecture/command-system.md
- [ ] core/planner/goal_planner.py + 测试
- [ ] core/decomposer/task_decomposer.py + 测试
- [ ] core/executor/task_executor.py + 测试
- [ ] core/validator/result_validator.py + 测试
- [ ] core/memory/memory_manager.py + 测试
- [ ] core/cache/cache_manager.py + 测试
- [ ] core/safety/safety_manager.py + 测试
- [ ] core/commands/（统一命令系统）
- [ ] interfaces/validator.py（接口抽象）
- [ ] 重构后的测试套件
- [ ] 更新的CI配置
