# Phase B 测试说明

直接复制粘贴到 PowerShell 运行，每步结果应完全一致。

## 前置条件

```powershell
cd "d:\ppt or work\opus\rxycode\RxyCode"
$venv = ".\venv\Scripts\python.exe"

# 将 uv 和 Git Bash 加入 PATH（减少 skip 数量）
$env:PATH = "d:\ppt or work\opus\rxycode\RxyCode\venv\Scripts;A:\gitee\Git\usr\bin;$env:PATH"
```

## 第一步：确认环境

```powershell
& $venv --version
& $venv -m pytest --version
& $venv -m ruff --version
```

期望：Python 3.14.x、pytest 9.x、ruff 0.x

## 第二步：代码静态检查

```powershell
& $venv -m ruff check core/subagents/ protocol/subagents.py tools/subagent_task_tool.py tools/agent_invoke.py tools/task_manage.py appserver/subagent_routes.py
```

**期望输出**：`All checks passed!`

## 第三步：Phase B 全部 14 张卡的测试

```powershell
& $venv -m pytest tests/test_subagents -q --timeout=120
```

**期望输出**：`422 passed`

## 第四步：全量回归（排除 Phase B 新增测试，确保旧代码未受影响）

```powershell
& $venv -m pytest tests -q --timeout=120 --ignore=tests/test_subagents
```

**期望输出**：约 `~9950 passed, 4 skipped`

**4 个 skip 说明**：
| 测试 | 原因 | 是否可修 |
|------|------|----------|
| 3 个 `test_installed_package` | `uv` 路径含空格，Bash 子进程找不到 | 可用 winget 装 uv 到系统 PATH 解决 |
| 1 个 symlink | 需要管理员权限运行终端 | 以管理员身份启动 PowerShell |
| 1 个 cache dedup | 同一个 query pair 故意跳过 | 设计如此，不是 bug |
| 1 个 live research | 测试内部 webfetch 调用第三方 API 失败 | 非 Phase B 问题，基线本身就 skip |

## 第五步：协议 schema 校验

```powershell
& $venv -m pytest tests/test_subagents/test_schema.py -q --timeout=30
```

**期望输出**：`7 passed`

## 第六步：E2E 场景（10 个完整场景 + 隔离要求）

```powershell
& $venv -m pytest tests/test_subagents/test_e2e.py -q --timeout=60
```

**期望输出**：`30 passed`

## 第七步：Live Eval 基线比对（需要 API key）

```powershell
& $venv -m evals.run run --backend agent --compare-baseline evals\baselines\latest-agent.json
```

**期望**：17/17 passed，GATE: PASS，通过率 ≥ 基线 88.2%

---

## 一键全跑

```powershell
cd "d:\ppt or work\opus\rxycode\RxyCode"
$venv = ".\venv\Scripts\python.exe"

Write-Output "=== 1/6 Ruff ==="
& $venv -m ruff check core/subagents/ protocol/subagents.py tools/subagent_task_tool.py tools/agent_invoke.py tools/task_manage.py appserver/subagent_routes.py

Write-Output "=== 2/6 Subagent tests (422) ==="
& $venv -m pytest tests/test_subagents -q --timeout=120

Write-Output "=== 3/6 Schema tests ==="
& $venv -m pytest tests/test_subagents/test_schema.py -q --timeout=30

Write-Output "=== 4/6 E2E tests ==="
& $venv -m pytest tests/test_subagents/test_e2e.py -q --timeout=60

Write-Output "=== 5/6 Full regression ==="
& $venv -m pytest tests -q --timeout=120 --ignore=tests/test_subagents

Write-Output "=== 6/6 Live eval ==="
& $venv -m evals.run run --backend agent --compare-baseline evals\baselines\latest-agent.json

Write-Output "=== DONE ==="
```
