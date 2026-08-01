# L3 · 情境化检索与作用域语义

> **前置**：[`L2-RXYCODE-BRIDGE.md`](./L2-RXYCODE-BRIDGE.md) 全部完成
> **产出**：EKO 能被准确检索出来，且**不会污染无关领域的任务**
> **工时**：6 天
> **卡数**：5 张（L3-1 ~ L3-5）
>
> **干活前读** [`../MODEL-ASSIGNMENT.md`](../MODEL-ASSIGNMENT.md)；本文件卡多为 **owner: backend** → [`../COMPOSER-2.5-PLAYBOOK.md`](../COMPOSER-2.5-PLAYBOOK.md)。**一次只做一张卡。**

---

## §0 为什么这是第一优先

两个实测数字（依据见 [`APPENDIX-B`](./APPENDIX-B-PAPER-EVIDENCE.md)）：

| 证据 | 数字 |
|---|---|
| 端到端消融：移除情境化检索 | **−1.85 pp**（五个模块里损失最大，配对 CI `[−3.12, −0.58]` 不跨 0） |
| 组件级：Recall@5 | 平铺 28.06% → **完整情境化 98.42%** |
| 组件级：错误作用域/状态激活率 | 72.33% → **0.00%** |

**同时它也是问题最大的一块。** 论文如实记录了一个未修复的缺陷：

| Turn 类型 | 完整系统 | 关掉反馈演化 |
|---|---:|---:|
| turn 12 **跨领域边界** | **0.15**（DeepSeek 仅 **0.01**） | 0.525 |
| turn 13 跨会话复用 | 0.565 | 0.02 |

**同一个偏好 EKO，在目标域内是正迁移，在无关域上是严重负迁移。**

在 DeepSeek 上，这个负迁移严重到让"关掉整个反馈演化"反而更好（80.15% vs 77.46%）。

**编码任务天然跨域**——今天写 React，明天调 SQL。照搬现有语义，LinkAgent 会比论文更严重地撞上这个问题。所以 L3 不只是"搬检索"，而是**修好它再用**。

---

## §1 问题的确切位置

### 1.1 现在的代码

`src/linkagent/eko/engine.py`，Grep 锚点 `def _matches_context`：

```python
def _matches_context(record: FormalEKO, context: RetrievalContext) -> bool:
    if context.allowed_statuses is not None and record.status not in context.allowed_statuses:
        return False
    users = record.scope.get("users")
    if users and (context.owner is None or context.owner not in users):
        return False
    for key, runtime_values in context.scope.items():
        allowed_values = record.scope.get(key)
        if allowed_values and not _value_overlap(allowed_values, runtime_values):   # ← 这里
            return False
    ...
```

Grep 锚点 `def _value_overlap`：

```python
def _value_overlap(left: list[str], right: tuple[str, ...]) -> bool:
    left_values = {_normalize(item) for item in left}
    right_values = {_normalize(item) for item in right}
    return bool(left_values & right_values)      # ← 交集非空即放行
```

### 1.2 两个叠加的毛病

**毛病一：交集放行。** 一个维度上只要有**一个值**重合就通过。

**毛病二（更根本）：未声明 = 不约束。** `if allowed_values and ...` —— EKO 如果**没声明**某个维度，这个维度直接跳过检查。

于是：**一个 scope 只写了 `{"users": ["alice"], "task_types": ["response_generation"]}` 的偏好 EKO，对 alice 的任何任务都通过过滤**，因为：
- `users` 匹配
- `task_types` 里 `response_generation` 是个近乎万能的标签，和什么任务都有交集
- 其他维度（比如"这是哪个领域"）**根本没声明，所以不检查**

这就是 turn 12 掉到 0.15 的原因。

### 1.3 论文的方法论其实是对的

论文 §2.2.2 写的是：

> 作用域和前置条件属于**使用要求**，不满足时**直接排除**，而不是仅降低排名。

代码没实现这个语义。**LinkAgent 要做的是让代码追上方法论**，不是发明新东西。

---

## §2 改造方案（已定，不要自己发挥）

### D1 · 作用域改成封闭 schema

现在的 `scope` 是自由字典 `dict[str, list[str]]`，蒸馏模型爱写什么写什么。**改成固定四个维度**：

| 维度 | 语义 | 缺省时 |
|---|---|---|
| `users` | 属于谁 | **必填**。空值 = 谁都能用，这不是我们要的 |
| `domain` | **在哪个领域学到的** | **必填**。见 D2 |
| `languages` | 涉及的语言/技术栈 | 可选，缺省 = 不约束 |
| `task_types` | 任务类型 | 可选，缺省 = 不约束 |

**为什么要封闭**：自由字典意味着"EKO 没声明的维度不检查"，而蒸馏模型很难稳定地声明全所有维度。封闭 schema 让"必填"这件事可以被强制。

### D2 · domain 是硬闸，默认域内

**这是 L3 最核心的一条改动。**

| 规则 | 说明 |
|---|---|
| `domain` **必填** | 蒸馏产出的 EKO 没有 domain 就拒绝入库 |
| 匹配是**精确相等** | 不是交集、不是前缀 |
| **不匹配就排除** | 不是降权 |
| 想跨域用，必须写 `domain: ["*"]` | **且只能由用户显式指定**，蒸馏模型不许自己填 `*` |

**默认域内、显式才跨域**——这正好是现在行为的反面。现在是"默认哪都能用"，改成"默认只在学到它的地方用"。

**为什么这条是对的**：一条经验能跨域，是个**强断言**。强断言应该要求显式证据，而不是作为默认值。

### D3 · 其余维度改成"声明了就必须满足"

`languages` 和 `task_types` 保持"未声明 = 不约束"，但**声明了就必须有交集**（这条现在就是对的，保留）。

关键改动在 `domain`——它**不允许"未声明"**。

### D4 · 保留 `_retrieval_text` 为 description-only

不要改。它已经和论文公式 `A(e,q) = cos(TFIDF(q), TFIDF(description_e))` 对齐了。

### D5 · 检索上下文由 LinkAgent 推断

RxyCode 不提供"当前是什么领域"这个信息。LinkAgent 要自己推断——这是 L3-1 的活。

**推断必须是确定性的，不许调 LLM。** 理由：检索发生在每个 turn 的最开头，加一次 LLM 调用会让延迟和成本都不可接受，而且引入不确定性。

---

## §3 任务卡

### L3-1 · 检索上下文推断

`P0` / 1.5 天 / 依赖：L2 全部

**背景**

要按 domain 过滤，先得知道"当前请求属于哪个 domain"。

**涉及文件**

| 文件 | 说明 |
|---|---|
| `src/linkagent/runtime/context.py` | 新建 |
| `tests/runtime/test_context.py` | 新建 |

**已经替你决定好的**

| 决定 | 值 | 理由 |
|---|---|---|
| **纯确定性，零 LLM** | 规则 + 信号提取 | 检索在每个 turn 最开头，加 LLM 调用不可接受 |
| domain 取值 | **封闭枚举**，不是自由字符串 | 自由字符串会漂移（`python` / `Python` / `py`），封闭枚举可测 |
| 推断不出来时 | `domain = "general"` | 不要猜。`general` 域的 EKO 天然是通用的 |
| 信号来源 | 工作目录文件扩展名 + 请求文本关键词 + 最近编辑的文件 | 都是免费信号 |

**domain 枚举**（初版，够用就行，以后可扩展）：

```python
class Domain(str, Enum):
    """EKO 的领域。封闭枚举而非自由字符串——自由字符串会漂移成
    python/Python/py 三个互不匹配的域。
    """
    PYTHON = "python"
    TYPESCRIPT = "typescript"
    FRONTEND = "frontend"
    BACKEND = "backend"
    DATABASE = "database"
    DEVOPS = "devops"
    DOCS = "docs"
    GENERAL = "general"     # 推断不出来时的兜底
```

**操作步骤**

1. `src/linkagent/runtime/context.py`：

```python
"""检索上下文推断。

回答一个问题:当前这个请求属于哪个领域、涉及什么语言、是什么类型的任务。

**全部是确定性规则,不调 LLM。** 检索发生在每个 turn 的最开头,在那里加
一次模型调用会让延迟和成本都不可接受,而且引入不确定性——同一个请求两次
推断出不同的域,检索结果就会跳变。

推断不出来时返回 GENERAL,不要猜。猜错的代价(把无关经验注入进来)比
不猜的代价(少用一条经验)大得多——这正是 turn 12 掉到 0.15 的教训。
"""


@dataclass(frozen=True)
class RequestContext:
    """一个请求的情境。"""

    query: str
    owner: str
    domain: Domain
    languages: tuple[str, ...] = ()
    task_types: tuple[str, ...] = ()


def infer_context(
    query: str,
    *,
    owner: str,
    cwd: Path | None = None,
    recent_files: Sequence[Path] = (),
) -> RequestContext:
    """从免费信号推断情境。

    信号优先级(高到低):
      1. 最近编辑的文件扩展名 —— 最强信号,用户正在动的就是他关心的
      2. 请求文本里的显式技术词 —— "帮我改这个 SQL" 直接给出域
      3. 工作目录的文件构成 —— 最弱,一个仓库可能有多种语言
    """
```

2. 扩展名到 domain 的映射表（写死，不要从配置读——这是实现细节不是用户选择）：

```python
_EXTENSION_DOMAINS = {
    ".py": Domain.PYTHON,
    ".ts": Domain.TYPESCRIPT, ".tsx": Domain.TYPESCRIPT,
    ".js": Domain.TYPESCRIPT, ".jsx": Domain.TYPESCRIPT,
    ".css": Domain.FRONTEND, ".scss": Domain.FRONTEND, ".html": Domain.FRONTEND,
    ".sql": Domain.DATABASE,
    ".yml": Domain.DEVOPS, ".yaml": Domain.DEVOPS, ".tf": Domain.DEVOPS,
    ".md": Domain.DOCS, ".rst": Domain.DOCS,
}
```

3. 测试必须覆盖：

```python
def test_recent_python_file_infers_python_domain():

def test_explicit_sql_mention_infers_database_domain():

def test_unknown_signals_fall_back_to_general():
    """推断不出来就是 general,不许猜。

    猜错的代价是把无关经验注入进来——那正是论文 turn 12 掉到 0.15 的
    原因。少用一条经验的代价小得多。
    """

def test_inference_is_deterministic():
    """同一输入调十次结果相同。

    检索结果跳变会让用户觉得 agent「时好时坏」,而且没法复现。
    """

def test_inference_does_not_call_any_model():
    """确定性推断不许有网络调用。用 monkeypatch 封掉网络验证。"""

def test_recent_files_outrank_cwd_composition():
    """最近编辑的文件优先于目录整体构成。

    在一个 Python 为主的仓库里改 .sql 文件时,域应该是 database。
    """
```

**验收命令**

```powershell
cd "D:\agent-demo\LinkAgent"
python -m pytest tests/runtime/test_context.py -q
python -m ruff check src/linkagent/runtime/
```

**完成判据**
- [ ] 六个测试全绿
- [ ] 推断是确定性的（有测试）
- [ ] 无任何模型/网络调用（有测试）
- [ ] 推断不出来返回 `GENERAL`
- [ ] `Domain` 是枚举不是字符串

**Commit**
```
feat(runtime): infer retrieval context from free deterministic signals

Domain gating needs to know what the current request is about, and that
answer has to be free and stable: retrieval runs at the top of every
turn, and a model call there would add latency plus make results jump
between identical requests. Unknown signals resolve to GENERAL rather
than a guess, because a wrong domain injects irrelevant experience.
```

---

### L3-2 · 作用域 schema 与 domain 硬闸

`P0` / 1.5 天 / 依赖：L3-1

**背景**

**这是整个 LinkAgent 相对论文的核心改进。**

**涉及文件**

| 文件 | Grep 锚点 | 改法 |
|---|---|---|
| `src/linkagent/eko/scope.py` | 新建 | 封闭 schema + 匹配函数 |
| `src/linkagent/eko/engine.py` | `def _matches_context` | 改用新的匹配函数 |
| `src/linkagent/eko/engine.py` | `def _value_overlap` | 保留（`languages`/`task_types` 还用它） |
| `tests/eko/test_scope.py` | 新建 | 核心测试 |

**已经替你决定好的**

见 §2 的 D1–D3。再强调三条：

1. **`domain` 必填、精确匹配、不匹配就排除**
2. **`domain: ["*"]` 只能由用户显式设置**，蒸馏模型产出的候选里出现 `*` 要拒绝
3. `languages` / `task_types` 保持"未声明=不约束，声明了=必须有交集"

**⚠ 不要动 `_retrieval_text`。** 它已经和论文公式对齐。

**操作步骤**

1. `src/linkagent/eko/scope.py`：

```python
"""EKO 作用域:封闭 schema 与匹配语义。

## 为什么要改论文的实现

论文方法论(§2.2.2)说作用域「不满足时直接排除」,但代码实现的是「交集
放行」,而且「EKO 未声明的维度不检查」。两者叠加的结果是:一个只声明了
users 和一个宽泛 task_type 的偏好 EKO,对该用户的**任何**任务都通过过滤。

论文自己记录了后果:跨领域边界 turn 的成功率 0.15(DeepSeek 0.01),而
关掉整个反馈演化反而有 0.525。同一条偏好在目标域内是正迁移,在无关域上
是严重负迁移。

编码任务天然跨域(今天 React 明天 SQL),所以 LinkAgent 必须先修这个。

## 改法

domain 变成硬闸:必填、精确匹配、不匹配就排除。想跨域用必须显式写
domain=["*"],而且只有用户能写,蒸馏模型不许自己填。

**默认域内、显式才跨域**——这是现在行为的反面。一条经验能跨域是个强
断言,强断言该要求显式证据,不该是默认值。
"""

#: 跨域通配符。**只有两个来源能设它**:
#:   1. 用户显式指定
#:   2. L8 的预置社区包构建流程
#: 蒸馏产出的候选里出现它一律拒绝。
#:
#: 预置包是第二个例外,因为它是离线人工策展的可信来源,而且它收录的
#: 「改行为前先写失败的测试」这类工程实践本来就不属于任何单一语言域。
#: 见 L8-PRESET-EKO-PACK.md §3 的 L8-1。
CROSS_DOMAIN = "*"

#: 作用域的封闭维度集合。
SCOPE_DIMENSIONS = ("users", "domain", "languages", "task_types")

#: 必填维度。缺了就不许入库。
REQUIRED_DIMENSIONS = ("users", "domain")


class ScopeError(ValueError):
    """作用域不合法。"""


def validate_scope(scope: Mapping[str, Sequence[str]], *, allow_cross_domain: bool = False) -> None:
    """校验作用域。

    Args:
        allow_cross_domain: 是否允许 domain=["*"]。**蒸馏路径必须传 False**
            ——让模型自己决定一条经验能跨域,等于把最强的断言交给最不可靠
            的一环。只有用户输入路径和 L8 预置包构建流程传 True。
    """


def scope_matches(eko_scope: Mapping[str, Sequence[str]], context: "RequestContext") -> bool:
    """EKO 的作用域是否覆盖当前情境。

    规则:
      users       —— 必须包含当前 owner
      domain      —— 必须精确等于当前 domain,或者是 ["*"]
      languages   —— 未声明则不约束;声明了则必须与当前语言有交集
      task_types  —— 同上
    """
```

2. 改 `engine.py` 的 `_matches_context`，把 scope 部分换成调 `scope_matches`。**status 检查和 preconditions 检查保持原样不动。**

3. `tests/eko/test_scope.py` 必须覆盖：

```python
def test_domain_mismatch_excludes_the_eko():
    """python 域的 EKO 不出现在 database 任务里。

    这是 L3 存在的理由。论文里这条不成立,turn 12 因此掉到 0.15。
    """

def test_exact_domain_match_includes_the_eko():

def test_wildcard_domain_matches_everything():

def test_missing_domain_is_rejected_at_validation():
    """没有 domain 的 EKO 不许入库。

    不是「入库了但不匹配」,是根本不让进——否则库里会积累一堆永远
    检索不到的死对象。
    """

def test_distillation_cannot_set_wildcard_domain():
    """蒸馏模型产出的候选里 domain=["*"] 必须被拒绝。

    「这条经验适用于所有领域」是最强的断言,不能让模型自己下。
    """

def test_undeclared_languages_do_not_constrain():
    """未声明的软维度不约束。"""

def test_declared_languages_must_overlap():

def test_owner_mismatch_excludes():
    """别人的经验不会出现在我的检索结果里。"""

def test_unknown_scope_dimension_is_rejected():
    """封闭 schema:蒸馏模型自创维度要报错。"""
```

**验收命令**

```powershell
cd "D:\agent-demo\LinkAgent"
python -m pytest tests/eko/test_scope.py -q
python -m pytest tests/eko -q
python -m ruff check src/linkagent/eko/
```

> ⚠ **`tests/eko/test_corpus_contract.py` 的检索基线会变**（L1-6 建的那个）。这是**预期的**——你就是来改检索语义的。
>
> 更新基线时**必须**在 commit message 里写明变化原因和影响的 case 数。**不许静默覆盖。**

**完成判据**
- [ ] 九个作用域测试全绿
- [ ] domain 不匹配确实排除（不是降权）
- [ ] 蒸馏路径不能设 `*`
- [ ] 未声明 domain 的 EKO 入库被拒
- [ ] `_retrieval_text` **未改动**
- [ ] 检索基线已更新且 commit message 说明了原因

**Commit**
```
feat(eko): gate retrieval on domain instead of any-value overlap

The paper's methodology excludes an EKO when scope is unsatisfied, but
the implementation passed on a single overlapping value and skipped
dimensions the EKO never declared. A preference tagged only with a broad
task type therefore reached every task, which is why the cross-domain
boundary turn scored 0.15 while disabling feedback evolution scored
0.525. Domain now defaults to local and requires an explicit user-set
wildcard to travel.
```

---

### L3-3 · 检索接入 turn

`P0` / 1 天 / 依赖：L3-2

**背景**

把 `_retrieve` 那个 `return []` 的占位换成真的。

**涉及文件**

| 文件 | Grep 锚点 |
|---|---|
| `src/linkagent/runtime/turn.py` | `def _retrieve` |
| `tests/runtime/test_turn.py` | — |

**已经替你决定好的**

| 决定 | 值 | 理由 |
|---|---|---|
| `limit` | **5** | 论文用的值，Recall@5 已达 98.42% |
| `allowed_statuses` | `("active",)` | `validated` 还没被实际用过；`deprecated` / `rejected` 显然不能用 |
| 检索失败时 | 返回空列表 + warning，**不中断 turn** | 经验层挂了不该让用户的任务失败 |
| 零命中 | 正常继续，不注入 | L2-3 已经处理 |

**操作步骤**

1. 实现 `_retrieve`：

```python
    def _retrieve(self, request: str) -> list[FormalEKO]:
        """情境化检索。

        失败时返回空列表而不是抛异常:经验层是增强,不是必需。它挂了
        应该退化成「一个普通的 RxyCode」,不该让用户的任务失败。
        """
        if not self._config.features.contextual_retrieval:
            return []
        try:
            context = infer_context(request, owner=self._owner, ...)
            matches = self._engine.search(
                RetrievalContext(
                    query=request,
                    owner=self._owner,
                    scope={...},
                    allowed_statuses=("active",),
                ),
                limit=5,
            )
            return [m.eko for m in matches]
        except Exception:
            logger.warning("EKO 检索失败,本轮不注入经验", exc_info=True)
            return []
```

2. 把检索结果接到 L2-3 的注入器上。

3. 测试：

```python
def test_retrieved_ekos_reach_the_prompt():
    """端到端:库里有匹配的 EKO → 注入文本里能看到它。"""

def test_cross_domain_eko_is_not_injected():
    """python 域的 EKO 不进 database 任务的 prompt。

    这是 L3 的验收核心。用两个域各一条 EKO,交叉验证。
    """

def test_retrieval_failure_degrades_gracefully():
    """引擎抛异常时 turn 照常完成,只是没有经验注入。"""

def test_feature_flag_off_skips_retrieval_entirely():

def test_only_active_ekos_are_retrieved():
    """deprecated 的 EKO 不会被检索出来。"""

def test_at_most_five_ekos_reach_the_prompt():
```

**验收命令**

```powershell
cd "D:\agent-demo\LinkAgent"
python -m pytest tests/runtime -q
python -m pytest -q
python -m ruff check .
```

**完成判据**
- [ ] 六个测试全绿
- [ ] **跨域不注入有测试**（L3 的验收核心）
- [ ] 检索失败降级不中断
- [ ] 只检索 `active`

**Commit**
```
feat(runtime): retrieve and inject EKOs during a turn

Retrieval failures degrade to "no experience this turn" rather than
failing the task: the experience layer is an enhancement, and when it
breaks LinkAgent should behave like plain RxyCode.
```

---

### L3-4 · 跨域负迁移回归测试集

`P0` / 1 天 / 依赖：L3-3

**背景**

**这张卡是 L3 的证据。** 前三张卡改了语义，这一张证明改对了。

论文的 turn 12 / turn 13 对比给了一个现成的实验设计：**同一条偏好 EKO，在目标域内应该被用上，在无关域上应该被排除。**

**涉及文件**

| 文件 | 说明 |
|---|---|
| `tests/fixtures/cross_domain_cases.json` | 新建，测试集 |
| `tests/eko/test_cross_domain_regression.py` | 新建 |

**已经替你决定好的**

- 测试集**手写**，不从论文语料生成——论文语料的 domain 字段是空的（那是 L3 之前的 schema）
- 至少 **12 组**：6 组"同域应命中"、6 组"跨域应排除"
- 每组要有**明确的期望**，不是"看起来合理"
- 这是**确定性测试**，不调模型

**测试集格式**：

```json
{
  "cases": [
    {
      "id": "same-domain-python-style",
      "eko": {
        "description": "生成 Python 代码时优先使用类型注解和 dataclass",
        "scope": {"users": ["u1"], "domain": ["python"], "task_types": ["code_generation"]}
      },
      "request": "帮我写一个表示用户的数据结构",
      "context": {"owner": "u1", "domain": "python"},
      "expected": "retrieved",
      "why": "同域同任务类型,应该命中"
    },
    {
      "id": "cross-domain-python-style-into-sql",
      "eko": { "...同一条 EKO..." },
      "request": "帮我写一个查询用户表的语句",
      "context": {"owner": "u1", "domain": "database"},
      "expected": "excluded",
      "why": "Python 代码风格偏好不该影响 SQL 编写。这正是论文 turn 12 掉到 0.15 的场景"
    }
  ]
}
```

**六组"跨域应排除"必须覆盖**：

| # | 场景 |
|---|---|
| 1 | Python 代码风格 → SQL 任务 |
| 2 | 前端 CSS 偏好 → 后端 API 任务 |
| 3 | 某项目的命名约定 → 文档写作任务 |
| 4 | DevOps 的 YAML 缩进偏好 → TypeScript 任务 |
| 5 | 数据库索引偏好 → 前端组件任务 |
| 6 | **别人的**偏好 → 我的任务（owner 隔离） |

**操作步骤**

1. 手写 12+ 组用例。

2. `tests/eko/test_cross_domain_regression.py`：

```python
"""跨域负迁移回归测试。

这是 L3 的核心证据。论文记录了一个未修复的缺陷:同一条偏好 EKO 在目标域
内是正迁移(turn 13:0.565 vs 0.02),在无关域上是严重负迁移(turn 12:
0.15 vs 0.525)。

LinkAgent 改了作用域语义(domain 硬闸、默认域内),这组测试证明改对了。

**这组测试不许改宽松。** 它红了说明作用域语义又漏了。
"""


@pytest.mark.parametrize("case", load_cases(), ids=lambda c: c["id"])
def test_cross_domain_case(case):
    """每组用例:同域应命中、跨域应排除。"""
```

3. 加一个汇总断言：

```python
def test_no_cross_domain_leakage_at_all():
    """全部 6 组跨域用例零泄漏。

    容忍度是零。论文里这个数字是 0.15 的成功率,我们要的是结构性排除,
    不是「大部分情况下不会」。
    """
```

**验收命令**

```powershell
cd "D:\agent-demo\LinkAgent"
python -m pytest tests/eko/test_cross_domain_regression.py -v
python -m pytest -q
```

**完成判据**
- [ ] 至少 12 组用例，6 同域 6 跨域
- [ ] 跨域泄漏 **0 组**
- [ ] 同域命中 **6 组全中**
- [ ] 每组用例有 `why` 字段说明为什么期望是这个
- [ ] 测试是确定性的，不调模型

**Commit**
```
test(eko): lock cross-domain isolation with a hand-written case set

Six same-domain cases must hit and six cross-domain cases must be
excluded outright. The tolerance is zero rather than "usually right",
because the failure mode this guards against is silent: an irrelevant
preference reaches the prompt and quietly degrades output.
```

---

### L3-5 · 检索可观测性

`P1` / 1 天 / 依赖：L3-3

**背景**

检索是个黑盒——用户不知道为什么 agent 突然改了行为。**至少要能查。**

**涉及文件**

| 文件 | 说明 |
|---|---|
| `src/linkagent/runtime/telemetry.py` | 从 SkillForest 搬 + 扩展 |
| `src/linkagent/cli.py` | 加 `--explain` |
| `tests/runtime/test_telemetry.py` | 新建 |

**已经替你决定好的**

- 每个 turn 记录：情境推断结果、候选数、**每个被排除条目的 id + 原因**、最终注入的 EKO id 和分数
- **默认记录，不默认展示**。`--explain` 才打印
- **必须逐条记录被排除的 id，不能只记原因分布。** [`L9-6`](./L9-DESKTOP-APP.md) 的检索解释面板要回答"我明明有一条相关经验，为什么没用上"，只有分布答不了这个问题
- **绝不记录 EKO 的完整内容**，只记 id + description 前 80 字符（日志体积）
- 落盘 JSONL：`~/.linkagent/telemetry/<date>.jsonl`

**排除原因要分类**，这是排查问题的关键：

```python
class ExclusionReason(str, Enum):
    STATUS = "status"              # 不是 active
    OWNER = "owner"                # 别人的
    DOMAIN = "domain"              # 域不匹配 ← L3 新增的主力
    LANGUAGE = "language"
    TASK_TYPE = "task_type"
    PRECONDITION = "precondition"
    BELOW_LIMIT = "below_limit"    # 匹配了但没进前 5
```

**操作步骤**

1. 扩展 `_matches_context` 返回排除原因（新增一个 `explain=True` 的变体，**不改原函数签名**）。

2. 记录并落盘。

3. `--explain` 输出示例：

```
情境: domain=python, languages=(python,), owner=u1
候选: 47 条当前 EKO
排除: domain 31 · owner 8 · status 3 · precondition 2
注入: 3 条
  [0.82] eko-modeu-a1b2 用户偏好在函数上加类型注解...
  [0.71] eko-aed-c3d4  重构前先跑一遍测试...
  [0.65] eko-modeu-e5f6 提交信息用祈使句...
```

4. 测试：排除原因分类正确、`--explain` 不改变行为、日志不含完整 EKO 内容、遥测失败不影响 turn。

**验收命令**

```powershell
cd "D:\agent-demo\LinkAgent"
python -m pytest tests/runtime/test_telemetry.py -q
python -m ruff check .
linkagent --explain "帮我写个 Python 类型注解的例子"
```

**完成判据**
- [ ] 排除原因分类正确且有测试
- [ ] `--explain` 能看到情境、候选数、排除分布、注入项
- [ ] 日志不含完整 EKO 内容
- [ ] 遥测失败不影响 turn

**Commit**
```
feat(runtime): record why each EKO was excluded from retrieval

Domain gating changes behaviour invisibly, so the exclusion breakdown is
the only way to tell "no matching experience" apart from "the gate is too
strict". Content stays out of the log; ids and truncated descriptions are
enough to investigate.
```

---

## §4 L3 出口检查

```powershell
cd "D:\agent-demo\LinkAgent"
python -m ruff check .
python -m pytest -q
python -m pytest tests/eko/test_cross_domain_regression.py -v
linkagent --explain "帮我写个 Python 类型注解的例子"
```

**L3 完成的定义：**
- 全部命令绿
- **跨域泄漏 0 组，同域命中 6 组全中**
- 情境推断是确定性的、零模型调用
- 检索失败降级不中断 turn
- `--explain` 能解释每条 EKO 为什么被用/没被用
- 检索基线已更新且 commit message 说明了原因
- 五个 commit

**此时 LinkAgent 才第一次比裸 RxyCode 强**——前提是库里有 EKO。而库还是空的，因为蒸馏在 L5。

**下一步**：[`L4-SAFETY-GATE.md`](./L4-SAFETY-GATE.md)
