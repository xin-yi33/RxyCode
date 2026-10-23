# Phase P · 产品意图叠加包（Product Intent Overlay）

> **在整条路线中的位置**：备忘施工包，**不是** F/L 的下一级主链。体例与 [`PHASE-J-PERSONA-AGENT-INTERFACE.md`](../PHASE-J-PERSONA-AGENT-INTERFACE.md) 相同：卡 **插进** [`PHASE-K-PLUGIN-DUAL-MODE.md`](../PHASE-K-PLUGIN-DUAL-MODE.md) / [`PHASE-N-CLI-PARITY-LONGRUN.md`](../PHASE-N-CLI-PARITY-LONGRUN.md) / [`PHASE-G-DESKTOP.md`](../PHASE-G-DESKTOP.md) / [`PHASE-L-TEAM-ECOSYSTEM-DISTRO.md`](../PHASE-L-TEAM-ECOSYSTEM-DISTRO.md)。现行顺序只看 [`DEV-ORDER.md`](./DEV-ORDER.md)。
> **前置条件**：本目录 [`research/2026-09-01-product-prior-art-verdicts.md`](./research/2026-09-01-product-prior-art-verdicts.md) 已有 Verdict；PHASE-FIX 不变量由 PHASE-K **KC1–KC5** 继承；单一 Session 由 [`ARCH-001`](../../../../decisions/ARCH-001-single-session-loop.md) 继承。
> **后继**：各卡依赖的 K/N/G/L 实现波次见 DEV-ORDER。本文件 **不改** 那些 PHASE 卡的编号、依赖、验收命令、完成判据。
>
> **一句话目标**：把桌面备忘 [`sources/RxyCode-产品意图备忘.md`](./sources/RxyCode-产品意图备忘.md) 变成可执行卡，且 **调研先行、能抄不造**；同一能力必须同时写 CLI 与 GUI；不改既有 PHASE-A…O / PHASE-FIX 卡正文。
>
> **执行模型**：**owner: backend + frontend** → 本叠加包由 **Grok 4.6** 主写（沿用 [`PHASE-FIX.md`](../PHASE-FIX.md) §5 与 PHASE-K 的先例）。这是对 [`../MODEL-ASSIGNMENT.md`](../../MODEL-ASSIGNMENT.md) 的 **局部例外**，**不改**总表。每卡完成判据在 **GPT-5.6 审计 PASS 前禁止勾选**。
> **修订**：2026-09-02（按 PHASE-K/L/N 卡面密度重写；逻辑不改，补路径、步骤、代码草稿、可勾判据）
> **预计工时**：按卡（P0 约 3–5 天；P1 约 3–4 周；P2 另排）
>
> ⚠️ **本叠加包引入的最大风险不是「功能点太多」，是「无 Verdict 就从零实现 Computer Use / 加号 / harness，然后把 PHASE-FIX 的 97% 命中率打穿」。** PP40 禁止自研 CUA；PP1 禁止 skills 列表进 S1；PP50 禁止第二套 invoke。

---

## 目录

| 章节 | 内容 |
|---|---|
| [§0 执行手册](#0-执行手册必读) | 模型约束 GP1–GP8、执行协议、硬性规则 PC0–PC10、决策 DP1–DP6 |
| [§1 一页看懂](#1-一页看懂三个问题的答案) | 为什么要叠加包 / 三块冲突怎么拍 / 好处是什么 |
| [§2 调研依据](#2-调研依据) | Verdict 表入口，不重复论证 |
| [§3 目标架构](#3-目标架构) | 挂接图、默认开/关、CLI/GUI 对等、插件≠skill≠MCP、CU token |
| [§4 任务卡](#4-任务卡) | PP1…PP100，逐张执行 |
| [§5 出口检查](#5-phase-p-出口检查) | 怎么算做完 |
| [§6 与既有 Phase 的接口与冲突消解](#6-与既有-phase-的接口与冲突消解) | **动手前必读** |
| [§7 证据缺口](#7-证据缺口与后续) | 已知不确定项 |
| [§8 愿望去向](#8-愿望去向备忘-12) | 备忘 §12 愿望 → 主去向，有且仅有一行 |

---

## §0 执行手册（必读）

### 0.1 模型约束（Grok 4.6）

本叠加包的全部任务卡由 **Grok 4.6** 执行。这是对 [`../MODEL-ASSIGNMENT.md`](../../MODEL-ASSIGNMENT.md) 的**范围内特例**，不是推翻它：

| 项 | 约定 | 依据 |
|---|---|---|
| 执行者 | Grok 4.6 单模型主写前后端 | PHASE-FIX §5、PHASE-K §0.1、PHASE-N §2.1 同一先例 |
| 与 MODEL-ASSIGNMENT 的关系 | 总表针对 Composer 双窗口。本包是**单模型单窗口**，不适用该分工表 | MODEL-ASSIGNMENT §5 承认后续实践可覆盖 |
| 审计门 | 每卡测试绿后换会话让 **GPT-5.6** 按 PHASE-FIX 附录 B 审 diff。**未 PASS 不得勾完成判据、不得开下一张卡** | 沿用 PHASE-FIX |
| 不修改 MODEL-ASSIGNMENT.md | 特例写在本节；冲突时以本节为准（仅限 Phase P 范围） | 用户规则：既有文档无明显错误则只添加不修改 |
| 不修改既有 PHASE 卡正文 | 本文件只叠加。hooks 跟 K14；goal 对象跟 N4–N6；加号 IA 跟 GX24 协议 | 备忘「不改那些文档」+ PHASE-N **NC5** |

**给 Grok 4.6 的行为约束**（这些不是建议，是本叠加包的执行前提）：

| # | 约束 | 为什么 |
|---|---|---|
| **GP1** | **一次只做一张卡，一张卡一个 commit。** 禁止「顺便把加号和 Computer Use 一起改了」 | 卡横跨 Python 内核 / 协议 / OpenTUI / Desktop 四层，混合 diff 无法 review |
| **GP2** | **动 `core/` 下任何 PHASE-FIX 文件之前，先读 PHASE-FIX §3 不变量全文。** 涉及文件：`core/turn_router.py`、`core/prefix_profile.py`、`core/prewarm.py`、`core/turn_context.py`、`core/handoff.py`、`core/catalog.py` | 这六个文件是 `AGENTS.md` 点名的 Phase-Fix 冻结面。本包最容易打穿的是 KC4（skills 进 S1）和 KC1（identity 漂移） |
| **GP3** | **不许猜文件路径和符号名。** 定位一律用 Grep 锚点。本文给出的行号是 **2026-09-02** 快照 | 与 PHASE-FIX §4.1、00-EXECUTION-PLAN **R1** 一致 |
| **GP4** | **不许发明第二套注入路径、第二套 invoke、第二套 agent loop。** 前缀入口仍是 `core/catalog.py`；插件 invoke 仍是 `appserver` 的 `plugin/*` + CapabilityService；会话仍是 `core/session.py` 的 `Session.prompt()` | ARCH-001、PHASE-K KC4、备忘 P2 |
| **GP5** | **示例代码是意图说明，不是可直接粘贴的成品。** 卡内代码与仓库现状冲突时，以仓库为准并在卡内记录偏差 | 行号快照会过期 |
| **GP6** | **完成判据必须客观可勾。** 禁止「体感更好」「基本可用」。每一条用户可见能力必须同时勾 CLI 与 GUI | 备忘 P1；00-EXECUTION-PLAN §0.5 |
| **GP7** | **新类型一律 `@dataclass(frozen=True, slots=True)`**；测试导入前缀 `from RxyCode.RxyCode1_1_0.core....` | PHASE-K **GK7** |
| **GP8** | **前端只消费协议，不发明 JSON-RPC 方法名。** 新方法先落 `protocol/requests.py`，再 appserver，再 OpenTUI/Desktop | PHASE-K **GK8**；ARCH-001 |

### 0.2 执行协议（含调研）

沿用 Phase A 的 7 步（LOCATE → READ → WRITE → LINT → TEST → CHECK → COMMIT），加本包专属五条：

```
0.  RESEARCH  写步骤前 / 实现前：本仓 rg → 注册表 → 已装 MCP/skill → GitHub → 本机闭源观察
              卡内必须有一行：
              Verdict: Adopt|Extend|Compose|Build — <仓库或本仓路径> — <证据>
              无 Verdict = 体例失败，不得实现。Build 必须说明不能抄的原因。

8.  PREFIX    每张碰 core/ / tools/ / prompts/ 的卡都要跑（PP1 / PP10 / PP20 / PP30 / PP40 / PP62 必跑）
              python -m pytest tests/test_cache/test_s1_s2_split.py tests/test_cache/test_stable_prefix.py -q

9.  IDENTITY  碰前缀或能力开关的卡额外跑（PP1 / PP42 / PP62）
              python -m pytest tests/test_cache/test_prefix_identity_default_unchanged.py -q
              （若该文件尚未因 PHASE-K K2 落地：输出 BLOCKED_PREREQUISITE，不许用别的测试冒充）

10. PAIR      每张用户可见能力卡必须同时改（或同时证明已有）CLI 与 GUI
              OpenTUI：frontend/opentui-app/src/commands.ts + 对应 dialog
              Desktop：frontend/desktop-app/src/renderer/...
              缺一端 = 本卡失败（PC1）

11. TUI       前端卡额外跑
              cd frontend\opentui-app; npx tsc --noEmit; npx vitest run
              cd frontend\desktop-app; 跑该卡点名的 node:test / vitest
```

**为什么要第 0 步**：备忘 P6 与用户硬条件「调研先行、能抄不造」。08-12 已经证明：不调研就会自研像素 CUA，然后 token 账与测试一起爆。

**为什么要第 8 步**：本包唯一可能悄悄毁掉 97% 的方式，就是让 skill 列表、团目录、CU 工具表、goal 文本混进 `get_system_s1()`（`core/prompts/registry.py:250`）。S1 测试红了，任何功能测试都不会告诉你缓存已经被打穿。

**为什么要第 10 步**：备忘原话「不要做成 GUI 有、终端没有或终端有、窗口里看不见」。PHASE-N **NC1/NC2** 已经把「两端调同一个协议方法」写成硬规则。本包不另发明第三条路径。

### 0.3 前置自检

```powershell
cd "D:\agent-demo\RxyCode\RxyCode1_1_0"

# 1) 本叠加包的调研与顺序（缺一项就停，不要凭聊天记忆开工）
Test-Path docs\plans\opus5-plan\rxycode\architecture\research\2026-09-01-product-prior-art-verdicts.md
Test-Path docs\plans\opus5-plan\rxycode\architecture\DEV-ORDER.md
Test-Path docs\plans\opus5-plan\rxycode\architecture\sources\RxyCode-产品意图备忘.md
Select-String -Path docs\plans\opus5-plan\rxycode\architecture\research\2026-09-01-product-prior-art-verdicts.md -Pattern "open-codex-computer-use"

# 2) PHASE-FIX 地基（PC6 / KC1–KC5 的牙齿）
Test-Path core\prefix_profile.py, core\turn_context.py, core\turn_router.py, core\catalog.py
python -m pytest tests/test_cache/test_s1_s2_split.py tests/test_cache/test_stable_prefix.py -q

# 3) 本包要挂的现成缝（不是「没有所以从零造」）
Test-Path core\session.py, core\safety\policy.py, core\safety\approval.py
Test-Path tools\edit.py, appserver\plan_files.py, appserver\side_chat.py
Test-Path frontend\opentui-app\src\commands.ts
Test-Path frontend\desktop-app\src\renderer\src\components\ComposerPlusMenu.tsx
Test-Path frontend\desktop-app\src\renderer\src\lib\goalSettings.mts
Test-Path core\agents\teams\software_dev\team.yaml

# 4) 工具名真值（写 YAML / 补丁 / CU 适配器都要用；裸 registry.get_names() 返回空列表）
python -c "import core.builtin_tool_registration as m; print(sorted({getattr(getattr(m,a),'name') for a in dir(m) if a.endswith('_tool') and isinstance(getattr(getattr(m,a),'name',None),str)}))"

# 5) OpenTUI 命令注册表（PP1 / PP31 / PP42 / PP70 的增量基准）
Select-String -Path frontend\opentui-app\src\commands.ts -Pattern "^\s+\{ name:"

# 6) CapabilityRegistry 是否已落地（决定 PP42 是接线还是 BLOCKED）
Test-Path core\capabilities\defaults.py
```

第 6 项为 `False` 时：PP42 输出 `BLOCKED_PREREQUISITE`（等 PHASE-K K1/K2），**其余卡不受影响**。不要自己建第二套能力表。

### 0.4 硬性规则

| # | 规则 | 依据 / 违反后果 |
|---|---|---|
| **PC0** | **调研先行、能抄不造。** 写卡前与实现前都要调研；卡内必有 `Verdict:`。无 Verdict 不得开工。Build 必须说明不能抄的原因 | 备忘 P6；search-first。违反 = 体例失败，审计直接 FAIL |
| **PC1** | **同一能力必须同时写 CLI 与 GUI 完成判据**，两端调**同一个**协议方法；允许呈现不同，不允许能力缺失 | 备忘 P1；PHASE-N NC1/NC2。只做一端 = 本卡失败 |
| **PC2** | **加号第一屏 = 已下载插件**；skill / MCP 不得冒充加号。invoke 仍只有 CapabilityService / `plugin/*`。禁止第二套 invoke | 备忘 P2；PHASE-K KC6。违反 = 用户以为装的是文档，实际拿到可执行扩展（LC14 同类事故） |
| **PC3** | **`/using-superpowers` 与 `/search-first` 定死本轮 SOP**；进 S2 / user 后缀，**禁止进 S1** | 备忘 §7；PHASE-K KC4 / FXC3。违反 = 97% 命中率当场打穿 |
| **PC4** | **改文件要红绿可见；子代理要能点进去。** JSONL 审计日志不算用户可见完成物 | 备忘 P4。违反 = 卡面可以勾、用户看不见 |
| **PC5** | **抄交互不抄内核。** 禁止把 Codex/OpenCode/Grok 的循环整仓嵌进来换掉 `Session` / `AgentV2` | 备忘 P5；ARCH-001 |
| **PC6** | **能力关闭 = PHASE-K 能力层级 L0**（S1 不变）；打开走能力层级 L1 会话边界。跨文档禁止裸写 `L0`/`L1` | PHASE-K §3.2；DEV-ORDER PC10。裸 `L0` 会和 PHASE-L L0a 撞名 |
| **PC7** | **网装 hooks 默认关**；已下载 ≠ 已信任 ≠ 已启用 | PHASE-K K14 / K19；LC9。供应链事故：空 matcher 的 PostToolUse 能看见全部工具 |
| **PC8** | **Computer Use 默认关；事实观察；`cli_list`/`cli_run` 并存不得替代**；优先 OSS/MCP，禁止自研跨平台 CUA | 备忘 §4；ARCH-003；08-12 冻结的是「像素点击当默认/唯一」，不是「永远不做直接控制」 |
| **PC9** | **`/goal` = PHASE-N N4–N6 服务端对象 + Codex UX + Grok Build SOP**。禁止另做存储，禁止继续 `applyGoalToPrompt` | 备忘 §6；PHASE-N DN3–DN5 |
| **PC10** | **跨文档引用带文档名**；禁止裸 `L0`/`M1`/`P1`。本包卡号是 `PP1`、`WFT1`，不是 `P-1` | 既有引用事故；测试 `test_live_order_and_intent.py` 认 `PP\d+` |

### 0.5 决策记录

以下六条是开工前已确认的决策。**改任何一条都要回到本节改，不要在任务卡里就地改。**

| # | 决策 | 选择 | 理由 |
|---|---|---|---|
| **DP1** | Computer Use vs 08-12 冻结 | **口述为准**：要直接控制 + 事实观察。软联系并存。接入 iFurySt/open-codex-computer-use | 备忘 §4 原文覆盖调研冻结。08-12 仍成立的部分（像素默认贵、截图进 S1 会炸）用「默关 + 固定工具面 + 无障碍树」接住，而不是改口成「不做」 |
| **DP2** | 加号 vs PHASE-K | **拆 IA，不推翻禁止第二 invoke** | PHASE-K 宿主（`plugin/list\|install\|uninstall`）继续当唯一执行面。加号第一屏是已装插件的**呈现**，不是新的 CapabilityService |
| **DP3** | `/goal` 三件套 | **承接 N4–N6 对象，不另做存储**；UX 抄 Codex；SOP 抄 Grok Build | 三件事是一层对象 + 一层呈现 + 一层节拍。混成一张卡会让 N4–N6 与本包抢存储 |
| **DP4** | PHASE-P 层级 | **叠加包，不是主链** | 用户要求合并计划版本，不要发明一条跟 K/L/M/N 平级的新字母链。DEV-ORDER 排的是既有未完成卡 |
| **DP5** | `agent_v2.py`（2026-09-02 实测 **6851** 行） | **必须拆；本目标不执行循环改写** | ARCH-004。高星对照：Codex 用目录消化大体量；Cline Task ~3756 行是债。拆之前先做 DEV-ORDER **SP0** |
| **DP6** | 默认开/关 | 见 §3.4 表。斜杠 skill 发现开、强制加载只在用户打了斜杠时发生；CU 关；网装 hooks 关；multiagent 产品开关仍关 | 00-EXECUTION-PLAN §12.4「能力要有，但不该悄悄替用户花钱」 |

---

## §1 一页看懂（三个问题的答案）

### 问题一：为什么还要一份 PHASE-P，而不是直接改 PHASE-K/N/G？

**因为备忘是愿望，K/N/G/L 是已经定稿的施工单位。** 用户明确说「不改那些文档」。如果把「加号第一屏是已下载插件」写进 PHASE-K K18，就会改掉已冻结的卡面；如果把 Computer Use 口述覆盖写进 08-12 调研正文，就会伪造历史。

叠加包的好处是：

1. **总顺序有牙齿**：DEV-ORDER 把既有未完成的 K/L/M/N/G/H 排进波次，而不是另起一条「产品愿望主链」。
2. **愿望有且仅有一个主去向**：§8 与备忘 §12 逐行对齐，测试 `test_memo_section12_each_wish_has_exactly_one_destination` 锁死。
3. **能抄则接 MCP/开源**：每张卡强制 Verdict，避免再从零写 CUA。

### 问题二：三块冲突到底听谁的？

| 冲突 | 听谁 | 落哪张卡 |
|---|---|---|
| Computer Use：08-12 冻结像素 vs 口述要直接控制 | **口述**。冻结范围缩成「像素不是默认/唯一」。`cli_list`/`cli_run` 并存不得替代 | PP40–PP42 + ARCH-003 |
| 加号：PHASE-K 偏 skill/MCP/GitHub pin vs 截图第一屏是已装插件 | **拆 IA**。宿主仍是 `plugin/*`；第一屏不是 skill/MCP 目录 | PP50–PP51 |
| `/goal`：N4–N6 服务端对象 vs Codex 侧栏 vs Grok Build SOP | **三层都要，存储只许一层** | PP60 = N4–N6；PP61 = Codex UX；PP62 = SOP |

### 问题三：做完用户能看见什么？

不是「又多了一份架构 README」，而是：

- 打 `/using-superpowers`，本轮 **必须** 走那条 SOP（CLI 与 GUI 都行），S1 字节不变。
- 改文件在对话流里红删绿增；GUI 能点开完成物。
- 加号第一屏是已下载插件，不是全世界 skill 目录。
- `/goal` 是服务端对象，不再是 `applyGoalToPrompt` 拼出来的「持续目标：」。
- Computer Use 能看见窗口/标签事实，默认关；不是把 `cli_run` 改个名字。

---

## §2 调研依据

本叠加包不重复论证。动手前至少读完 Verdict 报告的对应行，以及 PHASE-K §3.2（L0/L1 分级）。

| 报告 | 覆盖 | 本包用到的核心结论 |
|---|---|---|
| [`research/2026-09-01-product-prior-art-verdicts.md`](./research/2026-09-01-product-prior-art-verdicts.md) | 备忘每条愿望的 Adopt/Extend/Compose/Build | **写卡前 Verdict 的唯一入口** |
| [`research/2026-09-01-top-coding-agents-core-architecture.md`](./research/2026-09-01-top-coding-agents-core-architecture.md) | 前 20 核结构 | 拆 `agent_v2` 学 Codex 目录边界；CU Adopt iFurySt，不写进 loop |
| [`../research/2026-08-12-agent-native-computer-use-research.md`](../research/2026-08-12-agent-native-computer-use-research.md) | 像素 CU 成本 | 被口述覆盖默认路径；**仍成立**：截图工具表进 S1 会炸 |
| [`../research/2026-08-17-cli-agent-plugin-ecosystems.md`](../research/2026-08-17-cli-agent-plugin-ecosystems.md) | 插件宿主 | 加号 ≠ skill ≠ MCP；单一插件形态（KC6） |
| [`../research/2026-08-17-workbuddy-expert-team-teardown.md`](../research/2026-08-17-workbuddy-expert-team-teardown.md) | 专家团规模 | 加团走 [`PHASE-L-TEAMS-INCREMENT.md`](./PHASE-L-TEAMS-INCREMENT.md)，不在本文件造编排内核 |
| [iFurySt/open-codex-computer-use](https://github.com/iFurySt/open-codex-computer-use) | CU MCP | `list_apps` / `get_app_state` / `click` / `type_text` / `press_key`；无障碍树 |

三个独立来源指向同一条结论，这是本包全部架构决策的地基：

> 能力开关只要把新工具目录塞进 S1，就必然打穿 prompt cache。

证据：① PHASE-K 引用 pi「MCP tools can't be hot-swapped without invalidating the cache」；② FXC3 明文禁止 skills 列表进 S1；③ 08-12 把「N 个截图工具进前缀」列为 Computer Use 的第一杀手。

---

## §3 目标架构

### 3.1 本包挂在哪条缝上（不另造大脑）

```
[OpenTUI / Desktop]
        │  只许 protocol-client / JSON-RPC（GP8）
        ▼
[appserver]  plugin/* · goal/* · plan_files · side_chat · 访问档字段
        │  只许 Session 假面
        ▼
[Session]  core/session.py:144  Session.prompt() → emit()
        │
        ├─ harness      turn_router / prefix_profile / catalog / prompts
        ├─ isolation    core/safety/*  + 本包 PP10 真隔离剖面
        ├─ tools.edit   tools/edit.py  + 本包 PP20 结构化补丁
        ├─ hooks        PHASE-K K14 事件桥 + 本包 PP30/PP31 入口
        ├─ plugin-host  plugin/list|install  唯一 invoke（PP50 只改 IA）
        ├─ skills       K9 发现 / K10 S2 索引 + 本包 PP1 斜杠定死
        ├─ mcp          stdio only → ToolOrchestrator
        ├─ cu           独立 MCP 进程（PP40），不进 agent_v2
        └─ teams        加团走 WFT*，本文件不写 YAML
```

完整导入法与变更预算见 [`MODULE-BOUNDARIES.md`](./MODULE-BOUNDARIES.md)。Ink + `api_server.py` SSE = 同一 Session 的后备适配器，**不是第二大脑**。

### 3.2 插件 ≠ skill ≠ MCP（信息架构，不是三个宿主）

| 层 | 用户看见 | 协议 / 缝 | 不是 |
|---|---|---|---|
| 加号 / `/plugin` | 已下载可执行扩展 | `plugin/list`（`protocol/requests.py` PluginListRequest；`appserver/server.py:2603`） | skill 目录、MCP 列表、加号里的「全世界市场」 |
| skill / 斜杠 | `/using-superpowers` 定死 SOP | K9 发现 + K10 S2 + PP1 斜杠 | 加号第一屏 |
| MCP | `/list-mcp`、设置 | stdio MCP → ToolOrchestrator | 产品会话；加号第一屏 |

OpenTUI 现状（2026-09-02 快照 `commands.ts`）：已有 `/find-skill` `/addskill` `/list-skills` `/remove-skill` `/addmcp` `/list-mcp` `/remove-mcp`，**没有** `/using-superpowers`、`/plugin`、`/hooks`、`/goal`。Desktop 加号现状（`ComposerPlusMenu.tsx`）是「文件 / 工作区 / 目标 / 计划模式」四按钮，**没有**已装插件第一屏。这就是 PP1 / PP50 / PP31 / PP60 存在的原因。

### 3.3 Computer Use token 与工具面

默认关。观察优先无障碍树（AX / AT-SPI / UIA），截图按步 opt-in。工具面固定为 MCP 适配器暴露的那一组（以 iFurySt README 为准：`list_apps` `get_app_state` `click` `scroll` `drag` `type_text` `press_key` `set_value`），**禁止**「每个窗口一个 tool」或「N 张截图 N 个 tool」进 S1。

`cli_list` / `cli_run`（PHASE-N N12–N13 的 CLI-Anything 软联系）**继续存在**，完成判据里必须有负向测试：关掉 CU 之后这两条仍可用；打开 CU 不得删除它们。

### 3.4 默认开 / 关

| 能力 | 默认 | 开了之后走哪一档 | 谁翻转 |
|---|---|---|---|
| 斜杠定死 skill | **机制开**（用户打了斜杠才强制加载） | PHASE-K 能力层级 L0（索引进 S2，正文进 user 后缀） | 无翻转；不是常开技能列表 |
| 沙箱工作区档 | **开**（cwd 边界） | isolation 缝；不改 S1 | PP10/PP11 |
| 完全访问 | **关** | 访问档字段；须明示 | PP11 |
| 结构化补丁 | **开**（主路径）；字符串替换兜底 | tools.edit | PP20 |
| hooks 机制 | **开**（能挂）；网装 **关** | K14；零进前缀 | PP30 |
| Computer Use | **关** | PHASE-K 能力层级 L1 会话边界 | PP42 |
| 加号已装列表 | **开**（空列表也是合法第一屏） | plugin-host 呈现 | PP50 |
| `/goal` / Plan | 未设置则 **关** | N4–N6 对象 + plan_files | PP60/PP70 |
| Grok Build SOP | goal 激活后 **强制** | 写屏障 | PP62 |
| multiagent 产品开关 | **关** | PHASE-K DK1 / K21 | 本包不翻转 |
| 内置团 YAML | 发货但 **默关自动路由** | LC2 | WFT1，不在本文件 |

### 3.5 浏览器与终端形态

- 浏览器（PP80，P2）：系统 WebView / CDP，**不在 P1 塞整份 Chromium**。
- 终端（PP81）：优先 PTY；P1 允许降级为「协议事件可见命令 + 外开系统终端」。CLI 本身即是终端，不能拿「CLI 有 bash」勾 GUI 完成判据。

---

## §4 任务卡

任务卡字段与 [`00-EXECUTION-PLAN.md`](../00-EXECUTION-PLAN.md) §0.5 相同。行号是 2026-09-02 快照，动手前用 Grep 重定位（R1 / GP3）。

---

### PP1 · 斜杠定死 skill

`P0` / 1–2d / 依赖 PHASE-K K9 发现（**可并行设计**；合入须 K9 已能解析 SKILL.md）/ **owner: backend + frontend**

**施工权威改走 [`PHASE-UPDATE-01.md`](../PHASE-UPDATE-01.md) U27 + U29 + §9 SL-02/SL-04。** 本卡保留意图与 KC4（skills 列表不得进 S1）。禁止在 `core/skills/slash.py` 之外再写第二套 `parse_slash`。U29 的测试函数名必须与 PP1 原文 `test_slash_using_superpowers_forces_skill_into_user_suffix_not_s1` / `test_slash_unknown_skill_is_explicit_error` 一致。

**背景**

备忘 §7：用户写下 `/using-superpowers` 或 `/search-first`，本轮就必须走那条 SOP，不能靠模型「想起了再读」。Cursor 已有这个交互；本机已有 `C:\Users\Administrator\.agents\skills\superpowers\skills\using-superpowers\SKILL.md`。

现状缺口（2026-09-02 实测）：

- `frontend/opentui-app/src/commands.ts` 的 `AVAILABLE_COMMANDS` **没有** `/using-superpowers` / `/search-first`。Skills 分类只有安装/列表（`/find-skill` `/addskill` `/list-skills` `/remove-skill`）。
- Desktop 命令面板同样没有「把已装 skill 映射成斜杠并强制加载」。
- PHASE-K K9 只发现与解析、**零注入**；K10 才把索引进 S2。PP1 解决的是 **invoke 路径**：斜杠 → 本轮强制 `append_turn_context` 加载该 SKILL.md 正文。

不做这件事的后果：用户以为打了 SOP，模型仍按默认 agent 乱走；或者有人图省事把 skills 列表塞进 S1，97% 当场死。

**调研与 Verdict**

`Verdict: Adopt — shimo4228/search-first 与 obra/superpowers using-superpowers — 两条分列，斜杠定死，正文仍渐进披露。`

**涉及文件**

| 路径 | 锚点 / 行号快照 | 本卡怎么动 |
|---|---|---|
| `frontend/opentui-app/src/commands.ts:18` | `export const AVAILABLE_COMMANDS` | **不**把几百个 skill 静态写进这张表。增加「已装且 `user-invocable` 的 skill → 斜杠」的动态源。既有条目 `name`/`category`/`action` 定义 diff 为零（PHASE-N **NC6**） |
| `core/skills/`（K9 落地后）或本卡新建 `core/skills/slash.py` | 无 | 解析 `/using-superpowers rest...` → skill name + remainder |
| `core/turn_context.py` | `append_turn_context` | 正文只追加到 user 后缀 |
| `core/prompts/registry.py:250` | `get_system_s1` | **禁止**本卡改 S1 模板 |
| Desktop 命令面板 / Composer 输入 | 与 OpenTUI 同一协议 | GUI 点选 = 打同一斜杠 |
| `tests/test_skills/test_slash_force.py`（新增） | — | 契约测试先行 |
| `tests/test_cache/test_s1_s2_split.py` | `test_s1_same_variant_byte_identical` | PREFIX 必绿 |

**规范限制**

- 斜杠名 = skill `name`（K9 frontmatter）。`using-superpowers` 与 `search-first` 是两条 skill，不要合成一条「万能 SOP」。
- `user-invocable: false` 的 skill **不出现在斜杠补全**，打了返回明确错误，不崩溃。
- `disable-model-invocation: true` 的 skill 仍可被斜杠强制加载（这正是「定死」的意义），但 **不进 S2 索引**（K10 已有纪律）。
- 未安装时：CLI/GUI 都提示「未安装，可用 /addskill」，禁止静默当普通聊天发出去。
- 禁止把 skill 全文常驻 system prompt。

**操作步骤**

1. **契约测试先行** `tests/test_skills/test_slash_force.py`：

```python
def test_slash_using_superpowers_forces_skill_into_user_suffix_not_s1():
    """打斜杠后本轮必须加载 SOP；S1 不得出现 skill 名列表。"""
    s1_before = get_system_s1(tools=True, variant="default")
    inv = parse_slash("/using-superpowers 修登录")
    assert inv.skill_name == "using-superpowers"
    assert inv.remainder == "修登录"
    assert inv.force_load is True
    s1_after = get_system_s1(tools=True, variant="default")
    assert s1_before == s1_after
    assert "using-superpowers" not in s1_after
    assert "available_skills" not in s1_after


def test_slash_unknown_skill_is_explicit_error():
    inv = parse_slash("/not-a-real-skill-xyz")
    assert inv.error_code == "skill_not_installed"
```

2. **解析器**（意图，按 GP5 以仓库为准）：

```python
# core/skills/slash.py
from dataclasses import dataclass
from typing import Optional

@dataclass(frozen=True, slots=True)
class SlashSkillInvocation:
    skill_name: str
    remainder: str
    force_load: bool = True
    error_code: Optional[str] = None
```

斜杠命中规则：输入以 `/` 开头、第一个 token 精确匹配已装 skill 的 `name`（或 `name` 的 `/` 形式）。**只做精确匹配**，不做模糊——否则 `/team` 任务文本会被误吞（与 PHASE-N N8 `/team` 消歧同一纪律）。

3. **强制加载**：本轮第一条 user 消息经 `append_turn_context` 附上该 SKILL.md 正文（或「请先 read 该 skill」的既有渐进披露契约，以 K10 为准）。**不得**改 `get_system_s1`。

4. **CLI**：OpenTUI 输入 `/using-superpowers` 走解析器，不把该名写死进 `AVAILABLE_COMMANDS` 的静态 42 条（快照）——动态补全从 K9 发现结果来。既有 42 条定义逐字不变。

5. **GUI**：命令面板与 Composer 斜杠同一入口。点「using-superpowers」= 发送同一字符串。禁止 GUI 另写一套「读取 skill 然后拼进 system」。

6. **禁止事项**：`Select-String -Path core\prompts\*.py -Pattern "using-superpowers|available_skills"` 本卡不得新增 S1 命中。

**验收命令**

```powershell
python -m pytest tests/test_skills/test_slash_force.py tests/test_cache/test_s1_s2_split.py tests/test_cache/test_stable_prefix.py -q
cd frontend\opentui-app; npx tsc --noEmit; npx vitest run
```

**完成判据**

- [ ] 输入 `/using-superpowers` 后本轮必须加载该 SOP；有测试
- [ ] `/search-first` 作为**另一条** skill 同样强制；有测试
- [ ] CLI 与 GUI 都能打；两端无第二套加载路径（`git grep` 证明只走 `append_turn_context` / K10 已有缝）
- [ ] S1 无 skills 列表、无 `using-superpowers` 字面；PREFIX 绿
- [ ] 未安装时明确错误，不崩溃，不把斜杠当普通聊天吞掉
- [ ] 既有 `AVAILABLE_COMMANDS` 静态条目定义 diff 为零
- [ ] GPT-5.6 审计 PASS

**回滚**：revert 本卡。解析器是新文件，回滚面限于斜杠路径。

**常见坑**

- 把 skill 列表塞进 S1「这样模型才知道有哪些」——那是 K10 的 S2 索引，不是 S1。
- 只在 GUI 命令面板做快捷按钮，CLI 打斜杠没反应。
- 把 `using-superpowers` 与 `search-first` 合成一条「调研 SOP」。
- 在 `commands.ts` 静态添加 200 个 skill 名字。

**Commit**：`feat(skills): PP1 slash-force skill`

---

### PP10 · 真执行隔离内核

`P1` / 3–5d / 依赖 ARCH-002 isolation 缝；**不依赖** PHASE-K 全绿 / **owner: backend**

**背景**

备忘 §3.1：要真执行隔离，不是只靠写路径白名单和点一下批准。现状（2026-09-02）：

- `core/safety/policy.py` 是 OpenHands 风格的风险分级 + 写路径白名单（模块 docstring 第 1–7 行写明「Only the design is ported」）。
- `core/safety/approval.py` 是批准经纪（`TuiApproval` / `SseApproval`），批准后 **syscall 不再被裁**。
- `permission_mode` 现为 `confirm_all | auto_edit | full_auto`（`execution/tool_orchestrator.py:85`），这是**审批旋钮**，不是沙箱旋钮。PHASE-K **KC12** 已经写过：sandbox 与 approval 正交。

不做的后果：用户点了「允许」之后，`bash rm -rf` 仍然能跑出工作区——这不是 Codex 那种「允许之后系统调用仍可能被裁」。

**调研与 Verdict**

`Verdict: Extend — Codex sandbox 公开文档与 OpenHands runtime — 不自造隔离内核。Windows 用 Job Object / 完整性级别；POSIX 优先 bubblewrap/seatbelt 类现成剖面。`

**涉及文件**

| 路径 | 锚点 | 本卡怎么动 |
|---|---|---|
| `core/safety/policy.py` | `RiskLevel`、`TOOL_RISK_TABLE` | **不改**风险表语义；隔离是新剖面 |
| `core/safety/approval.py` | `ApprovalDecision` | 批准之后仍走隔离；禁止在 broker 里 return allow 翻盘（KC11） |
| `core/safety/isolation.py`（**新增**） | — | OS 级剖面：工作区档 vs 完全访问 |
| `execution/tool_orchestrator.py:85` | `permission_mode_override` | 可读取访问档，但访问档 ≠ permission_mode |
| `core/agent_v2.py` | 6851 行循环 | **禁止**在此写旁路 |
| `tests/test_safety_gate.py`、`tests/test_safety_audit.py` | 现有 | 回归必须绿 |
| `tests/test_safety/test_isolation.py`（新增） | — | deny / job object / 出界写 |

**规范限制**

- 工作区档：工作区外写、出界 bash cwd、任意网络（若本卡范围含网络）必须失败，即使 `permission_mode=full_auto`。
- 完全访问：明示；CLI 与 GUI 都能读到同一协议字段（字段名本卡定，PP11 做呈现）。
- 禁止用「再加一份路径白名单」冒充本卡。
- 禁止引入第二套 tool loop。

**操作步骤**

1. 契约测试：`full_auto` + 工作区档下，向工作区外 `write` / `bash` 必须返回拒绝，且 **syscall 未发生**（用临时目录探针）。
2. 新建 `core/safety/isolation.py`，对外只暴露：

```python
@dataclass(frozen=True, slots=True)
class AccessTier:
    key: str            # "workspace" | "full"
    title: str
    description: str

def enforce(path_or_cmd, *, tier: AccessTier, workspace: Path) -> None:
    """Raise IsolationDenied. Never return allow."""
```

3. 在 `ToolOrchestrator` 执行 **之前** 调 `enforce`。guard 只能抛拒绝或返回 `None`（KC11）。
4. Windows：Job Object 限制子进程；POSIX：优先现成 sandbox 后端，核不出 SPDX 合法实现则本卡停在 `BLOCKED_PREREQUISITE` 并写缺口，**禁止**自研 seccomp 解释器。
5. 文档：`docs/modules/` 对应模块说明访问档 ≠ 审批档。

**验收命令**

```powershell
python -m pytest tests/test_safety/test_isolation.py tests/test_safety_gate.py tests/test_safety_audit.py tests/test_cache/test_s1_s2_split.py -q
```

**完成判据**

- [ ] 工作区档下出界写/出界 bash 失败，有测试证明 syscall 未发生
- [ ] `full_auto` 不能翻开隔离（正交于审批）
- [ ] S1 不变（PREFIX 绿）
- [ ] 未在 `agent_v2.py` 新增隔离分支（`git diff core/agent_v2.py` 空，或仅必要的一处调用委托）
- [ ] CLI 与 GUI 尚不必做完呈现（那是 PP11），但协议字段已有，两端能读到同一 key
- [ ] GPT-5.6 审计 PASS

**回滚**：revert 本卡。隔离默认失败应 fail-closed；回滚后回到「白名单 + 批准」。

**常见坑**

- 在 `agent_v2` 里 `if tool == "bash": check_path()`。
- 把 `permission_mode=confirm_all` 当成沙箱。
- 只测 Python `Path` 前缀，不测 `bash -c "echo > /tmp/x"`。

**Commit**：`feat(safety): PP10 isolation kernel`

---

### PP11 · 访问档 CLI + GUI

`P1` / 1–2d / 依赖 PP10 / **owner: backend + frontend**

**背景**

备忘 §3.1 / §8：Codex 输入框旁「完全访问」是呈现。RxyCode 现有 `/permission confirm_all|auto_edit|full_auto`（`commands.ts:52`）管的是审批，用户会把「全自动同意」误读成「完全访问」。本卡把访问档做成**另一条**用户可见旋钮，两端同一协议字段。

**调研与 Verdict**

`Verdict: Build — 本机闭源观察：Codex 访问档 — 只抄档位 UX，内核用 PP10。`

**涉及文件**

| 路径 | 锚点 | 本卡怎么动 |
|---|---|---|
| `protocol/requests.py` | 现有 session/settings 方法族 | 增加只读/写入访问档的字段；**先改 protocol 再改表面**（GP8） |
| `frontend/opentui-app/src/commands.ts:52` | `/permission` | **不改**既有 `/permission` 行为（NC6）。新增 `/sandbox` 或设置分区里的访问档（名称开工时 Grep 确认无冲突） |
| OpenTUI 状态条 | 现有 status line | 常驻当前档，一行以内 |
| Desktop Composer 输入框旁 | 对照 `Composer.tsx` | 档位指示 + 可点切 |
| `tests/test_protocol/`（新增黄金件） | — | 两端同一字段 |

**规范限制**

- 两端只投影协议，不得各存一份 localStorage 档位。
- 缺一端失败。
- 切换到完全访问必须确认弹窗（PHASE-K DK2 混合粒度：CLI 逐项，设置面板可汇总）。

**操作步骤**

1. protocol 字段：`access_tier: "workspace" | "full"`，session pin（KC13）：会话内切换完全访问可立即影响隔离剖面（这是 L0 执行门，不改 `tools_digest`）。
2. CLI：状态条显示当前档；命令可切。
3. GUI：输入框旁显示；设置页同一字段。
4. 测试：只开 CLI 的 fixture 应失败本卡——写一个「GUI 客户端读同一方法」的契约。

**验收命令**

```powershell
python -m pytest tests/test_protocol/test_access_tier.py -q
cd frontend\opentui-app; npx tsc --noEmit; npx vitest run
```

**完成判据**

- [ ] CLI 与 GUI 都能读/切同一档
- [ ] `/permission` 既有三档行为 diff 为零
- [ ] 完全访问有确认；工作区档是默认
- [ ] 无第二份前端存储（`git grep access_tier` 不得命中 localStorage）
- [ ] GPT-5.6 审计 PASS

**回滚**：revert 本卡。PP10 内核可独立保留。

**常见坑**：两端各存一份；把 `/permission full_auto` 改名为「完全访问」。

**Commit**：`feat(surface): PP11 access tier`

---

### PP20 · 结构化补丁原语

`P1` / 2–3d / 依赖无（tools.edit 缝独立）/ **owner: backend**

**背景**

备忘 §3.2：主变异原语要向 Codex `apply_patch` 看齐。现状 `tools/edit.py:15` `edit_file(filePath, oldString, newString, replaceAll=False)` 仍是字符串替换；匹配失败时拼 fuzzy 提示（L23–52），成功则 `atomic_write_text`（L81）。

字符串替换的问题：不可审（模型说改了哪几行，用户只能信）、不可回放（没有 hunk）、多处匹配要靠 `replaceAll` 赌。

**调研与 Verdict**

`Verdict: Extend — Codex apply_patch 与 Aider editblock/udiff — 可审可回放。不嵌 Aider 循环。`

**涉及文件**

| 路径 | 锚点 | 本卡怎么动 |
|---|---|---|
| `tools/edit.py:8` | `class EditInput` | 增加补丁路径；保留 old/new 作为兜底 |
| `tools/write.py` | `_TEST_FUNCTION_CAP`（edit.py L66 已引用） | 补丁路径必须走同一测试函数上限 |
| `core/builtin_tool_registration.py` | `edit` 工具注册 | 工具名保持 `edit`（或并列 `apply_patch` 但 **tools_digest 策略必须先写进卡内并跑 IDENTITY**）。推荐：同一工具新参数，避免 L1 前缀爆炸 |
| `tests/test_tools/` | 现有 edit 测试 | 补丁用例 + 旧字符串替换仍绿 |
| `core/agent_v2.py` | — | **禁止**改循环 |

**规范限制**

- 主路径 = 结构化补丁（hunk / udiff / Codex patch 语法三选一，开工前在卡内写死一种 Verdict 子句）。
- 字符串替换仅兜底，失败信息保持现有 fuzzy。
- 补丁必须可从 trace 回放成同样字节。
- 不改 S1 里工具描述到「每个文件一种 tool」。

**操作步骤**

1. 先写 `tests/test_tools/test_apply_patch.py`：给定旧文件 + patch，得到新文件；再 apply 同一 patch 必须 no-op 或明确已应用。
2. `edit.py` 增加 `patch` 参数。解析失败返回 `[error: ...]`，不抛到 loop。
3. 与 `write.py` 的测试函数 cap 共用。
4. 文档 `docs/modules/` 写清「主路径是补丁」。

**验收命令**

```powershell
python -m pytest tests/test_tools -q --timeout=120
python -m pytest tests/test_cache/test_s1_s2_split.py -q
```

**完成判据**

- [ ] 主路径结构化补丁可审可回放，有测试
- [ ] 旧 `oldString/newString` 兜底仍绿
- [ ] 未改 `agent_v2` 循环
- [ ] PREFIX 绿
- [ ] GPT-5.6 审计 PASS

**回滚**：revert 本卡。兜底路径保证旧会话还能改文件。

**常见坑**：改成两个 tool 导致 `tools_digest` 变；在 agent_v2 里特殊处理 patch。

**Commit**：`feat(tools): PP20 structured patch`

---

### PP21 · 红绿 diff 与审计

`P1` / 2d / 依赖 PP20 / **owner: frontend**

**背景**

备忘 P4 / §3.2 / §8 审计行：CLI 要在对话流里红删绿增；GUI 要可点完成物 + diff + 耗时。仓库已有 JSONL 审计（`core/safety/audit.py`），**那不是用户可见完成物**。§8 把「审计」主去向指到本卡，就是为了堵住「有日志就算做完」。

**调研与 Verdict**

`Verdict: Compose — OpenCode/Grok 对话流 diff + Codex 完成物。不嵌别人 TUI。`

**涉及文件**

| 路径 | 锚点 | 本卡怎么动 |
|---|---|---|
| OpenTUI 对话流渲染 | `frontend/opentui-app/src/` 消息泡 | 消费工具结果里的 patch/diff 字段 |
| Desktop 完成物面板 | `frontend/desktop-app/src/renderer/` | 可点文件 + 红绿 + 耗时 |
| 协议 tool 事件 | `protocol/` 已有 tool 通知 | **尽量不新发明方法**；缺字段才按 GP8 加 |
| `tests/` 前端 vitest / node:test | 新增 | 渲染契约 |

**规范限制**

- 两端只渲染协议里的 diff，不在 Renderer 里对文件再 diff 一次（PHASE-G 红线：表面不算业务）。
- CLI 既有 42 条命令定义 diff 为零；本卡是呈现，不是新命令。若加 `/diff`，必须与 PHASE-N N8 清单对齐，不得抢先改 N8 卡面。

**操作步骤**

1. 约定 tool 结果携带 `unified_diff` 或 PP20 的 patch 原文。
2. OpenTUI：删除行红、新增行绿；无 ANSI 的 Windows 终端用标记前缀，但语义相同。
3. Desktop：完成物列表可点，打开 diff；展示耗时（已有 usage 计数在 `Session.prompt`）。
4. 负向：只有 JSONL、对话流无 diff = 失败。

**验收命令**

```powershell
cd frontend\opentui-app; npx tsc --noEmit; npx vitest run
cd frontend\desktop-app; node --test src/renderer/src/lib/*.test.mts
```

**完成判据**

- [ ] CLI 对话流能看见红删绿增
- [ ] GUI 能点文件看 diff + 耗时
- [ ] 不是「只有 JSONL 审计」
- [ ] GPT-5.6 审计 PASS

**回滚**：revert 本卡。PP20 内核可独立保留。

**常见坑**：只做 GUI；在前端重新计算 diff 与后端不一致。

**Commit**：`feat(surface): PP21 visible diff`

---

### PP30 · hooks.json 运行时

`P1` / 跟随 K14 工时 / 依赖 PHASE-K K19、K12；**实现跟 K14，本卡不另起事件名** / **owner: backend**

**背景**

备忘 §3.3：要把脚本挂进循环。PHASE-K **K14** 已立项事件桥，且硬依赖 K19。K14 未开工——本卡不是第二套 hooks 运行时，是产品意图侧的「必须落地 K14 + 网装默认关」叠加约束。

**调研与 Verdict**

`Verdict: Adopt — Codex hooks.json — 事件到 shell。事件表以 K14 为准。`

**涉及文件**

以 K14 指定为准（`core/hooks.py` 或 `core/plugins` 桥）。本卡额外锁：

- 网装默认关（PC7）
- 禁止 `SessionStart` 注入团 bootstrap（PHASE-L **LC16**）
- hooks 零进前缀（K14 完成判据已有）

**规范限制**

- 不另起事件名。K14 表没有的外部事件：忽略并按 KC9 报告。
- 本卡 **不得** 在 K19 之前合入对用户开放的网装入口。

**操作步骤**

1. 若 K14 未合入：本卡与 K14 **同一 commit 范围禁止**——先做 K14，本卡只补产品侧测试：网装默认关、CLI/GUI 尚未做入口（入口是 PP31）。
2. 若 K14 已合入：补 `tests/test_plugins/test_hooks_default_disabled.py` 断言 GitHub 来源 `enabled is False`。
3. PREFIX + IDENTITY。

**验收命令**

K14 验收命令全文，外加 PREFIX。

**完成判据**

- [ ] 网装 hooks 默认关，有测试
- [ ] 本机创建的 hooks 可开，有测试
- [ ] 无第二套事件名（`git grep SessionStart` 只有 K14 映射）
- [ ] 未用 hook 做团 bootstrap
- [ ] GPT-5.6 审计 PASS

**回滚**：跟 K14 revert。

**常见坑**：为备忘「会话开始」再发明 `on_session_start` 内部事件。

**Commit**：`feat(hooks): PP30 hooks json`

---

### PP31 · `/hooks` 与 GUI 面板

`P1` / 1d / 依赖 PP30 / **owner: frontend**

**背景**

PC1。没有入口的 hooks 等于没有。OpenTUI 现状无 `/hooks`。

**调研与 Verdict**

`Verdict: Extend — Codex 设置/hooks 可观察入口。`

**涉及文件**

| 路径 | 锚点 | 本卡怎么动 |
|---|---|---|
| `frontend/opentui-app/src/commands.ts` | `AVAILABLE_COMMANDS` | **追加** `/hooks`，既有条目定义不变 |
| Desktop 设置 | 对照 PHASE-M 四组容器 | 挂进「集成」分区语义，不新造第五组除非 M7 已有空位 |
| 协议 | hooks 列表/启用 | 两端同一方法 |

**操作步骤**

1. `/hooks` 列出已装 hooks + 启用态；启用网装 hook 必须二次确认。
2. GUI 面板同一数据源。
3. 未实现前若 N8 已注册占位，执行返回「该能力尚未合入」——本卡把它变成真的。

**验收命令**

```powershell
# 命令注册测试（开工时 Grep 现有 command catalog 测试文件名，禁止猜）
cd frontend\opentui-app; npx tsc --noEmit; npx vitest run
```

**完成判据**

- [ ] CLI `/hooks` 与 GUI 面板能力对等
- [ ] 两端同一协议方法
- [ ] 既有命令定义 diff 为零（只允许追加）
- [ ] GPT-5.6 审计 PASS

**回滚**：revert 本卡。

**常见坑**：只做 GUI；启用时不确认。

**Commit**：`feat(surface): PP31 hooks ui`

---

### PP40 · Computer Use 事实观察

`P2` / 3–5d / 依赖 PP11、ARCH-003；**不依赖**「先做完 PHASE-N N12」 / **owner: backend**

**背景**

备忘 §4：要看见窗口/标签事实，不是猜。08-12 冻结像素默认；口述覆盖的是产品要不要做直接控制，**不是**授权你自研 CUA。

**调研与 Verdict**

`Verdict: Extend — iFurySt/open-codex-computer-use — get_app_state/list_apps，禁止自研 CUA。`

开工前补 SPDX：用 GitHub API `license.spdx_id`（PHASE-L **LC17** 口径）。`NOASSERTION` / 无 LICENSE → 本卡 `BLOCKED_PREREQUISITE`，改列替代 MCP，**禁止**把对方源码抄进 `core/`。

**涉及文件**

| 路径 | 锚点 | 本卡怎么动 |
|---|---|---|
| 新增 `core/cu/` 或 `appserver` MCP 适配器 | — | stdio 拉起 ocu；**独立进程** |
| capability 开关 | `core/capabilities/defaults.py`（K1 后） | 默认 `False`；无该文件则 BLOCKED 只影响 PP42，观察适配器仍可先写死关 |
| `core/agent_v2.py` | — | **禁止**截图循环 |
| MCP 杀树 | `local-agent-process-isolation` 纪律 | 会话结束必须杀 MCP 子进程 |
| `tests/test_cu/test_observe.py`（新增） | — | mock MCP：返回无障碍树，不返回模型瞎编 |

**规范限制**

- 默认关。S1 无截图工具表。
- 观察来自 OS 事实（AX/AT-SPI/UIA），测试里断言 payload 含 `source=accessibility` 一类字段（以 ocu 实际 JSON 为准，GP3）。
- **禁止**用 `cli_run` 冒充本卡。
- 与 `cli_list`/`cli_run` 并存：负向测试。

**操作步骤**

1. 核 SPDX，写入卡内（本文件开工时补一行 commit hash）。
2. stdio MCP 接入；工具名以 ocu 为准，不要改名成 `computer_use_1`。
3. 默认不注册进冻结前缀：关 = 工具不在 allowlist（PHASE-K 能力层级 L0 执行门）或整段 L1 待下次 session（若工具描述会进 digest —— 选一种，写进本卡，优先 **不进 S1**：工具常驻描述用执行门关死，与 KC2 一致）。
4. 杀树测试：session close 后进程不在。

**验收命令**

```powershell
python -m pytest tests/test_cu/test_observe.py tests/test_cache/test_s1_s2_split.py -q
```

**完成判据**

- [ ] 观察来自 OS 事实，有测试
- [ ] 默认关；S1 无截图工具表
- [ ] 未自研 CUA；未把 ocu 源码 vendoring 进 loop
- [ ] `cli_list`/`cli_run` 仍在
- [ ] MCP 子进程随会话杀树
- [ ] GPT-5.6 审计 PASS

**回滚**：revert 本卡。关是默认，回滚后用户无 CU。

**常见坑**：截图当唯一路径；把工具表塞进 S1；用 bash `screencapture` 冒充。

**Commit**：`feat(cu): PP40 observe via open-codex-computer-use`

---

### PP41 · 授权内点键滚切

`P2` / 2–3d / 依赖 PP40 / **owner: backend + frontend**

**背景**

备忘 §4 表「能在授权范围内点、键、滚、切窗口」。无授权必须拒绝。

**调研与 Verdict**

`Verdict: Extend — 同一仓 click/type_text/press_key。`

**涉及文件**：PP40 同一适配器。表面开关在 PP42。本卡做执行门。

**规范限制**

- 访问档不足 → 拒绝（接 PP11）。
- 像素点击不是唯一路径；无障碍树 action 优先。
- CLI 与 GUI 都能触发同一 MCP tool。

**操作步骤**

1. deny 测试：workspace 档 + CU 开，仍拒绝出工作区语义的系统级点击（若 ocu 是全桌面能力，则 **CU 开 必须 伴随完全访问确认**——写进完成判据）。
2. 有授权：`click` / `type_text` / `press_key` 真执行（集成测试可 mock MCP）。
3. 失败关闭：MCP 挂了不得改走「模型猜坐标」。

**验收命令**

```powershell
python -m pytest tests/test_cu/test_actions.py tests/test_cu/test_observe.py -q
```

**完成判据**

- [ ] 无授权拒绝，有测试
- [ ] 有授权真执行，有测试
- [ ] CLI 与 GUI 都能动作（或本卡先内核、PP42 补齐开关——若本卡先合入，开关必须已能关死 action）
- [ ] 像素不是唯一路径
- [ ] GPT-5.6 审计 PASS

**回滚**：revert 本卡。

**常见坑**：workspace 档下静默全桌面点击。

**Commit**：`feat(cu): PP41 actions`

---

### PP42 · CU 开关 CLI + GUI

`P2` / 1d / 依赖 PP40、PHASE-K K1/K2 / **owner: frontend**

**背景**

PC6 / PC8。设置 + 命令两条路径。默认关。热改前缀禁止。

**调研与 Verdict**

`Verdict: Extend — PHASE-K 能力层级 L0/L1 开关模型。`

**涉及文件**

| 路径 | 锚点 | 本卡怎么动 |
|---|---|---|
| `core/capabilities/defaults.py` | `BUILTIN_CAPABILITIES` | 增加 `computer_use`，`default_enabled=False` |
| OpenTUI `/plugin` 或 `/cu` | PHASE-N N9 只出 `/plugin`（DN6） | **不要**再发明 `/capability`。CU 作为 builtin 出现在 `/plugin` 列表，来源标签 builtin |
| Desktop 设置 | 同上 | 同一 `capability/set` |

K1/K2 未落地 → `BLOCKED_PREREQUISITE`。

**操作步骤**

1. 关 = 执行门拒绝 CU 工具，S1 不变。
2. 若实现成 L1（工具描述进 digest）：会话内切换只写 pending，提示下次会话生效（KC3）。
3. IDENTITY 测试。

**验收命令**

```powershell
python -m pytest tests/test_cache/test_prefix_identity_default_unchanged.py tests/test_capabilities -q
```

**完成判据**

- [ ] 设置与命令两条路径；默认关
- [ ] CLI 与 GUI 对等
- [ ] 无热改前缀
- [ ] GPT-5.6 审计 PASS

**回滚**：revert 本卡。

**常见坑**：热改前缀；另做 `/cu` 又做 `/capability` 两个真相源。

**Commit**：`feat(cu): PP42 toggle`

---

### PP50 · 加号第一屏已下载插件

`P1` / 2d / 依赖 PHASE-K 宿主（`plugin/list`）、GX24 协议；可与 K18 并行做 IA，但数据源必须是 `plugin/list` / **owner: frontend**

**背景**

备忘 §5：点击 `+` 第一屏是已经下载过的插件。现状 `ComposerPlusMenu.tsx:24-60` 第一屏是「文件和文件夹 / 在项目中使用 / 目标 / 计划模式」，**零插件**。这不是「缺个按钮」，是信息架构做错了。

PC2：skill / MCP 不得冒充加号。invoke 仍走 `plugin/*`（`appserver/server.py:2603` `plugin/list`）。

**调研与 Verdict**

`Verdict: Build — 本机闭源观察：Codex Desktop 加号三页 — 只抄 IA。宿主不另造。`

**涉及文件**

| 路径 | 锚点 | 本卡怎么动 |
|---|---|---|
| `frontend/desktop-app/src/renderer/src/components/ComposerPlusMenu.tsx` | `data-testid="composer-plus-menu"` | 第一屏改为 `plugin/list` 已装；空态有文案 |
| `frontend/opentui-app/src/commands.ts` | 无 `/plugin` | 追加 `/plugin` 列出已装、启用某一个（若 N8/N9 已追加则接线，不改既有 42 条） |
| `protocol/requests.py:1349` | `plugin/list` | 只消费，不第二套 |
| GX24 市场页 | 发现未下载 | **不要**把市场塞进第一屏 |

**规范限制**

- 第一屏可含「插件管理」入口，但列表主体是已下载。
- 现有四按钮（附件/工作区/目标/计划）挪到加号的其它分组或保留在第一屏**下方**，不得把已装插件挤没。
- 禁止 `plugin/list` 返回 skills 或 MCP servers。

**操作步骤**

1. 契约：`plugin/list` fixture 两条插件 → 加号第一屏两条；零插件 → 空态「还没有已下载的插件」+ 管理入口。
2. 点一项 = 启用/invoke 已有 plugin 路径，不 new CapabilityService。
3. CLI `/plugin` 列出同一数组。
4. `git grep` 证明加号组件不 import `core/`。

**验收命令**

```powershell
python -m pytest tests/test_plugin.py tests/test_gx24_plugin_consume.py -q
cd frontend\desktop-app; 跑加号相关测试（开工 Grep composer-plus）
```

**完成判据**

- [ ] 第一屏是已下载插件，不是 skill/MCP 目录
- [ ] 空态合法
- [ ] CLI `/plugin` 对等
- [ ] 无第二 invoke
- [ ] GPT-5.6 审计 PASS

**回滚**：revert 本卡。宿主不动。

**常见坑**：把 `/list-skills` 填进加号；市场与已装混成一堆。

**Commit**：`feat(plugin): PP50 plus menu IA`

---

### PP51 · 标签页与旧会话搜索

`P1` / 2d / 依赖 PP50 / **owner: backend + frontend**

**背景**

备忘 §5.1 第 3–5 点：当前浏览器标签、历史对话、底部搜索。CLI 也要把当前页/旧会话塞进上下文（PC1）。

**调研与 Verdict**

`Verdict: Build — 本机闭源观察：Codex 加号第三页标签。`

**涉及文件**

协议新方法须先落 `protocol/requests.py`（GP8），例如 `context/tabs` / `thread/search`——**开工 Grep 是否已有**，有则复用。Desktop 加号第三页；OpenTUI 命令等价。

**操作步骤**

1. 列出可引用的标签/旧会话（只读投影）。
2. 选中后经 `append_turn_context` 进 user 后缀，不进 S1。
3. CLI 有命令能完成同一件事。

**验收命令**：协议测试 + PREFIX。

**完成判据**

- [ ] CLI 也能把当前页/旧会话塞进上下文
- [ ] S1 不变
- [ ] 只做 GUI 失败
- [ ] GPT-5.6 审计 PASS

**回滚**：revert 本卡。

**常见坑**：把网页 HTML 整页塞进 S1。

**Commit**：`feat(plugin): PP51 tabs history`

---

### PP60 · goal 服务端对象

`P1` / 跟随 N4–N6 / 依赖 PHASE-N N4–N6（**本卡不另做存储**）/ **owner: backend**

**背景**

备忘 §6.3 对照：PHASE-N 已定性 Desktop `/goal` 为 localStorage 字符串前缀。现状仍在：

```30:34:frontend/desktop-app/src/renderer/src/lib/goalSettings.mts
export function applyGoalToPrompt(goal: string | undefined, text: string): string {
  const trimmedGoal = goal?.trim() ?? ''
  if (trimmedGoal === '') return text
  return `持续目标：${trimmedGoal}\n\n${text}`
```

`App.tsx` 仍调用它。后端不知道 goal。PP60 的唯一合法实现就是 **做完 N4–N6**，本卡提供产品意图侧的挂接与禁止项。

**调研与 Verdict**

`Verdict: Extend — PHASE-N N4–N6 — 不另做存储。`

**涉及文件**：以 N4–N6 为准（`core/goals/model.py` 新增、`goal/*` 协议、删除 `goalSettings.mts`）。

**规范限制**

- 五字段：`objective` / `acceptance` / `budget` / `checkpoints` / `reinjection`（N4）。
- 检查点写进 GX9 计划文件，不建第二套（N5 / DN3）。
- 重注入走 user 后缀（N5 / DN4）。
- 禁止本卡发明 `core/goals_v2/`。

**操作步骤**：按 N4→N5→N6 顺序。本卡完成判据多一条产品负向：`git grep applyGoalToPrompt` 零命中。

**验收命令**：N4–N6 验收 + PREFIX。

**完成判据**

- [ ] 后端知道 goal（服务端对象）
- [ ] `applyGoalToPrompt` 与 localStorage 键已删除
- [ ] S1 零变化
- [ ] 未另做存储
- [ ] GPT-5.6 审计 PASS

**回滚**：跟 N4–N6 revert。

**常见坑**：继续拼 prompt 前缀「先让 GUI 能用」。

**Commit**：`feat(goal): PP60 server object`

---

### PP61 · Codex goal UX

`P1` / 2d / 依赖 PP60 / **owner: frontend**

**背景**

备忘 §6.1：侧栏可见、可暂停/恢复、长任务耗时可见、完成后给文件链接。N6 管五字段对话框与删 localStorage；本卡管 **Codex 目标模式呈现**。

**调研与 Verdict**

`Verdict: Build — 本机闭源观察：Codex 目标模式侧栏。`

**涉及文件**

- OpenTUI：`/goal` 对话框 + 状态行（N6 已列 `commands.ts` / `DialogGoal.tsx`）
- Desktop：侧栏目标会话可辨认；完成物链接接 PP21
- 暂停/恢复：优先复用 PHASE-N `run/start|status|cancel`，禁止本卡发明第四套长任务 RPC

**完成判据**

- [ ] CLI 与 GUI 都能暂停/恢复、见耗时、见完成物
- [ ] 输入框不再偷偷拼「持续目标」
- [ ] 两端同一 `goal/*`
- [ ] GPT-5.6 审计 PASS

**验收命令**：命令测试 + 前端测试。

**回滚**：revert 本卡。对象层 PP60 可保留。

**常见坑**：只做侧栏皮肤，没有暂停/恢复。

**Commit**：`feat(goal): PP61 codex ux`

---

### PP62 · Grok Build SOP

`P1` / 2–3d / 依赖 PP60、PP70 / **owner: backend**

**背景**

备忘 §6.3：goal 激活后的节拍抄 Grok Build：Plan → Search → Build。未批准计划拒绝改项目文件（除计划文件）。禁止另发明「目标流水线」，禁止 `SessionStart` 注入（LC16）。

**调研与 Verdict**

`Verdict: Adopt — Grok Build Plan/Search/Build。接到 plan_files 与 turn_router 已有缝。`

**涉及文件**

| 路径 | 锚点 | 本卡怎么动 |
|---|---|---|
| `appserver/plan_files.py:73` | `implement(..., confirm: bool)` | 已要求 `confirm is not True` 就拒绝。本卡把「goal 激活 ⇒ 未批准只许写计划文件」接到执行门 |
| `core/turn_router.py` | PHASE-FIX 冻结面 | 只加策略委托，不改 identity |
| `core/safety/` 写屏障 | — | 计划模式 = 除 `RXYCODE_DATA_DIR/plans` 外拒绝 write/edit/patch |
| `tests/test_plan_write_barrier.py`（新增） | — | goal on + plan unapproved → write 失败 |

**规范限制**

- 不另做状态机框架。
- Search 步 = 强制走仓库内已有 read/grep/ls，不是新 tool。
- Build 步可派子代理，但 **不** 因此打开 multiagent 产品默认开关（DK1）。

**操作步骤**

1. 写屏障测试先红。
2. 执行门读 goal+plan 状态。
3. PREFIX：屏障不得进 S1。

**验收命令**

```powershell
python -m pytest tests/test_plan_write_barrier.py tests/test_cache/test_s1_s2_split.py -q
```

**完成判据**

- [ ] goal 激活且计划未批准时，项目文件写失败（计划文件除外），有测试
- [ ] 无第三套流水线
- [ ] 无 SessionStart 团 bootstrap
- [ ] GPT-5.6 审计 PASS

**回滚**：revert 本卡。

**常见坑**：口头「先别写代码」当门；另写 GoalPipeline 类。

**Commit**：`feat(goal): PP62 grok build sop`

---

### PP70 · Plan 一等对象

`P1` / 1–2d / 依赖 `appserver/plan_files.py`（已存在）/ **owner: backend + frontend**

**背景**

备忘 §6.2：计划能打开、能改、能批准、能一键开始构建。现状：`PlanFileService.persist` 已把 markdown 写到 `RXYCODE_DATA_DIR/plans`（`plan_files.py:23-71`）；`implement` 已要 `confirm=true`（L73-86）。缺的是两端模式切换与「未批准只许改计划文件」的用户可见门（后者与 PP62 分担：本卡做对象与 UX，PP62 做 SOP 屏障）。

OpenTUI 已有 `/plan` `/build`（`commands.ts:26-27`）。本卡 **不得** 改这两条既有命令的 category/action 语义，除非开工 Grep 证明它们还是空壳——若已有行为，只接 `plan_files`，不改名。

**调研与 Verdict**

`Verdict: Extend — 本仓 plan_files + Codex Plan 可观察门。`

**涉及文件**：`appserver/plan_files.py`；OpenTUI `/plan` `/build`；Desktop `ComposerPlusMenu` 计划模式按钮（`plus-plan-mode`）；`frontend/desktop-app/src/renderer/src/lib/planDocument.test.mts`（已有）。

**操作步骤**

1. 输入框可进/出 Plan；两端同一协议。
2. 计划可打开/改/批准；批准走已有 `confirm=true`。
3. 只靠口头「先别写代码」不算完成。

**验收命令**：plan 协议测试 + 前端 `planDocument` 测试。

**完成判据**

- [ ] CLI 与 GUI 都能进/出 Plan
- [ ] 计划是可打开的对象，不是聊天里一段话
- [ ] 未批准不能 `implement`
- [ ] GPT-5.6 审计 PASS

**回滚**：revert 本卡。`plan_files.py` 已有逻辑尽量不回滚。

**常见坑**：GUI 一个 bool、CLI 另一套 plan id。

**Commit**：`feat(plan): PP70 first class plan`

---

### PP80 · GitHub 内嵌浏览器

`P2` / 3–5d / 依赖 §3.5 形态 / **owner: frontend**

**背景**

备忘 §8：GUI 内嵌 GitHub；「请到外部浏览器打开」不算完成。P1 不塞 Chromium。

**调研与 Verdict**

`Verdict: Extend — open-browser-use / 系统 WebView — 不塞整份 Chromium 到 P1。iFurySt 亦指向浏览器自动化，CU 观察与内嵌浏览不是同一张卡。`

**涉及文件**：Desktop webview（新增）；CLI 至少能开/控（命令或把 URL 交给 CU 观察，但本卡完成判据不能只用 CU 冒充「内嵌」）。

**完成判据**

- [ ] GUI 内嵌；CLI 至少能开/控
- [ ] 不是「请到外部浏览器打开就结束」
- [ ] GPT-5.6 审计 PASS

**验收命令**：webview 测试（若有）；无则契约测试 + 手工证据贴 PR。

**回滚**：revert 本卡。

**常见坑**：P1 打包 Chromium；只做 GUI。

**Commit**：`feat(browser): PP80 embed`

---

### PP81 · GUI 终端

`P2` / P1 可降级 / **owner: frontend**

**背景**

备忘 §8：GUI 必须有终端。Agent 跑的命令要能看见、能点进去、能接管。CLI 本身即是终端，**不能**拿 CLI 勾 GUI。

**调研与 Verdict**

`Verdict: Extend — node-pty 惯例。`

**涉及文件**：Desktop 终端面板（新增）。P1 降级：协议事件可见命令 + 外开。

**完成判据**

- [ ] GUI 必须有终端；P1 降级路径写进本卡并有测试（事件可见）
- [ ] 能看见 agent 命令、能点进去
- [ ] GPT-5.6 审计 PASS

**验收命令**：事件可见测试。

**回滚**：revert 本卡。

**常见坑**：CLI 有 bash 就算 GUI 完成。

**Commit**：`feat(term): PP81 panel`

---

### PP90 · 侧边聊天

`P2` / 1–2d / 依赖 `appserver/side_chat.py`（已存在）/ **owner: frontend**

**背景**

备忘 §8：主任务不中断的旁路。现状：`SideChatService`（`appserver/side_chat.py:21`）+ 协议 `thread/side_chat/create|close`（`protocol/requests.py:255`）+ `tests/test_side_chat.py` 已有。缺的是 OpenTUI `/btw`（或旁路）与 Desktop 侧栏消费。

**调研与 Verdict**

`Verdict: Extend — 本仓 side_chat + Cursor/Grok /btw。禁止第二套 loop。`

**涉及文件**

| 路径 | 锚点 | 本卡怎么动 |
|---|---|---|
| `appserver/side_chat.py:27` | `create` | 只消费；不复制父消息（已有 `context_copied: False`） |
| `appserver/server.py:2752` | `thread/side_chat/create` | 已接线 |
| OpenTUI | 无 `/btw` | 追加命令或旁路面板 |
| Desktop | 侧栏 | 同一 RPC |
| `core/session.py` | `Session.prompt` | **禁止**再开一个 AgentV2 大脑；side 仍走同一 Session 假面 |

**操作步骤**

1. GUI 侧边聊天调用已有 create/close。
2. CLI `/btw` 或 TUI 旁路同一方法。
3. 断言无第二套 `AgentV2()` 构造仅为 side chat（ARCH-001）。

**验收命令**

```powershell
python -m pytest tests/test_side_chat.py -q
```

**完成判据**

- [ ] 主任务不中断
- [ ] CLI 有旁路或 `/btw`
- [ ] 无第二套 loop
- [ ] GPT-5.6 审计 PASS

**回滚**：revert 表面。服务端已有代码不删。

**常见坑**：side chat 走 `api_server.py /chat`。

**Commit**：`feat(chat): PP90 side chat`

---

### PP100 · 子代理列表与点进

`P1` / 2d / 依赖 Phase D/E 运行时 / **owner: frontend**

**背景**

备忘 §9：用户还没在产品里见过合格的子代理呈现。OpenTUI **已经有** `/children` `/child` `/parent`（`commands.ts:57-59`）。本卡不是再注册三个命令，是让列表+点进在 **CLI 与 GUI 都真能用**，未点进只显示摘要。

**调研与 Verdict**

`Verdict: Extend — OpenCode TUI 展开 + D/E 运行时 — 只补表面。不默认打开 multiagent 产品开关。`

**涉及文件**：subagent 协议事件；OpenTUI 已有命令接真数据；Desktop 面板。`core/agents/` 编排 **不在本卡改**。

**规范限制**

- 不把子对话刷进主泡泡。
- 不因此把 DK1 的 multiagent 默认翻成 True。

**操作步骤**

1. 契约：派出 subagent 后 `/children` 非空；`/child <id>` 进入；GUI 同一事件。
2. 未点进：主视图只有摘要（谁在跑、状态、耗时）。
3. 既有 `/children` 定义若已存在，**行为补齐但字段名不变**（NC6：不许改 name/category/action；允许修 handler）。

**验收命令**：subagent 契约测试 + 前端测试。

**完成判据**

- [ ] CLI 与 GUI 都能看见列表并点进
- [ ] 未点进只显示摘要
- [ ] 未打开 multiagent 产品默认开关
- [ ] GPT-5.6 审计 PASS

**回滚**：revert 本卡。

**常见坑**：子代理消息刷进主泡泡；为呈现改 D/E 运行时。

**Commit**：`feat(obs): PP100 subagent drill-in`

---

## §5 Phase P 出口检查

- [ ] 每张 PP 卡有 `Verdict:`、涉及文件表、编号步骤、验收命令、可勾完成判据、回滚、常见坑、Commit
- [ ] 每张用户可见能力卡有 CLI **和** GUI 判据（PP10 内核卡有协议字段即可，呈现在 PP11）
- [ ] §8 十四行与备忘 §12 愿望 **有且仅有** 主去向
- [ ] PC0 写在 §0.4，且每卡 Verdict 非空
- [ ] 未实现产品循环代码（本目标文档重写不改 `core/agent_v2.py` 循环）
- [ ] 未改 PHASE-K/L/N/G 卡正文
- [ ] 跨文档 L0/L1 均带「PHASE-K 能力层级」或「PHASE-L L0a」前缀

---

## §6 与既有 Phase 的接口与冲突消解

**动手前必读。** 本文件是叠加，不是修订器。

| 主题 | 既有权威 | 本包怎么接 | 禁止 |
|---|---|---|---|
| 前缀 / S1 | PHASE-FIX FXC3、PHASE-K KC1–KC5 | PREFIX 每卡必跑 | 热改前缀；skills 进 S1 |
| 插件宿主 | PHASE-K K12/K18/K19、`plugin/*` | PP50 只改 IA | 第二 invoke |
| skill 发现 | PHASE-K K9/K10 | PP1 只强制斜杠 invoke | 绕过 K9 自己扫目录 |
| hooks 运行时 | PHASE-K K14 | PP30 跟 K14 | 新事件名 |
| `/goal` 对象 | PHASE-N N4–N6 | PP60 = 做这三张 | 第二套存储；`applyGoalToPrompt` |
| 长任务 RPC | PHASE-N N1–N3 | PP61 暂停/恢复复用 run/* | 把 `session/prompt` 超时改成 14h |
| CLI 命令增量 | PHASE-N NC6、N8 | 只追加 | 改既有 42 条定义 |
| GUI 基线 / 加号协议 | PHASE-M、GX24 | PP50 消费 `plugin/list` | 改 GX24 卡面编号 |
| Computer Use | 08-12 + ARCH-003 | PP40 接 ocu | 自研 CUA；用 CLI-Anything 替代 |
| 加团 | PHASE-L L11、WFT* | 不在本文件 | 把团 YAML 写进 PP 卡 |
| 拆核 | ARCH-004、DEV-ORDER SP* | 本包不执行 | 顺手改 `agent_v2` 循环 |

L0/L1 跨文档写法：写「PHASE-K 能力层级 L0」或「PHASE-L L0a」，禁止裸 `L0`。

---

## §7 证据缺口与后续

- open-codex-computer-use 许可证须在 **PP40 开工前** 核 SPDX（PC0 / LC17）。检索日 star 不是核验。
- PHASE-FIX.md 若磁盘缺失：不变量以 `docs/modules/core.md` 与 PHASE-K KC1–KC5 为准。
- `core/capabilities/defaults.py` 在 K1 落地前不存在：PP42 BLOCKED，其它卡继续。
- `test_prefix_identity_default_unchanged.py` 在 K2 落地前可能不存在：IDENTITY 步同样 BLOCKED，不得用全量 pytest 绿冒充 identity 冻住。
- OpenTUI 命令条数已从 PHASE-N 成文时的 37 漂到 2026-09-02 的 42。NC6 以 **开工当日 git 中的定义** 为准，不要把 37 写进新测试。
- 本机闭源 Codex 截图只作 IA 参照，不把图标/文案当协议。

---

## §8 覆盖表（备忘 §12）

| 备忘愿望 | 主去向 | CLI | GUI |
|----------|--------|-----|-----|
| 沙箱 + 访问档 | PP10+PP11 | 要 | 要 |
| 结构化改文件 + 红绿 diff | PP20+PP21 | 要 | 要 |
| hooks | PP30+PP31 | 要 | 要 |
| Computer Use（控制电脑 + 事实观察） | PP40+PP41+PP42 | 要 | 要 |
| 加号：已下载插件 / 标签 / 旧会话 | PP50+PP51 | 要 | 要 |
| `/goal` 目标模式 | PP60+PP61 | 要 | 要 |
| Plan 模式 | PP70 | 要 | 要 |
| `/goal` 之后的 SOP | PP62 | 要 | 要 |
| 斜杠定死 skill | PP1 | 要 | 要 |
| GitHub 内嵌浏览器 | PP80 | 要 | 要 |
| 终端 | PP81 | 本身即是 | 要 |
| 审计 | PP21 | 要 | 要 |
| 侧边聊天 | PP90 | 要 | 要 |
| 子代理 / 多代理可点进 | PP100 | 要 | 要 |
