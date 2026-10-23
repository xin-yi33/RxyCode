# Phase L · 内置专家团增量（Teams Increment Overlay）

> **在整条路线中的位置**：从 [`PHASE-L-TEAM-ECOSYSTEM-DISTRO.md`](../PHASE-L-TEAM-ECOSYSTEM-DISTRO.md) 拆出「**加内置团 YAML**」这一条工作流。**不是**发行版（L13/L14），**不是**跨宿主（L17），**不是**进自动路由索引（L12）。现行顺序见 [`DEV-ORDER.md`](./DEV-ORDER.md)。
> **前置条件**：`validate_team`（PHASE-F F3，`core/agents/spec.py:49`）、FXC3/S1、样例 `core/agents/teams/software_dev/`、以及 PHASE-L **LC1 / LC2 / LC11 / LC13 / LC17 / LC18 / LC19**（**引用原文，不在本文件重写条文**）。
> **不是前置**：PHASE-L L4、L10 共享角色库、L12、L13、L14、L17、L0b、PHASE-K K18、**PHASE-L 全文**。
> **后继**：L12 才把过了 F14 的团放进 L1 索引。本工作流产出的团必须保持 `ecosystem.disable_model_invocation: true`。
>
> **一句话目标**：按 L11 矩阵增加内置团数量，默关自动路由，不必等发行版。第一张能合入的产品卡是 **WFT1 · 软件工坊**。
>
> **执行模型**：Grok 4.6 主写（与 PHASE-L §0.1 同一局部例外）。审计 PASS 前不得勾完成判据。不改 `MODEL-ASSIGNMENT.md`。
> **修订**：2026-09-02（按 PHASE-L L11 卡面密度重写；纪律引用 L11 五条，不另发明编排内核）
>
> ⚠️ **本工作流最大风险：团目录进 S1，打穿 97%。** 第二大风险：照抄文档里的工具名——F11 已经错过一次（PHASE-L §6.2 勘误一）。第三：把发行版/跨宿主/进索引当成加团前置，用户要的广度永远进不了仓库。

---

## 目录

| 章节 | 内容 |
|---|---|
| [§0 执行手册](#0-执行手册必读) | 模型约束、四连、前置自检、硬规则引用、工作流级 Verdict |
| [§1 一页看懂](#1-一页看懂) | 加团 ≠ 发行版 ≠ 进索引 |
| [§2 与 L11 矩阵的接口](#2-与-l11-矩阵的接口) | 抄哪一行、五条纪律、批次 |
| [§3 目标包形态](#3-目标包形态) | 目录布局、字段、禁止事项 |
| [§4 任务卡](#4-任务卡) | WFT0–WFT2 |
| [§5 出口检查](#5-出口检查) | |
| [§6 冲突消解](#6-与既有-phase-的接口与冲突消解) | |
| [§7 证据缺口](#7-证据缺口) | |

---

## §0 执行手册（必读）

### 0.1 模型约束

**本叠加包全部内容由 Grok 4.6 主写**，审计由 GPT-5.6 独立执行。与 PHASE-L §0.1 同一局部例外，**不改** [`MODEL-ASSIGNMENT.md`](../../MODEL-ASSIGNMENT.md)。

每张卡：`READ → 契约测试先行 → 实现 → LINT/TEST → CHECK → 单 commit → 审计 PASS → 打钩`。**审计 PASS 之前不得自己勾完成判据。**

一次一张卡（PHASE-K GK1）。示例 YAML 是意图说明，以 `validate_team` 与仓库现状为准（GK5）。

### 0.2 本工作流四连（每卡必跑）

沿用 PHASE-L §0.2，但本工作流 **不跑 PERF `--mode team`**（那是 L0b/L12 的门，本工作流明确不进索引）。

| 名称 | 命令 | 守什么 |
|---|---|---|
| **PREFIX** | `python -m pytest tests/test_cache/test_s1_s2_split.py tests/test_cache/test_stable_prefix.py -q` | 团目录变大不得污染 S1（LC1 / FXC3） |
| **SPEC** | `python -m pytest tests/test_agents/test_spec.py -q` | `validate_team` 校验面不被绕过 |
| **LOAD** | 见各卡：`load_builtin_team("software_workshop")` 必须过 `validate_team` | YAML 落盘不是「看起来像」 |
| **BASELINE** | 仅当卡面写明。默认 **不要** 加 `--mode` | F14 未落地时自己加 flag 会撞车 |

> **三条施工须知（从 PHASE-L §0.2 抄来，不看会白跑）：**
>
> 1. `--mode` 现在还不存在。不要自己临时加。
> 2. 裸 `from tools.registry import registry; registry.get_names()` 返回 **`[]`**。工具名以 §0.3 第 3 条为准。
> 3. `task` 由两个工具共用一个名字。团 YAML 引用 `task` 时必须说明预期哪一种。本工作流 **默认不引用 `task`**，除非卡内写明。

### 0.3 前置自检（缺一项就停）

```powershell
cd "D:\agent-demo\RxyCode\RxyCode1_1_0"

# 1. PHASE-F schema 与样例团（本工作流真正的前置）
Test-Path core\agents\spec.py, core\agents\teams\software_dev\team.yaml, core\agents\teams\__init__.py

# 2. FXC3 的 S1/S2 拆分（LC1 的地基）
python -m pytest tests/test_cache/test_s1_s2_split.py tests/test_agents/test_spec.py -q

# 3. 真实工具名清单（写 YAML 必须核对；禁止照抄文档）
#    注意：不能只 import registry —— 工具在 register_builtin_tools() 里才注册。
python -c "import core.builtin_tool_registration as m; print(sorted({getattr(getattr(m,a),'name') for a in dir(m) if a.endswith('_tool') and isinstance(getattr(getattr(m,a),'name',None),str)}))"

# 4. 样例团能加载
python -c "from RxyCode.RxyCode1_1_0.core.agents.teams import load_builtin_team; t=load_builtin_team('software_dev'); print(t.name, len(t.members), t.extra.get('ecosystem.disable_model_invocation'))"
```

第 3 条 2026-08-18 实测 27 个名字（PHASE-L §0.4）。**开工当日以本命令输出为准**，不要把 27 写死进新团而不跑命令。样例 `software_dev/team.yaml` 头注释已写明编码团常用：`read / ls / grep / write / edit / patch / bash`。

第 1 条为假：本工作流 BLOCKED（连样例都没有，加第二支无从对照）。**不要**去等 L13。

### 0.4 硬性规则

本文件 **不重写** PHASE-L 条文。执行时打开 PHASE-L §0.3 读原文。本工作流强制引用：

| # | 一句话（指向原文，不是新规则） |
|---|---|
| **LC1** | 团目录再多，S1 一个字节都不许变 |
| **LC2** | 「内置」≠「进自动路由索引」。随包发货默认 `disable_model_invocation: true` |
| **LC11** | 成员姓名可以有，不得复用 WorkBuddy 具体姓名；复用构造法 |
| **LC13** | 第三方 skill/MCP 逐个核 license；CC-BY-NC / GPL / AGPL / NOASSERTION / 无 LICENSE 不得打包 |
| **LC16** | 禁止用 SessionStart 做团队 bootstrap |
| **LC17** | 许可口径 = GitHub `license.spdx_id`；采纳单个 skill 核到目录本体 |
| **LC18** | 依赖外部数据源的角色必须实测可达，否则不得进 L1（本工作流本来就不进 L1，但仍不得绑死数据源） |
| **LC19** | 预设团不得产出买卖建议形态的证券投资意见（WFT2 做到 #11 时生效） |
| **PC0** | 调研先行、能抄不造；卡内必须有 `Verdict:` |

另：PHASE-P **PC10** —— 卡号写 `WFT1`，禁止 `WF-BUILTIN-EXPERT-TEAMS` 当施工卡号（测试认 WFT / TEAMS-INCREMENT）。

### 0.5 工作流级调研与 Verdict

`Verdict: Extend — 本仓 software_dev + PHASE-L L11 矩阵 — 不自造编排内核。`

不抄 WorkBuddy 姓名、不抄无 LICENSE 的中文大仓、不把编排写进 `agent_v2.py`。

---

## §1 一页看懂

### 问题：用户要「增加内置专家团」，是不是要把 PHASE-L 19 张卡做完？

**不是。** PHASE-L 捆了五件独立的事（DEV-ORDER §7）。用户现在要的是 **YAML 落盘**，让 `/team software_workshop` 这种显式调用将来能选到第二支团。

| 用户可能以为必须先做 | 实际 |
|---|---|
| L13 `rxycode-teams` 仓 | 发行外壳。内置团活在 `core/agents/teams/` |
| L17 跨宿主三档编译 | 去别家 agent 还能跑。本周不加团也能活 |
| L12 进索引 | 自动路由候选。进了会顶 3s 首字。**本工作流禁止进** |
| L0b `--mode team` | 量具后半。加 YAML 不需要它 |
| L10 `shared-roles/` | 构建期展开。本工作流像 `software_dev` 一样 **内联 members** |

**好处**：广度先进入仓库；97% 命中率靠 LC2 守住；发行版与跨宿主仍按 PHASE-L 原卡走，互不改卡面。

---

## §2 与 L11 矩阵的接口

L11 是十三支团的权威矩阵。本工作流 **不重画矩阵**，只执行「YAML 落盘」那一列。打开原文：[`PHASE-L-TEAM-ECOSYSTEM-DISTRO.md` L11](../PHASE-L-TEAM-ECOSYSTEM-DISTRO.md)（约 L1237 行）。

### 2.1 本工作流认领的行

| # | 团 | 人 | 分类 | 可行性 | 核心现成资产 | 缺口 | 批次 | 本包卡 |
|---|---|:-:|---|:-:|---|---|:-:|---|
| 1 | 软件开发团队 | 10（现状 `software_dev` 已落地，不是 L11 成文时的 5） | 技术工程 | A | 已在 `core/agents/teams/software_dev/` | — | 首 | WFT0 盘点，不重做 |
| 2 | **软件工坊** | **6** | 技术工程 | **A** | 代码审查 / 安全审计 / QA 均有现成（与 software_dev 同源 skill，Apache-2.0 / MIT，已 vendored） | **产品评审必须自建** | **首** | **WFT1** |
| 3–10 | 其余可进索引候选 | 见 L11 | 见 L11 | 见 L11 | 见 L11 | 见 L11 | 二/三 | WFT2 |
| 11–13 | 交易 / 法律 / 财税 | 见 L11 | — | B | 见 L11 | LC18/LC19 | **永不进 L1** | WFT2 后段，仍默关 |

现状偏差必须写明：L11 成文时 #1 写「5 人」，仓库里 `software_dev` 已是 **10 位角色 · 7 阶段**（`team.yaml:9`）。WFT0 以仓库为准，不把团砍回 5 人。

### 2.2 五条必须照做的纪律（L11 原文，本工作流执行面）

**一 · 中文本地化大仓一个都不许用。** 无 LICENSE = LC17 禁用。

**二 · 逐 skill 核许可，不是逐仓核。** 本工作流优先 **复用已经 LC17 过关、躺在 `software_dev/skills/` 里的文件**（复制或共享路径，开工时选一种并在卡内写死）。禁止为了「工坊更专业」再拉 `deanpeters/Product-Manager-Skills`（CC BY-NC-SA，L11 #7 已禁）。

**三 · 每支团落盘前跑 §0.3 第 3 条。** 工具名以命令输出为准。禁止 `registry.get_names()`。

**四 · 有论文的照论文抄，没论文的才自己设计。** #2 软件工坊锚定代码审查工坊结构（评审 → 多视角审查 → QA → 门），不是再造一套 ChatDev 全角色开发团（那是 #1）。`team.yaml` 必须写 `ecosystem.provenance`。

**五 · 角色数落在 3–13。** #2 冻结 **6**（含机械 verifier）。超过要在 PR 里逐角色论证。

### 2.3 批次与索引（D6 精神）

| 批 | 团 | 进 L1 索引 |
|---|---|---|
| 首批 YAML | #1 已在、#2 WFT1 | ❌ 本工作流阶段全部 `disable_model_invocation: true`。过 F14 后由 **L12** 放行，不是 WFT1 |
| 二/三批 | WFT2 | 同上 |
| 永不进 | #11 #12 #13 | 仅 `/team` 显式调用；WFT2 仍要默关 |

---

## §3 目标包形态

对照已落地的 `software_dev`（这是本工作流的样板，不是 L13 的 Team Pack 发行形态）：

```
core/agents/teams/software_workshop/
├── team.yaml                 # members 内联；validate_team 必须过
├── mcp.lock.yaml             # 默认 enabled: false（LC8）
├── prompts/
│   ├── product_reviewer.md
│   ├── code_reviewer.md
│   ├── security_auditor.md
│   ├── qa.md
│   ├── maintainability_auditor.md
│   └── verifier.md           # 可空；mechanical: true 的角色不靠 LLM
└── skills/
    ├── code-review-and-quality.md      # 复用 software_dev，LC17 已过
    ├── security-and-hardening.md
    ├── test-driven-development.md
    ├── code-simplification.md
    └── product-review.md               # 自建；禁止从 CC-BY-NC 产品经理包摘
```

加载入口已经存在，**不要新写 loader**：

```38:48:core/agents/teams/__init__.py
def builtin_team_path(name: str = "software_dev") -> Path:
    directory = _DIR / name / "team.yaml"
    if directory.is_file():
        return directory
    return _DIR / f"{name}.yaml"

def load_builtin_team(name: str = "software_dev") -> TeamSpec:
    path = builtin_team_path(name)
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    return load_team_from_mapping(raw)
```

`load_team_from_mapping` 末尾调用 `validate_team`（`teams/__init__.py:34`）。YAML 非法 = 加载即炸，这是好事。

路由可见性：`core/agents/registry.py:56-58` `model_may_see` —— `ecosystem.disable_model_invocation` 为 true 则模型自动路由看不见。WFT1 必须走这条，而不是靠「先不 scan」。

### 3.1 禁止事项

| 禁止 | 为什么 |
|---|---|
| 把团摘要写进 S1 / system prompt | LC1 |
| 默认 `disable_model_invocation: false` | LC2；L12 才翻转 |
| 在 `agent_v2.py` 加 `if team_name == "software_workshop"` | SP3 / ARCH-004 |
| 团长写进 members | PHASE-F：团长由 Coordinator 构造（L11 勘误二） |
| WorkBuddy 姓名 | LC11 |
| 引用不存在的工具名 | F11 事故 |
| 为加团去改 L11 矩阵人数而不开 PR | 矩阵是权威；偏差写在本文件 §2.1 |

---

## §4 任务卡

---

### WFT0 · 盘点与门禁脚本

`P0` / 0.5–1d / 无依赖 / **owner: backend**

**背景**

F11 曾写错工具名（PHASE-L §6.2 勘误一：示例 YAML 4 个名字 3 个不存在）。本卡不产新产品团，只把「能安全加第二支」的测量与样例门禁立住。没有这张卡，WFT1 会把错误工具名写进工坊。

**调研与 Verdict**

`Verdict: Extend — PHASE-L §0.4 第 3 条工具名命令 + 本仓 software_dev。`

**涉及文件**

| 路径 | 锚点 | 本卡怎么动 |
|---|---|---|
| `core/agents/teams/software_dev/team.yaml` | 头注释工具名；`extra.ecosystem.disable_model_invocation: true`（L280） | **只读**核对 |
| `core/agents/spec.py:49` | `validate_team` | 不改校验器，除非发现 blocker（发现了记缺口，不顺手扩 scope） |
| `core/agents/teams/__init__.py:45` | `load_builtin_team` | 确认 `software_dev` 可加载 |
| `core/builtin_tool_registration.py` | `*_tool` 符号 | 跑命令，把输出贴进本卡 PR |
| `tests/test_agents/test_spec.py` | `test_valid_team_passes` 等 | 必须绿 |
| `tests/test_agents/test_builtin_teams_inventory.py`（新增，可选但推荐） | — | 断言 software_dev 加载 + disable 标志 + 工具名 ⊆ 命令输出 |

**操作步骤**

1. 跑 §0.3 全部命令，把第 3 条完整 stdout 贴进 PR（不要摘要成「27 个」）。
2. `load_builtin_team("software_dev")` 打印 `name`、成员数、`disable_model_invocation`。期望：`software_dev`、10、`True`（与 2026-09-02 快照不符则 **以加载结果为准** 写进本卡偏差）。
3. 脚本（可放 `tests/test_agents/test_builtin_teams_inventory.py`）：解析 `software_dev/team.yaml` 每个 `tools:` 列表，断言每个名字都在第 3 条输出里（`tools: null` 表示继承，跳过）。
4. PREFIX：本卡若只加测试、不改 prompts，S1 仍必须绿。
5. **禁止**在本卡开始写 `software_workshop/`。

**验收命令**

```powershell
python -m pytest tests/test_agents/test_spec.py tests/test_cache/test_s1_s2_split.py tests/test_agents/test_builtin_teams_inventory.py -q
python -c "from RxyCode.RxyCode1_1_0.core.agents.teams import load_builtin_team; t=load_builtin_team('software_dev'); assert t.extra.get('ecosystem.disable_model_invocation') in (True,'true','1')"
```

若尚未新增 inventory 测试文件：前两条 pytest 必须绿，第三条 python 断言必须跑。

**完成判据**

- [ ] `software_dev` 过 `validate_team` / `load_builtin_team`
- [ ] 工具名命令 stdout 贴进 PR
- [ ] YAML 里出现的工具名 ⊆ 该 stdout（脚本或测试，不许只靠目检）
- [ ] S1 测试绿
- [ ] 未创建第二支团目录
- [ ] GPT-5.6 审计 PASS

**回滚**：若只加测试，revert 测试即可。

**常见坑**

- 裸 `registry.get_names()` 得到空列表，然后以为「内置团不能引用工具」。
- 把 `code_search` 写进 YAML 却没声明 RAG 依赖（PHASE-L §0.4：它不在 27 个里）。
- 为了「盘点」去改 `software_dev` 角色 prompt。

**Commit**：`test(teams): WFT0 inventory builtin software_dev`

---

### WFT1 · 第二支软件工坊 YAML

`P0` / 2–3d / 依赖 WFT0 / **owner: backend**

**背景**

用户要增加内置专家团。L11 首批第二支是 **#2 软件工坊**：6 人、技术工程、可行性 A、代码审查/安全审计/QA 有现成、**产品评审必须自建**。它不是第二份「软件开发团队」——#1 已经从规格写到文档；工坊吃的是 **已有 diff / 已有 PR / 已有补丁**，产出审查结论与门禁，不从头实现产品。

**调研与 Verdict**

`Verdict: Extend — PHASE-L L11 矩阵 #2 软件工坊 — disable_model_invocation true。审查结构照「评审 → 多视角审查 → QA → 机械门」抄，不自造编排内核。skill 复用 software_dev 已过 LC17 的四份；产品评审 skill 自建。`

**涉及文件**

| 路径 | 锚点 | 本卡怎么动 |
|---|---|---|
| `core/agents/teams/software_workshop/`（**新增**） | 对照 `software_dev/` 布局 | 整包落盘 |
| `core/agents/teams/software_dev/skills/*.md` | 已 vendored | 复制或共享；选一种写进 PR。禁止改 software_dev 行为 |
| `core/agents/teams/__init__.py` | `load_builtin_team(name)` | **不改 API**；`name="software_workshop"` 应已能工作 |
| `core/agents/registry.py:56` | `model_may_see` | 不改；靠 YAML 标志 |
| `core/agent_v2.py` | — | **diff 空** |
| `tests/test_agents/test_software_workshop.py`（新增） | — | 加载 + validate + 工具名 + disable + S1 |
| `tests/test_cache/test_s1_s2_split.py` | — | PREFIX |

**规范限制**

- 角色数 **6**（含 mechanical verifier）。display_name 自造三字，与 L10 示例表、WorkBuddy 截图姓名 **零重合**。
- `ecosystem.disable_model_invocation: true`，无一例外。
- **不进** L1 索引（本卡不得改 router 把工坊加进自动候选）。
- 团长不在 members。
- `tools:` 每个名字 ∈ WFT0 命令输出。审查角色默认 `read, grep, ls`；QA 可 `write, edit, bash`（只写 `tests/` 的约束写进 constraints）。
- `tools: null` 的含义跟 `software_dev` 前端/后端工程师一样：继承运行时默认。工坊 **不要** 给审查角色 `null` 以免拿到 `write`。
- provenance 必填。产品评审 skill 在 PR 里声明「自建，无对应论文/仓」或给出非黑名单出处。

**操作步骤**

1. **契约测试先行**

```python
# tests/test_agents/test_software_workshop.py
from RxyCode.RxyCode1_1_0.core.agents.registry import model_may_see
from RxyCode.RxyCode1_1_0.core.agents.teams import load_builtin_team

def test_workshop_loads_and_stays_off_index():
    team = load_builtin_team("software_workshop")
    assert team.name == "software_workshop"
    assert 3 <= len(team.members) <= 13
    assert len(team.members) == 6
    assert team.extra.get("ecosystem.disable_model_invocation") in {True, "true", "1"}
    assert model_may_see(team) is False
    assert "provenance" in str(team.extra.get("ecosystem.provenance") or team.extra)


def test_workshop_not_in_s1():
    from RxyCode.RxyCode1_1_0.core.prompts.registry import get_system_s1
    s1 = get_system_s1(tools=True, variant="default")
    assert "software_workshop" not in s1
    assert "品把关" not in s1  # display_name 也不得进 S1
```

2. **落盘 `team.yaml`**（意图草稿，合入前必须被 `validate_team` 接受；字段名以 `protocol.agents.AgentSpec` / `SopStage` 为准，GP3）：

```yaml
# core/agents/teams/software_workshop/team.yaml
# 软件工坊：审查已有改动，不从头写产品。L11 #2。
# 工具名以 WFT0 命令为准：read / ls / grep / write / edit / patch / bash。

name: software_workshop
display_name: 软件工坊
description: 6 位角色 · 4 阶段 · 产品评审 → 三视角审查 → QA → 机械验证

members:
  - role: product_reviewer
    display_name: 品把关
    goal: 从产品规格与验收清单审查这次改动该不该做、有没有漏验收
    backstory: 你只做产品评审，不写实现代码。
    constraints:
      - 不要写实现代码
      - 每条意见带文件和行号或明确「规格缺口」
    prompt_stage: agent_product_reviewer
    tools: [read, grep, ls]
    memory_scope: private
    timeout_s: 300
    extra:
      "ecosystem.is_leader": true
      "ecosystem.skill": product-review
      "ecosystem.provenance": "self-authored product review; CC-BY-NC PM packs forbidden"

  - role: code_reviewer
    display_name: 柯察码
    goal: 只读审查正确性与测试覆盖，发现必须带文件和行号
    tools: [read, grep, ls]
    prompt_stage: agent_code_reviewer
    extra:
      "ecosystem.skill": code-review-and-quality
      "ecosystem.provenance": "addyosmani/agent-skills code-review-and-quality MIT (vendored via software_dev)"

  - role: security_auditor
    display_name: 康守全
    goal: 只读审计注入、密钥、鉴权、危险默认值
    tools: [read, grep, ls]
    prompt_stage: agent_security_auditor
    extra:
      "ecosystem.skill": security-and-hardening
      "ecosystem.provenance": "addyosmani/agent-skills security-and-hardening MIT (vendored via software_dev)"

  - role: maintainability_auditor
    display_name: 简可维
    goal: 只读审计结构、重复与命名
    tools: [read, grep, ls]
    prompt_stage: agent_maintainability_auditor
    extra:
      "ecosystem.skill": code-simplification
      "ecosystem.provenance": "addyosmani/agent-skills code-simplification MIT (vendored via software_dev)"

  - role: qa
    display_name: 裴测严
    goal: 为本次改动补独立测试并跑 pytest，禁止改产品代码糊弄
    tools: [read, grep, ls, write, edit, bash]
    prompt_stage: agent_qa
    extra:
      "ecosystem.skill": test-driven-development
      "ecosystem.provenance": "addyosmani/agent-skills test-driven-development MIT (vendored via software_dev)"

  - role: verifier
    display_name: 机械验证
    goal: 用确定性检查回答审查结论是否落地
    mechanical: true
    prompt_stage: ""
    tools: []
    timeout_s: 300

stages:
  - name: product_review
    role: product_reviewer
    expected_output: 产品评审：该不该做、验收是否可机械判定、缺口清单
    output_key: product_review
    verify_before_next: []
    next_on_success: review
    next_on_failure: null
    max_retries: 1

  - name: review
    role: code_reviewer
    parallel_members: [security_auditor, maintainability_auditor]
    expected_output: 三视角审查结论，每条带文件和行号
    context_keys: [product_review]
    output_key: review_report
    verify_before_next: []
    next_on_success: qa
    next_on_failure: qa
    max_retries: 1

  - name: qa
    role: qa
    expected_output: 独立测试 + pytest 结果。禁止改产品代码。禁止 assert True
    context_keys: [product_review, review_report]
    output_key: tests
    verify_before_next: [files_exist, python_parses]
    next_on_success: verify
    next_on_failure: verify
    max_retries: 1

  - name: verify
    role: verifier
    expected_output: 机械门结论
    context_keys: [review_report, tests]
    output_key: verify_report
    verify_before_next: [files_exist, python_parses, lint_clean, tests_pass]
    next_on_success: null
    next_on_failure: null
    max_retries: 0

entry_stage: product_review
total_token_budget: 400000
total_timeout_s: 2400
max_delegations: 16
extra:
  "ecosystem.category": 技术工程
  "ecosystem.version": "0.1.0"
  "ecosystem.disable_model_invocation": true
  "ecosystem.provenance": |
    PHASE-L L11 #2 软件工坊. Review workshop (product review →
    parallel code/security/maintainability → QA → mechanical gate).
    Skills vendored from software_dev after LC17. Product-review skill
    self-authored (no CC-BY-NC PM pack).
```

3. **prompts/*.md**：每个非 mechanical 角色一份。禁止把团成员表写进会进 S1 的模板。
4. **skills/**：四份从 `software_dev/skills/` 复制（保持 SPDX 头）；`product-review.md` 自建，短，验收导向。
5. **mcp.lock.yaml**：若 QA 声明 playwright，照 `software_dev/mcp.lock.yaml` 写 `enabled: false`。
6. 跑工具名核对脚本（WFT0 那条）针对新 YAML。
7. `git diff core/agent_v2.py` 必须空。
8. 姓名零重合：对 L10 示例「需真明/裴测严/康守全」—— **康守全 / 裴测严 是 L10 构造法示例**，工坊若采用须在完成判据里声明「与 L10 示例表重合的是构造法示范名，不是 WorkBuddy 名」。为避开混淆，**不要**用 WorkBuddy 截图里的「高见远/严过关」。上表用了 裴测严/康守全 作为 L10 已批准构造法的跨团复用（P3 精神：构建期展开前允许同职能同名）。若审计认为示例名应留给 L10：改成 安密审 / 测必过，并在 PR 注明。

**验收命令**

```powershell
python -c "from RxyCode.RxyCode1_1_0.core.agents.teams import load_builtin_team; from RxyCode.RxyCode1_1_0.core.agents.registry import model_may_see; t=load_builtin_team('software_workshop'); assert model_may_see(t) is False"
python -m pytest tests/test_agents/test_software_workshop.py tests/test_agents/test_spec.py tests/test_cache/test_s1_s2_split.py tests/test_cache/test_stable_prefix.py -q
git diff --stat core/agent_v2.py
```

**完成判据**

- [ ] `core/agents/teams/software_workshop/team.yaml` 存在且 `load_builtin_team` / `validate_team` 通过
- [ ] 6 名成员、角色数 3–13、四阶段（或合入时 `validate_team` 接受的等价 SOP），description 符合「`{N} 位角色 · {M} 阶段 · {阶段名链}`」且 ≤120 字符（L11 / DL3）
- [ ] `ecosystem.disable_model_invocation: true`；`model_may_see` 为 False
- [ ] **未**把该团加入自动路由索引（router 测试或 Grep 证明无新候选）
- [ ] 每个工具名 ∈ WFT0 命令输出
- [ ] 复用 skill 有 provenance + 已过 LC17；产品评审为自建
- [ ] 自造姓名与 WorkBuddy 零重合
- [ ] S1 不含团名与 display_name；PREFIX 绿
- [ ] `core/agent_v2.py` diff 为空
- [ ] GPT-5.6 审计 PASS

**回滚**：删除 `core/agents/teams/software_workshop/` 与对应测试。

**常见坑**

- 把 L13 仓 / L10 shared-roles / L12 索引当成 WFT1 前置。
- 把工坊做成第二份 software_dev（又写一套前后端实现 SOP）。
- `disable_model_invocation` 漏写，团进了自动路由。
- 给审查角色 `tools: null`，让他们拿到 write。
- 在 agent_v2 里硬编码团名。

**Commit**：`feat(teams): WFT1 software workshop pack`

---

### WFT2 · 按 L11 批次追加

`P1` / 按团 1–3d / 依赖 WFT1 / **owner: backend**

**背景**

L11 其余批次：二批 MVP / 独董会 / 游戏 / 智数；三批产品战略 / 设计 / 内容 / AI 视频；永不进索引的交易 / 法律 / 财税。本卡 **仍默关自动路由**。进索引是 PHASE-L L12，不是本卡。

每加一支都是一次独立 commit（GK1）。本卡是批次说明书，不是一张超级卡把十三支塞进一个 diff。

**调研与 Verdict**

`Verdict: Extend — PHASE-L L11 其余批次，仍默关自动路由。每支单独核 LC13/LC17；#11 还要 LC19。`

**涉及文件**：`core/agents/teams/<name>/` 按团新增。L11 矩阵「核心现成资产」列是起点，**开工当日重核 SPDX**，不要抄 2026-08-17 快照当已过关。

**规范限制**

- 每支 `disable_model_invocation: true`
- 角色 3–13；有论文写 provenance；无论文 PR 说明
- #11 产出不得含买卖建议句式；合规必须是显式 stage（LC19）
- #12 数据源 404 则角色标 B-degraded，且本卡仍不进 L1
- #13 不含税务申报角色
- 中文无 LICENSE 大仓禁用（纪律一）
- 不改 L13/L14/L17 卡面

**操作步骤**

1. 打开 L11 矩阵对应行，核对 license。
2. 复制 WFT1 的测试模板，换团名。
3. 落盘 → SPEC + PREFIX + 工具名脚本。
4. 一支一个 commit。

**验收命令**

```powershell
python -m pytest tests/test_agents/test_spec.py tests/test_cache/test_s1_s2_split.py -q
# 另：该团自己的 test_*.py + validate_team 批量
```

**完成判据**（对每一支重复勾）

- [ ] `validate_team` 通过
- [ ] `disable_model_invocation: true`
- [ ] 工具名核对脚本绿
- [ ] license 记录在案且不在黑名单
- [ ] 未进 L1 索引
- [ ] GPT-5.6 审计 PASS

**回滚**：按团目录 revert，团之间无耦合。

**常见坑**

- 未核 license 就打包。
- 把十三支放进一个 commit。
- 为「好用」提前进索引。
- #11 抄 WorkBuddy「BUY/SELL/HOLD」。

**Commit**：`feat(teams): WFT2 add <team_id> pack`

---

## §5 出口检查

- [ ] WFT0 工具名命令有实测 stdout
- [ ] WFT1 软件工坊 YAML 过 `validate_team`，默关自动路由
- [ ] 未改 PHASE-L L11–L17 卡正文
- [ ] 未改 `agent_v2.py` 循环
- [ ] PREFIX 在加团后仍绿
- [ ] 文档未把 PHASE-L 整份文档、L13、L14、L17 写成加团前置

---

## §6 与既有 Phase 的接口与冲突消解

| 主题 | 权威 | 本包 |
|---|---|---|
| 矩阵人数与资产 | PHASE-L L11 | 执行 YAML；#1 人数以仓库 `software_dev` 为准 |
| 进索引 | L12 + F14 + L0a/L0b | **不做** |
| 发行版 | L13/L14 | **不是前置** |
| 跨宿主 | L17 | **不是前置** |
| 共享角色库 | L10 | 本包内联 members，不阻塞 |
| 编排内核 | PHASE-F coordinator/sop | 不新写 |
| 拆核 | DEV-ORDER SP3 | 团逻辑不进 agent_v2 |

---

## §7 证据缺口

- L11 #2「6 人」没有逐角色官方名单，本包 WFT1 按审查工坊职能填了 5 个 LLM + 1 个机械门。若产品要把「发布经理」换成「性能」，在 WFT1 PR 改表，不要默默加到 7 而不论证（纪律五）。
- 复用 `software_dev/skills/` 的 SPDX 以当时 vendoring 记录为准；WFT1 开工再扫一遍文件头。
- `load_builtin_team` 默认参数仍是 `software_dev`。不必改默认；测试显式传 `software_workshop`。
- WorkBuddy 软件工坊若日后补到走查截图，只许对照职能结构，不许对照姓名。
