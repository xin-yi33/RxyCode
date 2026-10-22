# Phase W3 · WEB-WORKSPACE（WEB 项目施工卡）

> **范围**：这是唯一可施工卡面，其他总设计文档不复制任务卡。执行旧项目卡时仍需服从旧 `DEV-ORDER.md`。每张卡独立分支/提交，严格遵守 `../00-WEB-EXECUTION-PLAN.md` WEB-R1–R12。

## §0 W3 前置与出口

共 7 张卡；开工先核实 upstream docs/code 与 `git status`，当前文件名只是目标设计，施工前须 `Test-Path`，不能因为示例而声称实现存在。

| 卡号 | 名称 | 前置 | owner |
|---|---|---|---|
| `WEB-W3-C01` | React/Vite/TS Web 应用骨架与共用组件 | WEB-W2-C02,WEB-W1-C04 | frontend |
| `WEB-W3-C02` | 登录/Onboarding/Workspace/Project 管理 | WEB-W3-C01,WEB-W2-C02 | frontend |
| `WEB-W3-C03` | 消息流/SSE Reducer/Run 断线续传 | WEB-W2-C04,WEB-W3-C01 | frontend |
| `WEB-W3-C04` | Monaco 文件树/逐块 Diff/Git 审阅 | WEB-W3-C03,WEB-W2-C07 | frontend |
| `WEB-W3-C05` | xterm.js / PTY / 长活进程管理 | WEB-W3-C01,WEB-W2-C02 | frontend+runner |
| `WEB-W3-C06` | Plan/Todo/Approval/Subagent/Artifact 工作台 | WEB-W3-C03,WEB-W2-C06 | frontend |
| `WEB-W3-C07` | 移动响应式/A11y/错误页/前端稳定性 | WEB-W3-C01..C06 | frontend/qa |

## §1 任务卡（TEST-first，可单卡施工）

### WEB-W3-C01 · React/Vite/TS Web 应用骨架与共用组件
`优先级：P1` / 预计工时：0.5–2.5 工程日 / 依赖：WEB-W2-C02,WEB-W1-C04 · **owner: frontend**

**背景与当前代码事实**
Electron desktop-app 已使用 React19/Vite，可复用纯 React UI，不可将 Electron preload/Node APIs 注入普通网页。

**涉及文件（白名单；`NEW` = 本卡新增，`VERIFY_EXISTING` = 本卡必须检查已有文件或前置卡产物；路径不符须 STOP/提交裁定）**
| 文件 | Grep 锚点/前置 | 允许的改法 |
|---|---|---|
| `apps/web/package.json` | `NEW` | Vite React TS scripts/typecheck/test/build |
| `apps/web/src/app/App.tsx` | `NEW` | 路由/布局/错误处理/主题 |
| `apps/web/index.html` | `NEW` | 页面入口。裁定：Vite 没有这份文件就不会产出可打开的登录页 |
| `apps/web/vite.config.ts` | `NEW` | React 与 Tailwind 插件。裁定：构建配置不在 package.json 里 |
| `apps/web/tsconfig.json` | `NEW` | typecheck。裁定：`tsc --noEmit` 需要这份配置，并纳入纯桌面组件 |
| `apps/web/src/main.tsx` | `NEW` | 挂载 App。裁定：入口脚本不能写进 App.tsx |
| `apps/web/src/vite-env.d.ts` | `NEW` | Vite 客户端类型。裁定：否则 import.meta 没有类型 |
| `apps/web/src/styles/globals.css` | `NEW` | 设计 token 与 Tailwind。裁定：主题变量不放进 TSX |
| `apps/web/src/sdk/client.ts` | `NEW` | typed HTTP/SSE。裁定：页面不直接写 fetch |
| `apps/web/src/state/ui.ts` | `NEW` | Zustand 主题与离线。裁定：不用 localStorage |
| `apps/web/src/components/ui/button.tsx` | `NEW` | shadcn Button。裁定：共用按钮不复制 Electron 组件 |
| `apps/web/src/lib/cn.ts` | `NEW` | shadcn 的 cn。裁定：Button 要合并 class |
| `apps/web/bun.lock` | `NEW` | 锁定依赖。裁定：依赖写在 package.json，锁文件随包提交，node_modules 不提交 |
| `.gitignore` | `node_modules/` | 忽略 `apps/web/dist/`。裁定：构建产物不是源码，根目录的 `/dist/` 盖不到这里 |
| `frontend/desktop-app/src/renderer/` | `VERIFY_EXISTING` | 若复用纯组件，必须先核实原目录，不能搬运 preload |
| `tests/web/w3/test_w3_c01_unit.py` | `NEW` | 严格单元契约，不得替生产降级 |
| `tests/web/w3/test_w3_c01_module.py` | `NEW` | 至少一个跨模块/进程/安全负测 |

步骤 5 裁定：Web 只引用 `frontend/desktop-app/src/renderer/src/components/sessionVisualState.ts`。该文件没有 Electron、preload 或 Node 内置模块。不修改 desktop-app，不搬运 preload。

**已经替你决定好的（不准自己发挥）**
统一设计 token/组件；Web API 仅走 typed HTTP/SSE SDK；React 视图纯投影。所有页面必须有 empty/loading/error/disconnected；禁本地网页存储模型明文 key。

**否定边界**：本卡不实现第二套 Agent Loop、不跨表外文件“顺手修复”、不降低旧 `RiskLevel`、不以 mock/live screenshot 替代契约验收。现有路径/版本/依赖不符即 `BLOCKED_PREREQUISITE`，提案修改先审计。

**操作步骤（依次执行；TEST-first）**
1. 在隔离工作树读本卡上游源文件及对应模块 README，`rg` 定位锚点，记录 baseline 与当前 commit；无锚点 STOP。
2. **先建 RED 测试**：在 `tests/web/w3/test_w3_c01_unit.py` 写 `test_w3_c01_contract`、`test_w3_c01_negative`，在 `tests/web/w3/test_w3_c01_module.py` 写 `test_w3_c01_integration`，先运行观察**预期失败**，保存日志。
3. 先建立 render/error/focus 测试
4. 创建 App Router、TanStack Query、Zustand、Tailwind/shadcn 设计系统
5. 拆可复用纯组件而不是复制 Electron host
6. 添加构建和静态扫描。
7. 同步必要协议/生成 TS、更新模块文档，复跑 Unit→Contract→Process/E2E，保存 diff 与证据，单卡可独立 revert。

**测试施工（函数名锁定；Given / When / Then）**
- Unit `tests/web/w3/test_w3_c01_unit.py::test_w3_c01_contract`：Given 页面 API 未就绪 When 登录 Web Then 明确显示 error/retry，不白屏。
- Module `tests/web/w3/test_w3_c01_module.py::test_w3_c01_integration`：Given Desktop 纯 React 组件 When Web 构建 Then 不引入 Electron/preload/node builtins。
- 反向 `tests/web/w3/test_w3_c01_unit.py::test_w3_c01_negative`：Given Browser 环境 When 搜索 bundle Then 无 secret、fs/child_process/Electron API。
- E2E / Process：E2E-WEB-01 新用户登录→Project 页三态。
- 旧回归：任何碰 `core/` 或工具选取的卡加跑 `tests/test_cache/test_s1_s2_split.py` 和 `tests/test_cache/test_stable_prefix.py`；碰协议则加 `tests/test_protocol_schema.py`。

**验收命令（PowerShell；新测试文件由本卡创建，开卡前不得误判为已存在）**
```powershell
Set-Location 'D:\agent-demo\RxyCode\RxyCode1_1_0'
git status --short
if (!(Test-Path 'frontend/desktop-app/src/renderer/')) { throw 'BLOCKED_PREREQUISITE: frontend/desktop-app/src/renderer/' }
python -m pytest 'tests/web/w3/test_w3_c01_unit.py' -q
python -m pytest 'tests/web/w3/test_w3_c01_module.py' -q
git diff --check
git status --short
```

**完成判据**
- [x] `test_w3_c01_contract`、`test_w3_c01_negative` 与 `test_w3_c01_integration` 全部真绿且无无故 skip。
- [x] 当前行为满足本卡冻结决策、现有 CLI/Desktop 回归符合期望。
- [x] 安全拒绝、失败和取消按本卡约束实测，未开发路径标 `BLOCKED` 而不是 PASS。
- [x] `evidence/web/WEB-W3-C01/` 有红绿日志、协议快照（若适用）、diff、人工复审与交接。

**Commit（仅此卡）**
`feat(web): web-w3-c01 - React/Vite/TS Web 应用骨架与共用组件`

---

### WEB-W3-C02 · 登录/Onboarding/Workspace/Project 管理
`优先级：P1` / 预计工时：0.5–2.5 工程日 / 依赖：WEB-W3-C01,WEB-W2-C02 · **owner: frontend**

**背景与当前代码事实**
招聘可验证产品必须有可完成的引导，而不是只显示 Chat。Local 不需要强制 GitHub 登录，Cloud 使用真实 OAuth。

**涉及文件（白名单；`NEW` = 本卡新增，`VERIFY_EXISTING` = 本卡必须检查已有文件或前置卡产物；路径不符须 STOP/提交裁定）**
| 文件 | Grep 锚点/前置 | 允许的改法 |
|---|---|---|
| `apps/web/src/features/auth/` | `NEW` | login/session/CSRF hooks |
| `apps/web/src/features/onboarding/` | `NEW` | BYOK/target选择/首任务。裁定：验收命令把这个目录当前提，仓库里还没有它；本卡创建，不把引导写进 Electron |
| `apps/web/src/features/projects/` | `NEW` | 目录、导入、workspace 切换 |
| `apps/web/src/sdk/client.ts` | `createClient` | 补上登录、导入和建会话。裁定：页面不直接 fetch，沿用 W3-C01 的 SDK |
| `apps/web/src/app/App.tsx` | `createBrowserRouter` | 挂上引导和 OAuth 回调。裁定：不挂路由则 /onboarding 到不了新页面 |
| `tests/web/w3/test_w3_c02_unit.py` | `NEW` | 严格单元契约，不得替生产降级 |
| `tests/web/w3/test_w3_c02_module.py` | `NEW` | 至少一个跨模块/进程/安全负测 |

**已经替你决定好的（不准自己发挥）**
前端不保存模型密钥明文；Cloud 未授权 OAuth 必须拒绝，无后端 project/session 不生成虚构前端 ID；用户引导明确 Local/Cloud/Remote 区别。

**否定边界**：本卡不实现第二套 Agent Loop、不跨表外文件“顺手修复”、不降低旧 `RiskLevel`、不以 mock/live screenshot 替代契约验收。现有路径/版本/依赖不符即 `BLOCKED_PREREQUISITE`，提案修改先审计。

**操作步骤（依次执行；TEST-first）**
1. 在隔离工作树读本卡上游源文件及对应模块 README，`rg` 定位锚点，记录 baseline 与当前 commit；无锚点 STOP。
2. **先建 RED 测试**：在 `tests/web/w3/test_w3_c02_unit.py` 写 `test_w3_c02_contract`、`test_w3_c02_negative`，在 `tests/web/w3/test_w3_c02_module.py` 写 `test_w3_c02_integration`，先运行观察**预期失败**，保存日志。
3. 先写未授权/撤销登录/导入失败 RED
4. 完成 OAuth redirect、项目页和 onboarding wizard
5. 引导后创建真实 Session，记录等待状态
6. 为移动宽度补空/错误/loading。
7. 同步必要协议/生成 TS、更新模块文档，复跑 Unit→Contract→Process/E2E，保存 diff 与证据，单卡可独立 revert。

**测试施工（函数名锁定；Given / When / Then）**
- Unit `tests/web/w3/test_w3_c02_unit.py::test_w3_c02_contract`：Given 登录用户 When 导入 Repo Then Server 返回真实 Project 可在刷新后复现。
- Module `tests/web/w3/test_w3_c02_module.py::test_w3_c02_integration`：Given 用户选 Local 模式 When 访问 localhost Then 不强迫公网账户才能建 Session。
- 反向 `tests/web/w3/test_w3_c02_unit.py::test_w3_c02_negative`：Given OAuth 失败或 Key 保存失败 When 跳转 Then 显示失败并不得伪建 Project。
- E2E / Process：E2E-WEB-01 onboarding 本地/云端各跑一遍，保存浏览器 screenshot+API trace。
- 旧回归：任何碰 `core/` 或工具选取的卡加跑 `tests/test_cache/test_s1_s2_split.py` 和 `tests/test_cache/test_stable_prefix.py`；碰协议则加 `tests/test_protocol_schema.py`。

**验收命令（PowerShell；新测试文件由本卡创建，开卡前不得误判为已存在）**
```powershell
Set-Location 'D:\agent-demo\RxyCode\RxyCode1_1_0'
git status --short
if (!(Test-Path 'apps/web/src/features/onboarding/')) { throw 'BLOCKED_PREREQUISITE: apps/web/src/features/onboarding/' }
python -m pytest 'tests/web/w3/test_w3_c02_unit.py' -q
python -m pytest 'tests/web/w3/test_w3_c02_module.py' -q
git diff --check
git status --short
```

**完成判据**
- [x] `test_w3_c02_contract`、`test_w3_c02_negative` 与 `test_w3_c02_integration` 全部真绿且无无故 skip。
- [x] 当前行为满足本卡冻结决策、现有 CLI/Desktop 回归符合期望。
- [x] 安全拒绝、失败和取消按本卡约束实测，未开发路径标 `BLOCKED` 而不是 PASS。
- [x] `evidence/web/WEB-W3-C02/` 有红绿日志、协议快照（若适用）、diff、人工复审与交接。

**Commit（仅此卡）**
`feat(web): web-w3-c02 - 登录/Onboarding/Workspace/Project 管理`

---

### WEB-W3-C03 · 消息流/SSE Reducer/Run 断线续传
`优先级：P1` / 预计工时：0.5–2.5 工程日 / 依赖：WEB-W2-C04,WEB-W3-C01 · **owner: frontend**

**背景与当前代码事实**
Web 与 CLI 的最大区别是真 Run 可长期运行，UI 必须重建全部 Events 并区分 agent intermediate 与最终答案。

**涉及文件（白名单；`NEW` = 本卡新增，`VERIFY_EXISTING` = 本卡必须检查已有文件或前置卡产物；路径不符须 STOP/提交裁定）**
| 文件 | Grep 锚点/前置 | 允许的改法 |
|---|---|---|
| `apps/web/src/features/runs/eventReducer.ts` | `NEW` | 唯一投影 reducer |
| `apps/web/src/features/runs/useRunEvents.ts` | `NEW` | EventSource reconnect + cursor |
| `apps/web/src/features/chat/ChatPage.tsx` | `NEW` | 消息、工具卡、状态与重试 |
| `apps/web/src/app/App.tsx` | `createBrowserRouter` | 挂上 `/runs/:runId`。裁定：不挂路由则聊天页到不了 reducer |
| `packages/rxycode-server/src/rxycode_server/api/runs.py` | `NEW` | GET `/api/v1/runs/{id}`。裁定：协议有这个地址，现有 app 没有，聊天页要先读 Run 状态再订阅 |
| `packages/rxycode-server/src/rxycode_server/main.py` | `include_router` | 挂上 Run 查询。裁定：不挂进 app factory，状态地址不可达 |
| `tests/web/w3/test_w3_c03_unit.py` | `NEW` | 严格单元契约，不得替生产降级 |
| `tests/web/w3/test_w3_c03_module.py` | `NEW` | 至少一个跨模块/进程/安全负测 |

**已经替你决定好的（不准自己发挥）**
从 Server 取 Run state，再按 seq 订阅；UI 不伪造工具成功/审批通过；seq gap 等待补齐；旧 `intermediate` 标记保留，不污染 final answer；相同事件幂等。

**否定边界**：本卡不实现第二套 Agent Loop、不跨表外文件“顺手修复”、不降低旧 `RiskLevel`、不以 mock/live screenshot 替代契约验收。现有路径/版本/依赖不符即 `BLOCKED_PREREQUISITE`，提案修改先审计。

**操作步骤（依次执行；TEST-first）**
1. 在隔离工作树读本卡上游源文件及对应模块 README，`rg` 定位锚点，记录 baseline 与当前 commit；无锚点 STOP。
2. **先建 RED 测试**：在 `tests/web/w3/test_w3_c03_unit.py` 写 `test_w3_c03_contract`、`test_w3_c03_negative`，在 `tests/web/w3/test_w3_c03_module.py` 写 `test_w3_c03_integration`，先运行观察**预期失败**，保存日志。
3. 创建 seq 排序/去重/gap/terminal reducer 红测
4. 实现会话消息、工具/assistant events、连接状态
5. 断线使用 Last-Event-ID 恢复并处理 CURSOR_EXPIRED
6. 挂载到真实 W2 API。
7. 同步必要协议/生成 TS、更新模块文档，复跑 Unit→Contract→Process/E2E，保存 diff 与证据，单卡可独立 revert。

**测试施工（函数名锁定；Given / When / Then）**
- Unit `tests/web/w3/test_w3_c03_unit.py::test_w3_c03_contract`：Given events 1,2,2,4,3 When reducer 消费 Then 最终顺序一致且重复2仅出现一次。
- Module `tests/web/w3/test_w3_c03_module.py::test_w3_c03_integration`：Given SSE 重连 When Web 重新加载 Then Run 真实状态/审批/工具卡一致。
- 反向 `tests/web/w3/test_w3_c03_unit.py::test_w3_c03_negative`：Given intermediate child text 乱序 When final 到达 Then 主答复末尾只有最终用户答案。
- E2E / Process：E2E-WEB-02 持续任务中关闭/重开 Web，检查 DB seq 与渲染完全匹配。
- 旧回归：任何碰 `core/` 或工具选取的卡加跑 `tests/test_cache/test_s1_s2_split.py` 和 `tests/test_cache/test_stable_prefix.py`；碰协议则加 `tests/test_protocol_schema.py`。

**验收命令（PowerShell；新测试文件由本卡创建，开卡前不得误判为已存在）**
```powershell
Set-Location 'D:\agent-demo\RxyCode\RxyCode1_1_0'
git status --short
python -m pytest 'tests/web/w3/test_w3_c03_unit.py' -q
python -m pytest 'tests/web/w3/test_w3_c03_module.py' -q
git diff --check
git status --short
```

**完成判据**
- [x] `test_w3_c03_contract`、`test_w3_c03_negative` 与 `test_w3_c03_integration` 全部真绿且无无故 skip。
- [x] 当前行为满足本卡冻结决策、现有 CLI/Desktop 回归符合期望。
- [x] 安全拒绝、失败和取消按本卡约束实测，未开发路径标 `BLOCKED` 而不是 PASS。
- [x] `evidence/web/WEB-W3-C03/` 有红绿日志、协议快照（若适用）、diff、人工复审与交接。

**Commit（仅此卡）**
`feat(web): web-w3-c03 - 消息流/SSE Reducer/Run 断线续传`

---

### WEB-W3-C04 · Monaco 文件树/逐块 Diff/Git 审阅
`优先级：P1` / 预计工时：0.5–2.5 工程日 / 依赖：WEB-W3-C03,WEB-W2-C07 · **owner: frontend**

**背景与当前代码事实**
Web Coding 不能只在 Chat 展示代码文本，必须能查看真实 workspace、文件变更、Diff，并提交真实的用户审阅决定。

**涉及文件（白名单；`NEW` = 本卡新增，`VERIFY_EXISTING` = 本卡必须检查已有文件或前置卡产物；路径不符须 STOP/提交裁定）**
| 文件 | Grep 锚点/前置 | 允许的改法 |
|---|---|---|
| `apps/web/src/features/workspace/FileTree.tsx` | `NEW` | 文件树懒加载/权限状态 |
| `apps/web/src/features/workspace/DiffReview.tsx` | `NEW` | Monaco Diff + hunk decisions |
| `apps/web/src/features/workspace/GitPanel.tsx` | `NEW` | 变更列表/commit/PR 状态 |
| `packages/rxycode-server/src/rxycode_server/api/workspace.py` | `NEW` | 受租户约束的文件树、git diff 和带 base_revision 的审阅。裁定：冻结决策要求 server 读文件和 patch，现有 app 没有这条 API |
| `packages/rxycode-server/src/rxycode_server/api/projects.py` | `create_project` | 丢弃请求体里的 workspace_root 和 target_id。裁定：否则调用者能把项目指到服务器上的任意目录 |
| `packages/rxycode-server/src/rxycode_server/main.py` | `include_router` | 挂上工作区路由。裁定：不挂进 app factory，页面无法读到真实 diff |
| `apps/web/src/app/App.tsx` | `createBrowserRouter` | 挂上 `/projects/:projectId/workspace`。裁定：三个新组件需要一个路由才能打开 |
| `apps/web/src/sdk/client.ts` | `createClient` | 补上工作区读取和审阅。裁定：页面不直接 fetch |
| `apps/web/package.json` | `dependencies` | 增加 monaco-editor 与 @monaco-editor/react。裁定：本卡要求接 Monaco，锁文件随 bun.lock 提交 |
| `tests/web/w3/test_w3_c04_unit.py` | `NEW` | 严格单元契约，不得替生产降级 |
| `tests/web/w3/test_w3_c04_module.py` | `NEW` | 至少一个跨模块/进程/安全负测 |

**已经替你决定好的（不准自己发挥）**
读取文件与 patch 通过受权限保护的 server→runner API；前端的 accept/reject 必须提交带 base_revision 的真实命令，发生并发改动报告 conflict 而不覆盖用户工作。

**否定边界**：本卡不实现第二套 Agent Loop、不跨表外文件“顺手修复”、不降低旧 `RiskLevel`、不以 mock/live screenshot 替代契约验收。现有路径/版本/依赖不符即 `BLOCKED_PREREQUISITE`，提案修改先审计。

**操作步骤（依次执行；TEST-first）**
1. 在隔离工作树读本卡上游源文件及对应模块 README，`rg` 定位锚点，记录 baseline 与当前 commit；无锚点 STOP。
2. **先建 RED 测试**：在 `tests/web/w3/test_w3_c04_unit.py` 写 `test_w3_c04_contract`、`test_w3_c04_negative`，在 `tests/web/w3/test_w3_c04_module.py` 写 `test_w3_c04_integration`，先运行观察**预期失败**，保存日志。
3. 先写文件路径越权/多块 diff 和 revision conflict RED
4. 接 Monaco 和真实 diff backend API
5. 逐块 accept/reject 后 refresh 文件内容
6. 不同执行目标显示工作区标识。
7. 同步必要协议/生成 TS、更新模块文档，复跑 Unit→Contract→Process/E2E，保存 diff 与证据，单卡可独立 revert。

**测试施工（函数名锁定；Given / When / Then）**
- Unit `tests/web/w3/test_w3_c04_unit.py::test_w3_c04_contract`：Given 工具真实改了文件 When 打开 Diff Then hunk 与工作区实际变化匹配。
- Module `tests/web/w3/test_w3_c04_module.py::test_w3_c04_integration`：Given 文件变更与用户提交审阅竞态 When base_revision 过期 Then 拒绝并提示刷新。
- 反向 `tests/web/w3/test_w3_c04_unit.py::test_w3_c04_negative`：Given 未授权其他 Workspace When 使用路径猜测 Then 只能收到拒绝。
- E2E / Process：E2E-WEB-04 编辑→测试→Diff→逐块审批完成，重载不丢状态。
- 旧回归：任何碰 `core/` 或工具选取的卡加跑 `tests/test_cache/test_s1_s2_split.py` 和 `tests/test_cache/test_stable_prefix.py`；碰协议则加 `tests/test_protocol_schema.py`。

**验收命令（PowerShell；新测试文件由本卡创建，开卡前不得误判为已存在）**
```powershell
Set-Location 'D:\agent-demo\RxyCode\RxyCode1_1_0'
git status --short
python -m pytest 'tests/web/w3/test_w3_c04_unit.py' -q
python -m pytest 'tests/web/w3/test_w3_c04_module.py' -q
git diff --check
git status --short
```

**完成判据**
- [x] `test_w3_c04_contract`、`test_w3_c04_negative` 与 `test_w3_c04_integration` 全部真绿且无无故 skip。
- [x] 当前行为满足本卡冻结决策、现有 CLI/Desktop 回归符合期望。
- [x] 安全拒绝、失败和取消按本卡约束实测，未开发路径标 `BLOCKED` 而不是 PASS。
- [x] `evidence/web/WEB-W3-C04/` 有红绿日志、协议快照（若适用）、diff、人工复审与交接。

**Commit（仅此卡）**
`feat(web): web-w3-c04 - Monaco 文件树/逐块 Diff/Git 审阅`

---

### WEB-W3-C05 · xterm.js / PTY / 长活进程管理
`优先级：P1` / 预计工时：0.5–2.5 工程日 / 依赖：WEB-W3-C01,WEB-W2-C02 · **owner: frontend+runner**

**背景与当前代码事实**
需求是货真价实的交互终端，不能把过去的 bash stdout 静态渲染为 xterm.js。

**涉及文件（白名单；`NEW` = 本卡新增，`VERIFY_EXISTING` = 本卡必须检查已有文件或前置卡产物；路径不符须 STOP/提交裁定）**
| 文件 | Grep 锚点/前置 | 允许的改法 |
|---|---|---|
| `apps/web/src/features/terminal/TerminalPane.tsx` | `NEW` | xterm/resize/copy/exit |
| `packages/rxycode-server/src/rxycode_server/api/terminal_ws.py` | `NEW` | 授权 WS/进程 ID |
| `packages/rxycode-runner/src/rxycode_runner/local/pty.py` | `NEW` | Windows ConPTY/Linux PTY backend |
| `packages/rxycode-server/src/rxycode_server/main.py` | `include_router` | 挂上终端路由。裁定：不挂进 app factory，页面和测试都到不了 PTY |
| `apps/web/src/app/App.tsx` | `createBrowserRouter` | 挂上 `/terminal/:sessionId`。裁定：TerminalPane 需要一个路由才能在刷新后打开 |
| `apps/web/src/sdk/client.ts` | `createClient` | 补上终端读取。裁定：页面不直接 fetch |
| `apps/web/package.json` | `dependencies` | 增加 `@xterm/xterm`。裁定：本卡要求接 xterm.js，锁文件随 bun.lock 提交 |
| `apps/web/vite.config.ts` | `plugins` | 打包时去掉 xterm 的 electron 探测。裁定：浏览器包里出现 electron 会让 WEB-W3-C01 负向扫描失败 |
| `pyproject.toml` | `packages` | 登记 `rxycode_runner`。裁定：新包不进 setuptools 就不会被安装 |
| `requirements.txt` | `pywinpty` | Windows 上用 pywinpty 的 ConPTY。裁定：手写伪控制台句柄绑不上子进程 |
| `tests/web/w3/test_w3_c02_unit.py` | `_Stack` | 同源 WebSocket 升级转发到 API。裁定：浏览器终端连 `/api/v1/terminals/{id}/ws`，原来的静态代理不会升级 |
| `tests/web/w3/test_w3_c05_unit.py` | `NEW` | 严格单元契约，不得替生产降级 |
| `tests/web/w3/test_w3_c05_module.py` | `NEW` | 至少一个跨模块/进程/安全负测 |

**已经替你决定好的（不准自己发挥）**
PTY 生命周期独立于前端页面连接；终端输入/resize 双向，exit_code 真实；本机 Full Native 无沙箱；Cloud PTY 必须在沙箱内；禁通过前端以 tenant id 指挥任意主机。

**否定边界**：本卡不实现第二套 Agent Loop、不跨表外文件“顺手修复”、不降低旧 `RiskLevel`、不以 mock/live screenshot 替代契约验收。现有路径/版本/依赖不符即 `BLOCKED_PREREQUISITE`，提案修改先审计。

**操作步骤（依次执行；TEST-first）**
1. 在隔离工作树读本卡上游源文件及对应模块 README，`rg` 定位锚点，记录 baseline 与当前 commit；无锚点 STOP。
2. **先建 RED 测试**：在 `tests/web/w3/test_w3_c05_unit.py` 写 `test_w3_c05_contract`、`test_w3_c05_negative`，在 `tests/web/w3/test_w3_c05_module.py` 写 `test_w3_c05_integration`，先运行观察**预期失败**，保存日志。
3. 写终端输出/输入/resize/exit/断线拒绝
4. 实现 PTY 后端、WS 代理、xterm 的焦点和底部日志
5. 进程退出和网络断开通知由 Runner 确认
6. 负测跨租户 session。
7. 同步必要协议/生成 TS、更新模块文档，复跑 Unit→Contract→Process/E2E，保存 diff 与证据，单卡可独立 revert。

**测试施工（函数名锁定；Given / When / Then）**
- Unit `tests/web/w3/test_w3_c05_unit.py::test_w3_c05_contract`：Given PTY 启动 python -i When 输入 print Then 输出与交互一致且 exit_code 已知。
- Module `tests/web/w3/test_w3_c05_module.py::test_w3_c05_integration`：Given浏览器刷新 When PTY 还活着 Then 可重新附着或正确提示不支持。
- 反向 `tests/web/w3/test_w3_c05_unit.py::test_w3_c05_negative`：Given 权限不足 When WS 连接别人 PTY Then 握手拒绝且无进程泄漏。
- E2E / Process：E2E-WEB-05 在云端和本机执行真交互 terminal，录 stdout+进程退出。
- 旧回归：任何碰 `core/` 或工具选取的卡加跑 `tests/test_cache/test_s1_s2_split.py` 和 `tests/test_cache/test_stable_prefix.py`；碰协议则加 `tests/test_protocol_schema.py`。

**验收命令（PowerShell；新测试文件由本卡创建，开卡前不得误判为已存在）**
```powershell
Set-Location 'D:\agent-demo\RxyCode\RxyCode1_1_0'
git status --short
python -m pytest 'tests/web/w3/test_w3_c05_unit.py' -q
python -m pytest 'tests/web/w3/test_w3_c05_module.py' -q
git diff --check
git status --short
```

**完成判据**
- [x] `test_w3_c05_contract`、`test_w3_c05_negative` 与 `test_w3_c05_integration` 全部真绿且无无故 skip。
- [x] 当前行为满足本卡冻结决策、现有 CLI/Desktop 回归符合期望。
- [x] 安全拒绝、失败和取消按本卡约束实测，未开发路径标 `BLOCKED` 而不是 PASS。
- [x] `evidence/web/WEB-W3-C05/` 有红绿日志、协议快照（若适用）、diff、人工复审与交接。

**Commit（仅此卡）**
`feat(web): web-w3-c05 - xterm.js / PTY / 长活进程管理`

---

### WEB-W3-C06 · Plan/Todo/Approval/Subagent/Artifact 工作台
`优先级：P1` / 预计工时：0.5–2.5 工程日 / 依赖：WEB-W3-C03,WEB-W2-C06 · **owner: frontend**

**背景与当前代码事实**
原桌面已有 Todo/Activity/Plan/Team 语义，Web 应消费真实持久化 Event 和业务对象，不复制新 Planner。

**涉及文件（白名单；`NEW` = 本卡新增，`VERIFY_EXISTING` = 本卡必须检查已有文件或前置卡产物；路径不符须 STOP/提交裁定）**
| 文件 | Grep 锚点/前置 | 允许的改法 |
|---|---|---|
| `apps/web/src/features/plan/PlanDock.tsx` | `NEW` | Plan/Todo 权威投影 |
| `apps/web/src/features/approvals/ApprovalCard.tsx` | `NEW` | 审批/提问/超时 |
| `apps/web/src/features/agents/AgentTree.tsx` | `NEW` | 子 Agent 生命周期/费用 |
| `apps/web/src/features/artifacts/ArtifactPanel.tsx` | `NEW` | 产物和下载 |
| `apps/web/src/features/chat/ChatPage.tsx` | `useRunEvents` | 挂上四个工作台组件。裁定：运行页是这些投影的现成入口 |
| `apps/web/src/features/runs/eventReducer.ts` | `reduceEvents` | 补上 plan/todo/agent 投影。裁定：不另写一套 Planner，沿用已有事件归约 |
| `apps/web/src/sdk/client.ts` | `createClient` | 补上审批读取、审批决定、问题回答和产物列表。裁定：页面不直接 fetch |
| `packages/rxycode-server/src/rxycode_server/api/approvals.py` | `post_approval` | 增加问题读取和回答。裁定：协议有 question 事件，现有 web API 没有提交入口 |
| `core/question.py` | `SseQuestionBroker.ask` | 用共享邮箱登记待回答问题并接收 web 答案。裁定：worker 的 broker 不在 API 进程里 |
| `appserver/question.py` | `PipeQuestionBroker.ask` | 同样轮询这个邮箱，让 JSON-RPC 等待能被 web 回答唤醒。裁定：生产问题走 `question/request` |
| `tests/web/w3/test_w3_c06_unit.py` | `NEW` | 严格单元契约，不得替生产降级 |
| `tests/web/w3/test_w3_c06_module.py` | `NEW` | 至少一个跨模块/进程/安全负测 |

**已经替你决定好的（不准自己发挥）**
审批只向 Server POST，状态由后端新事件确认；子 Agent intermediate 不入主最终答复；允许用户完成暂停/拒绝/问题回答；旧 U 系列 Plan/Todo ID 不重定义。

**否定边界**：本卡不实现第二套 Agent Loop、不跨表外文件“顺手修复”、不降低旧 `RiskLevel`、不以 mock/live screenshot 替代契约验收。现有路径/版本/依赖不符即 `BLOCKED_PREREQUISITE`，提案修改先审计。

**操作步骤（依次执行；TEST-first）**
1. 在隔离工作树读本卡上游源文件及对应模块 README，`rg` 定位锚点，记录 baseline 与当前 commit；无锚点 STOP。
2. **先建 RED 测试**：在 `tests/web/w3/test_w3_c06_unit.py` 写 `test_w3_c06_contract`、`test_w3_c06_negative`，在 `tests/web/w3/test_w3_c06_module.py` 写 `test_w3_c06_integration`，先运行观察**预期失败**，保存日志。
3. 写 approval 过期/重复点击、Agent 序列化、artifacts 拒绝 RED
4. 集成待审批列表/时间/风险与 target
5. 实现 Todo dock / Artifact list / Agent tree
6. 校验长时间任务的焦点和可用性。
7. 同步必要协议/生成 TS、更新模块文档，复跑 Unit→Contract→Process/E2E，保存 diff 与证据，单卡可独立 revert。

**测试施工（函数名锁定；Given / When / Then）**
- Unit `tests/web/w3/test_w3_c06_unit.py::test_w3_c06_contract`：Given waiting_approval When 显示审批卡 Then 用户能看目标工具/路径/时限。
- Module `tests/web/w3/test_w3_c06_module.py::test_w3_c06_integration`：Given 用户批准 When server 尚未确认 Then UI 不立即标记 succeeded。
- 反向 `tests/web/w3/test_w3_c06_unit.py::test_w3_c06_negative`：Given 审批已过期 When 再点批准 Then UI 呈现冲突不假继续。
- E2E / Process：E2E-WEB-03 人工审批→刷新→再审批→Run 继续直到终态。
- 旧回归：任何碰 `core/` 或工具选取的卡加跑 `tests/test_cache/test_s1_s2_split.py` 和 `tests/test_cache/test_stable_prefix.py`；碰协议则加 `tests/test_protocol_schema.py`。

**验收命令（PowerShell；新测试文件由本卡创建，开卡前不得误判为已存在）**
```powershell
Set-Location 'D:\agent-demo\RxyCode\RxyCode1_1_0'
git status --short
python -m pytest 'tests/web/w3/test_w3_c06_unit.py' -q
python -m pytest 'tests/web/w3/test_w3_c06_module.py' -q
git diff --check
git status --short
```

**完成判据**
- [x] `test_w3_c06_contract`、`test_w3_c06_negative` 与 `test_w3_c06_integration` 全部真绿且无无故 skip。
- [x] 当前行为满足本卡冻结决策、现有 CLI/Desktop 回归符合期望。
- [x] 安全拒绝、失败和取消按本卡约束实测，未开发路径标 `BLOCKED` 而不是 PASS。
- [x] `evidence/web/WEB-W3-C06/` 有红绿日志、协议快照（若适用）、diff、人工复审与交接。

**Commit（仅此卡）**
`feat(web): web-w3-c06 - Plan/Todo/Approval/Subagent/Artifact 工作台`

---

### WEB-W3-C07 · 移动响应式/A11y/错误页/前端稳定性
`优先级：P1` / 预计工时：0.5–2.5 工程日 / 依赖：WEB-W3-C01..C06 · **owner: frontend/qa**

**背景与当前代码事实**
求职产品需要正常用户也能使用：手机查看任务/审批，键盘导航可达，断线/授权失败不能无尽加载。

**涉及文件（白名单；`NEW` = 本卡新增，`VERIFY_EXISTING` = 本卡必须检查已有文件或前置卡产物；路径不符须 STOP/提交裁定）**
| 文件 | Grep 锚点/前置 | 允许的改法 |
|---|---|---|
| `apps/web/src/app/responsive.css` | `NEW` | 断点/字体/深浅色/可读性 |
| `apps/web/src/features/notifications/RunStatusBanner.tsx` | `NEW` | 状态/重连/失败提示 |
| `apps/web/playwright.config.ts` | `NEW` | Chrome/Firefox/移动设备 E2E 配置 |
| `tests/web/w3/test_w3_c07_unit.py` | `NEW` | 严格单元契约，不得替生产降级 |
| `tests/web/w3/test_w3_c07_module.py` | `NEW` | 至少一个跨模块/进程/安全负测 |
| `apps/web/src/features/chat/ChatPage.tsx` | `useRunEvents` | 挂上运行状态条。裁定：运行页是状态、重试和审批入口的现成页面 |
| `apps/web/src/sdk/client.ts` | `createClient` | 增加取消运行。裁定：页面不直接拼取消请求 |
| `packages/rxycode-server/src/rxycode_server/api/runs.py` | `get_run` | 增加取消接口。裁定：现有运行读取没有取消入口 |
| `apps/web/package.json` | `devDependencies` | 增加 axe-core。裁定：验收要在页面上跑 axe |
| `apps/web/bun.lock` | `axe-core` | 锁住 axe-core。裁定：与 package.json 一起 |

**已经替你决定好的（不准自己发挥）**
WCAG 2.2 AA 作为目标，视口 375/768/1440；移动端编辑器可以只读，但审批/查看/取消不可缺；结果卡不得依赖颜色唯一表达。

**否定边界**：本卡不实现第二套 Agent Loop、不跨表外文件“顺手修复”、不降低旧 `RiskLevel`、不以 mock/live screenshot 替代契约验收。现有路径/版本/依赖不符即 `BLOCKED_PREREQUISITE`，提案修改先审计。

**操作步骤（依次执行；TEST-first）**
1. 在隔离工作树读本卡上游源文件及对应模块 README，`rg` 定位锚点，记录 baseline 与当前 commit；无锚点 STOP。
2. **先建 RED 测试**：在 `tests/web/w3/test_w3_c07_unit.py` 写 `test_w3_c07_contract`、`test_w3_c07_negative`，在 `tests/web/w3/test_w3_c07_module.py` 写 `test_w3_c07_integration`，先运行观察**预期失败**，保存日志。
3. 先做 a11y/keyboard/375px overflow RED
4. 实现移动抽屉、状态/焦点管理、错误恢复和主题
5. 测试 200% zoom / 低网速断线 / 虚拟化日志
6. 截图仅补充功能证据。
7. 同步必要协议/生成 TS、更新模块文档，复跑 Unit→Contract→Process/E2E，保存 diff 与证据，单卡可独立 revert。

**测试施工（函数名锁定；Given / When / Then）**
- Unit `tests/web/w3/test_w3_c07_unit.py::test_w3_c07_contract`：Given 键盘用户 When 打开审批弹窗 Then 焦点受控且可返回原位置。
- Module `tests/web/w3/test_w3_c07_module.py::test_w3_c07_integration`：Given 375px viewport When 打开活动 Run Then 可查看状态/审批/取消。
- 反向 `tests/web/w3/test_w3_c07_unit.py::test_w3_c07_negative`：Given API 不可达 When 访问工作台 Then 显示可恢复错误而非白屏。
- E2E / Process：E2E-WEB-06 375/768/1440 + keyboard + axe-core 自动检查。
- 旧回归：任何碰 `core/` 或工具选取的卡加跑 `tests/test_cache/test_s1_s2_split.py` 和 `tests/test_cache/test_stable_prefix.py`；碰协议则加 `tests/test_protocol_schema.py`。

**验收命令（PowerShell；新测试文件由本卡创建，开卡前不得误判为已存在）**
```powershell
Set-Location 'D:\agent-demo\RxyCode\RxyCode1_1_0'
git status --short
python -m pytest 'tests/web/w3/test_w3_c07_unit.py' -q
python -m pytest 'tests/web/w3/test_w3_c07_module.py' -q
git diff --check
git status --short
```

**完成判据**
- [x] `test_w3_c07_contract`、`test_w3_c07_negative` 与 `test_w3_c07_integration` 全部真绿且无无故 skip。
- [x] 当前行为满足本卡冻结决策、现有 CLI/Desktop 回归符合期望。
- [x] 安全拒绝、失败和取消按本卡约束实测，未开发路径标 `BLOCKED` 而不是 PASS。
- [x] `evidence/web/WEB-W3-C07/` 有红绿日志、协议快照（若适用）、diff、人工复审与交接。

**Commit（仅此卡）**
`feat(web): web-w3-c07 - 移动响应式/A11y/错误页/前端稳定性`

---

## §2 Wave 出口检查
- [ ] W3 所有卡各有独立 commit 和 evidence，未勾选项不被宣称完成。
- [ ] 既有行为回归没有被覆盖，新增 API 不依赖 mock/假状态。
- [ ] 运行期错误、权限拒绝和用户可见状态有负向证据。
