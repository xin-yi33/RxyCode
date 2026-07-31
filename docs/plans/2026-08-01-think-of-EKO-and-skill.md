# EKO ↔ Skill 双向映射设计思考

> ✅ **已工程化**：施工版本在 [`opus5-plan/linkagent/L10-SKILL-INTEROP.md`](./opus5-plan/linkagent/L10-SKILL-INTEROP.md)（6 张卡）。**冲突时以 L10 为准。**
>
> L10 相对这份备忘补了三件事：
> 1. **RxyCode 默认注册的 `skill()` 工具能绕过全部治理**（`core/agent_v2.py:1499,1519`）——这是备忘没覆盖的一个已存在漏洞，对应 L10-4，优先级 P0
> 2. **第三层 tier `imported`**：手动导入的 EKO 优先级 `DEFAULT(10)`，不是个人层的 40，因为没有该用户的执行证据
> 3. **L8 的离线策展就是反向映射的批量版**，两者共用同一个解析器，不写两套

> **日期**：2026-08-01  
> **状态**：设计备忘（已工程化，见上）  
> **关联**：Individualized Agent 论文图 2（执行路径 + 演化路径闭环）  
> **参考实现**：SkillForest `src/skillforest/export/skill_projection.py`（出站映射已实现）；反向映射待实现

---

## 总原则：对齐论文图 2 的双路径闭环

Individualized Agent 的核心是 **图 2** 所示的两条路径：

- **执行路径（上）**：从 EKO Forest 检索适用经验 → 恢复依赖、处理冲突 → 结合工具执行 → 行动结果写回
- **演化路径（下）**：接收用户交互与执行结果 → 蒸馏为候选 EKO → 验证 / 晋升 / 版本更新 / 回滚 → 写回 EKO Forest

**EKO 是系统内唯一权威对象**：被检索的、被演化的、被激活的，始终是同一组 EKO。

Skill（`SKILL.md`）不是第二套知识库，而是 EKO 的 **人类可读投影** 或 **待入库原料**。EKO 内部 **不做 `skill_ref` 指针**；`procedure` / `preconditions` / `parameters` 全部内联在 `FormalEKO` 字段里。

---

## 路径一：主路径——蒸馏产 EKO，再出站映射 Skill（正常逻辑）

这是默认、也是最常见的情形，对应图 2 **演化路径** 的主体。

```
用户交互 / 执行结果
    → 证据包（EvidencePacket）
    → 模型蒸馏 → CandidateEKO
    → 证据校验 + 安全门
    → promote → FormalEKO（写入 Forest，append-only + catalog 指针）
    → export_eko_to_skill_markdown() → SKILL.md（出站只读投影）
```

要点：

1. **先 EKO，后 Skill**。知识先在 Forest 里成为不可变 `FormalEKO`，再按需导出。
2. **蒸馏出来的 Skill 必须带齐完整元数据**——不是网上那种只有 `name` + 正文的裸 Skill，而是出站投影的完整 frontmatter，至少包括：
   - `source: <eko_id>@<version>`（溯源）
   - `version` / `parent_version` / `status` / `path`
   - `distillation`（模型、prompt 版本与哈希、request_hash）
   - `corpus_*` 哈希（若来自冻结语料）
   - `projection: eko-to-skill-v1`
3. 正文字段与 EKO 一一对应：

   | EKO 字段 | SKILL.md |
   |---|---|
   | `description` | `## Description` |
   | `preconditions` | `## Preconditions` |
   | `procedure` | `## Procedure` |
   | `parameters` | `## Parameters` |
   | `scope` | `## Scope` |
   | `dependencies` / `conflicts` / … | 同名 `##` 节 |

4. 导出目录与语料隔离（如 `artifacts/exported_skills/`），**只读、可重生成**，绝不回写冻结语料目录。

一句话：**正常流程里，Skill 是 EKO 的打印件，不是来源。**

---

## 路径二：出站映射（EKO → Skill）

**触发时机**：EKO 已在 Forest 中（蒸馏晋升、用户反馈修订、关系回填等任何演化结果）。

**做什么**：`export_eko_to_skill_markdown(eko)` 把内联字段投影为独立 `SKILL.md`，目录名 `{eko_id}@{version}/SKILL.md`。

**不做什么**：

- 不引入 `skill_ref` / `procedure_or_tool_pointer`
- 不修改源 EKO
- 不把 Skill 当作 Forest 的写入入口

**版本语义**：

- 每个 EKO 版本对应一份 Skill 投影
- `catalog.current_version` 决定默认导出哪一版
- 历史版可用 `--scope all-versions` 全部导出
- 回滚指针只改 catalog，不删历史 json 文件

---

## 路径三：反向映射（Skill → EKO）——处理「没有 EKO 照顾」的手动 Skill

这是 **例外路径**，不是主路径。当系统检测到：

- 用户手动放入新的 `SKILL.md`（例如从网上下载、或手工编写）；
- 该文件 **没有** 对应的 EKO（无 `source`、Forest 中查无此 id、或 provenance 链断裂）；

则该 Skill **不能直接进入执行路径被当作正式经验**，必须先走一遍 **图 2 演化路径的入库流程**，补全 EKO 所需的结构与证据。

```
手动添加的裸 SKILL.md（无 EKO 背书）
    → 系统检测：Forest 中无对应 FormalEKO
    → 标准化处理（模型解析 或 规则解析，二选一或串联）
        · 抽取 description / preconditions / procedure / parameters / scope
        · 补齐 path、scope、status 等缺失字段
        · 填写 provenance：user-add:<来源路径或导入批次>
        · 填写 validation_evidence：skill-import:<内容哈希> 或人工/沙箱审核标记
    → 过证据门 + 安全门（与蒸馏 promote 同级约束）
    → 生成 CandidateEKO → promote → FormalEKO v1.0.0
    → 写入 Forest（append + set_current）
    → 此后与主路径一致：可检索、可版本化、可回滚、可再 export 出完整版 Skill
```

要点：

1. **谁制造的，provenance 就写谁**。手动导入统一记为 `user-add:...`，与蒸馏路径的 `grounding:<packet_id>`、显式用户反馈的 `explicit-user:<evidence_id>` 并列，但来源不同。
2. **过一遍的目的不是「美化 Markdown」**，而是把裸 Skill **升格为符合 FormalEKO schema 的可审计对象**——有 id、version、path、scope、provenance、validation_evidence，才能进入图 2 闭环。
3. **处理方式灵活**：复杂非结构化正文可送模型做结构化抽取；格式规整的可代码直解析（frontmatter + `##` 节映射）；无论哪条，出口必须是同一套 `CandidateEKO → FormalEKO` 闸门。
4. **入库后不再是「野生 Skill」**：它变成 Forest 里的一条 EKO；以后再 export，自然带上完整 frontmatter（含 `source` 等；反向导入的 `distillation` 可为空或记 `import-runtime` 元数据）。

一句话：**反向映射 = 把没有 EKO 照顾的手动 Skill，重新接回图 2 演化路径。**

---

## 三条路径的关系

| 路径 | 方向 | 何时发生 | 权威源 | 图 2 对应 |
|---|---|---|---|---|
| 蒸馏主路径 | 证据 → EKO | 正常运行、学习 | EKO Forest | 演化路径主体 |
| 出站映射 | EKO → Skill | EKO 已存在，需人类/agent 可读副本 | EKO | 执行侧可读投影（只读） |
| 反向映射 | Skill → EKO | 手动新增、无 EKO 背书 | 入库后归 EKO | 演化路径的补接入口 |

**优先级**：蒸馏主路径 > 反向映射（例外）> 出站映射（派生）。

**禁止**：

- 裸 Skill 绕过 EKO 直接参与检索与激活
- EKO 内嵌 skill 指针

---

## 与图 2 闭环的对应关系

- **执行路径读 EKO**：无论 Skill 从哪来，最终进 Forest 的都是 `FormalEKO`；执行时 `retrieve()` 只认 Forest 里的 current 版本。
- **行动结果写回 EKO**：手动导入的 EKO 与蒸馏 EKO 无差别，反馈、修订、回滚走同一套 `append` + `set_current`。
- **关系获取**（dependencies / conflicts）：初始 hints 在入库时解析；运行期写回继续修订——与论文 §2.2.3 及图 2 循环一致。
- **版本与回滚**：所有入库路径共享 append-only 记录 + catalog 指针；找回旧版 = `rollback(id, version)` 或读 `records/.../{version}.json`。

---

## 设计约束（硬规则）

1. **EKO 内联，不做指针**：知识在 `FormalEKO` 字段里，不指向外部 skill 文件。
2. **出站只读**：`export` 不写语料、不改 Forest。
3. **反向必过闸门**：手动 Skill 必须经过标准化 + 证据/安全校验，才能 promote 为 EKO。
4. **蒸馏 Skill 要带全元数据**：主路径导出的 Skill 是完整审计投影，不是网上裸 Skill 格式。
5. **来源可追溯**：`provenance` 区分 `grounding:*`（蒸馏）、`explicit-user:*`（显式反馈）、`user-add:*`（手动导入）。

---

## 一句话收束

> **图 2 里，EKO Forest 是中心：蒸馏正常产 EKO，再出站成 Skill；手动放进来的裸 Skill 是例外，必须反向走一遍演化入库，provenance 记 `user-add`，达标后生成 FormalEKO，从此与蒸馏产物同等对待——检索、版本、回滚、再导出，全在同一闭环里。**
