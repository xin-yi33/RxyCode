# 任务 T001: 分析 agent_v2.py 方法统计

**难度：** 简单
**预计时间：** 30分钟
**前置任务：** 无

---

## 任务目标

分析 `core/agent_v2.py` 文件，统计所有类和方法，生成 JSON 格式的分析报告。

**输出文件：** `docs/analysis/agent_v2_methods.json`

---

## 前置条件检查

在开始前，请确认：

```powershell
# 1. 检查工作目录
cd D:\agent-demo\RxyCode\RxyCode1_1_0
Get-Location
# 预期输出：D:\agent-demo\RxyCode\RxyCode1_1_0

# 2. 检查 agent_v2.py 文件存在
Test-Path "core\agent_v2.py"
# 预期输出：True

# 3. 检查 Python 可用
python --version
# 预期输出：Python 3.10.x 或更高版本

# 4. 检查文件大小（应该是大文件）
(Get-Item "core\agent_v2.py").Length
# 预期输出：> 100000 字节（大于100KB）
```

**如果任何检查失败，停止并报告问题。**

---

## 步骤1: 创建分析目录

### 1.1 执行命令

```powershell
# 创建 docs/analysis 目录
New-Item -ItemType Directory -Path "docs\analysis" -Force
```

### 1.2 预期输出

```
    目录: D:\agent-demo\RxyCode\RxyCode1_1_0\docs

Mode                 LastWriteTime         Length Name
----                 -------------         ------ ----
d-----        2026/7/30     20:00                analysis
```

### 1.3 验证

```powershell
Test-Path "docs\analysis"
```

**预期：** `True`

### 1.4 如果失败

如果目录创建失败：
- 检查是否有写入权限
- 检查磁盘空间
- 尝试手动创建目录

---

## 步骤2: 运行分析脚本

### 2.1 执行命令

**复制以下完整代码块并执行：**

```powershell
python -c @"
import ast
import json
import os

# 读取 agent_v2.py 文件
with open('core/agent_v2.py', 'r', encoding='utf-8') as f:
    code = f.read()

print('[1/4] 文件读取成功')
print(f'      文件大小: {len(code)} 字符')

# 解析 Python AST
try:
    tree = ast.parse(code)
    print('[2/4] AST 解析成功')
except SyntaxError as e:
    print(f'[ERROR] AST 解析失败: {e}')
    exit(1)

# 查找所有类
classes = [node for node in ast.walk(tree) if isinstance(node, ast.ClassDef)]
print(f'[3/4] 找到 {len(classes)} 个类')

# 查找所有方法
methods = []
for cls in classes:
    for item in cls.body:
        if isinstance(item, ast.FunctionDef):
            methods.append({
                'class': cls.name,
                'method': item.name,
                'line': item.lineno,
                'args': len(item.args.args)
            })

print(f'[4/4] 找到 {len(methods)} 个方法')

# 确保目录存在
os.makedirs('docs/analysis', exist_ok=True)

# 保存结果
output_file = 'docs/analysis/agent_v2_methods.json'
with open(output_file, 'w', encoding='utf-8') as f:
    json.dump(methods, f, indent=2, ensure_ascii=False)

print(f'\n✅ 成功！分析结果已保存到: {output_file}')
print(f'   - 类的数量: {len(classes)}')
print(f'   - 方法总数: {len(methods)}')
"@
```

### 2.2 预期输出

```
[1/4] 文件读取成功
      文件大小: 125000 字符
[2/4] AST 解析成功
[3/4] 找到 1 个类
[4/4] 找到 44 个方法

✅ 成功！分析结果已保存到: docs/analysis/agent_v2_methods.json
   - 类的数量: 1
   - 方法总数: 44
```

**关键指标：**
- 类的数量应该是 1
- 方法总数应该在 40-50 之间（预期是44）

### 2.3 如果输出不符合预期

**情况A：方法数量不是44**
- 这可能正常，代码可能已经修改过
- 只要方法数量 > 30，就可以继续
- 记录实际数量

**情况B：类的数量不是1**
- 文件可能有多个类
- 检查是否读取了正确的文件
- 继续执行，但记录这个差异

**情况C：脚本报错**
- 检查错误信息
- 确认 Python 版本 ≥ 3.8
- 确认文件路径正确

---

## 步骤3: 验证输出文件

### 3.1 检查文件存在

```powershell
Test-Path "docs\analysis\agent_v2_methods.json"
```

**预期：** `True`

### 3.2 检查文件内容

```powershell
# 显示文件前20行
Get-Content "docs\analysis\agent_v2_methods.json" -Head 20
```

**预期输出示例：**
```json
[
  {
    "class": "AgentV2",
    "method": "__init__",
    "line": 45,
    "args": 5
  },
  {
    "class": "AgentV2",
    "method": "_plan_goal",
    "line": 245,
    "args": 3
  },
  ...
]
```

### 3.3 统计方法数量

```powershell
# 使用 PowerShell 解析 JSON 并统计
$data = Get-Content "docs\analysis\agent_v2_methods.json" | ConvertFrom-Json
$data.Count
```

**预期：** 显示一个数字（应该是44左右）

### 3.4 查看方法名称列表

```powershell
# 显示所有方法名称
$data = Get-Content "docs\analysis\agent_v2_methods.json" | ConvertFrom-Json
$data | ForEach-Object { $_.method } | Sort-Object
```

**预期：** 显示按字母排序的方法名列表

---

## 步骤4: 提交到 Git（可选）

如果一切正常，可以提交这个分析文件：

```bash
# 查看 Git 状态
git status

# 添加新文件
git add docs/analysis/agent_v2_methods.json

# 提交
git commit -m "docs: add agent_v2 method analysis

- Analyze core/agent_v2.py structure
- Generate JSON report with 44 methods
- Preparation for AgentV2 refactoring

Task: T001"

# 查看提交
git log --oneline -1
```

**注意：** 提交是可选的，如果你想先完成更多任务再一起提交也可以。

---

## 完成标准

在标记任务完成前，确认以下所有条件：

- [ ] 文件 `docs/analysis/agent_v2_methods.json` 存在
- [ ] 文件是有效的 JSON 格式
- [ ] 文件包含方法列表（数量 > 30）
- [ ] 每个方法都有 class、method、line、args 字段
- [ ] 没有 Python 错误或警告

**全部通过？恭喜！任务 T001 完成 ✅**

---

## 下一步

完成此任务后，进入下一个任务：

**→ 任务 T002: 方法职责分类**

文档位置：`TASK-T002-classify-methods.md`（待创建）

或者查看任务索引：`TASK-INDEX.md`

---

## 故障排除

### 问题1: Python 找不到命令

**症状：** `python: command not found` 或类似错误

**解决：**
```powershell
# 尝试使用 python3
python3 --version

# 或者使用完整路径
C:\Python310\python.exe --version

# 或者激活虚拟环境
.\venv\Scripts\activate
```

### 问题2: 文件编码错误

**症状：** `UnicodeDecodeError`

**解决：**
- agent_v2.py 可能包含特殊字符
- 脚本已经使用了 `encoding='utf-8'`
- 如果仍然失败，尝试 `encoding='utf-8-sig'`

### 问题3: 权限错误

**症状：** `Permission denied` 创建文件失败

**解决：**
```powershell
# 检查当前用户权限
whoami

# 以管理员身份运行 PowerShell
# 或者更改目标目录权限
```

### 问题4: JSON 文件为空或格式错误

**症状：** 文件创建了但内容不对

**解决：**
```powershell
# 删除错误的文件
Remove-Item "docs\analysis\agent_v2_methods.json"

# 重新运行步骤2的脚本
```

---

## 任务记录

完成后填写：

```
执行人: [AI模型名称，如 Claude Sonnet 5]
执行日期: [YYYY-MM-DD]
实际用时: [分钟]
发现的方法数量: [实际数量]
遇到的问题: [如有]
解决方案: [如有]
```

---

**任务创建日期：** 2026-07-30
**文档版本：** 1.0
