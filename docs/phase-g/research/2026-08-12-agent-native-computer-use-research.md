# Agent-Native Computer Use 调研与 RxyCode 集成决策报告（2026-08-12）

> **调研目的**：为 Phase G（RxyCode Desktop 完整工作台）的 GUI 改版（向 Codex 看齐）与"软件控制能力"（Computer Use / CLI-Anything）提供决策依据，回答：computer use 内核是什么、为什么对我们不现实、CLI-Anything 是否可抄、怎么抄、GUI 功能如何落卡。
> **调研方法**：本地框架/代码实证 + 网络一手来源（Anthropic 工程文、Cognition 观点文、微软 Magentic-One、Berkeley MAST 论文、HKUDS CLI-Anything 源码级拆解：README/HARNESS.md/PREVIEW_PROTOCOL.md/preview_bundle.py/skill_generator.py/repl_skin.py/registry.py/opencode-commands 全量抓取）。
> **核心结论（一句话）**：**Computer Use（截图点击）路线不进入 RxyCode**——token 账与脆弱性不可接受；采用 **Agent-Native Computer Use 路线（CLI-Anything 范式，混合集成：先消费 CLI-Hub 生态、后内嵌 7 阶段生成器）**，以"软联系"（结构化命令直连软件后端）打破生态护城河；GUI 全面对齐 Codex 交互，新增 20 张开发卡（B14–B18 + H14–H19 + GX19–GX27）。
> **下游产物**：本报告是 [`PHASE-G-DESKTOP.md`](../PHASE-G-DESKTOP.md)（GX19–GX27 增强任务卡）、[`PHASE-G-FRONTEND.md`](../PHASE-G-FRONTEND.md)（H14–H19 前端基建卡）、[`PHASE-G-BACKEND.md`](../PHASE-G-BACKEND.md)（B14–B18 后端卡）的立项依据与规格来源。

---

## 1 背景与问题

### 1.1 用户的原始诉求

1. Phase G GUI 不再走轻量化路线，向 **Codex harness** 看齐（"全世界的 GUI 都在抄 Codex，我们也抄"）；
2. **Computer Use** 很神奇，想学并抄过来——但**十分消耗 token**，要先了解其运行内核，评估能否仿照；
3. 发现港大（HKUDS）新项目 **CLI-Anything**（CLI 中连接电脑上的任意软件，类似 computer use 的效果）——倾向于用它达到 computer use 效果，但它是 CLI 出身、我们是 GUI，需要手动适配；
4. 生态护城河命题：Codex/各家 agent 的护城河是生态；**若能绕过与公司的联系、直接与软件联系（软联系而非硬联系），就能打破护城河**；前提是把 token 消耗控制在很小的量；
5. GUI 功能 = 抄 Codex（会话置顶、项目目录、新建会话、插件生态、定时任务、设置页全套、回收站、语言本地化、运行状态视觉、分类折叠等）；
6. 为多 Agent / 多 Agent × 多模型预留前端接口（能打样最好，做不出就留接口）。

### 1.2 两个关键概念的界定（本报告统一术语）

| 术语 | 定义 | 代表 |
|---|---|---|
| **硬联系（Hard Integration）** | agent 通过模拟人类交互（截图→点击/键入像素坐标）操作软件 | Anthropic Computer Use、OpenClaw、各类 claw 系 |
| **软联系（Soft Integration）** | agent 通过结构化命令直连软件后端/接口，软件以确定性输出应答 | CLI-Anything 生成的 CLI、MCP、官方 SDK 包装 |

**判定**：软联系是"绕过公司与软件生态的护城河"的唯一可行路径——它不依赖任何公司的官方插件市场或 API 授权，只依赖"软件有代码库或官方接口"这一普遍事实。

---

## 2 Computer Use 内核拆解（Anthropic 范式，公开技术知识）

### 2.1 机制循环

```text
循环（每步）：
  1. 截图当前屏幕（如 1280×800，压缩到模型支持的视觉规格）
  2. 模型（多模态）视觉分析屏幕内容 → 决定动作
  3. 模型输出结构化动作：{ action: click|type|key|scroll|move|screenshot, coordinate: [x, y], text, ... }
  4. 宿主执行：OS 层 API（Windows UI Automation / AppleScript / xdotool）执行动作
  5. 返回上一步
```

### 2.2 Token 账（为什么"十分消耗 token"）

| 成本项 | 量级 | 说明 |
|---|---|---|
| 每步截图转视觉 token | 数百 ~ 上千 token/张 | 每次循环都要把整屏图片交给模型 |
| 上下文随步数增长 | N 步 = N 张截图 × 全上下文回传 | 每轮消息都要带历史截图，上下文线性膨胀 |
| 多步任务合计 | 一个 20 步任务 = 20+ 张截图反复进上下文 | 远高于等长文本任务 |
| 模型要求 | 必须强多模态模型 | 视觉通道本身是硬成本 |

Anthropic 官方实测口径（多 Agent 研究系统文）：agent 系统比普通对话 token 消耗约 **4x**，多 agent 系统约 **15x**；其中 token 用量单独解释性能方差 **80%**。Computer Use 处于该谱系的最高消耗端。

### 2.3 脆弱性（为什么工程上不可持续）

1. **像素级交互**：UI 布局一变（升级/换肤/分辨率），坐标全部失效；
2. **时序依赖**：等待渲染、动画、弹窗的时序难以确定，竞态频繁；
3. **有损翻译**：把"视觉布局"翻译成"计算动作"是有损的——CLI-Anything 论文（arXiv 2606.03854）的原始论证："This eliminates the lossy visual-to-computational translation that plagues GUI agents"；
4. **安全面**：模拟输入可能点到不可预期位置（真实鼠标键盘在动），需要额外防线。

### 2.4 开源 claw 家族（OpenClaw / Hermes 的 claw 血统）

OpenClaw 及其衍生（hermes-claw 等）与 Anthropic Computer Use **同范式**：截图 + 像素坐标控制 macOS/Windows。它们没有解决 token 与脆弱性两个根本问题，只是把实现开源了。**"仿照内核造一个"在技术上可行，但在经济性与稳定性上把 RxyCode 拖回 computer use 的老路**——不采纳。

### 2.5 结论：为什么对我们不现实（决策论证）

| 维度 | Computer Use 路线 | RxyCode 的现实约束 |
|---|---|---|
| token | 每步截图 + 上下文膨胀 | Phase B 缓存未落地，token 账本尚不成立；15x 级消耗不可接受 |
| 脆弱 | 坐标/时序/UI 变更全废 | RxyCode 是长期产品，不能建在会因软件更新而碎的薄冰上 |
| 模型 | 必须强多模态 | 多模型场景（PHASE-H）角色分工里不应强制视觉通道 |
| 前端呈现 | 要渲染截图流（重、慢、模糊） | GUI 改版目标是 Codex 级轻快体验，截图流是反向 |
| 新基建 | 截图循环 + 坐标执行层 + 视觉通道三层新系统 | 现有 bash/工具面 + 子代理通道即可支撑 agent-native 路线 |

**决策 1（冻结）**：Computer Use 仅保留内核学习记录（本报告 §2），**不进入 RxyCode 产品路线**；软件控制能力全部走 Agent-Native 路线（§3–§5）。

---

## 3 CLI-Anything 深度拆解（HKUDS，46.9k stars，Apache-2.0）

> 源码实证：README 全文、HARNESS.md、PREVIEW_PROTOCOL.md、preview_bundle.py、skill_generator.py、repl_skin.py、session.py、registry.json/registry.py、opencode-commands/*、drawio agent-harness 包结构、codex-skill SKILL.md（2026-08-11 抓取）。

### 3.1 定位与论文论点

- **口号**："Making ALL Software Agent-Native"——今天软件服务人类，明天用户是 agent；
- **论文**：arXiv 2606.03854《CLI-Anything: Towards Agent-Native Computer Use》（HKU，2026-06-02）——直接论证 GUI agent 范式与 agent 能力**根本错位**，应建立与 agent 天然能力对齐的接口（结构化命令、显式状态、确定性反馈）；
- **定位**：它是 **computer use 的替代路线而非实现**——官方 README 明说"Replace or Supercharge GUI Agents：no more screenshots, no brittle pixel-clicking"；
- 生态：CLI-Hub 注册表（100+ 社区 CLI）、18+ 应用验证、2,464 测试 100% 通过、Apache-2.0 宽松许可。

### 3.2 7 阶段流水线（关键事实：纯 prompt 式，无生成器程序）

**CLI-Anything 没有"生成器代码"**——只有一份方法论规范 `HARNESS.md`（36.5KB）+ 各平台的"薄壳"（command/skill/plugin 提示词），由 LLM 按规范执行 7 阶段：

| 阶段 | 做什么 | 产出物 |
|---|---|---|
| 1 | 源码获取（GitHub URL clone / 本地目录） | 源码目录 |
| 2 | 代码库分析：找后端引擎（MLT/ImageMagick/bpy…）、GUI 动作→API 映射表、既有 CLI | 分析结论 |
| 3 | CLI 架构设计 | `<SOFTWARE>.md` 软件专属 SOP（命令组划分/状态模型/`--json` 输出） |
| 4 | 实现：数据层→probe/info 命令→mutation 命令→`utils/<sw>_backend.py`（`shutil.which`+`subprocess.run`）→渲染/导出→session+undo/redo→ReplSkin REPL | `agent-harness/cli_anything/<sw>/` 全部代码 |
| 5 | 测试计划（先写计划后写代码） | `tests/TEST.md` |
| 6 | 测试实现（单元→原生中间文件→真实后端→已安装命令四层） | `test_core.py` + `test_full_e2e.py` |
| 7 | 文档 + SKILL.md 生成 + PyPI 打包 | TEST.md、SKILL.md、setup.py |

**关键结论（对集成决策影响最大的一条）**：既然流水线是 prompt 式的，RxyCode 集成生成器的**代码成本极低**——本质是"把 HARNESS.md 与 7 阶段指令模板做进我们的技能/命令体系"，OpenCode 平台的参考实现（`opencode-commands/`）已经现成。

### 3.3 生成 CLI 的架构（GUI 适配的对象）

```
<software>/agent-harness/
├── <SOFTWARE>.md            # 软件专属 SOP
├── setup.py                 # find_namespace_packages(include=["cli_anything.*"])
└── cli_anything/<software>/  # PEP 420 命名空间
    ├── <software>_cli.py     # Click 入口：命令组 + 无子命令时进 REPL
    ├── core/{project,session,export,...}.py
    ├── utils/{<software>_backend.py, repl_skin.py}
    ├── skills/SKILL.md       # 打包兼容副本
    └── tests/{TEST.md, test_core.py, test_full_e2e.py}
```

- **命名**：包 `cli-anything-<software>`，`pip install -e .` 后直接上 PATH；多包命名空间共存无冲突；
- **Click 命令组**：顶层 `@click.group(invoke_without_command=True)` + 领域子组（drawio 例：project/shape/connect/page/export/session）；全局 `--project`/`--json` 选项；
- **JSON 输出约定**：每条命令必带 `--json`，返回结构化 dict；错误走 stderr + 非零退出码——**机器可消费是设计的核心**；
- **ReplSkin**（21KB，逐份 vendor 进各 harness）：prompt_toolkit PromptSession + 历史/补全/底部 toolbar；banner 打印 SKILL.md 绝对路径（agent 靠它读能力文档）；无 prompt_toolkit 时回退 `input()`；
- **undo/redo**：Session 持序列化快照栈（如 XML bytes），`checkpoint()` 在 mutation 前 push，`MAX_UNDO_DEPTH=50`；`status()` 返回 undo/redo 深度供内省；
- **SKILL.md 自动生成**（skill_generator.py，19KB）：正则解析 Click 装饰器 + docstring，重建嵌套命令组路径；双写 canonical（仓库根）+ 包内副本。

### 3.4 预览栈（GUI 适配的关键接口，producer/consumer 分离）

- **设计哲学**：harness 只负责产出 **Preview Bundle**（不可变快照目录），查看器只读消费、**永不渲染**；host（agent/GUI）可把 artifact 回塞模型上下文；
- **Bundle 结构**（`preview-bundle/v1`）：`{manifest.json, summary.json, artifacts/{hero.png, gallery_*.png, preview.mp4, pipeline_diff.json}}`；默认位置 `<project>/.cli-anything/previews/<software>/<recipe>/<bundle_id>/`；bundle_id = 时间戳+sha256；缓存键 = 协议版本+软件+recipe+源指纹（`--force` 绕过）；
- **Live 会话**（`preview-live/v1` + `preview-trajectory/v1`）：`session.json`（可变 head）+ `trajectory.json`（append-only 命令→预览历史，每 step 含 command/耗时/bundle_id/status/stage_label）；
- **廉价内省**：`preview live status --json` 内联返回 `trajectory_summary`（最新 3 步），agent 无需重读 trajectory.json——**省 token 的设计先例**；
- **性能预算**：hero ≤1280px、gallery 3–8 张、clip ≤8s ≤720p、bundle ≤25MB——"cheap enough to use often in agent loops"；
- **渲染真相原则**：预览必须来自真实后端导出/检查路径，**禁止截屏 GUI 窗口、禁止 Python 假渲染**；
- **CLI 消费面**：`cli-hub previews inspect / html / watch / open`（静态 HTML 画廊 + 1.5s 轮询 watch）——**GUI 可以直接复用这套消费协议**（见 §5.4）。

### 3.5 CLI-Hub 生态

- `pip install cli-anything-hub` → `cli-hub list/search/info/install/update/uninstall/launch`；
- `registry.json`（仓库根，GitHub Pages 发布，PR 合并即更新）+ `public_registry.json`（第三方，支持 pip/npm/brew/bundled 多源）；
- 本地缓存 `~/.cli-hub/*_cache.json`（TTL 1 小时，失败回退缓存）；
- **agent 自主安装**：`cli-hub-meta-skill` 让 agent 按自然语言任务自行 search→install→读 SKILL.md 使用；
- 来源标签 `_source`（in-repo / public）——多源合并时防止数据污染（#281 修复）。

### 3.6 平台适配薄壳模式（OpenCode 参考实现）

**共同抽象**：canonical 资源集 `cli-anything-plugin/`（HARNESS.md + commands + guides + repl_skin.py + preview_bundle.py + skill_generator.py + templates）是唯一真相源；每个平台只做一层薄壳，**生成的 Python harness 格式 100% 不变**。

| 平台 | 形态 | 壳的实现 |
|---|---|---|
| Claude Code | Plugin（marketplace） | `/plugin marketplace add HKUDS/CLI-Anything` + `/cli-anything <path>` |
| **OpenCode** | **Command（5 个 md + 同目录 HARNESS.md）** | **`subtask: true` 前注 + `$1/$2` 参数 + "CRITICAL: Read HARNESS.md First"** |
| Codex | Skill（install.sh/install.ps1，自包含，带路径重映射表） | `$CODEX_HOME/skills/cli-anything` |
| OpenClaw / Hermes / Reasonix / Pi | Skill / Extension | SKILL.md 拷入技能目录，绑定平台工具 |
| Qodercli / Copilot CLI | Plugin | 注册脚本 |

**三形态差异**：Skill = 自然语言触发（发现式，无参数槽）；Command = 带 `$1/$2` 参数 + `subtask: true`（OpenCode 先例）；Plugin = 可分发的打包形态。

### 3.7 Token 经济（四条设计原则，无量化数字）

1. **廉价内省**：`preview live status --json` 只回传摘要——agent 以最少的 token 理解状态；
2. **性能预算**：bundle 尺寸/分辨率上限 + 缓存键复用——预览"便宜到可以在 agent 循环里常用"；
3. **渐进式披露**：HARNESS.md v0.2.0 把细节抽到 `guides/` 按需加载（Codex skill 明写"Read referenced files only when they apply"）——**省的是 agent 读文档的 token**；
4. **自描述**：`--help` 自动文档 + JSON 输出消除解析成本。
5. README 明说：把碎片化 API 聚合成一个有状态 CLI，"one tool instead of dozens of raw API calls — stronger capabilities **while saving tokens**"。

**本报告补一笔账（生成期 vs 持续期）**：
- **生成期（一次性成本）**：7 阶段流水线需 frontier 级模型（README 明说 Opus 4.6 / Sonnet 4.6 / GPT-5.4 级），一次生成 + 常需 `/refine` 迭代 2–3 轮——一个软件数万~数十万 token；
- **持续期（每次调用）**：一条结构化命令 + JSON 返回，**小且确定**，远低于 computer use 每步截图的持续成本；
- **结论**：生成期一次性成本换取持续期低成本的长期收益——与 computer use"每步都烧"形成鲜明对比。

### 3.8 Windows 支持现状

- 生成 CLI 的 Click/REPL/JSON 跨平台无依赖；prompt_toolkit 兼容 Windows；
- 已知坑：Claude Code 插件经 bash 执行，Windows 需 Git for Windows（cygpath）或 WSL——**我们不走该路径**（RxyCode 直接 subprocess 调 python/pip，无此问题）；
- codex-skill / hermes-skill / reasonix-skill 均提供 install.ps1；`session.py` 的 `fcntl.flock` 在 Windows 上 ImportError 静默跳过（写锁降级）；
- ArcGIS Pro harness 为 Windows-only（ArcPy SDK + MCP bridge 包装闭源软件的先例）。

### 3.9 局限（必须诚实记录）

1. **生成质量依赖模型强度**：弱模型产出需大量人工修正；
2. **单一 `/cli-anything` 运行常需 `/refine` 迭代**才达生产质量（一次性成本可能翻倍）；
3. 覆盖的软件都有"代码库或官方接口"——**完全闭源且无 SDK 的软件无法 agent-native**（这是"软联系"的边界，本报告 §5.1 决策规则 4 明写不采用 computer use 补位）；
4. 项目自身无 GUI 先例（交互层是 ANSI 终端产物）——GUI 适配需我们自己做（§5.4）。

---

## 4 生态护城河分析

### 4.1 护城河的本质

Codex / Claude Code / Cursor 等主流 agent 的护城河 = **生态**：
- 官方插件市场（Claude Code plugins / Codex plugins / Cursor marketplace）；
- 官方集成（API 授权、云端服务、深度绑定的工具链）；
- 用户习惯沉淀（配置、技能、工作流都在墙内）。

**护城河的脆弱面**：这些生态全部依赖"**与公司联系**"（marketplace 审核、API 授权、账号体系）。任何不依赖公司授权的软件控制通道，都从侧面绕过护城河。

### 4.2 Agent-Native 路线的打破机制

CLI-Anything 证明了一条不依赖任何公司授权的通用路径：

```text
任何有代码库的软件
  → 7 阶段流水线自动生成结构化 CLI（软联系）
  → agent 直接调软件后端（bpy / headless LO / SVG / REST API / MCP 桥）
  → 不经过任何官方插件市场或 API 授权
```

- **生态对比**：CLI-Hub 的 100+ CLI 是社区以"软件能力"为单位组织的，不绑定任何 agent 平台（同一 CLI 可被 Claude Code / Codex / OpenClaw / nanobot / 我们的 RxyCode 共用）；
- **护城河反噬**：Codex 的护城河是"它家的插件+它家的集成"；agent-native 路线让"**软件本身**"成为公共资源——谁的 agent 能调用更多软件，谁就有生态，护城河从"平台侧"转移到"能力侧"。

### 4.3 RxyCode 的定位

| 层 | 现状 | 本次改版后 |
|---|---|---|
| 产品形态 | CLI + Electron Desktop（Phase G） | Desktop 对齐 Codex 交互（GX19–GX27），CLI 同步（F13 已有） |
| 软件控制 | 内置工具 30+（文件/bash/git/web/mcp/skills） | + CLI-Hub 消费（B14）+ 生成器（B15）——**任意软件可接入** |
| token 控制 | Phase B 缓存未落地 | 混合集成：消费零 token、生成一次性、调用小 token（§5.3） |
| 生态 | 无自建市场 | 插件生态（B18/GX24）+ CLI-Hub 借用——**不自建墙，借公共墙** |

**结论**：RxyCode 不复制"平台护城河"，走"**能力护城河**"——只要控制 token 消耗（用户的核心条件），claw 系（OpenClaw / hermes-claw 等靠截图点击吃饭的工具）在 agent-native 能力面前无优势可言。

---

## 5 集成方案决策（CLI-Anything × RxyCode）

### 5.1 为什么必须混合（单一方案论证）

**单一消费（只用 CLI-Hub 现成 CLI）不成立**：
1. CLI-Hub 只有 100+ 社区 CLI，覆盖不到用户的任意软件；
2. 私有/内部/新软件永远等社区贡献——护城河命题不成立（你只是寄生在 HKU 生态上）；
3. "生成能力"才是真正的武器，只消费 = 没拿到武器。

**单一内嵌（只自研生成器）不成立**：
1. 生成需 frontier 级模型 + 数万~数十万 token + 常需 refine 迭代——**每个软件都自研生成 = token 与时间双重爆炸**；
2. 社区已产出的 GIMP/Blender/LibreOffice 等成熟 CLI（2,464 测试验证）直接 `pip install` 零成本可用；
3. 重复造轮子违反"先调研不造轮子"的方法论约束。

**混合 = 互补**：现成的白嫖（消费），没有的自己造（生成），造得好的反哺社区（PR）。

### 5.2 混合的冲突清单与解法（用户关心的问题，逐条回答）

| # | 冲突面 | 冲突内容 | 解法（写进 B14 规范限制） |
|---|---|---|---|
| C-A | 工具名冲突 | `cli-anything-<sw>` 与内置工具（read/write/bash）同名？ | 不会——CLI 工具经**独立桥接器**注册，工具名带 `cli:` 前缀命名空间（`cli:gimp`）；与内置注册表隔离；沿用 D13 工具名冻结纪律（禁止同名覆盖） |
| C-B | pip 依赖冲突 | CLI-Hub 安装的包污染 RxyCode 运行环境 | CLI 运行于**独立 venv**（每 CLI 或共享 cli 环境），经子进程调用；复用子代理隔离先例（ExecSessionManager 独立 shell 会话） |
| C-C | 双轨版本 | 同一软件社区已有 CLI、我们又生成一版 | 决策规则定优先级（§5.1 决策规则）；生成版质量更好 → PR 反哺社区（CONTRIBUTING.md 流程现成） |
| C-D | 发现冲突 | GUI 工具面板同时有内置/CLI 工具 | 来源分组 + 标签（内置 / CLI-Hub / 自生成），G13 能力面板扩展（H19/GX25） |
| C-E | 生成质量 | 生成器产出不达标 vs 直接放弃 | 三级阶梯：生成 → refine → 仍不达标降级为手写 command 包装；记录"生成失败模式"回灌 HARNESS 经验 |

### 5.3 决策规则（何时用什么，写进 B14/B15 卡）

| 优先级 | 条件 | 动作 | token 成本 |
|---|---|---|---|
| 1 | 软件在 CLI-Hub registry | `cli-hub install` 消费 | 零（仅安装） |
| 2 | 不在 registry 且**有源码**（GitHub URL / 本地目录） | 内嵌生成器跑 7 阶段 + 需要时 refine | 一次性（数万~数十万） |
| 3 | 不在 registry 且**无源码但有官方 SDK/API** | MCP 桥模式（ArcGIS Pro live-bridge 先例） | 一次性 + 调用成本 |
| 4 | 完全闭源且无 SDK | **不采用**（软联系的边界；computer use 不补位） | — |

### 5.4 GUI 适配设计（CLI 出身 → GUI 的适配路径）

**核心依据**：CLI-Anything 的 producer/consumer 分离哲学——"GUI 完全可以作为新 consumer 驱动同一命令面"（源码实证：交互层与业务层分离，每条命令同时是一次性子进程调用）。

| CLI-Anything 组件 | GUI 适配方案 | 落卡 |
|---|---|---|
| Click 命令面 | 工具面板化：每条命令 → 表单化调用（参数 → 表单字段），或直接复用 `cli:gimp <subcommand> --json` 通道 | H19 / GX25 |
| `--json` 输出 | 结构化结果渲染（列表/表格/状态卡） | H19 / GX25 |
| ReplSkin REPL | 不做图形化 REPL（维护成本高）；保留子进程调用 + GUI 表单 | GX25 |
| **预览栈**（bundle/trajectory） | **产物画廊**：hero/gallery/video/JSON 渲染组件；`cli-hub previews html/watch` 数据源复用 | H19 / GX25 |
| SKILL.md | 工具目录：安装 CLI 后自动导入其 SKILL.md 作为能力说明 | H19 / GX25 |
| `session status`（undo 深度等） | 状态面板数据源 | GX25 |
| CLI-Hub registry | 内置"CLI 工具商店"面板（浏览/搜索/安装/启停） | B14 / GX25 |

### 5.5 Token 控制方案（用户的核心条件）

1. **消费型集成零生成成本**（决策规则 1）；
2. **生成一次性成本**，且挂起条件：Phase B 缓存未落地前 B15 不启动（C8）；
3. **调用小 token**：结构化命令 + JSON（无截图）；
4. **预览性能预算**沿用 CLI-Anything 规范（≤25MB/1280px/8s）；
5. **廉价内省**惯例：状态查询只回传摘要（trajectory_summary 先例）；
6. **缓存复用**：bundle 缓存键 + 本地 registry 缓存（TTL 1h）；
7. 独立 venv 隔离防依赖膨胀（C-B）。

---

## 6 GUI 全量规格（Codex 对齐 · 写进 GX/H 卡的规范限制）

### 6.0 总纲

- 布局/界面/交互**直接照抄 Codex**（用户指令："能抄多少抄多少"）；hover 高亮亮度、圆角、间距等视觉值以 **Codex 实机取样为准**（开发时截图对照，卡内写明取样要求）；
- 视觉规格统一收敛到 design tokens（H17 扩展现有 G12/G15 tokens）。

### 6.1 会话栏三分类（置顶 / 项目 / 最近）

- 会话栏（左栏）自上而下三个分类区：**置顶 / 项目 / 最近**（用户确认：'指定'是笔误，实际是'置顶'；'由下往上'是字面表述，标准顺序自上而下）；
- **归属规则**：置顶 = 用户 pin 的会话（pin 状态已由 GX8 定义，归并到本分类）；项目 = 项目目录树（每项目可展开其会话）；最近 = 未归类到项目也未置顶的会话；
- 分类标题：次要灰字体（design token secondary text，随主题）；
- **折叠交互**：分类均可独立展开/收起；收起时标题右侧显示 `>` 符号（展开态指向下），与标题间距 4px；
- **hover**：分类标题 hover 高亮（亮度抄 Codex：浅色 ≈ rgba(0,0,0,0.06)，深色 ≈ rgba(255,255,255,0.08)，以实机取样修正）；
- 置顶会话固定在该分类顶部（GX8 pin 语义扩展）。

### 6.2 项目目录

- 项目条目 hover 高亮（同 6.1 亮度）；点击项目名一次收起其会话、再点展开；
- 项目置顶 / 删除（**删除映射不删文件**，数据保留可恢复，与回收站联动 B17）；
- 项目目录设置入口（新增/移除项目目录、默认目录）；在项目目录内"新建会话"（目录 hover 菜单 / composer 顶部）。

### 6.3 会话条目与运行状态

- 会话置顶（pin，GX8）；会话删除 → 进回收站（删映射）；
- **运行状态视觉（抄 Codex）**：
  - 运行中：条目右侧**转圈动画**（圆环旋转）；
  - 完成：**蓝点**替代转圈位置（同位置平滑过渡）；
  - 停止/异常：OS 系统通知（复用 GX13 通知机制）+ 条目错误态徽标；
  - 正在运行的会话：条目**常驻高亮**（同 hover 亮度，保持不灭）；
- 状态一律为后端状态机（B5）的投影，纯视觉不改变业务语义（§5.2 铁律）。

### 6.4 设置页（左下角入口 + 8 分区）

- **入口**：左下角圆角矩形框（圆角 ≈ 6px，以取样为准），内含**设置图标 + "设置"二字**；hover 高亮（同 6.1）；点击展开；
- **8 分区（左导航列表）**：
  1. **回收站**：垃圾桶图标；已删除聊天列表（名称/删除时间）；每条"恢复"；**"清空回收站"按钮 → 弹窗确认（风险操作，明示"将永久删除会话记录与关联文件"）**（用户确认）；
  2. **常规**（全抄 Codex）：语言、启动行为（恢复上次会话）、默认项目目录、开发者选项等；
  3. **外观**（全抄 Codex）：主题（浅/深/跟随系统/高对比，现有 system/light/dark 扩展）、自定义主题、字体/字号、界面密度；
  4. **模型选择**：当前会话模型切换（对接现有 models/set_active，D5 已实现）；
  5. **模型添加**：AddModelPanel（D5 已实现，前端直接对接，不改后端）；
  6. **技能管理**：Skills 列表/启用/禁用（对接现有 skill_manager.py）；
  7. **MCP 服务管理**：MCP server 增删/启停/连接状态/工具列表（对接现有 mcp/ + G13 计划）；
  8. **团队与模型（预留）**：多 Agent 开关（F10 `settings.agents.enabled`）、多模型角色配置（H10 三层折叠对齐）——后端未合入 → 分区隐藏或显示 BLOCKED_PREREQUISITE（禁止 mock）。

### 6.5 i18n 语言本地化

- 启动：Electron `app.getLocale()` 获取系统语言 → 首次进入按系统语言显示；
- 切换：常规设置可选语言，持久化（localStorage/settings），重启保持；
- **边界**：只影响 GUI 界面文案（技能→Skills、设置→Settings）；**不影响对话中模型的回复语言**；
- 架构：`locales/{zh-CN,en}.json` 起步（用户确认首批两种），全部 UI 静态文案经 `t()` 取词；动态内容（会话文本/工具输出）不入 i18n；后续语言只加文件不加机制。

### 6.6 插件生态

- 插件形态（借鉴 Codex plugins + CLI-Anything SKILL.md）：**插件 = 命令 + 技能 + 工具/MCP 配置的组合包**（manifest 声明）；
- 市场页：浏览/搜索/安装/卸载/启停（来源：本地目录 + 远程 registry）；
- 与 G13 的关系：G13 是"已安装能力统一入口"，插件市场是"获取来源"，设置页技能/MCP 管理是"细粒度控制"——三者并存不冲突。

### 6.7 定时任务

- 前端：设置页分区或独立面板——任务列表（名称/触发规则/动作/启停/编辑/删除）；
- 触发规则：间隔（每 N 分钟/小时/天）+ 指定时间；
- 动作：运行指定会话/命令/技能；
- 后端：基于现有 `scheduler/`（cron.py + manager.py）扩展 + 持久化 + 崩溃恢复（B16）。

### 6.8 多 Agent / 多模型接口预留

- 设置页"团队与模型"分区（6.4-8）；
- GX19 多 Agent 活动可视化（委派树 + 成员状态灯 + 中转消息流 + 预算条，消费 E4 AgentEvent）——上轮多 agent 报告遗留，本轮并入；
- 前端协议预留：protocol/schema.json 预留 `agent_*` 事件域类型（schema 占位 + capability 门控，不实现）。

### 6.9 跨平台约束（Windows / Linux / macOS 三端适配）

> 用户补充决策（2026-08-12）：所有新增卡必须适配 Linux 与 macOS，不只 Windows。现有基础：Electron 打包目标已含 mac/linux（H13）、`config/credential_store.py` 已跨平台（Windows DPAPI / macOS Keychain / Linux Secret Service）、主题 system/light/dark 已有。

各功能跨平台差异点（写入对应卡的规范限制）：

| 功能 | 落卡 | 跨平台要点 |
|---|---|---|
| 系统语言获取 | H14/GX22 | `app.getLocale()` 三端一致；macOS 返回 `zh-Hans-CN` 等变体需归一化映射 |
| OS 通知 | H17/GX27/GX13 | 三端 API：Windows（toast）/ macOS（UserNotifications）/ Linux（libnotify/dbus）；Electron `new Notification()` 统一，Linux 需检查 libnotify 缺失降级（应用内横幅） |
| 安全存储 | GX26（模型添加） | 已有 credential_store 跨平台（DPAPI/Keychain/Secret Service），卡内注明复用，不新造 |
| 独立 venv | B14 | venv 路径三端差异（`Scripts\python.exe` vs `bin/python`）；激活方式差异；shebang 处理 |
| CLI 子进程 | B14 | `shutil.which` 三端 PATH 语义一致；`.exe` 后缀探测差异处理 |
| 定时任务 | B16 | cron 语义跨平台：Windows（Task Scheduler）/ macOS（launchd）/ Linux（cron/systemd-timer）——**统一在应用层实现间隔调度（asyncio），不依赖系统 cron**，保证三端一致 |
| 文件路径 | H15/B17（回收站映射） | 路径 canonicalize 三端（大小写敏感性 Windows 不敏感 vs Linux 敏感）；删除映射不涉及文件删除（purge 时注意） |
| 打包 | H13（修订） | 打包目标已含三端（nsis+dmg+AppImage/deb）；新 locale 资源入包；三端 smoke 测试加入验收命令 |
| hover/圆角取样 | GX20/GX26/GX27 | Codex 实机取样在 Windows 主平台进行，macOS（圆角/阴影观感）与 Linux（无标题栏窗口）需二次视觉验收（Grok 范围） |
| GUI 测试 | H14-H19 | 前端测试三端跑通：`npm run test` + 打包 smoke（现有 H13 机械门扩展） |

**通用卡内条款（所有新卡统一追加）**：
- 验收命令默认在 Windows 主平台执行，**打包 smoke 必须覆盖 macOS/Linux 构建目标**（现有 H13 打包链已含，新卡验收引用）；
- 涉及系统 API 的（通知/语言/安全存储）按上表平台差异点实现与测试；
- 禁止引入仅 Windows 可用的依赖（CLI-Anything 的 cygpath 问题即反例——我们不经过 bash 执行，直接 subprocess 调用 python/pip，天然规避）。

---

## 7 文档分派总表（阶段 2 修订依据）

> 三份文档：`PHASE-G-BACKEND.md`（B 卡）· `PHASE-G-FRONTEND.md`（H 卡）· `PHASE-G-DESKTOP.md`（GX 卡，P3 新增批）。

### 7.1 新增卡总表（20 张）

**后端（PHASE-G-BACKEND.md，B 卡格式 `### PhaseG-B#`）**

| 卡 | 标题 | P / 工时 / 依赖 | 协议变化 | 关键内容 |
|---|---|---|---|---|
| B14 | CLI-Hub 接入与 CLI 工具桥接器 | P1 / 3–4d / D 子代理通道 | `cli/install` `cli/launch` `cli/list`（GXn-PROTO 登记） | 独立 venv 隔离、registry 缓存（TTL 1h）、`cli:` 前缀注册、来源标签；冲突解法 C-A~C-E |
| B15 | 生成器能力（HARNESS 7 阶段技能化） | P2 / 2–3d / B14 | none | HARNESS.md vendor + 7 阶段指令模板（OpenCode 参考实现）、refine/validate；**挂起条件**：Phase B 缓存未落地不启动 |
| B16 | 定时任务调度器 | P1 / 3–4d / B5+B12 | `schedule/*`（GXn-PROTO 登记） | 基于现有 scheduler/（cron.py+manager.py）扩展、持久化、崩溃恢复、对齐 B12 |
| B17 | 回收站后端 | P1 / 2–3d / B5 | thread 元数据 new_optional_field：`deleted_at`/`restored_at`；`thread/purge` | 删映射不删数据、恢复、**清空（永久删除含文件）**、索引排除（GX8 纪律） |
| B18 | 插件注册与市场后端 | P2 / 3–4d / B11 | `plugin/*`（GXn-PROTO 登记） | 插件 manifest（命令+技能+工具/MCP 组合）、本地+远程来源、安装校验 |

**前端（PHASE-G-FRONTEND.md，H 卡格式 `### PhaseG-H#`，owner 默认 Composer 2.5）**

| 卡 | 标题 | P / 工时 / 依赖 | Grok 范围 | 关键内容 |
|---|---|---|---|---|
| H14 | i18n 语言本地化基建 | P1 / 3–4d / H1 | 视觉抽查 | locale JSON（zh-CN+en）、`t()`、`app.getLocale()`、持久化；边界：只改 GUI 文案 |
| H15 | 会话栏三分类重构 | P0 / 3–4d / H5+GX8 | 布局/折叠视觉 | 置顶/项目/最近投影、`>` 符号、hover 取样、回收站投影数据源、置顶分组 |
| H16 | Settings 页重构框架 | P0 / 3–4d / H11+B10 | 分区布局 | 左下角入口（圆角框+hover）、8 分区导航骨架、懒加载、团队与模型分区（对齐 H10） |
| H17 | 运行状态视觉系统 | P0 / 2–3d / H12+B5 | 动画/色彩 | 转圈/蓝点/停止通知联动/常驻高亮、tokens 扩展、纯投影不改变业务语义 |
| H18 | 多 Agent 前端契约预留 | P1 / 2–3d / H16 | 无 | AgentEvent 消费骨架（E4 占位）、capability 门控、未合入 → 隐藏/BLOCKED（不 mock） |
| H19 | CLI 工具面板与预览画廊 | P1 / 3–4d / H7+B14 | 画廊视觉 | 内置/CLI-Hub/自生成分组、bundle 渲染（hero/gallery/video/JSON）、边界：文件渲染≠PHASE-I 附件协议 |

**增强（PHASE-G-DESKTOP.md，GX 卡格式 `## GX#`，P3 · Codex 对齐批）**

| 卡 | 标题 | P / 工时 / 依赖 | owner | 关键内容 |
|---|---|---|---|---|
| GX19 | 多 Agent 活动可视化 | P1 / 3–4d / F12+E4 | frontend + backend | 委派树/成员状态灯/中转消息流/预算条；BLOCKED：E/F 未实施 |
| GX20 | 会话三分类 + 折叠交互 | P0 / 3–4d / B5+H15+GX8 | frontend + backend | 规格 §6.1–6.2、`deleted_at`/pin 字段、与 GX8 pin 整合 |
| GX21 | 回收站 UI | P1 / 2–3d / B17+H15 | frontend | 垃圾桶入口、列表、恢复、**清空+弹窗确认（风险操作）** |
| GX22 | i18n 语言本地化 | P1 / 2–3d / H14 | frontend | 文案清单映射表（技能→Skills 等）、切换生效范围 |
| GX23 | 定时任务 UI | P2 / 2–3d / B16 | frontend + backend | 任务列表/触发规则/启停/编辑/删除 |
| GX24 | 插件生态（市场+管理） | P2 / 3–4d / B18 | frontend + backend | 市场浏览/安装/卸载/启停、manifest 校验、与 G13/技能/MCP 关系声明 |
| GX25 | CLI-Anything 工具接入 + 预览画廊 | P1 / 3–4d / B14+H19 | frontend + backend | 决策规则 4 条、来源标签、画廊渲染、token 控制声明 |
| GX26 | 设置页重构（8 分区） | P0 / 4–5d / H16+B10+D5 | frontend + backend | 常规/外观/模型选择/模型添加（D5）/技能（skill_manager）/MCP（mcp/）/回收站/团队与模型预留 |
| GX27 | 运行状态视觉（转圈/蓝点/通知/高亮） | P0 / 2–3d / H17+GX13 | frontend | 交互规格、Codex 亮度取样、动画规格、GX13 通知联动 |

### 7.2 修订现有卡

| 卡 | 修订内容 |
|---|---|
| GX8 | pin 与三分类整合（置顶分类归属） |
| GX13 | 停止状态通知联动（GX27） |
| G11 / G12 | 设置分区与 GX26 对齐 |
| H5 | 会话中心对接 H15 分类投影与回收站数据源 |
| H7 | 工具工作台对接 H19 分组接口 |
| H11 | Settings 对接 H16 分区骨架 |
| H12 | 通知与 H17 停止联动 |
| H13 | 打包含 locale 资源 |

### 7.3 同步更新清单（16 处，交叉引用破坏防护）

| # | 位置 | 同步内容 |
|---|---|---|
| S1 | FRONTEND Part2 §0 任务总览 | GX 卡清单加 GX19–GX27 |
| S2 | FRONTEND Part2 §4 增强卡表 | 加 9 行（GX19–GX27 前端部分 + 消费协议） |
| S3 | FRONTEND 头部 | "PhaseG-H1–H13" → "PhaseG-H1–H19" |
| S4 | FRONTEND §1.1 结构图 | "H1–H16" 历史表述修正 |
| S5 | DESKTOP §2 GXn-PROTO 触发清单 | 加 GX20/23/24/25 |
| S6 | DESKTOP §3 出口标准 | 全量出口 → GX1–GX27；新增 P3 批出口定义 |
| S7 | DESKTOP §3 并行建议表 | 加 P3 GX19–GX27 批次（方法域划分：thread/pin、thread/restore、schedule/*、plugin/*、cli-tool/*） |
| S8 | DESKTOP §8 增强阶段概览 | GX1–GX18 → GX1–GX27 |
| S9 | DESKTOP Part3 标题 + §0 总览表 | 范围标题 + 9 行 |
| S10 | DESKTOP §3 跨端 GX 卡清单 | 加 GX20/23/24/25/26 |
| S11 | research/2026-08-10-gui-agent-benchmark.md | **不改**（历史事实）；新卡立项依据 = 本报告 |
| S12 | PHASE-H-MULTI-MODEL-COLLABORATION.md | 加一行引用：设置页团队与模型分区对齐 GX26 |
| S13 | PHASE-I-MULTIMODAL.md | 加边界声明：GX25 画廊=文件渲染，不隐含图片附件协议 |
| S14 | README.md | Phase G 描述行微调（Codex 风定位） |
| S15 | 00-EXECUTION-PLAN.md | 旧 Phase 编号表第 5–8 行 + 正文 2 处修复（上轮多 agent 报告遗留） |
| S16 | DESKTOP "主链 26 卡"（7 处） | 不动（主链未变）；FRONTEND 侧表述对齐 |

### 7.4 耦合结构风险清单（12 项，写入卡内规范限制）

| # | 耦合点 | 对策 |
|---|---|---|
| C1 | protocol/schema.json + TS codegen | 全部走 GXn-PROTO 子卡登记（探针→变更单→生成物随 commit） |
| C2 | B5 Thread 服务共用 | 操作=new_method、字段=new_optional_field 纪律；复用 B5 现有 mutation 优先 |
| C3 | desktop-app 实际结构 components/+hooks+/lib/ vs 文档 features/ | 涉及文件标注"以实际结构为准（探针），与 GX8 先例一致" |
| C4 | scheduler/ 已存在 | B16 基于现有扩展，先读 README/代码再设计 |
| C5 | skill_manager/skill_tool/mcp/ 已存在 | GX26 只做 UI 对接，禁止新造后端 |
| C6 | D5 模型管理已实现 | GX26 模型选择/添加直接对接 AddModelPanel |
| C7 | E4 AgentEvent / F12 未实施 | capability 门控 + BLOCKED_PREREQUISITE；禁止 mock |
| C8 | Phase B 缓存未落地 | B15 挂起；B14 只做消费型集成 |
| C9 | CLI-Hub pip 包污染 | 独立 venv + `cli:` 前缀命名空间（D13 纪律） |
| C10 | i18n 替换全局文案 | H14 基建先行；GX22 按 locale 清单逐组件核对；现有测试引用文案同步 |
| C11 | 五态铁律 + §5.2 视觉不改变业务语义 | H17 纯投影，状态以 B5 状态机为准 |
| C12 | P3 批并行协议方法名 | 方法域划分（thread/pin、thread/restore、schedule/*、plugin/*、cli-tool/* 互不重叠） |

---

## 8 文档规范约束（新增卡格式合规）

新增卡必须逐字段对齐现有格式（样例：`PHASE-G-DESKTOP.md` GX8 卡、`PHASE-G-FRONTEND.md` H5 卡、`PHASE-G-BACKEND.md` B5 卡）：

```text
GX 卡格式：
  ## GX# · 标题
  **借鉴来源**：...
  **优先级/工时**：P# / #d / 依赖：... / **owner: frontend + backend ...**
  **背景**：...
  **涉及文件**：- `路径`（新增/修改）
  **规范限制**：- （协议归属冻结/语义冻结/纪律引用）
  **开发步骤**：1. ...（后端先行 red→实现→前端 red→实现→接线→五态）
  **示例代码**：```python/ts```
  **验收命令**：```powershell```（可复制；含回归门禁；基线按批次出口执行）
  **完成判据**：- [ ] ...
  **Commit**：```feat(desktop): GX# ...```
  ---

H 卡格式（附加）：
  `P#` / #d / 依赖 / **owner: Composer 2.5**
  **对应基线**：...。**涉及文件**：...。**协议变化**：...。**Grok**：...
  **必须实现**：...
  **完成判据**：- [ ] ...（四件套：入口/功能/契约/回滚）

B 卡格式（附加）：与 H 卡对称；**协议变化**行 + 契约测试 + 交接包
```

**共同硬约束**：五态铁律（空/加载/错误/窄窗/深色）；禁止 mock 假协议（后端未合入 → BLOCKED_PREREQUISITE）；禁止像素硬编码；状态色语义 WCAG AA；单卡单 commit；批次 baseline 出口（§1-12/§2）按既有纪律执行；GXn-PROTO 子卡登记机制（协议类 GX 卡统一出口）。

---

## 9 证据清单

**网络来源**：
- HKUDS/CLI-Anything（Apache-2.0，46.9k★）：https://github.com/HKUDS/CLI-Anything （README / HARNESS.md / PREVIEW_PROTOCOL.md / opencode-commands/ / cli-anything-plugin/ / cli-hub/ 源码实证 2026-08-11）
- CLI-Anything 技术报告《Towards Agent-Native Computer Use》：https://arxiv.org/abs/2606.03854
- Anthropic《How we built our multi-agent research system》（2025-06-13）：https://www.anthropic.com/engineering/multi-agent-research-system
- Cognition《Don't Build Multi-Agents》（2025-06-12）：https://cognition.ai/blog/dont-build-multi-agents
- 微软《Magentic-One》（2024-11-04）：https://www.microsoft.com/en-us/research/articles/magentic-one-a-generalist-multi-agent-system-for-solving-complex-tasks/
- MAST《Why Do Multi-Agent LLM Systems Fail?》（arXiv 2503.13657，Berkeley）：https://arxiv.org/abs/2503.13657
- Computer Use 内核机制：公开技术知识（截图→视觉→动作坐标循环），非官方文（Anthropic 官网 2026-08 无法直连，已标注）

**本地来源**：
- `research/2026-08-08-8-projects-value-report.md`（八项目源码级调研）
- `research/2026-08-10-gui-agent-benchmark.md`（10 款 GUI agent 基准，GX1–GX18 立项依据）
- `research/2026-08-11-multiagent-expert-team-design-research.md`（多 Agent 专家团设计决策报告，C1–C6 修订建议 + GX19 立项）
- `PHASE-G-DESKTOP.md` / `PHASE-G-FRONTEND.md` / `PHASE-G-BACKEND.md`（合并版，2026-08-11）
- `00-EXECUTION-PLAN.md`（旧 Phase 编号表，S15 修复点）
- 代码实证：`scheduler/`（cron.py+manager.py）、`tools/skill_manager.py`、`tools/skill_tool.py`、`mcp/`、`config/credential_store.py`、`protocol/schema.json`、`tools/registry.py`、`core/governance.py`、`appserver/agent_worker.py`（存在性核查 2026-08-12）；`.worktrees/codex-desktop-cd/frontend/desktop-app/`（Electron 39 + React 19 + TS，components/+hooks+/lib/ 实际结构，D1–D8 落地记录）
