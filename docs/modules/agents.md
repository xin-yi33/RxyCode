# agents.md — 多 Agent 专家团

`core/agents/` + `protocol/agents.py`。默认关闭（`settings.agents.enabled=false`）。

## 调研结论

抄 **LangGraph supervisor + AgentMux 式确定性 SOP**，不引入 CrewAI / AutoGen。

- CrewAI hierarchical：20% 路由决策藏在 LLM 里，无法调试。
- AutoGen GroupChat：非确定性，开放式闲聊才合适。
- WorkBuddy / AgentMux：团长中转、成员不直连、状态机不自由发挥。
- Anthropic 实测多 Agent ≈ 15x token，且没有熔断。

## 八条设计约束

| # | 约束 | 理由 |
|---|---|---|
| DC1 | 单 Agent 是只有一个成员的团，不是第二条路径 | 双路径必然漂移 |
| DC2 | 成员不得直连，通信经 Coordinator | WorkBuddy / AgentMux |
| DC3 | 每个 runtime 独立 memory / cache / breaker / tools | 全局单例是反面教材 |
| DC4 | SOP 转移用确定性状态机 | CrewAI LLM 路由不可调试 |
| DC5 | LLM 审计前必须过机械验证门，结论绑 sha256 | 省钱且可复现 |
| DC6 | 成员不得建子团，委派深度 ≤ 3 | 递归 spawn 再翻 10x |
| DC7 | 多 Agent 默认关闭 | 只适合可拆的结构化分工 |
| DC8 | 缓存 namespace 含 agent 维；公共前缀进缓存段 | 避免互串与静默失效 |

## AgentSpec / TeamSpec / SopStage

- **AgentSpec**：角色静态定义。`role` / `goal` / `tools`（None=全开，[]=空）/ `may_consult` / `memory_scope` / `mechanical` / `prompt_stage`。
- **SopStage**：状态机节点。`next_on_success` / `next_on_failure` 静态决定下一跳。`verify_before_next`、`audit_after_verify`。`parallel_members` 非空时该阶段并发派发（D3）。
- **内置 software_dev**：目录包 `core/agents/teams/software_dev/`。10 角色 7 阶段：pm → architect → frontend_coder∥backend_coder → tester → verifier → 三审计并行 → doc。默认 `ecosystem.disable_model_invocation=true`。角色级 skill 写在 `extra.ecosystem.skill`。
- **TeamSpec**：成员 + 阶段 + `entry_stage` + `total_token_budget` / `total_timeout_s` / `max_delegations`。
- **extra 命名空间**：`pair.*`（H）/ `vision.*`（I）/ `persona.*`（J）/ `ecosystem.*`（F18）。不要把未定型字段提升为一等字段。

## 团长四职责与唯一 LLM 决策点

团长工具集为空。四件事：建团、派活、中转、收口。

唯一 LLM 决策点是失败后多个候选的 `choose_failure_target`。其余转移走 `SopMachine`。

## 机械验证门

低层 8 项：`files_exist` `python_parses` `json_parses` `yaml_parses` `lint_clean` `tests_pass` `no_forbidden` `diff_non_empty`。

高层：`goal_satisfied`。低层全过但高层不满足仍打回。结论绑定 `subject_hash`。

## 四道成本闸门

`BudgetGuard`：token 预算、墙钟、委派次数、咨询次数。任何一道触发就停并返回部分结果。

## 什么时候不该用多 Agent

**默认不要开。** F14 E0（`evals/baselines/f14-e0-matrix.md`）用 solo 基线加三段 SOP 成本模型得到：token ≈ 3.0x、墙钟 ≈ 2.5x、完成率不升。效能比灯全是 🔴。

不该用的时候：

- 单文件 bugfix / 小 refactor / 只读问答（当前评测集的主体）
- 强依赖串行、必须同一份上下文的任务
- 你还没有为这次运行单独准备 token 预算

该考虑打开的时候（E1/E2 再测）：

- 可拆的结构化分工（前后端、多模块、独立审计）
- 机械验证门能挡住假完成，且你接受至少 3x token

`settings.agents.enabled` 保持 **false**。F10 启发式 `min_files_for_team` 已回写为 4。

### 效能比门禁（红绿灯）

| 任务类型 | token倍数 | 时间倍数 | Δ完成率 | 灯 |
|---|---|---|---|---|
| bugfix | 3.0x | 2.5x | −2pp | 🔴 |
| feature | 3.0x | 2.5x | −2pp | 🔴 |
| readcode | 3.0x | 2.5x | −2pp | 🔴 |
| refactor | 3.0x | 2.5x | −2pp | 🔴 |

### 🔴 迭代记录

1. E0：成本模型，不烧团队 LLM。动作 = 默认关 + 阈值提高到 4。
2. E1：未开跑。等 F17 命中率门。
3. E2：未开跑。仅 E1 变黄再优化。

这不是失败，是省下的钱。

## 加角色 / 加专家团 / 加 SOP

### 加一个新角色

1. 先回答：工具能不能只读？`may_consult` 最短是谁？记忆是否 private？
2. `core/prompts/templates.py` 加 `agent_<role>`。
3. 在团 YAML 的 `members` 里加 `AgentSpec`。
4. `tests/test_agents/test_isolation.py` 加一条受限工具集断言。
5. 评测对比加角色前后。更差就不要加。

### 加一支新专家团

1. 复制 `core/agents/teams/software_dev/`（`team.yaml` + `prompts/` + `skills/`）。架构与 Phase L 后续团相同。
2. 先画 SOP 状态图，确认有终点。
3. `validate_team` 必须通过。
4. mock LLM 端到端先绿。
5. 设保守的 `total_token_budget`。

### 加一种机械检查

1. `verifier.py` 的 `CHECKS` 加纯确定性项。
2. 在 `verify_before_next` 引用。
3. 通过/失败各一测。

## 程序化构造 AgentSpec

J6：不要只靠 YAML。任何运行时都可以这样构造并交给 `validate_team`：

```python
from RxyCode.RxyCode1_1_0.protocol.agents import AgentSpec, SopStage, TeamSpec
from RxyCode.RxyCode1_1_0.core.agents.spec import validate_team

coder = AgentSpec(
    role="coder",
    display_name="编码员",
    goal="按方案实现",
    prompt_stage="agent_coder",
    tools=None,
    extra={"persona.id": "default"},
)
team = TeamSpec(
    name="adhoc",
    display_name="临时团",
    members=[coder],
    stages=[SopStage(name="implement", role="coder", expected_output="code", output_key="out")],
    entry_stage="implement",
)
validate_team(team)
```

字段校验、环检测、`extra` 命名空间与 YAML 加载共用同一套 `validate_team`。
