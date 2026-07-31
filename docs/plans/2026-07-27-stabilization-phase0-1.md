# RxyCode 稳定化 Phase 0+1 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不改动任何业务行为的前提下，完成仓库止血（版本控制、垃圾清理）与工程规范补齐（CORS 收窄、静态检查、多版本 CI），使代码库达到可安全重构的基线状态。

**Architecture:** 本计划只做三类操作 —— (1) 删除不该入库的文件；(2) 收紧配置边界；(3) 新增质量门禁。**不重构任何生产代码逻辑**。架构重构（AgentV2 拆分、循环依赖打破、slash 命令收敛）属于 Phase 2，不在本计划范围内。

**Tech Stack:** Python 3.10-3.13 / pytest 8.x / ruff / GitHub Actions / Git

---

## 状态基线（2026-07-27 02:55 实测）

本计划撰写期间，另一会话已并行修复了三个 P0 项。以下为**实测复核结果**，不是假设：

| 项 | 状态 | 证据 |
|---|---|---|
| 泄漏的 DeepSeek key | ✅ 已删除 | 全树搜 `sk-fd35` / `sk-[A-Za-z0-9_-]{20,}` 命中 0 |
| `api_server.py` GET 鉴权绕过 | ✅ 已修复 | `:232` 现为 `if request.method != "OPTIONS":` |
| 前端 GET 请求配套改造 | ✅ 已完成 | `frontend/src/hooks/useApi.ts:585,612,629,644,649,670,688` 均带 `authorizationHeaders()` |
| `scan_secrets.py` 跳过 artifacts | ✅ 已修复 | `SKIP_DIRECTORIES` 已移除 `artifacts`；`tests/unit/test_secret_scanner.py:17-29` 有回归测试锁定，3 passed |
| `git init` | ⚠️ 部分 | `.git` 存在，但 `rev-list --count HEAD` 为空 —— **零提交，未受保护** |

**因此本计划从 Task 1（首次提交）开始，不重复已完成的工作。**

⚠️ **执行前必读**：该项目当前有其他会话正在活跃编辑（02:44-02:53 期间 `api_server.py`、`memory/`、`frontend/` 均被修改）。执行 Task 1 前必须确认无并发写入，否则首次提交会捕获半成品状态。

---

## Global Constraints

- **不改动任何生产代码的业务逻辑。** 本计划所有代码改动限于：CORS 配置边界、新增配置文件、CI 配置。
- **Python 版本下限 3.10**（`pyproject.toml:10` `requires-python = ">=3.10"`），所有新增配置必须兼容 3.10-3.13。
- **不得降低现有覆盖率门槛**：core 67% / project 60%（`ci.yml:36-37`）。
- **不得修改 `.coveragerc` 的 `omit` 使其排除 `api_server.py` 或 `main.py`** —— `tests/unit/test_ci_contracts.py:45-50` 会失败。
- **不得在 `ci.yml` 中引入 `--cov-append`**，且 serial lane 必须保持 `-n 0` —— `tests/unit/test_ci_contracts.py:53-65` 会失败。
- 所有 shell 命令以 **Windows PowerShell 5.1** 为准（项目主开发环境为 win32）。
- 每个 Task 结束必须提交，提交信息使用 Conventional Commits 前缀（`chore:` / `fix:` / `ci:` / `build:`）。

---

## File Structure

| 文件 | 操作 | 职责 |
|---|---|---|
| `.gitignore` | 修改 | 补齐 `.refs/`、XML 报告、log 运行时文件的忽略规则 |
| `core/agent_v2.py.bak` | 删除 | 19KB 备份文件，git 建立后无存在意义 |
| `~/` | 删除 | tilde 未展开 bug 产生的伪目录 |
| 根目录 21 个 `*.xml` | 删除 | TDD 迭代残留的测试报告 |
| `artifacts/` | 删除 | 48MB 测试产物 |
| `scripts/debug_test.py` | 修改 | 修复触发 `~` 目录的 tilde 字面量 |
| `api_server.py` | 修改 | 仅删除 `allow_origin_regex` 一行 |
| `tests/contract/test_cors_policy.py` | 新建 | 锁定 CORS 收窄不被回退 |
| `pyproject.toml` | 修改 | 新增 `[tool.ruff]` 段 |
| `requirements-dev.txt` | 修改 | 新增 `ruff` |
| `.github/workflows/ci.yml` | 修改 | 新增 lint job；Python 版本矩阵化 |

---

## Task 1: 建立版本控制基线

**Files:**
- Modify: `.gitignore`
- Commit: 全仓

**Interfaces:**
- Produces: 一个干净的 git 基线提交，后续所有 Task 的回滚点。

**为什么第一**：当前 `.git` 存在但零提交，6.8 万行代码无任何保护。在此之前做任何删除操作都不可逆。

- [ ] **Step 1: 确认无并发写入**

```powershell
cd D:\agent-demo\RxyCode\RxyCode1_1_0
$cut = (Get-Date).AddMinutes(-10)
Get-ChildItem -Recurse -File -Force -ErrorAction SilentlyContinue |
  Where-Object { $_.LastWriteTime -gt $cut -and $_.FullName -notmatch '\\(__pycache__|\.pytest_cache|\.ruff_cache|node_modules|\.git)\\' } |
  Select-Object -ExpandProperty FullName
```

预期输出：空。若有输出，说明另一会话仍在编辑，**停止执行**，等待其完成。

- [ ] **Step 2: 补齐 .gitignore**

在 `.gitignore` 第 26 行 `test-results.xml` 替换为以下内容（保留原有其余行不动）：

```gitignore
# 测试报告（TDD 迭代残留会用各种后缀，需通配）
test-results.xml
test-results*.xml
.pytest-*.xml
```

在文件末尾追加：

```gitignore

# --- 第三方参考代码与调试脚本（33MB，不应入库） ---
.refs/

# --- log/ 是 Python 包，但混有运行时产物 ---
log/*.txt
log/*.err
log/*.out
log/status.json
```

- [ ] **Step 3: 验证忽略规则生效**

```powershell
git add -A --dry-run 2>&1 | Select-String -Pattern '\.refs/|\.pytest-.*\.xml|test-results-|artifacts/' | Measure-Object | Select-Object -ExpandProperty Count
```

预期输出：`0`。若非 0，说明规则未覆盖，检查上一步。

- [ ] **Step 4: 确认待提交规模合理**

```powershell
git add -A
git status --porcelain | Measure-Object | Select-Object -ExpandProperty Count
```

预期：数百量级（源码 + 前端源码 + 文档）。若出现数千，说明 `node_modules` 或 `.refs` 未被忽略，执行 `git reset` 后回到 Step 2。

- [ ] **Step 5: 首次提交**

```powershell
git commit -m "chore: initial commit of RxyCode 1.1.0 baseline"
git rev-list --count HEAD
```

预期输出：`1`

---

## Task 2: 清理仓库垃圾文件

**Files:**
- Delete: `core/agent_v2.py.bak`, `~/`, 根目录 21 个 `*.xml`, `artifacts/`

**Interfaces:**
- Consumes: Task 1 建立的 git 基线（保证可回滚）
- Produces: 干净的工作树，`git status` 无噪声

- [ ] **Step 1: 删除备份文件与伪目录**

```powershell
Remove-Item -LiteralPath "core\agent_v2.py.bak" -Force
Remove-Item -LiteralPath "~" -Recurse -Force
```

`~` 目录内仅含 `~\.rxycode\output\subway-runner.html`（35KB，测试生成的游戏页面，非源码）。

- [ ] **Step 2: 删除根目录测试报告**

```powershell
Remove-Item -LiteralPath . -Filter ".pytest-*.xml" -Force -ErrorAction SilentlyContinue
Get-ChildItem -File -Filter "test-results-*.xml" | Remove-Item -Force
Get-ChildItem -File -Filter "*.xml" | Select-Object -ExpandProperty Name
```

预期输出：空（根目录不应有任何 xml）。

- [ ] **Step 3: 删除 artifacts 与孤儿 pyc**

```powershell
Remove-Item -LiteralPath "artifacts" -Recurse -Force -ErrorAction SilentlyContinue
Get-ChildItem -Recurse -Directory -Filter "__pycache__" -Force | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
```

- [ ] **Step 4: 验证测试仍全绿**

删除的都是产物而非源码，测试必须不受影响：

```powershell
python -m pytest tests/unit tests/contract -m "not live and not pty" -q --timeout=180 2>&1 | Select-Object -Last 5
```

预期：`passed`，无 `error` / `failed`。

- [ ] **Step 5: 提交**

```powershell
git add -A
git commit -m "chore: remove build artifacts, backup file, and tilde-bug directory"
```

---

## Task 3: 修复 tilde 展开 bug

**Files:**
- Modify: `scripts/debug_test.py:322`

**Interfaces:**
- Consumes: Task 2 已删除 `~` 目录
- Produces: 该目录不会被重新创建

**背景**：`~` 目录由字面量字符串 `~/.rxycode/output/` 被直接传给文件系统 API 产生。PowerShell 不像 bash 会展开 `~/`。注意核心路径 helper（`core/session_runtime.py:110,133`、`core/safety/policy.py`）**都已正确调用 `.expanduser()`**，问题仅在这个调试脚本的 prompt 字面量。

- [ ] **Step 1: 定位字面量**

```powershell
Select-String -Path "scripts\debug_test.py" -Pattern '~/\.rxycode' -Context 2,2
```

- [ ] **Step 2: 写回归测试**

创建 `tests/unit/test_no_literal_tilde_paths.py`：

```python
"""Guard against literal '~/' paths reaching filesystem APIs.

A literal '~' directory was previously created at the repo root because a
prompt string containing '~/.rxycode/output/' was passed to a shell command
without expanduser(). PowerShell does not expand '~/' the way bash does.
"""

from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def test_no_literal_tilde_directory_at_repo_root():
    assert not (_repo_root() / "~").exists(), (
        "A literal '~' directory exists. Some code passed an unexpanded "
        "'~/...' string to a filesystem API. Call Path.expanduser() first."
    )


def test_debug_script_uses_expanded_output_dir():
    script = _repo_root() / "scripts" / "debug_test.py"
    text = script.read_text(encoding="utf-8")
    assert "~/.rxycode" not in text, (
        "scripts/debug_test.py still contains a literal '~/.rxycode' path. "
        "Use the resolved output directory instead."
    )
```

- [ ] **Step 3: 运行测试确认失败**

```powershell
python -m pytest tests/unit/test_no_literal_tilde_paths.py -v --timeout=60
```

预期：`test_debug_script_uses_expanded_output_dir` **FAILED**（因为字面量还在）；`test_no_literal_tilde_directory_at_repo_root` PASSED（Task 2 已删目录）。

- [ ] **Step 4: 修复字面量**

将 `scripts/debug_test.py:322` 中 prompt 里的 `~/.rxycode/output/` 改为不含 tilde 的表述。推荐改法是让 prompt 描述目标而不给出路径字面量：

```python
# 修改前（示意，以实际文件内容为准）
#   "... save it to ~/.rxycode/output/ ..."
# 修改后
#   "... save it to the configured output directory ..."
```

若该 prompt 必须给出真实路径，则在传入前展开：

```python
from pathlib import Path

output_dir = Path("~/.rxycode/output").expanduser()
# 然后在 prompt 中插入 str(output_dir)
```

- [ ] **Step 5: 运行测试确认通过**

```powershell
python -m pytest tests/unit/test_no_literal_tilde_paths.py -v --timeout=60
```

预期：2 passed

- [ ] **Step 6: 提交**

```powershell
git add scripts/debug_test.py tests/unit/test_no_literal_tilde_paths.py
git commit -m "fix: expand tilde before passing output path to shell prompt"
```

---

## Task 4: 收窄 CORS 策略

**Files:**
- Modify: `api_server.py:188`
- Test: `tests/contract/test_cors_policy.py`

**Interfaces:**
- Consumes: 当前已修复的 bearer 中间件（`api_server.py:232` `!= "OPTIONS"`）
- Produces: CORS 仅允许 `_allowed_origins` 白名单中的 6 个来源

**背景**：`api_server.py:187-188` 同时配置了 `allow_origins`（6 个精确来源）和 `allow_origin_regex`（任意 localhost 端口）。后者使白名单形同虚设。

配合 `allow_credentials=True`，任意本地端口的网页都能发起携带凭据的跨域请求。虽然 bearer 鉴权现已覆盖 GET，风险大幅下降，但宽 regex 仍是不必要的攻击面 —— 白名单已枚举了全部真实使用的端口。

- [ ] **Step 1: 写契约测试**

创建 `tests/contract/test_cors_policy.py`：

```python
"""CORS must be restricted to the enumerated frontend origins.

A previous configuration paired an explicit six-entry allowlist with
allow_origin_regex matching any localhost port, which made the allowlist
meaningless. Combined with allow_credentials=True, any page served from any
local port could issue credentialed cross-origin requests.
"""

import pytest

pytestmark = pytest.mark.contract


def test_allowlist_contains_known_frontend_origins():
    from RxyCode.RxyCode1_1_0 import api_server

    assert "http://localhost:8765" in api_server._allowed_origins
    assert "http://127.0.0.1:5173" in api_server._allowed_origins


def test_cors_middleware_has_no_wildcard_origin_regex():
    from RxyCode.RxyCode1_1_0 import api_server

    cors = [
        m for m in api_server.app.user_middleware
        if "CORSMiddleware" in repr(m)
    ]
    assert cors, "CORSMiddleware is not installed"

    options = cors[0].kwargs
    assert options.get("allow_origin_regex") is None, (
        "allow_origin_regex permits any localhost port and defeats the "
        "explicit allowlist; remove it."
    )
    assert options.get("allow_origins"), "allow_origins must stay populated"


def test_credentials_require_explicit_origins():
    from RxyCode.RxyCode1_1_0 import api_server

    cors = [
        m for m in api_server.app.user_middleware
        if "CORSMiddleware" in repr(m)
    ]
    options = cors[0].kwargs

    if options.get("allow_credentials"):
        assert "*" not in options.get("allow_origins", []), (
            "allow_credentials=True must never pair with a wildcard origin"
        )
```

- [ ] **Step 2: 运行测试确认失败**

```powershell
python -m pytest tests/contract/test_cors_policy.py -v --timeout=60
```

预期：`test_cors_middleware_has_no_wildcard_origin_regex` **FAILED**，报 `allow_origin_regex permits any localhost port`。

- [ ] **Step 3: 删除宽 regex**

编辑 `api_server.py`，删除第 188 行。修改后 `:185-192` 应为：

```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

- [ ] **Step 4: 运行测试确认通过**

```powershell
python -m pytest tests/contract/test_cors_policy.py -v --timeout=60
```

预期：3 passed

- [ ] **Step 5: 确认未破坏既有契约测试**

CORS 与 SSE、鉴权强相关，必须跑完整 contract 层：

```powershell
python -m pytest tests/contract -m "not live and not pty" -q --timeout=180 2>&1 | Select-Object -Last 5
```

预期：全部 passed。

若 `test_api_security_onboarding.py` 失败，说明有测试依赖非白名单来源 —— 检查该测试用的 Origin，若是真实使用的端口则加进 `_allowed_origins`，不要恢复 regex。

- [ ] **Step 6: 提交**

```powershell
git add api_server.py tests/contract/test_cors_policy.py
git commit -m "fix: restrict CORS to the enumerated frontend origins"
```

---

## Task 5: 接入 ruff 静态检查

**Files:**
- Modify: `pyproject.toml`, `requirements-dev.txt`
- Modify: `.github/workflows/ci.yml`

**Interfaces:**
- Produces: CI 中新增 `lint` job，阻止新增的 lint 问题

**背景**：项目根有 `.ruff_cache/` 但无任何 ruff 配置，也无 CI 集成 —— 说明有人本地跑过但从未固化。当前后端零静态检查、零类型检查。

**策略**：首次接入必须**先用宽松规则集**。直接开全量规则会产生数千条告警，导致 lint job 长期红灯而被忽略，反而不如不加。本 Task 只启用最高信噪比的规则（`E9` 语法错误、`F` 真实 bug、`I` import 排序）。

- [ ] **Step 1: 添加 ruff 依赖**

在 `requirements-dev.txt` 末尾追加：

```
ruff>=0.6,<1
```

- [ ] **Step 2: 安装并测量当前问题规模**

```powershell
python -m pip install "ruff>=0.6,<1"
python -m ruff check . --select=E9,F,I --statistics
```

记录输出的问题总数。这个数字决定下一步。

- [ ] **Step 3: 添加 ruff 配置**

在 `pyproject.toml` 末尾追加：

```toml
[tool.ruff]
target-version = "py310"
line-length = 100
extend-exclude = [
    ".refs",
    "_package_root",
    "artifacts",
    "frontend",
    "superpowers-zh",
]

[tool.ruff.lint]
# 首次接入只启用高信噪比规则。扩展规则集应在 Phase 2 结构重构后进行，
# 届时再逐条评估 B/SIM/UP 等规则。
select = ["E9", "F", "I"]

[tool.ruff.lint.per-file-ignores]
# 测试中的 fixture 注入和延迟 import 是刻意为之
"tests/**" = ["F811", "F401"]

[tool.ruff.lint.isort]
known-first-party = ["RxyCode"]
```

- [ ] **Step 4: 处理存量问题**

```powershell
python -m ruff check . --select=E9,F,I --fix
python -m ruff check .
```

`I`（import 排序）几乎全部可自动修复。若 `F` 类问题仍有残留，**逐条人工判断** —— `F401`（未使用 import）在本项目中可能是刻意保留的重导出，不要盲目删。

若某条确实是误报，用 `# noqa: F401` 加注释说明原因，不要放宽全局规则。

- [ ] **Step 5: 验证自动修复未破坏测试**

`--fix` 动了 import 顺序，而本项目有 400 处函数内延迟 import 用于打破循环依赖 —— 必须全量验证：

```powershell
python -m pytest tests -m "not live and not pty and not serial" -n 2 --dist loadscope -q --timeout=180 2>&1 | Select-Object -Last 8
python -m pytest tests -m "serial and not live and not pty" -n 0 -q --timeout=180 2>&1 | Select-Object -Last 8
```

预期：全部 passed。

⚠️ 若出现 `ImportError` 或 `AttributeError`，几乎可以确定是 ruff 的 import 重排触发了循环依赖。此时对该文件加豁免而非硬改：

```toml
[tool.ruff.lint.per-file-ignores]
"core/agent_v2.py" = ["I001"]
```

- [ ] **Step 6: 加入 CI**

在 `.github/workflows/ci.yml` 的 `jobs:` 下，`linux-backend` **之前**插入：

```yaml
  lint:
    name: Lint
    if: github.event_name != 'schedule'
    runs-on: ubuntu-latest
    timeout-minutes: 10
    steps:
      - uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: ${{ env.PYTHON_VERSION }}
          cache: pip
          cache-dependency-path: requirements-dev.txt

      - name: Install ruff
        run: python -m pip install -r requirements-dev.txt

      - name: Check lint rules
        run: python -m ruff check .

      - name: Check formatting drift
        run: python -m ruff format --check --diff .
        continue-on-error: true
```

注：`ruff format --check` 设 `continue-on-error: true` —— 首次接入不应因格式问题阻断构建。待格式统一后（Phase 2）再移除该行使其强制。

- [ ] **Step 7: 本地验证 CI 命令可通过**

```powershell
python -m ruff check .
```

预期：`All checks passed!`

- [ ] **Step 8: 提交**

```powershell
git add pyproject.toml requirements-dev.txt .github/workflows/ci.yml
git add -u
git commit -m "ci: add ruff lint gate with high-signal rule set"
```

---

## Task 6: CI 覆盖声明支持的 Python 版本

**Files:**
- Modify: `.github/workflows/ci.yml:23-24,28-46`

**Interfaces:**
- Consumes: Task 5 建立的 lint job
- Produces: `linux-backend` 在 3.10 与 3.13 上均验证

**背景**：`pyproject.toml:10` 声明 `requires-python = ">=3.10"`，classifiers（`:20-23`）列出 3.10/3.11/3.12/3.13，但 `ci.yml:24` 只测 3.12。**声明支持 4 个版本，实测 1 个。**

3.10 是下限（最可能因新语法失败），3.13 是上限（最可能因依赖不兼容失败）。测这两端即可覆盖绝大部分风险，不必跑全 4 个版本徒增 CI 时长。

- [ ] **Step 1: 写打包契约测试**

在 `tests/unit/test_packaging_contract.py` 末尾追加：

```python
def test_ci_covers_declared_python_floor_and_ceiling():
    """CI must test the lowest and highest Python versions we claim to support."""
    import re
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    pyproject = (root / "pyproject.toml").read_text(encoding="utf-8")
    workflow = (root / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

    declared = set(re.findall(r"Programming Language :: Python :: (3\.\d+)", pyproject))
    assert declared, "pyproject.toml declares no Python version classifiers"

    floor, ceiling = min(declared, key=float), max(declared, key=float)
    for version in (floor, ceiling):
        assert f'"{version}"' in workflow, (
            f"pyproject.toml claims support for Python {version} but ci.yml "
            f"never tests it"
        )
```

- [ ] **Step 2: 运行测试确认失败**

```powershell
python -m pytest tests/unit/test_packaging_contract.py::test_ci_covers_declared_python_floor_and_ceiling -v --timeout=60
```

预期：**FAILED**，报 `claims support for Python 3.10 but ci.yml never tests it`。

- [ ] **Step 3: 矩阵化 linux-backend**

修改 `.github/workflows/ci.yml`。将 `linux-backend` job 的 `runs-on` 下方插入 matrix：

```yaml
  linux-backend:
    name: Linux backend layers (py${{ matrix.python-version }})
    if: github.event_name != 'schedule'
    runs-on: ubuntu-latest
    timeout-minutes: 30
    strategy:
      fail-fast: false
      matrix:
        python-version: ["3.10", "3.12", "3.13"]
    env:
      RXYCODE_CORE_COVERAGE_FAIL_UNDER: "67"
      RXYCODE_PROJECT_COVERAGE_FAIL_UNDER: "60"
      RXYCODE_TEST_ROOT: ${{ github.workspace }}/artifacts/runtime
      RXYCODE_KEEP_TEST_ARTIFACTS: "1"
```

将该 job 内的 `python-version: ${{ env.PYTHON_VERSION }}`（原 `:46`）改为：

```yaml
          python-version: ${{ matrix.python-version }}
```

`fail-fast: false` 是必须的 —— 3.10 失败不应中断 3.13 的结果，否则无法一次看全兼容性问题。

- [ ] **Step 4: 修正产物名冲突**

矩阵化后三个 job 会上传同名 artifact 导致冲突。将该 job 的 upload 步骤 `name`（原 `:119`）改为：

```yaml
          name: linux-backend-test-reports-py${{ matrix.python-version }}
```

- [ ] **Step 5: 仅在主版本上强制覆盖率门槛**

3.10 与 3.13 的覆盖率可能因版本相关分支略有差异，不应因此阻断。将覆盖率报告步骤（原 `:109-113`）改为条件执行：

```yaml
          core_include="cache/*,config/*,core/*,execution/*,history/*,log/*,memory/*,planning/*,recovery/*,synthesis/*,tools/*,utils/*,validation/*"
          if [ "${{ matrix.python-version }}" = "3.12" ]; then
            python -m coverage report --include="$core_include" \
              --fail-under="$RXYCODE_CORE_COVERAGE_FAIL_UNDER"
            python -m coverage report \
              --fail-under="$RXYCODE_PROJECT_COVERAGE_FAIL_UNDER"
          else
            python -m coverage report --include="$core_include"
            python -m coverage report
          fi
```

此改动不违反 Global Constraints —— 门槛值未降低，仍在 3.12 上强制。

- [ ] **Step 6: 运行测试确认通过**

```powershell
python -m pytest tests/unit/test_packaging_contract.py -v --timeout=60
```

预期：全部 passed（含新增用例）。

- [ ] **Step 7: 验证 CI 契约测试未被破坏**

Global Constraints 要求不破坏 `test_ci_contracts.py`，而该文件有硬编码计数断言（`:59` `workflow.count("COVERAGE_FILE=") == 5`）：

```powershell
python -m pytest tests/unit/test_ci_contracts.py -v --timeout=60
```

预期：全部 passed。本 Task 未增减 COVERAGE_FILE 行数，计数不变。若失败，检查是否误改了 lane 数量。

- [ ] **Step 8: 提交**

```powershell
git add .github/workflows/ci.yml tests/unit/test_packaging_contract.py
git commit -m "ci: test Python 3.10 and 3.13 alongside 3.12"
```

---

## Task 7: 收紧覆盖率范围与依赖上限

**Files:**
- Modify: `.coveragerc:7-11`
- Modify: `requirements.txt`

**Interfaces:**
- Produces: 覆盖率分母不含第三方代码；关键依赖有上限保护

**背景 A**：`.coveragerc:6` 设 `source = .`，但 `omit` 未排除 `.refs/`（内含 gemini-cli 第三方代码树）、`_package_root/`、`scripts/`。第三方代码进入分母会稀释真实覆盖率。

**背景 B**：`requirements.txt` 中 `pydantic>=2.0.0` 和 `textual>=0.40.0` 无上限。pydantic 3 会是破坏性发布；textual 尚未到 1.0，API 频繁变动。

- [ ] **Step 1: 记录当前覆盖率基线**

改动前必须有基线，否则无法判断变化是否合理：

```powershell
python -m coverage erase
python -m pytest tests/unit -m "unit and not serial and not live and not pty" -q --cov --cov-report= --timeout=180
python -m coverage report 2>&1 | Select-Object -Last 3
```

记录 TOTAL 百分比。

- [ ] **Step 2: 收紧 omit**

将 `.coveragerc:7-11` 的 `omit` 段改为：

```
omit =
    */__pycache__/*
    */tests/*
    */frontend/*
    */superpowers-zh/*
    */.refs/*
    */_package_root/*
    */scripts/*
```

⚠️ **不得**添加 `api_server.py` 或 `main.py` —— `tests/unit/test_ci_contracts.py:45-50` 明确断言它们不在 omit 中。

- [ ] **Step 3: 确认覆盖率未被削弱**

```powershell
python -m coverage erase
python -m pytest tests/unit -m "unit and not serial and not live and not pty" -q --cov --cov-report= --timeout=180
python -m coverage report 2>&1 | Select-Object -Last 3
```

预期：TOTAL 百分比 **不低于** Step 1 记录值。排除的是从未被测试的第三方代码，分母缩小，比例应上升或持平。

若百分比下降，说明误排除了有覆盖的一方代码，回退检查。

- [ ] **Step 4: 验证 CI 契约测试**

```powershell
python -m pytest tests/unit/test_ci_contracts.py -v --timeout=60
```

预期：全部 passed。

- [ ] **Step 5: 添加依赖上限**

修改 `requirements.txt` 两行：

```
pydantic>=2.0.0,<3
textual>=0.40.0,<1
```

其余依赖保持不变 —— 已有上限的（langchain 系、langgraph、aiosqlite、jsonschema）不动，无上限但 API 稳定的（pyyaml、click、rich、httpx、fastapi 等）暂不加，避免过度约束导致后续升级摩擦。

- [ ] **Step 6: 验证依赖可解析**

```powershell
python -m pip install --dry-run -r requirements.txt 2>&1 | Select-Object -Last 5
```

预期：无 `ResolutionImpossible`。

- [ ] **Step 7: 提交**

```powershell
git add .coveragerc requirements.txt
git commit -m "build: exclude vendored code from coverage and cap volatile deps"
```

---

## Task 8: 全量验证与文档更新

**Files:**
- Modify: `tests/README.md`
- Create: `docs/plans/2026-07-27-stabilization-phase0-1-results.md`

**Interfaces:**
- Consumes: Task 1-7 全部产出
- Produces: 一份可验证的完成报告

**背景**：`tests/README.md:42,131` 严重过期 —— 声称"合计 111 个测试"、"conftest.py 约 30 行"，实测为 2073 个测试、conftest.py 319 行。

- [ ] **Step 1: 全量测试**

```powershell
python -m pytest tests -m "not live and not pty and not serial" -n 2 --dist loadscope -q --timeout=180 2>&1 | Select-Object -Last 10
```

预期：全部 passed，0 error。

- [ ] **Step 2: serial 层测试**

```powershell
python -m pytest tests -m "serial and not live and not pty" -n 0 -q --timeout=180 2>&1 | Select-Object -Last 10
```

预期：全部 passed。

- [ ] **Step 3: lint 与密钥扫描**

```powershell
python -m ruff check .
python scripts/scan_secrets.py .
```

预期：`All checks passed!` 与 `secret-scan: no credentials detected`

- [ ] **Step 4: 前端测试**

后端改动不应影响前端，但 Task 4 动了 CORS，需确认：

```powershell
cd frontend
npm test 2>&1 | Select-Object -Last 10
cd ..
```

预期：全部 passed。

- [ ] **Step 5: 更新 tests/README.md**

用实测数据替换过期数字。先取真实值：

```powershell
(Get-ChildItem tests -Recurse -Filter "test_*.py" -File).Count
(Get-ChildItem tests -Recurse -Filter "test_*.py" -File | Select-String -Pattern "^\s*(async )?def test_").Count
(Get-Content tests/conftest.py).Count
```

将 `tests/README.md:42` 的测试总数、`:131` 的 conftest.py 行数改为实测值，并删除对已不存在的 `r3_subdir/` 的引用。

- [ ] **Step 6: 写完成报告**

创建 `docs/plans/2026-07-27-stabilization-phase0-1-results.md`，记录：

- 每个 Task 的实际提交 hash（`git log --oneline`）
- Step 1/2 的测试通过数
- Task 7 Step 1 与 Step 3 的覆盖率对比
- 遗留项：Phase 2 待办（AgentV2 上帝类、5 处循环依赖、slash 命令双实现、关键词路由、测试分层迁移仅完成 12.8%）

- [ ] **Step 7: 最终提交**

```powershell
git add tests/README.md docs/plans/
git commit -m "docs: refresh test suite stats and record phase 0-1 results"
git log --oneline
```

预期：8 个提交，从 `chore: initial commit` 到本次。

---

## 验收标准

全部 Task 完成后，以下命令必须全绿：

```powershell
python -m pytest tests -m "not live and not pty and not serial" -n 2 --dist loadscope -q --timeout=180
python -m pytest tests -m "serial and not live and not pty" -n 0 -q --timeout=180
python -m ruff check .
python scripts/scan_secrets.py .
git status --porcelain    # 应为空
```

且以下事实成立：

- [ ] `git rev-list --count HEAD` ≥ 8
- [ ] 根目录无 `*.xml`、无 `~/`、无 `artifacts/`
- [ ] `core/agent_v2.py.bak` 不存在
- [ ] `api_server.py` 不含 `allow_origin_regex`
- [ ] `ci.yml` 含 `lint` job 且矩阵包含 `"3.10"` 与 `"3.13"`
- [ ] `.gitignore` 含 `.refs/` 与 `.pytest-*.xml`

---

## 不在本计划范围内（Phase 2）

以下问题已确认存在，但**风险与工量远大于本计划**，需独立规划：

| 问题 | 证据 | 规模 |
|---|---|---|
| `AgentV2` 上帝类 | `core/agent_v2.py:645-3501`，2857 行 / 44 方法 / 10 职责域 | 大 |
| 5 处包级循环依赖 | `validation/final_output.py:19`、`execution/executor.py:9` 等；导致 400 处函数内 import | 大 |
| slash 命令双实现且已漂移 | `main.py:289` vs `api_server.py:1120`，32 命令重复，4 个单边存在 | 中 |
| `_fast_reply` / `_fast_reply_with_tools` 并存 | `agent_v2.py:2542` vs `:1993`，后者 docstring 自认替代但旧的未删 | 中 |
| 关键词硬编码意图路由 | `agent_v2.py:1792-1870`，18 张表 120 字面量；`:1841` 注释记录了由此产生的线上 bug | 中 |
| 测试分层迁移仅完成 12.8% | 109/125 文件仍在 `test_core/`(49)、根目录(28)、`test_tools/`(18) | 中 |
| 死代码 `_run_with_subagents` | `agent_v2.py:2729` 直接 raise，但 `_should_use_subagents` 仍被调用 | 小 |
| `initial_state` 18 键字典复制两遍 | `agent_v2.py:2788` 与 `:3288` | 小 |
| 无类型检查 | 无 mypy/pyright 配置 | 中 |

**建议顺序**：先抽 `contracts/` 包放 `AgentState`/`TaskTree` 打破循环依赖（收益最高、风险最低），再收敛 slash 命令注册表，最后拆 `AgentV2`。
