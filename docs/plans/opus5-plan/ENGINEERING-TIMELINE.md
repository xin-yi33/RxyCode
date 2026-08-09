# 工程顺序 · Composer 主写（后端 + 前端）+ Grok 辅助（前端多模态）怎么把两个项目跑完

> **这份文档回答**：开 **Composer 窗口主写全部代码**（后端卡和前端卡都是它的）、**Grok 窗口辅助前端的多模态环节**（视觉验收、图片 UI、对照设计稿），哪些卡能同时飞、哪些必须排队、怎么不互相踩。
>
> **模型分工权威**：[`MODEL-ASSIGNMENT.md`](./MODEL-ASSIGNMENT.md)。  
> **它不替代施工文档。** 做什么看 [`rxycode/`](./rxycode/README.md) 和 [`linkagent/`](./linkagent/README.md)；主写纪律看 [`COMPOSER-2.5-PLAYBOOK.md`](./COMPOSER-2.5-PLAYBOOK.md)，辅助纪律看 [`GROK-FRONTEND-PLAYBOOK.md`](./GROK-FRONTEND-PLAYBOOK.md)。**这里只管顺序、并行度和冲突。**
>
> **创建**：2026-08-01 · **修订**：2026-08-03（主计划新增 Phase 3 模型输出上限，Desktop 顺延为 Phase 4；Composer 全栈，Grok 辅助前端多模态）

---

## §0 结论先说

**总量是 98 张卡**（RxyCode 主计划 38 + LinkAgent 60，不含 RxyCode Phase A/B/C/D）。

**分工定死了**：**Composer 主写全部代码**（后端 + 前端），**Grok 只辅助前端的多模态环节**（写前端要"看"的时候才用到）。不是两个同质窗口抢同一类活，也不是前后端各管一半。

**瓶颈不是 agent 的产出速度，是你审查的速度。** 所以：

| 直觉 | 实际 |
|---|---|
| 开两个窗口 = 两倍产出 | **约 1.1–1.3 倍。** Grok 是辅助不是第二条主链；审查只有你一个人做，是串行的 |
| 开三个窗口更快 | **基本没用。** 你审不过来，第三个窗口只会积压 |
| 双开的价值是并行执行 | **双开的真正价值是：你审 A 的时候 B 在跑。** 把 Grok 的视觉验收/截图环节藏进你的审查时间里 |
| 早期没多模态环节时让 Grok 写后端或写前端卡 | **禁止。** 空闲就查资料或空着；前端卡本体是 Composer 的活 |

**推论决定了整份文档的排法**：不按日历排，按**"Composer 的一张卡 + Grok 的一个多模态环节能否同时飞且不踩交接点"**排。早期几乎没有多模态环节，Grok 窗口经常空——这是正常的，不是浪费。

**唯一值得优先投入的加速手段是自动化验收**——它是唯一能放大你审查带宽的东西。这也是为什么 RxyCode 的 **Phase 1（让评测说真话）必须排在所有扩展之前**：没有可信的自动信号，你就得逐行读 agent 的产出，那才是真正的天花板。

---

## §1 单位换了：不是人周，是卡

原来按"人周"排是因为假设人在写代码。现在写代码的是 agent，人周这个单位失效了。

**新的计量单位是"卡"**，因为一张卡 = 一个 commit = 一个你要审的单元（[Playbook C1](./COMPOSER-2.5-PLAYBOOK.md)）。

| 项目 | 卡数 | 其中"大卡"（agent 单次跑不完、要拆） |
|---|---:|---|
| RxyCode Phase 0 | 8 | — |
| RxyCode Phase 1 | 6 | H3（修坏任务） |
| RxyCode Phase 2 | 8 | **P3（抽 Session 层）** |
| RxyCode Phase 3 模型输出上限 | 8 | M3、M4 |
| RxyCode Phase 4 Desktop | 8 | D2、D3 |
| LinkAgent L0–L9 | 54 | **L5-3（AED 蒸馏）**、L9-5 |
| LinkAgent L10（横切） | 6 | — |
| **合计** | **98** | 8 张 |

> **L10 不是一个阶段，是横切的六张卡**，分散插在 L1~L5 之间，见 [`L10 §3`](./linkagent/L10-SKILL-INTEROP.md) 的排期表。其中 **L10-4 是止血卡**（RxyCode 默认注册的 `skill` 工具能绕过全部治理），排期见 §4 阶段 4。

**施工文档里写的"工时"（如 L5 = 8.5 天）是人的工时，现在只能当作"这张卡有多复杂"的相对指标读，不要当日历用。**

### 怎么估真实进度

单卡从开工到合并的时间 ≈ **agent 执行 + 你审查 + 修一轮**。前者几分钟到几十分钟，后者取决于卡的大小和你的熟悉程度。

**跟踪进度用"已合并卡数 / 98"，不要用日期。** 跑完前 10 张卡之后你会有自己的速率，那时候再推算完成时间才有意义。

---

## §2 真正的三个约束

人力和技能都不再是约束了（agent 写 Python 和 TS 一样）。剩下三个：

### 约束 ① 依赖链（硬，改不了）

这四条是**语义依赖**，不是资源冲突，加窗口也解决不了：

| # | 依赖 | 违反的后果 |
|---|---|---|
| ① | **LinkAgent L2 ← RxyCode Phase 2** | Phase 2 改 `AgentV2` 对外形态，桥接层要跟着改 |
| ② | **LinkAgent L9-4~L9-8 ← RxyCode Phase D** | Desktop 基础壳来自主计划 Phase 4；模型/成本摘要消费 Phase 3；完整项目/Thread/审批/diff/worktree 工作台和扩展契约必须等 Phase D |
| ③ | **LinkAgent L5 ← L3 完成并验证** | 论文实测：作用域没修就开反馈演化，DeepSeek 上是**净负收益 −2.69 pp**。做反了会变差，不是"最好先做" |
| ④ | **一切 ← RxyCode Phase 1** | 没有可信评测，你无法判断 agent 的产出有没有搞坏东西 |

> ①② 在 §6 里会重新评估——**返工变便宜之后，这两条的约束力比原来弱**。③④ 不受影响，它们是语义约束。

### 约束 ② 文件冲突（这才是双开的主要风险）

两个 agent 同时改同一个文件 = 后合并的那个把前一个覆盖掉，而且**两边的验收都会通过**（各自跑的时候都是对的）。

**这类问题不会报错，只会静默丢代码。** 防它的唯一办法是提前把文件所有权划清楚——见 §4。

### 约束 ③ 审查带宽（真正的天花板）

见 §0。**你能审多快，整个项目就能跑多快。**

三个能放大它的投入，按性价比排序：

| 投入 | 效果 |
|---|---|
| **RxyCode Phase 1（评测说真话）** | 最高。有了可信基线，你审的是"基线有没有掉"，不是"这 300 行对不对" |
| **每张卡的验收命令写死在文档里** | 已经做了。agent 必须贴真实输出，你先看输出再看 diff |
| **契约测试**（L2-1、L9-1 的超集测试） | 跨仓库变更会自动报警，不用你记着 |

---

## §3 两条泳道：主写（Composer）与辅助（Grok），仓库是第二层

**第一层是模型分工**（硬）：

```
窗口 Composer ── 主写全部卡：后端（Python / schema / appserver / evals）+ 前端（TS / Electron / UI）
窗口 Grok     ── 只做前端卡里标注的「多模态环节」：截屏视觉验收、图片 UI、对照设计稿；空闲时查资料
```

**第二层是仓库**（减冲突）：Composer 尽量待在一个仓库跑主链；跨仓库时用 worktree。

```
常见配置 A（早期，几乎没多模态环节）
  Composer ── RxyCode Phase 0/1/2 → LinkAgent L0–L8，串行推进
  Grok     ── 空闲 / 查资料 / 等 schema 合并后再做被委托的视觉环节

常见配置 B（Phase 3 / Phase 4 / Phase C / L9 前端阶段，辅助收益最大）
  Composer ── 主写 RxyCode Phase 3 模型上限、Phase 4 基础壳、Phase D 完整 Desktop（D1–D16）或 LinkAgent L9
  Grok     ── 并行做 D6/D9/D10/D15、L9-4/L9-5 等卡的视觉验收、截图对比、换肤对照
```

**Grok 空闲不是问题。** 为了填满窗口让它改 Python 或接管前端卡本体 = 破坏 [`MODEL-ASSIGNMENT`](./MODEL-ASSIGNMENT.md) 的分工。

### 什么时候会被迫同仓双开

Composer 与 Grok 同时在一个仓库干活时（例如 RxyCode Phase 2：Composer 写 P1–P8，Grok 做被委托的视觉环节），用 **git worktree**，各自分支——**不要两个窗口开同一个工作目录**。Grok 不另开分支时（产出很小），直接把改动放 patch 文件或同一个 worktree 的另一分支，交 Composer 收口。

文件所有权：**全部文件归 Composer**（它是主写）；Grok 只动被委托环节涉及的片段。交接点只有 `schema.json` 和卡里标注的「多模态环节」。

---

## §4 分阶段执行顺序

### 阶段 0 · 开局（全是主写）

**这一阶段没有多模态环节。** Composer 串行或按仓库切换做全部卡；Grok **空闲 / 查资料**，不写代码。

| Composer（主写） | Grok（辅助） |
|---|---|
| **先** RxyCode Phase 0 S1–S8（8 张）止血 | 空闲 / 查资料 |
| **或穿插** LinkAgent L0（5）+ L1（6）EKO 移植 | — |

> 若你坚持双开两个 Composer 会话（都在后端、不同仓库），可以：一个会话只碰 RxyCode，一个只碰 LinkAgent。**那不是让 Grok 写代码。**

**这一段做完的标志**：`ruff check .` 进 CI；LinkAgent 能 `pip install -e .`、冻结语料契约测试全绿。

---

### 阶段 1 · 评测先行（仍是主写）

> **这是整个计划里最不该省的一段。** 它决定你后面所有卡的审查成本。

| Composer（主写） | Grok（辅助） |
|---|---|
| **Phase 1** H1–H6（6 张）：evals 跑真实 Agent、修坏任务、进 CI、基线落盘 | 空闲 / 查资料 |
| 穿插：L10-2 / L10-5 / L10-1 → L8-2 / L8-3（推荐） | — |

**Composer 侧在 Phase 1 间隙可推进的 LinkAgent 卡**：

| 选项 | 说明 | 推荐 |
|---|---|---|
| **先做 L10-2 / L10-5 / L10-1，再做 L8-2 / L8-3** | L10-2（Skill 解析器）**是 L8-2 的前置**。L8-3 是内容策展 | ✅ **推荐** |
| 空着专心审 Phase 1 | Phase 1 值得专注 | 🟡 也合理 |
| 让 Grok 帮写 Phase 1 | Phase 1 全是 Python / evals | ❌ **禁止跨界** |

> ⚠ **顺序别搞反**：L10-2 → L8-2 → L8-3。跳过 L10-2 直接做 L8-2，agent 会在 `curate.py` 里现写一套 SKILL.md 解析，之后 L10-3 再写第二套，两套解析产出的 EKO 结构就不一致了。
>
> ⚠ L8-1（包格式与装载）里有一条校验依赖 L3 的 scope 模块，**这张卡留到 L3 之后**。先做 L10-2/L8-2/L8-3 不受影响。

**出口标准**：`python -m evals.cli run --backend agent` 能跑真实 Agent，基线分数落盘。**从这里开始，每张卡合并前都要比对基线。**

---

### 阶段 2 · 协议（第一次出现辅助环节）

Phase 2 是 **RxyCode Phase 3/4 和 LinkAgent L2/L9 共同的地基**，优先级最高。

| Composer（主写） | Grok（辅助） |
|---|---|
| P1 定义协议层 + 产出 `schema.json` | **等 P1 合并后**：P2 `frontend/protocol-client/` 的**多模态环节**（若有，视觉验收） |
| **P3 抽 Session 层**（最大的一张，考虑拆成 3–4 个 commit） | P5 OpenTUI 迁移的**多模态环节**（若有） |
| P4 appserver、P6 api_server 变薄、P7 P8、**P2/P5 本体** | — |
| 间隙：LinkAgent L8-2 / L8-3 收尾 | — |

#### 同仓并行时的文件所有权（RxyCode Phase 2）

| 模型 | 拥有/独占 | 禁止碰 |
|---|---|---|
| Composer | **全部**：`protocol/`、`core/`、`appserver/`、`agent_v2.py`、`frontend/**` | 委托给 Grok 的多模态环节让它做，不要抢 |
| Grok | 无（辅助） | `protocol/**`（**只读消费 `schema.json`**）· 任何 `.py` · 环节外的前端代码 |

**交接点只有两个**：`protocol/schema.json`（Composer 产出，类型生成才开工）+ 卡里标注的「多模态环节」（Composer 委托，Grok 只做标注部分）。**P1 合并之前 Grok 不要开工。**

> 关于 **Phase A**：仍建议推后，别在审 P3 时分心。

**出口标准**：`protocol/schema.json` 已提交并有冻结测试；`python -m appserver` stdio 可跑通；OpenTUI 已迁到协议。

> 🚪 **这道门开了，LinkAgent L2 才能开工。**

---

### 阶段 3 · 模型输出上限自适应（Composer 主写，Grok 不介入代码）

**这一阶段把当前配置里的统一 `8192` 替换为按真实 `model_id` 解析的共享契约。** Composer 独做 M1–M8；Grok 不接管后端，也没有可以独立并行的多模态环节。它最多在需要时核对模型列表/设置页显示，结果回传 Composer 收口。

| Composer（主写） | Grok（辅助） |
|---|---|
| **M1–M8**：盘点固定值 → 冻结 ModelCatalog / OutputLimitResolution → 按 Provider + model ID 解析 → 接入 Provider → 兼容旧配置 → 摘要与诊断 → 回归与发布门 | 空闲 / 查资料；若已有前端模型选择器，只做卡内标注的视觉核对 |

**阶段 3 出口**：新增模型默认为 `auto`；精确 `model_id` 能命中目录；未知模型走可配置的高位兜底；Provider、CLI、OpenTUI 和后续 Desktop 只消费同一个 resolver/摘要协议；旧正整数配置保持显式覆盖。

---

### 阶段 4 · 辅助收益最大（Composer 主写 Desktop + LinkAgent，Grok 做视觉环节）

**这是分模型设计的主场**：Composer 主写 RxyCode Phase 4 基础壳和 Phase D 完整 Desktop（D1–D16 全部），Grok 在 D6/D9/D10/D15 等 UI 卡的多模态环节并行辅助；LinkAgent 后端链由 Composer 在间隙穿插。

| Composer（主写） | Grok（辅助） |
|---|---|
| **RxyCode Phase 4（8 张）主写**：D1 脚手架 → D2 主窗口 → D3 流式 + 工具卡片 → D4 审批 UI → D5 设置页 → D6 打包 / D7 更新 / D8 CI | **D3/D4/D5 的视觉验收**：起 dev server 截屏核对（正常/空/加载/错误态）、布局对齐、审批弹层样式 |
| 穿插 **LinkAgent**：L2 桥接（6 张）→ L3 检索+硬门（5 张）→ **L10-4 止血**（L4 后）→ L5 证据演化（6 张，⚠ 必须 L3 验证）→ L6 依赖组合（4 张，默认关闭） | 换肤/图标类环节（若有）对照截图 |
| 旁链：L7 评测（5 张）· L8-1/L8-4/L8-5 预置包 · L10-3/L10-6（L5 后） | 空闲时查资料 |

> **L10-4 为什么卡在 L4 正后面**：RxyCode 默认注册了 `skill(name)` 工具（`core/agent_v2.py:1499,1519`），它能把任意 `SKILL.md` 全文塞进上下文——**绕过 L3 的域门、L4 的安全门、L5 的证据链**。L4 一做完就有了 approval broker 的接线，这时候封成本最低。

#### L5 开工前的强制自检

```powershell
cd "D:\agent-demo\LinkAgent"
python -m pytest tests/eko/test_cross_domain_regression.py -v
```

**跨域泄漏必须是 0。** 不满足就回去修 L3，别硬上。

#### Composer 主链上的 LinkAgent 顺序

L2→L3→L4→L5 是串行的。L7 和 L8 是旁链，**穿插在等待和审查间隙做**：

| 旁链卡 | 最早能做 | 会碰的共享文件 |
|---|---|---|
| **L10-4**（止血） | **L4-3 合并后** | `safety/rules.py`（L4 刚建的）+ `skillio/gate.py`（新） |
| L7 全部 | L3 完成后 | `evals/`（新目录）、只读消费 `runtime/turn.py` |
| L8-1 | L3 完成后 | `preset/`（新目录） |
| L8-4 | **L3-3 合并后** | ⚠ `eko/engine.py` —— **和 L3-3 同一个文件，绝不能并行** |
| L8-5 | L8-4 后 | `preset/loader.py` |
| L10-3 | L5 全部完成后 | `tools/eko_tools.py` —— ⚠ 和 **L5-6** 同一个文件，串行 |
| L10-6 | L10-1 + L10-2 后 | 只有测试文件 |

**两个真冲突点**：

| 文件 | 抢它的卡 | 处理 |
|---|---|---|
| `eko/engine.py` | L3-3（检索接入）· L8-4（预置包接进检索） | **必须串行**，L3-3 先 |
| `tools/eko_tools.py` | L5-6（五个 EKO 工具）· L10-3（`skill_import`） | **必须串行**，L5-6 先 |

---

### ★ 决策点 · L7 首次基线

**这是整个计划里唯一一个"可能让后面全部作废"的地方。**

| L7-5 的结论 | 接下来 |
|---|---|
| **经验层有显著收益** | 做 L9 桌面端。这时 Phase 4 已完成，壳现成 |
| **无显著收益，但某个模块有** | 只留那个模块，砍掉其余；**不做 L9**，先把有效的部分做扎实 |
| **完全无收益** | **停 LinkAgent。** Composer 回 RxyCode Phase A → Phase B；Grok 空闲或辅助 Phase E 的图片类 UI |

**必须真的准备好接受第三种结果。** 论文的 +5.27 pp 是在 100 条受控序列、两个特定模型、沙箱工具上测的，LinkAgent 的任务分布、工具、执行路径全都不同，而且**主动改了作用域机制**。[`APPENDIX-B`](./linkagent/APPENDIX-B-PAPER-EVIDENCE.md)：只能测，不能推。

同一轮还要跑 [`L8 §5`](./linkagent/L8-PRESET-EKO-PACK.md) 的四组对照。**如果"有预置包 − 无预置包"不显著，预置层要缩到最小甚至砍掉**，别因为已经做了就留着。

---

### 阶段 5 · LinkAgent 桌面（仅在决策点通过时）

| Composer（主写） | Grok（辅助） |
|---|---|
| **L9-1** 协议扩展 + schema 超集契约 | 等 L9-1 |
| **L9-2** appserver · **L9-3** TS 类型（等 L9-1 的 schema） | 等 L9-3 完成 |
| **L9-4** fork Electron 壳 · **L9-5** 森林只读视图 | L9-4 换肤、L9-5 森林树渲染的**视觉验收**（截屏核对） |
| **L9-6** 检索解释 · **L9-7** 设置 · **L9-8** 打包 Win + macOS | L9-6/L9-7 的视觉验收（若有） |
| 间隙：转 RxyCode **Phase A** 模型适配 | 空闲 / 查资料 |

**交接点只有一个**：`src/linkagent/protocol/schema.json`。Composer 产出，类型生成才开工（L9-1 合并之前 L9-3 不要开工）；多模态环节由卡内标注指定，Grok 只做标注部分。

> L9-8 的打包验证有真实 wall-clock（两个系统的干净环境各装一次），这一步快不了，别指望 agent 加速它。

---

## §5 同仓双开的四条规则

Composer 与 Grok（或两个 Composer 会话）在同一仓库时，这四条必须守住。

### 规则 ① 先划文件所有权，再开工

默认所有权见 [`MODEL-ASSIGNMENT.md`](./MODEL-ASSIGNMENT.md) §1。开第二个窗口之前，**写下来**本阶段独占目录。§4 每个阶段的表就是这个东西。

**没写下来就双开 = 迟早静默丢代码。**

### 规则 ② 共享文件永远串行

`eko/engine.py`、`config.py`、`runtime/turn.py`、`schema.json` 这类被多张卡碰的文件，**同一时刻只能有一个窗口在改**（schema 只允许 Composer 写）。

### 规则 ③ 用 worktree，不要共用工作目录

```powershell
git worktree add ../RxyCode-lane2 -b feat/lane2
```

两个窗口各自的工作目录和分支，通过 PR 合并。**两个 agent 开同一个目录会互相看到对方写到一半的文件**，产出会莫名其妙。

### 规则 ④ 合并顺序固定：先合小的，后合大的

大卡（P3、L5-3）改动面广，让它最后合并、承担 rebase 成本。反过来会让小卡反复 rebase。

---

## §6 返工变便宜了，所以两条"先等一等"的建议要改

原来的施工文档里有几处写着"建议等 X 落地再做 Y，否则要返工"。**那是按人的返工成本写的。**

agent 重做一张卡的成本 ≈ 一次执行 + 一次审查，比人重做低一到两个数量级。所以：

| 原建议 | 现在怎么看 |
|---|---|
| "LinkAgent L2 等 RxyCode Phase 2，否则接受一次返工" | **仍然建议等**，理由是怕你审两遍。Composer 空闲时可提前做 L2——契约测试会报警 |
| "L9-4 等 Phase D" | **必须等**——没有完整 Desktop 壳、扩展契约和基础工作台就不应重复造一套 |
| "L5 等 L3" | **必须等**，语义约束，做反了效果是负的 |
| "Grok 空闲时写点代码" | **永远不行**——Grok 只做多模态环节，跨界比返工更贵（审查边界崩了） |

**判据**：如果"等"的理由是**返工成本**，现在可以重新考虑；如果理由是**没有前置产物**、**做反了结果是错的**、或**跨模型文件边界**，那还得等。

---

## §7 三个模型怎么配合

权威定义在 [`MODEL-ASSIGNMENT.md`](./MODEL-ASSIGNMENT.md)。摘要：

| 模型 | 职责 | 手册 |
|---|---|---|
| **Composer 2.5** | **主写全部**：后端（Python / schema / appserver / evals）+ 前端（Electron / React / TS / UI） | [`COMPOSER-2.5-PLAYBOOK.md`](./COMPOSER-2.5-PLAYBOOK.md) |
| **Grok 4.5** | **前端辅助**：只做卡里标注的「多模态环节」（视觉验收、图片 UI、对照设计稿）；空闲时查资料 | [`GROK-FRONTEND-PLAYBOOK.md`](./GROK-FRONTEND-PLAYBOOK.md) |
| **Sonnet 5** | Diff 预审（可选） | — |

推荐回路：**Composer 写卡 → 卡里「多模态环节」委托 Grok →（可选）Sonnet 预审 → 你合并**。

**最值得让 Sonnet 5 先审的四张卡**：

| 卡 | owner | 为什么 |
|---|---|---|
| RxyCode **P3**（抽 Session 层） | backend | 全项目最大的一次搬运 |
| RxyCode **B2**（拆全局单例） | backend | 漏一个单例就会在多 Agent 下随机出错 |
| LinkAgent **L3-2**（作用域硬门） | backend | 改检索语义，错了效果反向 |
| LinkAgent **L9-4**（fork Electron 壳） | frontend | 分叉一旦歪了，后续视图全建在歪壳上（执行者 Composer，视觉环节 Grok） |

---

## §8 一页速查

```
阶段 0   Composer: Phase0 / L0+L1（全主写）      ‖  Grok: 空闲或查资料
阶段 1   Composer: Phase1 + L10/L8 穿插          ‖  Grok: 空闲或查资料
           🚪 评测说真话
阶段 2   Composer: Phase2 Python/schema + P2/P5 本体  ‖  Grok: P2/P5 的视觉环节
           🚪 协议落地（schema 合并后前端类型才开工）
阶段 3   Composer: Phase3 模型输出上限 M1–M8 主写
         Grok: 空闲 / 必要时核对模型列表摘要
阶段 4   Composer: Phase4 Desktop D1–D8 + LinkAgent L2→L6 主写
         Grok: D3/D4/D5 视觉验收（截屏核对）
           ★ 决策点：L7 首次基线
阶段 5   Composer: L9-1~L9-8 主写 → Phase A      ‖  Grok: L9-4/L9-5 视觉验收
                                           → LinkAgent Desktop
```

| 门 | 开了才能做 |
|---|---|
| RxyCode Phase 1 出口 | 后面每张卡的基线比对 |
| RxyCode Phase 2 出口（含 schema） | LinkAgent L2、L9-1；前端类型生成 |
| RxyCode Phase 3 模型上限出口 | Phase 4 D5 和后续客户端消费统一摘要 |
| RxyCode Phase 4 Desktop 出口 | LinkAgent L9-4 |
| LinkAgent L3 跨域回归 = 0 | LinkAgent L5、L7、L8-1 |
| LinkAgent L3-3 合并 | LinkAgent L8-4（同一个文件） |
| LinkAgent L5-6 合并 | LinkAgent L10-3（同一个文件） |
| LinkAgent **L10-2** | LinkAgent **L8-2** |
| LinkAgent **L9-1** schema 合并 | LinkAgent **L9-3** 类型生成 |
| ★ L7 首次基线 | LinkAgent L9 整个阶段 |

> ⚠ **L10-4 不是"门"，是"欠债"。** 必须早于 L7 首次基线，否则基线测出来的治理有效性不可信。

**推迟到决策点之后再谈的**：RxyCode Phase C（多 Agent）、Phase E（多模型）、Phase F（多模态）、Phase G（PersonaAgent）。RxyCode Phase D Desktop 是主工作台路线，不应和这些高级能力一起无限后推。

> 推迟 Phase C 是有依据的：[`PHASE-C`](./rxycode/PHASE-C-MULTI-AGENT-ORCHESTRATION.md) §2.5 —— 多 Agent 消耗 15 倍 token，编码任务不是多 Agent 强项。
