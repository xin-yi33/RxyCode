# Phase W2 · SERVER-RUNTIME（WEB 项目施工卡）

> **范围**：这是唯一可施工卡面，其他总设计文档不复制任务卡。执行旧项目卡时仍需服从旧 `DEV-ORDER.md`。每张卡独立分支/提交，严格遵守 `../00-WEB-EXECUTION-PLAN.md` WEB-R1–R12。

## §0 W2 前置与出口

共 7 张卡；开工先核实 upstream docs/code 与 `git status`，当前文件名只是目标设计，施工前须 `Test-Path`，不能因为示例而声称实现存在。

| 卡号 | 名称 | 前置 | owner |
|---|---|---|---|
| `WEB-W2-C01` | PostgreSQL 模型、Alembic 迁移与数据权限 | W1全部 | backend/db |
| `WEB-W2-C02` | FastAPI 网关、OAuth/LocalAuth 与租户 API | WEB-W2-C01 | backend/server |
| `WEB-W2-C03` | Durable Run 创建、队列和 Worker 租约/Fencing | WEB-W2-C02 | backend/worker |
| `WEB-W2-C04` | EventStore + Outbox + SSE Replay and Follow | WEB-W2-C01,WEB-W2-C03 | backend/events |
| `WEB-W2-C05` | LangGraph Checkpoint/Worker 重启与副作用 Journal | WEB-W2-C03,WEB-W2-C04 | backend/recovery |
| `WEB-W2-C06` | 持久化 Approval / Question / 跨天 Resume | WEB-W2-C04,WEB-W2-C05 | backend/approval |
| `WEB-W2-C07` | 对象存储/Artifact/Usage 业务闭环 | WEB-W2-C01,WEB-W2-C02 | backend/artifacts |

## §1 任务卡（TEST-first，可单卡施工）

### WEB-W2-C01 · PostgreSQL 模型、Alembic 迁移与数据权限
`优先级：P0` / 预计工时：0.5–2.5 工程日 / 依赖：W1全部 · **owner: backend/db**

**背景与当前代码事实**
旧 Desktop JSON task_store 不能充当多用户长任务业务库；Cloud 需要 Run、Event、Approval、Device、Artifact 等外键与并发唯一性。

**涉及文件（白名单；`NEW` = 本卡新增，`VERIFY_EXISTING` = 本卡必须检查已有文件或前置卡产物；路径不符须 STOP/提交裁定）**
| 文件 | Grep 锚点/前置 | 允许的改法 |
|---|---|---|
| `packages/rxycode-server/src/rxycode_server/persistence/models.py` | `NEW` | SQLAlchemy 2 模型/索引 |
| `packages/rxycode-server/alembic/versions/001_web_base.py` | `NEW` | 真实升级/降级迁移 |
| `appserver/task_store.py` | `class DesktopTaskStore` | 只增加 legacy migration read adapter、不重写旧文件格式 |
| `packages/rxycode-server/alembic/env.py` | `NEW` | Alembic 在线迁移，一迁移一事务。裁定：版本文件不能单独被 Alembic 加载 |
| `packages/rxycode-server/alembic/__init__.py` | `NEW` | 让 Alembic 目录成为可安装包。裁定：wheel 里没有这份目录时 upgrade_head 找不到 env.py |
| `packages/rxycode-server/alembic/versions/__init__.py` | `NEW` | 让修订目录随包安装。裁定：同上，修订文件必须在安装后的 script_location 里 |
| `packages/rxycode-server/src/rxycode_server/persistence/migrate.py` | `NEW` | upgrade_head / downgrade_base。裁定：测试和安装要有一个调用入口 |
| `pyproject.toml` | `[project]` | 注册 rxycode_server、persistence，以及 rxycode_server.alembic。裁定：显式 packages 不会自动收录新包，Alembic 目录也不在 src 下面 |
| `packages/rxycode-server/src/rxycode_server/__init__.py` | `NEW` | 包入口。裁定：setuptools 显式包需要这个文件，否则安装后不能 import |
| `packages/rxycode-server/src/rxycode_server/persistence/__init__.py` | `NEW` | persistence 包入口。裁定：同上 |
| `requirements.txt` | `sqlalchemy` | 声明 SQLAlchemy、Alembic、psycopg。裁定：项目依赖是 dynamic，写在 requirements.txt，不能再在 pyproject 里写第二份 |
| `tests/web/w2/test_w2_c01_unit.py` | `NEW` | 严格单元契约，不得替生产降级 |
| `tests/web/w2/test_w2_c01_module.py` | `NEW` | 至少一个跨模块/进程/安全负测 |
| `tests/web/w2/conftest.py` | `NEW` | 空 PostgreSQL。裁定：两份测试要共用一个真实数据库，不能把容器启动写进生产模块 |

**已经替你决定好的（不准自己发挥）**
表结构按 `05-DATA-STATE-RECOVERY.md`，业务记录 tenant_id + FK + unique，不能用 JSON 文件管理云用户；迁移失败必须事务回滚，不得 DROP 原目录。

**否定边界**：本卡不实现第二套 Agent Loop、不跨表外文件“顺手修复”、不降低旧 `RiskLevel`、不以 mock/live screenshot 替代契约验收。现有路径/版本/依赖不符即 `BLOCKED_PREREQUISITE`，提案修改先审计。

**操作步骤（依次执行；TEST-first）**
1. 在隔离工作树读本卡上游源文件及对应模块 README，`rg` 定位锚点，记录 baseline 与当前 commit；无锚点 STOP。
2. **先建 RED 测试**：在 `tests/web/w2/test_w2_c01_unit.py` 写 `test_w2_c01_contract`、`test_w2_c01_negative`，在 `tests/web/w2/test_w2_c01_module.py` 写 `test_w2_c01_integration`，先运行观察**预期失败**，保存日志。
3. 先定义数据字典/unique/FK 的失败测试
4. 实现 SQLAlchemy model/migration
5. 跑空库 upgrade/downgrade；从旧 task_store 导入测试 fixture 验证不覆盖
6. 维护 seed demo project。
7. 同步必要协议/生成 TS、更新模块文档，复跑 Unit→Contract→Process/E2E，保存 diff 与证据，单卡可独立 revert。

**测试施工（函数名锁定；Given / When / Then）**
- Unit `tests/web/w2/test_w2_c01_unit.py::test_w2_c01_contract`：Given 空 PostgreSQL When upgrade head Then 业务表/唯一索引/约束完整可查询。
- Module `tests/web/w2/test_w2_c01_module.py::test_w2_c01_integration`：Given 两个 tenant 同名 project When 插入 Then 相互隔离且所有 FK 一致。
- 反向 `tests/web/w2/test_w2_c01_unit.py::test_w2_c01_negative`：Given 同 tenant 相同 request_id When 创建两 Run Then 数据库拒绝第二次创建。
- E2E / Process：本卡无独立 UI E2E；由对应 Phase 出口跨进程测试承接。
- 旧回归：任何碰 `core/` 或工具选取的卡加跑 `tests/test_cache/test_s1_s2_split.py` 和 `tests/test_cache/test_stable_prefix.py`；碰协议则加 `tests/test_protocol_schema.py`。

**验收命令（PowerShell；新测试文件由本卡创建，开卡前不得误判为已存在）**
```powershell
Set-Location 'D:\agent-demo\RxyCode\RxyCode1_1_0'
git status --short
rg -n --fixed-strings 'class DesktopTaskStore' 'appserver/task_store.py'
python -m pytest 'tests/web/w2/test_w2_c01_unit.py' -q
python -m pytest 'tests/web/w2/test_w2_c01_module.py' -q
git diff --check
git status --short
```

**完成判据**
- [x] `test_w2_c01_contract`、`test_w2_c01_negative` 与 `test_w2_c01_integration` 全部真绿且无无故 skip。
- [x] 当前行为满足本卡冻结决策、现有 CLI/Desktop 回归符合期望。
- [x] 安全拒绝、失败和取消按本卡约束实测，未开发路径标 `BLOCKED` 而不是 PASS。
- [x] `evidence/web/WEB-W2-C01/` 有红绿日志、协议快照（若适用）、diff、人工复审与交接。

**Commit（仅此卡）**
`feat(web): web-w2-c01 - PostgreSQL 模型、Alembic 迁移与数据权限`

---

### WEB-W2-C02 · FastAPI 网关、OAuth/LocalAuth 与租户 API
`优先级：P0` / 预计工时：0.5–2.5 工程日 / 依赖：WEB-W2-C01 · **owner: backend/server**

**背景与当前代码事实**
既有 api_server.py 是 loopback legacy，不适合直接公网；需要明确 GitHub OAuth 和本地单用户模式，而不能把账户逻辑塞 AgentV2。

**涉及文件（白名单；`NEW` = 本卡新增，`VERIFY_EXISTING` = 本卡必须检查已有文件或前置卡产物；路径不符须 STOP/提交裁定）**
| 文件 | Grep 锚点/前置 | 允许的改法 |
|---|---|---|
| `packages/rxycode-server/src/rxycode_server/main.py` | `NEW` | FastAPI app factory + lifecycle |
| `packages/rxycode-server/src/rxycode_server/api/auth.py` | `NEW` | GitHub OAuth state/PKCE, local session |
| `packages/rxycode-server/src/rxycode_server/api/projects.py` | `NEW` | owner-scoped Project/Session API |
| `packages/rxycode-server/src/rxycode_server/api/__init__.py` | `NEW` | 路由包入口。裁定：setuptools 显式包需要这个文件 |
| `pyproject.toml` | `[project]` | 注册 rxycode_server.api。裁定：显式 packages 不会自动收录新包 |
| `api_server.py` | `FastAPI` | 保留仅本地 fallback，禁止公网复用 |
| `tests/web/w2/test_w2_c02_unit.py` | `NEW` | 严格单元契约，不得替生产降级 |
| `tests/web/w2/test_w2_c02_module.py` | `NEW` | 至少一个跨模块/进程/安全负测 |

**已经替你决定好的（不准自己发挥）**
Cloud 使用安全 cookie、CSRF/Origin、session rotate；所有 resource scoped by user tenant；Local web 只 listen 127.0.0.1 并要求本地随机 secret；不存明文 key。

**否定边界**：本卡不实现第二套 Agent Loop、不跨表外文件“顺手修复”、不降低旧 `RiskLevel`、不以 mock/live screenshot 替代契约验收。现有路径/版本/依赖不符即 `BLOCKED_PREREQUISITE`，提案修改先审计。

**操作步骤（依次执行；TEST-first）**
1. 在隔离工作树读本卡上游源文件及对应模块 README，`rg` 定位锚点，记录 baseline 与当前 commit；无锚点 STOP。
2. **先建 RED 测试**：在 `tests/web/w2/test_w2_c02_unit.py` 写 `test_w2_c02_contract`、`test_w2_c02_negative`，在 `tests/web/w2/test_w2_c02_module.py` 写 `test_w2_c02_integration`，先运行观察**预期失败**，保存日志。
3. 建立未认证/跨用户/CSRF negative tests
4. 实现服务端 Cookie/OAuth state/expiry/项目鉴权
5. 导出 OpenAPI/golden
6. LocalAuth 与 Cloud Auth 分离；不改旧 /chat 接口。
7. 同步必要协议/生成 TS、更新模块文档，复跑 Unit→Contract→Process/E2E，保存 diff 与证据，单卡可独立 revert。

**测试施工（函数名锁定；Given / When / Then）**
- Unit `tests/web/w2/test_w2_c02_unit.py::test_w2_c02_contract`：Given 用户登录 When GET /me Then 返回真实授权组织和用户信息。
- Module `tests/web/w2/test_w2_c02_module.py::test_w2_c02_integration`：Given 两个用户 When A 访问 B 的 project/session Then 返回受控 403/404 无泄漏。
- 反向 `tests/web/w2/test_w2_c02_unit.py::test_w2_c02_negative`：Given CSRF 缺失或恶意 Origin When 写入项目 Then 拒绝且无 DB 变化。
- E2E / Process：本卡无独立 UI E2E；由对应 Phase 出口跨进程测试承接。
- 旧回归：任何碰 `core/` 或工具选取的卡加跑 `tests/test_cache/test_s1_s2_split.py` 和 `tests/test_cache/test_stable_prefix.py`；碰协议则加 `tests/test_protocol_schema.py`。

**验收命令（PowerShell；新测试文件由本卡创建，开卡前不得误判为已存在）**
```powershell
Set-Location 'D:\agent-demo\RxyCode\RxyCode1_1_0'
git status --short
rg -n --fixed-strings 'FastAPI' 'api_server.py'
python -m pytest 'tests/web/w2/test_w2_c02_unit.py' -q
python -m pytest 'tests/web/w2/test_w2_c02_module.py' -q
git diff --check
git status --short
```

**完成判据**
- [x] `test_w2_c02_contract`、`test_w2_c02_negative` 与 `test_w2_c02_integration` 全部真绿且无无故 skip。
- [x] 当前行为满足本卡冻结决策、现有 CLI/Desktop 回归符合期望。
- [x] 安全拒绝、失败和取消按本卡约束实测，未开发路径标 `BLOCKED` 而不是 PASS。
- [x] `evidence/web/WEB-W2-C02/` 有红绿日志、协议快照（若适用）、diff、人工复审与交接。

**Commit（仅此卡）**
`feat(web): web-w2-c02 - FastAPI 网关、OAuth/LocalAuth 与租户 API`

---

### WEB-W2-C03 · Durable Run 创建、队列和 Worker 租约/Fencing
`优先级：P0` / 预计工时：0.5–2.5 工程日 / 依赖：WEB-W2-C02 · **owner: backend/worker**

**背景与当前代码事实**
LLM 任务几分钟到小时；不能 HTTP 内同步执行，也不能用 Python Lock 伪装跨实例 Session 唯一。

**涉及文件（白名单；`NEW` = 本卡新增，`VERIFY_EXISTING` = 本卡必须检查已有文件或前置卡产物；路径不符须 STOP/提交裁定）**
| 文件 | Grep 锚点/前置 | 允许的改法 |
|---|---|---|
| `packages/rxycode-server/src/rxycode_server/runs/service.py` | `NEW` | Run create/transition/idempotency |
| `packages/rxycode-server/src/rxycode_server/persistence/models.py` | `uq_runs_one_active_per_session` | 活动唯一索引加入 cancel_requested。裁定：否则取消确认前会放开同 Session 的第二份活动 Run |
| `packages/rxycode-server/alembic/versions/002_cancel_active.py` | `NEW` | 已有库重建该部分索引。裁定：001 已发布，不能改旧修订 |
| `packages/rxycode-worker/src/rxycode_worker/supervisor.py` | `NEW` | claim/lease/fencing/pause/cancel |
| `packages/rxycode-worker/src/rxycode_worker/queue.py` | `NEW` | Outbox/Redis Streams worker dispatcher |
| `packages/rxycode-server/src/rxycode_server/runs/__init__.py` | `NEW` | runs 包入口。裁定：setuptools 显式包需要这个文件 |
| `packages/rxycode-worker/src/rxycode_worker/__init__.py` | `NEW` | worker 包入口。裁定：同上 |
| `pyproject.toml` | `[project]` | 注册 rxycode_server.runs 与 rxycode_worker。裁定：显式 packages 不会自动收录新包 |
| `requirements.txt` | `redis` | 声明 Redis 客户端。裁定：项目依赖是 dynamic，写在 requirements.txt |
| `tests/web/w2/test_w2_c03_unit.py` | `NEW` | 严格单元契约，不得替生产降级 |
| `tests/web/w2/test_w2_c03_module.py` | `NEW` | 至少一个跨模块/进程/安全负测 |

**已经替你决定好的（不准自己发挥）**
POST Run 202；同 request_id 同 payload 返回同 run；不同 payload 冲突；同 Session DB 独占 active；过期 Worker lease_epoch 不可提交；网络故障不重复写工具。

**否定边界**：本卡不实现第二套 Agent Loop、不跨表外文件“顺手修复”、不降低旧 `RiskLevel`、不以 mock/live screenshot 替代契约验收。现有路径/版本/依赖不符即 `BLOCKED_PREREQUISITE`，提案修改先审计。

**操作步骤（依次执行；TEST-first）**
1. 在隔离工作树读本卡上游源文件及对应模块 README，`rg` 定位锚点，记录 baseline 与当前 commit；无锚点 STOP。
2. **先建 RED 测试**：在 `tests/web/w2/test_w2_c03_unit.py` 写 `test_w2_c03_contract`、`test_w2_c03_negative`，在 `tests/web/w2/test_w2_c03_module.py` 写 `test_w2_c03_integration`，先运行观察**预期失败**，保存日志。
3. 写两 worker 并发领取/崩溃失败断言
4. 实现事务创建+Outbox 异步调度
5. 实现租约续期/幂等取消/epoch CAS
6. 实进程 kill 模拟过期 Worker 更新被拒。
7. 同步必要协议/生成 TS、更新模块文档，复跑 Unit→Contract→Process/E2E，保存 diff 与证据，单卡可独立 revert。

**测试施工（函数名锁定；Given / When / Then）**
- Unit `tests/web/w2/test_w2_c03_unit.py::test_w2_c03_contract`：Given 同请求幂等键 When 两次 POST Then 只有一个 Run 并返回同一 ID。
- Module `tests/web/w2/test_w2_c03_module.py::test_w2_c03_integration`：Given 两 Worker 同时 claim When DB 锁竞争 Then 只有一个拥有任务和有效 epoch。
- 反向 `tests/web/w2/test_w2_c03_unit.py::test_w2_c03_negative`：Given 旧 Worker 租约已失效 When 写终态 Then CAS 拒绝。
- E2E / Process：本卡无独立 UI E2E；由对应 Phase 出口跨进程测试承接。
- 旧回归：任何碰 `core/` 或工具选取的卡加跑 `tests/test_cache/test_s1_s2_split.py` 和 `tests/test_cache/test_stable_prefix.py`；碰协议则加 `tests/test_protocol_schema.py`。

**验收命令（PowerShell；新测试文件由本卡创建，开卡前不得误判为已存在）**
```powershell
Set-Location 'D:\agent-demo\RxyCode\RxyCode1_1_0'
git status --short
python -m pytest 'tests/web/w2/test_w2_c03_unit.py' -q
python -m pytest 'tests/web/w2/test_w2_c03_module.py' -q
git diff --check
git status --short
```

**完成判据**
- [x] `test_w2_c03_contract`、`test_w2_c03_negative` 与 `test_w2_c03_integration` 全部真绿且无无故 skip。
- [x] 当前行为满足本卡冻结决策、现有 CLI/Desktop 回归符合期望。
- [x] 安全拒绝、失败和取消按本卡约束实测，未开发路径标 `BLOCKED` 而不是 PASS。
- [x] `evidence/web/WEB-W2-C03/` 有红绿日志、协议快照（若适用）、diff、人工复审与交接。

**Commit（仅此卡）**
`feat(web): web-w2-c03 - Durable Run 创建、队列和 Worker 租约/Fencing`

---

### WEB-W2-C04 · EventStore + Outbox + SSE Replay and Follow
`优先级：P0` / 预计工时：0.5–2.5 工程日 / 依赖：WEB-W2-C01,WEB-W2-C03 · **owner: backend/events**

**背景与当前代码事实**
旧 task_store 有 ordered events，但面向 Web 多租户的 seq/持久化/断线续传必须数据库权威；Redis Pub/Sub 不能当历史。

**涉及文件（白名单；`NEW` = 本卡新增，`VERIFY_EXISTING` = 本卡必须检查已有文件或前置卡产物；路径不符须 STOP/提交裁定）**
| 文件 | Grep 锚点/前置 | 允许的改法 |
|---|---|---|
| `packages/rxycode-server/src/rxycode_server/events/store.py` | `NEW` | 事务写 event+outbox、按 run seq 回放 |
| `packages/rxycode-server/src/rxycode_server/api/sse.py` | `NEW` | 鉴权游标/订阅+DB catchup |
| `packages/rxycode-server/src/rxycode_server/events/outbox.py` | `NEW` | publish retry/heartbeat |
| `packages/rxycode-server/src/rxycode_server/events/__init__.py` | `NEW` | events 包入口。裁定：setuptools 显式包需要这个文件 |
| `packages/rxycode-server/src/rxycode_server/main.py` | `include_router` | 挂上 SSE 路由。裁定：不挂进 app factory，回放地址不可达 |
| `packages/rxycode-server/src/rxycode_server/persistence/models.py` | `event_seq` | 记下已分配的最大 seq。裁定：删掉历史行后不能把下一条又编成 1 |
| `packages/rxycode-server/src/rxycode_server/runs/service.py` | `event_seq` | 首条事件把计数写成 1。裁定：创建 Run 已经写了 seq 1 |
| `packages/rxycode-worker/src/rxycode_worker/supervisor.py` | `event_seq` | 取消事件也占用下一个 seq。裁定：request_cancel 写 run_events，不推进计数就会在裁剪后重用 seq |
| `packages/rxycode-server/alembic/versions/003_event_seq.py` | `NEW` | 已有库补上 event_seq。裁定：001 已发布 |
| `pyproject.toml` | `[project]` | 注册 rxycode_server.events。裁定：显式 packages 不会自动收录新包 |
| `tests/web/w2/test_w2_c04_unit.py` | `NEW` | 严格单元契约，不得替生产降级 |
| `tests/web/w2/test_w2_c04_module.py` | `NEW` | 至少一个跨模块/进程/安全负测 |

**已经替你决定好的（不准自己发挥）**
按 `04-PROTOCOL...` SSE 算法订阅先行/补齐 DB，Last-Event-ID 路径有严格读取规则；终态可重播；断网不取消 Run；跨租户 SSE 一律拒绝。

**否定边界**：本卡不实现第二套 Agent Loop、不跨表外文件“顺手修复”、不降低旧 `RiskLevel`、不以 mock/live screenshot 替代契约验收。现有路径/版本/依赖不符即 `BLOCKED_PREREQUISITE`，提案修改先审计。

**操作步骤（依次执行；TEST-first）**
1. 在隔离工作树读本卡上游源文件及对应模块 README，`rg` 定位锚点，记录 baseline 与当前 commit；无锚点 STOP。
2. **先建 RED 测试**：在 `tests/web/w2/test_w2_c04_unit.py` 写 `test_w2_c04_contract`、`test_w2_c04_negative`，在 `tests/web/w2/test_w2_c04_module.py` 写 `test_w2_c04_integration`，先运行观察**预期失败**，保存日志。
3. 锁 `seq` 事务唯一性与旧 event 映射
4. 先构造 replay/subscribe race 的失败测试
5. 实现 outbox + DB authority
6. 在真实 PG/Redis 进程模拟网络断开和重复消息
7. 校验终态可重连。
8. 同步必要协议/生成 TS、更新模块文档，复跑 Unit→Contract→Process/E2E，保存 diff 与证据，单卡可独立 revert。

**测试施工（函数名锁定；Given / When / Then）**
- Unit `tests/web/w2/test_w2_c04_unit.py::test_w2_c04_contract`：Given seq=1..42 When 断线用 after_seq=40 重连 Then 正好 41,42 一次。
- Module `tests/web/w2/test_w2_c04_module.py::test_w2_c04_integration`：Given Redis notify 丢失 When DB seq=43 已提交 Then 心跳/轮询仍补齐 43。
- 反向 `tests/web/w2/test_w2_c04_unit.py::test_w2_c04_negative`：Given B 用户订阅 A Run 或返回 cursor_expired When 访问 Then 无数据泄露/不静默跳到最新。
- E2E / Process：E2E-WEB-02 浏览器在工具运行中重载，不丢任何 seq，不重复工具卡。
- 旧回归：任何碰 `core/` 或工具选取的卡加跑 `tests/test_cache/test_s1_s2_split.py` 和 `tests/test_cache/test_stable_prefix.py`；碰协议则加 `tests/test_protocol_schema.py`。

**验收命令（PowerShell；新测试文件由本卡创建，开卡前不得误判为已存在）**
```powershell
Set-Location 'D:\agent-demo\RxyCode\RxyCode1_1_0'
git status --short
python -m pytest 'tests/web/w2/test_w2_c04_unit.py' -q
python -m pytest 'tests/web/w2/test_w2_c04_module.py' -q
git diff --check
git status --short
```

**完成判据**
- [x] `test_w2_c04_contract`、`test_w2_c04_negative` 与 `test_w2_c04_integration` 全部真绿且无无故 skip。
- [x] 当前行为满足本卡冻结决策、现有 CLI/Desktop 回归符合期望。
- [x] 安全拒绝、失败和取消按本卡约束实测，未开发路径标 `BLOCKED` 而不是 PASS。
- [x] `evidence/web/WEB-W2-C04/` 有红绿日志、协议快照（若适用）、diff、人工复审与交接。

**Commit（仅此卡）**
`feat(web): web-w2-c04 - EventStore + Outbox + SSE Replay and Follow`

---

### WEB-W2-C05 · LangGraph Checkpoint/Worker 重启与副作用 Journal
`优先级：P0` / 预计工时：0.5–2.5 工程日 / 依赖：WEB-W2-C03,WEB-W2-C04 · **owner: backend/recovery**

**背景与当前代码事实**
LangGraph checkpoint 恢复的是 Graph，不代表已经执行的文件写入可以自动重复；原 `tool_journal.py` 要保留 at-most-once replay。

**涉及文件（白名单；`NEW` = 本卡新增，`VERIFY_EXISTING` = 本卡必须检查已有文件或前置卡产物；路径不符须 STOP/提交裁定）**
| 文件 | Grep 锚点/前置 | 允许的改法 |
|---|---|---|
| `execution/tool_journal.py` | `pending` | 增加远程 call_id/attempt 的 adapter，保留旧 fail-closed |
| `packages/rxycode-worker/src/rxycode_worker/checkpoints.py` | `NEW` | AsyncPostgresSaver/恢复编排 |
| `packages/rxycode-worker/src/rxycode_worker/recovery.py` | `NEW` | safe resume/unknown resolve |
| `tests/web/w2/test_w2_c05_unit.py` | `NEW` | 严格单元契约，不得替生产降级 |
| `tests/web/w2/test_w2_c05_module.py` | `NEW` | 至少一个跨模块/进程/安全负测 |
| `requirements.txt` | `langgraph` | 声明 langgraph-checkpoint-postgres。裁定：AsyncPostgresSaver 不在已安装的 langgraph 里；项目依赖是 dynamic，写在 requirements.txt，不能再在 pyproject 里写第二份 |
| `execution/tool_orchestrator.py` | `bind_tool_journal` | 远程 call_id 进入已有 journal binding。裁定：步骤 5 要求写操作走 ToolOrchestrator 的 reserve；旧 binding 的 call key 来自 ordinal，对不上远程 call_id |

**已经替你决定好的（不准自己发挥）**
Graph thread_id 使用稳定的 session+run 隔离标识，不让两个 Run 串图；interrupt 节点可能重新执行；Journal 状态 not_started/completed/unknown，unknown 需人工/机械核验。

**否定边界**：本卡不实现第二套 Agent Loop、不跨表外文件“顺手修复”、不降低旧 `RiskLevel`、不以 mock/live screenshot 替代契约验收。现有路径/版本/依赖不符即 `BLOCKED_PREREQUISITE`，提案修改先审计。

**操作步骤（依次执行；TEST-first）**
1. 在隔离工作树读本卡上游源文件及对应模块 README，`rg` 定位锚点，记录 baseline 与当前 commit；无锚点 STOP。
2. **先建 RED 测试**：在 `tests/web/w2/test_w2_c05_unit.py` 写 `test_w2_c05_contract`、`test_w2_c05_negative`，在 `tests/web/w2/test_w2_c05_module.py` 写 `test_w2_c05_integration`，先运行观察**预期失败**，保存日志。
3. 为纯读 crash/写入结果未知/数据损坏先造红测
4. 接 AsyncPostgresSaver 和幂等 journal
5. 将 ToolOrchestrator 写操作前 reserve/retry 前 check
6. 失败进入 recovery_required；证明没有任何重复外部写。
7. 同步必要协议/生成 TS、更新模块文档，复跑 Unit→Contract→Process/E2E，保存 diff 与证据，单卡可独立 revert。

**测试施工（函数名锁定；Given / When / Then）**
- Unit `tests/web/w2/test_w2_c05_unit.py::test_w2_c05_contract`：Given Node 纯读 When Worker 重启 Then 从 Checkpoint 正确恢复。
- Module `tests/web/w2/test_w2_c05_module.py::test_w2_c05_integration`：Given Shell 写操作完成但结果 ACK 丢失 When 恢复 Then 不自动重复执行。
- 反向 `tests/web/w2/test_w2_c05_unit.py::test_w2_c05_negative`：Given checkpointer 不可用 When 收到 Run Then fail closed 不新建无记录副作用。
- E2E / Process：本卡无独立 UI E2E；由对应 Phase 出口跨进程测试承接。
- 旧回归：任何碰 `core/` 或工具选取的卡加跑 `tests/test_cache/test_s1_s2_split.py` 和 `tests/test_cache/test_stable_prefix.py`；碰协议则加 `tests/test_protocol_schema.py`。

**验收命令（PowerShell；新测试文件由本卡创建，开卡前不得误判为已存在）**
```powershell
Set-Location 'D:\agent-demo\RxyCode\RxyCode1_1_0'
git status --short
rg -n --fixed-strings 'pending' 'execution/tool_journal.py'
python -m pytest 'tests/web/w2/test_w2_c05_unit.py' -q
python -m pytest 'tests/web/w2/test_w2_c05_module.py' -q
python -m pytest tests/test_cache/test_s1_s2_split.py tests/test_cache/test_stable_prefix.py -q
git diff --check
git status --short
```

**完成判据**
- [x] `test_w2_c05_contract`、`test_w2_c05_negative` 与 `test_w2_c05_integration` 全部真绿且无无故 skip。
- [x] 当前行为满足本卡冻结决策、现有 CLI/Desktop 回归符合期望。
- [x] 安全拒绝、失败和取消按本卡约束实测，未开发路径标 `BLOCKED` 而不是 PASS。
- [x] `evidence/web/WEB-W2-C05/` 有红绿日志、协议快照（若适用）、diff、人工复审与交接。

**Commit（仅此卡）**
`feat(web): web-w2-c05 - LangGraph Checkpoint/Worker 重启与副作用 Journal`

---

### WEB-W2-C06 · 持久化 Approval / Question / 跨天 Resume
`优先级：P0` / 预计工时：0.5–2.5 工程日 / 依赖：WEB-W2-C04,WEB-W2-C05 · **owner: backend/approval**

**背景与当前代码事实**
现有 `appserver/approval.py` RPC 等待最多有限 timeout，断线后长时间审批不能靠等待住一个 Worker。

**涉及文件（白名单；`NEW` = 本卡新增，`VERIFY_EXISTING` = 本卡必须检查已有文件或前置卡产物；路径不符须 STOP/提交裁定）**
| 文件 | Grep 锚点/前置 | 允许的改法 |
|---|---|---|
| `appserver/approval.py` | `class JsonRpcApproval` | 保留 legacy 客户端 broker |
| `packages/rxycode-server/src/rxycode_server/approvals/service.py` | `NEW` | DB request/decision/CAS/expiry |
| `packages/rxycode-server/src/rxycode_server/approvals/__init__.py` | `NEW` | 包入口。裁定：setuptools 显式包需要这个文件 |
| `packages/rxycode-worker/src/rxycode_worker/interrupt_resume.py` | `NEW` | LangGraph interrupt/Command.resume gate |
| `packages/rxycode-worker/src/rxycode_worker/checkpoints.py` | `_open_saver` | setup 可跳过。裁定：审批暂停持有 advisory lock 时不能再跑 CREATE INDEX CONCURRENTLY，否则会和等锁事务死锁 |
| `packages/rxycode-server/src/rxycode_server/persistence/models.py` | `uq_runs_one_active_per_session` | 活动唯一索引加入 waiting_approval。裁定：否则用户还在审批时同 Session 能再开一个 Run |
| `packages/rxycode-server/alembic/versions/004_waiting_approval.py` | `NEW` | 已有库重建该部分索引。裁定：001 已发布，不能改旧修订 |
| `pyproject.toml` | `[project]` | 注册 rxycode_server.approvals。裁定：显式 packages 不会自动收录新包 |
| `packages/rxycode-server/src/rxycode_server/api/approvals.py` | `NEW` | GET/POST `/api/v1/runs/{id}/approvals`。裁定：协议要求这个地址返回 409 APPROVAL_STALE，现有 app 没有这条路由 |
| `packages/rxycode-server/src/rxycode_server/main.py` | `include_router` | 挂上审批路由。裁定：不挂进 app factory，审批地址不可达 |
| `tests/web/w2/test_w2_c06_unit.py` | `NEW` | 严格单元契约，不得替生产降级 |
| `tests/web/w2/test_w2_c06_module.py` | `NEW` | 至少一个跨模块/进程/安全负测 |

**已经替你决定好的（不准自己发挥）**
状态 waiting_approval 持久化并释放 Worker；同审批只能决定一次，过期/取消后任何 approve 拒绝；Full 本机已授权不经逐项 Ask；需要批准的外部副作用在 interrupt 之前不得先执行。

**否定边界**：本卡不实现第二套 Agent Loop、不跨表外文件“顺手修复”、不降低旧 `RiskLevel`、不以 mock/live screenshot 替代契约验收。现有路径/版本/依赖不符即 `BLOCKED_PREREQUISITE`，提案修改先审计。

**操作步骤（依次执行；TEST-first）**
1. 在隔离工作树读本卡上游源文件及对应模块 README，`rg` 定位锚点，记录 baseline 与当前 commit；无锚点 STOP。
2. **先建 RED 测试**：在 `tests/web/w2/test_w2_c06_unit.py` 写 `test_w2_c06_contract`、`test_w2_c06_negative`，在 `tests/web/w2/test_w2_c06_module.py` 写 `test_w2_c06_integration`，先运行观察**预期失败**，保存日志。
3. 先写等待/过期/重启/重复决定场景
4. 实现 DB state machine，事务写 approval/requested event
5. 用户提交决定后 Worker 领取 resume；检查工具 Journal 和后继 events。
6. 同步必要协议/生成 TS、更新模块文档，复跑 Unit→Contract→Process/E2E，保存 diff 与证据，单卡可独立 revert。

**测试施工（函数名锁定；Given / When / Then）**
- Unit `tests/web/w2/test_w2_c06_unit.py::test_w2_c06_contract`：Given 用户第二天登录 When 查看 pending approval Then 原请求和权限范围仍存在。
- Module `tests/web/w2/test_w2_c06_module.py::test_w2_c06_integration`：Given 决定 approve 后 Worker 重启 When graph resume Then 工具最多执行一次。
- 反向 `tests/web/w2/test_w2_c06_unit.py::test_w2_c06_negative`：Given 过期/取消 approval When 重复 approve Then 409 APPROVAL_STALE，不产生副作用。
- E2E / Process：E2E-WEB-03 关浏览器、重启 API、次日模拟时间、继续审批直到终态。
- 旧回归：任何碰 `core/` 或工具选取的卡加跑 `tests/test_cache/test_s1_s2_split.py` 和 `tests/test_cache/test_stable_prefix.py`；碰协议则加 `tests/test_protocol_schema.py`。

**验收命令（PowerShell；新测试文件由本卡创建，开卡前不得误判为已存在）**
```powershell
Set-Location 'D:\agent-demo\RxyCode\RxyCode1_1_0'
git status --short
rg -n --fixed-strings 'class JsonRpcApproval' 'appserver/approval.py'
python -m pytest 'tests/web/w2/test_w2_c06_unit.py' -q
python -m pytest 'tests/web/w2/test_w2_c06_module.py' -q
git diff --check
git status --short
```

**完成判据**
- [x] `test_w2_c06_contract`、`test_w2_c06_negative` 与 `test_w2_c06_integration` 全部真绿且无无故 skip。
- [x] 当前行为满足本卡冻结决策、现有 CLI/Desktop 回归符合期望。
- [x] 安全拒绝、失败和取消按本卡约束实测，未开发路径标 `BLOCKED` 而不是 PASS。
- [x] `evidence/web/WEB-W2-C06/` 有红绿日志、协议快照（若适用）、diff、人工复审与交接。

**Commit（仅此卡）**
`feat(web): web-w2-c06 - 持久化 Approval / Question / 跨天 Resume`

---

### WEB-W2-C07 · 对象存储/Artifact/Usage 业务闭环
`优先级：P0` / 预计工时：0.5–2.5 工程日 / 依赖：WEB-W2-C01,WEB-W2-C02 · **owner: backend/artifacts**

**背景与当前代码事实**
Web 必须给用户真实可下载产物和成本页，不能把截图或生成文件塞进 SSE 无界字段。

**涉及文件（白名单；`NEW` = 本卡新增，`VERIFY_EXISTING` = 本卡必须检查已有文件或前置卡产物；路径不符须 STOP/提交裁定）**
| 文件 | Grep 锚点/前置 | 允许的改法 |
|---|---|---|
| `packages/rxycode-server/src/rxycode_server/artifacts/service.py` | `NEW` | S3/MinIO 产物生命周期+ACL |
| `packages/rxycode-server/src/rxycode_server/usage/service.py` | `NEW` | Run cost/Token ledger |
| `packages/rxycode-server/src/rxycode_server/api/artifacts.py` | `NEW` | 有 owner 校验的下载接口 |
| `packages/rxycode-server/src/rxycode_server/artifacts/__init__.py` | `NEW` | 包入口。裁定：setuptools 显式包需要这个文件 |
| `packages/rxycode-server/src/rxycode_server/usage/__init__.py` | `NEW` | 包入口。裁定：setuptools 显式包需要这个文件 |
| `pyproject.toml` | `[project]` | 注册 rxycode_server.artifacts 与 rxycode_server.usage。裁定：显式 packages 不会自动收录新包 |
| `requirements.txt` | `boto3` | 声明 boto3。裁定：项目依赖是 dynamic，写在 requirements.txt，不能再在 pyproject 里写第二份 |
| `packages/rxycode-server/src/rxycode_server/main.py` | `include_router` | 挂上下载路由。裁定：不挂进 app factory，产物地址不可达 |
| `tests/web/w2/test_w2_c07_unit.py` | `NEW` | 严格单元契约，不得替生产降级 |
| `tests/web/w2/test_w2_c07_module.py` | `NEW` | 至少一个跨模块/进程/安全负测 |

步骤 6 裁定：`artifact.created` 与 `usage.updated` 由本卡服务在同一数据库事务写入事件表，payload 只有元信息。ToolOutcome / Trace 源文件不在本卡白名单，本卡不改。

**已经替你决定好的（不准自己发挥）**
统一 artifact 元信息/sha256/size/content-type/TTL；下载签名短效且租户隔离；usage 有模型/价格版本；重复终态事件不重复计算成本。

**否定边界**：本卡不实现第二套 Agent Loop、不跨表外文件“顺手修复”、不降低旧 `RiskLevel`、不以 mock/live screenshot 替代契约验收。现有路径/版本/依赖不符即 `BLOCKED_PREREQUISITE`，提案修改先审计。

**操作步骤（依次执行；TEST-first）**
1. 在隔离工作树读本卡上游源文件及对应模块 README，`rg` 定位锚点，记录 baseline 与当前 commit；无锚点 STOP。
2. **先建 RED 测试**：在 `tests/web/w2/test_w2_c07_unit.py` 写 `test_w2_c07_contract`、`test_w2_c07_negative`，在 `tests/web/w2/test_w2_c07_module.py` 写 `test_w2_c07_integration`，先运行观察**预期失败**，保存日志。
3. 先写跨用户 artifact 和重复 cost red tests
4. 实现对象上传/哈希/元信息保存
5. 提供下载 URL 校验和短时有效期
6. 与 ToolOutcome/Trace 连接。
7. 同步必要协议/生成 TS、更新模块文档，复跑 Unit→Contract→Process/E2E，保存 diff 与证据，单卡可独立 revert。

**测试施工（函数名锁定；Given / When / Then）**
- Unit `tests/web/w2/test_w2_c07_unit.py::test_w2_c07_contract`：Given 工具产生文件 When 完成 Then Artifact 可在项目工作区下载、digest 匹配。
- Module `tests/web/w2/test_w2_c07_module.py::test_w2_c07_integration`：Given同一 Run usage 重放 When 算成本 Then 不重复增加记录。
- 反向 `tests/web/w2/test_w2_c07_unit.py::test_w2_c07_negative`：Given B 用户持有 A artifact id When 请求 Then 严格拒绝。
- E2E / Process：本卡无独立 UI E2E；由对应 Phase 出口跨进程测试承接。
- 旧回归：任何碰 `core/` 或工具选取的卡加跑 `tests/test_cache/test_s1_s2_split.py` 和 `tests/test_cache/test_stable_prefix.py`；碰协议则加 `tests/test_protocol_schema.py`。

**验收命令（PowerShell；新测试文件由本卡创建，开卡前不得误判为已存在）**
```powershell
Set-Location 'D:\agent-demo\RxyCode\RxyCode1_1_0'
git status --short
python -m pytest 'tests/web/w2/test_w2_c07_unit.py' -q
python -m pytest 'tests/web/w2/test_w2_c07_module.py' -q
git diff --check
git status --short
```

**完成判据**
- [x] `test_w2_c07_contract`、`test_w2_c07_negative` 与 `test_w2_c07_integration` 全部真绿且无无故 skip。
- [x] 当前行为满足本卡冻结决策、现有 CLI/Desktop 回归符合期望。
- [x] 安全拒绝、失败和取消按本卡约束实测，未开发路径标 `BLOCKED` 而不是 PASS。
- [x] `evidence/web/WEB-W2-C07/` 有红绿日志、协议快照（若适用）、diff、人工复审与交接。

**Commit（仅此卡）**
`feat(web): web-w2-c07 - 对象存储/Artifact/Usage 业务闭环`

---

## §2 Wave 出口检查
- [ ] W2 所有卡各有独立 commit 和 evidence，未勾选项不被宣称完成。
- [ ] 既有行为回归没有被覆盖，新增 API 不依赖 mock/假状态。
- [ ] 运行期错误、权限拒绝和用户可见状态有负向证据。
