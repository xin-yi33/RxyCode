# AI模型执行指南

## 目标
本指南帮助AI模型（特别是Sonnet 3.5等能力较弱的模型）正确执行复杂的开发任务，无需大量上下文理解。

## 核心原则

### 1. 一次执行一个任务
- 不要跳步骤
- 不要合并多个任务
- 完成一个任务后才进入下一个

### 2. 每步都要验证
- 执行命令后检查输出
- 运行验证命令确认结果
- 不满足预期就停止并报告

### 3. 严格遵循指令
- 使用提供的精确命令
- 不要自行修改命令
- 不要跳过验证步骤

### 4. 失败时立即停止
- 记录错误信息
- 检查失败处理流程
- 执行回滚操作（如果有）
- 报告给用户

## 如何阅读执行计划文档

### 文档结构
每个任务文档包含：
```
任务标题
├── 前置条件（必须满足才能开始）
├── 子任务列表
│   ├── 子任务1
│   │   ├── 输入要求
│   │   ├── 输出目标
│   │   ├── 详细步骤
│   │   │   ├── 步骤1
│   │   │   │   ├── 执行命令
│   │   │   │   ├── 预期输出
│   │   │   │   ├── 验证方法
│   │   │   │   └── 失败处理
│   │   │   └── 步骤2...
│   │   ├── 完成标准
│   │   └── 下一步
│   └── 子任务2...
└── 最终验证
```

### 执行流程
1. **阅读前置条件** - 确保所有条件都满足
2. **找到第一个子任务** - 从子任务1.1开始
3. **检查输入要求** - 确保你有所需的所有信息
4. **按顺序执行每个步骤** - 不要跳过
5. **验证每个步骤** - 使用提供的验证命令
6. **检查完成标准** - 确保所有checkbox都满足
7. **移到下一步** - 按照"下一步"指引继续

## 通用命令模板

### Python相关

#### 检查Python环境
```bash
python --version
```
**预期输出示例:**
```
Python 3.8.10
```

#### 创建虚拟环境
```bash
python -m venv venv
```
**验证:**
```bash
Test-Path -LiteralPath "venv\Scripts\activate.ps1"
```
**预期输出:** `True`

#### 激活虚拟环境（Windows）
```bash
.\venv\Scripts\activate
```
**验证:**
```bash
$env:VIRTUAL_ENV
```
**预期输出:** 应该显示虚拟环境路径

#### 安装依赖
```bash
pip install -r requirements.txt
```
**验证:**
```bash
pip list
```
**预期输出:** 应该列出所有已安装的包

#### 运行Python脚本
```bash
python script.py
```

#### 运行测试
```bash
pytest tests/
```
**预期输出示例:**
```
===== test session starts =====
collected 5 items

tests/test_module.py .....     [100%]

===== 5 passed in 0.50s =====
```

#### 检查代码覆盖率
```bash
pytest --cov=src --cov-report=term-missing tests/
```

### Node.js/npm相关

#### 检查Node环境
```bash
node --version; if ($?) { npm --version }
```
**预期输出示例:**
```
v16.14.0
8.3.1
```

#### 初始化npm项目
```bash
npm init -y
```
**验证:**
```bash
Test-Path -LiteralPath "package.json"
```
**预期输出:** `True`

#### 安装依赖
```bash
npm install
```
**验证:**
```bash
Test-Path -LiteralPath "node_modules"
```
**预期输出:** `True`

#### 安装特定包
```bash
npm install <package-name> --save
```
**验证:**
```bash
npm list <package-name>
```

#### 运行脚本
```bash
npm run <script-name>
```

#### 运行测试
```bash
npm test
```

### Git相关

#### 检查Git状态
```bash
git status
```
**预期输出示例:**
```
On branch main
nothing to commit, working tree clean
```

#### 创建新分支
```bash
git checkout -b <branch-name>
```
**验证:**
```bash
git branch
```
**预期输出:** 应该显示当前在新分支上（带*标记）

#### 查看修改
```bash
git diff
```

#### 暂存文件
```bash
git add <file-path>
```
**验证:**
```bash
git status
```
**预期输出:** 文件应该在"Changes to be committed"下

#### 提交
```bash
git commit -m "commit message"
```
**验证:**
```bash
git log -1 --oneline
```

#### 推送
```bash
git push origin <branch-name>
```

### 文件操作

#### 检查文件是否存在
```bash
Test-Path -LiteralPath "<file-path>"
```
**预期输出:** `True` 或 `False`

#### 检查目录是否存在
```bash
Test-Path -LiteralPath "<directory-path>"
```
**预期输出:** `True` 或 `False`

#### 创建目录
```bash
New-Item -ItemType Directory -Path "<directory-path>"
```
**验证:**
```bash
Test-Path -LiteralPath "<directory-path>"
```
**预期输出:** `True`

#### 列出目录内容
```bash
Get-ChildItem -Path "<directory-path>"
```

#### 删除文件
```bash
Remove-Item -LiteralPath "<file-path>"
```
**验证:**
```bash
Test-Path -LiteralPath "<file-path>"
```
**预期输出:** `False`

## 验证方法

### 级别1：命令执行验证
检查命令是否成功执行（退出码为0）

```bash
command; if ($?) { Write-Output "Success" } else { Write-Output "Failed" }
```

### 级别2：输出验证
检查命令输出是否符合预期

```bash
$output = command
if ($output -match "expected pattern") { 
    Write-Output "Verified" 
} else { 
    Write-Output "Output mismatch" 
}
```

### 级别3：文件/状态验证
检查文件是否创建、内容是否正确

```bash
# 检查文件存在
Test-Path -LiteralPath "file.py"

# 检查文件内容
Select-String -Path "file.py" -Pattern "class ClassName"
```

### 级别4：功能验证
运行测试确保功能正常

```bash
pytest tests/test_specific.py -v
```

### 级别5：集成验证
检查整个系统是否正常工作

```bash
# 运行所有测试
pytest tests/ -v

# 检查覆盖率
pytest --cov=src tests/
```

## 错误处理流程

### 步骤1：识别错误类型

#### 命令未找到错误
**错误示例:**
```
command not found: python
```
**处理:**
1. 检查是否安装了该工具
2. 检查PATH环境变量
3. 使用完整路径执行

#### 权限错误
**错误示例:**
```
Permission denied
```
**处理:**
1. 检查文件/目录权限
2. 使用管理员权限（如果需要）
3. 检查文件是否被其他进程占用

#### 依赖缺失错误
**错误示例:**
```
ModuleNotFoundError: No module named 'xxx'
```
**处理:**
1. 检查是否在虚拟环境中
2. 运行 `pip install xxx`
3. 检查requirements.txt

#### 语法错误
**错误示例:**
```
SyntaxError: invalid syntax
```
**处理:**
1. 检查代码语法
2. 查看错误行号
3. 使用提供的代码模板

#### 测试失败
**错误示例:**
```
FAILED tests/test_xxx.py::test_function
```
**处理:**
1. 阅读失败信息
2. 检查代码逻辑
3. 运行单个测试调试
4. 查看测试日志

### 步骤2：执行回滚（如果提供）

每个步骤的"失败处理"部分会提供回滚命令，例如：

```bash
# 回滚Git提交
git reset --soft HEAD~1

# 删除创建的文件
Remove-Item -LiteralPath "file.py"

# 卸载包
pip uninstall package-name -y
```

### 步骤3：报告错误

报告格式：
```
❌ 任务失败: [任务名称]
步骤: [步骤编号和描述]
命令: [执行的命令]
错误信息: [完整的错误输出]
已执行回滚: [是/否]
建议: [如果有的话]
```

## 状态检查清单

### 开始任务前
- [ ] 已阅读完整的任务文档
- [ ] 已理解所有前置条件
- [ ] 已验证所有前置条件都满足
- [ ] 已确认有所需的所有工具
- [ ] 已确认在正确的目录中

### 执行每个步骤时
- [ ] 已阅读步骤的完整描述
- [ ] 已理解步骤的目标
- [ ] 已复制精确的命令（未修改）
- [ ] 已执行命令
- [ ] 已检查命令输出
- [ ] 已运行验证命令
- [ ] 验证结果符合预期

### 完成子任务后
- [ ] 已完成所有步骤
- [ ] 已运行所有验证
- [ ] 已检查完成标准中的所有项目
- [ ] 所有完成标准都满足
- [ ] 已记录任何异常或偏差

### 完成整个任务后
- [ ] 已完成所有子任务
- [ ] 已运行最终验证
- [ ] 所有测试通过
- [ ] 代码已提交（如果需要）
- [ ] 已创建文档（如果需要）
- [ ] 已通知用户完成

## 最佳实践

### DO（应该做的）
1. ✅ 仔细阅读每个步骤
2. ✅ 使用提供的精确命令
3. ✅ 验证每个步骤的结果
4. ✅ 出错时立即停止
5. ✅ 保持工作目录整洁
6. ✅ 定期检查Git状态
7. ✅ 运行测试确保质量
8. ✅ 记录遇到的问题

### DON'T（不应该做的）
1. ❌ 跳过步骤
2. ❌ 修改提供的命令
3. ❌ 忽略错误继续执行
4. ❌ 假设某个步骤成功了
5. ❌ 在错误的目录执行命令
6. ❌ 不运行验证就继续
7. ❌ 提交未测试的代码
8. ❌ 修改不相关的文件

## 快速参考

### 遇到错误时
1. 停止执行
2. 复制完整错误信息
3. 检查错误处理流程
4. 执行回滚（如果有）
5. 报告用户

### 不确定时
1. 重新阅读步骤
2. 检查前置条件
3. 验证当前状态
4. 询问用户

### 完成任务时
1. 运行最终验证
2. 检查所有完成标准
3. 清理临时文件
4. 报告完成状态

## 示例：完整的任务执行流程

```
1. 阅读任务文档: TASK-01-AGENT-V2-REFACTORING.md
   ✓ 理解任务目标
   ✓ 查看前置条件

2. 检查前置条件
   执行: Test-Path -LiteralPath "src/agent_v2.py"
   输出: True
   ✓ 文件存在

3. 开始子任务1.1
   目标: 分析agent_v2.py
   
   步骤1: 读取文件
   执行: Get-Content -Path "src/agent_v2.py"
   验证: 文件内容显示
   ✓ 完成

   步骤2: 识别类和方法
   执行: Select-String -Path "src/agent_v2.py" -Pattern "class |def "
   验证: 找到类和方法定义
   ✓ 完成

4. 检查完成标准
   ✓ 文件已读取
   ✓ 类和方法已识别
   ✓ 已记录分析结果

5. 移到下一个子任务
   参考: 子任务1.2

6. 重复流程直到所有任务完成

7. 运行最终验证
   执行: pytest tests/ -v
   ✓ 所有测试通过

8. 报告完成
```

## 获取帮助

如果遇到问题：
1. 查看本指南的错误处理部分
2. 查看VERIFICATION-CHECKLIST.md
3. 查看CODE-TEMPLATES.md获取代码示例
4. 向用户报告具体问题

---

**记住：慢即是快。仔细执行每个步骤比快速出错更好。**
