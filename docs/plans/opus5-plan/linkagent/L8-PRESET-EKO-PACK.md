# L8 · 预置社区 EKO 包

> **前置**：[`L3-RETRIEVAL-AND-SCOPE.md`](./L3-RETRIEVAL-AND-SCOPE.md) 全部完成（域硬门必须先在）
> **可并行**：与 L4 / L5 / L7 并行做，不阻塞它们
> **产出**：新用户装完应用、一条经验都没有的时候，森林里已经有一批可用的顶层分区 EKO
> **工时**：5 天
> **卡数**：5 张（L8-1 ~ L8-5）
>
> **干活前读** [`../COMPOSER-2.5-PLAYBOOK.md`](../COMPOSER-2.5-PLAYBOOK.md) §2。**一次只做一张卡。**

---

## §0 这一阶段解决的问题：冷启动

LinkAgent 的全部价值来自 EKO 森林。**新用户装完应用，森林是空的**，于是：

| 天数 | 森林状态 | 用户体验 |
|---|---|---|
| 第 1 天 | 0 条 EKO | 和裸 RxyCode **完全一样**，看不出装 LinkAgent 有什么用 |
| 第 1 周 | 几条个人 EKO | 偶尔命中一次 |
| 第 1 月 | 几十条 | 开始像回事 |

**前两周是流失窗口。** 预置包把第 1 天的体验从"完全一样"变成"已经有一层可用的工程实践"。

### 但预置的必须是正确的那种东西

> ⚠ **不要预置个人偏好。** 论文的冻结语料 `EKO Corpus v2`（304 条）是**别人的**个人偏好——"某某喜欢简洁回复""某某关心隐私"。把它塞给新用户是负资产：既不准，`scope.users` 也对不上，检索时会被过滤掉。**那份语料只做测试装置，不进预置包。**

预置的是**领域分区的顶层锚点**：从社区维护的高质量 skill 提炼出来的通用工程实践。判断标准是"这条经验换个人还成立吗"——成立才能预置。

| 能预置 | 不能预置 |
|---|---|
| 改行为前先写失败的测试 | 我喜欢 4 空格缩进 |
| 一次改动只做一个垂直切片，改完就验证 | 我讨厌 emoji |
| 提交信息说清楚 why 不是 what | 回复请简短 |
| 依赖升级前先看 CHANGELOG 的 breaking 段 | 用中文回答我 |

左边这些**换谁都成立**，右边的**只对一个人成立**。

---

## §1 分层模型（先读 [`00-OVERVIEW`](./00-OVERVIEW-AND-ARCHITECTURE.md) §10）

```
Tier community  owner=shared  优先级 DEFAULT(10)              path: <domain>/community/<slug>
Tier imported   owner=用户    优先级 DEFAULT(10)              path: <domain>/imported/<slug>
                    ↑ 都被覆盖
Tier personal   owner=用户    优先级 PERSISTENT_PERSONAL(40)  path: <domain>/personal/<slug>
```

**五级优先级已经把覆盖语义表达好了，不需要新机制。** 用户蒸馏出的"我们项目不写单测，靠集成测试兜底"（40）自动压过社区预置的"改行为前先写失败的测试"（10）。

> **`imported` 层是 [`L10`](./L10-SKILL-INTEROP.md) 加的第三层**——用户手动导入的 SKILL.md。它和社区层同优先级，理由一样：**没有该用户的执行证据支撑**。权威定义在 [`APPENDIX-C §4.6`](./APPENDIX-C-INTERFACE-CONTRACTS.md)。
>
> 做 L8 时可以先只管 `community` 和 `personal`，但**别把 `tier` 写成二值布尔**（比如 `is_preset`），留成枚举。

### 两条隔离必须守住

| 隔离 | 规则 | 违反的后果 |
|---|---|---|
| **id 命名空间** | 社区 EKO 的 id 必须以 `eko-community-` 开头 | 整包替换时误删用户的个人经验 |
| **owner 通配** | `scope.users = ["*"]` **只有预置包构建流程能设**；蒸馏路径产出带 `*` 的候选一律拒绝 | 模型能自己造一条"所有人都适用"的经验，绕过个人化边界 |

第二条和 L3 定的 `domain: ["*"]` 是同一类规则：**最强的断言必须由最可信的一方下**。

---

## §2 素材来源（已调研，2026-07-31）

社区 skill 生态已经成熟，不需要自己写内容，**策展就行**。

| 仓库 | Star | License | 特点 | 用途 |
|---|---|---|---|---|
| [`anthropics/skills`](https://github.com/anthropics/skills) | 165k | Apache-2.0（部分子目录例外） | 官方，`SKILL.md` 格式的定义者 | 格式基准 + 少量通用实践 |
| [`addyosmani/agent-skills`](https://github.com/addyosmani/agent-skills) | 81k | MIT | 24 条**研发生命周期**技能：TDD、增量实现、代码审查、依赖审计、性能 | **主力来源**，正好是跨语言通用实践 |
| [`VoltAgent/awesome-agent-skills`](https://github.com/VoltAgent/awesome-agent-skills) | 29k | MIT | 1000+ 条，来自 Anthropic / Google / Vercel / Stripe / Cloudflare / Sentry / Trail of Bits 等官方团队 | **领域专项**来源（前端、安全、云） |
| [`sickn33/agentic-awesome-skills`](https://github.com/sickn33/agentic-awesome-skills) | 43.7k | MIT | 1987+ 条，300 contributors | 补充；但数量大、质量不齐，需要严筛 |

> ⚠ **`anthropics/skills` 的 `skills/docx`、`skills/pdf`、`skills/pptx`、`skills/xlsx` 四个子目录是 source-available 不是开源**，License 不允许再分发。**明确排除。** 策展脚本里要有硬编码的排除名单。

### 别做的事

| ❌ | 理由 |
|---|---|
| 运行时从 GitHub 拉 skill | 网络依赖、供应链风险、不可复现。**策展是离线的，产物随应用分发** |
| 把 1987 条全导进去 | 检索会被稀释。**目标是每个域 5–15 条**，宁缺毋滥 |
| 让 LLM 自动决定收哪条 | 预置包是所有用户共享的最高杠杆资产，必须人工过一遍 |

---

## §3 任务卡

### L8-1 · 预置包的数据格式与装载

`P0` / 1 天 / 依赖：L3 全部

**背景**

先定格式再谈内容。预置包是一个**冻结产物**，和用户的 EKO 库分开存放、分开管理。

**涉及文件**

| 文件 | Grep 锚点 | 改法 |
|---|---|---|
| `src/linkagent/preset/__init__.py` | 新建 | — |
| `src/linkagent/preset/loader.py` | 新建 | 装载 + 校验 |
| `src/linkagent/preset/packs/` | 新建目录 | 存放 `.json` 包 |
| `tests/preset/test_loader.py` | 新建 | — |

**已经替你决定好的**

| 决定 | 理由 |
|---|---|
| 预置包是**单个 JSON 文件**，不是目录树 | 冻结产物只读，单文件好校验、好比对、好嵌进安装包 |
| 包里带 **`pack_version` + 内容 SHA256** | 更新时能判断变没变；校验失败就整包拒绝装载 |
| 装载走**内存合并**，不写进用户的森林文件 | 用户目录里只有用户自己的东西，卸载预置包 = 改个开关，零残留 |
| 每条预置 EKO 带 **`source_url` + `source_license` + `source_commit`** | License 合规是硬要求，不是可选项 |
| 装载时**强制校验** id 前缀与 `scope.users == ["*"]` | 格式错的包宁可不装 |

**包格式**

```jsonc
{
  "pack_version": "2026.08.1",
  "content_sha256": "…",           // 对 ekos 数组规范化序列化后的 hash
  "generated_at": "2026-08-01T00:00:00Z",
  "generator": "linkagent.preset.curate v1",
  "ekos": [
    {
      // 一条完整的 FormalEKO,字段与 L1 的 schema 完全一致
      "id": "eko-community-tdd-red-green-refactor",
      "version": "1.0.0",
      "path": "engineering/community/test-driven-development",
      "scope": { "users": ["*"], "domain": ["*"], "task_types": ["code_change"] },
      "provenance": {
        "source_url": "https://github.com/addyosmani/agent-skills/blob/…/SKILL.md",
        "source_license": "MIT",
        "source_commit": "…",
        "curated_by": "human",
        "curated_at": "2026-08-01"
      }
      // …其余字段
    }
  ]
}
```

> 注意 `domain: ["*"]`：L3 规定通配只能由用户设。**预置包是第二个例外**，理由和用户一样——它是可信来源，而且这类跨语言工程实践本来就不属于任何单一域。这条例外要**写进 L3 的 domain 门代码注释里**，别让后来人以为是 bug。

**操作步骤**

1. `src/linkagent/preset/loader.py`：

```python
"""预置社区 EKO 包的装载与校验。

## 预置包不进用户的森林文件

装载是内存合并:引擎检索时同时看用户森林和已装载的预置包,但预置包
永远不写进 ~/.linkagent/forest/。这样:

- 用户目录里只有用户自己的东西,备份和迁移干净
- 关掉预置包 = 改一个开关,零残留
- 升级预置包 = 换一个文件,不需要 diff/merge 用户数据

## 为什么校验这么严

预置包是所有用户共享的资产,一条错误的 EKO 会影响每个人。装载时:

- content_sha256 对不上 -> 整包拒绝(分发过程被篡改或损坏)
- 有 id 不以 eko-community- 开头 -> 整包拒绝(会污染用户 id 空间)
- 有 scope.users != ["*"] -> 整包拒绝(不是共享 EKO,不该在这里)
- 缺 provenance.source_license -> 整包拒绝(License 合规)

宁可不装,不要装一个坏的。
"""


class PresetPackError(Exception):
    """预置包校验失败。装载方必须当作「没有预置包」继续运行,不要崩。"""


def load_pack(path: Path) -> list[FormalEKO]:
    """装载并校验预置包。校验失败抛 PresetPackError。"""
```

2. 校验函数拆开写，每条规则一个函数，每条规则一个测试。
3. `tests/preset/test_loader.py`：好包能装、四类坏包各拒一次。

**验收**

```bash
pytest tests/preset/test_loader.py -v
```

- [ ] 合法包能装载，条数正确
- [ ] SHA256 不匹配 → `PresetPackError`
- [ ] id 前缀错 → `PresetPackError`
- [ ] `scope.users` 不是 `["*"]` → `PresetPackError`
- [ ] 缺 `source_license` → `PresetPackError`
- [ ] 装载后 `~/.linkagent/forest/` **没有任何新文件**（这条必须真的断言文件系统）

**禁止**

- ❌ 装载失败时崩掉整个应用——降级成"没有预置包"
- ❌ 把预置 EKO 写进用户森林
- ❌ 运行时从网络拉包

---

### L8-2 · 离线策展脚本（skill → EKO）

`P0` / 1.5 天 / 依赖：L8-1 + **[`L10-2`](./L10-SKILL-INTEROP.md)**

**背景**

`SKILL.md` 和 `FormalEKO` 不是一回事。前者是给人和模型读的散文，后者是结构化的可执行知识对象。这张卡做转换。

> ⚠ **这张卡就是反向映射（Skill → EKO）的离线批量版。** 运行期版本是 [`L10-3`](./L10-SKILL-INTEROP.md)，两者**共用 [`L10-2`](./L10-SKILL-INTEROP.md) 的解析器 `linkagent.skillio.parser`**。
>
> **不要在 `curate.py` 里自己写一套 SKILL.md 解析。** 两套解析逻辑会长出不同的字段习惯，然后离线策展和运行期导入产出的 EKO 结构就不一致了。`curate.py` 只负责：抓取仓库 → 调 `parse_skill_markdown()` → 人工 review → 打包。

**涉及文件**

| 文件 | Grep 锚点 | 改法 |
|---|---|---|
| `src/linkagent/preset/curate.py` | 新建 | 策展 CLI，**调用** `skillio.parser` |
| `src/linkagent/skillio/parser.py` | L10-2 建的 | **不改**，只调用 |
| `tests/preset/test_curate.py` | 新建 | — |

**字段映射**（与 [`L10-2`](./L10-SKILL-INTEROP.md) 的映射表一致，这里只列 L8 特有的补齐部分）

| `SKILL.md` | `FormalEKO` | 怎么转 |
|---|---|---|
| frontmatter `name` | `id`（加前缀、slugify） | 机械转换 |
| frontmatter `description` | `description` | **直接用**。L3 定了检索只看 `description`，所以这个字段质量决定检索质量 |
| 正文的"何时使用" | `preconditions` | LLM 辅助抽取 + **人工确认** |
| 正文的步骤 | `procedure` | LLM 辅助抽取 + **人工确认** |
| — | `scope` | **人工填**。域归属是最关键的判断 |
| 仓库元信息 | `provenance` | 机械转换 |
| — | `dependencies` / `conflicts` | **留空**。L6 默认关闭，没必要现在填 |
| — | `validation_evidence` | 填策展记录，**不要伪造执行证据** |

**已经替你决定好的**

| 决定 | 理由 |
|---|---|
| 策展是**半自动**：LLM 出草稿，人工逐条过 | 预置包是共享资产，杠杆最高的地方最不能省人工 |
| 产物是 **JSON + 一份人类可读的 review 清单** | 人工确认需要一个能读的东西，不是让人读 JSON |
| `procedure` 硬上限 **6 步** | 超过 6 步说明这是个工作流不是一条经验，应该拆或者不收 |
| `description` 硬上限 **200 字符** | 它进 TF-IDF，太长会稀释关键词 |
| 脚本**幂等**：同一个 commit 跑两次结果字节相同 | 不然没法 review diff |
| 排除名单**硬编码在脚本里**，不放配置 | License 合规不能靠配置对不对 |

**操作步骤**

1. `curate.py` 的 CLI：

```bash
python -m linkagent.preset.curate fetch   --repo addyosmani/agent-skills --ref <commit>
python -m linkagent.preset.curate draft   --out drafts/2026.08.1/
python -m linkagent.preset.curate review  --dir drafts/2026.08.1/     # 生成人读清单
python -m linkagent.preset.curate build   --dir drafts/2026.08.1/ --out src/linkagent/preset/packs/community-2026.08.1.json
```

2. `fetch` 用 `git clone --depth 1` 到临时目录，记录 commit。**不用 GitHub API**，避免 rate limit 和认证。
3. `draft` 对每个 `SKILL.md` 出一份 YAML 草稿，`scope` 留 `TODO`。
4. `build` 拒绝任何还带 `TODO` 的草稿。

**验收**

```bash
pytest tests/preset/test_curate.py -v
python -m linkagent.preset.curate build --dir tests/preset/fixtures/drafts --out /tmp/p.json
python -m linkagent.preset.curate build --dir tests/preset/fixtures/drafts --out /tmp/p2.json
# 两次产物字节相同
```

- [ ] 幂等：两次 build 的文件 hash 相同
- [ ] 带 `TODO` 的草稿 → build 失败并指出是哪条
- [ ] `procedure` 超 6 步 → build 失败
- [ ] `description` 超 200 字符 → build 失败
- [ ] 排除名单里的 skill 不出现在产物中
- [ ] 产物能被 L8-1 的 `load_pack` 装载
- [ ] **`curate.py` 里没有自己的 SKILL.md 解析代码**——`grep -n "frontmatter\|^## \|yaml.safe_load" src/linkagent/preset/curate.py` 应当只命中调用 `skillio.parser` 的那一行

**禁止**

- ❌ 让 LLM 直接产出最终包（必须过人工）
- ❌ 收录排除名单里的内容
- ❌ 给预置 EKO 伪造 `execution_stats` 或 `feedback_evidence`
- ❌ **在 `curate.py` 里重写 SKILL.md 解析**（用 [`L10-2`](./L10-SKILL-INTEROP.md) 的）

---

### L8-3 · 第一批预置内容

`P0` / 1.5 天 / 依赖：L8-2

**背景**

这张卡的产出不是代码，是**内容**。质量由人工负责，代码只负责不让坏内容混进去。

**目标规模**

| 层 | 条数 | 来源 |
|---|---|---|
| 跨域工程实践（`engineering/community/`） | 8–12 | `addyosmani/agent-skills` 为主 |
| Python（`python/community/`） | 3–5 | VoltAgent 官方团队部分 |
| TypeScript / 前端 | 3–5 | 同上 |
| 安全审计 | 2–3 | Trail of Bits 部分 |
| **合计** | **16–25** | — |

> **别超过 30 条。** 检索 top-k 是有限的，预置层挤占的每个位置都是个人经验的损失。**预置层的作用是保底，不是主力。**

**收录标准（四条全过才收）**

| 标准 | 怎么判 |
|---|---|
| **换人还成立** | 这条经验对另一个用户、另一个项目仍然正确吗 |
| **可执行** | `procedure` 是具体动作，不是"要注意质量"这种废话 |
| **不与 RxyCode 已有行为重复** | RxyCode 的系统提示已经说了的事，不要再说一遍 |
| **License 允许再分发** | MIT / Apache-2.0 / BSD。其他一律不收 |

**验收**

- [ ] 产出 `src/linkagent/preset/packs/community-2026.08.1.json`
- [ ] 条数在 16–25 之间
- [ ] 每条都有人工 review 记录（`provenance.curated_by == "human"`）
- [ ] License 清单单独产出一份 `THIRD-PARTY-NOTICES.md`
- [ ] 每条都能通过 L8-1 的全部校验
- [ ] **人工抽查 5 条**：`description` 读起来像不像一句能被检索到的话

**禁止**

- ❌ 为了凑数收录不满足四条标准的
- ❌ 收录任何个人风格偏好
- ❌ 漏掉 `THIRD-PARTY-NOTICES.md`

---

### L8-4 · 接进检索与开关

`P1` / 0.5 天 / 依赖：L8-3、L3-3

**背景**

预置包要能被检索到，也要能被关掉。

**涉及文件**

| 文件 | Grep 锚点 | 改法 |
|---|---|---|
| `src/linkagent/eko/engine.py` | `def retrieve` | 检索范围加上已装载的预置包 |
| `src/linkagent/config.py` | `class LinkAgentConfig` | 加 `preset_pack_enabled` / `preset_domains_disabled` |
| `src/linkagent/runtime/telemetry.py` | 检索遥测 | 记录每条命中来自哪一层 |
| `tests/eko/test_preset_retrieval.py` | 新建 | — |

**已经替你决定好的**

| 决定 | 理由 |
|---|---|
| 开关粒度：**整包** + **按域** | 用户可能只想关掉"前端那些"，不想全关 |
| 默认**开** | 冷启动是这一阶段存在的理由 |
| 预置 EKO **参与同一次检索排序**，不做单独通道 | 两套检索会让"为什么用了这条"变得无法解释 |
| 遥测**必须区分层** | 不然没法回答"预置包到底有没有用" |

**验收**

```bash
pytest tests/eko/test_preset_retrieval.py -v
```

- [ ] 空森林 + 预置包开 → 编码任务能检索到预置 EKO
- [ ] 关掉预置包 → 检索结果为空
- [ ] 按域关闭 → 只有该域的预置 EKO 消失
- [ ] 个人 EKO 与预置 EKO 冲突时，**个人的赢**（这条必须有独立测试）
- [ ] 遥测的 `hits[].tier` 能区分 `community` / `imported` / `personal`（枚举，不是布尔）

**禁止**

- ❌ 给预置 EKO 单开一条检索通道
- ❌ 让预置 EKO 的优先级高于 `DEFAULT`

---

### L8-5 · 预置包的更新与用户数据安全

`P1` / 0.5 天 / 依赖：L8-4

**背景**

预置包会随应用版本更新。**更新绝不能碰用户的数据。**

**涉及文件**

| 文件 | Grep 锚点 | 改法 |
|---|---|---|
| `src/linkagent/preset/loader.py` | `def load_pack` | 加版本选择逻辑 |
| `tests/preset/test_pack_upgrade.py` | 新建 | — |

**已经替你决定好的**

| 决定 | 理由 |
|---|---|
| 更新 = **整包替换**，不做逐条 merge | 预置层不可变，merge 只会制造无法调试的中间状态 |
| 用户可**钉住**某个包版本 | 新包让某个域变差时，用户要有退路 |
| 更新**不迁移、不触碰**任何 `eko-community-` 之外的 id | 用户数据安全的硬边界 |
| 更新前后**打一条遥测**记录条数变化 | 出问题时能定位到是哪次更新 |

**验收**

```bash
pytest tests/preset/test_pack_upgrade.py -v
```

- [ ] 从 `2026.08.1` 升到 `2026.09.1`，用户的个人 EKO **一条不少、一个字节不变**
- [ ] 钉住旧版本后，新包存在也不装载
- [ ] 引用了某条预置 EKO 的历史遥测记录，在该条被新包删除后**仍可读**（记录里存快照，不是存引用）
- [ ] 新包校验失败 → 回退到旧包并告警，**不是**降级成无预置包

**禁止**

- ❌ 逐条 merge
- ❌ 更新时写用户森林文件
- ❌ 校验失败直接裸奔

---

## §4 完成标准

全部五张卡做完，下面每一条都要能演示：

- [ ] 全新用户、空森林，问一个编码问题 → 检索到预置 EKO 并注入
- [ ] 用户说"我们项目不写单测" → 蒸馏出个人 EKO → 下次同类任务**个人的赢**
- [ ] 设置里关掉预置包 → 行为退回裸 RxyCode
- [ ] `THIRD-PARTY-NOTICES.md` 覆盖包里每一条的 License
- [ ] 升级预置包，用户数据零改动（有测试断言）

---

## §5 交给 L7 验证的问题

预置包**有没有用是个实证问题**，不能假定。[`L7`](./L7-EVAL-HARNESS.md) 建好后跑这一组对照：

| 组 | 配置 |
|---|---|
| A | 无预置包、无个人经验（裸 RxyCode） |
| B | 有预置包、无个人经验（**冷启动收益** = B − A） |
| C | 有预置包 + 有个人经验 |
| D | 无预置包 + 有个人经验（**预置包在有个人经验后还有没有边际价值** = C − D） |

**如果 B − A 不显著，这一阶段的前提就不成立**，应该把预置层缩到最小或者砍掉。**先建能证伪它的测量，再谈扩大内容规模。**

---

## §6 下一步

- 冷启动解决了 → [`L9-DESKTOP-APP.md`](./L9-DESKTOP-APP.md)（用户得看得见这些 EKO）
- 想验证有没有用 → [`L7-EVAL-HARNESS.md`](./L7-EVAL-HARNESS.md)
