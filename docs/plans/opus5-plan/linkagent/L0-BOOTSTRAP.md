# L0 · 建仓与骨架

> **前置**：无。这是第一份施工文档。
> **产出**：一个能 `pip install -e .`、能跑 `pytest`、能过 `ruff` 的空壳仓库。
> **工时**：2 天
> **卡数**：5 张（L0-1 ~ L0-5）
>
> **干活前读** [`../MODEL-ASSIGNMENT.md`](../MODEL-ASSIGNMENT.md)；本文件卡多为 **owner: backend** → [`../COMPOSER-2.5-PLAYBOOK.md`](../COMPOSER-2.5-PLAYBOOK.md)。**一次只做一张卡。**

---

## §0 这份文档要解决什么

L0 之后不会有任何业务功能。它只保证一件事：**后面每一张卡都有地方放代码、有命令验证。**

不要在 L0 里写任何 EKO 逻辑。看到自己在写 `class EKO` 就是跑偏了。

### 已经替你决定好的（全局，L0–L7 通用）

| 决定 | 值 | 理由 |
|---|---|---|
| 项目名 | `linkagent` | 包名、PyPI 名、导入名统一 |
| Python 版本 | `>=3.12` | SkillForest 要求 3.12，RxyCode 要求 3.10，取交集 |
| 构建后端 | `hatchling` | 与 SkillForest 一致，迁移代码时少一层摩擦 |
| 包布局 | `src/linkagent/` | src-layout，避免"没装就能 import"的假象 |
| 数据模型 | `pydantic>=2.0` | 搬过来的代码全是 pydantic v2 |
| Lint | `ruff`，`line-length = 120` | 与 SkillForest 一致 |
| 测试 | `pytest` | 同上 |
| 数据目录 | `~/.linkagent/` | **不与 `~/.rxycode/` 混用**，见 L0-4 |

### ⚠ `linkagent` 命令是开发调试工具，不是产品

产品交付形态是**独立桌面应用**（产品决策 #1，见 [`00-OVERVIEW`](./00-OVERVIEW-AND-ARCHITECTURE.md) §11 和 [`L9`](./L9-DESKTOP-APP.md)）。

CLI 仍然要建、要好用——它比 UI 早很多可用，跑评测、查经验库、排检索问题全靠它。但**别把它当最终用户界面来设计**：

| 该有 | 不该有 |
|---|---|
| 只读查询、评测、诊断 | 精心打磨的交互体验 |
| 机器可读输出（`--json`） | 花哨的终端渲染 |
| 稳定的退出码 | 对 EKO 的写命令（见 [`L5-6`](./L5-EVIDENCE-AND-EVOLUTION.md)） |

桌面端建在 **RxyCode Phase C 的完整 Desktop 壳和扩展契约**之上（fork）；主计划 Phase 3 只提供基础 Electron 壳，`desktop/` 目录到 [`L9-4`](./L9-DESKTOP-APP.md) 才建，**L0 不用管它**。

---

## §1 任务卡

### L0-1 · 建仓与 pyproject

`P0` / 3h / 依赖：无

**背景**

从零建一个独立的 git 仓库。**不是在 RxyCode 里建子目录**——LinkAgent 是独立项目。

**涉及文件**（全部新建）

| 文件 | 说明 |
|---|---|
| `pyproject.toml` | 项目定义 |
| `README.md` | 一段话说明 + 安装命令 |
| `.gitignore` | Python 标准 + `~/.linkagent` 不会在仓库内但要防误配 |
| `src/linkagent/__init__.py` | 只放 `__version__` |
| `tests/__init__.py` | 空 |
| `tests/conftest.py` | 见步骤 4 |

**已经替你决定好的**

- 仓库路径：`D:\agent-demo\LinkAgent`（与 RxyCode、SkillForest 平级）
- **不要**把 RxyCode 或 SkillForest 作为 git submodule。SkillForest 的代码是**复制**过来的（要改），RxyCode 是 **pip 依赖**（不改）
- 版本从 `0.1.0` 起

**操作步骤**

1. 建目录并 `git init`：

```powershell
New-Item -ItemType Directory -Path "D:\agent-demo\LinkAgent" -Force
cd "D:\agent-demo\LinkAgent"
git init
```

2. 写 `pyproject.toml`：

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "linkagent"
version = "0.1.0"
description = "Personalized coding agent: EKO-governed experience layer on top of RxyCode"
readme = "README.md"
license = "MIT"
requires-python = ">=3.12"
dependencies = [
    "pydantic>=2.0",
    "jsonschema>=4.23",
    "numpy>=1.24",
]

[project.optional-dependencies]
dev = [
    "pytest>=7.0",
    "pytest-asyncio>=0.21",
    "ruff>=0.1",
]

[project.scripts]
linkagent = "linkagent.cli:main"

[tool.hatch.build.targets.wheel]
packages = ["src/linkagent"]

[tool.pytest.ini_options]
testpaths = ["tests"]
python_files = "test_*.py"

[tool.ruff]
line-length = 120
target-version = "py312"
```

> **注意 `rxycode` 不在 dependencies 里。** 它在 L2 才加，理由见 L0-3。

3. `src/linkagent/__init__.py` 只写一行：

```python
__version__ = "0.1.0"
```

4. `tests/conftest.py` —— **现在就要写好数据目录隔离**，否则后面的测试会污染真实的 `~/.linkagent`：

```python
"""测试夹具。

最重要的一条:每个测试用独立的临时数据目录。EKO 森林是磁盘上的东西,
测试如果写进真实的 ~/.linkagent,跑一遍测试就会污染用户的经验库。
"""

import pytest


@pytest.fixture(autouse=True)
def isolated_data_dir(tmp_path, monkeypatch):
    """把 LINKAGENT_DATA_DIR 指向临时目录。

    autouse=True 是刻意的——不允许任何测试忘记隔离。
    """
    monkeypatch.setenv("LINKAGENT_DATA_DIR", str(tmp_path / "linkagent"))
    return tmp_path / "linkagent"
```

5. `cli.py` 先放一个占位（因为 `pyproject.toml` 里声明了 entry point，不写会装不上）：

```python
def main() -> int:
    print("linkagent (skeleton)")
    return 0
```

**验收命令**

```powershell
cd "D:\agent-demo\LinkAgent"
python -m pip install -e ".[dev]"
python -c "import linkagent; print(linkagent.__version__)"
linkagent
python -m ruff check .
python -m pytest -q
```

**完成判据**
- [ ] `pip install -e ".[dev]"` 成功
- [ ] `import linkagent` 能拿到版本号
- [ ] `linkagent` 命令能跑
- [ ] `ruff check .` 零输出
- [ ] `pytest -q` 通过（0 个测试也算通过）
- [ ] `git log` 有且只有一个 commit

**Commit**
```
chore: bootstrap linkagent package skeleton

Separate repo rather than a RxyCode subdirectory: RxyCode is consumed as
a pip dependency and must stay unmodified, while the EKO layer carries
its own release cadence.
```

---

### L0-2 · 目录骨架与模块占位

`P0` / 2h / 依赖：L0-1

**背景**

把 [`00-OVERVIEW-AND-ARCHITECTURE.md §8`](./00-OVERVIEW-AND-ARCHITECTURE.md#8-目标目录结构) 定好的目录结构建出来。

**这张卡只建空包，不写实现。** 目的是让后面每张卡都知道文件该放哪，避免各写各的。

**涉及文件**（全部新建，全部是 `__init__.py`）

```
src/linkagent/eko/__init__.py
src/linkagent/distillation/__init__.py
src/linkagent/safety/__init__.py
src/linkagent/bridge/__init__.py
src/linkagent/runtime/__init__.py
tests/eko/__init__.py
tests/distillation/__init__.py
tests/safety/__init__.py
tests/bridge/__init__.py
tests/runtime/__init__.py
```

**已经替你决定好的**

- **不要**在 `__init__.py` 里写 `from .xxx import *`。搬代码时会造成循环导入，而且遮蔽真实的依赖关系
- 每个 `__init__.py` 里写一行 docstring 说明这个包干什么，其余留空

**操作步骤**

1. 建目录和 `__init__.py`。每个文件内容只有一行 docstring，例如：

```python
"""EKO 核心:数据模型、森林存储、检索引擎、冲突与依赖解析。"""
```

对应关系：

| 包 | docstring |
|---|---|
| `eko` | `"""EKO 核心:数据模型、森林存储、检索引擎、冲突与依赖解析。"""` |
| `distillation` | `"""经验蒸馏:证据打包、候选生成、晋升为正式 EKO。"""` |
| `safety` | `"""安全门控:激活前的纯代码规则检查。"""` |
| `bridge` | `"""RxyCode 桥接:执行、上下文注入、轨迹回收。"""` |
| `runtime` | `"""运行时:turn 编排与遥测。"""` |

2. `tests/` 下的镜像目录同理，docstring 写 `"""<对应包> 的测试。"""`。

**验收命令**

```powershell
cd "D:\agent-demo\LinkAgent"
python -c "import linkagent.eko, linkagent.distillation, linkagent.safety, linkagent.bridge, linkagent.runtime; print('ok')"
python -m ruff check .
python -m pytest -q
```

**完成判据**
- [ ] 五个子包都能 import
- [ ] 没有任何 `import *`
- [ ] `ruff` 零输出

**Commit**
```
chore: add package layout for eko / distillation / safety / bridge / runtime

Fixing the layout up front keeps later ports from scattering the same
concern across ad-hoc modules.
```

---

### L0-3 · 依赖策略与 RxyCode 安装验证

`P0` / 3h / 依赖：L0-1

**背景**

LinkAgent 依赖 RxyCode，但**现在还不把它写进 `dependencies`**。

理由：RxyCode 还没发到 PyPI，只能本地 `-e` 安装。如果现在写进 `dependencies`，任何人 clone 下来 `pip install` 都会失败。

这张卡做的是：**验证本地可安装 + 把安装步骤写进文档 + 加一个能明确报错的守卫**。

**涉及文件**

| 文件 | 说明 |
|---|---|
| `README.md` | 补安装章节 |
| `src/linkagent/bridge/_require.py` | 新建，RxyCode 可用性检查 |
| `tests/bridge/test_require.py` | 新建 |

**已经替你决定好的**

- RxyCode **不进 `dependencies`**，改为 `[project.optional-dependencies]` 里的 `rxycode` 组，且注明要本地安装
- 检查函数放在 `bridge/_require.py`，**不放在 `__init__.py`**——import 一个包不应该有副作用
- 缺 RxyCode 时给**可操作的错误信息**（告诉用户跑什么命令），不是 `ModuleNotFoundError`

**操作步骤**

1. 先确认 RxyCode 能装上：

```powershell
python -m pip install -e "D:\agent-demo\RxyCode\RxyCode1_1_0"
python -c "from RxyCode.RxyCode1_1_0.core.agent_v2 import AgentV2; print('rxycode ok')"
```

> ⚠ 如果这一步失败，**停下来报告**（Playbook 规则 C8）。不要试图绕过或改 RxyCode。

2. `src/linkagent/bridge/_require.py`：

```python
"""RxyCode 可用性检查。

LinkAgent 把 RxyCode 当执行底座,但不把它写进 install_requires——它还没
发到 PyPI,只能本地 editable 安装。所以这里给一个明确的、可操作的错误,
而不是让用户撞上一个裸的 ModuleNotFoundError。
"""

from __future__ import annotations

#: RxyCode 的导入路径。它的包名带版本段,不是普通的 `rxycode`。
RXYCODE_IMPORT_PATH = "RxyCode.RxyCode1_1_0"

_INSTALL_HINT = (
    "LinkAgent 需要 RxyCode 作为执行底座,但没有找到它。\n"
    "本地安装:\n"
    "    pip install -e <RxyCode 仓库路径>\n"
    "例如:\n"
    "    pip install -e D:\\agent-demo\\RxyCode\\RxyCode1_1_0"
)


class RxyCodeNotAvailable(ImportError):
    """RxyCode 未安装或无法导入。"""


def require_rxycode() -> None:
    """确认 RxyCode 可用,不可用时抛出带安装指引的异常。

    调用方:bridge 层在真正需要执行能力之前调用。**不要**在模块 import
    时调用——那会让「只想跑 EKO 单元测试」的场景也强制依赖 RxyCode。
    """
    try:
        __import__(f"{RXYCODE_IMPORT_PATH}.core.agent_v2")
    except ImportError as exc:
        raise RxyCodeNotAvailable(_INSTALL_HINT) from exc


def rxycode_available() -> bool:
    """RxyCode 是否可用。给测试用 skipif 判断。"""
    try:
        require_rxycode()
    except RxyCodeNotAvailable:
        return False
    return True
```

3. `pyproject.toml` 加一个可选组：

```toml
[project.optional-dependencies]
dev = [
    "pytest>=7.0",
    "pytest-asyncio>=0.21",
    "ruff>=0.1",
]
# RxyCode 尚未发布到 PyPI,只能本地 editable 安装:
#   pip install -e <RxyCode 仓库路径>
# 这一组是占位,发布后改成真实版本约束。
rxycode = []
```

4. `tests/bridge/test_require.py`：

```python
"""RxyCode 依赖检查的测试。"""

from linkagent.bridge._require import RxyCodeNotAvailable, rxycode_available


def test_missing_rxycode_raises_actionable_error(monkeypatch):
    """错误信息必须告诉用户跑什么命令,而不是只说 module not found。"""


def test_rxycode_available_returns_bool():
    """不抛异常,只返回布尔值,方便 skipif 用。"""
    assert isinstance(rxycode_available(), bool)
```

第一个测试用 `monkeypatch` 让 import 失败，断言异常消息里含 `pip install -e`。

5. `README.md` 补一节：

```markdown
## 安装

LinkAgent 需要 RxyCode 作为执行底座。RxyCode 尚未发布到 PyPI，需要本地安装：

    pip install -e D:\agent-demo\RxyCode\RxyCode1_1_0
    pip install -e ".[dev]"

只跑 EKO 层的单元测试不需要 RxyCode。
```

**验收命令**

```powershell
cd "D:\agent-demo\LinkAgent"
python -c "from linkagent.bridge._require import rxycode_available; print(rxycode_available())"
python -m pytest tests/bridge -q
python -m ruff check .
```

**完成判据**
- [ ] `rxycode_available()` 返回 `True`（RxyCode 已装的情况下）
- [ ] 缺 RxyCode 时的错误信息含 `pip install -e`
- [ ] **`import linkagent` 本身不触发 RxyCode 检查**（写测试守这条）
- [ ] `ruff` 零输出

**Commit**
```
feat(bridge): guard RxyCode availability with an actionable error

RxyCode is not on PyPI yet, so it cannot go into install_requires. Fail
with the exact install command instead of a bare ModuleNotFoundError,
and keep the check out of import time so EKO-only tests stay standalone.
```

---

### L0-4 · 数据目录与配置

`P0` / 3h / 依赖：L0-1

**背景**

EKO 森林是磁盘上的东西。**在写任何存储代码之前**，先把"数据放哪"定死，否则后面每个模块都会自己拼一遍路径。

**涉及文件**

| 文件 | 说明 |
|---|---|
| `src/linkagent/config.py` | 新建 |
| `tests/test_config.py` | 新建 |

**已经替你决定好的**

| 决定 | 值 | 理由 |
|---|---|---|
| 根目录 | `~/.linkagent/` | **不与 `~/.rxycode/` 混用**。两个项目独立演进，数据混在一起会让备份和迁移都变复杂 |
| 环境变量 | `LINKAGENT_DATA_DIR` | 与 RxyCode 的 `RXYCODE_DATA_DIR` 对称 |
| 森林目录 | `<root>/forest/` | 里面是 `catalog.json` / `records/` / `indices/` |
| 证据目录 | `<root>/evidence/` | 原始 EvidencePacket，JSONL |
| 配置文件 | `<root>/config.yaml` | **L0 只定路径，不实现读写**（YAML 解析等到真有配置项再说） |
| 配置对象 | `frozen dataclass` | 不要单例，不要模块级可变全局——RxyCode 就是被这个坑的 |

**⚠ 最后一条特别重要。** RxyCode 的配置是"文件 + 函数式全局"（`load_config()` 每次读盘），导致没法在同进程里跑两套配置（见 [`APPENDIX-A §6.3`](./APPENDIX-A-ASSET-INVENTORY.md#63--全局单例清单决定进程隔离策略)）。**LinkAgent 不重复这个错误**：配置是一个显式传递的不可变对象。

**操作步骤**

1. `src/linkagent/config.py`：

```python
"""LinkAgent 配置与路径解析。

设计约束:配置是一个**显式传递的不可变对象**,不是模块级单例。

理由:RxyCode 的配置是 load_config() 每次读盘的函数式全局,结果是同进程
里跑不了两套配置(见 APPENDIX-A §6.3)。LinkAgent 的 L7 评测需要同时跑
「EKO 开」和「EKO 关」两种配置,所以这里从一开始就走显式传递。
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

#: 覆盖数据根目录的环境变量。与 RxyCode 的 RXYCODE_DATA_DIR 对称。
DATA_DIR_ENV = "LINKAGENT_DATA_DIR"


def default_data_dir() -> Path:
    """数据根目录。环境变量优先,否则 ~/.linkagent。"""
    override = os.environ.get(DATA_DIR_ENV)
    if override:
        return Path(override).expanduser()
    return Path.home() / ".linkagent"


@dataclass(frozen=True)
class Paths:
    """所有磁盘位置的唯一来源。

    别的模块**不许**自己拼路径——拼出来的第二份定义迟早会漂移。
    """

    root: Path

    @classmethod
    def resolve(cls, root: Path | None = None) -> "Paths":
        return cls(root=root or default_data_dir())

    @property
    def forest(self) -> Path:
        """EKO 森林:catalog.json + records/ + indices/。"""
        return self.root / "forest"

    @property
    def evidence(self) -> Path:
        """原始 EvidencePacket,JSONL 追加写。"""
        return self.root / "evidence"

    @property
    def config_file(self) -> Path:
        return self.root / "config.yaml"

    def ensure(self) -> "Paths":
        """建目录。幂等。"""
        self.forest.mkdir(parents=True, exist_ok=True)
        self.evidence.mkdir(parents=True, exist_ok=True)
        return self


@dataclass(frozen=True)
class Features:
    """功能开关。

    默认值直接对应 APPENDIX-B §7 的实测结论:检索/安全门/反馈演化默认开,
    依赖组合和冲突裁决默认关(端到端无显著收益且有开销)。
    """

    contextual_retrieval: bool = True
    safety_gate: bool = True
    feedback_evolution: bool = True
    dependency_composition: bool = False
    conflict_resolution: bool = False


@dataclass(frozen=True)
class Config:
    """LinkAgent 的完整配置。显式传递,不做单例。"""

    paths: Paths
    features: Features = Features()

    @classmethod
    def default(cls) -> "Config":
        return cls(paths=Paths.resolve())
```

2. `tests/test_config.py` 必须覆盖：

```python
def test_data_dir_env_override_wins():
def test_default_data_dir_is_under_home():
def test_paths_ensure_is_idempotent():
def test_dependency_composition_defaults_off():
    """依赖组合默认关闭——APPENDIX-B §2 的端到端消融没有显著收益。"""
def test_conflict_resolution_defaults_off():
def test_config_is_frozen():
    """配置不可变。可变配置会让 L7 的 A/B 评测出现串扰。"""
```

**验收命令**

```powershell
cd "D:\agent-demo\LinkAgent"
python -m pytest tests/test_config.py -q
python -m ruff check .
python -c "from linkagent.config import Config; c = Config.default(); print(c.paths.forest); print(c.features)"
```

**完成判据**
- [ ] 六个测试全绿
- [ ] `Features` 里 `dependency_composition` 和 `conflict_resolution` 默认 `False`
- [ ] `Config` 和 `Paths` 都是 `frozen`
- [ ] 没有任何模块级可变全局

**Commit**
```
feat(config): explicit immutable config with dedicated data dir

Config is passed explicitly rather than loaded from a module-level
global, so the L7 A/B harness can run EKO-on and EKO-off side by side.
Feature defaults follow the ablation evidence: composition and conflict
resolution stay off until a domain actually has dependency metadata.
```

---

### L0-5 · CI 与验收命令

`P1` / 3h / 依赖：L0-1 ~ L0-4

**背景**

后面每张卡都会说"跑验收命令"。这张卡把那组命令固定下来，并放进 CI。

**涉及文件**

| 文件 | 说明 |
|---|---|
| `.github/workflows/ci.yml` | 新建 |
| `README.md` | 补开发章节 |

**已经替你决定好的**

- CI 只跑 **Python 3.12**（`requires-python >= 3.12`，没必要做矩阵）
- CI **不装 RxyCode**。理由：RxyCode 不在 PyPI，CI 里装不了。所以 CI 只跑不依赖 RxyCode 的测试
- 需要 RxyCode 的测试用 `pytest.mark.skipif(not rxycode_available())` 标记
- `ruff check` 失败就红，不给警告余地

**操作步骤**

1. `.github/workflows/ci.yml`：

```yaml
name: CI

on:
  push:
  pull_request:

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: python -m pip install -e ".[dev]"
      - run: python -m ruff check .
      # RxyCode 不在 PyPI,CI 装不了。依赖它的测试会自行 skip。
      - run: python -m pytest -q
```

2. `README.md` 补：

```markdown
## 开发

    python -m ruff check .
    python -m pytest -q

需要 RxyCode 的测试在未安装时会自动跳过。跑全量：

    pip install -e D:\agent-demo\RxyCode\RxyCode1_1_0
    python -m pytest -q
```

3. **验证 skip 机制真的生效**：临时卸载 RxyCode 跑一遍，确认是 skip 不是 error。

```powershell
python -m pip uninstall -y rxycode
python -m pytest -q
python -m pip install -e "D:\agent-demo\RxyCode\RxyCode1_1_0"
```

**验收命令**

```powershell
cd "D:\agent-demo\LinkAgent"
python -m ruff check .
python -m pytest -q
```

**完成判据**
- [ ] CI 配置存在且语法正确
- [ ] 卸载 RxyCode 后 `pytest` 仍然全绿（依赖它的测试 skip，不是 error）
- [ ] `ruff check .` 零输出

**Commit**
```
ci: run lint and tests on 3.12 without requiring RxyCode

RxyCode is not installable from PyPI, so CI exercises everything that
does not need the execution substrate; bridge tests skip themselves.
```

---

## §2 L0 出口检查

```powershell
cd "D:\agent-demo\LinkAgent"
python -m pip install -e ".[dev]"
python -m ruff check .
python -m pytest -q
python -c "import linkagent.eko, linkagent.distillation, linkagent.safety, linkagent.bridge, linkagent.runtime; print('layout ok')"
python -c "from linkagent.config import Config; print(Config.default().features)"
```

**L0 完成的定义：**
- 五条命令全绿
- 五个子包能 import，都是空的（没有业务逻辑）
- 配置对象不可变，两个 feature 默认关闭
- 卸载 RxyCode 后测试仍全绿
- `git log` 有五个 commit，一张卡一个

**下一步**：[`L1-EKO-CORE.md`](./L1-EKO-CORE.md)
