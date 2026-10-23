# RxyCode 产品意图备忘

> **性质**：产品老板口述的「我想做什么」。给产品和架构师后续写成开发文档用。  
> **不是**：施工卡、任务拆分、接口设计、工期、验收命令。  
> **整理日期**：2026-09-01  
> **口述来源**：与研发助手的连续讨论 + Codex Desktop 三张加号菜单截图。  
> **对现有计划的态度**：仓库里已有 PHASE-K / N / G 等施工文档。本文件**不改那些文档**，只陈述愿望。两边打架的地方单独标「冲突」，由产品和架构师拍板。

---

## 1. 一句话

RxyCode 要同时做成：

1. **能装、能开、能看见的插件工作台**（加号里是已下载的插件，不是 skill / MCP 列表）。
2. **能直接操作电脑、能看见事实的 Computer Use**（抄 Codex 那种控制电脑 + 观察屏幕/标签，不只是聊天）。
3. **带沙箱、结构化改文件、hooks 扩展的 harness**（眼馋 Codex 的执行外壳）。
4. **同一套能力，CLI 和 GUI 都要有**。GUI 抄 Codex 工作台；CLI 抄 OpenCode / Grok Build 的呈现。

不要做成「GUI 有、终端没有」或「终端有、窗口里看不见」。

---

## 2. 总原则（写开发文档时不许丢掉）

| # | 原则 | 含义 |
|---|---|---|
| P1 | **CLI / GUI 能力对等** | 下面每一条功能，CLI 要能用命令或 TUI 做完，GUI 要能点完。允许呈现不同，不允许能力缺失。 |
| P2 | **插件 ≠ skill ≠ MCP** | 加号菜单、插件管理里出现的是**已经下载的插件**（可执行扩展 / 应用）。Skill 和 MCP 是另一条安装与调用通道，不能冒充这个加号。 |
| P3 | **显式调用要定死** | 用户写下 `/using-superpowers` 或等价斜杠，就必须走那条 skill / SOP，不能靠模型「想起了再读」。CLI 和 GUI 同一套斜杠。 |
| P4 | **先看见再合并** | 改文件要出红删绿增；子代理 / 多代理跑起来要能点进去看。看不见就不算做完。 |
| P5 | **抄交互，不抄内核** | Codex / OpenCode / Grok Build / Cursor 是交互与 SOP 的参照。不要把别人的循环整仓嵌进来换掉现有 harness。 |
| P6 | **先搜再造** | 产品和研发动手前，必须先在 GitHub、包注册表、本机已装产品里找前人。见第 10 节。 |

---

## 3. Harness：眼馋 Codex、我要做的三件硬能力

这三件和「插件市场」是分开的。没有这三件，加号菜单只是皮肤。

### 3.1 沙箱

- 要做**真执行隔离**，不是只靠写路径白名单和点一下批准。
- 参照 Codex：用户点了允许之后，系统调用仍可能被裁掉。
- CLI 和 GUI 都要能看到当前是什么访问档（截图里 Codex 输入框旁的「完全访问」就是这种呈现）。档位名称可以另定，语义要对用户可读。

### 3.2 改文件

- 主变异原语要向 Codex 的结构化补丁看齐（可审、可回放），不要只停留在「找一段字符串替换一段字符串」。
- **CLI**：改过的代码直接呈现在对话流里。删除用红色框选，添加用绿色。这就是 CLI 侧的审计。参照 OpenCode、Grok Build。
- **GUI**：同样要有可点的完成物与 diff（截图里 Codex 的「已完成」文件链接是最低限度；完整形态还要能展开红绿 diff）。

### 3.3 Hooks 扩展

- 要能把脚本挂进循环（会话开始、用户提交、工具前/后等），用来扫密钥、跑校验、记日志、按仓库定制行为。
- 参照 Codex 的 `hooks.json` + 信任审阅：装了不等于自动信。
- 从网上装来的 hooks 必须默认关，用户显式打开。
- CLI 要有 `/hooks` 一类入口；GUI 要有对应设置/面板。

---

## 4. Computer Use（明确要做，而且要 Codex 那种）

**愿望：直接控制电脑，并且是事实观察，不是模型瞎猜屏幕上有什么。**

截图里已经能看到这种产品形态的入口：

- 加号插件列表里有 **「浏览器 / 控制应用内浏览器」**。
- 加号另一页有 **「标签页」**：当前 Edge 里打开的页面（比赛报名页、GitHub README、grok.com Cloud Sandbox）可以直接被点进上下文。
- 状态上有「完全访问」。

我要的是这一套，不是「只会 bash 的假 Computer Use」：

| 要 | 不要理解成 |
|---|---|
| 能看当前屏幕 / 窗口 / 浏览器标签的**事实** | 只根据聊天记录猜用户在看什么 |
| 能在授权范围内点、键、滚、切窗口 | 只生成一段「请用户自己去点」的说明 |
| CLI 也能开/关、看状态、对当前页做动作（命令或 TUI） | 只有 GUI 里一个玩具浏览器 |
| 作为可开关的能力（设置 + 命令两条路径） | 偷偷常开、没有档位 |

**给架构师的冲突提示（必须写进后续开发文档的决策节）：**

仓库调研 `docs/plans/opus5-plan/rxycode/research/2026-08-12-agent-native-computer-use-research.md` 曾经冻结「像素点击 Computer Use」，改走 CLI-Anything 软联系。  
**本备忘以产品老板本次口述为准：Codex 那种直接控制电脑 + 事实观察，我要做。**  
软联系（`cli_list` / `cli_run`）可以并存，不能用来替代这条愿望。怎么控 token、怎么过安全门，由产品和架构师另写方案，不要在本文件里自行改口。

---

## 5. 插件（加号菜单）——看图就能对上的那一层

### 5.1 加号里是什么

点击输入框左侧 **「+」**，弹出层里应能看到：

1. **已经下载过的插件**，带图标和一句说明，点一下就能用。  
   截图实例（Codex，只作信息架构参照，不要求同名同图标）：
   - GitHub（PR / Issue / CI / 发布）
   - Superpowers（计划、开发、调试）
   - Documents / PDF / Spreadsheets / Presentations
   - Template Creator
   - Sites（建站与部署）
   - 浏览器（控制应用内浏览器）
   - Visualize
   - 插件管理（发现与管理插件）
2. **应用**（带 `@` 的那种入口，例如安全设置）。这是插件的近亲，不是 skill 列表。
3. **曾经打开过的网页 / 当前浏览器标签**（截图第三张：Edge 标签可被搜、可被点进上下文）。
4. **历史对话**（截图里叫 ChatGPT 对话；我们自己的产品里就是本机/账号下的旧会话）。
5. **底部搜索框**：输入即搜文件或会话。

### 5.2 硬约束

- **不是 skill，不是 MCP。** Skill / MCP 可以另外有 `/skill`、`/mcp`、设置页。加号第一屏不要变成「全世界 skill 目录」。
- 没下载过的插件可以出现在「插件管理 / 发现」里，不要和已安装插件混成一堆无法区分的列表。
- CLI 对等：`/plugin` 列出已安装、启用某一个、搜标签页/历史会话的等价命令。不能只有 GUI 能把「当前打开的 GitHub 页」塞进上下文。

### 5.3 安装从哪来

讨论里已定方向（供架构师对照 PHASE-K，仍以本愿望为准）：

- 不自建托管插件 CDN。
- 从 GitHub pin 下载 + 本机 on/off。
- Computer Use、Copilot 私有面、各家宿主 hook **不能**指望 clone 一个仓就跑起来；要么当一等能力做，要么整进程托管对方 agent。

---

## 6. `/goal` 目标模式 + Plan 模式

### 6.1 `/goal` = 目标模式

- CLI：`/goal`（无参开设置/对话框，有参直设，可清除）。侧边历史里目标会话要能看出来（截图侧栏有 `/goal 第一个文件…` 这种条目）。
- GUI：同一能力叫 **「目标模式」**，不是在输入框前面偷偷拼一行「持续目标：…」。
- **交互抄 Codex 的目标模式**（侧栏可见、可暂停/恢复、长任务耗时可见、完成后给文件链接）。
- 这是能跑很久的目标，不是一轮聊天的标题。

### 6.2 Plan 模式

- **也抄 Codex 的 Plan 模式**（先出计划、只读探索、用户确认后再动手）。
- CLI 和 GUI 都要能进/出 Plan。输入框附近要有模式切换，不能只靠口头「先别写代码」。
- 计划是一等对象：能打开、能改、能批准、能一键开始构建。

### 6.3 `/goal` 打开之后的 SOP：抄 Grok Build

目标模式一旦启用，后面怎么拆步、怎么建、怎么并行，**采用 Grok Build 的 SOP**，不要另发明一套「目标流水线」。

公开可对照的 Grok Build 骨架（架构师写开发文档时以 Grok Build 本机/官方文档为准，这里只钉愿望）：

1. **Plan**：先出可审计划，未批准前不改项目文件。
2. **Search**：在仓库里找齐现有模式再动手。
3. **Build**：按计划改；大任务可分子代理并行。
4. 计划文件与执行门分离；Plan 期间除计划文件外的写入应被拒绝。

`/goal` 解决「要达成什么、怎么持久」；Grok Build SOP 解决「达成过程按哪张节拍器走」。

**给架构师的对照：** PHASE-N 已把现在的 Desktop `/goal` 定性为「localStorage 字符串前缀，后端不知道」。后续开发文档应把本愿望接在「服务端持久目标」上，并补上 Codex 交互 + Grok Build SOP，而不是继续拼 prompt 前缀。

---

## 7. 显式 Skill 调用（定死）

Cursor 里可以 `/using-superpowers`，把一条 skill **强制**拉进本轮。

我要在自己的 agent 里也能这样：

- 用户输入 `/using-superpowers`、`/search-first` 或任意已安装 skill 的斜杠名。
- **定死调用**：本轮必须按该 skill 的 SOP 执行，不是「模型如果想起来就读一下」。
- **CLI 和 GUI 都能打这行命令**。GUI 也可以从加号/命令面板点同一个入口，效果与打斜杠相同。
- Skill 正文仍按渐进披露加载；斜杠只解决「必须用哪一条」，不把全部 skill 正文塞进默认前缀。

本机已有参照：`C:\Users\Administrator\.agents\skills\superpowers\skills\using-superpowers\SKILL.md`。那条 skill 管的是「先找 skill 再动手」。第 10 节要另找的是「先搜 GitHub / 本机前人再造轮子」。两条都要能被斜杠定死。

---

## 8. GUI 工作台（抄 Codex 壳 + Cursor 的可观察性）

这些都要，而且是 **GUI 上要看见的**：

| 愿望 | 参照 | 备注 |
|---|---|---|
| 侧边栏：搜索、新对话、按项目/文件夹分组的会话、最近 | Codex 截图 | 目标会话（`/goal …`）在列表里可辨认 |
| 加号菜单（第 5 节） | Codex 截图三张 | 已装插件 / 标签页 / 旧对话 / 搜文件 |
| 内嵌 GitHub 浏览器 | Codex 浏览器插件 + 标签页里的 GitHub | 内嵌即可；不要做成「请到外部浏览器打开」就结束 |
| 终端 | Codex / Cursor | **内嵌或外链都可以，但必须有**。Agent 跑的命令要能看见、能点进去、能接管 |
| 审计 | Codex 完成物 + 耗时；Cursor / OpenCode 的 diff | 谁改了什么、批没批、跑了多久、产出哪些文件 |
| 侧边聊天 | Cursor Side Chat | 主任务不中断的旁路问询 |
| 子代理 / 多代理活动 | Cursor Agent Windows | 见第 9 节 |
| 访问档 + 模型选择 | Codex「完全访问」+ 模型下拉 | 与沙箱档位是同一件事的两面 |
| 分享 / 分栏布局 | Codex 顶栏 | 分栏用来同时开聊天 + 浏览器/终端/diff |

「等等」按产品常识补齐工作台，但**不要用「等等」当借口做成另一套 IDE**。先把上表做齐。

---

## 9. 子代理 / 多代理：必须能点进去看

现状：我还没在自己的产品里看到过「子代理 / 多代理正在跑」的合格呈现。

**愿望：**

- Agent 一旦派出 subagent，或进入 multiagent，**CLI 和 GUI 都要能看见列表**：谁在跑、状态、耗时。
- **可以点进去**看那一路具体在干什么（对话、工具、diff），类似：
  - OpenCode：子代理在 TUI 里可展开；
  - Cursor Agent Windows：独立窗口/面板，能进到某一个 agent。
- 没点进去时，主会话只显示摘要（在跑 / 完成 / 失败），不要把所有子对话刷在主泡泡里。
- 这是**可观察性**，不是现在就要求把 multiagent 产品开关默认打开。看不见，等于没做。

---

## 10. 给后续开发文档的边界（本文件故意不写）

产品和架构师写开发文档时自己补，本备忘不代写：

- 任务卡、依赖、工期、默认开还是关。
- 和 PHASE-FIX 前缀冻结、97% 缓存地板怎么共存（尤其是加插件、开 Computer Use、切 Plan）。
- Computer Use 的 token 账和安全门具体方案。
- 插件信任门、hooks 供应链。
- 内嵌浏览器是 Chromium 控件还是系统 WebView，终端是 PTY 内嵌还是外开。

本文件只锁定：**我想要，而且 CLI/GUI 都要。**

---

## 11. 先搜再造：GitHub 上已经有的 skill（含 SOP）

口述要求：找一套 skill（内涵 SOP），让以后想做功能时，不必每次口头嘱咐「不要自己造轮子，先去 GitHub / 公网 / 本机找前人」。

### 11.1 结论

**没有一条开源 skill 同时完美覆盖「GitHub 开源 + 本机闭源产品抄作业」。**  
最接近、建议直接装来用（可用 `/search-first` 定死调用）的是下面几条。本机闭源（Codex Desktop、Cursor、本机已装但不开源）要在我们自己的 skill 里加一节，见 11.3。

### 11.2 公开仓库（按贴合度）

| 仓库 | 是什么 | SOP 骨架 | 缺口 |
|---|---|---|---|
| [shimo4228/search-first](https://github.com/shimo4228/search-first) 及镜像 [cloud99277/ai-skills-hub `search-first`](https://github.com/cloud99277/ai-skills-hub/blob/main/search-first/SKILL.md) | Agent Skills 标准的「写代码前先搜」 | 先用一句话说清需求 → 本仓 `rg` → npm/PyPI → 已装 MCP/skill → GitHub → 必须留下 `Verdict: Adopt / Extend / Compose / Build` | 不管本机闭源 GUI；偏库和工具，不偏「抄 Codex 加号」 |
| [niveku/skill-research-first](https://github.com/niveku/skill-research-first) | 研究优先插件，声明兼容 Claude / Codex / Gemini / Cursor | 先读本仓上下文 → OSS / awesome 列表 / 注册表 / 论坛；`references/` 按域拆 | 判决格式不如 search-first 硬；同样几乎不管本机闭源 App |
| [rakuteneng/nothing-new-under-the-sun](https://github.com/rakuteneng/nothing-new-under-the-sun) | 六段侦察：本仓 → 已有依赖 → 注册表 → GitHub → API/SaaS → 模板 | 六种结局：REUSE / USE / FORK / BUY / INTEGRATE / BUILD，带证据矩阵 | 偏买与集成；抄交互、抄闭源壳不是它的主场 |
| [merceralex397-collab/skilllibrary `github-prior-art-research`](https://github.com/merceralex397-collab/skilllibrary/blob/main/06-agent-role-candidates/github-prior-art-research/SKILL.md) | 专门搜 GitHub 前人实现 | 候选人 + 许可 + Adopt/Adapt/Skip | 只覆盖 GitHub |
| [bendrucker/claude `research:prior-art`](https://github.com/bendrucker/claude/blob/main/plugins/research/skills/prior-art/SKILL.md) | 问题空间扫盘 | 并行搜 → 读 README → 再下钻代码 | `disable-model-invocation: true`，要人手动喊，**不能当默认定死调用** |
| 本机已有 [obra/superpowers `using-superpowers`](https://github.com/obra/superpowers) | 先找 **skill** 再动手 | 技能优先于探索 | **不管**「GitHub 有没有现成实现」。和本需求互补，不能替代 |

**推荐用法（给架构师）：**

1. 把 `search-first`（或 `skill-research-first`）装进 RxyCode 的 skill 目录，斜杠 **`/search-first` 定死调用**（第 7 节）。
2. 不要和 `using-superpowers` 合成一条：一个找 skill，一个找实现。
3. 本机闭源抄作业用 11.3，作为 `search-first` 的补丁节，或单独 `/copy-local-surface`。

### 11.3 公开 skill 都缺的一节：本机闭源产品

Codex Desktop、Cursor、本机已装的 Grok Build / OpenCode，经常是**闭源或只开一部分**。没有一条成熟 skill 写清「本机先观察再抄」。

后续写我们自己的 SOP 时，建议补这几步（仍不是开发文档，只是意图）：

1. 列出本机参照：已装路径、帮助文档、用户截图、本仓库 `docs/plans/**/research/`。
2. **只抄可观察的交互与信息架构**（菜单层级、状态文案、diff 颜色、侧栏分组）。禁止把逆向、破解、绕过许可写成 skill。
3. 再搜 GitHub / 公网：有没有开源复刻（例如 OpenCode 对标 Claude Code 的 TUI diff）。
4. 判决必须多一个出处：`Verdict: … — 本机闭源观察：Codex Desktop 加号第三页标签页`。
5. 没有开源实现时，允许 **Build**，但必须写「抄了哪几个可观察表面、哪一层我们自己做」。

---

## 12. 愿望对照表（给开写开发文档的人）

| 愿望 | CLI | GUI | 主要抄谁 | 仓库里已有线索（仅对照，不视为已交付） |
|---|---|---|---|---|
| 沙箱 + 访问档 | 要 | 要 | Codex | `safety` 现为白名单+审批；workspace 自报 `cwd_boundary_only` |
| 结构化改文件 + 红绿 diff | 要 | 要 | Codex 补丁；OpenCode / Grok Build 呈现 | `tools/edit.py` 仍是字符串替换 |
| hooks | 要 | 要 | Codex hooks | PHASE-K K14 未开工 |
| Computer Use（控制电脑 + 事实观察） | 要 | 要 | Codex | 08-12 调研曾冻结像素路线，**与本愿望冲突** |
| 加号：已下载插件 / 标签 / 旧会话 | 命令对等 | 要 | Codex 截图 | PHASE-K 偏 skill/MCP/GitHub pin，加号信息架构未按截图钉死 |
| `/goal` 目标模式 | 要 | 要 | Codex | PHASE-N 认领服务端目标；交互未按 Codex 钉 |
| Plan 模式 | 要 | 要 | Codex | 计划模式与能力门的冲突已在 GX 文档里提到 |
| `/goal` 之后的 SOP | 要 | 要 | **Grok Build** | 无现成卡叫「Grok Build SOP」 |
| 斜杠定死 skill | 要 | 要 | Cursor `/using-superpowers` | skill 发现未做成斜杠强制 |
| GitHub 内嵌浏览器 | 至少能开/控 | 要 | Codex | 无 |
| 终端 | 本身就是 | 内嵌或外链，要有 | Codex / Cursor | 无 Desktop 终端面板 |
| 审计 | 红绿 diff 即审计 | 完成物+diff+耗时+日志 | OpenCode / Codex | 有 JSONL 审计，缺用户可见 diff 流 |
| 侧边聊天 | TUI 旁路或 `/btw` | 要 | Cursor / Grok `/btw` | 无 |
| 子代理 / 多代理可点进 | 要 | 要 | OpenCode、Cursor Agent Windows | Phase D/E/F 有运行时，**没有**这种呈现 |

---

## 13. 给产品和架构师的使用说明

1. 把本文件当 **PRD 输入**，不要当施工清单逐条开工。
2. 先拍三块冲突：Computer Use 与 08-12 冻结、加号「插件 vs skill/MCP」、`/goal` 持久对象 vs Codex 交互 vs Grok Build SOP。
3. 写开发文档时保持 **P1：CLI/GUI 对等**。只写 GUI 卡或只写 CLI 卡，都算偏题。
4. 动手实现任何一条之前，用第 11 节的 skill 走一遍「先搜再造」，并把 Verdict 写进开发文档附录。
