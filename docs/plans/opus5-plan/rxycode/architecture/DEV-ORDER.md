# 活开发顺序（权威）

> **本文件是「下一步做什么」的唯一入口。** 既有 `PHASE-A`…`PHASE-O` / PHASE-FIX / G 卡正文仍是施工单位（**不改那些卡的逻辑**）。本文件只排波次、标并行、把维护卡 SP* 写清楚。
> **不是现行顺序：** `docs/RxyCode_PLAN.md`、gitignored 的 [`00-EXECUTION-PLAN.md`](../00-EXECUTION-PLAN.md)（它仍是 Phase 0–4 与任务卡字段规范的历史权威，**每天打开哪张卡以本文件为准**）。
> **PHASE-P 不是 F/L 的下一级主链**，只是备忘叠加包（像 PHASE-J），卡插进 K/N/G/L。
> **下一步**：开工 [`PHASE-L-TEAMS-INCREMENT`](./PHASE-L-TEAMS-INCREMENT.md) 的 **WFT1**。前置是 `validate_team`（PHASE-F F3）与 FXC3/S1，**不是** PHASE-L 整份文档、L13/L14/L17。可与 PHASE-L L0a、PHASE-N N0、PHASE-M M0a 并行。
> **执行模型**：读卡与实现由 **Grok 4.6** 按各 PHASE §0 执行；审计 PASS 前禁止勾完成判据。
> **修订**：2026-09-02（按 00-EXECUTION-PLAN / PHASE-K 密度重写顺序说明与 SP 卡；不发明第二条主链）
>
> ⚠️ **最大误用方式**：把本文件读成「另起一套 P0 产品愿望」，然后把 PHASE-L L0a / PHASE-K K1 丢到一边。本文件排的是**已经写好但还没做完**的卡。

---

## 目录

| 章节 | 什么时候读 |
|---|---|
| [§0 怎么开发](#0-怎么开发每天必读) | **每次开工前** |
| [§1 优先级 P0](#1-优先级-p0立刻能并行) | 今天能做的 |
| [§2 优先级 P1](#2-优先级-p1宿主--goal--gui-基线--拆核) | 下一波 |
| [§3 优先级 P2](#3-优先级-p2-cu--内嵌-webview--发行版) | 别提前 |
| [§4 可并行 / 必须串行](#4-可并行与必须串行) | 排人之前 |
| [§5 下一步](#5-下一步) | **现在**打开哪张 |
| [§6 G 之后波次](#6-g-之后波次既有文档优先) | 规划 |
| [§7 PHASE-L 工作流拆分](#7-phase-l-工作流拆分) | 加团 vs 发行版 |
| [§8 维护卡 SP*](#8-维护卡-sp本目标不改-agent_v2py-循环) | 拆核准备 |
| [§9 出口](#9-本文件的出口) | 顺序文档自己完没完 |

---

## §0 怎么开发（每天，必读）

仓库根：

```
D:\agent-demo\RxyCode\RxyCode1_1_0
```

你是 Windows / PowerShell 下的编码代理。每次接到「做下一张卡」：

```
0. RESEARCH  写步骤前 / 实现前：
             本仓 rg → 注册表 → 已装 MCP/skill → GitHub → 本机闭源观察
             留下：Verdict: Adopt|Extend|Compose|Build — <仓库> — <证据>
             无 Verdict 的卡不得开工。能抄不造。search-first 找实现。

1. ORDER     打开本文件，取当前波次第一张未勾且前置满足的卡
             卡号必须带文档名：PHASE-L L0a、PHASE-P PP1、PHASE-L-TEAMS-INCREMENT WFT1
             禁止裸 L0 / M1 / P1

2. READ      只读该卡 + 所属 PHASE 的 §0（硬规则 + 决策记录）
             叠加卡还要读 PHASE-P §0 或 TEAMS-INCREMENT §0
             用 Read 打开「涉及文件」里的每一个路径，确认行号还对得上（00-EXECUTION-PLAN R1）

3. LOCATE    Grep 锚点，不要猜符号名

4. TEST-1st  契约测试先行（红）→ 实现 → 测试绿

5. VERIFY    跑该卡「验收命令」每一条，把真实输出贴出来。没跑就不许说完成（R2）

6. AUDIT     GPT-5.6 按 PHASE-FIX 附录 B 审 diff。未 PASS 不得勾完成判据

7. COMMIT    一张卡一个 commit，用卡内 Commit 模板（R9）
```

**新协议**：先 `agent-core-boundaries`（`protocol/` + `appserver/`），再 runtime 或 surface。禁止前端发明 JSON-RPC 方法名。

**为什么第 0 步在第 1 步前面**：PHASE-P **PC0**。用户原话是硬条件，不是建议。08-12 已经演示过「先写 CUA 再调研」会把测试写炸。

**为什么必须带文档名**：PHASE-K 能力层级 L0、PHASE-L L0a、优先级 P0 三个「L0/P0」会撞。测试 `test_live_order_and_intent.py` 认 `PP1` / `WFT1` 这种不带连字符的卡号。

### 0.1 每天环境自检

```powershell
cd "D:\agent-demo\RxyCode\RxyCode1_1_0"
python --version
git status --short
git branch --show-current
Test-Path docs\plans\opus5-plan\rxycode\architecture\DEV-ORDER.md
```

有未提交改动而当前卡没提到：停下来问用户，不要 `git checkout .`。

### 0.2 跨 PHASE 的四连（按卡选用）

| 名称 | 命令 | 何时 |
|---|---|---|
| **PREFIX** | `python -m pytest tests/test_cache/test_s1_s2_split.py tests/test_cache/test_stable_prefix.py -q` | 任何碰 `core/` `prompts/` `tools/` `teams/` 的卡 |
| **SPEC** | `python -m pytest tests/test_agents/test_spec.py -q` | 任何团 YAML |
| **TUI** | `cd frontend\opentui-app; npx tsc --noEmit; npx vitest run` | 任何 OpenTUI 卡 |
| **BASELINE** | `python -m evals.cli run --backend agent --compare-baseline evals\baselines\latest-agent.json` | PHASE-L 写明要跑时。**不要自己加 `--mode`**——那是 F14 的事 |

---

## §1 优先级 P0（立刻能并行）

这些工作流 **文件域不重叠**，前置已在既有文档里写明为「无」或「不是 PHASE-L 全文」。

| 工作流 | 打开哪张卡 | 文件域 | 前置 | 为什么现在就能做 |
|---|---|---|---|---|
| 绝对基线量具 | [PHASE-L L0a](../PHASE-L-TEAM-ECOSYSTEM-DISTRO.md) | `evals/` | 无。L0a 是量具本体，不依赖 F14 的 `--mode` | PHASE-L 原文：「第一天就能开工」。没有量具，后面加团/开 multiagent 都是盲飞 |
| GUI 勘误/路径 | [PHASE-M M0a / M1 / M2](../PHASE-M-GUI-BASELINE-CAPABILITY.md) | Desktop 文档 + 超时 | 无 | PHASE-M 原文。10 秒 `agent/invoke` 超时是生产伤 |
| CLI 盘点 | [PHASE-N N0 / N7](../PHASE-N-CLI-PARITY-LONGRUN.md) | OpenTUI 命令 / 设置容器 | 无 | PHASE-N 原文。N0 是盘点不是改命令行为 |
| 加内置团 YAML | [PHASE-L-TEAMS-INCREMENT WFT1](./PHASE-L-TEAMS-INCREMENT.md)（先 WFT0） | `core/agents/teams/` | `validate_team`（PHASE-F F3）、FXC3/S1；**不是** PHASE-L 全文、不是 L13/L14/L17 | 用户要加团。发行版与跨宿主是另一条工作流 |
| 占用 / 微压缩 / LLM compact | [PHASE-UPDATE-01](../PHASE-UPDATE-01.md) **U0–U19** | `core/occupancy.py` · `compaction.py` · OpenTUI `/compact` | 不挡 L0a。微压缩权威 **U3**；LLM compact **U16**（summarizer 不得**调用**工具）；请求体 tools schema **U43** | 禁止与 slash / browse / CU 焊同一行 |
| 斜杠映射 | [PHASE-UPDATE-01](../PHASE-UPDATE-01.md) **U25–U32** | `core/slash/` · `/goal` 表面 · `/loop` | `/loop` 权威 **U31**（UPDATE-02 V45 只指针）。`/goal` **对象**仍 N4–N6。U29 合入须 K9。**KC4** 从第一天生效 | 禁止第二套 CommandSpec |
| CU / snapshot MCP | [PHASE-UPDATE-01](../PHASE-UPDATE-01.md) **U20–U24** | `core/cu/` ocu · `browser_use` Playwright | U24 ≠ U20–U23 ≠ PP80。`browser_*` 撞名归 U22/U24 | 禁止写进 UPDATE-02 |
| 浏览质量（信封/路由） | [PHASE-UPDATE-01](../PHASE-UPDATE-01.md) **U33–U36** | `core/web_intent.py` · `search_envelope.py` | **不**重写 U24 工具表。成功信封=U34；失败串=FX3-12 | 与 CU / snapshot **分行** |
| Playwright 默认开 + 用户 Chrome + 升级 | [PHASE-UPDATE-01](../PHASE-UPDATE-01.md) **U46** | `core/web_escalate.py` · `chrome_attach` | Playwright/Chrome **默认开、惰性**。bundled MCP 或用户插件。Search→Fetch→PW→Chrome；**CU 可点网页但须任务信号**。调研=多次一条 query 的 websearch；25s 是单次墙 | 覆盖 U24 卡面默认关；不是「CU 永不网页」 |
| 连续性 / cache 纪律 | [PHASE-UPDATE-01 轨 G](../PHASE-UPDATE-01.md) **U37–U45** | `core/followup.py` · `prefix_hydrate.py` · `tool_visibility.py` · `compact_tools.py` | **不**重写 U3；**不**焊任务进 S1；**不**塞进 U24/U35；**不**写进 UPDATE-02 | 2026-09-14 轨 G |
| 会话列表自动持久化 | [PHASE-UPDATE-01 轨 H](../PHASE-UPDATE-01.md) **U47–U51** | `core/session_list.py` · `session_title.py` · OpenTUI `DialogSessionList` | `/session` 走 `sessions/list`，**不是** `chat_storage`。LLM 标题 + 日期分组 + `ctrl+r/d/f`。**不**新增 `session/pin`；**不**改 Ink `App.test.tsx` | 2026-09-15 轨 H |
| `/effort` 选择器 | [PHASE-UPDATE-01 轨 I](../PHASE-UPDATE-01.md) **U52–U56** | `frontend.effort-picker` · `effortPicker.ts` · composer 芯片 · `shouldOpenEffortPicker` | 标题 `Select effort`；Default 首行；换模型/addmodel 后弹；esc=default。**不**改名为 `/variant`；**不**改 `formatHeaderLine` | 2026-09-15 轨 I |
| Message Actions | [PHASE-UPDATE-01 轨 J](../PHASE-UPDATE-01.md) **U57–U62** | `messageActions.ts` · `session_revert.py` · `DialogMessageActions` | 右键=灰底；Revert/Copy/Fork。运行中 overlay **仍开**；Revert 先 `session/interrupt`。**不**用 `session/fork`；**不**改 `thread/fork` 复制范围 | 2026-09-15 轨 J |
| 会话落盘 / 调度续跑 | [PHASE-UPDATE-01 轨 K](../PHASE-UPDATE-01.md) **U63–U68** | `core/session_durability.py` · `ScheduleService.restore_after_restart` · bash 现网 default | 换模型不丢；跨 dated hydrate；`/loop` 时钟。**不**改 `tools/bash.py` Field default（今日观测 60） | 2026-09-15 轨 K |
| 磁盘工作区快照 | [PHASE-UPDATE-01 轨 K2](../PHASE-UPDATE-01.md) **U69–U72** | `workspace_snapshot.py` content-addressed blobs | 突然关机仍能 restore before；FileTracker 不得无界囤全文。**不** vendor OpenCode odb | 2026-09-15 轨 K2 |
| CLI 双开 / Transport / Skills 惰性 / Todo / Activity | [PHASE-UPDATE-02](../PHASE-UPDATE-02.md) V0–V46 + [TESTS](../PHASE-UPDATE-02-TESTS.md) | `core/transport/` · skills catalog · todo · shelf · compose workflow | 不挡 L0a。**V4/V5** 才是 CLI 双开。不改写占用/CU。V45 不施工。V39 依赖 SP0/SP1 | 测试只许抄 TESTS.md |
| 斜杠定死 skill | [PHASE-UPDATE-01 U29](../PHASE-UPDATE-01.md)（原 PHASE-P PP1；挂 K9/K10） | 命令 + S2 | K9 可并行设计；合入须发现器能解析 SKILL.md。**KC4 从第一天就生效** | 施工走 Update 01 轨 E，不另写第二套 parse_slash |
| 测试迁到 Session 假面 | [SP0](#sp0--测试迁到-session-假面)（本文件） | `tests/` 直绑 AgentV2 | 无产品循环改写 | 不迁测试就无法拆 6851 行的 `agent_v2.py` |
| 本治理 | architecture 文档 | `docs/plans/opus5-plan/rxycode/architecture/` | — | 正在做；不挡上面任何一张 |

P0 **不是**「把备忘 14 条愿望全做了」。CU / 加号宿主 / 发行版都不在本表。

---

## §2 优先级 P1（宿主 / goal / GUI 基线 / 拆核）

| 工作流 | 打开 | 备注 |
|---|---|---|
| 插件宿主与前缀 | PHASE-K K1→K2→K9/K10→K12/K18/K19→K14 | 加号 UI（PP50）**不得**排到 K 宿主之前当第二 invoke。PP1 可与 K9 并行设计 |
| `/goal` 对象 | PHASE-N N4–N6 | 备忘对象层就是这三张。PP60 是挂接，不另做存储。关窗口后续跑对照：[`research/2026-09-15-session-durability-snapshots-loop-timeout.md`](../research/2026-09-15-session-durability-snapshots-loop-timeout.md) |
| goal UX + Grok SOP | PHASE-P PP61 / PP62 | 叠加；依赖 N4–N6 与 PP70 |
| Plan 一等对象 | PHASE-P PP70 | 接已有 `appserver/plan_files.py` |
| GUI 基线补差 | PHASE-M M3–M8 | M5–M11 等 GX24/26/28 |
| 拆核 SP1–SP3 | 本文件 §8 | 本目标只写卡不执行拆代码 |
| 沙箱/补丁/hooks 双表面 | PHASE-P PP10–PP31 | 能抄则 Extend OSS。hooks 实现跟 K14 |
| 加号第一屏 | PHASE-P PP50 | 依赖 `plugin/list` |
| 子代理点进 | PHASE-P PP100 | 只补表面；不翻转 multiagent 默认 |

---

## §3 优先级 P2（CU / 内嵌 WebView / 发行版）

| 工作流 | 打开 |
|---|---|
| Computer Use MCP 接入 | PHASE-P PP40–PP42 **与** UPDATE-01 **U20–U23**。优先 iFurySt/open-codex-computer-use。`cli_list`/`cli_run` 并存不得替代。**不是** browser 卡 |
| Browser snapshot MCP | PHASE-UPDATE-01 **U24**（Playwright `browser_snapshot`+ref，能力键 `browser_use`）。**不是** PP80，**不是** ocu |
| Search/Fetch/Browse 路由 | PHASE-UPDATE-01 **U33–U36**（信封 + 意图 + OpenTUI `fetch:`≠`browse:`）。**不**重写 U24 工具表 |
| Playwright 默认开 + Chrome 附着 + 升级 | PHASE-UPDATE-01 **U46**（`escalate_web` / `chrome_attach`；CU 任务限定可点浏览器窗口）。bundled MCP 或用户插件 |
| 连续性 + cache 纪律 | PHASE-UPDATE-01 **U37–U45**（「？」禁应用答案缓存、中断记前缀、hydrate、闲 MCP、tools digest、子代理摘要）。**不**重写 U3。**不是** compact / CU / slash / browse |
| 会话列表自动持久化 | PHASE-UPDATE-01 **U47–U51**（`sessions/list` 目录、LLM 标题、日期分组、列表快捷键）。**不是** `chat_storage` / `/save-chat`。**不是**轨 G cache/session |
| `/effort` 选择器 | PHASE-UPDATE-01 **U52–U56**（Select effort、composer 芯片、model/addmodel 链）。**不是** `/variant`。**不是**改厂商 `effort_options` |
| Message Actions | PHASE-UPDATE-01 **U57–U62**（右键灰底、Revert/Copy/Fork；busy overlay 仍开；Revert interrupt-then-revert）。**不是** `session/fork`。**不是**改 `thread/fork` |
| 会话落盘 / 调度续跑 | PHASE-UPDATE-01 **U63–U68**（A transcript ≠ D catalog；换模型不丢；隔夜 hydrate；`/loop` 时钟）。bash default = 现网源码，禁止改。**不是** Cursor vscdb。**不是**重写 U31 / PHASE-N Goal |
| 磁盘工作区快照 | PHASE-UPDATE-01 **U69–U72**（崩溃 Undo 在磁盘 blobs；FileTracker 不得无界囤全文）。**不是** RAM git。**不是** vendor OpenCode odb |
| 内嵌浏览器 / GUI 终端 / 侧边聊天 | PP80 / PP81 / PP90。PP80 = GitHub WebView，**不是** U24/U33 |
| L13/L14 发行版、L17 跨宿主 | PHASE-L 原卡。**不挡 WFT1** |
| H → I 主链 | PHASE-H / PHASE-I |
| O Muse Spark | 仅 MS0 审计过才开 MS1 |

---

## §4 可并行与必须串行

### 可并行（文件域不重叠）

- PHASE-L **L0a**（`evals/`）∥ WFT1（`core/agents/teams/`）∥ PHASE-N **N0**（命令文档）∥ PHASE-M **M0a**
- PHASE-UPDATE-01 **轨 B 型号**（`core/providers/`）∥ **轨 C** U14–U18（`compaction.py` / prompts / `/compact`）；轨 A U1–U3 不要和 U16 抢同一函数同一 commit
- PHASE-UPDATE-01 **U29**（斜杠 skill，原 PP1）∥ L0a ∥ WFT0/WFT1 ∥ SP0（`tests/` 迁徙，不改循环）
- PHASE-UPDATE-01 **轨 F U33–U36** ∥ 轨 E U25–U32（文件域：`web_intent`/`websearch` vs `core/slash/`）；**禁止**改 U24 卡体
- PHASE-UPDATE-01 **U46** 接 U35+U24 工具表 + U42 惰性；文件域 `web_escalate.py` / `chrome_*`；**禁止**改 U24 三名、**禁止**无信号把 CU 当 Search/Fetch 退路
- PHASE-UPDATE-01 **轨 G U37–U45** ∥ 轨 E/F（文件域：`followup`/`prefix_hydrate`/`tool_visibility` vs slash / browse）；**禁止**改 U3/U24/U35 卡体；**禁止**与 compact 梯子抢同一 commit
- PHASE-UPDATE-01 **轨 H U47–U51** ∥ 轨 E/F/G（文件域：`session_list.py` / `session_title.py` / `DialogSessionList.tsx` vs followup / browse / slash）；**禁止**改 `chat_storage.py`、Ink `App.test.tsx`、U36/U38 测试文件；**禁止**新增 `session/pin`
- PHASE-UPDATE-01 **轨 I U52–U56** ∥ 轨 H（文件域：`effortPicker.ts` / composer 芯片 vs session list）；**禁止**改 `formatHeaderLine`、`test_effort_presets.py`、`parse_slash`
- PHASE-UPDATE-01 **轨 J U57–U62** ∥ 轨 I（文件域：`messageActions.ts` / `session_revert.py` vs effort picker）；**禁止**改 `thread/fork` 复制范围、`DialogSelect` 导航、`session/fork`；**禁止** busy 堵 overlay；**禁止** Revert 只填 composer（#14014）
- PHASE-UPDATE-01 **轨 K U63–U68** ∥ 轨 J/H（文件域：`session_durability.py` / `schedule_service.py` vs message-actions / session list）；**禁止**改 U31 `parse_loop_args`、PHASE-N Goal store、`tools/bash.py` Field default、`chat_storage.py`
- PHASE-UPDATE-01 **轨 K2 U69–U72** ∥ 轨 K（文件域：`workspace_snapshot.py` vs schedule）；**禁止**把 FileTracker 改成崩溃权威；**禁止** vendor OpenCode odb
- isolation（PP10，`core/safety/`）∥ tools.edit（PP20，`tools/edit.py`）∥ hooks（K14，插件桥）——三缝 ARCH-002 已钉死互不顺手改
- 协议合入后：同一能力 CLI ∥ GUI（仍须同一 commit 或紧邻两 commit 都绿才能勾 PC1）
- search-first 调研与读卡可并行，**写步骤前 Verdict 必须已在卡里**

### 必须串行（现有文档已写死）

- 新 JSON-RPC → `protocol/` → `appserver/` → 表面（ARCH-001 / GP8）
- 进前缀 → PHASE-FIX identity（KC1–KC5）。任何 L1 能力开关在 K2 之前禁止合入
- PHASE-N N9/N10 → PHASE-K K2+K6+K20（N 卡自己写的依赖，本文件不放宽）
- PHASE-L L12 进索引 → L0a+L0b+F14（进索引不是加 YAML）
- `/goal` SOP（PP62）→ PHASE-N N4–N6 先存在
- Computer Use → 访问档（PP11）；与 `cli_list`/`cli_run` 并存不得替代
- 拆 `agent_v2` → **SP0 测试假面先迁**（ARCH-004）
- 加号第一屏（PP50）→ `plugin/list` 宿主可用（K 宿主 / GX24）
- 网装 hooks 对用户开放 → K19 然后 K14 然后 PP31

---

## §5 下一步

开工 **PHASE-L-TEAMS-INCREMENT** 的 **WFT1**（第二支内置团 YAML）。

前置是：

- `validate_team`（PHASE-F F3，`core/agents/spec.py:49`）
- FXC3 / S1（`tests/test_cache/test_s1_s2_split.py`）
- 本叠加包的 **WFT0**（盘点工具名，防止再写错 F11 那种不存在的工具）

前置 **不是** PHASE-L 整份文档，**不是** L13/L14 发行版，**不是** L17 跨宿主，**不是** L0b / L12。

可与 **PHASE-L L0a**、**PHASE-N N0**、**PHASE-M M0a**、**PHASE-UPDATE-01 U29**（原 PP1）、**SP0** 并行。

实现任何一张卡前先做调研（search-first），卡内必须有 `Verdict:`。

---

## §6 G 之后波次（既有文档优先）

字母 Phase 主链在 G 之后本来就是 K→L→M→N→H→I→O。本表 **不发明** 一条跟它们平级的「产品愿望链」。PHASE-P 的卡插进对应波次。

**波次 0** 本目标：调研报告 → 本文件 → 模块合同 → PHASE-P / TEAMS-INCREMENT → 门禁测试。**不改产品循环代码。**

**波次 1** 现有「可立即开工」（P0）：PHASE-L L0a ∥ PHASE-M M0a/M1/M2 ∥ PHASE-N N0/N7 ∥ WFT0→WFT1 ∥ PHASE-UPDATE-01 **U25–U32**（slash；`/loop`=U31，不要开 V45）∥ **轨 F U33–U36**（不重写 U24；失败串让 FX3-12）∥ **U46**（Playwright/Chrome 默认开 + 升级梯子）∥ **轨 G U37–U45**（「？」；不写进 UPDATE-02）∥ **轨 H U47–U51**（会话列表；不接 chat_storage）∥ **轨 I U52–U56**（`/effort` Select effort；不改名为 `/variant`）∥ **轨 J U57–U62**（Message Actions；不用 session/fork）∥ **轨 K U63–U68**（落盘/调度；不改 bash Field default）∥ **轨 K2 U69–U72**（磁盘快照；不把 Undo 只放 RAM）∥ UPDATE-02 **V4/V5**（CLI 双开）∥ SP0。禁止同一行焊两套 slash / loop / Goal store。

**波次 2** PHASE-K 宿主：K1–K2 → K9/K10（+U29 合入）→ K12/K18/K19 → K14（+PP30/PP31）→ GX24（+PP50 加号 IA）。加号第一屏已装插件，不是 skill/MCP。

**波次 3** PHASE-N：N4–N6（+PP60）→ PP61/PP62 → N1–N3 → N9/N10（等 K）。PP70 可与 N4 后并行。

**波次 4** PHASE-M 其余（M3–M8；M5–M11 等 GX）。

**波次 5** PHASE-L 其余（L0b 等 F14；L2–L12；**L13/L14/L17 不挡 WFT1**，它们在本波次后段或与发行无关的并行轨）。

**波次 6** PHASE-H → PHASE-I。

**波次 7** CU（PP40–PP42 / UPDATE-01 U20–U23，open-codex-computer-use）/ **内嵌** WebView PP80 / 终端 PP81 / 侧边聊天 PP90。U24 snapshot MCP、U33–U36 浏览质量、**U46 Chrome 附着**在 UPDATE-01，**不要**排进本波次当同一张卡。

**波次 8** PHASE-O（MS0 过才开 MS1）。

---

## §7 PHASE-L 工作流拆分

PHASE-L 一份文档里捆了五件独立的事。把它们绑成「必须先做完 L13/L14/L17 才许加 YAML」会让加团永远开不了工。

| 工作流 | 卡 | 现在？ | 为什么能/不能 |
|---|---|---|---|
| 量具 | PHASE-L L0a | **能** | 无前置。缺的是把 `Session` 已有信号接进评测门 |
| 团模式接线 | PHASE-L L0b | 等 F14/F17 | `--mode team` 还不存在，不要自己加 flag |
| **加内置团 YAML** | **WFT1** | **能**（前置≠PHASE-L 全文） | 样例 `software_dev` 已在；`validate_team` 已在 |
| 进自动索引 | PHASE-L L12 | 等 L0a+L0b+F14 | LC2：发货 ≠ 进索引。WFT1 必须 `disable_model_invocation: true` |
| Team Pack / 跨宿主 | L4 / L17 | 与加团解耦 | 用户要加团，不是要今天发 rxycode-teams 仓 |
| 发行版 | L13 / L14 | 不挡加团 | 极简发行版是 K20 的外壳 |

---

## §8 维护卡 SP*（本目标不改 `agent_v2.py` 循环）

`core/agent_v2.py` 2026-09-02 实测 **6851** 行。测试大量 `from RxyCode.RxyCode1_1_0.core.agent_v2 import AgentV2`（例如 `tests/test_cache/test_stable_prefix.py`、`tests/test_agents/test_isolation.py`）。ARCH-004：必须按缝拆；方法是已有 `Session` 假面（`core/session.py:144`）；**本目标 diff 不含循环改写**。

调研：`Verdict: Adopt — openai/codex session/ 目录边界`（见 `research/2026-09-01-top-coding-agents-core-architecture.md`）。Cline Task ~3756 行是债，不是样板。

---

### SP0 · 测试迁到 Session 假面

`P0` / 2–3d / 依赖无 / **owner: backend** / **本卡禁止修改 `core/agent_v2.py` 循环**

**背景**

测试直绑 `AgentV2` 使拆核不可能：一抽 harness，所有 `AgentV2(` 构造与私有方法断言一起红。Codex 能拆 15 万行是因为测试打在 session/tools 边界上，不是打在一个上帝文件的私有函数上。

**调研与 Verdict**

`Verdict: Extend — core/session.py 已有假面 — as-is 审计 §5；高星对照 Codex session/ crate。`

**涉及文件**

| 路径 | 锚点 | 本卡怎么动 |
|---|---|---|
| `core/session.py:144` | `class Session` / `async def prompt` | **只读**理解假面；本卡不改 prompt 语义 |
| `tests/test_cache/test_stable_prefix.py` 等 | `from ...agent_v2 import AgentV2` | 新测试走 Session；旧测试分批迁，本卡至少迁 **一条证明路径** + 加禁令 |
| `tests/helpers/session_facade.py`（新增） | — | 测试用 Session 装配，不 new AgentV2 私有状态 |
| `tests/test_docs/` | — | 不在本卡范围 |
| `core/agent_v2.py` | 6851 行 | **diff 必须空**（循环与分支） |

**操作步骤**

1. 盘点：Grep `from RxyCode.RxyCode1_1_0.core.agent_v2 import` 与 `from core.agent_v2 import`，列出文件清单贴进本卡 PR（清单会变，以 Grep 为准）。
2. 新建测试装配：只通过 `Session(session_id=..., workspace_root=..., emit=...)` + 公开 `prompt()`。
3. 选一个不依赖私有 `_` 的测试文件先迁（优先 `tests/test_agents/` 里只关心行为不关心内部字段的）。
4. 加 lint/测试门：`tests/` **新增**文件禁止 `from ...agent_v2 import AgentV2`（允许 `TYPE_CHECKING` 或明确白名单旧文件）。本卡不要求一次迁完所有旧文件。
5. PREFIX：本卡不碰 prompts，仍跑一次证明没误改 core。

**验收命令**

```powershell
python -m pytest tests/helpers tests/test_cache/test_s1_s2_split.py -q --timeout=120
git diff --stat core/agent_v2.py
# 期望空
```

**完成判据**

- [ ] 新测试走 Session 假面，有至少一例
- [ ] 新增测试文件禁止直绑 AgentV2，有门禁
- [ ] `git diff core/agent_v2.py` 为空
- [ ] 未改 plugin_service、safety 执法、CU、frontend
- [ ] GPT-5.6 审计 PASS

**回滚**：revert 本卡。旧测试未删则回滚面小。

**常见坑**：顺手「清理」`agent_v2` 私有函数；把装配写成第二套 loop。

**Commit**：`test(session): SP0 migrate tests to Session facade`

---

### SP1 · 抽出 harness 调用

`P1` / 依赖 SP0 / **owner: backend** / **本目标不执行**

**背景**

把 turn_router / prefix_profile / prewarm / catalog 的调用从 `agent_v2.py` 搬到可单测的 harness 缝。ARCH-002 允许改这些文件；禁止顺手改 `plugin_service`、safety 执法、CU、frontend。

**调研与 Verdict**

`Verdict: Adopt — openai/codex session/ 目录边界`

**涉及文件**（执行日 Grep）：`core/turn_router.py`、`core/prefix_profile.py`、`core/prewarm.py`、`core/catalog.py`、`core/prompts/`、`tests/test_cache/`。

**规范限制**

- 禁止顺手改：`core/safety/*`、`appserver/plugin_service.py`、`tools/edit.py`、`core/agents/teams/`、`frontend/*`、CU 模块、`agent_v2.py` 无关分支。
- 每步 ADR + 测试（ARCH-004）。

**操作步骤**（执行日才写细，本目标只锁边界）

1. SP0 门禁绿。
2. 抽出一个调用点，测试只打新模块。
3. `agent_v2` 变为委托。禁止一次搬完 6851 行。

**验收命令**：该步新增测试 + PREFIX + IDENTITY（若碰前缀）。

**完成判据**

- [ ] 新模块可独立 import
- [ ] 禁止清单里的路径 diff 为空
- [ ] GPT-5.6 审计 PASS

**回滚**：单步 revert。

**常见坑**：一次 PR 拆三个缝。

**Commit**：`refactor(harness): SP1 extract turn/prefix calls`

---

### SP2 · 工具只经 ToolOrchestrator

`P1` / 依赖 SP0 / **owner: backend** / **本目标不执行**

**背景**

CU、hooks、edit、bash 若在 `agent_v2` 里直接执行，隔离与补丁缝永远插不进去。工具必须只经 `execution/tool_orchestrator.py`。

**调研与 Verdict**

`Verdict: Extend — 本仓 ToolOrchestrator + Codex tools 目录。`

**涉及文件**：`execution/tool_orchestrator.py`；禁止在 `agent_v2` 新增 `edit_file(` / MCP 调用。

**完成判据**

- [ ] 新工具路径不经过 agent_v2 私有分支
- [ ] CU 仍不进 agent_v2（PP40）
- [ ] GPT-5.6 审计 PASS

**验收命令**：orchestrator 测试 + Grep 负向。

**回滚**：revert 本卡。

**常见坑**：为「快」在 loop 里直接 `subprocess`。

**Commit**：`refactor(tools): SP2 orchestrator only`

---

### SP3 · 团逻辑不在 agent_v2 新增长分支

`P1` / 依赖 SP0 / **owner: backend** / **本目标不执行**

**背景**

团走 `core/agents/`（coordinator / sop / registry）。`agent_v2` 再长 `if team:` 会把 F 与拆核对打。

**调研与 Verdict**

`Verdict: Extend — 本仓 core/agents/ + PHASE-F。`

**涉及文件**：`core/agents/`；`core/session.py` 已有 `agent_runtimes` 注释（L159–162）指向 Phase F。本卡禁止在 agent_v2 新增团分支。

**完成判据**

- [ ] 新团行为在 `core/agents/`
- [ ] agent_v2 无新增团长分支
- [ ] GPT-5.6 审计 PASS

**验收命令**：`tests/test_agents/` + PREFIX。

**回滚**：revert 本卡。

**常见坑**：把 WFT1 YAML 解析写进 agent_v2。

**Commit**：`refactor(agents): SP3 keep teams out of agent_v2`

---

## §9 本文件的出口

- [ ] P0/P1/P2 三张表都指向**既有** PHASE 卡或本文件 SP*/WFT*/PP*
- [ ] 「下一步」指向 WFT1，且不把 PHASE-L 整份文档写成前置
- [ ] 可并行 / 必须串行写清文件域
- [ ] SP0 有涉及文件、步骤、验收、可勾判据，且禁止改 agent_v2 循环
- [ ] 未发明第二条主链（没有「Phase P 做完再做 K」）
