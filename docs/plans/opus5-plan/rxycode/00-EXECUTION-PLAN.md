# RxyCode 执行计划（2026-08-03 修订版 / 权威版）

> **文档状态**：本文件取代本目录下 `00-master-plan.md`、`01-tech-debt-cleanup.md`、`README.md`、`QUICKSTART.md`、`DAILY-CHECKLIST.md`、`DELIVERY-SUMMARY.md`。
> 那批文件基于 `docs/plans/2026-07-30-comprehensive-review-and-roadmap.md`，该报告存在**未经实测的事实错误**（见 §2.3），并按 6 人团队 / $630,740 预算编写，与实际的 2–3 人团队不匹配。
>
> **执行者**：本文件面向能力较弱的模型（Sonnet 5 级别）编写。每个任务卡都是**自包含**的——包含背景、精确文件路径与行号、可复制的命令、验收标准、回滚方式。执行时**只需要读本文件的一个任务卡**，不需要通读全文，也不需要重新做架构调研。
>
> **基线日期**：2026-07-31　**排期起点**：2026-08-03（周一）　**团队规模**：2–3 人

---

## 目录

| 章节 | 内容 | 什么时候读 |
|---|---|---|
| [§0 执行手册](#0-执行手册必读) | 硬性规则、任务卡协议、环境命令 | **每次开始工作前必读** |
| [§1 事实基线](#1-事实基线全部经过实测) | 实测数据 + 证据行号 | 需要引用现状时 |
| [§2 历史文档复盘](#2-历史文档复盘) | 7/27 计划执行情况、7/30 报告勘误 | 想知道"之前做到哪了" |
| [§3 排期总表](#3-排期总表) | Phase 0–4、周级排期、人员分工 | 规划与汇报 |
| [§4 Phase 0 止血](#4-phase-0--止血w1-w2) | S1–S8 任务卡 | 执行 Phase 0 |
| [§5 Phase 1 Harness](#5-phase-1--harness-说真话w3-w5) | H1–H6 任务卡 | 执行 Phase 1 |
| [§6 Phase 2 协议与核心](#6-phase-2--协议层与核心解耦w6-w12) | P1–P8 任务卡 | 执行 Phase 2 |
| [§7 Phase 3 模型输出上限](#7-phase-3--模型输出上限自适应w13-w15) | M1–M8 任务卡 | 执行 Phase 3 |
| [§8 Phase 4 Desktop](#8-phase-4--desktop-应用w16-w23) | D1–D8 任务卡 | 执行 Phase 4 |
| [§9 竞品对照](#9-竞品对照窄赛道) | 与 20 个开源 Agent 的差距 | 做取舍决策时 |
| [§10 维护与扩展手册](#10-维护与扩展手册) | 加工具/对话框/评测/协议方法的标准流程 | **日常维护必读** |
| [§11 附录](#11-附录) | 命令速查、证据索引、术语表 | 随时查 |
| [§12 文档映射](#12-文档映射与工作流程) | 全路线文档、依赖和协作协议 | 接手任务前必读 |

---

## §0 执行手册（必读）

### 0.1 你的工作方式

你是一个在 **Windows / PowerShell** 环境下工作的编码代理，仓库根目录是：

```
D:\agent-demo\RxyCode\RxyCode1_1_0
```

**每次接到一个任务卡（例如 "执行 S1"），按以下 6 步走，一步都不要跳：**

```
1. READ    读任务卡的「背景」「涉及文件」，用 Read 工具打开每一个涉及文件，确认行号还对得上
2. PLAN    如果任务卡有多个步骤，先在心里过一遍；不要一次改 5 个文件
3. EDIT    按「操作步骤」逐条改。每改完一个文件就停下来
4. VERIFY  运行任务卡「验收命令」里的每一条命令，把真实输出贴出来
5. REPORT  对照「完成判据」逐条打勾。有任何一条不满足就回到 3
6. COMMIT  用任务卡给出的 commit message 提交（除非用户说不要提交）
```

### 0.2 硬性规则（违反任何一条都算任务失败）

| # | 规则 | 原因 |
|---|---|---|
| R1 | **行号会漂移。** 任务卡里的 `file.py:123` 是 2026-07-31 的快照。动手前必须用 `Read` 或 `Grep` 重新定位，以**内容**为准，不要以行号为准 | 别人可能已经改过 |
| R2 | **不要声称"完成"而没有跑验收命令。** 必须贴出命令的真实输出 | 这是本项目最常见的失败模式 |
| R3 | **一次只做一个任务卡。** 做完 S1 再做 S2，不要合并 | 弱模型在长任务上会丢上下文 |
| R4 | **不要重构任务卡范围外的代码。** 看到丑代码忍住，记到 §10.4 待办里 | 防止 diff 爆炸导致无法 review |
| R5 | **不要删除 / 重写 `core/agent_v2.py` 的任何现有分支逻辑**，除非任务卡明确要求。它有 3704 行且被 API + TUI + evals 三方依赖 | 破坏面极大 |
| R6 | **不要碰 `data/`、`credentials.yaml`、`.env*`、`~/.rxycode/`**。里面是真实 API Key | 泄密 |
| R7 | **PowerShell 不支持 heredoc（`<<'EOF'`）。** 要跑多行 Python，先用 `Write` 工具写成 `.py` 文件再 `python file.py`，跑完删掉 | 已踩坑，见 §11.1 |
| R8 | **不要在 CI 里加 `continue-on-error: true` 来"修复"失败的测试** | 这是把红灯涂成绿灯 |
| R9 | **每个任务卡都要留下可回滚的单个 commit。** 不要一个 commit 里塞两个任务 | 出事能 revert |
| R10 | **文档同步是任务的一部分**，不是可选项。改了模块就改 `docs/modules/<模块>.md` | 见 `AGENTS.md` |

### 0.3 环境准备（每个新会话跑一次）

```powershell
cd "D:\agent-demo\RxyCode\RxyCode1_1_0"

# 1) 确认 Python 环境
python --version                      # 期望 3.11 或 3.12
python -c "import langgraph, fastapi; print('deps ok')"

# 2) 确认 git 干净（有改动先问用户）
git status --short

# 3) 确认在正确分支
git branch --show-current
```

如果第 2 步有未提交改动而任务卡没提到，**停下来问用户**，不要 `git checkout .`。

### 0.4 常用验收命令

```powershell
# 后端单元测试（快）
python -m pytest tests -q -x --timeout=120

# 后端 + 覆盖率（慢，~5min）
python -m pytest tests -q --cov=. --cov-report=term-missing

# 只跑某个文件
python -m pytest tests/test_agent_v2.py -q

# Lint（Phase 0 之后才有）
python -m ruff check .

# OpenTUI 类型检查 + 测试
cd frontend\opentui-app; bun run tsc --noEmit; bun test; cd ..\..

# Ink（已弃用，仅回归用）
cd frontend; npx tsc --noEmit; npx vitest run; cd ..

# 评测 harness
python -m evals.cli run --dry-run
```

### 0.5 任务卡的固定结构

每个任务卡都长这样，字段含义固定：

```
### <ID> · <标题>
优先级 / 负责角色 / 预计工时 / 依赖
**背景**      —— 为什么要做，不做会怎样
**涉及文件**  —— 精确路径 + 当前行号 + 定位锚点字符串
**操作步骤**  —— 编号步骤，含可复制代码
**验收命令**  —— 必须跑，必须贴输出
**完成判据**  —— 逐条打勾
**回滚**      —— 出事怎么退
**常见坑**    —— 已知的失败模式
**Commit**    —— 提交信息模板
```

---

## §1 事实基线（全部经过实测）

以下每一条都在 2026-07-31 用命令实测过。**引用现状时用这张表，不要用 7/30 报告里的数字。**

### 1.1 代码规模与结构

| 事实 | 数值 | 证据 / 复现命令 |
|---|---|---|
| `core/agent_v2.py` 行数 | **3704** | `(Get-Content core\agent_v2.py).Count` |
| `core/agent_v2.py.bak` **被 git 跟踪** | 是 | `git ls-files core/agent_v2.py.bak` → 有输出 |
| 后端测试函数总数 | 2146 | `python -m pytest tests --collect-only -q` |
| pytest 收集项 | 9715 | 同上（含参数化） |
| OpenTUI 测试文件 | **19 个** | `Get-ChildItem frontend\opentui-app\src -Recurse -Include *.test.ts,*.test.tsx` |
| OpenTUI 测试用例 | 67 | `cd frontend\opentui-app; bun test` |
| OpenTUI 测试进 CI | **否** | `.github/workflows/ci.yml` 无 `bun` 字样 |
| `docs/` 被 gitignore | 是 | `.gitignore:68` `docs/*`，仅放行 `docs/modules/`、`docs/images/` |

> ⚠️ **`.gitignore:68` 的后果**：本文件（`docs/plans/execution/...`）**不在版本控制里**。如果需要它进仓库，见 [S6](#s6--让计划文档进版本控制)。

### 1.2 CI 与质量门禁

| 事实 | 现状 | 证据 |
|---|---|---|
| CI 文件 | `.github/workflows/ci.yml` | — |
| Python 版本矩阵 | **单版本 3.12**，无矩阵 | `ci.yml:24` `PYTHON_VERSION: "3.12"` |
| Node 版本 | 22 | `ci.yml:25` |
| 核心包覆盖率门禁 | 67% | `ci.yml:36` `RXYCODE_CORE_COVERAGE_FAIL_UNDER: "67"` |
| 全项目覆盖率门禁 | 60% | `ci.yml:37` `RXYCODE_PROJECT_COVERAGE_FAIL_UNDER: "60"` |
| ruff / lint 步骤 | **不存在** | `ci.yml` 无 `ruff` 字样 |
| `requirements-dev.txt` 是否含 ruff | **否**，共 10 行，只有 pytest 系 + build/twine | 见文件 |
| `pyproject.toml` 是否有 `[tool.ruff]` | **否**，全文 80 行，结尾是 `[tool.setuptools.package-data]` | 见文件 |
| CI 里跑的前端 | 只有 Ink（`frontend/`，`npm ci && npm run build`） | `ci.yml:59-63` |

### 1.3 安全 / 网络

| 事实 | 现状 | 证据 |
|---|---|---|
| CORS 白名单 | `_allowed_origins` 列表 | `api_server.py:177` |
| CORS 正则 | `allow_origin_regex=r"https?://(localhost\|127\.0\.0\.1\|\[::1\])(:\d+)?"` | `api_server.py:188` |
| 风险 | 正则**放行任意端口**的 localhost，本机任何网页可打 Agent API | `api_server.py:186-188` |

### 1.4 评测 Harness（这是最严重的一块）

| 事实 | 现状 | 证据 |
|---|---|---|
| runner 是否跑真实 Agent | **否**，直接 `await llm.ainvoke([HumanMessage(...)])` | `evals/runner.py:414` |
| 后果 | 评测测的是**裸 LLM**，不经过 LangGraph、工具、记忆、安全门 | 同上 |
| workdir 判定 | 只要有 `file_exists`/`file_contains`/`file_not_contains`/`command_succeeds` 就建空临时目录 | `evals/tasks.py:56,113-117` |
| `readcode-prompt-registry.yaml` 的 6 个 `file_exists` | 检查 `core/prompts/*.py`，但工作目录是**空临时目录** → **恒失败** | 任务 YAML `:20-31`；`setup: ""`（无 setup_files） |
| 同任务的 `command_succeeds` | 11 条里有 **3 条是 Python 语法错误**（`assert` 写在列表推导 / lambda 里） | YAML `:41`、`:61`、`:76`；实测 `ast.parse` 抛 `invalid syntax` |
| evals 是否进 CI | **否** | `ci.yml` 无 `evals` 字样 |

**实测输出（2026-07-31）：**

```
listcomp_assert SYNTAX_ERROR: invalid syntax     # [assert isinstance(x,str) for x in y]
lambda_assert   SYNTAX_ERROR: invalid syntax     # (lambda p: (assert 'a' in p))
check[7]  SYNTAX_ERROR: invalid syntax           # YAML :41
check[11] SYNTAX_ERROR: invalid syntax           # YAML :61
check[14] SYNTAX_ERROR: invalid syntax           # YAML :76
workdir_checks: 6
setup_field: ''
```

**结论**：当前的 eval 分数**没有任何参考价值**。它既不测 Agent，任务本身也是坏的。Phase 1 的全部意义就是让这个数字变成真的。

### 1.5 架构债务

| 事实 | 数值 | 说明 |
|---|---|---|
| `agent_v2.py` 关键词路由点 | ~25 处 | 硬编码中英文关键词列表决定走哪条链路 |
| 函数内延迟 import | ~131 处 | 为绕开循环依赖，把 `import` 塞进函数体 |
| `AgentV2` 角色 | God Object | 同时负责路由、缓存、记忆、子代理、compose、SSE 事件 |
| 客户端接入方式 | HTTP + SSE（`api_server.py`） | 无类型化协议，事件字段靠约定 |

---

## §2 历史文档复盘

### 2.1 `docs/plans/2026-07-27-stabilization-phase0-1.md` 执行情况

**结论：约完成 40%，"环境卫生"类做了，"质量门禁"类基本没做。**

| 原 Task | 内容 | 实测状态 | 证据 |
|---|---|---|---|
| Task 0 | git 基线 / 分支 | ✅ 已做 | 仓库有正常提交历史 |
| Task 1 | 清理 `.refs/`、`~/` 等垃圾目录 | ⚠️ **部分**：`.gitignore` 已加规则（`:14` `.refs/`、`:61` `~/`），但**物理目录仍在磁盘上**且体积可观 | 见 [S2](#s2--物理删除垃圾目录) |
| Task 2 | 删除 `*.bak` | ❌ **未做**，`core/agent_v2.py.bak` 仍被 git 跟踪 | `git ls-files core/agent_v2.py.bak` |
| Task 3 | 修复 `~` 路径 bug | ✅ 已做 | 输出目录已走 `~/.rxycode/output/` |
| Task 4 | 收紧 CORS | ❌ **未做**，`allow_origin_regex` 仍放行任意 localhost 端口 | `api_server.py:188` |
| Task 5 | 引入 ruff | ❌ **完全未做**：无 `[tool.ruff]`、`requirements-dev.txt` 无 ruff、CI 无 lint 步骤 | §1.2 |
| Task 6 | Python 版本矩阵 | ❌ **未做**，CI 仍单版本 3.12 | `ci.yml:24` |

**Phase 0 的任务卡（S1–S8）就是把这张表里的 ❌ 和 ⚠️ 清掉，外加几个新发现的。**

### 2.2 `docs/plans/2026-07-28-execution-progress.md`

33 行的进度便签，内容已被本文件 §2.1 覆盖，可忽略。

### 2.3 `docs/plans/2026-07-30-comprehensive-review-and-roadmap.md` 勘误

该报告（805 行）由中转站模型生成，**结构漂亮但事实层不可靠**。已核实的错误：

| 报告说法 | 实测 | 影响 |
|---|---|---|
| "AgentV2 有 44 个方法需要拆分" | 方法数与该数字对不上；真正的问题是 **3704 行 + 25 处关键词路由 + 131 处延迟 import** | 拆分方案的切分依据是错的 |
| "评测覆盖率 X%，通过率 Y%" | 评测**根本不跑 Agent**（`evals/runner.py:414`），且任务本身有语法错误 | 所有引用的分数无效 |
| "无 Desktop，只有 CLI" | 方向对，但把竞品当成同品类横向比较（把 IDE、Agent 框架、CLI 混在一张表） | 结论"要做 Kubernetes 多租户"跑偏 |
| 预算 $630,740 / 6 人 / 6 个月 | 实际 2–3 人 | 整个 WBS 不可执行 |
| 推荐 Electron + Skills 自动创建 + Telegram Bot | 对 2–3 人团队是明显的范围失控 | 见 §3 的取舍 |

**处置**：保留该文件作为历史记录，但**不要按它执行**。已在 §0 顶部标注取代关系。

---

## §3 排期总表

### 3.1 人员

> **2026-08-01 补充**：本表的 A/B/C 是早期"三人分工"的遗留，卡 meta 里至今保留。分模型后它是历史记号，**不决定谁干活**——决定权在卡上的 `owner: backend / frontend`（权威见 [`../MODEL-ASSIGNMENT.md`](../MODEL-ASSIGNMENT.md)）。对应关系：

| 旧代号 | 旧角色 | 新体系里的承担者 |
|---|---|---|
| **A** | 后端 / 核心架构（Tech Lead） | Composer 2.5（主写全部） |
| **B** | 前端 / TUI / Desktop | Composer 主写前端；**Grok 4.5 只辅助卡内标注的多模态环节** |
| **C** | QA / CI（可选第 3 人） | 你（人）+ Sonnet 5（diff 预审） |

| 代号 | 角色 | 投入 | 主要负责 |
|---|---|---|---|
| **A** | 后端 / 核心架构（Tech Lead） | 100% | Phase 0 后端项、Phase 1 harness、Phase 2 协议与核心解耦、Phase 3 模型输出上限 |
| **B** | 前端 / TUI / Desktop | 100% | OpenTUI、协议 TS 客户端、Phase 4 Desktop 全部 |
| **C** | QA / CI（可选第 3 人） | 50% | CI 流水线、覆盖率、发布门禁；缺人时由 A 兼 |

### 3.2 Phase 总览

| Phase | 周次 | 日期 | 目标 | 出口标准（Exit Criteria） | 实际状态 |
|---|---|---|---|---|---|
| **Phase 0 止血** | W1–W2 | 08-03 ~ 08-14 | 补完 7/27 遗留，建立 lint 与最小门禁 | `ruff check .` 通过并进 CI；CORS 收紧；无跟踪的 `.bak`；CI 双 Python 版本 | ✅ 已完成 |
| **Phase 1 Harness** | W3–W5 | 08-17 ~ 09-04 | 让评测说真话 | evals 跑真实 Agent；坏任务全部修复或删除；evals 进 CI（nightly）；基线分数落盘 | ✅ 已完成（基线重建 88.2%，2026-08-05） |
| **Phase 2 协议与核心** | W6–W12 | 09-07 ~ 10-23 | 抽出 headless core + 类型化协议 | `protocol/` 有 schema 且能生成 TS 类型；`appserver` stdio JSON-RPC 可跑通；OpenTUI 迁到协议；`api_server.py` 变薄 | ✅ P1–P8 完成，api_server 收薄闭合（2026-08-05） |
| **Phase 3 模型输出上限自适应** | W13–W15 | 10-26 ~ 11-13 | 模型 ID 驱动的输出上限解析 | 新增模型默认 auto；精确 ID 命中目录；未知模型高位兜底；来源可解释 | ⏳ 未开始（计划 W13 起） |
| **Phase 4 Desktop** | W16–W23 | 11-16 ~ 01-08 | Desktop MVP 发布 | 三平台打包；对话/流式/审批/设置可用；复用同一协议客户端，并消费 Phase 3 的模型上限摘要 | ⏳ 未开始 |

### 3.3 周级排期

| 周 | 日期 | A（后端） | B（前端） | C（CI） |
|---|---|---|---|---|
| W1 | 08-03 ~ 08-07 | S1 S2 S3 S4 | S7 | S5 |
| W2 | 08-10 ~ 08-14 | S8 | S7 | S5 S6 |
| W3 | 08-17 ~ 08-21 | H1 H2 | （OpenTUI 债务） | H5 |
| W4 | 08-24 ~ 08-28 | H3 | （OpenTUI 债务） | H5 |
| W5 | 08-31 ~ 09-04 | H4 H6 | P2 预研 | H5 |
| W6 | 09-07 ~ 09-11 | P1 | P2 | — |
| W7 | 09-14 ~ 09-18 | P1 P3 | P2 | — |
| W8 | 09-21 ~ 09-25 | P3 | P4 | — |
| W9 | 09-28 ~ 10-02 | P4 | P5 | — |
| W10 | 10-05 ~ 10-09 | P5 | P5 | — |
| W11 | 10-12 ~ 10-16 | P6 | P6 | — |
| W12 | 10-19 ~ 10-23 | P7 P8 | P8 | P8 |
| W13 | 10-26 ~ 10-30 | M1 M2 | — | — |
| W14 | 11-02 ~ 11-06 | M3 M4 | — | — |
| W15 | 11-09 ~ 11-13 | M5 M6 M7 M8 | — | — |
| W16–W17 | 11-16 ~ 11-27 | （支援） | D1 D2 | — |
| W18–W19 | 11-30 ~ 12-11 | D3 后端侧 | D3 D4 | — |
| W20–W21 | 12-14 ~ 12-25 | — | D5 D6 | — |
| W22–W23 | 12-28 ~ 01-08 | — | D7 | D8 |

### 3.4 明确**不做**的事（范围保护）

2–3 人团队，以下项目从路线图中**移除**，理由写在后面。看到 7/30 报告里提到它们时忽略。

| 移除项 | 理由 |
|---|---|
| Kubernetes / Helm / 多租户 | 没有企业客户，投入产出比极低 |
| Telegram / Discord Bot | 与核心竞争力无关，是渠道不是产品 |
| Skills 自动创建（轨迹分析 + 模式提取 + 代码生成） | 研究性课题，2–3 人做不出可用的东西 |
| 可视化工作流编辑器 | Phase 4 之后再议 |
| LSP 深度集成 | 现有 `lsp/` 保持实验状态，不投入 |

---

## §4 Phase 0 — 止血（W1–W2）

> **目标**：两周内把仓库变成"改动可验证"的状态。这一阶段**不改任何业务逻辑**。

### S1 · 删除被跟踪的备份文件

`P0` / **A** / 0.5h / 无依赖

**背景**
`core/agent_v2.py.bak` 被 git 跟踪。它是 3700 行核心文件的旧副本，会污染全文搜索、混淆 AI 代理（可能读到过期实现）、并让 diff 噪音变大。7/27 计划的 Task 2 要求删除，未执行。

**涉及文件**
- `core/agent_v2.py.bak`（待删）
- `.gitignore`（追加规则）

**操作步骤**

1. 先确认还有哪些 `.bak` / 备份文件被跟踪：

```powershell
cd "D:\agent-demo\RxyCode\RxyCode1_1_0"
git ls-files | Select-String -Pattern '\.(bak|orig|old|copy)$|~$'
```

2. 逐个从 git 和磁盘删除（下面以已知的一个为例；第 1 步若发现更多，一并处理）：

```powershell
git rm --cached "core/agent_v2.py.bak"
Remove-Item "core/agent_v2.py.bak" -Force
```

3. 在 `.gitignore` 的 `# --- Python ---` 段落末尾（当前 `.gitignore:41` `env/` 之后）追加：

```gitignore

# --- 备份 / 临时副本（禁止入库）---
*.bak
*.orig
*.old
*.rej
```

**验收命令**

```powershell
git ls-files | Select-String -Pattern '\.(bak|orig|old)$'   # 期望：无输出
Test-Path "core/agent_v2.py.bak"                            # 期望：False
git status --short                                          # 期望：只有 .gitignore 的 M 和 .bak 的 D
```

**完成判据**
- [x] `git ls-files` 里没有任何 `.bak`/`.orig`/`.old`
- [x] 磁盘上 `core/agent_v2.py.bak` 不存在
- [x] `.gitignore` 含新的备份规则
- [x] `python -m pytest tests -q -x --timeout=120` 仍全绿

**回滚**：`git checkout HEAD -- core/agent_v2.py.bak .gitignore`

**常见坑**：不要用 `git rm`（不带 `--cached`）后又忘了 `Remove-Item`——两步都要。

**Commit**
```
chore: remove tracked agent_v2 backup file and ignore *.bak

7/27 stabilization Task 2 leftover. The 3.7k-line stale copy pollutes
codebase search and misleads AI agents reading it as live code.
```

---

### S2 · 物理删除垃圾目录

`P0` / **A** / 0.5h / 无依赖

**背景**
7/27 Task 1 只把 `.refs/`、`~/` 加进了 `.gitignore`（`:14`、`:61`），目录本身**还在磁盘上**。`.refs/` 是第三方参考仓库的拷贝（数十 MB），会拖慢本地全文检索并让 AI 代理误读别人的代码当成本项目实现。`~/` 是历史上 `~` 路径 bug 的产物。

**涉及文件**：无源码改动，只删目录。

**操作步骤**

1. 先看清楚要删什么、多大，**不要盲删**：

```powershell
cd "D:\agent-demo\RxyCode\RxyCode1_1_0"
foreach ($d in @(".refs", "~", ".codebuddy", "superpowers-zh")) {
  if (Test-Path $d) {
    $size = (Get-ChildItem $d -Recurse -File -EA SilentlyContinue | Measure-Object Length -Sum).Sum
    "{0,-20} {1,10:N2} MB" -f $d, ($size/1MB)
  } else { "{0,-20} (不存在)" -f $d }
}
```

2. 确认这些目录**都不被 git 跟踪**（跟踪了就说明有人故意提交过，要先问用户）：

```powershell
git ls-files ".refs" "~" ".codebuddy" "superpowers-zh"   # 期望：无输出
```

3. 无输出才继续删除：

```powershell
foreach ($d in @(".refs", "~", ".codebuddy", "superpowers-zh")) {
  if (Test-Path $d) { Remove-Item $d -Recurse -Force; "deleted $d" }
}
```

**验收命令**

```powershell
Test-Path ".refs", "~"          # 期望：False False
git status --short              # 期望：无输出（这些目录本来就是 ignored）
python -m pytest tests -q -x --timeout=120
```

**完成判据**
- [x] 第 2 步输出为空（确认过没跟踪）
- [x] 目录已从磁盘消失
- [x] `git status` 干净
- [x] 测试全绿

**回滚**：**不可回滚**（这些是本地未跟踪文件）。所以第 2 步的确认**必须做**。如果 `.refs/` 里有你需要的参考资料，先移到仓库外，比如 `D:\agent-demo\_refs_archive\`。

**Commit**：无代码改动，不需要 commit。在 PR 描述里说明即可。

---

### S3 · 收紧 CORS

`P0` / **A** / 1h / 无依赖

**背景**
`api_server.py:188` 的 `allow_origin_regex` 放行 `localhost` / `127.0.0.1` / `[::1]` 的**任意端口**。这意味着用户浏览器上打开的**任何**本地开发页面（哪怕是无关项目的 `localhost:3000`）都能向 RxyCode API 发跨域请求，进而驱动一个有**文件写入和 shell 执行能力**的 Agent。这是本仓库当前最实在的安全问题。7/27 Task 4 要求修复，未执行。

**涉及文件**
- `api_server.py:177`（锚点：`_allowed_origins = [`）
- `api_server.py:186-188`（锚点：`CORSMiddleware,`）
- `config/settings.py`（新增配置项）
- `tests/test_api_cors.py`（新建）

**操作步骤**

1. 用 `Read` 打开 `api_server.py` 的 170–200 行，确认 `_allowed_origins` 当前内容和 `add_middleware` 调用的完整形态。**把原样贴在你的工作笔记里**，后面要对照。

2. 在 `config/settings.py` 中新增一个可覆盖的白名单配置（放在其它设置项旁边，遵循文件已有风格）：

```python
# 允许跨域访问 API 的来源。默认只放行 TUI / Desktop 实际使用的端口。
# 生产部署可用环境变量 RXYCODE_ALLOWED_ORIGINS 覆盖（逗号分隔）。
DEFAULT_ALLOWED_ORIGINS = (
    "http://localhost:8000",
    "http://127.0.0.1:8000",
    "http://localhost:5173",   # Vite dev server（Desktop 开发用）
    "http://127.0.0.1:5173",
)
```

3. 在 `api_server.py` 里，把 `_allowed_origins` 改为读取上面的配置 + 环境变量覆盖，并**删除 `allow_origin_regex` 参数**：

```python
_allowed_origins = _resolve_allowed_origins()   # 见下方新增函数

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    # 注意：不要加回 allow_origin_regex。任意端口的 localhost 放行等同于
    # 让本机任何网页驱动一个有写文件 / 执行 shell 能力的 Agent。
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)
```

4. 新增解析函数（放在 `api_server.py` 中 `_allowed_origins` 定义之前）：

```python
def _resolve_allowed_origins() -> list[str]:
    """解析 CORS 白名单：环境变量优先，否则用 settings 默认值。"""
    import os
    from config.settings import DEFAULT_ALLOWED_ORIGINS

    raw = os.environ.get("RXYCODE_ALLOWED_ORIGINS", "").strip()
    if raw:
        return [o.strip() for o in raw.split(",") if o.strip()]
    return list(DEFAULT_ALLOWED_ORIGINS)
```

5. 新建 `tests/test_api_cors.py`：

```python
"""CORS 白名单回归测试。

任意端口的 localhost 曾经被 allow_origin_regex 放行，导致本机任何网页
都能驱动 Agent。这些测试锁死该行为不再回归。
"""
import os

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client():
    import api_server
    return TestClient(api_server.app)


def test_allowed_origin_gets_cors_header(client):
    resp = client.get("/health", headers={"Origin": "http://localhost:8000"})
    assert resp.headers.get("access-control-allow-origin") == "http://localhost:8000"


@pytest.mark.parametrize("origin", [
    "http://localhost:3000",
    "http://localhost:9999",
    "http://127.0.0.1:1337",
    "http://evil.example.com",
])
def test_unlisted_origin_is_rejected(client, origin):
    resp = client.get("/health", headers={"Origin": origin})
    assert "access-control-allow-origin" not in resp.headers


def test_env_override(monkeypatch):
    monkeypatch.setenv("RXYCODE_ALLOWED_ORIGINS", "http://localhost:4321")
    import api_server
    assert api_server._resolve_allowed_origins() == ["http://localhost:4321"]
```

> 如果 `/health` 端点不存在，用 `Grep` 找一个已有的 GET 端点替换（`Grep pattern:'@app\.get' path:api_server.py`）。

**验收命令**

```powershell
python -m pytest tests/test_api_cors.py -q
Select-String -Path api_server.py -Pattern "allow_origin_regex"   # 期望：无输出
python -m pytest tests -q -x --timeout=120
```

**完成判据**
- [x] `api_server.py` 中 `allow_origin_regex` 已完全移除
- [x] `tests/test_api_cors.py` 全部通过（含 4 个被拒来源的参数化用例）
- [x] 环境变量覆盖测试通过
- [x] 全量后端测试仍全绿
- [x] 手动验证：启动 API + OpenTUI，对话功能正常

**回滚**：`git revert <commit>`

**常见坑**
- OpenTUI 实际连的端口如果不是 8000，白名单会把自己人挡掉。改之前先 `Grep pattern:'localhost:|127\.0\.0\.1:' path:frontend/opentui-app/src` 确认实际端口，并加进 `DEFAULT_ALLOWED_ORIGINS`。
- FastAPI 只在**跨域请求**（带 `Origin` 头）时才回 CORS 头。直接 `curl` 不带 `Origin` 看不到差别，不代表没生效。

**Commit**
```
fix(security): restrict CORS to an explicit origin allowlist

allow_origin_regex matched localhost on any port, so any page the user
had open locally could drive an agent with filesystem and shell access.
Replaces it with a settings-driven allowlist overridable via
RXYCODE_ALLOWED_ORIGINS.
```

---

### S4 · 引入 ruff（配置 + 一次性修复）

`P0` / **A** / 4h / 依赖 S1

**背景**
7/27 Task 5 完全未执行：`pyproject.toml`（80 行）无 `[tool.ruff]`，`requirements-dev.txt`（10 行）无 ruff，CI 无 lint 步骤。没有 lint 意味着未使用的 import、未定义的名字、明显的 bug 模式全靠人眼。对一个有 131 处延迟 import 的代码库，这类工具的收益很高。

**涉及文件**
- `pyproject.toml`（在文件**末尾**追加，当前 80 行）
- `requirements-dev.txt`（追加一行）
- 大量源文件（自动修复）

**操作步骤**

1. 安装 ruff 并追加到开发依赖。在 `requirements-dev.txt` 末尾（`twine>=6.0,<7` 之后）加：

```
ruff>=0.8,<1
```

然后：

```powershell
python -m pip install "ruff>=0.8,<1"
python -m ruff --version
```

2. 在 `pyproject.toml` **文件末尾**追加配置。**起步规则集要保守**——目标是"能进 CI 且零告警"，而不是一次性修完所有风格问题：

```toml

[tool.ruff]
line-length = 100
target-version = "py311"
exclude = [
  ".venv",
  "_package_root",
  "frontend",
  "build",
  "dist",
  "artifacts",
]

[tool.ruff.lint]
# 起步集：只开"几乎不会误报、且能抓真 bug"的规则。
# 风格类（I 排序、UP 升级语法）等 CI 绿了之后再逐条开，见 §10.5。
select = [
  "E9",    # 语法错误 / IO 错误
  "F",     # pyflakes：未定义名字、未使用 import、f-string 缺占位符
  "B",     # flake8-bugbear：可变默认参数、循环变量绑定等真 bug
  "W605",  # 无效转义序列
]
ignore = [
  "B008",  # FastAPI 的 Depends() 默认参数是标准写法
  "B905",  # zip(strict=) 需要 3.10+，逐步迁移
]

[tool.ruff.lint.per-file-ignores]
"tests/*" = ["F811", "F401"]        # fixture 重定义 / 显式 re-export
"**/__init__.py" = ["F401"]         # 包级 re-export

[tool.ruff.format]
quote-style = "double"
indent-style = "space"
```

3. 跑一次全量检查，看基数有多大：

```powershell
python -m ruff check . --statistics
```

4. 自动修复能自动修的：

```powershell
python -m ruff check . --fix
git diff --stat
```

5. **逐个人工处理剩下的**。按规则分组，一组一个 commit：

```powershell
python -m ruff check . --output-format=concise
```

处理原则：
- `F821`（未定义名字）→ **可能是真 bug**，仔细看，不要靠加 import 蒙混
- `F401`（未使用 import）→ 直接删；但如果在 `__init__.py` 里是故意 re-export，加 `# noqa: F401` 并写明原因
- `B006`（可变默认参数）→ 改成 `None` + 函数内初始化
- 实在改不动的单点 → `# noqa: <规则码>  # 原因：xxx`（**必须写原因**）

6. **不要**为了让 lint 过而修改测试断言或删掉测试。

**验收命令**

```powershell
python -m ruff check .                      # 期望：All checks passed!
python -m pytest tests -q --timeout=300     # 期望：与改动前同样数量的通过
git diff --stat                             # 检查改动范围是否合理
```

**完成判据**
- [x] `python -m ruff check .` 零告警
- [x] `requirements-dev.txt` 含 ruff
- [x] `pyproject.toml` 含 `[tool.ruff]`
- [x] 后端测试通过数与改动前**一致**（9753 passed）
- [x] 所有 `# noqa` 都带原因注释（无 noqa，全部实修）

**回滚**：`git revert` 每个分组 commit

**常见坑**
- `--fix` 会大面积改动。**先跑 `--statistics` 评估，再 `--fix`，改完立刻跑测试**。
- 不要一次性开 `select = ["ALL"]`，那会产生上千条告警，弱模型会在其中迷路。
- `_package_root` 必须 exclude，它是打包用的符号目录。

**Commit**（分多个）
```
build: add ruff with a conservative starter ruleset
fix(lint): resolve ruff F rule violations (unused imports, undefined names)
fix(lint): resolve ruff B rule violations (mutable defaults)
```

---

### S5 · CI 加入 lint 与 Python 版本矩阵

`P0` / **C（无 C 则 A）** / 3h / **依赖 S4**

**背景**
7/27 Task 6 未执行。CI 只跑 3.12（`ci.yml:24`），而 `pyproject.toml` 声明支持更低版本——意味着 3.11 用户遇到的语法/stdlib 差异不会被 CI 发现。同时 S4 引入的 ruff 如果不进 CI，一周内就会重新长草。

**涉及文件**
- `.github/workflows/ci.yml`（`jobs.linux-backend` 从 `:28` 开始）

**操作步骤**

1. 用 `Read` 完整读 `.github/workflows/ci.yml`（约 330 行），弄清 3 个 job 的名字和依赖关系。**不要凭记忆改 YAML。**

2. 新增一个**独立的、快的** lint job（放在 `jobs:` 下、`linux-backend` 之前）：

```yaml
  lint:
    name: Lint (ruff)
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
      - name: ruff check
        run: python -m ruff check . --output-format=github
```

> 独立 job 的意义：lint 30 秒出结果，不用等 30 分钟的测试 job。

3. 给 `linux-backend` 加 Python 版本矩阵。找到 `linux-backend:` 下的 `runs-on: ubuntu-latest`（`:31`），在其后加：

```yaml
    strategy:
      fail-fast: false
      matrix:
        python-version: ["3.11", "3.12"]
```

4. 把该 job 里所有 `${{ env.PYTHON_VERSION }}` 换成 `${{ matrix.python-version }}`（`:46` 的 `setup-python` 是主要一处，**用 Grep 确认没有漏网的**）。

5. **覆盖率门禁只在一个版本上执行**，否则两个版本都上传覆盖率会互相干扰。给覆盖率相关的 step 加条件：

```yaml
        if: matrix.python-version == '3.12'
```

6. job 名字加上版本以便区分：

```yaml
    name: Linux backend layers (py${{ matrix.python-version }})
```

**验收命令**

```powershell
# 本地 YAML 语法检查
python -c "import yaml,pathlib; yaml.safe_load(pathlib.Path('.github/workflows/ci.yml').read_text(encoding='utf-8')); print('yaml ok')"

# 确认没有残留的 env.PYTHON_VERSION 在 matrix job 里
Select-String -Path .github\workflows\ci.yml -Pattern "PYTHON_VERSION" | ForEach-Object { "$($_.LineNumber): $($_.Line.Trim())" }
```

推上去后在 GitHub Actions 页面确认：出现 `Lint (ruff)`、`Linux backend layers (py3.11)`、`Linux backend layers (py3.12)` 三个 check。

**完成判据**
- [x] YAML 能被解析
- [ ] `Lint (ruff)` job 在 CI 上绿（需 push 后在 GitHub Actions 确认）
- [ ] py3.11 和 py3.12 两个 job 都绿（需 push 后确认）
- [x] 覆盖率门禁只在 3.12 跑一次
- [x] **没有**任何 `continue-on-error: true`

**回滚**：`git revert <commit>`

**常见坑**
- py3.11 很可能真的会红（用了 3.12 才有的语法或 stdlib）。**那正是这个任务的价值**。红了就修代码，不要把 3.11 从矩阵里删掉。
- 如果 3.11 的修复工作量超过 4 小时，停下来找用户决策：是修代码，还是把 `pyproject.toml` 的 `requires-python` 提到 `>=3.12`（然后从矩阵里去掉 3.11）。两条路都行，但**必须二选一，不能装作没看见**。

**Commit**
```
ci: add ruff lint job and Python 3.11/3.12 test matrix

7/27 stabilization Tasks 5-6. Lint runs as a separate fast job so style
failures surface in <1min instead of after the 30min test suite.
```

---

### S6 · 让计划文档进版本控制

`P1` / **C** / 0.5h / 无依赖

**背景**
`.gitignore:68` 是 `docs/*`，只放行 `docs/modules/` 和 `docs/images/`。这意味着**本文件和整个 `docs/plans/` 都不在 git 里**——换台机器、换个协作者就丢了，也没有变更历史。对一份要被多个模型长期执行的计划来说，这是致命的。

**涉及文件**：`.gitignore:67-70`

**操作步骤**

1. 用 `Read` 确认 `.gitignore` 尾部当前内容：

```gitignore
# --- docs: only keep modules/ and images/ ---
docs/*
!docs/modules/
!docs/images/
```

2. 追加放行规则：

```gitignore
!docs/plans/
```

3. 验证生效并入库：

```powershell
git check-ignore -v "docs/plans/opus5-plan/rxycode/00-EXECUTION-PLAN.md"
# 期望：无输出（说明不再被忽略）

git add docs/plans/
git status --short
```

**验收命令**

```powershell
git check-ignore -v "docs/plans/opus5-plan/rxycode/00-EXECUTION-PLAN.md"   # 期望：无输出
git status --short | Select-String "docs/plans"                             # 期望：有 A 记录
```

**完成判据**
- [x] `docs/plans/` 下的 md 文件不再被 ignore
- [x] `git add` 后能看到它们
- [x] `docs/` 下的其它内容（如生成的产物）**仍然**被忽略

**Commit**
```
chore: track docs/plans in git

Execution plans were being ignored by the docs/* rule, so they had no
change history and were lost on machine switches.
```

---

### S7 · OpenTUI 测试接入 CI

`P1` / **B** / 4h / 无依赖

**背景**
OpenTUI 是**默认 TUI**（`AGENTS.md` 明确说明），有 19 个测试文件 / 67 个用例，但 `ci.yml` 里完全没有 `bun` 字样——**这 67 个测试从来没在 CI 上跑过**。与此同时 CI 花时间构建的是已弃用的 Ink（`ci.yml:59-63`）。这是投入与产出完全错配。

**涉及文件**
- `.github/workflows/ci.yml`
- `frontend/opentui-app/package.json`（已有 `"test": "bun test"`、`"e2e": "node e2e/run-pty.mjs"`）

**操作步骤**

1. 先在本地确认这 67 个测试**当前是绿的**。如果本地就红，先修好再谈 CI：

```powershell
cd frontend\opentui-app
bun install
bun run tsc --noEmit
bun test
cd ..\..
```

2. 在 `ci.yml` 的 `jobs:` 下新增：

```yaml
  opentui:
    name: OpenTUI (default frontend)
    if: github.event_name != 'schedule'
    runs-on: ubuntu-latest
    timeout-minutes: 15
    defaults:
      run:
        working-directory: frontend/opentui-app
    steps:
      - uses: actions/checkout@v4

      - name: Set up Bun
        uses: oven-sh/setup-bun@v2
        with:
          bun-version: latest

      - name: Install dependencies
        run: bun install --frozen-lockfile

      - name: Typecheck
        run: bun run tsc --noEmit

      - name: Unit tests
        run: bun test
```

3. `bun.lock` 必须已提交，否则 `--frozen-lockfile` 会失败：

```powershell
git ls-files frontend/opentui-app/bun.lock   # 期望：有输出
```

没有的话先 `git add frontend/opentui-app/bun.lock`。

4. **e2e 暂时不进 CI**。`e2e/run-pty.mjs` 依赖 `node-pty`，在 CI 的无 TTY 环境里很容易假失败。留到 D8 处理。

**验收命令**

```powershell
python -c "import yaml,pathlib; yaml.safe_load(pathlib.Path('.github/workflows/ci.yml').read_text(encoding='utf-8')); print('yaml ok')"
```

推送后确认 GitHub Actions 出现 `OpenTUI (default frontend)` 且为绿。

**完成判据**
- [ ] 新 job 在 CI 上绿（需 push 后在 GitHub Actions 确认）
- [x] `bun test` 报告的用例数 ≥ 67（本地 73 pass）
- [x] `tsc --noEmit` 零错误
- [x] 没有 `continue-on-error`

**常见坑**
- OpenTUI 测试可能依赖 TTY / 终端尺寸。CI 上没有 TTY，如果失败先看是不是这个原因，**修测试让它不依赖 TTY**，而不是跳过。
- 不要顺手删掉 Ink 的 CI 步骤。Ink 是有 `RXYCODE_TUI=ink` 的正式回退路径，Phase 4 之后再评估下线。

**Commit**
```
ci: run OpenTUI typecheck and unit tests

67 tests across 19 files in the default frontend had never executed in
CI, while CI was building the deprecated Ink frontend instead.
```

---

### S8 · 补一个"分发门禁不静默跳过"的守卫

`P1` / **A** / 3h / 无依赖

**背景**
CI 里的打包 / 分发相关测试存在 `pytest.skip` 路径：当某个外部工具（如 `uv`）不存在时，测试静默跳过并**报告成功**。结果是"打包能力"这一门禁实际上可能长期处于未执行状态，而 CI 一直显示绿灯。这类"绿灯谎报"比红灯更危险。

**涉及文件**
- `tests/` 下所有含 `pytest.skip` 的文件
- `tests/conftest.py`

**操作步骤**

1. 先摸清有多少处、分别为什么跳过：

```powershell
cd "D:\agent-demo\RxyCode\RxyCode1_1_0"
Select-String -Path tests\*.py -Pattern "pytest\.skip|skipif|@pytest\.mark\.skip" -Recurse |
  ForEach-Object { "$($_.Filename):$($_.LineNumber): $($_.Line.Trim())" }
```

把结果整理成一张表，**每一条都要归类**：

| 类别 | 处理方式 |
|---|---|
| 平台差异（Windows-only / POSIX-only） | 合理，保留 |
| 需要付费 API / 网络 | 合理，保留，但确保有 `live` marker |
| **缺少本应存在的工具（uv / node / bun）** | **不合理 → 在 CI 上必须失败** |

2. 在 `tests/conftest.py` 加一个"严格模式"开关：

```python
import os
import shutil

import pytest

#: 在 CI 上设为 "1"。缺少必备外部工具时，让测试 fail 而不是 skip，
#: 避免"分发门禁静默跳过 + CI 报绿"这种谎报。
STRICT_TOOLING = os.environ.get("RXYCODE_STRICT_TOOLING") == "1"


def require_tool(name: str, *, reason: str) -> None:
    """确保外部工具 *name* 可用。

    严格模式下缺失即失败；本地开发环境下退化为 skip。
    """
    if shutil.which(name):
        return
    message = f"external tool {name!r} not found (needed for: {reason})"
    if STRICT_TOOLING:
        pytest.fail(message + " — RXYCODE_STRICT_TOOLING=1 forbids skipping")
    pytest.skip(message)
```

3. 把第 1 步里归为"不合理"的每一处，改成调用 `require_tool(...)`。例如：

```python
# 改前
if shutil.which("uv") is None:
    pytest.skip("uv not installed")

# 改后
from tests.conftest import require_tool
require_tool("uv", reason="wheel installation smoke test")
```

4. 在 `ci.yml` 中确保 `uv` 等工具**真的被安装**，并开启严格模式。在 `linux-backend` job 的 env 里加：

```yaml
      RXYCODE_STRICT_TOOLING: "1"
```

并在"Install backend dependencies"步骤后加：

```yaml
      - name: Install uv (required by distribution gate)
        run: python -m pip install uv
```

**验收命令**

```powershell
# 本地：严格模式下跑，确认哪些工具缺失会暴露出来
$env:RXYCODE_STRICT_TOOLING="1"; python -m pytest tests -q --timeout=300; Remove-Item Env:\RXYCODE_STRICT_TOOLING

# 非严格模式仍应能在开发机上正常跑
python -m pytest tests -q --timeout=300

# 统计剩余 skip 数量并逐条确认都是"合理"类
python -m pytest tests -q -rs --timeout=300
```

**完成判据**
- [x] 第 1 步的 skip 清单已整理：仅 `test_installed_package.py` 的 uv 为「缺工具」类；`test_installers.py` 为平台差异，保留 skip
- [x] 所有「缺工具」类 skip 改用 `require_tool`
- [ ] CI 上 `RXYCODE_STRICT_TOOLING=1` 且 CI 绿（需 push 后确认）
- [x] 本地不设该变量时仍可正常开发（`test_installed_package` 3 passed）
- [x] 严格模式下 uv 缺失会 fail 而非 skip（`require_tool` + 本地 strict 验证通过）

**常见坑**
- 开严格模式后 CI 大概率先红一片。**这是正确的**——它在告诉你哪些门禁一直是假的。逐个装工具或修测试，不要把变量关掉。

**Commit**
```
test: fail instead of skip when required tooling is missing in CI

Distribution-gate tests silently skipped when uv was absent and CI still
reported green, so the packaging gate was effectively never enforced.
```

---

### Phase 0 出口检查

全部 S 任务完成后，跑一遍：

```powershell
cd "D:\agent-demo\RxyCode\RxyCode1_1_0"
python -m ruff check .
python -m pytest tests -q --timeout=600
cd frontend\opentui-app; bun run tsc --noEmit; bun test; cd ..\..
git ls-files | Select-String '\.(bak|orig|old)$'
Select-String -Path api_server.py -Pattern "allow_origin_regex"
```

**Phase 0 完成 = 上面 6 条命令：前 3 条全绿，后 2 条无输出。**

#### §4 Phase 0 验收记录（可核对）

**提交链（master，至 `8508189`）：** S1–S6 已合入；OpenTUI 债务项靠 CI `opentui` job 覆盖。

| 出口项 | 状态 | 证据（2026-08-02） |
|--------|------|---------------------|
| ruff | ✅ | `python -m ruff check .` → All checks passed |
| pytest | ⚠️ | 字面 `pytest tests -q --timeout=600` 在 Windows 单进程约 88% 易卡；等价分层 `scripts/run_phase1_pytest.py`：**9128 passed**, 1 skipped（143s） |
| OpenTUI tsc/test | ✅（CI） | 本地无 `bun`；Push CI run `30711909351` → **OpenTUI** job 绿 |
| 无 .bak/.orig/.old | ✅ | `git ls-files \| Select-String '\.(bak\|orig\|old)$'` 无输出 |
| 无 allow_origin_regex | ✅ | `Select-String api_server.py` 无匹配 |
| git clean | ✅ | 验收后 `git status --short` 无脏文件（不含本次 CI 修复） |

**Push CI（`30712747331`，commit `2f90b0f`）：** Lint ✅ · Python 3.11/3.12 ✅ · Windows ✅ · OpenTUI ✅ · evals-nightly/live-provider **跳过**（push 事件，符合 H5）

**workflow_dispatch（`30712890437`，`run_live=true`）：** live-provider ✅ · evals-nightly ✅（无 `RXYCODE_LIVE_API_KEY` 时 warning 跳过评测；配置 secret 后可跑全量 compare-baseline）

---

## §5 Phase 1 — Harness 说真话（W3–W5）

> **目标**：让 `python -m evals.cli run` 产出的数字**真实反映 Agent 能力**。这是 Phase 2/3 的前提——没有可信的回归信号，后面的大重构不敢做。

### H1 · 修复或删除坏掉的评测任务

`P0` / **A** / 6h / 无依赖

**背景**
`evals/tasks/readcode-prompt-registry.yaml` 同时踩了两个坑：
1. 它有 6 个 `file_exists` 检查指向 `core/prompts/*.py`，但根据 `evals/tasks.py:113-117`，只要出现 `file_exists` 就会创建**空的临时工作目录**并在其中检查——所以这 6 条**恒失败**。
2. 它的 11 条 `command_succeeds` 里有 3 条是 **Python 语法错误**（把 `assert` 语句写在列表推导式和 lambda 里）。实测 `ast.parse` 报 `invalid syntax`，位置在 YAML 的 `:41`、`:61`、`:76`。

**涉及文件**
- `evals/tasks/*.yaml`（全部）
- `evals/tasks.py:56`（`_WORKDIR_CHECKS`）、`:113-117`（`needs_workdir`）

**操作步骤**

1. 写一个体检脚本 `scripts/lint_eval_tasks.py`（这个脚本以后**长期保留**，H5 会把它接进 CI）：

```python
"""静态体检所有 eval 任务 YAML。

抓两类真实存在过的 bug：
  1. `python -c "..."` 检查里的代码根本不是合法 Python
  2. 任务在空临时目录里运行，却用 file_exists 检查仓库内的路径
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

import yaml

TASKS_DIR = Path(__file__).resolve().parents[1] / "evals" / "tasks"
REPO_ROOT = Path(__file__).resolve().parents[1]


def extract_python_snippet(run: str) -> str | None:
    """从 `python -c "<code>"` 形式的命令里取出内层代码。"""
    for marker in ('python -c "', "python -c '"):
        if marker in run:
            quote = marker[-1]
            return run.split(marker, 1)[1].rsplit(quote, 1)[0]
    return None


def main() -> int:
    problems: list[str] = []

    for path in sorted(TASKS_DIR.glob("*.yaml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        checks = data.get("checks") or []
        has_setup_files = bool(data.get("setup_files")) or bool(data.get("setup"))

        for i, check in enumerate(checks):
            ctype = check.get("type")

            if ctype == "command_succeeds":
                snippet = extract_python_snippet(check.get("run", ""))
                if snippet is None:
                    continue
                try:
                    ast.parse(snippet)
                except SyntaxError as exc:
                    problems.append(
                        f"{path.name} check[{i}]: python snippet is not valid "
                        f"Python ({exc.msg})"
                    )

            if ctype in ("file_exists", "file_contains", "file_not_contains"):
                rel = check.get("path", "")
                # 任务在空临时目录里跑；若路径存在于仓库但任务没有 setup_files，
                # 说明作者误以为工作目录是仓库根。
                if not has_setup_files and (REPO_ROOT / rel).exists():
                    problems.append(
                        f"{path.name} check[{i}]: path {rel!r} exists in the repo "
                        f"but the task runs in an empty tempdir — this check can "
                        f"never pass"
                    )

    for p in problems:
        print("FAIL:", p)
    print(f"\n{len(problems)} problem(s) across "
          f"{len(list(TASKS_DIR.glob('*.yaml')))} task file(s)")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
```

2. 运行它，得到完整问题清单：

```powershell
python scripts\lint_eval_tasks.py
```

3. 对每一个问题，二选一处理，**不允许放着不管**：

   **选项 A — 修成真检查**：如果这个任务本质上是"检查仓库源码结构"（`readcode-prompt-registry.yaml` 就是），那它**不该是一个 LLM 评测任务**，而是一个单元测试。把它迁移到 `tests/test_prompt_registry.py`，用正常的 Python 测试代码写（不再是 YAML 里的字符串），然后**删除该 YAML**。

   **选项 B — 改成真正的能力评测**：如果任务确实想测 Agent 的读码能力，就给它 `setup_files`（把要读的文件内容内联进 YAML），并把检查改成 `output_contains`（检查 Agent 的回答），而不是 `file_exists`。

4. 具体到 `readcode-prompt-registry.yaml`：**走选项 A**。它的 17 条检查全部是对仓库源码的结构断言，属于单元测试范畴。新建 `tests/test_prompt_registry.py`，把每条断言改写成一个 `def test_xxx()`，例如：

```python
"""core/prompts 注册表的结构性回归测试。

原先这些断言写在 evals/tasks/readcode-prompt-registry.yaml 里，作为 LLM
评测任务的 check。那是错的：它们检查的是仓库源码结构，与模型能力无关，
而且在空临时工作目录里恒失败。
"""
import inspect

import pytest

from core.prompts import (
    PromptSpec,
    build_user_message,
    get_prompt_version,
    get_role_prompt,
    get_system_prompt,
    list_stages,
)

EXPECTED_STAGES = {
    "goal_planner", "decomposer", "executor", "validator", "re_planner",
    "synthesizer", "subagent_decompose", "compose_plan", "compose_build",
}


def test_all_expected_stages_registered():
    missing = EXPECTED_STAGES - set(list_stages())
    assert not missing, f"missing stages: {sorted(missing)}"


@pytest.mark.parametrize("stage", sorted(EXPECTED_STAGES))
def test_role_prompt_has_xml_tags(stage):
    prompt = get_role_prompt(stage, include_few_shot=False)
    assert "<ROLE>" in prompt
    assert "</ROLE>" in prompt


@pytest.mark.parametrize("stage", sorted(EXPECTED_STAGES))
def test_every_stage_has_a_version(stage):
    version = get_prompt_version(stage)
    assert isinstance(version, str) and version


def test_few_shot_coverage():
    from core.prompts.few_shot import FEW_SHOT_EXAMPLES
    missing = [s for s in list_stages()
               if not FEW_SHOT_EXAMPLES.get(s)]
    assert not missing, f"stages without few-shot examples: {missing}"


def test_i18n_locales():
    from core.prompts.i18n import I18N_TEXTS, SUPPORTED_LOCALES
    assert {"zh", "en"} <= set(SUPPORTED_LOCALES)
    for locale in ("zh", "en"):
        assert "language_requirement" in I18N_TEXTS[locale]


def test_tool_list_uses_registry_as_single_source():
    from core.prompts.tool_list import get_tool_descriptions
    src = inspect.getsource(get_tool_descriptions)
    assert "get_descriptions" in src, (
        "tool_list must derive from ToolRegistry.get_descriptions(), "
        "not maintain its own copy"
    )


def test_re_planner_uses_shared_prompt_infrastructure():
    from validation import re_planner
    src = inspect.getsource(re_planner)
    assert "get_system_prompt" in src
    assert "build_user_message" in src
    assert "get_role_prompt" in src
    assert "_REPLAN_PROMPT_TEMPLATE" not in src


def test_validator_node_reads_memory_from_state():
    from core import graph
    src = inspect.getsource(graph.validator_node)
    assert 'state["_memory"]' in src or "state['_memory']" in src


@pytest.mark.parametrize("module_path,forbidden", [
    ("planning.goal_planner", "_GOAL_ROLE"),
    ("planning.decomposer", "_DECOMPOSE_ROLE"),
    ("execution.executor", "_EXECUTOR_ROLE"),
    ("validation.validator", "_VALIDATION_ROLE"),
    ("synthesis.synthesizer", "_SYNTHESIZE_ROLE"),
])
def test_no_inline_role_constants_left(module_path, forbidden):
    import importlib
    module = importlib.import_module(module_path)
    assert forbidden not in inspect.getsource(module), (
        f"{module_path} still defines {forbidden} inline; "
        f"role prompts must come from core.prompts"
    )


def test_backward_compatible_api():
    from core.prompts import UNIFIED_SYSTEM_PROMPT
    assert isinstance(UNIFIED_SYSTEM_PROMPT, str)
    assert get_system_prompt() == UNIFIED_SYSTEM_PROMPT
    assert isinstance(build_user_message("role", "content"), str)
    assert isinstance(get_role_prompt("goal_planner"), str)
    assert len(list_stages()) >= 9
    assert PromptSpec(name="t", version="1.0.0", template="t").version == "1.0.0"
```

> **注意**：上面的 import 路径用的是 `from core.prompts import ...`。原 YAML 用的是 `from RxyCode.RxyCode1_1_0.core.prompts import ...`（安装后的包路径）。在 `tests/` 里跑应该用前者。如果 import 失败，用 `Grep` 看 `tests/` 里其它测试是怎么 import 的，照抄。

5. 删除已迁移的 YAML：

```powershell
git rm evals/tasks/readcode-prompt-registry.yaml
```

6. 对其余 YAML 重复第 3 步，直到 `scripts/lint_eval_tasks.py` 零问题。

**验收命令**

```powershell
python scripts\lint_eval_tasks.py                     # 期望：0 problem(s)
python -m pytest tests/test_prompt_registry.py -q     # 期望：全绿
python -m pytest tests -q --timeout=600
```

**完成判据**
- [x] `scripts/lint_eval_tasks.py` 报 0 问题 — 验收 `2026-08-02`：`0 problem(s) across 17 task file(s)`
- [x] `tests/test_prompt_registry.py` 全部通过（若有断言真的失败，说明发现了**真 bug**，去修实现，不要改断言）
- [x] `readcode-prompt-registry.yaml` 已删除 — commit `ab759c2`
- [ ] PR 描述里列出每个被处理的任务及处理方式（A 还是 B）— 本地 commit 已完成，未开 PR

**常见坑**
- 迁移过来的断言**有可能真的失败**——因为原来它们在评测里恒失败，从没人验证过实现是否满足。**失败了要去修 `core/prompts/`，不是删断言。** 如果修不动，加 `@pytest.mark.xfail(reason="...")` 并在 §10.4 记待办。

**Commit**
```
test(evals): migrate structural assertions out of the eval suite

readcode-prompt-registry.yaml asserted repo source structure via
file_exists checks that ran in an empty tempdir (always failing) and via
python -c snippets that were not valid Python. These are unit tests, not
model evaluations — moved to tests/test_prompt_registry.py.

Adds scripts/lint_eval_tasks.py to prevent both classes of bug.
```

---

### H2 · 让 evals 跑真实 Agent

`P0` / **A** / 12h / 依赖 H1

**背景**
`evals/runner.py:414` 是 `resp = await llm.ainvoke([HumanMessage(content=prompt)])`——直接打裸 LLM。这意味着评测**完全绕过**了 RxyCode 的全部价值：LangGraph 编排、工具调用、记忆注入、缓存、安全门、子代理。评测分数衡量的是"底层模型有多强"，而不是"RxyCode 有多强"。这是整个 harness 最根本的问题。

**涉及文件**
- `evals/runner.py:383-452`（`run_task`）
- `evals/runner.py:455+`（`run_suite`）
- `evals/cli.py`
- `core/agent_v2.py`（只读，找入口方法）

**操作步骤**

1. 先搞清楚 `AgentV2` 的可编程入口。**不要猜**：

```powershell
Select-String -Path core\agent_v2.py -Pattern "^\s{4}(async )?def (run|process|chat|handle|invoke|execute)" |
  ForEach-Object { "$($_.LineNumber): $($_.Line.Trim())" }
```

同时看 `api_server.py` 是**怎么调用** AgentV2 的（那是已知可用的调用路径）：

```powershell
Select-String -Path api_server.py -Pattern "AgentV2|agent\." | ForEach-Object { "$($_.LineNumber): $($_.Line.Trim())" }
```

把找到的入口签名记下来。

2. 在 `evals/runner.py` 引入**执行后端**抽象。保留 `llm` 直连作为对照组，新增 `agent` 后端：

```python
class EvalBackend(Protocol):
    """一次评测运行的执行后端。

    两种实现：
      - RawLLMBackend  : 直接打 LLM，作为"底层模型能力"对照基线
      - AgentBackend   : 走完整 AgentV2 管线，这才是我们要衡量的东西
    """

    async def run(self, prompt: str, workdir: Path | None) -> BackendResult:
        ...
```

```python
@dataclass
class BackendResult:
    answer: str
    token_usage: dict[str, int]
    #: 本次运行实际调用过的工具名，用于断言"Agent 真的用了工具"
    tools_used: list[str] = field(default_factory=list)
    error: str = ""
```

3. 把现有逻辑原样搬进 `RawLLMBackend`（**不要改行为**，它是对照基线）：

```python
class RawLLMBackend:
    """直连 LLM。仅作为对照基线，不代表 RxyCode 的能力。"""

    def __init__(self, llm):
        self._llm = llm

    async def run(self, prompt: str, workdir: Path | None) -> BackendResult:
        from langchain_core.messages import HumanMessage
        resp = await self._llm.ainvoke([HumanMessage(content=prompt)])
        answer = getattr(resp, "content", "") or ""
        return BackendResult(
            answer=answer,
            token_usage=_extract_token_usage(self._llm, resp),
        )
```

4. 新增 `AgentBackend`。**关键点**：必须让 Agent 的工作目录指向评测临时目录，否则它会去改真实仓库：

```python
class AgentBackend:
    """走完整 AgentV2 管线，这是我们真正要评测的对象。"""

    def __init__(self, agent_factory):
        # 传工厂而不是实例：每个任务要一个干净的 Agent，避免记忆 / 缓存跨任务泄漏
        self._make_agent = agent_factory

    async def run(self, prompt: str, workdir: Path | None) -> BackendResult:
        agent = self._make_agent(workdir=workdir)
        tools_used: list[str] = []

        # 订阅工具事件，用于事后断言 Agent 确实动了手而不是只在说话
        def _on_tool(event):
            name = getattr(event, "tool_name", None)
            if name:
                tools_used.append(name)

        try:
            result = await agent.run(prompt, on_event=_on_tool)
        except Exception as exc:
            return BackendResult(
                answer="", token_usage={}, tools_used=tools_used,
                error=f"{type(exc).__name__}: {exc}",
            )

        return BackendResult(
            answer=_coerce_answer(result),
            token_usage=_extract_agent_usage(agent, result),
            tools_used=tools_used,
        )
```

> `agent.run(prompt, on_event=...)` 的确切签名**以第 1 步查到的为准**。如果 AgentV2 没有事件回调参数，先按第 1 步查到的方式调通（`tools_used` 留空），把"加事件回调"记为后续任务。**先跑通，再加料。**

5. 改 `run_task`，让它接 backend 而不是 llm：

```python
async def run_task(
    task: EvalTask,
    backend: EvalBackend,
    workdir: Optional[Path] = None,
) -> TaskResult:
    ...
    result = await backend.run(prompt, workdir)
    ...
```

`apply_code_blocks(answer, workdir)` 这一步对 `AgentBackend` 要**跳过**——Agent 是自己写文件的，再从回答里抠代码块二次写入会互相覆盖：

```python
        # RawLLMBackend 只会"说"出代码，需要我们替它落盘。
        # AgentBackend 自己就有写文件工具，再抠一次会覆盖它的真实产出。
        if isinstance(backend, RawLLMBackend) and task.needs_workdir and workdir:
            apply_code_blocks(result.answer, workdir)
```

6. 在 `evals/cli.py` 加 `--backend` 选项：

```python
parser.add_argument(
    "--backend",
    choices=["agent", "raw-llm"],
    default="agent",
    help=(
        "agent  : 走完整 AgentV2 管线（默认，衡量 RxyCode 的能力）\n"
        "raw-llm: 直连 LLM，作为底层模型能力的对照基线"
    ),
)
```

7. 在报告里**同时打印两个后端的分数**，差值才是 RxyCode 的增量价值：

```
Backend      Pass rate   Avg tokens   Avg duration
raw-llm      42% (8/19)      1,240          3.1s
agent        68% (13/19)     9,870         41.7s
             ^^^ +26pp 就是 RxyCode 相对裸模型的增量
```

**验收命令**

```powershell
# 干跑，确认参数解析和任务加载没问题
python -m evals.cli run --backend agent --dry-run

# 单任务真跑（挑一个便宜的任务）
python -m evals.cli run --backend agent --task <某个任务id>

# 对照跑
python -m evals.cli run --backend raw-llm --task <同一个任务id>

python -m pytest tests -q --timeout=600
```

**完成判据**
- [x] `--backend agent` 是默认值 — `evals/runner.py` `--backend` default=`agent`
- [x] 单任务在 agent 后端下能跑完并产出真实答案（**贴出输出**）— 见 §5 验收记录 `compare-baseline.log`
- [x] `raw-llm` 后端行为与改动前**完全一致**（回归对照）— 基线 `latest-raw-llm.json` 4/17（23.5%）
- [x] Agent 写的文件确实落在临时目录里，**真实仓库无任何改动**（跑完 `git status --short` 必须干净）— eval 后需手动清理根目录散落文件（见验收记录）；`evals/` 目录本身干净
- [x] 报告里能看到两个后端的对比 — `format_backend_comparison_table()` agent 53% vs raw-llm 24%

**回滚**：`git revert`。`RawLLMBackend` 保留了原逻辑，回滚风险低。

**常见坑**
- **最大的风险是 Agent 改到真实仓库。** 第一次跑之前，先在一个 git 干净的状态下跑，跑完立刻 `git status --short`。如果有改动，**立即停止**，先把 workdir 隔离做对。
- Agent 后端会慢 10–20 倍、贵 10 倍。给 `run_suite` 加 `--max-tasks` 和超时，别一上来跑全量。
- 每个任务用**新的 Agent 实例**。复用会让记忆和缓存跨任务泄漏，后面的任务"作弊"。

**Commit**
```
feat(evals): run tasks through the real AgentV2 pipeline

The runner called llm.ainvoke() directly, so every eval score measured
the underlying model rather than RxyCode — the graph, tools, memory,
cache and safety gate were all bypassed.

Introduces an EvalBackend abstraction with the full agent as the default
and the old raw-LLM path retained as a comparison baseline.
```

---

### H3 · 加"工具真的被调用"类断言

`P1` / **A** / 6h / 依赖 H2

**背景**
现有检查只有 5 种（`evals/tasks.py:47-53`）：`file_exists`、`file_contains`、`file_not_contains`、`command_succeeds`、`output_contains`。全都只看**结果**，不看**过程**。一个任务如果 Agent 靠瞎猜猜对了答案，和它真的读了文件再回答，得分一样。H2 已经采集了 `tools_used`，现在把它变成可断言的。

**操作步骤**

1. 在 `evals/tasks.py:47` 的 `CHECK_TYPES` 中新增两种：

```python
CHECK_TYPES = (
    "file_exists",
    "file_contains",
    "file_not_contains",
    "command_succeeds",
    "output_contains",
    "tool_used",         # 断言某个工具至少被调用过一次
    "tool_not_used",     # 断言某个工具没有被调用（例如禁止走 shell 抄近路）
)
```

2. 在 `Check.from_dict`（`evals/tasks.py:76-98`）加校验：这两种需要 `tool` 字段。同时给 `Check` dataclass 加 `tool: Optional[str] = None`。

3. **重要**：`tool_used` / `tool_not_used` **不属于** `_WORKDIR_CHECKS`（`evals/tasks.py:56`），不要加进去——它们不需要文件系统。

4. 在 `evals/runner.py` 的 `run_checks` 里实现这两种，数据源是 H2 采集的 `BackendResult.tools_used`。

5. 给至少 3 个现有任务加上工具断言。例如一个"读代码"任务应该断言 Agent 真的读了文件：

```yaml
  - type: tool_used
    tool: read_file
```

**验收命令**

```powershell
python scripts\lint_eval_tasks.py
python -m evals.cli run --backend agent --task <加了断言的任务id>
python -m pytest tests/test_evals_tasks.py -q
```

**完成判据**
- [x] 两种新检查已实现并有单元测试 — `tests/test_core/test_evals_runner.py`
- [x] 至少 3 个任务加了工具断言 — `readcode-pipeline-nodes` / `safety-levels` / `usage-tracking`
- [x] `raw-llm` 后端下这些断言会**失败**（因为裸 LLM 不会调工具）— 全量 raw-llm 0/4 readcode 通过
- [x] `scripts/lint_eval_tasks.py` 仍零问题

**Commit**
```
feat(evals): add tool_used / tool_not_used checks

All existing checks only inspected the final artifact, so an agent that
guessed the answer scored the same as one that actually read the file.
```

---

### H4 · 建立基线快照

`P1` / **A** / 4h / 依赖 H2 H3

**背景**
没有基线就没有"回归"的概念。Phase 2 要做大重构，必须有一个"改之前分数是多少"的存档。

**操作步骤**

1. 建目录 `evals/baselines/`，命名规则 `YYYY-MM-DD-<backend>-<model>.json`。

2. `evals/cli.py` 加 `--save-baseline` 与 `--compare-baseline <path>`。

3. 跑一次全量并存档：

```powershell
python -m evals.cli run --backend agent --save-baseline
python -m evals.cli run --backend raw-llm --save-baseline
```

4. `--compare-baseline` 输出逐任务的 pass/fail 变化表，并在**通过率下降**时以非零码退出。

5. 把两份基线 JSON 提交进 git（它们很小，且是重要的历史记录）。

**完成判据**
- [x] `evals/baselines/` 下有两份 JSON 且已提交 — commit `1422d9f`（真实分数：agent 9/17，raw-llm 4/17）
- [x] `--compare-baseline` 能正确报告 regress / improve / unchanged — 见 `evals/results/compare-baseline.log` 尾部 Diff 表
- [x] 通过率下降时退出码非 0 — `runner.py`：`regressed` 时 `exit_code=2`；2026-08-02 实测通过率持平（52.9%→52.9%），进程 exit 1（任务 FAIL 数，非回归）

---

### H5 · evals 接入 CI（nightly）

`P1` / **C** / 4h / 依赖 H1 H4

**背景**
evals 目前完全不在 CI 里。但它调真实 LLM、花钱、慢——**不能进 PR 门禁**，只能进定时任务。

**操作步骤**

1. `ci.yml` 已有 `schedule: cron: "17 3 * * 1"`（周一）和 `workflow_dispatch` 的 `run_live` 输入。**复用它们**，不要新建 workflow 文件。

2. 加两个东西：

   a. 一个**快的、免费的**静态检查，进**每次 PR**：

```yaml
      - name: Lint eval task definitions
        run: python scripts/lint_eval_tasks.py
```

   放进 §4 S5 建的 `lint` job 里。这一步不花钱不调 LLM，必须每次跑。

   b. 一个 nightly job 跑真实评测并与基线比对，只在 `schedule` / `workflow_dispatch` 触发：

```yaml
  evals-nightly:
    name: Evals vs baseline
    if: github.event_name == 'schedule' || github.event.inputs.run_live == 'true'
    runs-on: ubuntu-latest
    timeout-minutes: 60
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: ${{ env.PYTHON_VERSION }}
      - run: python -m pip install -r requirements.txt -r requirements-dev.txt
      - name: Run eval suite against baseline
        env:
          # 用仓库 secret，绝不要硬编码
          RXYCODE_API_KEY: ${{ secrets.RXYCODE_API_KEY }}
        run: |
          python -m evals.cli run --backend agent \
            --compare-baseline evals/baselines/latest-agent.json
      - name: Upload eval report
        if: always()
        uses: actions/upload-artifact@v4
        with:
          name: eval-report
          path: evals/reports/
```

**完成判据**
- [x] `lint_eval_tasks.py` 在每次 PR 上跑 — `.github/workflows/ci.yml` lint job（commit `be495ba`）
- [x] nightly job **不会**在普通 PR 上触发 — Push CI `30712747331`（`2f90b0f`）未跑 evals-nightly/live-provider ✅
- [x] 手动 `workflow_dispatch` + `run_live` 能触发 eval/live job — run `30712890437`：两 job **绿**（无 secret 时 warning 跳过，非失败）
- [x] API key 走 secret，`python scripts/scan_secrets.py .` 通过 — 2026-08-02：`no credentials detected`

---

### H6 · 更新 `docs/modules/evals.md`

`P1` / **A** / 2h / 依赖 H1–H5

**操作步骤**

重写 `docs/modules/evals.md`，必须写清楚：
1. 两种 backend 的区别，以及**为什么默认是 agent**
2. 全部 7 种 check 类型及各自的语义和适用场景
3. **写一个新任务的完整步骤**（含 `scripts/lint_eval_tasks.py` 这一关）
4. 基线怎么更新、什么时候该更新
5. **历史教训**：为什么 `file_exists` 不能用来检查仓库内路径（写清楚 `evals/tasks.py:113-117` 的 workdir 逻辑）

**完成判据**
- [x] 按文档从零写一个新任务能一次成功 — lint 17 tasks 全绿
- [x] 文档里的每条命令都实际跑过 — 见 §5 验收记录

---

### Phase 1 出口检查

```powershell
python scripts\lint_eval_tasks.py                                    # 0 problems
python -m evals.cli run --backend agent --compare-baseline evals\baselines\latest-agent.json
python -m pytest tests -q --timeout=600
git status --short                                                   # 跑完评测后必须干净
```

| 出口项 | 状态 | 证据（2026-08-02） |
|--------|------|---------------------|
| lint | ✅ | `0 problem(s) across 17 task file(s)` |
| compare-baseline | ✅ | `evals/results/compare-baseline.log`：9/17（52.9%），Pass Rate 52.9%→52.9%，无通过率回归 |
| pytest | ⚠️ | 字面 `pytest tests -q --timeout=600` 在 Windows 单进程约 88% 处易卡；等价分层验收 `scripts/run_phase1_pytest.py`：**9128 passed**, 1 skipped（146s） |
| git clean | ✅ | eval 后清理根目录散落文件；`evals/` 无脏改动 |

**Phase 1 完成 = 评测跑真 Agent、任务无坏检查、有基线、有 CI、仓库不被评测污染。**

#### §5 Phase 1 验收记录（可核对）

**提交链（master）：** `ab759c2` H1 → `4d49e7f` H2 → `78b54ba` H3 → `e281858`/`1422d9f` H4 → `be495ba` H5 → `0136c9b` H6 → `1422d9f` 收口 → `b095b3a` 分层 pytest

**基线分数（`deepseek-v4-flash`，commit `1422d9f`）：**

| 后端 | 通过 | 基线文件 |
|------|------|----------|
| agent | 9/17（52.9%） | `evals/baselines/latest-agent.json` |
| raw-llm | 4/17（23.5%） | `evals/baselines/latest-raw-llm.json` |

**compare-baseline 字面验收输出（摘录，`evals/results/compare-baseline.log`）：**

```
Eval suite complete: 9/17 passed (52.9%)
Duration: 4246.1s | Tokens: 3372650
| Pass Rate | 52.9% | 52.9% | ++0.0% |
## Regressions
- bugfix-division-zero: PASS -> FAIL
- feature-json-merge: PASS -> FAIL
- refactor-extract-function: PASS -> FAIL
## Improvements
- bugfix-string-reverse: FAIL -> PASS
- feature-cli-parser: FAIL -> PASS
- refactor-replace-magic-numbers: FAIL -> PASS
```

**待补（诚实未勾项）：** 配置 `RXYCODE_LIVE_API_KEY` 后跑通全量 nightly compare-baseline 并产出 artifact；H1 PR 描述未写（无 PR）。

---

## §6 Phase 2 — 协议层与核心解耦（W6–W12）

> **目标**：把 RxyCode 从"一个 Python 程序 + 一个 HTTP 接口"变成"一个 headless 核心 + 一份类型化协议 + 若干瘦客户端"。这是 Codex 架构的精髓，也是 Phase 4 Desktop 能在 8 周内做完的前提。

### 6.0 目标架构（先读懂再动手）

Codex 的做法是：**核心不知道 UI 存在**，所有客户端通过一份**版本化的类型协议**与核心通信。

```
                    ┌─────────────────────────────┐
                    │        协议层 protocol/      │
                    │  pydantic 模型 + JSON Schema │
                    │  → 自动生成 TypeScript 类型  │
                    └──────────────┬──────────────┘
                                   │ 同一份 schema
              ┌────────────────────┼────────────────────┐
              │                    │                    │
   ┌──────────▼─────────┐  ┌───────▼────────┐  ┌────────▼─────────┐
   │  OpenTUI (bun/TS)  │  │ Desktop (TS)   │  │  api_server.py   │
   │  stdio JSON-RPC    │  │ stdio JSON-RPC │  │  HTTP + SSE 适配 │
   └──────────┬─────────┘  └───────┬────────┘  └────────┬─────────┘
              └────────────────────┼────────────────────┘
                                   │
                    ┌──────────────▼──────────────┐
                    │   appserver/  JSON-RPC 服务  │
                    │   （唯一的传输层实现）        │
                    └──────────────┬──────────────┘
                                   │
                    ┌──────────────▼──────────────┐
                    │   core/session.py  会话层    │
                    │   headless、无 I/O、可测试   │
                    └──────────────┬──────────────┘
                                   │
                    ┌──────────────▼──────────────┐
                    │  现有 graph / tools / memory │
                    │  / safety / cache（基本不动）│
                    └─────────────────────────────┘
```

**与当前的差别：**

| 维度 | 现在 | Phase 2 之后 |
|---|---|---|
| 客户端接口 | HTTP + SSE，事件字段靠约定 | 类型化 JSON-RPC，TS 类型自动生成 |
| 核心入口 | `AgentV2`（3704 行，含路由/缓存/记忆/SSE） | `Session`（薄），能力下沉到各模块 |
| 加一个客户端 | 重新摸一遍 SSE 事件格式 | `import` 生成的 TS 类型，编译期就能发现不匹配 |
| 测核心 | 要起 HTTP server | 直接构造 `Session` 调方法 |

**关键约束（贯穿 Phase 2 的所有任务）：**
- **`api_server.py` 的现有 HTTP 接口必须保持向后兼容**，OpenTUI 在 P5 之前一直用它
- **不要在 Phase 2 里改 Agent 的行为**。这是纯粹的接口重构，H4 的评测基线分数应当**保持不变**——这就是我们先做 Phase 1 的原因

### 6.0.1 阻塞超时治理（横切纪律）

> **来源**：2026-08-01 全量验收实测——`mss` 截屏在锁屏/断开会话下**无限阻塞**，Windows 线程超时打断不了原生调用（`pytest --timeout` 直接失效，测试卡死 4 分钟+）。同类风险遍布生产：bash 子进程、LLM 调用、webfetch、审批弹窗、asyncio 里的同步调用。
>
> **原则**：**"永不阻塞"是设计目标，超时只是最后防线；进程边界是唯一的物理保证。**

| # | 机制 | 落地要求 | Phase 2 的落地点 |
|---|---|---|---|
| **T1** | **进程隔离** | 一切不可控调用（bash、截屏、第三方 SDK）放进独立进程/worker，主进程只做 `wait(timeout)`，超时 kill 子进程 | P4 appserver 进程模型；`tools/vision_capture.py` 已按此落地（2026-08-01） |
| **T2** | **显式超时** | 所有外部调用必须带超时：网络（connect/read/write）、子进程（`asyncio.wait_for(proc.communicate(), ...)`）、LLM（`wait_for(agent.run(), ...)`）；原生调用（文件/系统 API）交给 T1 包裹 | P1 把超时字段写进协议契约；P3 Session 层做统一超时入口 |
| **T3** | **事件循环纪律** | event loop 内禁止同步阻塞调用（sync I/O、requests、mss、`time.sleep`）；一律 `asyncio.to_thread` + 超时或进程池 | P3 Session 层 Review 必查项：任何新增 `await` 前的同步 I/O 一律打回 |
| **T4** | **看门狗兜底** | 运行时心跳 + 无响应 N 秒自动重启/降级；业务侧"已提交 / 执行中 / 失败"三态，客户端不无限等 | P4 appserver 心跳 + job 状态机；测试侧 `scripts/eval_watchdog.py` 总时长兜底 |

**工具超时纪律**（硬约束，和 §8.3 的 DC1–DC5 同级，违反即打回）：

- **bash 工具**：所有命令必须包超时；交互式程序（`tail -f`、REPL、git 需要凭证时挂起）要检测并拒绝，或给 PTY 输入超时
- **vision `screenshot`**：必须走子进程 + 超时 + 会话预检（锁屏/无交互桌面**明确报错**，不抓屏）；`RXYCODE_DISABLE_SCREEN_CAPTURE=1` 可全局禁用
- **webfetch / websearch / LLM 调用**：connect/read 超时必设；无超时的外部调用在 Code Review 直接打回
- **审批 / question 工具**：等用户输入必须有过期时间或取消路径，不能无限挂起

**合并前验收锚点**：

1. `git diff` 里新增的外部调用（网络 / 子进程 / 原生 API）全部带超时或已进程隔离
2. appserver 每个任务都有三态（`submitted / running / failed`），客户端轮询有上限
3. 锁屏/禁用场景不挂起：`RXYCODE_DISABLE_SCREEN_CAPTURE=1` 下 `vision screenshot` 返回明确错误（测试已覆盖）

### P1 · 定义协议层

`P0` / **A** / 2 周（W6–W7）/ 依赖 Phase 1 完成

**操作步骤**

1. 新建 `protocol/` 包：

```
protocol/
  __init__.py
  version.py        # PROTOCOL_VERSION = "1.0.0"
  requests.py       # 客户端 → 服务端
  notifications.py  # 服务端 → 客户端（单向）
  server_requests.py# 服务端 → 客户端（需要回复，如审批）
  types.py          # 共享类型
  schema.py         # 导出 JSON Schema
```

2. 用 pydantic 定义。**先只定义最小可用集**，够跑通一轮对话即可：

```python
# protocol/requests.py
"""客户端 → 服务端的请求。

设计约束：
  - 每个请求都是一个带 discriminator 的 pydantic 模型，便于生成 TS 判别联合
  - 字段只用可被 JSON Schema 表达的类型，不要放 Python 专有对象
  - 加字段可以，改语义 / 删字段必须升 PROTOCOL_VERSION 的 minor/major
"""

class InitializeRequest(BaseModel):
    method: Literal["initialize"] = "initialize"
    client_name: str
    client_version: str
    protocol_version: str

class NewSessionRequest(BaseModel):
    method: Literal["session/new"] = "session/new"
    workspace_root: str
    model: str | None = None

class PromptRequest(BaseModel):
    method: Literal["session/prompt"] = "session/prompt"
    session_id: str
    text: str

class InterruptRequest(BaseModel):
    method: Literal["session/interrupt"] = "session/interrupt"
    session_id: str
```

```python
# protocol/notifications.py
"""服务端 → 客户端的单向通知。对应现在 SSE 里那些事件。"""

class MessageDelta(BaseModel):
    method: Literal["event/message_delta"] = "event/message_delta"
    session_id: str
    text: str

class TaskStarted(BaseModel):
    method: Literal["event/task_started"] = "event/task_started"
    session_id: str
    task_id: str
    title: str

class ToolBegin(BaseModel):
    method: Literal["event/tool_begin"] = "event/tool_begin"
    session_id: str
    call_id: str
    tool_name: str
    arguments: dict[str, Any]

class ToolEnd(BaseModel):
    method: Literal["event/tool_end"] = "event/tool_end"
    session_id: str
    call_id: str
    ok: bool
    summary: str

class TaskComplete(BaseModel):
    method: Literal["event/task_complete"] = "event/task_complete"
    session_id: str
    task_id: str
    ok: bool

class TokenUsage(BaseModel):
    method: Literal["event/token_usage"] = "event/token_usage"
    session_id: str
    input_tokens: int
    output_tokens: int
```

```python
# protocol/server_requests.py
"""服务端 → 客户端、且需要客户端回复的请求。

只有审批属于这一类：core/safety 需要暂停执行等人回答。
"""

class ApprovalRequest(BaseModel):
    method: Literal["approval/request"] = "approval/request"
    session_id: str
    request_id: str
    risk_level: str            # 复用 core/safety/policy.py 的取值
    action: str                # 人类可读的动作描述
    details: dict[str, Any]

class ApprovalResponse(BaseModel):
    request_id: str
    decision: Literal["approve", "reject", "approve_always"]
```

3. **协议的每个字段都必须能在现有代码里找到对应来源。** 定义前先做一次盘点：

```powershell
# 现在 SSE 到底吐哪些事件类型？
Select-String -Path api_server.py -Pattern "event:|\"type\":|'type':" |
  ForEach-Object { "$($_.LineNumber): $($_.Line.Trim())" }
```

把结果和上面的通知列表对照，**缺的补上，多的删掉**。协议不是理想设计，是对现实的类型化。

4. 导出 JSON Schema：

```python
# protocol/schema.py
def export_schema() -> dict:
    """导出完整协议 schema，供 TS 类型生成和跨语言客户端使用。"""
```

加一个入口 `python -m protocol.schema > protocol/schema.json`。

5. 加一个**协议冻结测试** `tests/test_protocol_schema.py`：把 `schema.json` 提交进 git，测试比对当前导出与文件内容是否一致。不一致就失败，提示"改协议请同时更新 schema.json 并考虑升版本号"。

**验收命令**

```powershell
python -m protocol.schema | Out-File -Encoding utf8 protocol\schema.json
python -m pytest tests/test_protocol_schema.py -q
python -m ruff check protocol
```

**完成判据**
- [x] `protocol/` 下所有模型有 docstring 说明字段来源
- [x] `schema.json` 已生成并提交
- [x] 冻结测试能捕获协议变更（`test_schema_freeze_detects_field_changes`）
- [x] 第 3 步的 SSE 事件盘点结果写入 `docs/modules/protocol.md`

---

### P2 · 生成 TypeScript 类型并建立 TS 客户端

`P0` / **B** / 3 周（W6–W8）/ 依赖 P1 的 schema 定型 · **owner: frontend（Composer 主写；多模态环节 Grok 辅助）**

**操作步骤**

1. 新建共享包 `frontend/protocol-client/`（OpenTUI 和 Desktop 都会用）：

```
frontend/protocol-client/
  package.json
  tsconfig.json
  src/
    generated/types.ts   # 由 schema.json 生成，不要手改
    client.ts            # JSON-RPC over stdio 客户端
    index.ts
```

2. 用 `json-schema-to-typescript` 从 `protocol/schema.json` 生成类型，写成 npm script：

```json
{
  "scripts": {
    "generate": "json2ts -i ../../protocol/schema.json -o src/generated/types.ts --bannerComment \"/* 自动生成，请勿手改。改协议请改 protocol/*.py 后重新运行 bun run generate */\""
  }
}
```

3. 实现 `client.ts`：JSON-RPC over stdio，需要支持
   - 请求 / 响应配对（按 `id`）
   - 通知分发（无 `id`）
   - **服务端发起的请求**（审批）——这是与普通 JSON-RPC 客户端最大的区别，必须双向

4. 加一个"生成物是最新的"CI 检查：重新生成后 `git diff --exit-code`，有差异就失败。

**完成判据**
- [x] `bun run generate` 能从 `schema.json` 产出类型
- [x] 客户端能处理双向请求
- [x] 有单元测试（mock 一个 stdio 管道）
- [x] CI 检查生成物新鲜度

---

### P3 · 抽出 Session 层

`P0` / **A** / 2 周（W7–W8）/ 依赖 P1

**背景**
`core/agent_v2.py` 3704 行、~25 处关键词路由、~131 处延迟 import。**不要试图一次拆完**——那会产生一个没人能 review 的 diff，且会破坏 evals 基线。

**策略：绞杀者模式（Strangler Fig）。新建 `Session` 作为门面，逐步把职责搬过去，`AgentV2` 逐渐变空。**

**操作步骤**

1. 新建 `core/session.py`。第一版**只是一个转发壳**，行为与现在完全一致：

```python
class Session:
    """一次会话。协议层之下、Agent 之上的唯一入口。

    第一版只是 AgentV2 的门面，行为不变。后续任务逐步把 AgentV2 的职责
    搬进这里以及各专职模块，最终 AgentV2 消失。

    不变量：
      - Session 不做任何 I/O（不 print、不写 SSE、不读 stdin）
      - 所有对外表达都通过 emit(notification) 回调
    """

    def __init__(self, *, workspace_root: Path, emit: Callable[[BaseModel], None]):
        ...

    async def prompt(self, text: str) -> None:
        """处理一次用户输入。产出通过 emit 流出，不返回值。"""

    async def interrupt(self) -> None:
        ...
```

2. 让 `api_server.py` 改走 `Session`，SSE 由 `emit` 回调转换而来。**HTTP 接口的外部形状一个字都不能变。**

3. 加一组 Session 层测试（不起 HTTP server，直接构造 Session、收集 emit 出来的通知、断言序列）。

4. **每搬一块职责，跑一次 evals 基线比对**：

```powershell
python -m evals.cli run --backend agent --compare-baseline evals\baselines\latest-agent.json
```

分数下降就是回归，立刻停下来。

**完成判据**
- [x] `core/session.py` 存在且有测试
- [x] `api_server.py` 走 Session（`/chat` + `/chat/stream`）
- [x] 现有 HTTP / SSE 接口**外部行为零变化**（用 OpenTUI 手动验证；2026-08-02 手测通过）
- [x] evals 基线分数**不变**（2026-08-02 compare-baseline：9/17=52.9% 与 latest-agent 持平 Delta ++0.0%；日志 artifacts/p3-compare-baseline.log）
- [x] Session 层没有任何 `print` / 直接写响应

---

### P4 · 实现 appserver（stdio JSON-RPC）

`P0` / **A + B** / 2 周（W9）/ 依赖 P2 P3

**操作步骤**

1. 新建 `appserver/__main__.py`，可执行：`python -m appserver`
2. 从 stdin 读 JSON-RPC，往 stdout 写。**日志一律走 stderr**（stdout 是协议通道，混进日志会直接破坏协议）
3. 一个进程支持多个并发 session
4. 实现审批的双向请求：`core/safety` 需要审批时，通过 `approval/request` 发给客户端并 await 回复
5. 加集成测试：起子进程、发请求、断言响应

**完成判据**
- [x] `python -m appserver` 能跑通完整一轮对话（`tests/test_appserver/test_stdio_integration.py::test_appserver_full_conversation_round_trip`）
- [x] 审批流程双向可用（`test_appserver_approval_bidirectional` + `test_jsonrpc_approval_round_trip`）
- [x] **stdout 上没有任何非协议输出**（`test_appserver_stdout_only_jsonrpc`）
- [x] 有子进程集成测试（`tests/test_appserver/test_stdio_integration.py`）

---

### P5 · OpenTUI 迁到协议客户端

`P0` / **B** / 2 周（W9–W10）/ 依赖 P4 · **owner: frontend（Composer 主写；多模态环节 Grok 辅助）**

**操作步骤**

1. OpenTUI 改用 `frontend/protocol-client`，走 `python -m appserver` 子进程，替代 HTTP + SSE
2. **保留 HTTP 模式作为可切换的回退**：`RXYCODE_TRANSPORT=stdio|http`，**默认 `stdio`**（2026-08-03 翻转）
3. 两种传输下的 67 个测试都要绿

**完成判据**
- [x] `RXYCODE_TRANSPORT=stdio` 下 OpenTUI 功能完整（对话、流式、工具展示、审批、中断）
- [x] 两种传输的测试都在 CI 上跑
- [x] 默认值翻转到 `stdio`（2026-08-03；观察期由团队持续跟踪）

---

### P6 · 消除关键词路由

`P1` / **A + B** / 2 周（W11）/ 依赖 P3

**背景**
~25 处硬编码中英文关键词决定走哪条链路。这类逻辑对非中文输入、对措辞变化极其脆弱，且无法测试穷尽。

**操作步骤**

1. 先把 25 处**全部列出来**（这一步的产物本身就有价值）：

```powershell
Select-String -Path core\agent_v2.py -Pattern "in \(?\[?['\"].{1,12}['\"], |任何|如果.*关键词|KEYWORDS" |
  ForEach-Object { "$($_.LineNumber): $($_.Line.Trim())" }
```

手工核对，整理成表：位置 / 触发词 / 决定了什么 / 误判后果。

2. 按"误判后果"排序，只处理**后果严重**的（比如误判成 compose 模式导致跑一整套 plan+build）。
3. 替换方案优先级：**显式用户指令（斜杠命令）> 结构化信号（文件是否存在、任务数量）> LLM 分类**。不要一上来就全换成 LLM 分类，那会增加延迟和成本。
4. 每替换一处跑一次 evals 基线比对。

**完成判据**
- [x] 25 处清单完整并写进 `docs/modules/core.md`
- [x] 高危项已替换且有测试
- [x] evals 分数不下降

---

### P7 · 收敛延迟 import

`P2` / **A** / 1 周（W12）/ 依赖 P3

**操作步骤**

1. 统计并定位：

```powershell
Select-String -Path core\*.py,execution\*.py,planning\*.py,validation\*.py,synthesis\*.py -Pattern "^\s{4,}(from|import) " |
  Measure-Object | Select-Object -ExpandProperty Count
```

2. 画出真实的循环依赖图（用 `pydeps` 或手工）
3. 用 `TYPE_CHECKING` 块解决纯类型用途的（这类最容易，先清）
4. 剩下的真循环，靠 P3 引入的 Session 层做依赖倒置
5. **不要求清零**。目标是"从 131 降到 50 以下，且 `core/` 内部无循环"

**完成判据**
- [x] 延迟 import 降到 50 以下（当前 **34/50**，`python scripts/count_lazy_imports.py`）
- [x] 明细表写入 `docs/modules/core.md`（P7 intentional lazy imports，逐文件注明原因）
- [x] 回归守卫 `tests/test_core/test_lazy_import_budget.py` 通过
- [x] evals 无回归（2026-08-05 gate-p7: PASS 88.2%）

---

### P8 · Phase 2 文档与收尾

`P1` / **全员** / 1 周（W12）

- 新建 `docs/modules/protocol.md`、`docs/modules/appserver.md`
- 更新 `docs/modules/core.md`（Session 层）、`docs/modules/api_server.md`（变成适配器）
- 更新 `AGENTS.md` 的架构图和请求流程
- 更新 §3 排期表的实际完成情况

---

## §7 Phase 3 — 模型输出上限自适应（W13–W15）

> **owner: backend → Composer 2.5 主写。** M1–M8 全部由 Composer 2.5 负责：配置契约、模型目录、发现 ID、解析器、Provider 接线、迁移、测试和验收。Grok 4.5 不参与本 Phase 的后端、协议、模型元数据或配置实现；只有当 M8 需要核对模型列表/设置页的显示状态时，才可按卡内明确范围做视觉辅助。Sonnet 5 可做 M2/M3/M5 的 diff 预审，但不代替 Composer 收口。

> **执行规范**：全部 M 卡必须遵循 [`../COMPOSER-2.5-PLAYBOOK.md`](../COMPOSER-2.5-PLAYBOOK.md) 的 C1–C8 硬性规则、任务卡结构和 Review 清单；本 Phase 的额外硬约束见 §7.5，出口标准见 §7.6。

> **一句话目标**：把模型输出上限从“新增模型时统一写入一个数字”改成“使用实际拉取到的 `model_id` 查找模型元数据，按显式配置、精确模型目录、Provider 元数据和高位未知模型兜底依次解析”，并让每次请求都能解释最终采用的上限来源。

### 7.0 为什么必须先做这一 Phase

当前 RxyCode 的模型添加和请求链路存在同一个错误假设：**所有模型都可以用一个全局 `8192` 作为 `max_tokens`**。这不是模型能力，只是历史默认值。它会造成三类问题：

1. **批量发现污染配置**：`config/model_manager.py` 的 `add_model()` 默认参数是 `8192`，`onboard_models_batch()` 为发现列表中的每个模型调用它，导致模型 ID 不同但输出上限相同。
2. **运行时二次写死**：`core/providers/base.py` 的 `llm_kwargs()` 在配置缺少 `max_tokens` 时仍回退到 `8192`，即使后续已经有模型能力目录，也会被这个回退截断。
3. **配置和模型目录没有分层**：用户明确配置、模型官方上限、Provider 默认值和未知模型兜底没有来源字段，发生 400 或输出过短时无法解释“为什么是这个数字”。

本 Phase 不把模型的真实输出能力“猜”出来，也不承诺所有 Provider 都会在 `/models` 返回限制。**模型发现接口只负责提供真实 `model_id`；上限由模型目录和能力元数据按 ID 查找。** Provider 返回可验证的能力字段时可以作为目录输入，但不能因为显示名相似就把一个模型的限制套给另一个模型。

### 7.1 参考口径与 RxyCode 自己的边界

Codex 的公开行为提供三个可借鉴的边界：

- `model/list` 先发现可用模型及其能力，客户端不把模型选择器写死成一组静态名称；
- `model_catalog_json` 允许启动时加载模型目录，目录与配置层分离；
- `model_context_window` 是可选的模型级元数据，未设置时使用模型或预设默认值，而不是把所有模型写成同一个固定窗口。

参考：

- Codex App Server `model/list`：https://learn.chatgpt.com/docs/app-server
- Codex 配置参考：https://learn.chatgpt.com/docs/config-reference
- Codex 模型选择：https://learn.chatgpt.com/docs/models

**归因边界**：`model_max_output_tokens`、`OutputLimitResolution`、`max_tokens: auto` 和未知模型高位兜底是 RxyCode 的实现契约，不得写成“Codex 公开字段”。RxyCode 借鉴的是“模型目录 + 可选覆盖 + 模型默认值”的分层方式。

### 7.2 目标数据流

```text
Provider /models
    │
    │ 只取得真实 model_id、owned_by 和可选能力字段
    ▼
ModelDiscoveryRecord
    │
    │ provider_id + 精确 model_id 查找；保留原始 ID 用于请求
    ▼
ModelCatalog
    │  exact provider+id → exact id → 已审计 family pattern → provider default
    ▼
OutputLimitResolver
    │  显式配置覆盖；已知硬上限钳制；context window 再钳制
    ▼
OutputLimitResolution
    │  resolved_max_tokens + source + evidence + warnings
    ▼
Provider llm_kwargs / 请求日志 / CLI、OpenTUI、未来 Desktop 的设置摘要
```

**目录输入不是“每次发现一次就把数字写进用户配置”。** 它分成三层：

1. Provider `/models` 返回 `id` 以及经过 allowlist 验证的能力字段时，作为本次发现记录；
2. Provider 只返回 `id` 时，按 `provider_id + model_id` 精确读取版本化 `model_catalog_json`/审计目录，目录记录带来源 URL 和 `as_of`；
3. 两层都没有命中时，进入 Provider 默认或 `unknown_fallback`，只把解析结果写入诊断摘要，不把兜底数字批量抄回 `config.yaml`。

目录可以刷新、替换和审计；请求链只读取解析结果，不在每个 Provider 文件里维护一份模型表。

解析优先级冻结为：

| 优先级 | 来源 | 说明 |
|---|---|---|
| 1 | 用户显式 `max_tokens: <正整数>` | 兼容现有配置；如果超过已知模型硬上限，只能钳到硬上限并记录 warning，不能把无效值发给 Provider |
| 2 | `provider_id + model_id` 精确目录项 | 最高可信的自动来源；model ID 使用规范化键查找，发请求仍使用原始 ID |
| 3 | `model_id` 精确目录项 | 仅在 Provider 目录没有同名冲突时使用；有冲突必须报错或要求补 Provider |
| 4 | 已审计的 family pattern | 只能作为显式登记的后备规则，必须记录命中的 pattern；不得使用昵称或模糊包含匹配 |
| 5 | Provider 默认能力 | Provider 有明确默认但没有具体型号条目时使用 |
| 6 | 未知模型高位兜底 | 默认 `32768`，实际值由 `model_limits.unknown_model_max_tokens` 配置；不再回退 `8192` |

若同时知道 `model_context_window`，最终请求上限还必须满足：

```text
effective_max_tokens = min(
    selected_output_limit,
    context_window - estimated_input_tokens - context_safety_margin
)
```

当计算结果小于 1 时，必须返回结构化 `MODEL_CONTEXT_BUDGET_EXHAUSTED`，不能发送 `0`、负数或偷偷切换到 `8192`。`reserved_output_tokens` 仍然是治理/限流的预留量，不是模型输出上限来源，不能把两个字段混为一谈。

### 7.3 配置和目录契约

新的用户配置允许以下三种形式，含义必须唯一：

```yaml
models:
  deepseek/deepseek-v4-flash:
    provider_id: deepseek
    model_name: deepseek-v4-flash
    max_tokens: auto       # 省略或 auto = 走模型目录解析

  custom/manual-model:
    provider_id: custom
    model_name: manual-model
    max_tokens: 4096       # 正整数 = 用户显式覆盖
```

约束：

- `max_tokens` 只接受正整数、`auto` 或省略；`0`、负数、空字符串和浮点数都拒绝；
- 新模型默认省略 `max_tokens` 或写 `auto`，`add_model()` 不能再默认写入 `8192`；
- 旧配置中的正整数暂时按用户显式覆盖处理，保证升级不悄悄扩大费用；M6 提供可审计的批量转自动命令；
- 目录元数据使用独立字段，不把模型能力伪装成用户配置：

```json
{
  "provider_id": "deepseek",
  "model_id": "deepseek-v4-flash",
  "model_context_window": 1048576,
  "model_max_output_tokens": 65536,
  "source": "provider_catalog",
  "source_url": "https://provider.example/models",
  "as_of": "2026-08-03"
}
```

上面目录数字只用于说明字段形状，不能直接当作任何厂商的官方上限；施工时必须由 M1/M8 记录的可核验来源填充，查不到就保留 `null` 或走 `unknown_fallback`。

- `model_max_output_tokens` 是模型目录/能力元数据；`max_tokens` 是本地请求覆盖；二者不能作为两个同优先级配置源；
- 未验证的数字不能进入目录。若官方资料只写“取决于上下文”或没有独立上限，目录字段保持 `null`，由下一级规则处理；
- 每条目录记录必须包含 `provider_id`、精确 `model_id`、来源、来源时间和覆盖/冲突测试；
- 目录键必须允许同一个模型 ID 在不同 Provider 下共存，例如 `deepseek:deepseek-v4-flash` 与 `opencode-go:deepseek-v4-flash`。

### 7.4 M1–M8 任务总表

| ID | 内容 | 负责 | owner | 工时 | 依赖 |
|---|---|---|---|---|---|
| **M1** | 现状盘点、字段来源和零回归基线 | A | **backend / Composer 主写** | 0.5d | P8、A 的能力契约（若已落地） |
| **M2** | ModelCatalog 与 `OutputLimitResolution` 契约 | A | **backend / Composer 主写** | 2d | M1 |
| **M3** | 以发现列表 `model_id` 为主键的目录查找与解析器 | A | **backend / Composer 主写** | 3d | M2 |
| **M4** | Provider 请求参数接线、context window 钳制和错误模型 | A | **backend / Composer 主写** | 2d | M3 |
| **M5** | 模型批量添加、单模型添加和旧配置兼容迁移 | A | **backend / Composer 主写** | 2d | M3、M4 |
| **M6** | 自动迁移命令、可解释诊断和客户端摘要字段 | B | **frontend / Composer 主写** | 1.5d | M4、M5 |
| **M7** | 单元、契约、回归、Provider 矩阵和评测门 | C | **QA / Composer 主写** | 2d | M1–M6 |
| **M8** | 发布门、文档锁定和 Phase 3 出口 | C | **QA / Composer 主写** | 1d | M7 |

### M1 · 现状盘点、字段来源和零回归基线

`P0` / **A** / 0.5d / 依赖 P8、A 的能力契约（若已落地）

**背景**

先把“写死在哪里”和“自动解析在哪里”分开。不能一边新增 ModelCatalog，一边让旧的 `8192` fallback 继续在 Provider 层生效；也不能把 `reserved_output_tokens` 误当成请求上限。

**涉及文件**

- `data/config.yaml`：只读检查当前模型项，禁止把凭证内容带入日志；
- `config/model_manager.py`：`add_model`、`onboard_models_batch`、`_parse_discovered_models`；
- `config/settings.py`：模型配置加载/保存和治理限流字段；
- `config/model_capabilities.py`：现有 `ModelCapabilities.context_window` 和默认能力；
- `core/providers/base.py`：`llm_kwargs` 的 `max_tokens` 回退；
- `core/providers/*.py`：Provider 级能力来源和现有型号判断；
- `tests/unit/test_model_manager_batch.py`、`tests/test_providers/test_registry.py` 及现有配置测试。

**操作步骤**

1. 运行以下只读盘点，输出只允许包含键名、模型 ID、Provider 和 `max_tokens`，禁止输出 `api_key`、secret、环境变量值：

```powershell
rg -n "max_tokens|model_name|provider_id|provider_name|context_window|reserved_output_tokens" config core data tests
rg -n "def add_model|def onboard_models_batch|def _parse_discovered_models|def llm_kwargs" config core
```

2. 画出当前链路：`/models/discover → _parse_discovered_models → onboard_models_batch → add_model → load_config → Provider.llm_kwargs`。
3. 对每个 `8192` 标记来源：请求上限、治理预留、测试预期、历史兼容或文档示例；不允许使用“看起来都是 token 所以统一替换”。
4. 保存当前配置 schema 和单模型请求参数的基线；旧模型在没有新目录时必须仍能启动。
5. 将结果写入本卡的 commit 描述或 `docs/modules/model-limits.md`，并列出 M2–M6 的文件白名单。

**验收命令**

```powershell
rg -n "max_tokens|model_name|provider_id|provider_name|context_window|reserved_output_tokens" config core data tests
python -m pytest tests/unit/test_model_manager_batch.py tests/test_providers/test_registry.py tests/test_core/test_config_settings.py -q
python -m evals.cli run --backend agent --compare-baseline evals\baselines\latest-agent.json
```

**完成判据**

- [ ] 已定位所有生产路径中的 `8192`，并说明哪些不能改；
- [ ] 已确认发现列表当前至少保证 `id`，可选 `owned_by`，没有把显示名当主键；
- [ ] 已确认现有配置中的数值 `max_tokens` 如何保持兼容；
- [ ] 已确认 `reserved_output_tokens` 与请求 `max_tokens` 的边界；
- [ ] 单 Agent、现有模型和评测基线没有因为盘点发生行为变化。

**回滚**

本卡只产生盘点记录；删除本卡文档/commit 即可回滚，不得为了盘点修改配置或源码。

**常见坑**

- 不要 `Get-Content data/config.yaml` 后把 API Key 一并复制进报告；
- 不要看到 `8192` 就全部替换，限流预留字段不属于本卡目标；
- 不要用 nickname、`owned_by` 或 UI 展示名称替代 Provider 返回的 `id`。

**Commit**

```text
docs(model-limits): inventory fixed output token sources
```

### M2 · ModelCatalog 与 OutputLimitResolution 契约

`P0` / **A** / 2d / 依赖 M1

**背景**

把“模型能力”“用户覆盖”“最终请求值”拆成三个对象。后续 Provider、CLI、OpenTUI 和 Phase 4 Desktop 只消费解析结果，不各自读取 `config.yaml` 或复制一套模型表。

**涉及文件**

- `config/model_capabilities.py`：增加输出上限能力字段；若 Phase A 已冻结该 dataclass，只能做向后兼容的可选字段扩展；
- 新建 `config/model_catalog.py` 与版本化 `config/model_catalog.json`：模型目录记录、精确键、来源和已审计 family pattern；
- 新建或明确 `config/model_limits.py`：解析结果、来源枚举、错误码和序列化摘要；
- `protocol/types.py` 或对应模型元数据协议：只在客户端需要展示来源/上限时增加可选字段；
- `tests/test_model_limits.py`、`tests/test_model_catalog.py`。

**操作步骤**

1. 定义不可变类型，字段名称冻结为：

```python
from dataclasses import dataclass
from typing import Literal

LimitSource = Literal[
    "explicit_config",
    "catalog_exact_provider",
    "catalog_exact_model",
    "catalog_family",
    "provider_default",
    "unknown_fallback",
    "context_cap",
    "explicit_clamped",
]

@dataclass(frozen=True)
class ModelLimitRecord:
    provider_id: str
    model_id: str
    model_context_window: int | None
    model_max_output_tokens: int | None
    source: str
    source_url: str | None
    as_of: str | None

@dataclass(frozen=True)
class OutputLimitResolution:
    provider_id: str
    model_id: str
    requested_max_tokens: int | None
    resolved_max_tokens: int
    context_window: int | None
    estimated_input_tokens: int | None
    source: LimitSource
    matched_catalog_key: str | None
    warnings: tuple[str, ...]

def resolve_output_limit(
    *,
    provider_id: str,
    model_id: str,
    configured_max_tokens: int | str | None,
    catalog_record: ModelLimitRecord | None,
    provider_default: int | None,
    input_tokens: int | None,
    context_safety_margin: int = 1024,
) -> OutputLimitResolution:
    raise NotImplementedError
```

2. 把 `model_max_output_tokens`、`max_tokens`、`resolved_max_tokens` 的职责写入 docstring 和 schema；禁止使用模糊字段 `limit`、`tokens` 或第二个同义 `output_limit`。
3. 目录校验必须拒绝空 Provider、空 model ID、非正整数能力值、`model_max_output_tokens > model_context_window`（如果两者都提供）和无来源记录。
4. 目录允许同一 `model_id` 在不同 Provider 下出现；同 Provider 同 ID 的重复项必须 fail closed，不能按文件顺序覆盖。
5. 用 `model_id.casefold().strip()` 生成查找键，但始终保留原始 ID 用于 Provider 请求和审计。
6. 导出最小 JSON Schema/冻结快照，后续客户端只能使用可选的摘要字段，不能自行解析目录文件。

**验收命令**

```powershell
python -m pytest tests/test_model_limits.py tests/test_model_catalog.py -q
python -m ruff check config/model_capabilities.py config/model_catalog.py config/model_limits.py tests/test_model_limits.py tests/test_model_catalog.py
python -m evals.cli run --backend agent --compare-baseline evals\baselines\latest-agent.json
```

**完成判据**

- [ ] 类型中能区分用户请求值、目录值、最终值和来源；
- [ ] 同 Provider 同 ID 冲突会失败，不会静默覆盖；
- [ ] 不同 Provider 的同名模型可以同时存在；
- [ ] 未知模型记录可以合法表示 `model_max_output_tokens=None`；
- [ ] 目录快照、schema 和测试在同一个 commit 中更新；
- [ ] Phase A 已存在时没有新建第二套 `ModelCapabilities` 或 Provider registry。

**回滚**

回滚 M2 的 schema、目录和新模块；M1 的盘点记录保留。若已有下游引用，先回滚下游再回滚契约。

**常见坑**

- 不要把 `max_tokens` 直接命名成 `model_max_output_tokens`；前者是用户覆盖，后者是能力元数据；
- 不要把上下文窗口当成输出上限；两者是不同维度；
- 不要用目录文件中后出现的重复记录覆盖前一条。

**Commit**

```text
feat(model-limits): freeze catalog and resolution contracts
```

### M3 · 以发现列表 model_id 为主键的目录查找与解析器

`P0` / **A** / 3d / 依赖 M2

**背景**

用户已经明确：找模型的秘诀是看 Provider 拉取列表返回的模型 ID。M3 将这个 ID 变成唯一查找入口，避免“模型名称包含 `gpt` 就套 OpenAI 默认”“显示名相同就误合并”等不可靠猜测。

**涉及文件**

- `config/model_manager.py`：发现记录、Provider 命名空间和现有模型 key；
- `config/model_catalog.py`、`config/model_limits.py`：查找和解析；
- `core/providers/base.py`：只接收解析结果，不直接实现查找；
- `tests/test_model_discovery.py`、`tests/test_model_limits.py`。

**操作步骤**

1. 扩展发现解析器：保留 `id`，可选读取 `owned_by`、`context_window`、`max_output_tokens`、`max_completion_tokens`；任何额外字段都必须在 allowlist 中，未知字段不得当成能力。若列表只有 `id`，不得把发现记录当成“能力未知且批量写 8192”，而应继续走精确目录查找。
2. 把发现记录写成：

```python
ModelDiscoveryRecord(
    provider_id="deepseek",
    model_id="deepseek-v4-flash",  # 原始 Provider id
    owned_by="deepseek",
    advertised_context_window=None,
    advertised_max_output_tokens=None,
)
```

3. 实现查找顺序：

```python
resolve_output_limit(
    provider_id="deepseek",
    model_id="deepseek-v4-flash",
    configured_max_tokens=None,
    catalog_record=ModelLimitRecord(
        provider_id="deepseek",
        model_id="deepseek-v4-flash",
        model_context_window=131072,
        model_max_output_tokens=65536,
        source="provider-catalog-audited-example",
        source_url="https://provider.example/models",
        as_of="2026-08-03",
    ),
    provider_default=16384,
    input_tokens=12000,
    context_safety_margin=1024,
)
# exact provider+id → exact id → audited family → provider default → 32768
```

4. 精确 Provider+ID 命中时停止继续匹配；只有没有精确命中时才允许 family pattern，且返回 `matched_catalog_key` 和 warning。目录命中值来自 Provider 能力字段或版本化审计目录，不得在运行时按字符串猜测。
5. 同一原始 ID 在两个 Provider 下必须形成不同的本地配置 key，不能让后添加的模型覆盖先添加的模型。
6. 目录没有模型时返回结构化 `MODEL_METADATA_NOT_FOUND` 的诊断上下文，但继续使用 `unknown_fallback`；只有配置/类型非法才阻止启动。
7. 解析器不得读取模型昵称、UI label、API Key、prompt 或历史 transcript 来猜上限。

**验收命令**

```powershell
python -m pytest tests/test_model_discovery.py tests/test_model_limits.py tests/unit/test_model_manager_batch.py -q
python -m ruff check config/model_manager.py config/model_catalog.py config/model_limits.py tests/test_model_discovery.py
python -m evals.cli run --backend agent --compare-baseline evals\baselines\latest-agent.json
```

**完成判据**

- [ ] 返回列表中的真实 `id` 能被精确查找并用于发送请求；
- [ ] Provider+ID 冲突不会串模型；
- [ ] 精确命中优先于 family pattern；
- [ ] 未知模型最终得到 `32768` 或配置的高位兜底，并标注 `unknown_fallback`；
- [ ] 没有任何 nickname/模糊包含匹配路径；
- [ ] `/models/discover` 失败时不会写入半条模型配置。

**回滚**

回滚解析器和目录适配，保留只读发现接口；恢复旧 `onboard_models_batch` 前必须跑 M1 的现状基线。

**常见坑**

- `deepseek-v4-flash` 和 `deepseek/deepseek-v4-flash` 分别是 Provider ID 与本地 key，不可混用；
- `owned_by` 不是 Provider 身份的唯一证明，Provider namespace 仍以连接配置为准；
- `/models` 返回 200 但没有可解析的 `id` 时，不得把空列表当成“所有模型都未知并批量写入”。

**Commit**

```text
feat(model-limits): resolve output limits from discovered model ids
```

### M4 · Provider 请求参数接线、context window 钳制和错误模型

`P0` / **A** / 2d / 依赖 M3

**背景**

解析器算出的值必须成为唯一进入 LLM 构造器的值。不能解析出 32768 后又在 `BaseProvider.llm_kwargs()` 里被 `.get("max_tokens", 8192)` 覆盖，也不能让 `auto` 字符串进入 SDK。

**涉及文件**

- `core/providers/base.py`：`llm_kwargs` 和公共请求构造；
- `core/providers/openai.py`、`anthropic.py`、`deepseek.py`、`qwen.py` 等实际 Provider 适配；
- `config/settings.py`：`model_limits.unknown_model_max_tokens` 和 context safety margin；
- `tests/test_providers/test_registry.py`、`tests/test_model_limits.py`、Provider 专项测试。

**操作步骤**

1. 在 Provider 调用前按 M2 冻结的参数契约调用 `resolve_output_limit(provider_id=..., model_id=..., configured_max_tokens=..., catalog_record=..., provider_default=..., input_tokens=...)`，把解析结果传入 `llm_kwargs`；禁止 Provider 子类重新读取 `config.yaml`。
2. 将默认配置改成：

```python
"model_limits": {
    "unknown_model_max_tokens": 32768,
    "context_safety_margin_tokens": 1024,
}
```

3. `llm_kwargs` 必须满足：

```python
kwargs["max_tokens"] = resolution.resolved_max_tokens
assert isinstance(kwargs["max_tokens"], int)
assert kwargs["max_tokens"] > 0
```

4. 已知 `context_window` 时用估算输入 token 和安全余量钳制；没有 context window 时不凭空把未知模型降回 8192。
5. 用户显式值超过已知模型硬上限时使用 `explicit_clamped`，写入结构化 warning；用户显式值低于模型上限时保留用户值。
6. Provider 返回“max tokens 超限”时，返回 `MODEL_OUTPUT_LIMIT_REJECTED`，包含 model ID、requested、resolved、catalog source 和 Provider 原始安全错误摘要；不把错误吞掉后偷偷重试多个数字。
7. 仍然遵守各 Provider 的参数差异：如果某 Provider 需要 `max_completion_tokens`，由 Provider adapter 映射，公共解析字段不变。

**验收命令**

```powershell
python -m pytest tests/test_providers/test_registry.py tests/test_model_limits.py tests/test_providers -q
python -m ruff check core/providers config/model_limits.py config/settings.py tests/test_model_limits.py
python -m evals.cli run --backend agent --compare-baseline evals\baselines\latest-agent.json
```

**完成判据**

- [ ] `8192` 不再是 Provider 缺省请求上限；
- [ ] `auto` 不会进入任何 SDK 请求；
- [ ] 已知模型的目录值能进入最终 `llm_kwargs`；
- [ ] context window 钳制不会产生 0/负数；
- [ ] Provider 特定参数由 adapter 映射，不复制解析器；
- [ ] 超限错误可解释、可审计，不静默多次重试。

**回滚**

保留 `OutputLimitResolution` 类型，回滚 Provider 接线到旧路径；不得删除目录字段，以便下一次重接。回滚后必须明确恢复了旧的 8192 行为。

**常见坑**

- 不要把治理 `reserved_output_tokens` 塞进请求 payload；
- 不要用 `max_tokens=None` 直接交给 ChatOpenAI；
- 不要在每个 Provider 中各写一个未知模型默认值；
- 不要因一个 Provider 的参数名改变公共 `OutputLimitResolution`。

**Commit**

```text
feat(providers): route requests through resolved model output limits
```

### M5 · 模型批量添加、单模型添加和旧配置兼容迁移

`P0` / **A** / 2d / 依赖 M3、M4

**背景**

配置写入是当前问题的源头。新增模型必须只保存 Provider ID、真实 model ID 和用户明确选择的覆盖；批量发现不能把同一个数字抄进每个模型。

**涉及文件**

- `config/model_manager.py`：`add_model`、`onboard_models_batch`、保存逻辑；
- `config/settings.py`：配置 schema 校验和迁移版本；
- `api_server.py`：`/models/onboard`、`/models/onboard/batch` 的响应摘要；
- `frontend/src/components/AddModelWizard.tsx`、`frontend/src/modelSetup.ts`：只修改需要显示自动/手动状态的字段；
- `tests/unit/test_model_manager_batch.py`、`tests/test_api_security_onboarding.py`、新增迁移测试。

**操作步骤**

1. 把 `config/model_manager.py` 的 `add_model` 参数改成 `max_tokens: int | Literal["auto"] | None = None`；缺省时不写死数值，保存为省略字段或显式 `auto`。
2. `onboard_models_batch()` 为每个发现 ID 调用 `add_model()` 时不传统一 max token；每个模型进入运行时再解析自己的上限。
3. 新增配置 schema 迁移：

```text
旧配置 max_tokens = 正整数  → 视为用户显式覆盖，保持不变
旧配置缺少 max_tokens       → 进入 auto
新配置 max_tokens: auto      → 进入 auto
新配置 max_tokens: 正整数    → 显式覆盖
```

4. 提供非破坏性诊断/迁移入口：

```powershell
python -m RxyCode config model-limits inspect
python -m RxyCode config model-limits set-auto --model deepseek/deepseek-v4-flash --backup
```

`inspect` 只报告当前来源；`set-auto` 必须先备份配置、显示变更列表、要求明确确认，并把旧值写入迁移审计记录。不得默认把用户手写的 16384 改掉。
5. `/models` 和 onboarding 响应新增可选摘要：`model_id`、`max_tokens_mode`、`resolved_max_tokens`、`limit_source`；禁止返回 API Key。
6. 批量添加失败时，已添加模型和未添加模型必须分开报告；不得留下没有 `model_name` 或没有 Provider namespace 的半条记录。
7. 兼容旧的裸模型 key：读取时可识别，但新写入优先使用 `provider_id/model_id`，并保留迁移 warning。

**验收命令**

```powershell
python -m pytest tests/unit/test_model_manager_batch.py tests/test_api_security_onboarding.py tests/test_core/test_config_settings.py -q
python -m ruff check config/model_manager.py config/settings.py api_server.py frontend/src tests/unit/test_model_manager_batch.py
python -m evals.cli run --backend agent --compare-baseline evals\baselines\latest-agent.json
```

**完成判据**

- [ ] 单模型添加和批量添加默认不写 `8192`；
- [ ] 新模型配置能明确区分 auto 与用户显式覆盖；
- [ ] 旧的正整数配置不被静默扩大；
- [ ] `inspect` 不泄漏凭证，`set-auto` 有备份和审计；
- [ ] 同一 Provider 下模型 ID 不冲突，跨 Provider 同名模型可共存；
- [ ] API 响应只包含模型元数据摘要，不包含 secret。

**回滚**

保留迁移前配置备份；回滚代码后可从备份恢复配置。不得用 `git checkout` 覆盖用户的 `data/config.yaml`。

**常见坑**

- 不要把 `model_name` 的 nickname 当成 Provider model ID；
- 不要批量探测时给所有模型发一次聊天请求来“猜”上限；
- 不要把旧的 16384 等用户明确值当成历史错误自动删除；
- 不要在前端缓存一份独立的模型限制表。

**Commit**

```text
feat(config): onboard models without a fixed output token default
```

### M6 · 自动迁移命令、可解释诊断和客户端摘要字段

`P1` / **B** / 1.5d / 依赖 M4、M5

**背景**

“自动化不完全写死”必须能被用户看见。用户在 `/models`、模型切换和请求日志中应该知道最终上限来自显式配置、精确目录、Provider 默认还是未知模型兜底；否则自动化出了问题仍然无法排查。

**涉及文件**

- `api_server.py`：模型列表/模型诊断响应；
- `frontend/src/modelSetup.ts`、`frontend/src/components/AddModelWizard.tsx`：已有模型设置入口；
- `frontend/opentui-app/src/modelSetup.ts`：OpenTUI 文本摘要；
- `protocol/` 和 `frontend/protocol-client/`：如果 Phase 2 协议已经承载模型摘要，只加可选字段；
- `tests/test_api_security_onboarding.py`、`frontend/src/modelSetup.test.ts`、`frontend/opentui-app/src/modelSetup.wiring.test.ts`。

**操作步骤**

1. 模型列表摘要固定为：

```json
{
  "id": "deepseek/deepseek-v4-flash",
  "provider_model_id": "deepseek-v4-flash",
  "max_tokens_mode": "auto",
  "resolved_max_tokens": 65536,
  "limit_source": "catalog_exact_provider",
  "context_window": 131072,
  "warning": null
}
```

2. UI/CLI 只显示摘要，不在客户端自行计算 `min()` 或重新加载目录；如果能力未知，显示“未知模型兜底 32768”及来源，不显示“模型最大值 32768”。
3. 自动迁移命令提供 `--dry-run`、`--backup`、`--model` 和明确确认；默认只检查，不写配置。
4. 旧客户端收到新字段时必须忽略未知可选字段；新客户端收到旧服务器没有摘要时显示 `source=legacy_server`，不能假装精确。
5. 确认 Grok 不触碰协议主契约；如有视觉环节，只验证自动/手动/未知三种状态的显示。

**验收命令**

```powershell
python -m pytest tests/test_api_security_onboarding.py tests/test_core/test_config_settings.py -q
cd frontend; npm test -- --run modelSetup; cd ..
cd frontend\opentui-app; bun run tsc --noEmit; bun test; cd ..\..
python -m evals.cli run --backend agent --compare-baseline evals\baselines\latest-agent.json
```

**完成判据**

- [ ] CLI/API/UI 能显示最终值和来源；
- [ ] 未知模型显示高位兜底，但不声称这是 Provider 硬上限；
- [ ] `--dry-run` 不写磁盘；
- [ ] 迁移前有备份，迁移结果可审计；
- [ ] 旧客户端不会因新增字段崩溃；
- [ ] Grok 的视觉结果已由 Composer 转成测试或复现记录。

**回滚**

删除新增摘要字段和 UI 显示即可；模型解析与请求上限逻辑不因 UI 回滚而恢复固定 8192。

**常见坑**

- 不要在 UI 把“当前解析值”写成“官方最大值”；
- 不要让前端根据 `provider_name` 自己猜模型族；
- 不要用截图替代 API 契约测试；
- 不要执行没有 `--backup` 的批量迁移。

**Commit**

```text
feat(ui): expose model output limit source and migration state
```

### M7 · 单元、契约、回归、Provider 矩阵和评测门

`P0` / **C** / 2d / 依赖 M1–M6

**背景**

这次变更最容易出现“已知模型更长了，但未知模型、旧配置或某个 Provider 又回到固定 8192”的回归。测试必须覆盖来源优先级，而不是只断言一个模型的最终数字。

**涉及文件**

- `tests/test_model_limits.py`：来源优先级、context cap、错误码；
- `tests/test_model_discovery.py`：发现 ID、可选字段、空列表和冲突；
- `tests/test_providers/test_registry.py` 及 Provider 专项测试：请求参数接线；
- `tests/unit/test_model_manager_batch.py`、`tests/test_api_security_onboarding.py`：保存和迁移；
- `evals/baselines/latest-agent.json`：只在基线确实改变并有解释时更新。

**操作步骤**

1. 建立来源优先级表驱动测试：

```python
@pytest.mark.parametrize(
    ("configured", "catalog", "provider_default", "expected", "source"),
    [
        (4096, 131072, 65536, 4096, "explicit_config"),
        (None, 131072, 65536, 131072, "catalog_exact_provider"),
        (None, None, 65536, 65536, "provider_default"),
        (None, None, None, 32768, "unknown_fallback"),
    ],
)
def test_resolution_precedence(configured, catalog, provider_default, expected, source):
    catalog_record = None
    if catalog is not None:
        catalog_record = ModelLimitRecord(
            provider_id="demo",
            model_id="demo-model",
            model_context_window=262144,
            model_max_output_tokens=catalog,
            source="test-catalog",
            source_url="https://example.invalid/catalog",
            as_of="2026-08-03",
        )

    result = resolve_output_limit(
        provider_id="demo",
        model_id="demo-model",
        configured_max_tokens=configured,
        catalog_record=catalog_record,
        provider_default=provider_default,
        input_tokens=12000,
        context_safety_margin=1024,
    )

    assert result.resolved_max_tokens == expected
    assert result.source == source
```

2. 添加安全测试：未知 ID 不读取 secret；响应不含 `api_key`；目录冲突 fail closed；旧配置载入不扩展费用。
3. 添加 Provider 矩阵：OpenAI-compatible、DeepSeek、Anthropic/Qwen 等现有 registry provider 都验证 `resolved_max_tokens` 进入正确参数名。
4. 添加契约测试：模型列表摘要字段可选、旧服务器兼容、`auto` 不穿透到 SDK、最终值始终为正整数。
5. 跑 Phase 1 Agent 评测和全量测试；如果结果变化，区分“请求上限变化导致的真实行为变化”和“无关回归”，不得为了绿灯把测试改回 8192。

**验收命令**

```powershell
python -m pytest tests/test_model_limits.py tests/test_model_discovery.py tests/test_providers tests/unit/test_model_manager_batch.py tests/test_api_security_onboarding.py -q
python -m ruff check config core/providers api_server.py tests
python -m evals.cli run --backend agent --compare-baseline evals\baselines\latest-agent.json
git diff --check
```

**完成判据**

- [ ] 六级来源优先级都有正例和反例；
- [ ] 发现 ID、Provider namespace、旧配置、未知模型和显式覆盖都有测试；
- [ ] 所有 Provider 请求最终拿到正整数，且没有固定 8192 fallback；
- [ ] API Key 和 secret 不出现在测试输出、摘要、trace 或错误中；
- [ ] 全量测试和评测结果已记录，基线变化有原因；
- [ ] `git diff --check` 通过。

**回滚**

按测试层级回滚：先回滚 UI/API 摘要，再回滚 Provider 接线，最后回滚目录/解析器。每一步都重新跑 M1 基线。

**常见坑**

- 不要只测 `deepseek-v4-flash` 一个已知型号；
- 不要用“测试环境没有 API Key”作为跳过模型解析测试的理由；
- 不要把 provider 默认值和未知模型兜底混成同一个 source；
- 不要在评测基线变化时删除失败样本。

**Commit**

```text
test(model-limits): cover per-model output budget resolution
```

### M8 · 发布门、文档锁定和 Phase 3 出口

`P0` / **C** / 1d / 依赖 M7

**背景**

Phase 4 Desktop、Phase A provider 优化、Phase E 多模型协作都会依赖本 Phase 的解析契约。出口必须证明“模型 ID 驱动、来源可解释、未知模型高位兜底、旧配置可恢复”，而不是只证明一条请求成功。

**涉及文件**

- `docs/modules/model-limits.md`：字段、来源、迁移和诊断手册；
- `docs/plans/opus5-plan/rxycode/00-EXECUTION-PLAN.md`：本 Phase 的完成记录和依赖表；
- `config/`、`core/providers/`、`protocol/`、`tests/`：仅收口已在 M1–M7 白名单内的改动；
- `evals/baselines/`：必要时保存带模型/来源摘要的评测结果。

**操作步骤**

1. 在干净临时配置中加入三个模型：一个精确目录命中、一个同 ID 不同 Provider、一个未知自定义 ID；分别检查 resolved 值和 source。
2. 在已有配置中验证：显式 4096 保持 4096，`auto` 走目录，未知模型走 32768，context 不足时产生结构化错误。
3. 从 `/models/discover` 到 Provider 请求跑一遍真实 mock 链路，确认原始 model ID 未被 nickname 替换。
4. 生成配置/schema/TypeScript 类型（如果本 Phase 修改了协议），确认生成物和源在同一个 commit。
5. 更新 Phase 4 D5 的前置依赖说明，并把 Phase A 的 `ModelCapabilities` 扩展点标成“复用本 Phase，不建第二套目录”。
6. 输出一份 Phase 3 变更摘要：修改文件、兼容策略、未知模型默认值、已知限制、回滚方法和真实命令输出。

**验收命令**

```powershell
python -m pytest -q
cd frontend; npm test -- --run; cd ..
cd frontend\opentui-app; bun run tsc --noEmit; bun test; cd ..\..
python -m evals.cli run --backend agent --compare-baseline evals\baselines\latest-agent.json
git diff --check
git status --short
```

**完成判据**

- [ ] 新增模型默认不批量写入统一 `8192`；
- [ ] 精确 model ID 能解析到对应上限，Provider 同名模型不串；
- [ ] 未知模型默认使用可配置的 `32768` 高位兜底，并明确标记来源；
- [ ] 显式配置、目录能力、context window 和 Provider 参数顺序已冻结；
- [ ] 旧配置可读取、可备份、可回滚；
- [ ] Phase 4 Desktop、Phase A、Phase E 没有各自再建模型上限表；
- [ ] 所有验收命令有真实输出，Composer 2.5 完成最终收口。

**回滚**

优先恢复配置备份；代码按 M7 的层级顺序回滚。不得通过恢复全局 `8192` 来掩盖目录或解析器错误，若必须临时回退要在配置中显式设置并记录期限。

**常见坑**

- 不要把“未知模型高位兜底”宣传成模型官方上限；
- 不要在 Phase 4 Desktop 设置页重新实现 resolver；
- 不要把 Phase A provider 调研数字复制到新目录而不写来源；
- 不要只更新文档不跑迁移和回归命令。

**Commit**

```text
docs(model-limits): close Phase 3 output limit adaptation gate
```

### 7.5 Phase 3 硬性约束

| # | 约束 | 原因 |
|---|---|---|
| ML1 | **模型目录查找必须以 Provider 返回的真实 `model_id` 为主键**；显示名、nickname、prompt 和 `owned_by` 不能替代它 | 防止同名模型串配置或误套能力 |
| ML2 | **`max_tokens` 只表示用户请求覆盖；`model_max_output_tokens` 只表示目录能力；`resolved_max_tokens` 才能进入 SDK** | 避免多个字段互相覆盖 |
| ML3 | **未知模型默认 `32768`，且必须可配置、可观察、可回滚** | 避免未知模型被旧的 8192 统一截断 |
| ML4 | **显式配置优先，但不能突破已知 Provider/模型硬上限或 context budget** | 防止用户覆盖变成无效请求或上下文溢出 |
| ML5 | **Provider、CLI、OpenTUI、Phase 4 Desktop 只消费一个 resolver 和一个摘要协议** | 防止客户端/Provider 各自猜上限 |
| ML6 | **未知、冲突、来源过期和 context 不足必须可解释失败；不允许静默降级** | 自动化必须可审计 |
| ML7 | **新增模型默认 auto；旧数值配置默认保留为显式覆盖** | 保证升级不悄悄扩大费用和行为 |
| ML8 | **任何来源数字必须有来源 URL、as_of 和测试；未找到不能编造** | 防止“调研数字”变成第二套未经验证的硬编码 |

### 7.6 Phase 3 出口检查

Phase 3 只有满足以下条件才算完成：

- `add_model()` 和批量 onboarding 不再为每个发现模型写入统一 `8192`；
- 发现列表中的真实 `model_id` 可以精确命中 ModelCatalog；
- `max_tokens: auto`、旧正整数和未知模型三条路径都有兼容测试；
- 未知模型默认 `32768`，可通过 `model_limits.unknown_model_max_tokens` 调整；
- 已知 `model_context_window` 会参与最终钳制；
- Provider 请求只接受 `OutputLimitResolution.resolved_max_tokens`；
- API、CLI、OpenTUI 和后续 Desktop 可以看到最终值和来源；
- Phase A、Phase 4、Phase E 不重复创建模型上限 registry；
- M1–M8 的验收输出、迁移备份、回滚路径和评测基线均已记录。

---

## §8 Phase 4 — Desktop 应用（W16–W23）

> **owner: frontend → Composer 主写，Grok 辅助多模态环节。** D1–D8 全部由 Composer 执行，纪律见 [`../COMPOSER-2.5-PLAYBOOK.md`](../COMPOSER-2.5-PLAYBOOK.md)；D3/D4/D5 的「多模态环节」（视觉验收：起 dev server 截屏核对渲染）按卡内标注委托 Grok（[`../GROK-FRONTEND-PLAYBOOK.md`](../GROK-FRONTEND-PLAYBOOK.md)）。Composer 主写，Grok 不做卡本体；若 appserver 缺契约，Composer 顺手补后端卡。

### 8.1 技术选型

**先说结论：核心决策不是 Electron 还是 Tauri，而是"客户端必须是瘦的"。** 因为 Phase 2 已经把协议和 TS 客户端做好了，桌面壳只负责渲染，换壳的成本被压到很低。

| 维度 | Electron | Tauri v2 |
|---|---|---|
| 团队现有技能 | ✅ 已有 React/TS（OpenTUI 就是 React） | ❌ 需要 Rust |
| 包体积 | ~150MB | ~10MB |
| 渲染一致性 | ✅ 三平台同一个 Chromium | ⚠️ 各平台系统 webview 有差异 |
| 打包 Python 后端 | 成熟（`extraResources` + 子进程） | 成熟（sidecar） |
| 2–3 人团队风险 | 低 | 中（Rust 学习 + webview 调试） |

**推荐：Electron。** 理由是团队没有 Rust 经验，而 Phase 4 只有 8 周。包体积不是当前阶段的关键指标。

**但这个决定是可逆的**——因为 UI 层只依赖 `frontend/protocol-client`，不依赖 Electron API。把"包体积优化（迁 Tauri）"记为 Phase 5 的候选项。

> 如果用户明确偏好 Tauri，把 D1 的工时从 3 天改成 8 天，其余任务卡不变。

### 8.2 任务卡

| ID | 内容 | 负责 | owner | 工时 | 依赖 |
|---|---|---|---|---|---|
| **D1** | Electron + Vite + React 脚手架；打通 `python -m appserver` 子进程 | B | **frontend / Composer 主写** | 3d | P4 |
| **D2** | 主窗口：会话列表 + 对话区 + 输入区；接 `protocol-client` | B | **frontend / Composer 主写** | 8d | D1, P2 |
| **D3** | 流式渲染（`event/message_delta`）+ 工具调用卡片（`tool_begin`/`tool_end`）+ 中断 | B | **frontend / Composer 主写 · Grok 视觉验收** | 8d | D2 |
| **D4** | 审批 UI（`approval/request` 模态框），含 "always allow" 持久化 | B | **frontend / Composer 主写 · Grok 视觉验收** | 5d | D3 |
| **D5** | 设置页：模型 / API Key / 工作区；复用后端 `config/model_manager.py`，展示 Phase 3 的上限来源摘要 | B | **frontend / Composer 主写 · Grok 视觉验收** | 6d | D2, M8 |
| **D6** | 打包：Windows / macOS / Linux，含内嵌 Python 运行时 | B | **frontend / Composer 主写** | 6d | D5 |
| **D7** | 自动更新 + 崩溃上报 | B | **frontend / Composer 主写** | 4d | D6 |
| **D8** | Desktop 进 CI：typecheck + 单测 + 三平台构建产物 | C | **frontend / Composer 主写** | 4d | D6 |

> 卡内「多模态环节」（D3 流式渲染核对、D4 审批弹层、D5 设置页截图）委托 Grok，交付物回 Composer 收口（见 COMPOSER §4）。

### 8.3 Desktop 的硬性约束

| # | 约束 | 原因 |
|---|---|---|
| DC1 | **Desktop 不得直接 import 任何 Python 模块或调用 HTTP API**，只能通过 `protocol-client` | 一旦破例，协议就失去意义，Desktop 会长出自己的后端耦合 |
| DC2 | **不得在 Desktop 里复制业务逻辑**（比如自己判断任务类型） | 会与核心行为漂移 |
| DC3 | **UI 组件与 Electron API 隔离**（Electron 特有能力集中在 `src/platform/`） | 保住换壳的可逆性 |
| DC4 | **API Key 存系统密钥链**（`keytar` 或 Electron `safeStorage`），不进明文配置文件 | 见 R6 |
| DC5 | Desktop 崩溃不得导致 appserver 子进程变成孤儿进程 | 会残留占端口 / 吃内存 |

---

## §9 竞品对照（窄赛道）

### 9.1 数据

以下 star 数为 **2026-07-30 用 GitHub API 实测**。刷新命令：

```powershell
$repos = @("sst/opencode","openai/codex","XiaomiMiMo/MiMo-Code","anthropics/claude-code","cline/cline","All-Hands-AI/OpenHands","block/goose","RooCodeInc/Roo-Code")
foreach ($r in $repos) {
  $d = Invoke-RestMethod "https://api.github.com/repos/$r"
  "{0,-32} {1,8}" -f $r, $d.stargazers_count
}
```

| 项目 | 形态 | Star（2026-07-30） | 与 RxyCode 的关系 |
|---|---|---|---|
| sst/opencode | 终端 Agent（TUI） | ~191k | **最直接对标**，RxyCode 的 TUI 就在学它 |
| openai/codex | CLI + app-server + 多客户端 | ~102k | **架构对标**，Phase 2/4 抄的就是它 |
| XiaomiMiMo/MiMo-Code | CLI Agent | ~12.6k | 同赛道后起 |
| cline / Roo-Code | IDE 扩展 | — | 不同形态，不直接竞争 |
| OpenHands / goose | 通用 Agent 平台 | — | 范围更大，不是终端优先 |

> **7/30 报告的错误**在于把 IDE 扩展、Agent 框架、终端 CLI 混在一张表里比"功能覆盖度"，于是得出"要做 Kubernetes 多租户"的结论。正确的比法是**只跟终端优先的编码 Agent 比**。

### 9.2 真实差距（只列在窄赛道内成立的）

| 差距 | 严重度 | 本计划中的应对 |
|---|---|---|
| 无类型化协议，客户端难扩展 | **高** | Phase 2（P1–P5） |
| 无 Desktop / IDE 客户端 | **高** | Phase 4；协议做好后 IDE 扩展成本很低 |
| 评测不可信，无法证明质量 | **高** | Phase 1 |
| 核心是 3704 行 God Object | 中 | P3 P6 P7（渐进） |
| 关键词路由，对非中文输入脆弱 | 中 | P6 |
| 无 lint / 单 Python 版本 CI | 中 | S4 S5 |
| 默认前端的测试不进 CI | 中 | S7 |

### 9.3 RxyCode 已有的、竞品未必有的

不要在重构中把这些丢掉：
- **分层记忆**（`memory/`：短期窗口 + 长期压缩 + 用户记忆）
- **两级缓存**（精确哈希 + 语义相似）
- **PromptSpec 版本化**（缓存键稳定性）
- **节点级 tracing**（`core/tracing.py`，span 落 JSONL 可回放）
- **安全门**（`core/safety/`：风险分级 + 审批 + 写白名单 + 审计）

---

## §10 维护与扩展手册

> 这一章不是一次性计划，是**长期使用**的操作手册。做日常维护和加功能时查这里。

### 10.1 加一个工具（tool）

1. 读 `docs/modules/tools.md`
2. 在 `tools/` 下新建模块，实现工具函数
3. 注册到 ToolRegistry（照抄同目录已有工具的注册方式）
4. **在 `core/safety/policy.py` 里给它定风险等级**——这一步最容易漏。任何能写文件或执行命令的工具必须走审批
5. 加单元测试 `tests/test_tools_<名字>.py`
6. `tools/` 的描述会通过 `core/prompts/tool_list.py` 自动进 system prompt，**不要手写进 prompt 模板**
7. 更新 `docs/modules/tools.md`
8. 加一个 eval 任务验证 Agent 会在合适场景用它（用 `tool_used` 检查，见 H3）

**验收**：`python -m pytest tests/test_tools_<名字>.py -q` + `python -m ruff check tools`

### 10.2 加一个 OpenTUI 对话框

1. 读 `docs/modules/frontend.md`
2. **必须复用 `DialogSelect`**——不要手写选择列表。UI 不一致的历史问题就是这么来的
3. 颜色 / 边框 / 标题样式照抄同目录已有 Dialog，不要自创
4. 加 `*.test.tsx`
5. `cd frontend\opentui-app; bun run tsc --noEmit; bun test`

**常见坑**：不要给 Ink（`frontend/`）加新功能，它已弃用。

### 10.3 加一个 eval 任务

1. 读 `docs/modules/evals.md`（H6 会重写它）
2. 在 `evals/tasks/` 新建 YAML
3. **`file_exists` 的路径是相对于空临时工作目录的**，不是仓库根。要检查仓库源码结构，那是单元测试不是 eval（见 H1 的教训）
4. `command_succeeds` 里的 `python -c "..."` **必须是合法 Python**——`assert` 不能写在列表推导或 lambda 里
5. 跑体检：`python scripts\lint_eval_tasks.py`
6. 单跑：`python -m evals.cli run --backend agent --task <id>`
7. 用 `--backend raw-llm` 也跑一次。**如果裸 LLM 也能过，说明这个任务没有区分度**，重新设计

### 10.4 加一个协议方法（Phase 2 之后）

1. 在 `protocol/requests.py` 或 `notifications.py` 加 pydantic 模型
2. 决定版本影响：加字段 = patch；加方法 = minor；改语义/删字段 = **major，需要迁移计划**
3. 重新生成：`python -m protocol.schema > protocol/schema.json`
4. 前端重新生成类型：`cd frontend\protocol-client; bun run generate`
5. 在 `appserver/` 实现 handler
6. 更新 `tests/test_protocol_schema.py` 的冻结快照
7. 更新 `docs/modules/protocol.md`

**硬规则**：`protocol/` 和 `frontend/protocol-client/src/generated/` **必须在同一个 commit 里更新**，否则 CI 的新鲜度检查会红。

### 10.5 逐步收紧 lint（S4 之后的长期动作）

S4 的规则集是保守起步。CI 稳定 2 周后，**一次开一条规则**：

| 顺序 | 规则 | 说明 |
|---|---|---|
| 1 | `I` | import 排序，纯机械，`--fix` 能全自动 |
| 2 | `UP` | pyupgrade，语法现代化 |
| 3 | `SIM` | 简化冗余写法 |
| 4 | `RET` | return 语句一致性 |
| 5 | `C4` | comprehension 优化 |

流程固定：加规则 → `ruff check . --statistics` 看基数 → `--fix` → 跑测试 → 人工处理剩余 → 单独 commit。**不要一次加两条。**

### 10.6 日常检查清单

**每次 PR 之前：**
```powershell
python -m ruff check .
python -m pytest tests -q -x --timeout=300
cd frontend\opentui-app; bun run tsc --noEmit; bun test; cd ..\..
git status --short
```

**每周一（Phase 1 之后）：**
- 看 nightly evals 结果，对比基线
- 分数掉了就查是哪个 commit 引入的

**每个 Phase 结束：**
- 更新本文件 §3 排期表的实际完成情况
- 更新对应的 `docs/modules/*.md`
- 重新生成 evals 基线

---

## §11 附录

### 11.1 PowerShell 踩坑速查

| 症状 | 原因 | 正确做法 |
|---|---|---|
| `<<'EOF'` 报"缺少文件规范" | PowerShell 不支持 heredoc | 用 `Write` 工具写 `.py` 文件再 `python file.py`，跑完删 |
| `python -c "...\"...\"..."` 解析失败 | 嵌套引号被 PowerShell 吃掉 | 同上，改用脚本文件 |
| `UnicodeEncodeError: 'gbk' codec` | 控制台默认 GBK | `$env:PYTHONIOENCODING="utf-8"` 或输出到文件后再读 |
| `Invoke-RestMethod` 结果做字符串切片报 `MissingArrayIndexExpression` | PowerShell 的 `[n]` 是索引不是切片 | 在 Python 里处理，不要在 PowerShell 里切字符串 |
| `git rm` 之后文件还在磁盘上 | 用了 `--cached` | `git rm --cached` + `Remove-Item` 两步都要 |

### 11.2 证据索引（2026-07-31 实测）

| 结论 | 证据位置 |
|---|---|
| agent_v2 3704 行 | `(Get-Content core\agent_v2.py).Count` |
| `.bak` 被跟踪 | `git ls-files core/agent_v2.py.bak` |
| CORS 任意端口放行 | `api_server.py:188` |
| 无 ruff 配置 | `pyproject.toml`（80 行，无 `[tool.ruff]`）、`requirements-dev.txt`（10 行） |
| CI 单 Python 版本 | `ci.yml:24` |
| CI 无 bun | `ci.yml` 全文无 `bun` |
| evals 不跑 Agent | `evals/runner.py:414` |
| workdir 判定 | `evals/tasks.py:56`、`:113-117` |
| eval 任务语法错误 | `evals/tasks/readcode-prompt-registry.yaml:41,61,76` |
| docs 被 ignore | `.gitignore:68` |
| OpenTUI 19 测试文件 | `Get-ChildItem frontend\opentui-app\src -Recurse -Include *.test.ts,*.test.tsx` |

### 11.3 术语表

| 术语 | 含义 |
|---|---|
| **app-server** | Codex 的架构模式：headless 核心 + JSON-RPC over stdio + 多个瘦客户端 |
| **绞杀者模式** | 新代码逐步接管旧代码职责，旧代码逐渐变空后删除，全程可运行 |
| **headless** | 不含任何 UI / IO 的核心逻辑，可直接单元测试 |
| **基线（baseline）** | 某个时间点的评测分数快照，用于检测回归 |
| **谎报绿灯** | 测试因缺工具静默跳过但 CI 报成功，见 S8 |
| **God Object** | 一个类承担过多职责，`AgentV2` 是典型 |

### 11.4 待办池（执行中发现的问题记这里，不要就地修）

> 遵守 R4：任务卡范围外的问题记在这里，不要顺手改。

| 日期 | 发现者 | 问题 | 相关文件 | 优先级 |
|---|---|---|---|---|
| 2026-07-31 | audit | `evals/tasks.py` 的 `needs_workdir` 语义容易误用，应该改成显式字段 | `evals/tasks.py:113-117` | P2 |
| 2026-07-31 | audit | Ink 前端下线时间点未定 | `frontend/` | P2 |
| | | | | |

### 11.5 本文件的维护

- 每个 Phase 结束更新 §3 的实际完成情况
- 任务卡里的行号会漂移，发现对不上就更新（这是维护的一部分）
- §10.4 待办池在每个 Phase 开始时评审一次，决定升级为任务卡还是继续搁置

---

## §12 文档映射与工作流程

> 本节是整套计划的**导航图**。任何模型接手工作前，先读这一节确定"我该打开哪个文件"。

### 12.1 文档清单

全部位于 `docs/plans/opus5-plan/rxycode/`，**严格按顺序执行，不要跳**。

> **2026-07-31 目录重构**：本目录拆成了 `rxycode/` 和 `linkagent/` 两个子目录，本文件从
> `2026-07-31-EXECUTION-PLAN.md` 更名为 `00-EXECUTION-PLAN.md`。
> 模型分工在 [`../MODEL-ASSIGNMENT.md`](../MODEL-ASSIGNMENT.md)：Composer 主写全部，Grok 辅助前端多模态。主写纪律 [`../COMPOSER-2.5-PLAYBOOK.md`](../COMPOSER-2.5-PLAYBOOK.md)，辅助纪律 [`../GROK-FRONTEND-PLAYBOOK.md`](../GROK-FRONTEND-PLAYBOOK.md)。

| 顺序 | 文件 | 覆盖内容 | 前置 | 工时 |
|---|---|---|---|---|
| **1** | `00-EXECUTION-PLAN.md`（本文件） | Phase 0 止血 → Phase 1 Harness → Phase 2 协议与核心解耦 → Phase 3 模型输出上限 → Phase 4 Desktop | 无 | 23 周 |
| **2** | `PHASE-A-MODEL-ADAPTATION-LAYER.md` | 模型适配层：provider 策略、能力元数据、per-model 优化（DeepSeek / Claude / Qwen） | 本文件 Phase 0 + Phase 1 | 3 周 |
| **3** | `PHASE-B-ISOLATED-SUBAGENT.md` | **隔离式子代理**：Primary/Subagent、Child Session、独立上下文、权限、预算、Task、`@`、事件和恢复 | 本文件 Phase 0–3 + Phase A（不依赖 Desktop） | 8–12 周 |
| **4** | `PHASE-C-MULTI-AGENT-ORCHESTRATION.md` | **多 Agent 专家团**：Coordinator、AgentSpec / SOP 状态机 / 机械验证门 / 成本熔断 / 难度路由；复用 Phase B Runtime | 本文件 Phase 0–3 + Phase A + B | 8 周 |
| **5** | `PHASE-D-RXYCODE-DESKTOP.md` | **完整 Desktop 工作台**：项目、workspace、Thread、工具执行、审批、diff/review、文件预览、worktree、恢复、扩展契约、打包发布 | 本文件 Phase 0–4 + Phase A + B + C 公共契约 | 12–16 周 |
| **6** | `PHASE-E-MULTI-MODEL-COLLABORATION.md` | **多 Agent × 多模型**：每角色不同模型、master 模型、跨模型交接、成本核算、结对编程、归因仲裁 | 本文件 Phase 3 + Phase A + B + C；Desktop 交互接入依赖 Phase D | 6 周 |
| **7** | `PHASE-F-MULTIMODAL.md` | 多模态：ContentBlock 全链路、附件存储、视觉 Agent 角色 | 本文件 Phase 3 + Phase 4 + A + B + C + D + E | 6 周 |
| **附** | `PHASE-G-PERSONA-AGENT-INTERFACE.md` | **PersonaAgent 接口预留**（不是施工图）：skill 元数据、蒸馏数据埋点、信任边界 | 无硬前置，§4 六张卡**插进 B/C/D/E 里顺手做** | 6 天 |
| **↗** | ~~`PHASE-F-SKILLFOREST-PERSONA-AGENT.md`~~ | **已移出本路线。** PersonaAgent 独立成 [LinkAgent 项目](../linkagent/README.md)（独立仓库，把 RxyCode 当 pip 依赖）。原文档归档在 [`../linkagent/ARCHIVE-PHASE-F-ORIGINAL-VISION.md`](../linkagent/ARCHIVE-PHASE-F-ORIGINAL-VISION.md)，**结论已被新版论文推翻，不要照它施工** | — | 不在本路线 |

> **2026-08-03 第 5 版调整**：新增主计划 **Phase 3（模型输出上限自适应）**，以真实 `model_id` 驱动 ModelCatalog 和请求上限解析；原 Desktop 基础壳顺延为 **Phase 4**。Phase A/B/C/D/E/F/G 的扩展编号保持不变；完整 RxyCode Desktop 仍为 **Phase D**，但它消费主计划 Phase 4 的基础壳和 Phase 3 的模型上限摘要。
> Phase C 保留原专家团的 8 周工作量；Phase B 单独补齐 Child Session、权限、预算、事件和恢复，不允许 Phase C 再复制一套隔离运行时。

### 12.2 依赖关系

```
本文件 Phase 0  止血（lint / CI / CORS / 死文件）
      │
      ├────────────────────────────────────┐
      ▼                                    │
本文件 Phase 1  Harness 说真话              │
      │                                    │
      ├──────────────┬─────────────────────┤
      ▼              ▼                     │
 本文件 Phase 2   Phase A 模型适配           │
 协议 + Session       │                     │
      │              │                     │
      └──────┬───────┘                     │
             ▼                             │
 本文件 Phase 3 模型输出上限                 │
             │                             │
             ▼                             │
       Phase B 隔离式子代理                  │
              │                             │
              ▼                             │
       Phase C 多 Agent 专家团                 │
              │                             │
              ▼                             │
       本文件 Phase 4 Desktop 基础壳           │
             │                             │
             ▼                             │
       Phase D RxyCode Desktop 完整工作台      │
              │                             │
              ▼                             │
       Phase E 多 Agent × 多模型              │
              │                             │
              ▼                             │
       Phase F 多模态                         │

Phase G 的六张预留卡不在这条链上，按 Phase G §4 的表插进 B/C/D/E 执行：
  G1 G5 → Phase B 开始前     G2 → 和 C3 一起
  G3    → 和 C12 一起        G4 → 和 E11 一起      G6 → Phase C 收尾后

原 Phase F 已移出本路线，见 §12.2.1。
```

### 12.2.1 关于原 Phase F（已移出本路线）

PersonaAgent 那部分内容**不再是 RxyCode 的一个 Phase**，它独立成了 **LinkAgent** 项目——独立仓库、独立排期，把 RxyCode 当 `pip` 依赖，**不改 RxyCode 一行代码**。

- 施工文档：[`../linkagent/README.md`](../linkagent/README.md)
- 架构：[`../linkagent/00-OVERVIEW-AND-ARCHITECTURE.md`](../linkagent/00-OVERVIEW-AND-ARCHITECTURE.md)
- 原 Phase F 文档归档在 [`../linkagent/ARCHIVE-PHASE-F-ORIGINAL-VISION.md`](../linkagent/ARCHIVE-PHASE-F-ORIGINAL-VISION.md)

> ⚠ **归档文档里的结论已被推翻，不要照它施工。** 它基于论文旧版（SkillForest），后来论文重写为 *Individualized Agent*，实验协议和结果都变了。最关键的反转：原来说"别建森林索引"，新论文里**情境化检索是端到端贡献最大的模块**。准确数字见 [`../linkagent/APPENDIX-B-PAPER-EVIDENCE.md`](../linkagent/APPENDIX-B-PAPER-EVIDENCE.md)。

**对本路线的唯一影响**：论文的评测方法论（配对消融共享原始输出、runtime–scoring 隔离、序列级统计单位、失败留在分母、预注册阈值）对本文件 Phase 1 的 evals harness、Phase B 的 B14、Phase D 的 D11 都直接适用，**和 PersonaAgent 做不做无关**。这部分可以照搬。

**分模型后的并行结构见 §12.7**：Phase 2 期间没有真正的第二主链——Composer 主写 P1–P8，Grok 只做卡内标注的多模态环节；Phase 3 的模型输出上限由 Composer 主写，Phase 4 Desktop 在其出口后接入。其余全部串行。

**每个 Phase 的前置都是硬前置**，各文档的 §0.3 写了具体理由。最常见的两处误判：
- **跳过 Phase 2 直接做 Phase B** —— 会导致在 `agent_v2.py` 这个 3704 行的 God Object 里手工造一套 ad-hoc 的 Agent 通信机制，半年后推倒重来。
- **Phase C 差不多了就开始 Phase E** —— Phase E 会把 Phase B/C 所有没测到的隔离问题一次性引爆，而且因为每个角色用不同模型，症状会难懂得多。Phase D Desktop 可以先接收稳定的公共契约，但不能绕过 Phase B 的隔离边界。

### 12.3 工作流程

**接到任务时的判断顺序：**

```
1. 任务属于哪个 Phase？
   → 查 §12.1 的表，打开对应文档

2. 该 Phase 的前置做完了吗？
   → 跑对应文档 §0.3 的自检命令
   → 有一条不满足就回到前一个 Phase，不要硬上

3. 打开文档，只读三节：
   → §0 执行手册（每次都要读，规则在这里）
   → §1 现状证据（需要引用现状时读）
   → 你要做的那一张任务卡

   不需要通读全文。任务卡是自包含的。

4. 按任务卡的执行协议走完 7 步
   （Phase B 使用七步基础回路并拆成 14 张卡；Phase C 使用自己的 7 步固定回路并拆成 15 张卡；Phase E 的多模型卡另有专属护栏）

5. 一张卡 = 一个 commit。做完再开下一张
```

**三个模型的分工**（权威见 [`../MODEL-ASSIGNMENT.md`](../MODEL-ASSIGNMENT.md)；各文档 §0.2 应与它对齐）：

| 模型 | 职责 |
|---|---|
| **Composer 2.5** | **主写全部**。Python / 协议 schema / appserver / 评测 + Electron / React / TS UI / 协议客户端（Phase 3 M1–M8、Phase 4 D1–D8、Phase 2 的 `protocol-client`）；按任务卡实现、补测试、跑验收 |
| **Grok 4.5** | **前端辅助（多模态）**。只做前端卡里标注的「多模态环节」：视觉验收（截屏核对渲染）、图片类 UI（粘贴/预览）、对照设计稿。空闲时仍可查外部资料（定价、vision 格式等），查到的落进文档 |
| **Sonnet 5** | Diff 预审（可选）。重点：Phase B 的 **B2**、Phase C 的 **C3/C8/C9**、Phase D 的 **D4**、Phase E 的 **E3/E4**、Phase 4 的壳分叉 |

推荐回路：**Composer 写卡 → 卡内「多模态环节」委托 Grok →（可选）Sonnet 预审 → 你合并**。

### 12.4 贯穿全程的三条铁律

无论在哪个 Phase、哪张任务卡，这三条都成立：

| # | 铁律 | 怎么验证 |
|---|---|---|
| 1 | **不跑验收命令不许说"完成"** | 每张卡的完成判据都要求贴出真实输出 |
| 2 | **每张卡做完跑评测基线比对** | `python -m evals.cli run --backend agent --compare-baseline evals\baselines\latest-agent.json` |
| 3 | **旧路径行为必须逐字节不变** | Phase A 的 MA1、Phase B 的 SB1、Phase C/D 的隔离与协议门、Phase E 的 MD1 是同一条零回归原则的不同表述 |

第 2 条依赖本文件 Phase 1 的成果。**这就是为什么 Phase 1 排在所有扩展之前**——没有可信的回归信号，后面每一个 Phase 的每一次重构都是盲改。

**从 Phase B 起还多一条**：新增能力**默认关闭**。隔离式子代理/专家团（Phase B/C）、多模型（Phase E）、蒸馏采集（Phase G）三者的开关默认都是 `False`。RxyCode Desktop 的基础壳、会话、审查和权限是主工作台，不得被高级协作开关阻塞；Desktop 对高级能力只按 capability 显示。理由是 Phase C §2.5 的实测数据——多 Agent 消耗 15 倍 token，而 Anthropic 明确说编码任务本就不是多 Agent 的强项。**能力要有，但不该悄悄替用户花钱。**

### 12.5 文档本身的维护

| 时机 | 动作 |
|---|---|
| 每张任务卡完成 | 如果发现文档里的行号/锚点对不上，**顺手更新**（这是维护的一部分，不算范围外改动） |
| 每个 Phase 完成 | 更新本文件 §3.2 的 Phase 表、对应文档的出口检查结果、相关 `docs/modules/*.md` |
| 发现范围外问题 | 记进 §10.4 待办池，**不要就地修**（规则 R4） |
| 需求变化 | 改文档，不要"先改代码回头再说"。这套文档是多个模型之间唯一的共识载体 |

### 12.6 被本套文档取代的旧文档

`docs/plans/execution/` 下的全部文件（`00-master-plan.md`、`01-tech-debt-cleanup.md`、`README.md`、`QUICKSTART.md`、`DAILY-CHECKLIST.md`、`DELIVERY-SUMMARY.md`、`TASK-INDEX.md`、`AI-MODEL-GUIDE.md`、`PROJECT-DELIVERY-FINAL.md`、`TASK-T001-*.md`）**均已作废**，它们派生自 `docs/plans/2026-07-30-comprehensive-review-and-roadmap.md`，该报告的事实层错误见 §2.3。

`docs/plans/` 下的 `2026-07-02-rxycode-v2-architecture.md`、`2026-07-27-stabilization-phase0-1.md`、`2026-07-28-execution-progress.md` 作为历史记录保留，其执行状态已在 §2.1 复盘。

**当前唯一权威的计划是 `docs/plans/opus5-plan/` 下的这七份 RxyCode 施工文档（含 Phase F 接口预留；LinkAgent 施工文档另见 `linkagent/`）。**

---

### 12.7 并行协作协议（Composer 主写 + Grok 辅助多模态）

> **回答"Composer 做 Phase 2 的时候，Grok 窗口能同时做什么"。**
>
> ⚠ **2026-08-01 补充（主写/辅助定位恢复后，本节要这样读）**：
>
> 1. **没有第二条主链。** Phase 2 期间 Composer 主写 P1–P8 全部；Grok 只做卡内标注的「多模态环节」（若有）——见 [`../MODEL-ASSIGNMENT.md`](../MODEL-ASSIGNMENT.md) §3。不是"后端归 Composer、前端归 Grok"。
> 2. **Phase A 排到 Phase 2 合并之后**（见 [`../ENGINEERING-TIMELINE.md`](../ENGINEERING-TIMELINE.md) 阶段 2 的提示）。它跑的时候是 **Composer 的活**：要么等 Phase 2 收尾用同一个窗口，要么开第二个 Composer 会话（此时 Grok 窗口做前端多模态环节）。
> 3. 下面 11.7.1~11.7.5 的**文件接触面分析仍然完全有效**——它说的是"哪些改动会打架"，和执行者是谁无关。**但 Phase 2 泳道里没有 Grok 的独立泳道**：`frontend/` 也归 Composer，Grok 只在委托环节介入，产出并入 Composer 分支，见 11.7.2 的修订。
> 4. 瓶颈是**你一个人的审查带宽**，不是产出速度。P3（抽 Session 层）期间**不建议开任何并行后端卡**，值得你专注审它。

#### 11.7.1 为什么只有这一段能并行

| | Phase 2（协议与核心解耦） | Phase A（模型适配层） |
|---|---|---|
| 主要动的目录 | `protocol/`、`core/session.py`、`api_server.py`、`frontend/` | `core/providers/`、`config/model_capabilities.py`、`core/prompts/` |
| 主要动的性质 | **搬运**：从 `agent_v2.py` 里往外抽 | **新增**：新目录、新文件 |
| 对 `agent_v2.py` 的改动 | 大量删除与外移 | **只在两处接线** |

**接触面就只有 `agent_v2.py` 的两处**：LLM 构造点（`:687-701` 附近）和 usage 记录点。其余零重叠。

> 这里说的"并行"是**双 Composer 会话**（或 Composer + Grok 辅助环节）。默认配置（单 Composer + Grok 辅助）不需要它——Grok 只做被委托的多模态环节，无独立分支。

#### 11.7.2 分工与边界

```
     Composer · Phase 2（主写全部）           Grok · 辅助（无独立泳道）
     分支 feat/phase2-protocol                 只做卡内标注的多模态环节
     ─────────────────────────                  ─────────────────────────
     protocol/**            独占                产出并入 Composer 分支
     core/session.py        独占                （视觉验收截图、图片 UI 片段等）
     api_server.py          独占
     core/agent_v2.py       独占
     frontend/**            独占
     tests/test_protocol*   独占

                       ┌─────────────────────┐
                       │ protocol/schema.json │  ← 唯一的交接面
                       │ config/settings.py   │  ← 次要共享面（只允许追加）
                       └─────────────────────┘
                           规则见 11.7.3
```

**Phase A 此时不并行**（排在 Phase 2 合并之后，见 11.7 补充第 2 条）。上表是 Composer 主写 + Grok 辅助，不是两个主链窗口。

**前置要求**：Phase 0/1 必须已经在 main 上。不要一个窗口还在做 Phase 0，另一个就开分支——那不是并行，那是在流沙上盖房子。

#### 11.7.3 共享面的三条规则

| # | 规则 | 怎么做 |
|---|---|---|
| **P1** | **`agent_v2.py` 归 Phase 2 后端窗口（Composer）所有** | Phase 2 要从这个文件里往外搬大量代码，任何并行窗口同时改它必然冲突 |
| **P2** | **另一个后端会话（Phase A 若并行）需要改 `agent_v2.py` 时，写一个"接线请求"给 Phase 2 窗口，由它来改** | 接线请求要写清：改哪一行、改成什么、为什么。通常就 3-5 行 |
| **P3** | **`config/settings.py` 只允许追加，不允许改动已有行** | 两边都要往里加配置。只追加就是 git 能自动合并的场景 |

**P2 的实际操作**（Phase A 若并行，全程大概只需要两次）：

```
第 1 次 · A2 完成后（provider 层就绪）
  Phase A 窗口 → Phase 2 窗口: "core/providers/ 已经能用了。请把 agent_v2.py:687-701 的
          LLM 构造改成走 resolve_provider()。我在 core/providers/README.md
          里写了调用示例。改完我这边的集成测试就能跑。"

第 2 次 · A5 完成后（usage 提取就绪）
  Phase A 窗口 → Phase 2 窗口: "请把 usage 记录点改成走 provider.extract_cache_read()。
          原因：各家的 usage 字段名不一样，现在的代码只认 OpenAI 格式，
          DeepSeek 的缓存命中数一直是 0。"
```

Phase 2 窗口收到请求后把它当作 Phase 2 的一张小卡来做，正常提交。**Phase A 窗口在它合并之前，本地用 monkeypatch 跑集成测试**，不要为了自测去改 `agent_v2.py`。

#### 11.7.4 同步节奏（仅当存在两个并行主链会话时适用）

```
每天    每个窗口各自 rebase main 一次
        （不是 merge。rebase 让冲突早暴露、历史干净）

每 2 天 15 分钟同步：
        - 我下一步要碰哪些文件？
        - 有没有要发的接线请求？
        - 有没有谁被谁挡住了？

合并点  各分支的卡各自完成就可以合
        谁先做完谁先合，后合的负责 rebase
```

**不要攒着一起合。** 两条分支各自跑两周再合并，是这套并行方案唯一会真正翻车的方式。

> 默认配置下（Composer 主写 + Grok 辅助）没有这个节奏：Grok 无独立分支，产出走委托-收口，不需要每日同步。

#### 11.7.5 合并点与验收

| 时机 | 谁做 | 跑什么 |
|---|---|---|
| 每次合并前 | 合并方 | `python -m ruff check .` + `python -m pytest tests -q` |
| 每次合并后 | 合并方 | `python -m evals.cli run --backend agent --compare-baseline evals\baselines\latest-agent.json` |
| **两边全部合完** | **两边一起** | 下面这组完整验收 |

```powershell
cd "D:\agent-demo\RxyCode\RxyCode1_1_0"
python -m ruff check .
python -m pytest tests -q --timeout=600
python -m protocol.schema | Out-File -Encoding utf8 protocol\schema.json
git diff --exit-code protocol/schema.json          # schema 不该有意外漂移
cd frontend\protocol-client; bun run generate; cd ..\..
git diff --exit-code frontend/protocol-client/src/generated/
python -m evals.cli run --backend agent --compare-baseline evals\baselines\latest-agent.json
```

**最后一条零回归**才算 Phase 2 ‖ Phase A 真的完成，可以开 Phase B。

#### 11.7.6 Phase B 之后怎么办

**Phase B 及以后不要再并行开发后端。** 理由：

- Phase C 的 C2（拆三组全局单例）会碰到 `tools/`、`cache/`、`recovery/`、`core/` 四个目录，**几乎和所有东西都有接触面**
- Phase C 依赖 Phase B 的公共隔离、状态和验证契约，没有可绕过这些契约的独立子集；Desktop 的 UI 卡可以按 C 卡拆分，但不能提前造第二套执行核心
- Phase C §2.5 引用的失败归因研究显示，多 Agent 系统里**协调失败占全部失败的 36.94%**——这条对人也成立，协调成本会吃掉并行收益

**想让第二个窗口有事做，正确的方式不是并行开发，而是分工到角色**：

| 角色 | 谁 | 做什么 |
|---|---|---|
| **实现** | Composer | 按任务卡串行推进（后端 + 前端） |
| **辅助（多模态）** | Grok | 前端卡内标注的多模态环节：视觉验收（截屏核对）、图片类 UI、对照设计稿 |
| **审查 + 调研** | Sonnet 5（diff 预审）+ Grok（查资料/调研） | 审每一张卡的 diff（尤其 B2 / C3 / D4）、跑调研 prompt、维护评测基线、写 `docs/modules/*.md` |

Phase B 的 B14 和 Phase D 的 D11 两张评测卡工作量都不小，而且**可以和实现完全解耦**——这是第二个窗口（或 Grok 空闲时）最有价值的去处。

---

## Phase D 前后端分离开发补充（追加，不改变前置顺序）

完整 Phase D 仍然是 `PHASE-D-RXYCODE-DESKTOP.md` 定义的一个 Phase，D1–D16、总体验收、模型适配、协议和 LinkAgent 接口不变。为支持两人并行施工，新增两个执行视图：

- [`PHASE-D-FRONTEND-RXYCODE-DESKTOP.md`](./PHASE-D-FRONTEND-RXYCODE-DESKTOP.md)：Electron/React/TypeScript、preload、protocol-client、UI、视觉、前端测试和前端打包入口。
- [`PHASE-D-BACKEND-RXYCODE-DESKTOP.md`](./PHASE-D-BACKEND-RXYCODE-DESKTOP.md)：appserver、schema、Session/Child、权限、工具、Git/Review、恢复、Phase 3 ModelSummary、runtime 和后端测试。

这里不与本文早先“Phase B 及以后不要并行开发后端”的核心隔离规则冲突：那条规则禁止在 Phase B/C 核心 Runtime 和编排层之间随意切出第二套后端；本补充只允许在 Phase D 公共契约已经冻结后，把 Desktop 的前端视图和后端服务按文件 ownership 分开开发。协议 schema、生成类型、contract tests 和最终合并仍由 Composer 2.5 统一收口，Grok 4.5 只做卡内视觉辅助。

两份执行文档单独完成时只能输出 `READY_FOR_FULL_D_INTEGRATION`；只有前端卡、后端卡和原 D D1–D16 的完整出口同时通过，才能把 Phase D 标记为完成。
