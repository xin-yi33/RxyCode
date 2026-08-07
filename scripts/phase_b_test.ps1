# Phase B 全量测试启动脚本
# 用法：以管理员身份运行 PowerShell，然后执行此脚本
#
#   powershell -ExecutionPolicy Bypass -File scripts\phase_b_test.ps1

$ErrorActionPreference = "Continue"
Set-Location "d:\ppt or work\opus\rxycode\RxyCode"

# ── 1. 环境 PATH ──────────────────────────────────────────
$env:PATH = "d:\ppt or work\opus\rxycode\RxyCode\venv\Scripts;A:\gitee\Git\usr\bin;$env:PATH"

# ── 2. Live test 环境变量 ──────────────────────────────────
$env:RXYCODE_RUN_LIVE_TESTS = "1"
$env:RXYCODE_APPSERVER_LIVE = "1"
$key = & "d:\ppt or work\opus\rxycode\RxyCode\venv\Scripts\python.exe" -c "from RxyCode.RxyCode1_1_0.config.credential_store import load_credential; from RxyCode.RxyCode1_1_0.config.settings import get_config_path; print(load_credential('2e9ffcce176d47f29329c77461ed87c8', get_config_path()))"
$env:RXYCODE_LIVE_API_KEY = $key.Trim()

# ── 3. 检查管理员权限（影响 symlink 测试） ─────────────────
$isAdmin = ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole] "Administrator")
Write-Output "============================================"
Write-Output "  Phase B Full Test Suite"
Write-Output "  Admin: $isAdmin"
Write-Output "  uv: $(if (Get-Command uv -ErrorAction SilentlyContinue) { (uv --version) } else { 'NOT FOUND' })"
Write-Output "  sh: $(if (Get-Command sh -ErrorAction SilentlyContinue) { 'found' } else { 'NOT FOUND' })"
Write-Output "============================================"

# ── 4. Ruff ────────────────────────────────────────────────
Write-Output "`n[1/4] Ruff check"
& "d:\ppt or work\opus\rxycode\RxyCode\venv\Scripts\python.exe" -m ruff check core/subagents/ protocol/subagents.py tools/subagent_task_tool.py tools/agent_invoke.py tools/task_manage.py appserver/subagent_routes.py
if ($LASTEXITCODE -ne 0) { Write-Output "RUFF FAILED"; exit 1 }

# ── 5. Phase B 全套 ───────────────────────────────────────
Write-Output "`n[2/4] Phase B subagent tests"
& "d:\ppt or work\opus\rxycode\RxyCode\venv\Scripts\python.exe" -m pytest tests/test_subagents -q --timeout=120
if ($LASTEXITCODE -ne 0) { Write-Output "SUBTESTS FAILED"; exit 1 }

# ── 6. 全量回归 ────────────────────────────────────────────
Write-Output "`n[3/4] Full regression"
& "d:\ppt or work\opus\rxycode\RxyCode\venv\Scripts\python.exe" -m pytest tests -q --timeout=120 --ignore=tests/test_subagents

# ── 7. Live eval（需要 API key） ───────────────────────────
Write-Output "`n[4/4] Live eval baseline comparison"
& "d:\ppt or work\opus\rxycode\RxyCode\venv\Scripts\python.exe" -m evals.run run --backend agent --compare-baseline evals\baselines\latest-agent.json

Write-Output "`n============================================"
Write-Output "  ALL DONE"
Write-Output "============================================"
