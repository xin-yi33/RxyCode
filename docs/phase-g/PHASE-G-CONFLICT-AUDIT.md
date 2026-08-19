# PHASE-G 冲突与耦合审计登记表

> **这主要是登记表，不是施工文档。** 它登记「PHASE-G 与其他文档 / 与仓库现状之间已确证的偏差」，并给每条指派处置归属。
>
> **§6 的三张补缺卡（AX1–AX3）已全部处置完毕，本表回归纯登记表。** AX1 的卡面写进了 PHASE-F（`F18b`），AX2 并进了 PHASE-K 的 K5，AX3 因 X8 被证伪而取消。§6 现在只留裁定与指针，**不再有卡面副本**——同一张卡在两处维护只会分叉。
>
> ⚠️ **「无人认领项清零」只对 PHASE-G 冲突成立。** 本表还剩 **八条无主**，都不属于 PHASE-G、本表也无处安放，需要单独找 owner：
>
> | 编号 | 一句话 | 状态（2026-08-18 17:20） |
> |---|---|---|
> | **X13** | PHASE-D 的 §3.5 整节与 D5.5 整卡，正文被一次有损写入销毁 | ✅ **已重写**（08-18，C7 归零）。原文不可恢复——git / `.rar` / 同源文档三条路均无副本。**遗留：需 PHASE-D owner 复核一次措辞** |
> | **X14** | **31 份计划文档里 21 份不在版本控制内，S6 的 `[x]` 已回归成假** | 🛑 **已确证**——S6 自己的验收命令当场就不过。X13 之所以救不回来，根因在此 |
> | **X15** | `G1–G8` / `M1–M8` 在两份文档里各指两套完全不同的卡 | ⚠️ **已确证**。第三组撞车（`D1`/`D2`）是本表自己造的，**已改名 DF1 / DF2** |
> | **X16** | **三份 PHASE-G 的章节号都重复两到三遍**（DESKTOP 11 / BACKEND 8 / FRONTEND 8），**405 处「见 §N」不唯一** | ⚠️ **已确证**。M1 差点因此改错地方，**已给 M1 / M2 补锚点**；书写规范待定 |
> | **X17** | `PHASE-G-FRONTEND` 主链前端卡的依赖用旧卡号，**44 处引用全部指不到**；其中 `J1`–`J6` 静默解析到 PHASE-J 的无关卡 | ✅ **已修**（08-18 由 PHASE-M `M1b` 执行，C9 归零） |
> | **X18** | Phase K 的验收闸门 K21 要求「**四组**门禁全绿：97/97/95/95」，而它自己的阈值表只有**三行** | ✅ **已修**（08-18 补出「全关」对照组并标明读法；用户三条硬线数值未动） |
> | **X11** | 分目录跑全绿，合并跑出九条失败 | ✅ **九条根因全部查明**，两种机制各有 7 秒最小复现：三条是**模块身份劫持**（bare-core 别名 + 扁平子模块导入劫持点分父包属性 → 同一文件两个类），六条是**进程工作目录泄漏**（`bootstrap_agent` 的 `os.chdir` 逃出测试）。**两者都在生产代码里** → PHASE-FIX2 RL1–RL4 |
> | **X10** | 整套 pytest 一次跑会卡死、`fake_mcp_server` 堆积 | 🟡 **未在干净环境复测**，此前观测受 X12 污染 → PHASE-FIX2 RL8（含「随 RL7 消失」也算合格结论） |
> | **DF1** | 性能门禁写死 8765，撞 RxyCode 自己的 API 端口 → 门禁恒定误报失败 | ✅ **已确证并给出决定性对照**（换端口即 1.0）。**补丁只存在于独占工作树，从未落到本仓**（`bench_async.py:190` 仍是 8765）→ PHASE-FIX2 RL6 |
> | **DF2** | `_kill_process_tree` 在 Windows 上 `taskkill` 后无条件 return，兜底走不到 | ✅ **已确证**，静态可读 → PHASE-FIX2 RL7 |
>
> **DF1 直接威胁「基线达标」这类合并门**：只要开发机上开着 RxyCode，门就红，且红的原因与被测代码无关。**因此 RL6 必须先于任何需要读基线数字的卡完成**——门禁会说谎时，性能判断没有意义。
>
> 🛑 **上面五条已全部承接到 [`PHASE-FIX2-PROCESS-GLOBAL-STATE.md`](./PHASE-FIX2-PROCESS-GLOBAL-STATE.md)（RL1–RL9）。** 该 Phase 排在 PHASE-F / PHASE-G 开工之前，理由不是「测试红了不好看」：X11 的两个根因**都是生产代码在做进程级全局破坏**，而 F 的多 Agent 与 G 的桌面端会大幅增加进程内并发导入与多工作区切换，**正是这两个缺陷的放大器**。
>
> 🛑 **X13 / X14 应当排在其余各条之前处置。** 其余六条都是「文档说错了」或「测试不稳」，读得出、查得到、改得回；X13 是**正文已经不存在了**，X14 是**它还会再发生一次**。每多改一天文档，可丢的东西就多一天。
>
> **这三条是 `scripts/doc_audit.py` 查出来的**，不是人读出来的——X13 的签名是「合法 UTF-8、结构完好、只有中文变问号」，通篇浏览会直接滑过去。检查器现有 C1/C2/C4/C5/C6/C7 六项，跑法：`python scripts\doc_audit.py --severity warn --out report.txt`。
>
> 🛑 **动这四条之前，先读 [X12](#x12--x10x11-的全部测量都是在一个被并发改动的工作区里做的)** ——它解释了为什么 2026-08-18 13:00 前后那批「X11 只剩三条」的结论全部作废（测量做在被并发改动的工作区里），以及后来是怎么用独占工作树 + 单跑对照把九条污染和两个独立缺陷分开的。**在共享工作区里跑出来的测试结论，一条都不能用。**
>
> **本表出过一次严重误判（X8），已撤回。** 读的时候请记住：标 🟡 的从未复核，标 ✅ 的也只是**某一时刻**的观测。动手前自己再跑一遍。
>
> **谁该读它**：任何准备开 PHASE-G（含 G1–G16、GX1–GX28、PhaseG-B*、PhaseG-H*）某张卡的人，开工前先在这里搜一下自己那张卡的编号。
>
> **审计日期**：2026-08-18　**审计范围**：`PHASE-G-DESKTOP.md`（4400+ 行）、`PHASE-G-BACKEND.md`、`PHASE-G-FRONTEND.md`，对照 F / H / I / J / K / L / M / FIX / 00-EXECUTION-PLAN 与**仓库实码**。
>
> **一句话结论**：PHASE-G 作为产品定义与 backlog 是完整的，但它**成文早于 K / L / M，也早于仓库现在的目录与协议形态**，因此存在一批系统性偏差。其中 **9 条会导致照文档施工直接出错**，必须在开卡前处置。
>
> ❌ **本表出过一次严重误判，已撤回：X8「PHASE-E 产物不存在」是错的。** PHASE-E 实测完好——E1–E4 产物齐备、协议面与 TS 生成物同步、165 个契约测试全绿，GX19 的 E 侧前置**可以放行**。误判源于一次过时观测，且当时手边的 `git status` 已给出相反证据却被忽略。原委与教训见 §1 的 **X8**，配套的 AX3 卡已取消。**读本表的其余条目时请一并留意：标 🟡 的从未复核，标 ✅ 的也只是某一时刻的观测。**

---

## §0 怎么用这张表

| 列 | 含义 |
|---|---|
| **编号** | `X#` 硬冲突 / `S#` 软冲突 / `C#` 耦合风险 / `R#` 悬空引用 |
| **核验** | ✅ = 本人已查原文与实码复核；🟡 = 审计报告所列，未逐条复核，处置前需自行复核 |
| **归属** | 谁负责修。已有卡就写卡号，没有归属的写「**无人认领**」——**这几条最危险** |

**证据强度声明**：标 ✅ 的条目，本文给出的文件行号是 2026-08-18 实测。标 🟡 的来自审计报告，**采信前请自行复核**——审计报告本身也出过错（见 §5 的一处纠正）。

---

## §1 阻塞开工的九条（+ 二轮追加的 X8b，共十条）

按「不修就会出什么错」排序，不按严重度形容词排序。

### X1 · GX28 依赖一组**不存在且无人负责建**的协议　✅

**GX28 原文**（`PHASE-G-DESKTOP.md:4212,4217`）声称：

> `protocol/schema.json` + `protocol/*.py`（**F18 `team_*` 协议消费**——F18 合入后消费，本卡不新增字段）
> 本卡**无协议扩展**（F18 的 `team_*` 协议由 PHASE-F 定义，本卡纯消费）——按 §1 通用纪律**无需 GXn-PROTO 登记**

**F18 实际交付**（`PHASE-F-MULTI-AGENT-ORCHESTRATION.md:2003-2035`，逐条核对过）：

| F18 操作步骤 | 产物 | 是协议吗 |
|---|---|:-:|
| 1 TeamSpec 扩展 | `extra` 字段 + `ecosystem.*` 约定 | 否 |
| 2 TeamRegistry | `core/agents/registry.py` + `teams.groups.yaml` | 否 |
| 3 TeamImporter | `core/agents/importer.py` | 否 |
| 4 `team_install` | `core/builtin_tool_registration.py` 注册的工具 | 否（是工具） |
| 5 路由索引 | description 进上下文 | 否 |

**F18 的「涉及文件」里没有 `protocol/`，完成判据里没有任何 RPC。** 唯一带「协议」二字的是判据第 4 条「`team_install` 工具两步询问流程走通，**有协议测试**」——那测的是既有的 `question/request`，不是团队 RPC。

而 `event/team_*`（`PHASE-F:878`）是 **F3 的编排阶段事件流**（`stage_completed` / `team_completed`），给 F12 trace 和 GX19 投影用，**不是**团队列表 / 分组 / 安装的 RPC。

**所以 GX28 需要的 `team/list`、`team/groups`、`team/group_rename`、`team/install`、`team/set_active` 一个都不存在，也没有任何一张卡负责建。**

**为什么这条排第一**：GX28 免登记 PROTO 的理由是假的，于是**连「发现缺失就挂起」的机制都不会触发**。施工者会先把三层窗口流的组件建出来，再发现拿不到数据，然后大概率自造协议——而那正是 GX28 自己禁止的事。更麻烦的是 **PHASE-L（`:1727`「本 Phase 不改 GX28 的任何交互」）与 PHASE-M（M7/DM5「选团逻辑一律调 GX28」）各有两张卡压在它上面**，四张卡共同压在一个空产物上。

**归属：已落地（2026-08-18）。** 采用方案 ②——由拥有真相源的那张卡交付协议。完整卡面已写进 [`PHASE-F-MULTI-AGENT-ORCHESTRATION.md`](./PHASE-F-MULTI-AGENT-ORCHESTRATION.md) 的 **`F18b`**（紧随 F18，不改 F18 本体），F18 卡首另有注记指向它。裁定记录见 §6 的 AX1。

---

### X2 · `/team` 被两份文档定义成互斥的两件事　✅

| 文档 | 语义 |
|---|---|
| `PHASE-F:1486` | `/team <任务>`　**带参数**，强制走专家团路由（与 `/solo` `/team-multi` 同族，是第 1 级显式指令） |
| `PHASE-G-DESKTOP.md:4218,4227` | `/team`　**不带参数**，打开三层窗口流（分组列表 → 团队 → 详情 → Enter 使用 / Esc 逐级返回） |

两边都写了「冻结」。且 `PHASE-F:2021` 里 F18 自己也在用第一种语义：「`disable_model_invocation: true` 的团**只可由用户显式选（`/team` 命令）**」。

**扩散范围**：PHASE-L 的 `/team-new`（`:1036`）与 PHASE-M 的 DM5（`:507`）都已按 GX28 的语义写。**改名要同步四处。**

**裁定（2026-08-18）：`/team` 按参数分流——带参即路由，不带参即打开选择器。两种语义都保留，不改名。**

| 输入 | 行为 | 出处 |
|---|---|---|
| `/team <任务描述>` | 强制走专家团路由，用**当前激活的团** | PHASE-F 语义 |
| `/team` | 打开三层选择器（分组 → 团队 → 详情 → Enter 使用） | GX28 语义 |
| `/team <团名>` | **歧义，必须消解**：见下 |

**为什么这样裁，而不是给其中一个改名**：

1. **两种语义在用户心里本来就是一件事**——「我要用专家团」。带不带参只是「我已经知道用哪个」和「我还要挑一个」的区别。这正是 `/model` 已经在用的模式（`/model` 开选择器、`/model <名字>` 直接切），**CLI 里已有先例，用户不需要学新规则**。
2. **改名的代价是四处同步**（PHASE-F、GX28、PHASE-L 的 `/team-new`、PHASE-M 的 DM5），而且改完之后 `/team` 这个最自然的名字要么空着、要么归其中一方，另一方拿到一个更差的名字。**收益是消除歧义，但分流同样能消除歧义，且代价为零。**
3. F18 那句「`disable_model_invocation: true` 的团只可由用户显式选（`/team` 命令）」**在分流方案下依然成立**——不带参打开选择器，选择器里能看到这些团，这本来就是「用户显式选」。

**必须同时冻结的一条消歧规则**（否则分流方案会在这里塌掉）：

`/team <团名>` 与 `/team <任务描述>` 在语法上无法区分。**规则：先按团名精确匹配已注册的 team id / display_name，命中则视为「切换到该团」；未命中才视为任务描述。** 精确匹配、不做模糊匹配——模糊匹配会让「帮我重构 team 模块」这种任务被误吞成切团。

**归属：已落地 → `PHASE-N` 的 [N8 卡](./PHASE-N-CLI-PARITY-LONGRUN.md)（2026-08-18）。** 分流表、消歧规则与理由已写进 N8 并冻结，`/team` 加入该卡的命令注册批次（7 条 → 8 条），完成判据新增三条（三种输入形态各有测试、消歧须为精确匹配且有反例、PHASE-F 与 GX28 各加注记指向该规格）。**两边既有描述不改**——它们各写对了一半。

---

### X3 · 前后端目录路径大面积指向不存在的位置　✅　**（后端侧已于 08-18 写进 M2）**

| 文档写法 | 出现次数 | 仓库实际 |
|---|---:|---|
| `frontend/desktop-app/src/features/<name>/` | **85 处**（DESKTOP）+ 3 处（FRONTEND） | 不存在，实际是 `src/renderer/src/` |
| `appserver/handlers/<x>.py` | **20 处**（DESKTOP 16 + BACKEND 4） | 不存在，实际是 `model_routes.py` / `subagent_routes.py` 平铺 |
| `tests/test_protocol/` `test_threads/` `test_review/` 等目录 | 各卡验收命令 | 均不存在 |

**归属：PHASE-M 的 M1 + M2。已补齐（2026-08-18）。**

原状是 M2 只管前端，后端那 20 处 `appserver/handlers/*` 没人管（PHASE-K `:888` 只点名了 `handlers/plugin.py` 一处）。**现已把后端并入 M2**，理由是前后端属同一类问题、同一条裁定，拆两张卡等于让两个人各判一遍还可能判出不同结果。

M2 扩容后新增三行映射：根 `tests/` → 前端同目录、`appserver/handlers/<x>.py` → `appserver/<x>_routes.py`，并在验收命令里加了**反向断言**（`handlers/` 若被建出来则 throw）。`PHASE-G-BACKEND.md:904` 的白名单行同步由 M1 改写。

---

### X4 · `frontend/opentui-app/` 不在 PHASE-G 的文件白名单里，但 GX28 要改它　✅

`PHASE-G-DESKTOP.md:2092` 的表头写着「**白名单，不可越界**」，表内列了 `appserver/`、`protocol/`、`frontend/protocol-client/`、`frontend/desktop-app/`、`packaging/`——**没有 `frontend/opentui-app/`**。

而 GX28（`:4207,4235`）要改它。全文涉及 CLI 只有 3 处：`:366` 是架构图（非规范性），另两处都属 GX28。

**并发风险**：PHASE-K 的 K6 要改 `DialogSelect`，PHASE-FIX 要改 `stdioTransport.ts`，加上 GX28——**三方在同一目录，无边界约定**。

**归属**：已在 PHASE-G 顶部加注记声明「CLI 归 [`PHASE-N-CLI-PARITY-LONGRUN.md`](./PHASE-N-CLI-PARITY-LONGRUN.md)」。**仍需补的是 §3 白名单表的那一行与三方并发边界**，否则白名单形同虚设。

---

### X5 · `plugin/toggle` 是不是独立协议方法，两份文档给了相反答案　🟡

| 文档 | 说法 |
|---|---|
| `PHASE-G-BACKEND.md:579,584`（B18）+ GX24-PROTO 登记表（`DESKTOP:4289`） | `plugin/toggle`（**new_method**，登记 GXn-PROTO） |
| `PHASE-K:311,928,2231`（KC6） | 「`plugin/toggle` 在实现上转发到 `capability/set`，**不是第二套逻辑**，有测试」 |

**照 B18 原文施工会造出第二套开关状态机，直接违反 KC6。**

**归属：已接上执行者（2026-08-18）。** KC6 早有裁定，缺的是把它接进 GX24-PROTO 登记表。现已在 PHASE-K §3.3 注记里给出登记口径表（`plugin/toggle` → 「由 `capability/set` 提供，不新增方法」），并**写进 K5 卡的完成判据**——K5 不改登记表就不算完。实际动登记表的手是 GX24 owner，但现在有人盯着了。

---

### X6 · `plugin/search` 无人负责　🟡

PHASE-K 的 **DK4**（`:122`）裁定「**不自建市场**」，GX24 的市场页因此要改为消费 `plugin/search`。但这个方法**既不在 GX24-PROTO 登记表里，也不在 K 的方法清单里**——该清单在 `PHASE-K:308-312`，共**六个**：`capability/list` / `preview` / `set` + `plugin/list` / `install` / `uninstall`。

> 建表时此处写的是「五方法清单」，**记错了，已改为六个**（实测 `PHASE-K:308-312`）。数目不影响本条结论（`plugin/search` 不在其中），但既然要求下游按行号复核，就不该留一个对不上的数字。

GX24 开工时会发现市场页没有数据源。

**归属：已落地（2026-08-18）。** 归 PHASE-K——它是 DK4 那条裁定的直接产物，做决定的人负责把决定落成接口。方法已补进 §3.3 表（六行 → 七行）、K5 完成判据已同步。详见 §6 的 AX2。

---

### X7 · `/auto` 是一条**写进完成判据**的悬空引用　✅

`PHASE-G-DESKTOP.md:4263` 的 GX28 完成判据：

> - [ ] 双控路由：`disable_model_invocation` 团队在 **`/auto`** 不可见

全仓 + 全文档搜索 `/auto`，**只命中 PHASE-G 这两行**。PHASE-F 的显式指令族是 `/solo` `/team` `/team-multi`（`:1485-1487`），F18（`:2021`）的表述是「**模型自动选择时**不可见」——是一个状态，不是一个命令。

**为什么单列**：这不是正文里的笔误，**是一条要写测试的判据**。施工者会去实现一个不存在的命令，或者卡在这里。

**归属：已并入（2026-08-18）。** 原文只写了「建议并进 M1」——**建议不是执行**，M1 的清单里当时并没有它。现已作为**第十四条**写进 [`PHASE-M`](./PHASE-M-GUI-BASELINE-CAPABILITY.md) §7.4.1，改为「模型自动路由（F10 第 2/3 级）不可见」，并进了 M1 的完成判据与反向断言（`/auto` 命中数须为 0）。

---

### X8 · ~~PHASE-E 产物不存在~~ → **撤回。本条曾经的结论是错的**　❌

> **2026-08-18 二次复核：X8 的核心指控不成立，全部撤回。** 保留本条不删，是因为它已经被引用到 PHASE-E、PHASE-G GX19、PHASE-G §2、README 四处，删掉会让那些指针悬空；也因为**它出错的方式本身值得留档**。

**当初写了什么**：称 PHASE-E 七张卡全标 `[x]` 但产物不在仓库里，依据是三项实测——七个 commit SHA 全库不存在、`appserver/agent_runtime.py` 不存在、`AgentEvent`/`event/agent` 全仓零命中。据此判定 GX19 的门控会**误判为可开工**。

**实际情况**（2026-08-18 二次实测，全部可复现）：

| 卡 | 产物 | 结果 |
|---|---|:-:|
| E1 | `appserver/eventbus.py` `class EventBus:191` | ✅ 在（11,646 B） |
| E2 | `appserver/agent_task.py` `class AgentTask:68` | ✅ 在（11,780 B） |
| E3 | `appserver/agent_runtime.py` `class AgentRuntime:162` | ✅ 在（19,100 B） |
| E4 | `AgentEvent`/`event/agent` 于 `protocol/notifications.py`、`protocol/schema.json`、`frontend/protocol-client/src/generated/types.ts` | ✅ 三处全中，TS 生成物已同步 |
| E1–E6 | `tests/contract/test_{eventbus,agent_task_lifecycle,agent_runtime,agent_protocol,agent_context,agent_quota}.py` | ✅ **165 passed in 4.99s** |
| E7 | `evidence/bench-multi-agent-E{,1,-stress}.json` | ✅ 在 |

**唯一站得住的部分**：七个 commit SHA 确实解析不了。但这**完全由历史 squash 解释**（本仓有 `backup-pre-p4-squash`、`backup-pre-p4-r9-fold`），而且恰恰印证了「SHA 不该当凭据」这个正面结论。

**这条为什么会错——两个原因，第二个更要紧**：

1. **观测过时。** 第一次核查时那四个文件确实不在工作区（`Get-ChildItem appserver` 逐项列过，没有它们）。文件的 `mtime` 是 **2026/8/18 2:58**，晚于那次核查。它们在核查之后才落到盘上。
2. **我把「当下不在」写成了「从未存在」，并且预先驳回了唯一正确的反驳。** 当时想到了 squash 这个解释，但用「squash 只改 SHA 不改内容，内容若合过符号会留在文件里」把它排除掉了。**这个推理本身没错，错在它建立在第 2、3 项观测上，而那两项观测是过时的。** 更糟的是，会话开始时的 `git status` 快照里明明白白列着 `A appserver/agent_runtime.py`——**证据一直在手边，只是与我的观测冲突时，我信了自己的观测。**

**留下的教训，比原结论有用**：

- **两个信源打架时，先解释矛盾，再下结论。** `git status` 说文件已暂存、`Test-Path` 说文件不存在，这两件事同时为真只有很少几种可能（暂存后删除、时序差、路径错），逐个排掉最多花一分钟。跳过这一步、直接采信其中一个，就会得到一个自洽但错误的结论。
- **给出的证据越硬，越要留复现命令。** X8 原文写的是「全仓零命中」这种绝对断言，却没让读者一眼看出它是**某一时刻**的观测。PHASE-E 现在的完成表补了「验证命令」列，就是为了让任何断言都能被当场重跑——**这条正面做法保留，它本来就是对的，只是被挂在了一个错误的例子上**。

**受影响的四处已全部更正**：PHASE-E 完成表（恢复 `[x]`，补验证命令列）、PHASE-G GX19 注记（改为放行）、PHASE-G §2 第 8 项（保留探针，改写理由）、README（改为正面做法）。

**AX3 已取消**，见 §6。

---

### X8b · ~~完成标记普遍不可信~~ → **降级为一条正面做法**　🟡

原文由 X8 推广而来，称「这批规划文档的完成标记没有验证机制」。X8 既已撤回，这个推广就**失去了它唯一的证据**。

**保留的部分**（与 X8 无关，独立成立）：

- `PHASE-G-DESKTOP.md` §6.0 声称「D1–D8 已合入 master」「10874 后端测试全绿」「136 tests」。`appserver/model_routes.py`、`config/credential_store.py`、`SettingsPage.tsx` 确实存在（已核）。**测试数量 2026-08-18 已复现：实测 12,020 passed / 0 failed**（分目录批量执行，10m43s）。数字比 10874 多约 1150，方向一致——套件在此期间增长了，**「全绿」这个断言属实**。✅ 本条待查项关闭。
- 同文件 §2 前置自检列出七项并要求输出 `BLOCKED`，**与 §6.0 的「已合入」在语气上冲突**。这一条与 X8 无关，仍需 PHASE-G owner 澄清。🟡

---

### X12 · **X10/X11 的全部测量都是在一个被并发改动的工作区里做的**　✅　**先读这条，再读 X10/X11**

**这条不是新缺陷，是对前两条证据效力的否定。**

2026-08-18 13:45 查 `git reflog --date=iso` 发现，**在测量进行期间本仓被切了分支**：

| 时刻 | 动作 |
|---|---|
| 13:17:31 | `reset: moving to HEAD`（**把 `core/agent_v2.py` 的未提交改动回退掉了**，该文件 mtime 正是 13:17:31） |
| 13:17:33 | `checkout: master -> cursor/release-v1210-verify-0ef5` |
| 13:17:58 | 又两次 checkout |
| 13:18:03 | `checkout: ... -> master` |
| 13:27:23 / 13:33:10 | `main.py` / `core/session.py` 被改（非本次排查所为） |

**这些动作不是排查者做的**——全程没有执行过任何 `git checkout` / `reset`。分支名 `cursor/release-v1210-verify-0ef5` 指向另一个在同一工作目录上作业的 agent。

**后果，按时段逐条判定**：

| 测量 | 时段 | 是否可信 |
|---|---|---|
| 前 12 目录合并 → 3 failed | 12:44–12:58 | **可信**（churn 之前，单进程） |
| 前 14 目录合并 → 3 failed + traceback | 13:00–13:12 | **可信**（同上） |
| 「12 个目录 + 受害文件 → clean」 | 13:21–13:31 | **不可比**——跑在 13:17 reset **之后**的代码上，与上面两次不是同一份源码 |
| 「污染源在 test_core 内部」这个推论 | — | **随之作废**，它建立在跨版本比较上 |
| bisect2 / delta 的全部输出 | 13:32 起 | **作废**（另有自身原因，见下） |

**另有一条必须自认的错**：13:38–13:45 期间有两个排查脚本**同时**在跑 pytest。原因是 kill 时拿到的是外层包装进程的 PID，真正的 PowerShell（27528 / 30652）没被杀掉，脚本继续推进到了下一个探针。**那段时间的「clean」全部是两个 pytest 互相干扰下的产物**——`all 11 + test_core` 只用了 75 秒就报 clean，而同样配置此前需要 283 秒，本身就说明它没跑完该跑的东西。已彻底清理。

**对 X10 的直接影响**：X10 记的「每 ~23 秒堆积一个 `fake_mcp_server`，累计 30 个并存」**很可能根本不是泄漏，而是多个 pytest 会话并存**。原排查排除了五个假设，但**没有排除「并发」这个假设**，因为当时没人想到工作区是共享的。**X10 需要在独占环境里重测后才能定性。**

#### 由此得出的一条纪律（比这两条 bug 本身更重要）

**在共享工作区里跑出来的测试结论，一条都不能用。** 后续任何 X10/X11 的测量必须满足三条，缺一不可：

1. **独占的源码快照**——用 `git worktree add` 挂一个钉死到具体 commit 的工作树，别的 agent 切分支不会波及它
2. **确认无并发 pytest**——开跑前 `Get-CimInstance Win32_Process | Where CommandLine -match 'pytest'` 计数为 0，收工时再查一次
3. **记录测量时的 commit 与 `git status`**，写进结论旁边；**没有这两样的测量结果不予采信**

第 3 条同时解释了 07:00 那批数据（12 失败 / 23 失败 / 九条受害者）为何复现不出来——**它们同样没有记录当时的树状态**，而那个时段大概率也在被并发改动。

> **14:50 更正**：这句话只有一半对。在独占工作树里重测后，**「九条受害者」原样复现、逐条吻合**，07:00 那份名单是准确的；复现不出来的只有「12 → 23 单调增长」那个观察。**换句话说，被污染的不是 07:00 那次测量，而是 12:44–13:15 那几次「复核」**——是它们错误地推翻了一份正确的记录。这个方向值得记住：**脏环境既会制造假失败，也会制造假的「问题已消失」**，后者更危险，因为它让人停止调查。

#### 这三条已经落成可直接用的东西（2026-08-18 14:40）

**独占工作树已建好**，钉死在 `e47c38a`：

```powershell
git worktree add --detach "D:\agent-demo\RxyCode-verify\RxyCode1_1_0" e47c38a
```

放在 `RxyCode-verify\` 而不是 `RxyCode\` 下，是为了不与主检出争 `RxyCode.RxyCode1_1_0` 这个包名的目录形态；实测 conftest 的合成模块机制与路径无关（`tests/conftest.py:27-53` 自建 `sys.modules["RxyCode.RxyCode1_1_0"]`），**受害文件在该树单独跑 6 passed / 2.30s，环境可用**。

**跑测量用 `scripts/x11_clean.ps1`**（在该工作树内），它把三条纪律做成了硬门：开跑前若检测到任何其他 pytest 进程就 `ABORT` 不测；跑完比对前后的 `commit` 与 `git status`，**不一致就在日志里判定「result is NOT evidence」**。

> **主检出里那三个排查脚本（`x11_bisect.ps1` / `x11_bisect2.ps1` / `x11_delta.ps1`）产出的数据全部作废**，它们跑在共享树上，其中后两个还一度并发。
>
> **2026-08-19 更新：这三个脚本已删除，不要再去找。** 原话说「脚本本身逻辑没问题，挪到独占树可复用」——**这个说法后来被推翻了**：同名系列里至少有一个栽在 `Tee-Object` 上（它同时往管道写，输出混进判定函数的返回值，让二分每步无条件向左，日志里每行其实都是 `target_failures=0`，详见下面 16:00 段的注）。**留着一个已知会给出自信错误结论的工具，比没有工具更危险。**
>
> **现行可用的排查脚本只有一个**：`scripts/x11_cache_hunt.ps1`（23:40 段那次二分就是它跑出来的）。它把 RM1/RM2 两条纪律做成硬门（开跑前检测并发 pytest 直接 `ABORT`，跑前跑后记录 commit 与脏文件数），并且**刻意用 `Write-Host` + `Add-Content` 而不是 `Tee-Object`** 记日志。要新写排查脚本请照它抄，别照被删的那三个抄。
>
> 另注：主检出 `scripts/` 下 07:00 那批脚本（`find_polluter.ps1`、`run_batched_tests.ps1`、`capture_merged_failures.ps1` 等七个）**已被那次 checkout 抹掉**。引用它们的结论无法再复现——这本身就是「共享工作区」代价的一个具体注脚。

> 🔍 **本表引用的四个排查脚本，现在一个都不在主仓里**（2026-08-18 由 `scripts/doc_audit.py` 的 C1 证据检查扫出）。**它们支撑的结论并不因此作废，但都降格成「不可当场复跑」**——谁要再动这些结论，得先把脚本重建出来：
>
> | 脚本 | 在哪被引 | 撑着什么结论 | 现状 |
> |---|---|---|---|
> | `scripts/x11_clean.ps1` | `:283` | X11 净室复测的**全部**数据（九名受害者、双因子、模块劫持） | 只在独占工作树 `D:\agent-demo\RxyCode-verify\`，**刻意未入本仓** |
> | `scripts/bisect_hang.ps1` | `:316` | X10 的最小复现子集 | 被 checkout 抹掉 |
> | `scripts/bisect_hang3.ps1` | `:341` `:581` | X10 第三轮的预算/判定两处纠正、`http.server` 孤儿进程的定位 | 被 checkout 抹掉 |
> | `scripts/run_batched_tests.ps1` | `:374` `:673` `:1022` | §6.5 基线表「分开跑全部零失败」、以及**当前推荐的绕法** | 被 checkout 抹掉 |
>
> 最后一行是唯一需要马上处理的：`:1022` 把它写成**后端现在就该用的跑法**，`:673` 说它「已验证」。一条现行操作规程指向一个不存在的文件，下一个人照做只会得到 `command not found`。**重建它，或者把那两处改成显式的分目录命令行。**
>
> 这四条同时也是 X14（计划文档与排查资产都不入版本控制）的下游症状：**脚本没进 git，所以一次 checkout 就带走了一批证据。**

---

### X10 · `pytest tests` 一次性跑会卡死，必须分目录批量执行　✅　**2026-08-19 干净房结案（PHASE-FIX2 RL8 / (a)）**

**2026-08-19 干净房重测（RL7 之后，独占 worktree `D:\agent-demo\RxyCode\RxyCode-fix2`，commit `a064678`，脏文件 0，RM1 无并发 pytest）**：

| 项 | 值 |
|---|---|
| 命令 | `python -m pytest tests -q --tb=line` |
| 结果 | **整套跑完**，671.15s（0:11:11） |
| 计数 | 38 failed, 12011 passed, 3 skipped, 371 warnings, 5 errors |
| `fake_mcp_server` 采样 | 每 30s 一次，**全程 count=1**，峰值 1，无每 23s 堆积到 30 的曲线 |

X10 的原症状是「36 分钟跑不完 + fake_mcp 稳定堆积到 30」。本次**未复现卡死**，进程数也没有累积。失败项是定价/session/身份门等既有或 RL5 门抓出的用例，不是挂起。判定 **(a)：X10 随 RL7 消失**，整套跑可作为权威口径；那 38/5 另开卡，不在本条修。

**2026-08-18 实测的两组对照**（历史，证据效力见 X12）：

| 执行方式 | 结果 |
|---|---|
| `python -m pytest tests -q --timeout=900`（整套一次跑） | **36 分钟未跑完**，期间稳定每 ~23 秒堆积一个 `fake_mcp_server.py` 子进程，累计 30 个并存；手动终止 |
| 按 `tests/` 子目录逐个跑（每目录 `--timeout=120`） | **12,020 passed / 0 failed，10 分 43 秒** |

**同一批测试，一个跑不完，一个十分钟全绿。** 所以问题不在任何单个模块——`tests/test_mcp/test_stdio_runtime.py` 单独跑是 **9 passed / 3.32s**，快得很。

**已排除的三个假设**（都靠证据否掉，记在这里是为了让下一个查的人不必重走）：

1. **配置污染** —— 曾怀疑 `test_mcp_failure_backoff_preserves_healthy_server` 通过 `save_config()` 把 MCP server 写进会话级共享配置，污染后续所有建 agent 的测试。**两次独立否定**：① A/B 对照，`tests/test_bridge` 单独 2.19s、前置 MCP 文件后 5.46s，多出的 3 秒正好是 MCP 文件自身耗时，无放大；② 直接翻会话运行时目录（`%TEMP%\rxycode-tests-*`），`data/config.yaml` **只有 4 字节**，全目录递归搜 `mcpServers` / `fake_mcp_server` **零命中**。
2. **`_refresh_mcp_tools` 丢弃旧客户端** —— `core/agent_v2.py:3508` 有一句 `self._mcp_clients = {}`，看着像不关旧连接就重置。**实际它在 `if not hasattr(self, "_mcp_lock")` 分支内，是首次惰性初始化**，不是刷新路径。
3. **`test_mcp` 与某个大目录两两冲突** —— 三种配对（配 `test_core` / `contract` / `test_subagents+test_execution`）全部干净通过，见上表。
4. **`load_config()` 有模块级缓存，缓存了被污染的配置** —— `config/settings.py` 的 `load_config()` **每次都从磁盘读**（`:124`，只有 `_CONFIG_LOCK` 一把锁，无缓存变量、无 `lru_cache`）。假设不成立。
5. **泄漏的 agent 自带重试循环在反复重生** —— `_schedule_mcp_refresh`（`core/agent_v2.py:3767`）起的是**一次性守护线程**，跑完 `_refresh_mcp_tools` 就结束，不是循环。单个泄漏的 agent 不会自己每 23 秒重生一次。

**排查时的一条观察，供下一个人参考**：`tests/conftest.py` 的 autouse fixture `_isolate_process_singletons` 还原 7 个模块单例（`core.tracing` / `core.question` / `core.session_runtime` / `core.safety.approval` / `core.safety.audit` / `log.monitor.run_monitor` / `recovery.circuit_breaker` / `utils.streaming.token_stats`）——**其中没有一个与 MCP 有关**。这不构成证据，但是个值得先看的方向。

**剩下的解释空间**：磁盘配置干净、无内存缓存、无重试循环、两两组合干净。那么重生只能来自**后续测试新建的 agent**，而它们又得从某处拿到指向 `test_mcp` 临时目录的 server 配置。**下一步该做的是经验取证而不是继续推测**：复现前 15 个目录，在 fake 进程出现的瞬间抓当前正在跑的测试名、以及 fake 命令行里的 tmp 路径指向哪个测试的目录。**上面五条假设都是推测先行、被数据推翻的，第六条不该再这么开始。**

**根因未定位**，但影响明确且属上线级：**「跑一遍全量测试」这个最基本的动作在本仓当前不可用**。CI 若照 `pytest tests` 配置，会挂到超时而不是给出结果。

**第一轮二分的否定结果（2026-08-18，`scripts/bisect_hang.ps1`）**——三种含 `test_mcp` 的组合**全部干净通过**，均未复现：

| 组合 | 耗时 | `fake_mcp_server` 峰值 | 结果 |
|---|---|:-:|---|
| `test_mcp` + `test_core` | 274s | 1 | 7,417 passed |
| `test_mcp` + `contract` | 213s | 0 | 871 passed |
| `test_mcp` + `test_subagents` + `test_execution` | 41s | 1 | 637 passed |

**这排除了「`test_mcp` 与某一个大目录两两冲突」这个最直觉的假设。** 峰值 1 是正常的瞬时值（测试自己起的那个），不是堆积——整套跑时是稳定累积到 30。

**下一步该往哪查**：既然两两组合都干净，触发条件更可能与**会话规模**相关（累积的 autouse fixture 状态、tmp_path 数量、未回收的事件循环），而不是某一对目录。所以第二轮改成了按前缀二分。

**第二轮二分的确证结果（`scripts/bisect_hang2.ps1`）**：

| 探测 | 判定 | 依据 |
|---|---|---|
| 全部 19 个目录 | **复现** | 856s 时出现 **3 个并发** `fake_mcp_server`（健康运行峰值为 1） |
| 前 5 个目录 | 干净 | 219.9s，877 passed，峰值 0 |

**所以复现是确定性的，且触发点落在第 6–19 个目录的加入过程中。**

> **⚠️ 同时要撤回该轮的一条判定，并记下它错在哪。** 该轮还报告「前 10 个目录复现」，依据是超出 600 秒预算——**这是误判**。那 10 个目录分开跑的耗时合计约 514 秒，600 秒只留了 17% 余量，而且当时 `peak fakes=0`（没有任何泄漏迹象）。它是**预算不够**，不是卡死。
>
> **这跟本轮修掉的 C8 bench 门是同一类错误：一道门因为错误的原因报失败。** 我在写探测脚本时犯了自己刚审计出来的毛病。
>
> **第三轮（`scripts/bisect_hang3.ps1`）的两处纠正**：① 预算改为该子集**实测批量耗时的 2.5 倍**（下限 180s），不再用固定值；② **「泄漏堆积」与「超时」判成两种不同结论**，只有堆积算复现，超时先按 2 倍预算重试一次再说。

**第三轮的收敛结果**：

| 探测 | 判定 | 数据 |
|---|---|---|
| 前 12 个目录 | **干净** | 709.7s / 预算 1316s，峰值 fakes=1 |
| 前 16 个目录 | **泄漏** | 790.9s，峰值 fakes=**3** |

| 前 14 个目录 | 干净 | 742.7s，峰值 fakes=**0** |
| 前 15 个目录 | **泄漏** | 766.9s，峰值 fakes=**3** |

**二分收敛（06:56）：最小泄漏前缀 = 1..15，把它推过阈值的目录是 `tests/test_subagents`。**

**但这不等于「`test_subagents` 有 bug」**，恰恰相反——它单独跑是 **447 passed / 14.8s** 全绿（§6.5），第一轮配 `test_mcp` + `test_execution` 三者同跑也干净（637 passed / 41s）。**只有当它跟前面 14 个目录累积在同一个会话里时才触发。** 所以要查的是「前 14 个目录留下了什么，使得 `test_subagents` 开始泄漏 MCP 子进程」，而不是去审 `test_subagents` 本身。

第二轮那条「前 10 个复现」的误判也就此坐实——前 14 个都干净，前 10 个当然更干净。

> **注意这两条线要分开看**：前 14 个目录**没有进程泄漏**（峰值 0），但**有 23 个失败**。所以 X10（泄漏）与 X11（合并失败）**触发条件不同**，先前「很可能同源」的猜测**证据上站不住**——失败在第 12 个目录就出现了，泄漏要到第 15–16 个才出现。**当作两个独立问题处理。**

---

### X11 · **同一批测试，分目录跑全绿，合并跑出九条失败**　✅　**九条根因已全部查明（17:20 / 23:40 两段），承接于 PHASE-FIX2 RL1–RL4**

> **只想知道结论的，读这三段就够**：**17:20 段**（三条 = 模块身份劫持）、**23:40 段**（六条 = 工作目录泄漏）、以及 **14:50 段**（九条名单如何确证）。中间 12:44 / 13:00 / 13:10 那几段复核做在被污染的工作区里，结论（「只剩三条」「增长不成立」）已作废，保留只为留痕。
>
> **两个根因都在生产代码里，都不是测试基础设施问题。** 施工卡见 [`PHASE-FIX2-PROCESS-GLOBAL-STATE.md`](./PHASE-FIX2-PROCESS-GLOBAL-STATE.md)。

二分过程中顺带采到的摘要，**失败数随合并规模单调增长**：

| 合并范围 | 摘要 | 分开跑的失败数 |
|---|---|:-:|
| 前 12 个目录 | `12 failed, 9238 passed, 3 skipped` | **0** |
| 前 14 个目录 | `23 failed, 9714 passed, 3 skipped` | **0** |

同样这些目录，`scripts/run_batched_tests.ps1` 一个个分开跑时**全部零失败**（见 §6.5 基线表）。

**「12 → 23」这个增长比失败本身更能说明问题。** 多合并两个目录（`test_planning` + `test_providers`，两者分开跑合计才 16 秒、13+474 条全绿）就多出 11 个失败——**这不是某两个测试互相看不顺眼，是残留在累积**。会话里跑过的测试越多，后面倒下的越多。

这也解释了为什么整套跑会失控：按这个趋势外推到 19 个目录，失败数会更高，同时叠加 X10 的进程堆积。

**这比 X10 的进程泄漏更要紧。** 泄漏只是慢和费资源，而这个意味着——

- **测试结果取决于你怎么切分套件**。同一份代码，分开跑绿、合起来跑红。
- **两种跑法都不能当作权威**。分批跑可能在掩盖真实缺陷（测试之间本该暴露的干扰被切分隔离掉了）；合并跑可能在制造假失败（前一个测试污染了后一个）。**在查清之前，§6.5 那份「12,020 全绿」的基线只能说明「分批口径下全绿」，不能直接等同于「代码没问题」。**
- CI 无论选哪种跑法，都在一个未经解释的口径上做发布决策。

**失败名单已采集并逐个隔离复跑**（`scripts/capture_merged_failures.ps1`，2026-08-18 07:09）：

**九条是真正的污染受害者——单独跑全部通过**：

| 测试 | 数量 |
|---|:-:|
| `tests/test_cache/test_model_contracts.py`（`test_catalog_has_nine_provider_contracts` / `test_catalog_schema_validates_contracts` / `test_contract_required_fields` / `test_contract_single_read_entry`） | 4 |
| `tests/test_core/test_turn_context.py`（`test_chat_path_ignores_blocks` / `test_agent_path_appends_after_memory` / `test_empty_blocks_byte_identical_through_agent_path`） | 3 |
| `tests/test_cache/test_no_rework.py::test_git_snapshot_captures_status` | 1 |
| `tests/test_cache/test_s1_s2_split.py::test_research_not_second_system` | 1 |

**这九条就是 X11 的本体**：代码没问题，是会话里前面的测试留下了什么，让它们在合并跑时倒下。注意 `test_turn_context` 那三条属于 PHASE-FIX 的冻结面（`core/turn_context.py`），**污染打到了缓存前缀不变量的测试上**，值得优先查。

#### ~~2026-08-18 12:44 复核：九条里只剩三条~~　❌　**这次复核作废，见下面 14:50 的干净房结论**

> **下面这一整段的测量做在被并发改动的主检出里**（X12），且当时我判断的「无并发」是错的——我自己有三个后台 pytest 脚本没杀干净。**结论不成立，保留原文只为留痕。**

上面这份名单**部分过期**。同日 12:44 按原口径重跑（同机、同分支、无并发），结果：

| 口径 | 07:00 记录 | 12:44 实测 |
|---|---|---|
| 前 12 目录合并 | `12 failed, 9238 passed` | **`3 failed, 9048 passed`**（13 分 32 秒） |
| 复现的失败 | 九条受害者 | **只有 `test_turn_context.py` 那三条** |

**没能复现的部分**（结论：当时的观测不可靠，或依赖那个会话特有的环境状态）：

- `test_model_contracts.py` 四条：用 07:00 那次 `find_polluter.ps1` 给出的精确复现对（`tests/test_appserver` + 该文件）原样重跑，**140 passed，零失败**。同时排除了三种解释——工作区那两处改动（`core/agent_v2.py` / `core/bridge/acp.py`）改的是传输重试异常分类，与 catalog 无关；**未安装 `pytest-randomly`**，不存在用例顺序随机；`%TEMP%` 下无遗留 `rxycode-tests-*` 会话目录。
- `test_no_rework.py` 与 `test_s1_s2_split.py` 各一条：本次未出现。

**仍然成立且已稳定复现的部分**：`test_turn_context.py` 的 `test_chat_path_ignores_blocks` / `test_agent_path_appends_after_memory` / `test_empty_blocks_byte_identical_through_agent_path`。

#### 2026-08-18 14:50 干净房重测：**九条全部复现，07:00 的原始名单是对的**

在独占工作树（`RxyCode-verify\`，钉死 `e47c38a`，跑前跑后 `git status` 一致、无其他 pytest 进程）按原口径重跑前 12 个目录，**结果可采信**：

```
15 failed, 9045 passed, 3 skipped in 505.11s
[after] commit=e47c38a dirty_files=1 other_pytest=0 → worktree stable, admissible
```

再把这 15 条所属的 6 个文件**在同一个工作树里逐个单独跑**作对照，判据很干净——单独也失败的不算污染，单独通过、合并才失败的才是 X11：

| 文件 | 单独跑 | 合并跑 | 判定 |
|---|---|:-:|---|
| `tests/test_cache/test_model_contracts.py` | 31 passed | 4 failed | **X11 污染** |
| `tests/test_core/test_turn_context.py` | 6 passed | 3 failed | **X11 污染** |
| `tests/test_cache/test_no_rework.py` | 52 passed | 1 failed | **X11 污染** |
| `tests/test_cache/test_s1_s2_split.py` | 5 passed | 1 failed | **X11 污染** |
| `tests/contract/test_bench_gate.py` | 3 failed | 3 failed | 不是 X11 → 见下 **DF1** |
| `tests/test_bridge/test_agent_bridge.py` | 3 failed | 3 failed | 不是 X11 → 见下 **DF2** |

**4 + 3 + 1 + 1 = 九条，与 07:00 的原始名单逐条吻合。** 所以：

- **X11 成立，规模是九条不是三条**，12:44 那次「只剩三条、`test_model_contracts` 不复现」是污染环境下的假象；
- 「12 → 23 单调增长」那个观察**仍未复现**（干净房前 12 目录是 15 failed，其中 9 条污染 + 6 条独立缺陷），暂不作为依据；
- 顺带把两个**一直被误记在 X11 名下的独立缺陷**摘了出来，见下面 DF1 / DF2——它们跟合并与否无关，单独跑一样红。

**方法论上值得记一笔**：这次能把九条污染和六条真缺陷分开，靠的不是更长的日志，而是**在同一个环境里加了一组单跑对照**。此前几轮都只跑合并、拿合并结果去猜，才会把 `test_bench_gate` 这种「本来就坏」的东西算进污染账上，一路查错方向。

#### 2026-08-18 15:30 定性：`test_turn_context` 那三条是**双因子**触发，这是前几轮全查空的原因

三次实测（独占工作树，`e47c38a`，`tracked_dirty=0`）：

| 组合 | `test_turn_context` 结果 |
|---|---|
| 前 9 个目录 + **仅 `test_turn_context.py` 这一个文件** | ✅ 通过（同批里 contract/bridge/cache 自己有 12 条失败） |
| **整个 `tests/test_core` 目录**单独跑（7408 条） | ✅ 全绿，3 分 40 秒 |
| 前 9 个目录 + **整个 `tests/test_core`** | ❌ 三条失败 |

**触发需要两个因子同时在场**：某个（些）在前面跑过的目录，**以及** `test_core` 里除受害文件之外的其他文件。**去掉任一因子都不复现。**

这直接解释了此前几轮排查为什么颗粒无收——**它们都在做单因子搜索**：要么固定受害文件去找「哪个目录污染了它」（永远找不到，因为缺第二个因子），要么在 `test_core` 内部找「哪个文件污染了它」（也找不到，因为缺第一个因子）。**07:00 那次 `find_polluter.ps1` 给出的所谓「精确复现对」（`tests/test_appserver` + 单个受害文件）就是这么来的，它在这个口径下复现不了并不奇怪。**

> **给下一个人的方法论提醒**：套件污染的默认心智模型是「A 污染 B」的一对一关系，工具（包括 `pytest-bisect` 一类）也大多按这个模型设计。**这里的形状是「A 与 C 共同作用才污染 B」**，一对一的搜索在这种形状面前会稳定地返回「无污染源」，而且返回得很快很自信。**看到「怎么找都找不到，但合并跑就是红」时，先怀疑因子数，别怀疑复现性。**

**注意 `test_cache` 那六条与本条形状不同**：在「前 9 个目录 + 单文件」那次运行里，`test_cache` 的六条**照样失败**——它们是单因子污染，受害于更早跑过的目录。所以 X11 名下的九条**至少是两种不同的机制**，不要指望一个修法全解决。

#### 2026-08-18 16:00 收敛：第一个因子是 **`tests/contract`**

按上面的双因子模型重做二分（目标改成整个 `tests/test_core`，而不是受害文件），四步全部实测复现：

| 步骤 | 前缀集合 | 耗时 | `test_turn_context` 失败数 |
|---|---|--:|:-:|
| 全集 | 九个目录 | 8m41s | **3** |
| LEFT | contract, fixtures, integration, live | 7m02s | **3** |
| LEFT | contract, fixtures | 7m06s | **3** |
| LEFT | **contract** | 7m05s | **3** |

**最小复现：`python -m pytest tests/contract tests/test_core`** → 6 failed（3 条是 DF1 的 bench_gate，3 条是本条受害者）。

> **上一轮同名二分给出的「MINIMAL SET: tests/contract」是巧合，不作数。** 那个脚本的 `Say` 用了 `Tee-Object`——它除了写文件还往管道写，于是 `Say` 的输出混进了判定函数的返回值，让 `if (Fails-With ...)` **恒为真**，二分每步都无条件向左，必然停在第一个元素。它日志里每一行其实都是 `target_failures=0`。**结论碰巧对，过程完全无效。** 记在这里是因为这个坑在 PowerShell 里很容易踩：**函数返回值是「所有未被消费的输出」，不是 `return` 那一个值。**

#### 2026-08-18 17:20 **根因查明**，最小复现 7 秒 · 三个文件

```powershell
# 3 failed
python -m pytest tests/contract/test_agent_context.py `
    tests/test_core/test_lazy_import_budget.py `
    tests/test_core/test_turn_context.py
# 去掉第一个文件 → 9 passed
```

**完整机制**（每一步都已实测，不是推断）：

1. **`tests/contract/test_agent_context.py:17`** 用扁平名导入 `from appserver.agent_context import ...`。这触发 `appserver/__init__.py` 的 `_register_bare_core_alias()`，它执行 `sys.modules["core"] = RxyCode.RxyCode1_1_0.core`——**让两种拼写指向同一个包对象**。这个别名是**故意加的**，注释写得很清楚：防止 bare 与 dotted 两种写法各加载一份、把模块级单例（注释点名了 approval broker）劈成两个。

2. **`tests/test_core/test_lazy_import_budget.py:49`** 执行 `importlib.import_module("core.agent_v2")`（该文件硬编码了六个扁平模块名，用途是烟测 P7 的无环性）。Python 导入子模块时会**把新模块对象绑成父包的同名属性**。而此刻父包就是上一步那个共享对象，于是——

   ```
   sys.modules['core'] is dotted core package : True    ← 第 1 步的别名
   dotted_pkg.agent_v2 is flat module         : True    ← 属性被覆盖
   dotted_pkg.agent_v2 is dotted module       : False
   flat AgentV2 is dotted AgentV2             : False   ← 两个类
   ```

   `sys.modules["RxyCode.RxyCode1_1_0.core.agent_v2"]` 仍指向原来那个模块，但**父包上的 `agent_v2` 属性已经被换成扁平模块**。

3. **`tests/test_core/test_turn_context.py`** 于是同时拿到了两个：
   - 第 14 行 `from ...core.agent_v2 import AgentV2` 在**收集期**执行，走 `sys.modules` → 拿到**点分**模块的类；
   - 第 83 行 `import ...core.agent_v2 as agent_v2_module` 在**调用期**执行，`import x.y.z as w` 走的是 **`getattr(父包, "z")`** → 拿到**扁平**模块。

   桩打在扁平模块上，而 `AgentV2._fast_reply.__globals__` 是点分模块的字典。**桩对被测代码不可见。**

4. 于是 `build_user_message`（`agent_v2.py:5453`）调的是**未打桩的原版**，`captured` 始终为空；执行继续往下走到 `agent_v2.py:5464` 的 `_application_cache_namespace()`，在 `:4040` 摸 `self.model_config`——那是 `_ctx_agent()` 用 `object.__new__` 造对象时没设的属性——抛 `AttributeError`，被 `_run_impl` 的 `except Exception`（`:6472`）吞成一行 warning。测试侧只看得到 `KeyError: 'memory_context'`。

> **这就是为什么「桩没被调用」和「执行走过了那一行」这对看似矛盾的症状能同时成立**——它们发生在两个不同的模块对象里。此前几轮排查反复卡在这个矛盾上，因为默认前提是「只有一个 `agent_v2`」。

**这里有一个比测试失败严重得多的推论，建议单独立项：**

> `_register_bare_core_alias()` 这个**为了防止模块分裂而加的别名，恰恰使分裂能够通过规范名被观察到**。别名建立后，**任何一次扁平子模块导入都会劫持点分父包的同名属性**，而 `from a.b.c import X` 走 `sys.modules`、`import a.b.c as m` 走 `getattr(父包, "c")`——**两种拼写从此指向不同对象**。
>
> 这不是测试专属问题。`appserver/*` 与 `tools/*` 按其 docstring 本来就在用 bare `from core...` 形式，**生产进程里同样会发生**。后果与该 docstring 想防的完全一样：模块级单例（它自己点名的 approval broker）、`isinstance` 判断、`except SomeError` 跨模块捕获，都可能因为「哪种拼写先执行」而静默失效。**建议按「安全相关缺陷」定级，不要当成测试基础设施问题。**

**修法的三个层次**（由窄到宽，建议至少做前两条）：

1. **窄**：`tests/test_core/test_lazy_import_budget.py` 改用规范名（`RxyCode.RxyCode1_1_0.core.*`）。该测试的目的是烟测无环性，点分名同样达标，**没有任何理由必须用扁平名**。这一条就能让九条里的三条转绿。
2. **中**：`_register_bare_core_alias()` 建立别名后，**同时把两种前缀下的子模块 `sys.modules` 条目保持同步**（或改用一个真正的 meta_path finder，让 `core.X` 与 `RxyCode.RxyCode1_1_0.core.X` 解析到同一个 spec），而不是只对齐包对象、放任子模块各走各的。
3. **宽**：全仓统一导入风格，禁掉 bare `from core...`。**这条成本最高且容易在评审里被稀释，不要用它替代前两条。**

~~**未解决的部分**：`test_cache` 那六条是**单因子污染**，与本条机制不同，**尚未定位**。~~　✅ **已于 2026-08-18 23:40 查明，见下条。**

#### 2026-08-18 23:40 **test_cache 六条根因查明**，最小复现 7 秒 · 两个文件 —— **X11 至此完整解释**

二分（`scripts/x11_cache_hunt.ps1`，主检出，跑前无并发 pytest、8765 空闲）四步收敛，每步实测：

| 前缀集合 | 耗时 | 目标失败数 |
|---|--:|:-:|
| 无（对照） | 3s | **0** |
| 九个前置目录全上 | 247s | 9（6 条目标 + 3 条 DF2 的 bridge） |
| contract, fixtures, integration, live | 214s | **0** |
| stress_test, support | 4s | **0** |
| system | 16s | **0** |
| **test_appserver** | 42s | **6** |

**最小前置集合 = `tests/test_appserver` 单个目录**，再缩到文件级只要两个文件、7 秒：

```powershell
python -m pytest -q tests/test_appserver/test_bootstrap_model_selection.py `
                    tests/test_cache/test_model_contracts.py `
                    tests/test_cache/test_no_rework.py::test_git_snapshot_captures_status `
                    tests/test_cache/test_s1_s2_split.py::test_research_not_second_system
# 6 failed, 28 passed in 7.05s
```

**根因是进程工作目录泄漏，与 turn_context 那三条的模块身份劫持是两回事**：

1. `tests/test_appserver/test_bootstrap_model_selection.py:37` **在进程内**调用 `bootstrap.bootstrap_agent(stub=False, workspace_root=tmp_path)`；
2. `appserver/bootstrap.py:33` 执行 `os.chdir(root)`，`root` 是 pytest 临时目录；
3. **没有任何东西还原它**——`monkeypatch.chdir` 会自动还原，但这里是生产代码直接调的 `os.chdir`，pytest 不知情；
4. 此后整个进程 CWD 停在临时目录，`test_model_contracts.py:24` 的 `CATALOG_PATH = Path("config/model_catalog.json")` 是相对路径 → `FileNotFoundError: 'config\model_catalog.json'`（实测 traceback）。

> **和三条那次一样，根因又在生产代码里，不在测试基础设施。** `bootstrap_agent` 的唯一生产调用方是 `appserver/agent_worker.py:452`，跑在每会话独占的子进程里——**在那个位置 chdir 完全合理**，错的是把这个不可逆的进程级副作用放在一个普通库函数里，而签名对此只字不提。
>
> 另需注意 `core/session_runtime.py:209` 的 docstring 明写 *"Persist the active session's cwd atomically **without calling os.chdir()**"*——**本仓早已确立过「不要 chdir」的原则，bootstrap 是漏网的那个**。

**方法论补记**：本条一开始被误判为「需要双因子」，因为 07:00 给出的复现对在 12:44 复核时不复现——**那次复核做在污染环境里（X12）**。干净环境下 07:00 的结论一次就复现了。**双因子只是 turn_context 三条的形状，不要推广到整个 X11。**

**测量可采信性（RM2）**：二分跑前 `commit=a608e5f dirty=28`，跑后 `commit=70054cc dirty=8`——期间有他人提交。已核对 `git diff --stat a608e5f..70054cc` 对本条涉及的全部路径（`appserver/`、`tests/test_appserver/`、`tests/test_cache/`、`scripts/bench_async.py`、`core/bridge/acp.py`）**为空**，且二分首步（40s 处）与末步（42s 处）结论一致，故结论可采信。

**承接**：两个根因与 DF1 / DF2 / X10 已全部落到 [`PHASE-FIX2-PROCESS-GLOBAL-STATE.md`](./PHASE-FIX2-PROCESS-GLOBAL-STATE.md) 的 RL1–RL9 九张卡。本条的六条由 **PHASE-FIX2 RL2**（根因）+ **RL3**（纵深防御）承接；turn_context 三条由 **RL1**（触发点）+ **RL4**（机制）承接。

**RLI-3 扫描记录（RL3 验收命令三，2026-08-19，fix2 @ 788e480）**：`Select-String -Path tests\**\*.py -Pattern 'Path\("(config|core|docs|scripts)/'` 计数 **0**（`Get-ChildItem tests -Recurse` 同样 0）。本卡只修了三个已知受害者；该计数供后续全仓相对路径卡参考。

**RL5 门抓出的历史违规（不在本卡修，owner: backend）**，fix2 @ ea1f5ee：
1. `tests/test_core/test_first_turn_latency.py::test_worker_bootstrap_schedules_prewarm_on_open` — 新增 `core.question` / `core.safety` / `core.safety.approval`
2. `tests/test_core/test_module_identity.py::test_bare_and_dotted_core_submodules_are_one_object[agent_v2-flat_first]` — 新增 `core.agent_v2`
3. `tests/test_core/test_module_identity.py::test_bare_and_dotted_core_submodules_are_one_object[session_runtime-flat_first]` — 新增 `core.session_runtime`

**留下的可复用资产**（都在独占工作树，未跟踪）：`tests/test_core/test_zz_x11_identity_probe.py`（模块身份断言，可直接改造成回归测试）、`x11_trace.py`（`-p x11_trace` 加载的导入追踪插件，能打印任意模块首次导入的完整调用栈与当时的用例 nodeid）、`scripts/x11_bisect*_clean.ps1`。

**这三条有一个共同点，而且是可检验的线索**：它们是该文件里**仅有的三条 `monkeypatch.setattr(agent_v2_module, "build_user_message", _spy)`** 的用例；同文件不打这个桩的三条（`test_zero_blocks_...` / `test_rejects_...` / `test_clear_...`）在合并跑里全过。所以问题大概率出在**打桩目标的模块身份或调用路径**上，而不是 `turn_context` 的业务逻辑。已排除生产代码里存在 `importlib.reload`（全仓仅两处测试内的同名测试函数，非重载）。

> ~~**给下一个人的口径修正**：`§6.5` 那句「12,020 全绿只能说明分批口径下全绿」**仍然成立但要收窄**——现已知合并跑的额外失败是 **3 条**而非 12 条，且集中在一个文件、一种打桩方式上。**不要再按「整套测试结果不可信」来理解这条**，那个说法源于尚未复现的 07:00 观测。~~
>
> ❌ **这条收窄作废（14:50）**：干净房实测九条污染，07:00 的名单是对的。`§6.5` 那句原话**按字面理解即可，不要收窄**。

#### ~~13:00 追加：失败数不随合并规模增长，原「12 → 23」不成立~~　❌　**测量环境已污染，见 X12**

> 「不随规模增长」这半个结论在 14:50 的干净房里**碰巧仍成立**（前 12 目录九条污染），但**它当时的证据是无效的**，且同一段里「稳定在 3 条」那半是错的。**不要引用本段，引用 14:50 那段。**

带 `--tb=long` 重跑**前 14 个目录**：`3 failed, 9247 passed, 3 skipped, 12 分 18 秒`。与前 12 个目录同为 **3 条，同样三个用例**。

07:00 记录的「多合并两个目录就多出 11 个失败，是残留在累积」**未能复现**。那条推论当时被用来解释「为什么整套跑会失控」并外推到 19 个目录——**该外推现在没有证据支撑，不要再引用**。

#### 13:10 追加：真实报错拿到了，是**异常被吞后的降级**，不是断言不成立

三条全部死在 `KeyError: 'memory_context'`——即打的桩 `build_user_message` **一次都没被调用**，而不是被调用后值不对。第一条另有一行 captured log：

```
WARNING  core.agent_v2:agent_v2.py:6485 no-tool fast path failed:
         'AgentV2' object has no attribute 'model_config'
```

`_run_impl` 的 `decision.path == "chat"` 分支把 `_fast_reply` 整个包在 `except Exception` 里，异常只记一条 warning 就返回兜底话术（`core/agent_v2.py:6462-6477`）。所以**测试看到的是"桩没被调用"，真实原因是内部抛了 AttributeError 并被静默降级**。

**这里有一处独立于 X11 的可靠性问题，值得单独记**：这个 `except Exception` 的宽度让「代码抛异常」和「代码正常但走了别的分支」在测试侧长得一模一样。本次要不是 `--tb=long` 带出了 captured log，根本看不到 `model_config` 那行。**任何在这个 except 下面写的测试，失败时都会指向错误的方向。**

**已排除的三条**（静态核对，避免下一个人重走）：`_ensure_session_loaded` 在 `_session_loaded=True` 时是空操作；`_memory_ctx_for_turn` 对社交问候直接返回 `""`；`_prompt_variant` → `_owner_cache_contract` 全程用 `vars(owner)` + `.get()`，不触发属性查找。也就是说 `_fast_reply` 在调 `build_user_message`（`:5453`）之前的四行都不该抛。

#### 13:15 追加：查到一个**同文件双模块**，它本身就是个真缺陷

```
flat   core.agent_v2                       -> D:\...\core\agent_v2.py
dotted RxyCode.RxyCode1_1_0.core.agent_v2  -> D:\...\core\agent_v2.py
same module object : False
same AgentV2 class : False
```

**同一个源文件被加载成两个模块对象，产生两个互不相等的 `AgentV2` 类**，各自有一套模块级全局量。

这会静默破坏三类东西：**`monkeypatch.setattr` 打在其中一个上、代码却在另一个里查找**（正是本条症状的形状）、`isinstance` / `except SomeError` 跨模块失效、以及任何模块级单例/缓存变成两份。

**它不是本次三条的根因，而且我一度拿错了证据。** 原文用「log 行号 `6485` 与实测 `6473` 差 12 行」来佐证双模块，**那条推断是错的**：`core/agent_v2.py` 当时有一处未提交改动恰好是 12 行，而 13:17:31 有人对本仓执行了 `git reset` 把它回退掉了（见下条 X12）。**行号差是文件在测量后被改了，与模块身份无关。**

双模块本身仍是实测事实（上面那段输出可复现），但**它与这三条失败之间目前没有证据链**。

> **不论根因是否落在它身上，双导入都该修。** 修法不是在测试里绕，是让 `RxyCode.RxyCode1_1_0.core.*` 与 `core.*` 解析到同一个模块对象（在 conftest 建立别名，或统一全仓导入风格）。**修之前先读 X12**——在共享工作区里做的任何测量都不作数。

**另外三条被脚本判成「真缺陷」，但那是误判——它们是我自己的排查工具造成的**：

三条全在 `tests/contract/test_bench_gate.py`。实测原因是 **PID 27452（`python -m http.server 8765`，启动于 06:05:12）在一小时后仍占着端口**，触发了本轮给 C8 加的「脏环境拒绝测量」保护。

这个孤儿进程来自 `scripts/bisect_hang3.ps1`：它中途 `Stop-Job` 掐掉 pytest 时，`Kill-Stragglers` 只清理了 `fake_mcp_server` 和 `pytest`，**漏了 pytest 派生出来的 `http.server`**。清掉该进程后原样重跑 → **6 passed**。脚本已修（`Kill-Stragglers` 增加清理 8765 监听者）。

> **但这件事本身暴露了一个该记的真问题**：**任何一次测试运行的非正常终止（Ctrl-C、CI 超时、job 被杀）都会留下 8765 监听者，此后所有 bench 运行都拒绝测量。** C8 的保护是对的（总比谎报 0.0 强，见 PHASE-C 注记），但**恢复手段只有「人去读错误信息里的 PID 然后手动 kill」**。CI 上没人读，就会持续红。建议 C8 owner 考虑在测量前对「确认是自己上一轮遗留的」监听者做一次有据的清理，而不是一律拒绝。
>
> 这也是本轮第二次栽在同一件事上——**第一次是 bench 门自己因端口被占而诬告，第二次是我的排查脚本制造了那个占用**。同一个坑，两个方向各踩一次。

> **2026-08-18 14:55 更正上面这段的归因**：把占用 8765 的东西说成「我的排查脚本遗留的 `http.server` 孤儿进程」**只说对了一半，而且是次要的那一半**。真正的结构性原因见下面 DF1——**8765 就是 RxyCode 自己的默认 API 端口**，谁都不用留孤儿，只要有人在开发机上正常跑着 RxyCode，这个门就红。「清掉孤儿进程就好了」这个处方治不了它。

---

### DF1 · 性能门禁把一次性负载写死在 8765，**与 RxyCode 自己的 API 端口相撞**　✅　**PHASE-FIX2 RL6 结案（动态端口 + 负载未起则抛错）**

`tests/contract/test_bench_gate.py` 的三条失败（合并跑、单独跑都红）根因在 `scripts/bench_async.py:190`：

```python
port = 8765
argv = [sys.executable, "-m", "http.server", str(port)]
```

而 8765 是 **RxyCode 自己的默认 API 端口**——`api_server.py:2165`（`port: int = 8765`）、`main.py:599`（`--api-port` 默认值）、`Dockerfile`（`EXPOSE 8765`）、`config/settings.py` 的 CORS 白名单，全指同一个数。

**因果链**：探针用 `_win_port_listener(8765)` 采「我应该杀掉哪些 PID」，采到的集合里混进了 RxyCode 自己的进程；那个进程理所当然活着；`residual_after()` 恒为真；`tool_timeout_kill_rate` 恒为 `0.0`；阈值 `= 1.0` 判 FAIL；`bench_async.py` 退出码 2；三条测试全挂。

**实测证据**（2026-08-18 14:52，独占工作树）：

```
python scripts/bench_async.py --out ... --rounds 1
  → tool_timeout_kill_rate: 0.0
  → FAIL: tool_timeout_kill_rate: 0.0000 violates = 1.0   (exit 2)

# 8765 上的监听者是谁：
PID 11132 = "D:\Anaconda3\python.exe" "D:\Anaconda3\Scripts\rxycode.exe"
```

**决定性对照**（`scripts/killrate_probe.py`，同机同代码，只把端口换成 `_free_port()` 拿到的空闲口）：

```
probe port = 64081 (8765 holders: [11132])
  round 0: spawned listeners = [28440]  residual after cancel = []
  round 1: spawned listeners = [4468]   residual after cancel = []
kill_rate = 1.0000  (2/2)
```

**所以杀进程的实现是好的，坏的是探针选错了端口。** 这是一次**假失败**，而且是最坏的一种假失败——它诬告的正是「超时能否杀干净子进程」这条安全属性，让人以为进程会泄漏。

**为什么这条对你现在的门禁选择很要紧**：你把合并门定成「全套测试 + 基线达标」。若基线那半直接接 `bench_async.py`，**它会在「开发者本机正好开着 RxyCode」这个最常见的情形下稳定红**，而红的原因与被测代码无关。门禁一旦以这种方式误报，最可能的下场是被人加 `--no-verify` 绕过，那就等于没有门。

**修法（按优先级）**：

1. **别用固定端口**——`socket.bind(("127.0.0.1", 0))` 拿一个内核分配的空闲口。一次性负载没有任何理由要求固定端口号。
2. 若因某种原因必须固定，**至少不能选 8765**，并在测量前断言该端口空闲、否则报「环境不干净」而不是报「kill_rate=0」。**把「探针失效」谎报成「被测属性不达标」，比不测还糟。**
3. `if not target_pids: continue` 这行（`bench_async.py:215`）把「负载压根没起来」和「杀失败」记成同一种结果，也该分开——前者是探针问题，后者才是缺陷。

**补丁已备好**：`D:\agent-demo\d1-bench-port-fix.patch`（103 行，基于 `e47c38a`）。改三处——`_free_local_port()` 用 `bind(("127.0.0.1", 0))` 取内核分配的空闲口；`port = 8765` 改为调它；`if not target_pids: continue` 改为抛 `RuntimeError` 并说明「什么都没测到，因此报不出 kill rate」。**尚未验收**：验证要跑 `tests/contract/test_bench_gate.py`，而当时机器上正跑着 X11 二分，起第二个 pytest 会触发二分脚本的并发护栏。

> **补丁没有直接落进主检出，是故意的**：主检出当时有另一个 agent 的 20 个未提交改动在飞（`frontend/`、`core/session.py`、`main.py` 等）。把修改混进别人正在进行的工作集，正是 X12 那条纪律要防的事。**由 owner 在干净树上 apply + 验收。**

**归属：待认领**（PHASE-C C8 的 owner 最合适，该卡定义了这个门）。

---

### DF2 · `_kill_process_tree` 在 Windows 上 `taskkill` 之后**无条件 return**，兜底永远走不到　✅　**PHASE-FIX2 RL7 结案（校验 + proc.kill 兜底 + 仍活则 error/raise）**

`tests/test_bridge/test_agent_bridge.py` 的三条失败（`test_run_official_agent_timeout_kills` / `test_stop_kills_process` / `test_token_budget_exceeded_kills`，全部 `assert proc.killed is True` 不成立）根因在 `core/bridge/acp.py:25-36`：

```python
if os.name == "nt":
    try:
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)],
                       capture_output=True, timeout=10)
        return          # ← 无条件
    except Exception:
        pass
# 下面的 killpg / proc.kill() 兜底
```

`subprocess.run` **没带 `check=True`**，所以 taskkill 失败只是返回一个非零 returncode，**不抛异常**——`except` 抓不到，代码照样 `return`，底下的 `proc.kill()` 兜底永远没机会执行。而 returncode 从头到尾没人看。

**真实影响面**（不只是测试里的假 PID）：taskkill 会因为权限不足、目标 PID 已被回收、`taskkill` 不在 PATH（精简容器镜像常见）等原因失败。任一情形下，**进程活着，而调用方拿到的是「已清理」的语义**。这正是 `stop()` 文档字符串承诺的「不留僵尸进程」的反面。

**与 DF1 的关系**：两条都关于「杀进程」，但**是两个独立缺陷，别合并**。DF1 是探针选错端口造成的假失败（实现是好的），DF2 是实现里真的少了一条错误路径。今天之所以能分开，是因为 DF1 在换端口后变绿而 DF2 不受端口影响。

**修法**：检查 returncode，非零则继续走兜底而不是 `return`；`proc.kill()` 之后再 `await proc.wait()` 确认回收。注意**不要**改成 `check=True` 就完事——那只是把静默失败换成抛异常被同一个 `except` 吞掉，行为不变。

**归属：待认领**（属 `core/bridge/`，PHASE-C 的 bridge 卡 owner 最合适）。

---

**与 X10 的关系：证据表明是两件独立的事，不要合并。** 前 14 个目录的探测**峰值 fakes=0（无泄漏）却有 23 个失败**；而泄漏要到前 16 个目录才出现。失败比泄漏更早触发、且随规模单调增长，两者的触发条件不重合。先前「很可能同源」的猜测已被这条数据推翻。

**归属：无人认领**，与 X10 同一次排查。

**当前可用的绕法**（已验证）：按目录分批——每目录独立进程 + 独立超时，单个模块卡死不会吞掉整套，且进度实时可读。**具体命令见 §6.5 开头**（原先指向的 `run_batched_tests.ps1` 已被抹掉，那里已改成不依赖脚本的等价写法）。

**归属：无人认领。** 定位需要二分法逐段合并目录复现，是一次独立的排查任务。

**正面做法（这条是对的，独立于 X8 成立）**：完成标记附一条**可当场执行的验证命令**，而不是只留 commit SHA。PHASE-E 是最好的正面例子——**它的七个 SHA 今天全部解析不了，但它的验证命令全部通过**。凭据烂了，东西是好的；如果当初只有 SHA，就没人能证明这一点。PHASE-E 完成表已补该列，建议其余阶段照办。

---

### X13 · PHASE-D 的 §3.5 整节与 D5.5 整卡，正文已被一次有损写入销毁　✅ **已结案（08-18）**

> ## 2026-08-18 结案：重写稿的六条核心判断已逐条查证
>
> 重写完成后没有停在「请 owner 复核」，而是**先去查这些判断在别处有没有独立记载**——能查到的，就不必靠任何人的记忆背书。结果是**六条里五条查到了**：
>
> | 判断 | 独立依据 | 是否需人工确认 |
> |---|---|---|
> | 唯一执行入口收在 `ChildExecutionBridge` | PHASE-D **幸存原文** `:198`；另 PHASE-G 2 处 | 否 |
> | Provider 只共享无状态 client，不复用 session | PHASE-D **幸存原文** `:810`（D5 完成判据） | 否 |
> | MCP / Skill 走 ToolOrchestrator，不另开旁路 | PHASE-4-CD / B / E / G / K 共 20 处 | 否 |
> | `usage` 的 cache 字段拿不到写 `not_reported` | PHASE-4-CD 6 处 | 否 |
> | D5.5 依赖 D5 | PHASE-G 9 处 | 否 |
> | **桥接未完成时返回 `runtime_not_implemented`，不得假 `completed`** | **查无出处**（幸存原文、他文档、代码三处皆无） | **是 → 用户已裁定按此执行** |
>
> **两处幸存原文是关键**：`:198` 的「禁止让子代理直接实例化 `AgentV2` 并调用 `run()`」和 `:810` 的「Provider 可共享的部分只有无状态调用能力，不能共享对话状态」——这两条把重写稿里最要紧的隔离纪律**用原作者的话确认了一遍**。
>
> **第六条是真新增**：代码侧也印证了它无出处（`core/subagents/` 有 14 个文件，但确实没有 `execution_bridge.py`，与桥接未施工一致）。用户当日裁定采纳，理由是**假 `completed` 在测试里和真成功长得一模一样**，所有信号都是绿的，属于最难查的一类 bug。
>
> **两处「待复核」标注已撤除**，PHASE-D 可照重写稿开工。**内容损毁本身仍是不可逆的**——措辞是重写的，这一点永久记录在案；本条结案指的是「重写稿可信、可施工」，不是「原文找回来了」。
>
> 以下为结案前的原始记录。

---

**这条是本轮最重的一项，而且此前没有任何检查会发现它。**

`PHASE-D-ISOLATED-SUBAGENT.md` 里有 49 行正文的中文被替换成了字面问号。不是乱码——文件是合法 UTF-8，没有一个 U+FFFD，markdown 结构完好，代码块和英文标识符一字未损。丢的恰恰是只有人才读的那部分：

```
### D5.5 ? ???????ChildRuntime ? Provider/Tool?
`P0` / 16?24h / ?? D5 / **owner: backend**
**??**?? D5 ??? Runtime ???? AgentV2/Provider/Tool ?????
1. ?? `core/agent_v2.py`?`core/session.py` ??????????? Primary ????
- [ ] `TaskResult.status=completed` ?? AgentV2/Provider ????????
```

**损毁范围**（`python scripts/doc_audit.py --check C7` 可复现）：

| 位置 | 内容 | 行数 |
|---|---|--:|
| `:409-487` | **§3.5 执行桥设计规范全节**（3.5.1 定位 / 3.5.2 调用链注解 / 3.5.3 契约说明 / 3.5.4 权限与 MCP/Skill / 3.5.5 十一条完成判据 / 3.5.6 与 flag 的关系） | 24 |
| `:807-845` | **D5.5 整卡**（标题、背景、七条操作步骤、八条完成判据、备注） | 23 |
| `:1072-1073` | 出口判据两行 | 2 |

代码块内的 `ChildExecutionBridge` Protocol 签名、调用链 text 图、`ChildRuntime.execute()` 示例**完好无损**——这正是有损写入的特征：它只吃非 ASCII。

**损毁只此一份文档。** 初筛时 PHASE-F `:1807-1808`、PHASE-G-DESKTOP `:2477`、PHASE-H `:942-946` 也命中过同一模式，逐条看过是**评测结果表的待填占位符**（`team ??% ??,??? ?.?x`），不是损毁——C7 因此豁免代码块内的行。

**为什么不可恢复**（三条路都验过了）：

1. **git**：`PHASE-D` 从未进过版本控制。`git log --all -- <该文件>` 无输出；`3fcec9b` / `eb0633d` / `83aa025` 三个历史点里 `git cat-file -e` 全部报不存在——文件是在计划文档被移出索引**之后**才创建的（见 X14）
2. **归档**：`docs/plans/opus5-plan.rar`（1.6 MB，08-10）解出 132 个文件，`PHASE-D*.md` **零命中**
3. **同源文档**：`2026-08-13-phase-f-expert-team-open-ecosystem-design.md` 只有 D5 的一行摘要，没有 D5.5

**影响**：D5.5 是 `P0` / 16–24h / 前置 D5 的卡，`PHASE-G-DESKTOP:2105` 还把 `core/subagents/runtime.py` 列为 B5/B6/B7 的硬前置。施工者拿到的是一张只有文件路径、没有任何要求的卡——**它不是「写得不清楚」，是根本没有内容可读**。§3.5 与 D5.5 互为设计与施工，两边同时没了，连交叉参照都做不到。

**处置：已于 2026-08-18 17:5x 重写完毕**，`python scripts\doc_audit.py --check C7` 归零。

重写覆盖 §3.5 六个小节（24 行 → 87 行）、D5.5 整卡（23 行 → 41 行）、D14 出口清单第 11–12 条（2 行）。依据是幸存的代码块（`ChildExecutionBridge` Protocol 签名、调用链 text 图、`ChildRuntime.execute()` 示例）、四个文件路径，以及 D5 / D7 / D9–D12 的既有约束与 `PHASE-G-DESKTOP:2105` 的前置声明——**这些约束足以定死技术内容，但定不死原作者的措辞**。

⚠️ **仍需一次人工复核，这是本条唯一的遗留项。** 两处重写段落卡首都挂了醒目声明，写明「是重写不是原文、有出入以此为准、不要两套并存」。复核要点：

1. §3.5.3 的隔离清单（哪些能共享、哪些不能）是否与你理解的 D5 边界一致
2. D5.5 操作步骤第 7 条「删掉 placeholder summary 兜底」是否确为原意——它是整张卡的靶心，原文只剩 `??????????????????? placeholder summary ???`
3. §3.5.5 的十一条判据条数与原文一致（原文残骸可数出 11 个 `- [ ]`），但**每条的具体措辞是重构的**

**归属：PHASE-D owner 复核**（不再是「无人认领」）。

**防复发**：`scripts/doc_audit.py` 的 C7 已把这类损毁做成阻断项。它专挑「合法 UTF-8 但中文变问号」这个签名，是唯一能在没有原文对照的情况下认出有损写入的办法。**任何往这些文档写字的工具，都必须显式指定 UTF-8**——本轮我自己就两次踩到同一个坑（`doc_audit.py` 的 GBK `UnicodeEncodeError`、PowerShell `>` 重定向出 UTF-16LE 补丁），说明这不是一次意外，是这台机器上的默认行为。

---

### X14 · 21 份计划文档 + 9 份验收证据不在版本控制内，S6 的 `[x]` 已经回归成假　✅ **已解决（08-18）**

> ## 2026-08-18 结案：病因诊断错了一半，且已修复
>
> **用户澄清了 `.gitignore:141` 的动机：那是刻意的，他不想把计划文档推到 GitHub。** 所以「把它们加回主仓」从一开始就是错误的处方——它解决的是版本控制，却违背了不上传的意图。而这两件事本来就不冲突。
>
> **然后发现了更要紧的事：`docs/plans/opus5-plan/` 早就有一个纯本地 git 仓。** 建于 2026-08-08，首次提交信息白纸黑字写着 `chore: initial local snapshot of opus5-plan (never pushed)`，无 remote。**用户想要的方案，十天前就已经建好了。**
>
> **真正的问题是它从 08-08 起再没提交过。** 实测未跟踪 78 项、已修改 20 项，其中包括：
>
> - **全部核心 PHASE 文档**（C/D/E/F/G/H/I/J/K/L/M/N），一份都没进去
> - 全部 15 份 evidence（含四份用户签字的验收记录、三份 benchmark 基线 JSON）
> - 全部 research 笔记，以及用户提供的 26 张 WorkBuddy / Codex 截图
>
> **所以 X13 的销毁是这个空档的直接后果**：PHASE-D 的 §3.5 与整张 D5.5（49 行）被一次有损写入抹掉时，仓里根本没有它的任何版本——不是回滚失败，是**压根没得可回滚**。
>
> **处置**（三步，均已实测）：
>
> 1. **补提交**：101 份文件一次性入库（`beb340e`），已跟踪总数 110，工作区归零。**主仓 `.gitignore:141` 一字未动，这些文件对 GitHub 依然不可见。**
> 2. **加 pre-push 硬闸**：本库无 remote 本就推不出去，钩子是第二道锁，防止日后有人不明就里地加上 remote。
> 3. **实测验证**：建临时本地裸仓当靶子推一次，**确认被拒（exit 1）**。
>
> **步骤 3 抓到一个不测就发现不了的坑**：第一次推送**成功了**——钩子根本没跑。原因是 **Cursor 全局设置了 `core.hooksPath=C:/Users/Administrator/.cursor/git-hooks`，仓内 `.git/hooks/` 被整体旁路**。已对该仓单独设 `core.hooksPath=.git/hooks` 恢复，重测确认拦截。
>
> ⚠️ **这条对本仓同样成立**：**任何写进 `.git/hooks/` 的钩子在这台机器上默认都是死的**，写了不等于生效。后续若有卡依赖 git 钩子做门禁，必须照上面的方式实测，不能假定它在跑。
>
> **仍需注意**：`core.hooksPath` 存在 `.git/config` 里，**不随仓库分发**。换机器或重新 clone 后要重设。本库无 remote、本就不会被 clone，此处仅作备忘。
>
> 以下为 08-18 结案前的原始记录，保留以备追溯。

---

**`00-EXECUTION-PLAN.md:840-842` 的 S6「让计划文档进版本控制」三条判据全打了 `[x]`，还附了 commit message。现在跑它自己的验收命令，第一条就不过：**

```powershell
git check-ignore -v "docs/plans/opus5-plan/rxycode/00-EXECUTION-PLAN.md"
# S6 期望：无输出
# 实测：.gitignore:141:docs/plans/   <该文件>       exit=0
```

**完整时间线**（`git log` 可查）：

| 提交 | 日期 | 做了什么 |
|---|---|---|
| `83aa025` | 08-06 | S6 生效，计划文档入库 |
| `eb0633d` | 08-07 | **`chore(git): untrack dev plans from index (local-only, never pushed to GitHub)`** |
| `4eda972` | 08-09 | `Delete docs/plans directory` |
| — | — | `.gitignore:141` 重新加回 `docs/plans/` |

**先说清楚：08-07 那次是有意决策，不是事故。** commit message 写明了理由——内部计划不上 GitHub。这个诉求成立，本条**不主张**把它们推到远端。

**但代价是实打实的，而且已经兑现了两次**：

1. **X13 的 51 行正文永久丢失**，就是因为没有任何历史可回滚
2. **X12 那次「工作区被并发改动、`git reset` 悄悄回退了源文件」之所以查了半天**，也是因为这批文档处在 git 视野之外——改了没记录，回退没痕迹

现状是：所有 PHASE-A 至 PHASE-N、`00-EXECUTION-PLAN.md`、本表、`README.md`（共 21 份，约 3.7 万行）**没有变更历史、没有 diff、没有备份、没有评审入口**，仅有的一份 `.rar` 快照停在 08-10 且不含 PHASE-D。唯一在库的是 `PHASE-FIX.md` 与 `PHASE-4-CD` 等 10 份早期文件。

**08-18 追加：同一条规则还吞掉了验收签字记录，这是比文档丢失更麻烦的一类。**

`docs/plans/opus5-plan/rxycode/evidence/` 下 19 份证据，**10 份已跟踪、9 份被 `.gitignore:141` 忽略**——注意是「忽略」不是「漏加」，所以 `git status` 里**根本看不见它们**，不会有任何提示。被忽略的九份是：

| 文件 | 是什么 |
|---|---|
| `a10-acceptance.md` / `a10b` / `a11` / `a12` | **四份验收签字记录**，`PHASE-A:1554` 那条 `[x]` 的签字依据就是 `a10-acceptance.md` |
| `bench-async-I.json` / `.baseline.json` | 异步基准的实测值与基线 |
| `c8-benchmark-record.md` / `c4-default-switch-event-comparison.md` | C8 / C4 的验收记录 |
| `protocol-baseline-commit.txt` | 协议基线的 commit 锚点 |

**「10 跟踪 + 9 忽略」这个混合状态比全不跟踪更危险**：目录在 git 里看着是有的，`git log` 也能查到东西，于是没人会怀疑另外九份正悬在版本控制之外。一次 `git clean -xfd`，用户显式签字的 P0 验收凭据就没了，而且不会有任何报错。

顺带解释了本表 §6.5 那批排查脚本为什么会被一次 checkout 带走——**同一个根因，不同的目录**。

**处置建议**：`docs/plans/` 整目录保持不推远端的前提下，仍可以进版本控制——最直接的是 `git add -f` 加一个本地专用分支，或把这批内容拆到独立的私有仓/子模块。**这是本条唯一需要使用者定夺的地方**，因为它牵涉「内部计划不上 GitHub」这条原始诉求怎么落地，不该由施工者替你选。

**处置**：需要一条既满足「不上 GitHub」又留下历史的办法，且**必须在继续大改这批文档之前定下来**——本表和 PHASE-M/N 每天都在增删几百行，每多写一天，可丢的东西就多一天。可选项（本表不替使用者做主）：

- 本地独立仓库（`git init` 在 `docs/plans/`，不加 remote）——最贴近 08-07 那次决策的原意
- 主仓私有分支，不 push
- 定时归档快照，把 `.rar` 那套做成自动的

**同时要做的是把 S6 的 `[x]` 改掉**——它现在是一条**会误导人的完成标记**：任何人读到「计划文档已进版本控制 ✅」都会以为改坏了能回滚。这正是 X8b 那条「完成标记要附可执行验证命令」想防的情形，而 S6 讽刺地**附了**验收命令，只是没人再跑第二遍。

**归属：无人认领。**

---

### X15 · `G1–G8` 与 `M1–M8` 在两份文档里各指两套完全不同的卡　⚠️

`scripts/doc_audit.py --check C4` 查出 18 条卡号重复，去掉误报后是三组真撞车：

| 卡号 | 一边 | 另一边 |
|---|---|---|
| `G1`–`G8` | `00-EXECUTION-PLAN:1095+`　评测卡（G1 = 修复坏掉的评测任务） | `PHASE-G-DESKTOP:816+`　桌面卡（G1 = Desktop 基线与包边界冻结） |
| `M1`–`M8` | `00-EXECUTION-PLAN:2445+`　Phase 3 模型卡（M1 = 现状盘点） | `PHASE-M:748+`　GUI 卡（M1 = PHASE-G 勘误） |
| `D1` / `D2` | `PHASE-D:670,694`　子代理卡 | ~~本表的缺陷编号~~ → **已于 08-18 改名 DF1 / DF2** |

**第三组是本表自己造的**，而且本表 `:755` 早就写过「注意 `D1-D8` 是主计划 Phase 4，别改错」——写下警告的人和踩进去的是同一个。已改，不再赘述。

前两组是历史遗留，**不建议改名**：`00-EXECUTION-PLAN` 的 G/M 两批多数已完成，卡号写进了 commit message 与 evidence 文件，改名会让历史凭据失效。**改用限定引用**：跨文档提到这些卡号时必须带文档名（`PHASE-M M1`、`主计划 M1`），单独写 `M1` 只在本文档内有效。

**为什么这不是小事**：`PHASE-M M1` 的内容是「改 PHASE-G 的十四处勘误」，主计划 `M1` 是「模型层现状盘点」。施工者按 §0.2 的规矩「只读本卡」，拿到一句无限定的「先做 M1」，两种读法都讲得通，而做错的那种要到验收时才暴露。

**归属：无人认领**（限定引用规则需要写进 `README.md` 的阅读约定）。

---

### X16 · **三份 PHASE-G 的章节号都重复了两到三遍**，405 处「见 §N」因此不唯一　⚠️

**三份文档都中招，不是 DESKTOP 一家的毛病**：

| 文档 | 重号数 | 形状 | 内部引用 |
|---|--:|---|--:|
| `PHASE-G-DESKTOP.md` | **11 / 12** | 主链 + 一页速览 + 增强批，**三套编号** | 248 |
| `PHASE-G-BACKEND.md` | 8 | 正文（`:47-705`）+ 交接附录（`:812` 起）两套 | 46 |
| `PHASE-G-FRONTEND.md` | 8 | 同上 | 40 |

再加上其他文档指向 PHASE-G 的 **71 处**（PHASE-M 35、PHASE-N 17、本表 8、README 4，余下 7 分散），**合计 405 处引用，每一处都要靠上下文猜是哪一套编号**。

DESKTOP 最严重——增强批（GX）从 `## §0 增强批总则` 起把章节号从头重编，中间还夹了一套「一页速览」的编号，于是 **12 个号里 11 个重复，`§0`–`§4` 各出现三次**：

| 号 | 出现三次的 | | |
|---|---|---|---|
| `§0` | `:74` 执行手册 | `:2066` 一页速览 | `:2338` 增强批总则 |
| `§1` | `:161` 为什么需要新的 Phase G | `:2078` 必读文档清单 | **`:2376` 通用规范限制** |
| `§2` | `:236` 产品定义 | `:2093` 前置条件自检 | `:4383` GXn-PROTO 登记机制 |
| `§3` | `:333` 整体架构 | `:2129` 分工与文件边界 | `:4403` 追加阶段出口标准 |
| `§4` | `:452` 数据模型 | `:2161` Git 分支与提交 | `:4430` 排期与并行 |

`§5`–`§10` 各两次。**唯一不重号的是 `§11`。**

**已经差点出事一次**：`PHASE-M` 的 **M1**（P0 纯文档卡，全部工作就是精确改字）通篇写「把映射规则写进 PHASE-G `§1`」，而三个 `§1` 里最像目标的其实是错的那个——`§1 必读文档清单`听起来正该收录一条路径规则，但真正的目标是 GX 批的 `§1 通用规范限制`（勘误二举例的 `12. 基线执行规则` 在那节）。**2026-08-18 已给 M1 / M2 补上锚点说明与一条反向判据**，但那只挡住了这一张卡。

**处置建议**（本表不替使用者做主，但有默认倾向）：

- ❌ **不建议重编号**。405 处引用会一起失效，且 M1 的勘误二特意保留原编号括注就是为了不打断「见 §1 第 N 条」这类引用——重编号等于把它想防的事做一遍
- ✅ **建议改为「引用必带标题」**：写 `§1 通用规范限制` 而不是 `§1`。这与 M1 §7.4.1 已经在用的「按定位锚点搜索、禁止行号」是同一条纪律，只是把它从「定位手法」升成「书写规范」
- 落点：写进 `README.md` 的阅读约定，与 X15 的「跨文档引用卡号必带文档名」并列——**两条是同一个毛病的两个面：标识符在局部唯一，被当成全局唯一来用**

**归属：无人认领。**

---

### X17 · `PHASE-G-FRONTEND` 的 12 行依赖用的是一套已废弃的卡号，44 处引用全部指不到　🛑

**PHASE-G 前后端卡在某次改名后，依赖声明没跟着改。** 现在的卡叫 `PhaseG-H2` / `PhaseG-B2`，但依赖行里写的还是旧名 `J2` / `DB2`：

```
### PhaseG-H13 · 前端打包、发布 UI 与发布流程
`P0` / … / 依赖 J2、J3、J11、J12 和后端 DB13 / …
                 ^^^^^^^^^^^^^^^^^^^^^^^^^^^  五个 ID，一个都不存在
```

**规模**：12 行依赖、**44 处引用、24 个唯一 ID**（`DB2`–`DB13` 十二个 + `J1`–`J12` 十二个）。覆盖 `PhaseG-H2` 到 `PhaseG-H13` —— **主链前端卡从头到尾没有一张的依赖是能解析的**。

**映射是确定的，不是猜的**：逐卡比对标题后，`DBn` → `PhaseG-Bn`、`Jn` → `PhaseG-Hn` **十二组全部语义吻合**，抽三组为证：

| 依赖写法 | 实际指向 | 前端卡自己的标题 | 对得上吗 |
|---|---|---|---|
| `DB2` | `PhaseG-B2` 「Protocol handshake、能力、错误」 | H2「Protocol-client 握手、能力和错误投影」 | ✅ |
| `DB12` | `PhaseG-B12`「Notifications、定时任务、恢复、replay」 | H12「Notifications、定时任务、恢复和离白视觉系统」 | ✅ |
| `J11`/`J12` | `PhaseG-H11`/`H12` | H13「前端打包、发布」依赖设置页与通知先完工 | ✅ |

**`J1`–`J6` 这六个比其余十八个更危险，因为它们不会报错。**

`PHASE-J-PERSONA-AGENT-INTERFACE.md` 里**真的有 `J1`–`J6` 六张卡**（PersonaAgent 接口预留）。所以「`PhaseG-H2` 依赖 `J1`」在任何自动检查里都会**解析成功**——只不过解析到了 PersonaAgent 的 J1，而不是它真正要等的 `PhaseG-H1`「Desktop 基线与前端包边界」。**一个前端壳的依赖被静默接到了一张与它毫无关系的接口预留卡上。** 施工者照着排期走，会以为 H2 要等 PHASE-J，而 PHASE-J 按 README 是「无硬前置、六天、插进 D/F/G/H 里做」的附录——排期会当场错乱。

这是 [X15](#x15) 那条「标识符局部唯一、被当全局唯一使用」的第二次现形，也是**第一次造成静默错误而非报错**。本表 08-18 新增的 C9 检查最初也没抓到这六个，正是因为它们「有解」。

**处置：已于 2026-08-18 执行完毕**，见 [`PHASE-M-GUI-BASELINE-CAPABILITY.md`](./PHASE-M-GUI-BASELINE-CAPABILITY.md) 的 **M1b**（含实施记录）。12 行依赖全部改写，`--check C9` 退出码 0，差异恰好 24 行、无标题与判据改动。

不并进 M1——M1 自己的规范限制写着「除这十四处外，PHASE-G 与 README 无其他改动，逐行核对」，往里塞第十五项会直接违反它的判据。

**顺带验证了 X14 的一个具体代价**：M1b 原本的判据是「`git diff` 只出现依赖行」，实际执行时发现 `PHASE-G-FRONTEND.md` **不在版本控制内**，`git diff` 返回空，只能改用改前备份做 `Compare-Object`。**在 X14 解决之前，任何 PHASE-* 文档的「用 git diff 验收」都是写不出来的判据。**

---

### X20 · 两张 `P1 / 5d` 的卡没有完成定义　✅

按「卡里有没有说过什么叫做完」扫全部 **305 张施工卡**，两张没有：

| 卡 | 规格 | 状况 |
|---|---|---|
| `PHASE-F F15 · 文档` | `P1 / 5d / 依赖 F1–F14` | 有 4 步操作（含 9 个子项），**无验收命令、无完成判据** |
| `PHASE-H H12 · 文档` | `P1 / 5d / 依赖 H1–H11` | 有 4 步操作（含 6 个子项），**无验收命令、无完成判据** |

**这类卡的隐蔽之处在于它看上去很完整**：有优先级、有工时、有依赖、有细到子项的步骤列表。缺的东西只在最后一刻才显形——**写的人不知道什么时候可以停，复核的人不知道凭什么签字。** 两张各 5 人日，合计 10 人日没有完成定义。

两张都夹在文档中段（F15 后面还有 F16–F18，H12 后面还有 H13），所以 Phase 级的出口检查也覆盖不到它们。

**处置：已于 2026-08-18 补齐**，判据与验收命令**全部由各卡自己的步骤逐条推出，没有新增任何要求**。两处都标注了补写日期与本登记号。补写时各强调了一条原卡已写、但容易被当成装饰的要求：

- **F15**：「什么时候不该用多 Agent」必须独立成段——那是 F14 整轮评测唯一对外的产出，混在正文里等于没做。
- **H12**：`config/model_pricing.py` 的维护责任要写明**责任人与周期**。这是本卡唯一**会自然过期**的交付：别的文档写错了会被人读出来，**定价表过期没有任何症状，只会安静地把成本算错**。

**已做成机械检查 `C10`（cards define done）**，防止再出现。它跳过 73 个卡形但非施工的编号（`X*` 审计条目、`DL*`/`DM*`/`DN*` 设计决策、`OV*` 裁定、`MC*`/`NC*` 纪律表等），也豁免「拆成 A/B 两半」的容器卡（如 `PHASE-L L0`，工作在 L0a/L0b 里）。**反向验证过**：把 PHASE-F 的判据表述全部抽掉，它报出 18 张——不是空转。

---

### X19 · 裸写的 `L0` / `L1` 有三个互不相干的含义　✅

建需求追溯表时，检索工具把 `PHASE-K:280` 的 `#### L1 的代价` 当成了一张卡。它不是。顺着查下去，`L1` 在这套文档里同时是三样东西：

| 含义 | 出处 | 说的是什么 |
|---|---|---|
| **能力层级** | `PHASE-K:280`（`#### L1 的代价`），及 K 全文的「L0 不改前缀 / L1 会话边界生效」 | 能力项对前缀缓存的影响分级 |
| **施工卡** | `PHASE-L:833`（`### L1 · PHASE-F 的两处收口`） | PHASE-L 的一张卡 |
| **路由索引层** | 全线 29 处「L1 摘要 / L1 索引 / L1/L2」 | 两级路由索引的第一级 |

`L0` 同样三义：K 的能力层级 L0、PHASE-L 的绝对基线门 `L0`（已拆成 L0a/L0b）、路由索引的 L0。

**为什么要登记**：这三者**跨文档同时被引用**——PHASE-L 的 L0b 要守命中率，靠的正是「团只走 L1 索引不进前缀」，而 PHASE-K 判断某能力能否默认开，靠的是「它是不是 L0」。一句「L1 会破坏缓存吗」在三种读法下答案完全不同（层级 L1：会，且是设计如此；卡 L1：不适用；索引 L1：不会，这是它存在的理由）。**这不是笔误，三种用法各自都是对的**，问题只在裸写时读者无从分辨。

**处置**：不改任何一处现有命名（三者都已深度嵌入各自文档，改名的连带风险远大于收益），改为**在 README 的引用约定里加一条**：跨文档引用 `L0`/`L1` 必须带限定词——「能力层级 L1」/「PHASE-L L1 卡」/「L1 摘要索引」。同文档内沿用本地含义即可，无需啰嗦。

---

### X18 · Phase K 的验收闸门要求「四组门禁全绿」，而它自己的阈值表只有三行　✅

`K21` 是 **整个 Phase K 的验收闸门**，也是 multi-agent 默认值翻转（DK1）的执行点。它的完成判据写着：

```
- [ ] 四组命中率门禁全绿：97% / 97% / 95% / 95%
```

同一句在 §「Phase K 完成的定义」第 4 条又出现一次。但**同一张卡里的阈值表只有三行**（仅 multiagent 97% / +多模态 95% / +LinkAgent ≥95%），正文还明写「这**三个**组合全是 L0」。

**四个数字、三行表、零处说明第四组是谁。** 从 §3.2 的推导反推，第四组只能是「全关」对照组——`97% / 97%` 的前两个分别是「全关」和「仅 multiagent」，它们相等正是本卡要证明的结论（L0 能力不改前缀，所以开与不开命中率应当一致）。**但这层推理从未落到纸面。**

**为什么这条比看上去严重**：施工者拿到一张写着「四组全绿」的判据和一张三行的表，最省事的读法是「表里三组 + 随便再跑一组」，而**恰恰是那个没写出来的「全关」对照组，才是「能力全开不掉命中率」这个核心承诺唯一的比对基准**。少了它，另外三个数字只是三个孤立数值，证明不了任何东西。

**处置：已于 2026-08-18 修完。** 阈值表补成四行并编号（第 1 行「全关」标注为本卡推导、其余三行标注「用户硬线」），两处判据都加上「按第 1→4 行顺序」的读法说明，正文「这三个组合」改为「第 2–4 行」并补出设对照组的理由。**用户的三条硬线数值一字未动。**

顺带核对了基线数字在全线的一致性：`PHASE-L:95-97`（CLI）、`PHASE-M:175-177`（GUI）、`PHASE-K` 阈值表三处的三档口径**完全一致**（97 / 95 / 95），延迟契约（简单 1s、复杂首字 3s）亦然。**唯一的偏差是 F14 的 `cache_hit_floor` 仍是 85%，但那条 PHASE-L 已在 `:772` 登记并由 L0a/L0b 接管。**

---

### X9 · 下游的覆盖裁定，施工者结构性地读不到　✅

这条最隐蔽，值得单独说清楚。

**PHASE-FIX §0.2 的规则明令**：「**不读整份施工文档**，只读本卡 + §0 + §4」。这是为了控制上下文，本身是对的。

**但 PHASE-G 全文零处引用 PHASE-K / PHASE-L / PHASE-M**（grep 确认），而这三份各自声明覆盖了 PHASE-G 的结论：

| 覆盖裁定 | 出处 | 覆盖了 PHASE-G 的什么 |
|---|---|---|
| **OV1** Desktop 主写模型改 Grok 4.6 | `PHASE-M:95` | `PHASE-G:70-72`「所有卡的实现者默认是 Composer」 |
| **OV2** 桌面端解禁极简模式 | `PHASE-M` §3 | `PHASE-K K20` 原本的禁止 |
| **OV3** GUI 纳入绝对基线门 | `PHASE-M` §3 | PHASE-G §10 完全没有性能出口 |
| **DM2** 设置页四组容器 | `PHASE-M:456` | GX26 的「8 分区职责冻结」 |
| **HN2** B14 工具面收成常数 | `PHASE-N` §6.4 | B14 必须实现第 3 条 |

**照 PHASE-G 原文开第一张卡就会违规**，而施工者按 FIX 的规则根本不会读到这些。

**归属：本表 §2 就是这份索引**，并已在 PHASE-G 顶部加了指向本表的注记。M1 原本只负责 OV1 那一条脚注。

---

### X22 · 同一个 commit 上出现两个互不相容的测量结果　待定夺

**发现时机**：2026-08-19 复核 `fix2` 是否可合入 master 时。

**分歧**：两次测量都声称跑的是 `fix2 @ 45df39f` 的 §5 出口，结论相反。

| 出处 | 结论 |
|---|---|
| README 计划表原记录（另一执行者） | 「零 error，**仍余 6 failed**」——3 条 stall + **3 条 credential `icacls` GBK 解码** |
| 本次复核（2026-08-19 下午，`D:\agent-demo\RxyCode\RxyCode-fix2`，开跑前确认 `concurrent_pytest=0`、`dirty=0`） | 五目录门禁 `8881 passed / 0 failed / 0 error`；**全套 `12063 passed / 0 failed / 0 error / 11m53s`** |

**倾向**：本次复核可信度更高——它满足 X12 立的三条纪律（独占目录、开跑前确认无并发、记录 commit 与 `git status`），且**全套跑**比五目录跑覆盖更广，仍是零失败。原记录里的「credential `icacls` GBK 解码」看形态是**控制台代码页相关的环境敏感失败**，很可能随 shell 的 code page 变化而出现或消失。

**为什么单独登记而不是直接改掉**：这是本轮第二次出现「同一 commit、不同结论」（第一次是 X12 的脏工作区）。**两次都不是代码问题，是测量口径问题。** 直接覆盖掉原记录，等于把这个模式抹平——而它正在反复发生。

**待定夺的是**：要不要把「测量必须记录 console code page / locale」补进 PHASE-FIX2 §0.3 的 RM 纪律。**若那 3 条 credential 失败确实是代码页导致的，那它就是一类会随环境静默出现的假红**，性质与 DF1（端口冲突导致的假红）完全相同，而 DF1 是被当作真缺陷修掉的。

---

### X21 · RL4 只统一了 `core`，把 `protocol` 等五个包从「碰巧一致」翻成「确定不一致」　已归属

**发现时机**：2026-08-19，`fix2` 分支 RL1–RL9 全部审计 PASS 之后、跑 PHASE-FIX2 §5 出口门禁时。

**归属**：[`PHASE-FIX2-PROCESS-GLOBAL-STATE.md`](./PHASE-FIX2-PROCESS-GLOBAL-STATE.md) 的 **RL10**（扩身份统一 + 删 `core/session.py` 双写法回退）与 **RL11**（RL5 的门改判同一性）。根因详述在该文件 §1.6。

**两侧实测对照**（五目录合并跑，同机、无并发）：

| 分支 | 结果 |
|---|---|
| master `5e8e7b2` | `3 failed`，全在 `tests/test_bridge/test_agent_bridge.py` 的杀进程三条（即 DF2） |
| fix2 `fb92730` | `5 failed + 2 errors`，全在 `tests/test_core/test_session.py`；master 那三条**已转绿** |

**结论有两层，第二层比第一层重要：**

1. **RL7 确实修好了 DF2**，但 fix2 **净新增五条 master 上没有的失败**，`fix2` 因此**不得合入 master**。
2. **这不只是「RL4 没做完」。** `protocol` 的分裂在 RL4 之前就存在，只是被 `core/session.py` 的 `except ImportError` 回退盖住了——也就是说，**生产进程里 `isinstance(x, FinalAnswer)` 是否成立，一直取决于 `appserver` 有没有被 import 过**。RL4 只是让它第一次可见。这是 RLI-2 要禁的东西，换了个包名。

**为什么 RL4 的验收没抓住**：RL4 验收命令第三条把 `tests/test_appserver` 与 `tests/test_tools` **各自单跑**，从未与 `tests/test_core` 合并跑。这恰好踩中 PHASE-FIX2 §5 自己写下的「分批跑绿证明不了任何事」。**卡的完成判据写窄了，实现严格满足了判据。**

**连带修订**：PHASE-FIX2 §5 出口新增第 3 条「与 master 的净差为非负」。理由是原出口只看本分支的绝对失败数，**无法区分「没修干净」与「修好一批又打坏另一批」**——这次正是后者，而两者的处置完全不同。

**附带发现（同归 RL11）**：RL5 的门查的是裸 core 键的**存在性**而非**同一性**，在 RL4 装了 finder 之后会误伤 RL4 自己的身份测试。RL5 的实施记录把这三条登记成了「历史违规」，**该定性是错的**，已在 PHASE-FIX2 就地更正（原记录保留）。

**另记一笔（不归 X21，供排期参考）**：截至 2026-08-19，主工作树已切到 `feat/phase-f-expert-team`，**PHASE-F 已开工**，其首个提交 `e48017b` 删除了 `tools/agent_tool.py`。这意味着实际执行顺序偏离了既定的 **FIX2 → F → G** 合并次序。后果之一是文档审计在该分支上出现 6 条 C1 阻断（五份文档仍按「`tools/agent_tool.py` 存在、待迁移」描述），**该文件在 master 上仍存在**，故这批阻断是 F 施工中的预期漂移，不是文档缺陷；等 F 的迁移卡收尾时一并更新描述即可。

---

## §2 「PHASE-G 已被下游覆盖」索引

> **这一节是给施工者的。开 PHASE-G 任何一张卡之前，先看你那张卡在不在下表。**

| PHASE-G 的原始规定 | 被谁覆盖 | 现在以什么为准 |
|---|---|---|
| §0.2「实现者默认是 Composer 2.5，Grok 4.5 只做视觉辅助」 | `PHASE-M` **OV1** | **Grok 4.6 主写 Desktop**；能力边界约束（不绕协议 import Python、不在 Renderer 做权限判断）仍有效 |
| §10 四类出口 43 条，**零条**性能指标 | `PHASE-M` **OV3** + M0a/M0b/M0c | GUI 纳入绝对基线门，**卡级门**（首字目标 1s/3s、下限 2s/5s、命中率下限 95%、GUI 层开销 ≤150ms） |
| GX 卡的 `src/features/<name>/` 路径 | `PHASE-M` **M2** | 映射到 `src/renderer/src/` |
| **后端 `appserver/handlers/<x>.py` 路径（20 处）** | `PHASE-M` **M2**（08-18 扩容） | 映射到 **`appserver/<x>_routes.py`**，沿用 `model_routes.py` / `subagent_routes.py` 命名。**不建 `handlers/` 子目录**，M2 验收命令内有反向断言 |
| **GX28「本卡无协议扩展、无需 PROTO 登记」** | `PHASE-F` **F18b**（08-18 新增） | 五个 `team/*` 方法由 F18b 交付；GX28 改为消费方，须加注记指向 F18b |
| **GX24-PROTO 把 `plugin/toggle` 登记为 `new_method`** | `PHASE-K` **KC6** + §3.3 注记 | **不新增方法**，由 `capability/set` 提供；另补第七个方法 `plugin/search`（DK4 追补） |
| **`/team` 语义（PHASE-F 带参路由 vs GX28 无参选择器）** | `PHASE-N` **N8**（08-18 裁定） | **按参数分流**，两种语义都保留；消歧为**团名精确匹配**，未命中即当任务描述 |
| GX26「设置页 8 分区，职责冻结」 | `PHASE-M` **DM2 / M5** | 四组容器（个人 / 集成 / 编码 / 已归档）；8 项改为**注册项**装进四组 |
| GX24 的插件页在设置分区内 | `PHASE-M` **M8** | 插件页**提升为一级导航**；GX24 只保留「已装管理」的内容 |
| `PHASE-K K20`「桌面端禁用极简模式」 | `PHASE-M` **OV2** | 桌面端**解禁**，与 CLI 对齐 |
| B14「`cli:<软件名>` 注册进 `tools/registry.py`」 | `PHASE-N` **§6.4 / HN2** | 只注册恒定两个 agent 工具；否则 `cli/install` 会击穿前缀缓存 |
| §11「多模态 → Phase J」 | `PHASE-M` **M1** | **Phase I** |
| PHASE-G 不管 CLI（白名单不含 `opentui-app/`） | `PHASE-N` | CLI 对齐 + 长任务内核归 Phase N |

---

## §3 命名撞车登记

不阻塞开工，但每一条都能让人改错文件。**引用时一律带 Phase 前缀。**

| 符号 | 含义一 | 含义二 | 核验 |
|---|---|---|:-:|
| `/team` | PHASE-F：带参强制路由 | GX28：无参打开选择器 | ✅ **已裁定分流**，见 X2 |
| `GX1`–`GX8` | PHASE-FIX §0.2：**Grok 限制规则**编号 | PHASE-G：**任务卡**编号 | 🟡 「违反 GX2」是歧义句 |
| `B14` | PhaseG-B14：CLI-Hub 桥接器 | 代码 `appserver/subagent_routes.py:3`：Phase B 的 B14 子代理 | 🟡 |
| `D5` | GX26 依赖的「模型管理」= 主计划 Phase 4 卡 | `PHASE-D` D5：隔离式 AgentRuntime | 🟡 |
| `L9` | `PHASE-G:1494`「LinkAgent L9」 | `PHASE-L:1135` L9 · 缺 skill 引导 | 🟡 |
| `H10` | `PHASE-H:851` Settings 与 CLI 命令 | `PhaseG-H10` 文件树与 Worktree UI | 🟡 |
| **「模式」** | 四义：`mode`(build/plan/compose) / `permission_mode` / GX14 的 Ask-Edit-Agent / K 的极简-标准 profile | — | ✅ 见 `PHASE-N` DN7 |
| **`capability`** | PHASE-G：握手能力 + GX14 的 invoke 参数 | PHASE-K：CapabilityRegistry 的开关项 | 🟡 建议 GX14 那个改名 `tool_scope` |

---

## §4 卡号与计数勘误

> **✅ 已于 2026-08-18 并入 [`PHASE-M`](./PHASE-M-GUI-BASELINE-CAPABILITY.md) §7.4.1，由 M1 执行。** 本节自此只作存档，**施工以 §7.4.1 为准**。
>
> **⚠️ 下表的行号已全部失效，不要照着改。** 08-17/08-18 两轮在 `PHASE-G-DESKTOP.md` 追加注记后，其后内容整体下移且**各区段位移量不同**（`:1702`→`:1731` 是 +29，`:2232`→`:2280` 是 +48）。§7.4.1 给的是**可搜索的原文锚点**，用那个。
>
> **并入时复核发现本节两处自身错误**，已在 §7.4.1 更正：
> - 「`DESKTOP:1993-2014` 整段用 `I*`/`D*` 前缀」——**不成立**。D.2 映射表 16 行里只有 `G15` 一行用了 `I12`，其余全对。这条与前三条重复计数。
> - 「GX27/GX28 表格行多一个 `\|`，三列渲染成四列」——**描述错了**。实测两行都是 6 列、与 GX26 一致，真实缺陷是**行首多了 2 个空格**。
>
> 另有一条（GX14 两处「优先级/工时」）经复核**不是简单重复**：两行的工时拆分与依赖描述互相矛盾，`删一行` 这个处置不成立，须由 GX14 owner 裁定。§7.4.1 已改为「标注冲突、禁止自行删除」。
>
> **净结果：本节登记 11 条 → 实为 9 条**（去重复计数 1、去已修 1）。

全部为文本错误，可并进 M1 的勘误批一次清掉。

| 位置 | 错误 | 应为 | 核验 |
|---|---|---|:-:|
| `DESKTOP:1938` | `PhaseG-H1–I13` | `PhaseG-H1–H19` | 🟡 |
| `DESKTOP:1939` | `PhaseG-B1–D13` | `PhaseG-B1–B18` | 🟡 |
| `DESKTOP:1975` | G15 → `I12` | G15 → `PhaseG-H12` | 🟡 |
| `DESKTOP:1993-2014` | 整段用 `I*` / `D*` 前缀 | `H*` / `B*`（注意 `:1289,1296` 的 `D1-D8` 是主计划 Phase 4，别改错） | 🟡 |
| `DESKTOP:2232` | 「P3 · Codex 对齐批（**9 卡**）」且只列到 GX27 | **10 卡**，GX19–GX28 | 🟡 |
| `DESKTOP:2320-2321` | GX27/GX28 表格行多一个 `\|`，三列表渲染成四列 | 删多余竖线 | 🟡 |
| `DESKTOP:2241` | 「§10 **六项**出口达标」 | §10 只有 10.1–10.4 **四节** | 🟡 |
| `DESKTOP:3348` 与 `:3359` | GX14 的「优先级/工时/依赖」写了两遍 | 删一行 | 🟡 |
| `DESKTOP:1702` | `approval.requested` / `question.requested` | 实码为 `approval/request` / `question/request` | ✅ |
| `README.md:71` | PHASE-M「14 张卡」 | **15 张**（含 M13） | ✅ 已改 |
| `README.md:136` | 「两份文档采用 `PhaseG-F*` / `PhaseG-B*`」 | 实际是 `PhaseG-H*` / `PhaseG-B*` | 🟡 |

---

## §5 一处对审计报告本身的纠正

审计报告的 H2 称「`agent/invoke` **已有** `mode` 字段（build/plan/compose）」，并据此说 GX14 另造 `capability` 是重复。

**实测不是这样**（`frontend/protocol-client/src/generated/types.ts`）：

- `Mode`（`:54-57`，注释「Agent run mode (build/plan/compose); defaults to build.」）挂在 **`Method2 = "session/prompt"`** 那一段（`:47-57`）
- `AgentInvokeRequest`（`:488-496`）的字段是 `root_session_id` / `parent_session_id` / `request_id` / `agent_id` / `prompt` / `output_schema` / `requested_budget`——**没有 `mode`**

**所以结论要反过来说，而且更强**：`mode` 这一族参数住在 `session/prompt` 上，`agent/invoke` 上没有。GX14 把 `capability` 加到 `agent/invoke`，等于把一个 composer 级的控件挂到了 @ 提及子代理的路径上——**主对话那一轮根本不带这个字段**。用户会看到「我选了 Edit，它还是跑了 bash」。详见 `PHASE-N` 的 **HN5** 与 PHASE-G GX14 卡旁的注记。

**记这一条是为了立个规矩**：审计报告（包括本表标 🟡 的条目）是线索，不是判决。**动手前复核原文与实码。**

---

## §6 三条无主项的处置（AX1–AX3，均已了结）

> X1 / X6 / X8 三条当初**不属于任何现有文档的范围**——分别卡在 PHASE-F 与 PHASE-G 之间、PHASE-K 与 GX24 之间、PHASE-E 与 GX19 之间。本表先在这里建了三张临时卡，**现已全部落到各自该去的文档里**，此处只留裁定与指针。

### ~~AX1 · 补齐专家团的协议面~~ · **已落地为 PHASE-F `F18b`（2026-08-18）**

**背景**：X1。GX28 需要 `team/list`、`team/groups`、`team/group_rename`、`team/install`、`team/set_active`，F18 一个都不交付。

**裁定：协议由 F18 侧交付，不由 GX28 自造。** 理由是**真相源在哪，协议就在哪**——团队数据的真相源是 F18 的 `TeamRegistry` 与 `teams.groups.yaml`。让 GX28（一张前端卡）去定义读取后端真相源的协议，等于让消费方定义供给方的契约，这正是 PHASE-G 红线 4 要禁的事。

**处置：完整卡面已写进 [`PHASE-F-MULTI-AGENT-ORCHESTRATION.md`](./PHASE-F-MULTI-AGENT-ORCHESTRATION.md) 的 `F18b`**（紧随 F18 之后），含五方法语义表、规范限制、验收命令与九条完成判据。F18 卡首另有注记指向它。

**本表不再保留卡面副本**——两处维护一份卡只会分叉。这里只留裁定与指针。

**剩余一条待办（归 GX28 owner）**：GX28 卡里「本卡无协议扩展、无需 PROTO 登记」那句要改为指向 F18b。已列入 F18b 的完成判据。

---

### ~~AX2 · `plugin/search` 归属裁定与落地~~ · **已并入 PHASE-K（2026-08-18）**

**背景**：X6。PHASE-K 的 DK4 裁定「不自建市场，走 GitHub topic 搜索」，GX24 的市场页因此要消费 `plugin/search`——但这个方法既不在 GX24-PROTO 登记表里，也不在 K 的六方法清单里。

**裁定：归 PHASE-K。** 它是 DK4 那条裁定的直接产物，而 DK4 是 K 做的。**做决定的人负责把决定落成接口**，否则决定就只是一句话。

**处置（已完成，不另建卡）**：

- PHASE-K §3.3 方法表**从六行补为七行**，新增 `plugin/search`
- 同处挂追加注记，给出三条约束（走 GitHub topic API、不自建索引、网络不可达返回空列表而非抛错）
- **K5 卡的完成判据同步修正**——原判据写「五个方法」，与 §3.3 表列的六个本就对不上；现改为**七个**，并新增两条判据（`plugin/search` 的降级行为、GX24-PROTO 登记表同步）
- DK 决策表旁挂「DK4 追补」行，说明这条接口的由来

**不另建卡的理由**：`plugin/search` 是 K5（协议与前端路由卡）范围内的第七个方法，本就该在那张卡里做完。单开一张卡去加一个方法，只会让 K5 和它抢同一个文件。

---

### ~~AX3 · PHASE-E 完成状态复核与前置补录~~ · **已取消（2026-08-18）**

**取消原因**：本卡是为处置 X8 而建的，而 **X8 的结论已被证伪并撤回**。PHASE-E 复核实际已在 08-18 当场完成，结果是**通过**——E1–E4 产物齐备、协议面与 TS 生成物同步、165 个契约测试全绿。没有需要「复核」的东西了。

**本卡原计划的四项产出，三项已直接落地**（无需排期）：

- ✅ PHASE-E 完成表新增「验证命令」列，七行填满，附一条跑完整个 E 阶段的 pytest 命令
- ✅ `PHASE-G` §2 前置自检补入第 8 项（`protocol/` 内 `AgentEvent`/`event/agent` 符号探测），实测通过
- ✅ GX19 卡旁注记改为「E 侧门控可放行」，并给出 30 秒自检命令
- ⛔ 「把 E1–E7 状态改为待复核」——**不做，因为 `[x]` 是准确的**

**留下的唯一有效产物**是那条正面做法：完成标记附可执行的验证命令而非 commit SHA。已写进 PHASE-E 与 README，见 X8b。

---

## §6.4 已完成阶段的「文档 vs 实码」脱节体检（2026-08-18，结果良好）

X8 那次误判之后，把「文档说的东西在不在」做成了机械检查，对 PHASE-A/B/C/D/E/H/I/J 全量跑了两遍。**结论：已完成的阶段基本没有脱节，只揪出一处真错。**

**检查一 · 路径引用是否存在**（`scripts/audit_doc_paths.ps1`）

| 文档 | 引用路径 | 不存在 | 判定 |
|---|--:|--:|---|
| PHASE-J | 5 | **0** | ✅ 最干净 |
| PHASE-D | 13 | 1 | ✅ 误报——原文写的是「Phase F **将来会写**一个 `core/agents/runtime.py`」，将来时 |
| PHASE-A | 66 | 2 | ✅ 误报——`config/model_pricing.py` 是 Phase H E4 的交付物，前向引用 |
| PHASE-B | 44 | 2 | ⚠️ **1 真 1 误**，见下 |
| PHASE-H | 26 | 18 | ✅ 未实施阶段，缺的是它自己将来要建的 `core/agents/*` |
| PHASE-I | 36 | 11 | ✅ 同上，`core/attachments/*` 与 `tests/test_multimodal/*` |

**唯一的真错**：`PHASE-B:812` 的 B4 影响文件清单写 `core/memory/compressor.py`，**`core/memory/` 目录不存在**，真实位置是仓库顶层 `memory/compressor.py`。有意思的是**同一份文档另外两处写对了**，且行号区间 `:169-194` 本身准确（实测 `class ContextCompressor:25`、`_middle_truncate:169`）。全 `docs/plans/opus5-plan/rxycode/` 内 `core/memory/` 仅此一例。**已修，并在原处留脚注。**

**检查二 · `file.py:NN` 行号引用是否越界**（`scripts/verify_doc_linerefs.ps1`）

| 文档 | 行号引用 | 越界 |
|---|--:|--:|
| PHASE-A | 20 | **0** |
| PHASE-B | 72 | **0** |
| PHASE-C | 34 | **0** |
| PHASE-D | 2 | **0** |
| PHASE-E | 6 | **0** |

**134 条行号引用，越界 0 条。** 报告里的「文件不存在」计数（PHASE-B 50 条最多）经逐条核对**全部是引用外部项目**——`ClaudeCodeRuntimeDriver.ts`、`base_coder.py`（aider）、`cache_handler.py`（litellm）、`soul/compaction.py` 等竞品实现。PHASE-B 是缓存调研重的设计文档，引竞品源码是正常写法，不是脱节。

**这项检查有个已知盲区**：行号偏几行是机械查不出来的，所以上表是脱节的**下界**而非全貌。人工抽验做了一批（PHASE-C 的 `git_tool.py:128` / `vision.py:347` / `format_tool.py:233` / `open_file.py:249` 四条**逐个精确命中**），未发现偏移。

---

## §6.5 上线前基线实测（2026-08-18 05:21，全绿）

> 这一节是**可复现的当前状态快照**，不是断言。每行都附了产生它的命令，任何人可以当场重跑推翻它——这正是 X8b 那条做法（附验证命令而非只留结论）用在本表自己身上。

**后端**：按 `tests/` 子目录逐个跑，每目录独立进程 + `--timeout=120`。

原文这里写的是 `scripts/run_batched_tests.ps1`，但**该脚本已被 X12 那次 checkout 抹掉**——而本节开头刚承诺「每行都附了产生它的命令，任何人可以当场重跑」。所以改成不依赖任何脚本的等价命令：

```powershell
cd D:\agent-demo\RxyCode\RxyCode1_1_0
Get-ChildItem tests -Directory |
  Where-Object { (Get-ChildItem $_.FullName -Filter "test_*.py" -Recurse -File).Count -gt 0 } |
  Sort-Object Name | ForEach-Object {
    $r = python -m pytest $_.FullName -q --timeout=120 2>&1
    $s = "$($r | Select-String -Pattern '\d+ (passed|failed|error)' | Select-Object -Last 1)".Trim()
    "{0,-22} {1}" -f $_.Name, $(if ($s) { $s } else { "NO RESULT LINE" })
  }
```

**这段是实测过的，不是照着脑子写的**（2026-08-18，主检出）。两处细节是被真实报错逼出来的，改写时别退回去：

- `Where-Object` 那行不能省——`tests/` 下有 `__pycache__` / `_fixtures` / `fixtures` / `support` / `stress_test` / `test_synthesis` 六个不含测试文件的目录，直接遍历会得到六行空结果和 `exit 5`
- 结果行先 `"$(...)"` 字符串化再 `.Trim()`——直接 `.Trim()` 在 `Select-String` 返回数组时会抛 `MethodNotFound`，`tests/live`（无 API key 时一条都不跑）正好触发它。现在它输出 `NO RESULT LINE`，不会中断整轮

抽查三个目录的实测输出：`contract` → `862 passed`（186s）、`system` → `8 passed`、`test_appserver` → `109 passed, 1 skipped`。

| 目录 | 结果 | 目录 | 结果 |
|---|---|---|---|
| `test_core` | 7,408 passed（211s） | `test_appserver` | 109 passed, 1 skipped |
| `test_tools` | 954 passed | `test_bridge` | **17 passed**（本轮修复前 3 failed） |
| `contract` | 862 passed（194s） | `test_planning` | 13 passed |
| （根目录测试文件） | 570 passed | `test_mcp` | 9 passed |
| `test_providers` | 474 passed | `system` | 8 passed |
| `test_cache` | 457 passed, 3 skipped | `integration` | 7 passed |
| `test_subagents` | 447 passed | `live` | 1 skipped |
| `unit` | 191 passed | `test_validation` | 123 passed |
| `test_memory` | 190 passed | `test_execution` | 181 passed |

**合计 12,020 passed / 0 failed，10 分 43 秒。**

> ⚠️ **这份基线的口径必须说清楚：它是「分目录逐个跑」的结果，不等于「整套跑也全绿」。** 后续探测发现同样这批目录**合并成一个 pytest 会话跑，会出现九条只在合并时才倒下的失败**（X11，2026-08-18 14:50 已在独占工作树确证），**另有六条无论怎么跑都红**（DF1 / DF2 两个独立缺陷）。在 X11 查清之前，本表只能证明分批口径下全绿。
>
> **别把这条读成「所以要一直用分批跑」。** 分批跑是绕过，不是修复：它同时也在掩盖测试之间本该暴露的相互干扰。

**前端**：`scripts/run_frontend_checks.ps1`（每个项目独立执行，一个失败不掩盖其余）

| 项目 | typecheck | 单元测试 |
|---|:-:|---|
| `frontend/protocol-client` | ✅ | 11 tests / 3 files |
| `frontend/desktop-app` | ✅ | 266 tests |
| `frontend/opentui-app` | ✅ | 184 tests / 44 files |

**合计 461 tests 全绿，三处 typecheck 零错误，23 秒。**

**唯一已知的红线**：整套 `pytest tests` 一次性执行跑不完，见 [X10](#x10--pytest-tests-一次性跑会卡死必须分目录批量执行)。分目录批量是已验证的绕法，上表就是用它跑出来的。

---

## §7 处置归属汇总

| 条目 | 落到哪张卡 | 状态 |
|---|---|---|
| X1（GX28 缺的 `team/*` 协议） | **`PHASE-F` F18b**（新增卡，紧随 F18） | ✅ 卡面已写入 PHASE-F |
| X2（`/team` 语义互斥） | **`PHASE-N` N8**（参数分流裁定 + 消歧规则） | ✅ 已冻结 |
| X3（105 处失效路径） | **`PHASE-M` M2**（前端四行 + 根 `tests/` + 后端一行） | ✅ 已覆盖前后端 |
| X4（CLI 归属 / 白名单漏列） | **`PHASE-N`** + PHASE-G §3 白名单新增一行 | ✅ 已落地 |
| X5（`plugin/toggle` 登记口径） | **`PHASE-K`** §3.3 注记 + **K5 完成判据** | ✅ 已接上执行者 |
| X6（`plugin/search` 无人负责） | **`PHASE-K`** §3.3 表（六→七方法）+ **K5 完成判据** | ✅ 已落地 |
| X7（`/auto` 悬空引用） | **`PHASE-M` §7.4.1 第十四条** → M1 | ✅ 已并入 |
| ~~X8~~（PHASE-E 产物不存在） | — | ❌ **结论错误，已撤回**；AX3 取消 |
| X8b（完成标记纪律） | PHASE-E 完成表 + README | ✅ 降级为正面做法并落地 |
| X9（下游覆盖读不到） | 本表 §2 索引 + PHASE-G 顶部注记 | ✅ 已落地 |
| **X10（`pytest tests` 整套跑会卡死）** | — | ⛔ **无主**，需一次二分法排查；分目录批量为已验证绕法 |
| 上线前功能核验修掉的三个真缺陷 | `PHASE-C` C8 注记、`PHASE-B` B10 注记 | ✅ 代码已修并复验 |
| §4 卡号与计数勘误（9 条） | **`PHASE-M` §7.4.1** → M1 | ✅ 已并入，M1 工时 2–3h → 5–7h |
| B14 工具面（HN2）、GX14 挂错方法（HN5） | **`PHASE-N`** | ✅ 注记已落地 |

**文档侧无主项：0。** 二轮时还剩 X2 一条挂着「需产品裁定」，三轮直接裁了——理由是它其实不是产品问题：`/team` 带参与不带参在用户心里是同一件事的两种入口，`/model` 早就是这个模式，照抄既有先例即可，不需要谁来拍板要什么。

**四轮转入实码核验后新增一条无主项：X10。** 它跟前面九条性质不同——前九条是文档与实码脱节，X10 是**实码本身的问题**（全量测试跑不完）。分目录批量已验证可用（12,020 passed / 10m43s），所以不阻塞，但根因该有人去二分。

**唯一还需要别人动手的**：GX28 卡里「本卡无协议扩展、无需 PROTO 登记」那句要改成指向 F18b，以及 GX24-PROTO 登记表那两行。**两者都已写进对应卡的完成判据**（F18b、K5），不会再漏。

---

## §8 修订记录

| 日期 | 变更 |
|---|---|
| 2026-08-18 | 建表。五份并行审计合并去重后得 9 条阻塞项、8 条命名撞车、11 条卡号勘误。其中 X1/X2/X3/X4/X7/X9 与 §5 的纠正为本人复核原文与实码确证；其余标 🟡。同日在 `PHASE-G-DESKTOP.md` / `PHASE-G-BACKEND.md` 落地六处 ⚠️ 注记。 |
| 2026-08-18（二轮） | 处理四条无主项。新增 §6 补缺卡 **AX1/AX2/AX3**；X3 后端部分并入 PHASE-M **M2**（M2 同步新增反向断言禁建 `appserver/handlers/`）。**X8 在本轮被重写并升级为「PHASE-E 产物不存在」——该结论在三轮被证伪，见下行。** |
| 2026-08-18（四轮 · 上线前功能核验） | 从文档审计转入实码核验。修好三个真缺陷：**C8 bench 门在端口被占时诬告「杀进程失败」**（一次泄漏永久锁死该门；已改为 spawn 前快照并指名冲突 PID）、**B10 的「超时/预算即 kill」在 Windows 上恒红且掩盖了真实漏洞**（`taskkill` 返回码未检查且无回退，杀不掉却报告已杀掉）、**`test_bench_gate` 在中文 Windows 上 GBK 解码崩溃**。基线实测 **12,020 passed / 0 failed**，X8b 的「测试数量未复现」待查项关闭。新增 **X10**：`pytest tests` 整套一次跑会卡死，分目录批量则 10m43s 全绿，根因未定位。PHASE-E 的七个 SHA 查明为跨分支合并（`e47c38a`，08-18 合入）所致，真实 commit 已填回表。 |
| 2026-08-18（三轮） | **撤回 X8。** 二次实测：PHASE-E 的 E1–E4 产物齐备（`eventbus.py` / `agent_task.py` / `agent_runtime.py` / `agent_context.py`）、`AgentEvent` 覆盖 `protocol/` 与 TS 生成物、165 个契约测试全绿。二轮结论源于一次过时观测（相关文件 `mtime` 为 08-18 02:58，晚于核查），且忽略了会话起始 `git status` 里已列出的 `A appserver/agent_runtime.py`。**AX3 取消**；X8b 由「完成标记普遍不可信」降级为一条正面做法（附验证命令而非 SHA）。同步更正 PHASE-E 完成表、PHASE-G GX19 注记、PHASE-G §2 第 8 项、README 四处。**§4 勘误并入 PHASE-M §7.4.1 交 M1 执行**（§4 的九行 + §1 X7 的 `/auto` 一条 = **十条**，对应 M1 的勘误五至十四；本行原写「九条」漏计了 `/auto`）；**WorkBuddy 四处勘误在 PHASE-F 原地挂注记**，PHASE-L L1 补两处漏项。 |
