# L4 · 安全门控

> **前置**：[`L3-RETRIEVAL-AND-SCOPE.md`](./L3-RETRIEVAL-AND-SCOPE.md) 全部完成
> **产出**：经验驱动的动作在执行前被检查，且**不与 RxyCode 已有的安全门重复**
> **工时**：4 天
> **卡数**：4 张（L4-1 ~ L4-4）
>
> **干活前读** [`../MODEL-ASSIGNMENT.md`](../MODEL-ASSIGNMENT.md)；本文件卡多为 **owner: backend** → [`../COMPOSER-2.5-PLAYBOOK.md`](../COMPOSER-2.5-PLAYBOOK.md)。**一次只做一张卡。**

---

## §0 为什么排第二

| 证据 | 数字 |
|---|---|
| 端到端消融：移除安全门 | **−1.54 pp**（配对 CI `[−2.65, −0.42]` 不跨 0） |
| 组件级：危险激活率 | 100% → **0%** |
| 组件级：安全任务通过率 | 100% → **100%**（零误伤） |
| 组件级：警告决策准确率 | 0% → **100%** |

**而且它最便宜**：纯代码、零 LLM 调用、零额外延迟。收益显著、成本近乎为零，所以排在反馈演化前面。

> ⚠ **别把 RQ4 的 100% 当承诺。** 论文 §5 自己说了：65-turn 人工审计包里只有 2 个 safe、2 个 warning、1 个 killed 样本，**样本量太小，无法定量估计罕见安全行为**。这些数字说明"机制生效了"，不说明"覆盖率高"。

---

## §1 最重要的问题：不要重复造 RxyCode 已有的东西

**RxyCode 已经有一套完整的安全门。** 动手前必须搞清楚边界，否则 L4 会写出一堆重复的检查。

### RxyCode 已经做的

| 机制 | 位置（Grep 锚点） | 做什么 |
|---|---|---|
| 工具风险分级 | `core/safety/policy.py` · `TOOL_RISK_TABLE` | 每个工具标 `READ` / `WRITE` / `DANGER` |
| bash 命令分级 | `core/safety/policy.py` · `def classify_bash_command` | 识别危险 shell 命令 |
| 写白名单 | `core/safety/policy.py` · `def is_write_allowed` | 限制能写哪些路径 |
| 审批模式 | `config` 的 `safety.permission_mode` | `confirm_all` / `auto_edit` / `full_auto` |
| 审批通道 | `core/safety/approval.py` | TUI / SSE 两种 |
| 审计日志 | `core/safety/audit.py` | 记录所有受控操作 |

### SAG 补充的（这才是 L4 该做的）

| 维度 | RxyCode 的门 | LinkAgent 的 SAG |
|---|---|---|
| **判断依据** | 这个**工具**危险吗 | 这次调用的**内容**危险吗 |
| **粒度** | 单个工具调用 | 单个调用 **+ 多个调用的组合** |
| **典型拦截** | "你要执行 `rm -rf`" | "你要把一个含密钥的文件内容 POST 到外网" |
| **组合风险** | ❌ 看不到 | ✅ **核心能力** |
| **可覆盖性** | 用户批准即可 | **FULL 级不可覆盖** |

**一句话**：RxyCode 问"这把刀危险吗"，SAG 问"你拿这把刀在切什么、和刚才那一刀合起来是在干嘛"。

### 结论

> **L4 只做 RxyCode 做不到的两件事：内容级检查、组合风险检查。**
>
> 看到自己在写"判断 `rm -rf` 危不危险"就是跑偏了——那是 RxyCode 的活，而且它已经做了。

---

## §2 论文的规则表几乎不能用

搬过来的 `safety/checker.py`（L1-4 搬的）规则是这样的：

| FULL 级（阻断） | 编码场景相关性 |
|---|---|
| 武器制造、毒品合成、人口贩卖、恐怖主义、儿童剥削、身份盗窃 | ❌ **完全无关**，而且基座模型自己就会拒 |
| 恶意软件 | 🟡 边缘相关 |

| PARTIAL 级（警告） | 编码场景相关性 |
|---|---|
| API key / bearer token / AWS key / 私钥 PEM / 数据库连接串 | ✅ **高度相关** |
| 数据外泄 URL / 提权 / SSN / 信用卡号 | ✅ **相关** |

组合风险规则更离谱——`employee_profiling`、`employee_criminal_linking` 是为论文的 HR 场景硬编码的，编码场景一次都不会触发。

**所以 L4 的实质工作是重写规则表，不是接线。** 接线在 L2-4 已经做完了。

---

## §3 任务卡

### L4-1 · 编码场景的敏感内容规则

`P0` / 1 天 / 依赖：L3 全部

**背景**

保留有用的（密钥泄漏），替换无关的（武器毒品），补上缺失的（编码场景特有的）。

**涉及文件**

| 文件 | Grep 锚点 | 改法 |
|---|---|---|
| `src/linkagent/safety/rules.py` | 新建 | 编码场景规则表 |
| `src/linkagent/safety/checker.py` | `_FULL_CONFLICT_PATTERNS` | 换成引用新规则表 |
| `tests/safety/test_rules.py` | 新建 | — |

**已经替你决定好的**

| 决定 | 理由 |
|---|---|
| **保留**全部 PARTIAL 级密钥泄漏规则 | 编码场景高度相关，而且写得不错 |
| **删除**武器/毒品/人口贩卖/恐怖主义/儿童剥削 | 编码 agent 一次都不会触发，基座模型自己会拒。留着只会让规则表看起来很吓人但没用 |
| **删除** `employee_profiling` / `employee_criminal_linking` | 论文场景硬编码 |
| **保留** `malware` 但改写 | 编码场景确实可能撞上 |
| 规则表**数据与逻辑分离** | 规则是数据，放独立模块，方便审查和扩展 |
| 每条规则**必须有测试用例**，正例反例各一 | 正则很容易写出误伤 |

**新增的 FULL 级规则**（不可覆盖，即使用户同意）：

| 规则名 | 拦什么 |
|---|---|
| `credential_exfiltration` | 把读到的凭证内容发往外部地址 |
| `history_rewrite_on_shared_branch` | 对 main/master/develop 强推或改写历史 |
| `mass_destruction` | 递归删除超出工作目录的路径 |

**新增的 PARTIAL 级规则**（需用户确认）：

| 规则名 | 拦什么 |
|---|---|
| `dotenv_read` | 读 `.env` / `.env.*` / `credentials.json` 之类 |
| `dependency_from_unknown_source` | 从非官方源装包（`pip install` 带 `--index-url`、`curl \| sh`） |
| `production_config_write` | 写 `prod` / `production` 命名的配置 |
| `broad_permission_change` | `chmod 777`、`chown root`（论文的 `privesc` 拆细） |

**操作步骤**

1. `src/linkagent/safety/rules.py`：

```python
"""编码场景的安全规则表。

## 为什么要重写论文的规则

论文的 FULL 级规则是武器/毒品/人口贩卖/恐怖主义/儿童剥削——它们对编码
agent 一次都不会触发,而且基座模型自己就会拒绝。留着只会让规则表看起来
很严密但实际不起作用。

论文的 PARTIAL 级规则(密钥/token/私钥/连接串泄漏)则高度相关,原样保留。

组合风险规则(employee_profiling 等)是为论文的 HR 场景硬编码的,删掉,
换成编码场景真实存在的组合风险(见 L4-2)。

## 与 RxyCode 安全门的边界

RxyCode 已经做了「这个工具危险吗」(风险分级、bash 命令分类、写白名单)。
这里只做它做不到的:**内容级**检查。不要在这里重复判断 rm -rf 危不危险。

## 规则表是数据

每条规则都是 (名字, 级别, 正则, 说明) 的元组,不含逻辑。这样审查规则时
只需要读这张表,不用读代码。每条规则在 tests/safety/test_rules.py 里都
必须有正例和反例——正则最容易出的问题是误伤。
"""


@dataclass(frozen=True)
class Rule:
    name: str
    level: ConflictLevel
    pattern: re.Pattern[str]
    #: 给用户看的说明。不要写「匹配了规则 X」,要写「这个操作会怎样」。
    explanation: str
```

2. 迁移保留的规则，加上新规则。

3. **误伤测试是重点**。每条规则至少一个反例：

```python
def test_dotenv_rule_does_not_fire_on_env_var_reads():
    """读环境变量不是读 .env 文件。

    os.environ.get("API_KEY") 是完全正常的代码,不能因为出现 API_KEY
    就报警。误伤会让用户很快学会无视所有警告。
    """

def test_api_key_rule_does_not_fire_on_placeholder():
    """文档里的 api_key = "your-key-here" 不该报警。"""

def test_mass_destruction_allows_deletion_inside_workspace():
    """删自己工作目录里的东西是正常操作。"""
```

**误伤比漏报更值得担心**——一个总在误报的安全门，用户会关掉它。

**验收命令**

```powershell
cd "D:\agent-demo\LinkAgent"
python -m pytest tests/safety/test_rules.py -v
python -m ruff check src/linkagent/safety/
python -c "from linkagent.safety.rules import ALL_RULES; print(f'{len(ALL_RULES)} rules')"
```

**完成判据**
- [ ] 武器/毒品/人口贩卖/恐怖主义/儿童剥削规则**已删除**
- [ ] 密钥泄漏规则**全部保留**
- [ ] 三条新 FULL 规则 + 四条新 PARTIAL 规则已加
- [ ] **每条规则都有正例和反例测试**
- [ ] `employee_*` 组合规则已删除

**Commit**
```
feat(safety): replace the research rule table with coding-scenario rules

Weapons and trafficking patterns never fire for a coding agent and the
base model already refuses them; the credential-leak patterns are the
part worth keeping. New rules cover what a coding agent actually risks:
exfiltrating a secret it just read, rewriting shared branch history, and
deleting outside the workspace. Every rule carries a false-positive test
because a gate that cries wolf gets switched off.
```

---

### L4-2 · 组合风险检测

`P0` / 1.5 天 / 依赖：L4-1

**背景**

**这是 SAG 唯一 RxyCode 完全做不到的能力，也是论文里最有意思的部分。**

论文 RQ4 里有 2 个案例："单个动作都安全，组合起来有风险"。系统正确识别了两个。

编码场景的等价物很具体：

```
动作 1：读 config/database.yml          ← 单独看:正常,读配置而已
动作 2：POST 到 https://paste.ee/api   ← 单独看:正常,发个请求而已
────────────────────────────────────────
组合：把数据库凭证发到外部粘贴板         ← 危险
```

**涉及文件**

| 文件 | 说明 |
|---|---|
| `src/linkagent/safety/composition.py` | 新建 |
| `tests/safety/test_composition.py` | 新建 |

**已经替你决定好的**

| 决定 | 值 | 理由 |
|---|---|---|
| 检测窗口 | **单个 turn 内** | 跨 turn 关联误报率会失控，而且用户会觉得"我上一轮干的事凭什么影响这一轮" |
| 动作分类 | 打**能力标签**，不是记具体调用 | `reads_secret` / `network_egress` / `writes_outside_workspace` / `modifies_history` |
| 组合规则 | 标签的**共现**，不是顺序 | 顺序判断太脆弱（模型可能先发请求再读文件） |
| 触发后 | **PARTIAL**（需确认），不是 FULL | 组合判断有误报可能，不该不可覆盖 |
| 例外 | 同一 turn 内读的密钥只发往**同一凭证所属的服务**时不报 | 用 API key 调对应的 API 是正常操作 |

**能力标签**（初版）：

```python
class Capability(str, Enum):
    READS_SECRET = "reads_secret"                   # 读了含凭证的文件/环境
    NETWORK_EGRESS = "network_egress"               # 往外发数据
    WRITES_OUTSIDE_WORKSPACE = "writes_outside"     # 写工作目录之外
    MODIFIES_VCS_HISTORY = "modifies_vcs_history"   # 改版本历史
    INSTALLS_DEPENDENCY = "installs_dependency"     # 装包
    EXECUTES_DOWNLOADED = "executes_downloaded"     # 执行刚下载的内容
```

**组合规则表**：

| 标签组合 | 风险名 | 为什么 |
|---|---|---|
| `READS_SECRET` + `NETWORK_EGRESS` | `credential_exfiltration` | 凭证外泄，最典型 |
| `READS_SECRET` + `WRITES_OUTSIDE_WORKSPACE` | `credential_spill` | 凭证写到了不该在的地方 |
| `INSTALLS_DEPENDENCY` + `EXECUTES_DOWNLOADED` | `supply_chain` | 装了就跑，供应链风险 |
| `MODIFIES_VCS_HISTORY` + `NETWORK_EGRESS` | `history_push` | 改完历史推出去 = 不可逆 |

**操作步骤**

1. `src/linkagent/safety/composition.py`：

```python
"""组合风险检测。

**这是 SAG 唯一 RxyCode 完全做不到的能力。** RxyCode 的安全门逐个工具
判断风险,看不到「这两个动作合起来是在干嘛」。

论文 RQ4 里有 2 个组合风险案例(单个动作都安全,组合后产生员工画像风险),
系统都识别了。编码场景的等价物更具体:读了数据库配置 + 往外发请求 =
凭证外泄。

## 设计选择

**按能力标签的共现判断,不按顺序。** 顺序判断太脆弱——模型完全可能先发
请求再读文件,或者中间插几个无关操作。共现在一个 turn 内就足够可疑。

**触发后是 PARTIAL 不是 FULL。** 组合判断存在误报可能(比如用 API key
调对应的 API 就是正常操作),不该做成不可覆盖。
"""


def classify_capabilities(invocation: ToolInvocation) -> frozenset[Capability]:
    """给一次工具调用打能力标签。"""


def detect_composition_risks(
    invocations: Sequence[ToolInvocation],
) -> list[CompositionRisk]:
    """检测一个 turn 内的组合风险。"""
```

2. 实现"同服务例外"：

```python
def _is_same_service_usage(secret_source: str, egress_target: str) -> bool:
    """读的密钥是否就是发往目标所需的凭证。

    用 GitHub token 调 api.github.com 是完全正常的操作,不该报警。
    判断方式:密钥来源的服务名与出口域名匹配。

    保守起见,匹配不上就认为**不是**同服务(即报警)。安全检查宁可
    多问一次。
    """
```

3. 测试必须覆盖：

```python
def test_reading_secret_alone_is_safe():
    """单独读配置文件不报警。"""

def test_network_request_alone_is_safe():

def test_secret_read_plus_egress_is_flagged():
    """组合触发。这是这张卡的核心用例。"""

def test_order_does_not_matter():
    """先发请求后读文件同样触发。"""

def test_same_service_usage_is_not_flagged():
    """用 GitHub token 调 GitHub API 不报警。"""

def test_composition_risk_is_partial_not_full():
    """组合风险可以被用户覆盖。它有误报可能。"""

def test_risks_do_not_leak_across_turns():
    """上一个 turn 的读密钥不影响这一个 turn 的网络请求。"""
```

**验收命令**

```powershell
cd "D:\agent-demo\LinkAgent"
python -m pytest tests/safety/test_composition.py -v
python -m ruff check src/linkagent/safety/
```

**完成判据**
- [ ] 七个测试全绿
- [ ] 单个动作不误报
- [ ] 组合正确触发，且与顺序无关
- [ ] 同服务例外生效
- [ ] 组合风险是 PARTIAL 不是 FULL
- [ ] turn 之间不串

**Commit**
```
feat(safety): detect risks that only exist in combination

Reading a config file is fine and making a request is fine; doing both in
one turn may be credential exfiltration. RxyCode's per-tool gate cannot
see this because it never compares two calls. Detection keys on capability
co-occurrence rather than ordering, since a model can just as easily make
the request first.
```

---

### L4-3 · SAG 接入执行链路

`P0` / 1 天 / 依赖：L4-1、L4-2

**背景**

L2-4 已经把管道装好了（`GatedApprovalBroker` + 恒等放行的 `verdict_fn`）。这张卡把 `verdict_fn` 换成真的 SAG。

同时补上 turn 第 4 步的**计划级**检查。

**涉及文件**

| 文件 | Grep 锚点 |
|---|---|
| `src/linkagent/safety/gate.py` | 新建 |
| `src/linkagent/runtime/turn.py` | `def _authorize` |
| `tests/safety/test_gate.py` | 新建 |

**已经替你决定好的**

**两道门各管各的**：

| | 第 4 步（计划级） | 第 5 步内（工具级） |
|---|---|---|
| 检查对象 | 检索到的 EKO 的 `procedure` 和 `parameters` | 实际发生的工具调用 |
| 时机 | 执行之前 | 每次工具调用之前 |
| 能拦住什么 | "这条经验本身就在教危险操作" | "模型正要做危险的事" |
| 实现 | `EKOEngine.authorize_activation` | `GatedApprovalBroker` |

**为什么两道都要**：论文只有第一道，因为它的执行器是沙箱、计划即执行。LinkAgent 接的是真实 Agent，**AgentV2 内部自己规划**，第 4 步看不到最终的工具调用。

其他决定：

- `FULL` 级**不可覆盖**，即使用户说同意。这是论文明确验证过的行为（2 个明确危险的计划带着"接受风险"决定也没被激活）
- `PARTIAL` 走 RxyCode 原有的审批通道展示（不要自己造 UI）
- **安全检查自身异常 = 降级放行 + 记 warning**，不是阻断（L2-4 已定）

**操作步骤**

1. `src/linkagent/safety/gate.py` 组装两道门。

2. 实现 turn 的 `_authorize`。

3. 把 `verdict_fn` 换成 SAG。

4. 测试：

```python
def test_full_level_cannot_be_overridden_by_user_acceptance():
    """FULL 级即使用户接受风险也不放行。

    论文 RQ4 验证过:2 个明确危险的计划带着「接受风险」决定也没被激活。
    这不是保守,是「有些事不该由一次点击决定」。
    """

def test_partial_level_goes_through_rxycode_approval():
    """PARTIAL 用 RxyCode 原有的审批通道,不自己造 UI。"""

def test_safe_plan_passes_without_prompting():
    """安全的计划零打扰。误伤和打扰一样会让用户关掉安全门。"""

def test_plan_level_gate_catches_dangerous_eko_procedure():
    """一条教人做危险操作的 EKO 在执行前就被拦。"""

def test_tool_level_gate_catches_what_the_plan_gate_missed():
    """AgentV2 内部自己决定的危险工具调用被第二道门拦住。

    这是两道门都要的理由——第一道看不到 AgentV2 内部的规划。
    """

def test_gate_exception_degrades_to_allow_with_warning():
    """安全检查自己出 bug 时不阻断用户的任务。"""
```

**验收命令**

```powershell
cd "D:\agent-demo\LinkAgent"
python -m pytest tests/safety -q
python -m pytest -q
python -m ruff check .
```

**完成判据**
- [ ] 六个测试全绿
- [ ] FULL 不可覆盖（有测试）
- [ ] PARTIAL 走 RxyCode 审批通道
- [ ] 安全计划零打扰
- [ ] 两道门各自能拦住对方漏掉的
- [ ] 检查异常降级不阻断

**Commit**
```
feat(safety): wire SAG into both the plan and the tool-call path

The plan gate cannot see AgentV2's internal planning, so a second gate
sits at the approval broker where the actual calls surface. FULL stays
unoverridable even with user acceptance, matching the paper's finding
that some plans should not be one click away.
```

---

### L4-4 · 安全审计与误报追踪

`P1` / 0.5 天 / 依赖：L4-3

**背景**

**误报是安全门的头号死因。** 一个总在误报的门，用户三天内就会关掉它。所以必须能测量误报率。

**涉及文件**

| 文件 | 说明 |
|---|---|
| `src/linkagent/safety/audit.py` | 新建 |
| `tests/safety/test_audit.py` | 新建 |

**已经替你决定好的**

- 记录每一次判定：规则名、级别、用户最终决定、是否被覆盖
- **"被用户覆盖"是误报的代理指标**——用户批准了说明他觉得没问题
- 落盘 `~/.linkagent/safety/<date>.jsonl`
- **不记录被匹配的具体内容**（那可能就是密钥本身）。只记规则名和位置偏移
- 提供 `linkagent safety-report` 看统计

**最后两条尤其重要**：安全日志记录密钥内容是个经典的自伤。

**操作步骤**

1. 审计记录：

```python
@dataclass(frozen=True)
class SafetyAuditRecord:
    """一次安全判定的记录。

    **刻意不含被匹配的内容。** 匹配到的很可能就是密钥本身,把它写进日志
    等于把密钥从一个文件搬到另一个文件。只记规则名和偏移量,排查时够用。
    """

    timestamp: str
    rule_name: str
    level: str
    #: 匹配位置在文本中的偏移,不含内容
    match_offset: int
    user_decision: str | None
    overridden: bool
```

2. `linkagent safety-report` 输出：

```
最近 30 天安全判定

规则                          触发   被覆盖   覆盖率
credential_exfiltration          3        0     0%
dotenv_read                     18       17    94%   ← 疑似误报
production_config_write          2        1    50%
```

3. 加一个**误报警戒线**：覆盖率 >80% 且触发数 ≥10 的规则，在报告里标出来。

**验收命令**

```powershell
cd "D:\agent-demo\LinkAgent"
python -m pytest tests/safety/test_audit.py -q
linkagent safety-report
python -m ruff check .
```

**完成判据**
- [ ] 审计记录**不含**被匹配的内容（写测试验证）
- [ ] `safety-report` 能出统计
- [ ] 高覆盖率规则被标出
- [ ] 审计失败不影响主流程

**Commit**
```
feat(safety): audit verdicts and surface likely false positives

Override rate is the proxy for false positives: a rule users approve 94%
of the time is training them to approve everything. Matched content stays
out of the log — the match is often the secret itself.
```

---

## §4 L4 出口检查

```powershell
cd "D:\agent-demo\LinkAgent"
python -m ruff check .
python -m pytest -q
python -m pytest tests/safety -v
linkagent safety-report
```

**L4 完成的定义：**
- 全部命令绿
- 规则表是编码场景的，武器毒品那套已删除
- **每条规则有正例和反例测试**
- 组合风险能检出，且单动作不误报
- 两道门各就各位，FULL 不可覆盖
- 安全日志不含被匹配内容
- 四个 commit

**下一步**：[`L5-EVIDENCE-AND-EVOLUTION.md`](./L5-EVIDENCE-AND-EVOLUTION.md)
