# RxyCode v1.4.3 CHANGELOG

> 变更管理约定：开发期随改随记；条目被撤回时同步删除/标注。发版时随版本号滚动为新文件。
> 基线：v1.4.2（同版本刷新批次 f96ce3fd）。

## 键位更正（2026-10-11）Ctrl+T 改回思考开关

用户裁定：`Ctrl+T` 是思考展开开关（Ink 版 `frontend/src/App.tsx` 与设计稿
`frontend/_palette.txt` 的原始约定），FIX5 做 Todo dock 时把它挪给 Todo、把思考挤到
`Ctrl+E` 是错的。本版**换回**：`Ctrl+T` = 展开/折叠思考，`Ctrl+E` = 打开/收起 Todo。

- 改动文件（OpenTUI）：`todoDock.ts`（`keyAction` 单点互换）、`statusBar.ts`（完整/紧凑
  文案）、`brand.ts` 快捷键行、`DialogDoc.tsx`、`DialogSettings.tsx` 快捷键条目、
  `types.ts` / `lib/thinkingDisplay.ts` 注释；对应测试 `todoDock.test.ts` /
  `statusBar.test.ts` 同步更新。
- 用户文档：README / README.zh-CN 快捷键表互换描述。
- 历史文档跟进（按"内容撤回文档同步"约定）：`CHANGELOG.md`、`RELEASE_NOTES_v1.4.2.md`、
  `CHANGELOG_v1.4.2.md` 中的旧键位描述均加 ⚠️ 更正标记，不删除历史事实。
- Ink 版一直是 `Ctrl+T`=思考，无需改动；桌面端 `Ctrl+T`=浏览器面板属另一键位体系，不受影响。

## 性能修复（2026-10-11）/model 与 /session 卡顿

### 背景

- `/model` 选中模型后长时间停在"正在切换模型..."。
- `/session` 打开会话目录有时巨慢。

两处共同根因：Windows 上的同步磁盘 I/O（config 读写 + `icacls` 修 ACL 的子进程风暴、26MB `tasks.json` 全量重写）跑在 asyncio 事件循环上，把 loop 冻结数秒。

### 后端修复

| 位置 | 修改 | 原因 |
|---|---|---|
| `appserver/agent_worker.py` | worker 的 `model/switch` 改 `asyncio.to_thread(self._agent.switch_model, ...)` | 原同步调用含 save_history 原子写 + load_config + DPAPI 解密，1–3s 内 worker 心跳/中断/输出全部停摆，30s 超时兜底即"巨慢"体感 |
| `appserver/server.py` | `models/list`、`models/set_active` handler 改 `asyncio.to_thread` | 同步 load_config/save_config + icacls 子进程冻结整个 appserver loop，所有会话一起卡 |
| `appserver/server.py` | `_handle_session_set_model` 删除重复的全局 `set_active` 持久化 | 前端 `switchModel` 已先调 `models/set_active`（唯一全局持久化点）；这里重写一遍 config = 又一轮 icacls 风暴。协议 `protocol/requests.py` 本来就约定 "without changing the global CLI default"，旧行为与其矛盾；桌面端 `setTaskModel` 本就是任务级语义。任务记录上的 model 仍照常持久化 |
| `appserver/task_store.py` + `server.py` | 回放事件改 `append_event_buffered`：内存 append 仍在 loop 上做，26MB 的跨进程锁 + 重读 + merge + 全量重写 + fsync 由后台 flusher 合并落盘（0.2s 窗口，快照 + `drop_generation` 防止 purge 穿插回写）；优雅关停 `flush_pending` 兜底 | 根因最直接的修复：回合运行期间每个 replay 事件都同步全量重写 26MB `tasks.json`，loop 被反复冻结 → 用户在跑工具时打开 /session 就"有时巨慢"。语义代价（已注释声明）：强杀进程可能丢最后 ≤0.2s 的回放展示事件（非执行真相） |
| `config/credential_store.py` | `restrict_file_permissions` 按路径缓存 `(size, mtime_ns, exists)`，文件未变跳过 icacls；`atomic_write_bytes` 写后主动失效缓存；`RXYCODE_DISABLE_ACL_CACHE=1` 可回退旧行为 | 一次模型切换原需 15–30+ 个 `icacls` 子进程（每个 15s 超时兜底、杀软环境 50–300ms），是 /model 慢的头号外部耗时。缓存进程内有效；icacls 幂等，多进程最坏多跑一次 |

### 前端修复（OpenTUI）

| 位置 | 修改 | 原因 |
|---|---|---|
| `frontend/opentui-app/src/transport/stdioTransport.ts` | `switchModel` 在 `session/set_model` 失败时返回 `ok:false` + "切换失败，请重试"，不再刷新状态快照 | 修复假成功 bug：全局 active 已切但 worker 还跑旧模型，界面却提示已切换、芯片显示新模型。无 session（② skipped）时全局默认已切，仍算成功 |
| 同文件 | `listModels()` in-flight 合并 | 切换成功后 `fetchStatus()` 与 `fetchModels()` 同拍触发同一 `models/list`，合并为一次请求 |
| 同文件 | `listSessions()` 改 `requestWithTimeout`（8s） | 原 `client.request` 无超时：服务端 loop 被卡死静默时不应答，对话框无限转圈。超时直接交还 UI 错误态，不触发 respawn（与进程已死区分） |
| `frontend/opentui-app/src/dialog/DialogSessionList.tsx` | 模块级 stale-while-revalidate 缓存：二次打开立即渲染上次目录、后台刷新替换；刷新失败保留缓存行、底栏提示；`__clearSessionListCacheForTests` | 原每次打开白等全量重拉无缓存 |
| `frontend/opentui-app/src/transport/index.ts` | `__setChatTransportForTests` 测试注入口 | 支撑上述缓存测试，不走 `mock.module`（全量跑泄漏） |

### 测试

- 新增/更新：`tests/test_appserver/test_desktop_task_store.py`（buffered flush 合并/等价/多进程 merge/purge）、`tests/test_appserver/test_session_model.py`、`tests/test_core/test_credential_acl_cache.py`、`frontend/opentui-app/src/transport/stdioTransport.switchModel.test.ts`、`stdioTransport.listSessions.test.ts`、`src/dialog/DialogSessionList.cache.test.tsx`。
- 门禁：appserver 199 passed / 1 skipped（live-gated）；credential 相关 20 passed；ruff appserver+config 全过；前端 bun test **333 passed / 0 fail**；`tsc --noEmit` 零错。

#### 追加：`/model` 打开时的 models/list 慢（2026-10-11 真实环境复测发现并修复）

真实环境（66 模型、349 会话、26MB 台账）实测 `models/list` 每次调用 1.3–2.0s。
cProfile 定位：`resolve_model_config` 每模型一次 → 57 次 `load_credential` →
**57 次纯 Python `yaml.safe_load` 重复解析同一 credentials.yaml**（1.37s）+
59 次 `get_data_dir` 每次重跑 legacy 目录迁移扫描（0.47s）。

| 位置 | 修改 | 原因 |
|---|---|---|
| `config/credential_store.py` | `_read_store` 按 `(path, size, mtime_ns)` 签名缓存解析结果，命中返回浅拷贝；`_write_store` 与任何外部写入（mtime 变化）自动失效；与 ACL 缓存共用 `RXYCODE_DISABLE_ACL_CACHE=1` 回退开关 | 同文件没变化时重复 parse 是纯浪费；写后必须读到新内容，防 store_credential 拼装污染缓存因此返回拷贝 |
| `config/settings.py` | `_migrate_legacy_data_if_needed` 按目标路径记忆（`_MIGRATED_TARGETS`），进程内同一目录只迁移一次（含失败标记） | 迁移本就是幂等的"缺则补齐"；热路径上重复扫描是 0.4s+ 白工。RXYCODE_DATA_DIR 切换的测试不受影响（按路径区分） |

实测：`models/list` 冷 0.88s → **热 0.10–0.12s**；`models/set_active` 80–90ms；
`sessions/list`（349 会话）60–125ms。测试：
`tests/test_core/test_credential_read_store_cache.py`（4）、
`tests/test_core/test_migration_memo.py`（2）+ 全量门禁通过。

#### 追加：上面性能改动引入的正确性，以及仍同步的热路径（2026-10-11）

上面的缓冲快照和 `to_thread` 没有拆掉 stdin 读循环，也没有挡住旧快照回写。
本段只记这次补上的行为和本机函数测量，不重复宣称 `/model`、`/session` 的界面加速。

| 位置 | 修改 | 原因 |
|---|---|---|
| `appserver/task_store.py` | 模型、标题、状态、用量、回收、恢复、重启门和 purge 都增加代次；快照复制任务行，代次不一致则放弃该轮并重刷 | 缓冲事件先拍下旧行，`upsert` 已换成新模型/标题/终态后，旧快照仍把磁盘写回旧值和 `running`。`drop_generation` 原先只覆盖 purge |
| `frontend/.../stdioTransport.ts` | 管理 RPC（含 `models/list`、`session/events`）走有界等待，超时清掉 inflight。`session/prompt`、`session/warm` 不套这个短超时。`attachSession` 只有事件加载成功才提交新 `sessionId` | 无超时的 `models/list` 被 inflight 合并后，后续读取挂在同一个 Promise。加载失败前改会话身份会串会话 |
| `core/agent_v2.py`、`stdioTransport.ts` | 切换边界只刷新模型表。新 LLM、provider、能力和 memory 建成后才提交。失败后状态轮询锁住切换前的 worker 模型，不回滚其他窗口的全局 active | 已启动 worker 用启动时的 `self._cfg`，看不到刚添加的模型。失败后轮询用全局默认模型冒充当前 worker |
| `DialogSessionList.tsx` | 每次打开增加代次，关闭弹窗的迟到结果不写缓存。刷新失败仍保留缓存 | 旧弹窗返回覆盖新弹窗已经拿到的列表 |
| `appserver/server.py` | stdin 单独线程。中断、steer、审批回复不排在发现/连接测试/切换后面。同会话 prompt 与 `set_model` 按到达顺序。配置写入单车道。发现类请求最多 4 路，关停时排空 | `run` 等完整 `_dispatch` 返回才读下一行。handler 里的 `to_thread` 让出了事件循环，但读不到已经在 stdin 里的中断和审批回复 |
| `sessions.py`、`task_store.py` | 用量、终态、重命名在有事件循环时并入已有 0.2s 刷盘。内存立刻更新。无循环时仍立即保存。关停 `flush_pending` 排空 | 这三项仍每次同步重写整份 `tasks.json`。20 次用量加终态加重命名是 22 次读 |
| `model_manager.py`、`credential_store.py`、`api_server_models.py` | 批量添加先校验，再一次凭据写、一次配置写。每个模型仍有独立凭据引用，失败只删这一批新引用。HTTP 单模型添加放到 `to_thread`，并用 `activate=True` 合并第二次 `set_active` 写 | 20 个模型原来 22 次 load、21 次 save、20 次凭据文件写 |
| `sessionEventsToMessages.ts` | `tool_end` 用 `call_id` 索引配卡片。打开会话仍拉完整 `session/events`，不用截断的 `session/items` 代替全量恢复 | 每个 `tool_end` 复制、反转并扫描全部消息 |

本机测量（不是 TUI 按键、首屏、网络或 worker bootstrap）：慢发现期间中断进入处理 5 次，中位数 0.20ms（0.11–0.23ms），改前 500ms 内进不了处理。2 万对 tool 事件转换 5 次，中位数 13.5ms（7.0–23.8ms），改前单次约 559ms。20 次用量加终态加重命名在循环上 5 次，中位数 0.27ms（0.26–0.40ms），磁盘合并为 1 读 1 写。批量 20/100 个模型各 1 次 load、1 次 save、1 次凭据文件写；该计时是内存假写入，不是 DPAPI 磁盘时间。

#### 追加：审计确认的三处正确性（2026-10-11）

- `onboard_models_batch` 提交时在 `hold_config_lock()` 里重新读取配置，只合并本批尚未存在的模型。连接检查不持有这把锁。`add_model`、`set_active_model`、`remove_model`、清凭据走同一把跨进程文件锁。进程内 `RLock` 不充当跨进程保护。保存失败只删除本轮新建的凭据引用。
- 失败切模锁定的是任务的 `model_id`，不再用显示名称反查。加载另一会话、重连和成功切模会替换该 id。名称、服务商后缀和上下文上限来自同一个模型条目。
- 会话弹窗每次刷新递增序号。同一次打开里，置顶、重命名或 Fork 的结果不会被更早的 `sessions/list` 盖回。
- `stdioTransport.todo.test.ts` 的桩补上 `requestWithTimeout`，三条原有 Todo 行为继续断言内容，不只判断不抛异常。

#### 追加：三个异步边界（2026-10-11）

- 凭据文件的添加、批量添加和删除用 `exclusive_file_lock` 包住完整读改写，不再只靠进程内 `_STORE_LOCK`。先放开凭据锁，再拿配置锁，避免和 `add_model` 里「先配置、后凭据」交叉死锁。双进程测试在隔离目录用测试密钥复现：两边都写成功后两个引用都能读回。
- `switchModel` 在第一个 await 之前固定目标 `session_id`、原模型 id 和 `attachGeneration`。`session/set_model` 使用这个固定会话。响应只有在代次和会话都没变时才改当前模型 id 或状态条。最后一次状态刷新结束后再查一次；期间若已加载另一会话，不再返回 `model_changed`。
- 会话弹窗用实例存活标记。关闭之后，置顶、重命名、Fork 的迟到回调可以让后台操作结束，但不再调用 `reload()`，因此不会递增全局序号，也不会改缓存或界面。

## 安全：MCP 接入三防线（2026-10-12）

用户裁定按审计结论修。三条基线原本状况：description 审计部分有、版本锁定没有、最小权限凭证部分有。本批落地：

| 防线 | 修改点 | 说明 |
|---|---|---|
| **投毒审计**（新模块 `mcp/tool_poisoning.py`） | `mcp/client.py` tools/list 解析处 | description 原样进模型系统提示此前无防线。命中 `<IMPORTANT>`/"ignore previous instructions"/`<system>`/密钥外泄/敏感文件读取模式时：给模型可见的 `⚠ description flagged` 警告前缀 + warning 日志（fail-open，不静默注册） |
| **审批可见性** | `core/safety/approval.py`、`appserver/approval.py`、`execution/tool_orchestrator.py`、`ApprovalDialog.tsx`、`stdioTransport.ts` | 审批载荷携带工具完整 description（`details.description`，additive 不改协议），OpenTUI 审批弹窗新增 `Desc:` 行——用户复核时第一次能读到外部（如 MCP）工具自己写的说明 |
| **版本钉死** | `tools/mcp_manager.py`、`appserver/plugin_service.py` | `_NPM_PACKAGE_RE` 允许 `pkg@version`/`@tag`（原来禁止 @后缀，`npx -y 裸包名`是静默拉最新通道）；GitHub MCP docker 镜像钉 `v0.5.0`（原隐式 `:latest`），升级=改常量+重审 |
| **清单重审**（新模块 `mcp/tool_manifest.py`） | `core/agent_v2.py` 注册/移除路径 | 每 server 持久化 `(description, schemas)` 哈希基线到 `<data_dir>/mcp/tool_manifests.json`；`tools/list_changed` 热重注册时比对：漂移记 warning（+/-/~ 工具名明细）+ `runtime_status().mcp.manifest_drift` 计数聚合，fail-open 注册且新清单立即成为基线（每次真实变化只报一次）。server 移出配置时基线同步清除 |
| **最小权限 env** | `mcp/client.py`（墓石注释） | `GITHUB_PERSONAL_ACCESS_TOKEN`/`GH_TOKEN` 移出全局继承白名单——原来任何 server（含无关天气 server）的子进程都能读到仓库级 PAT。github 系仍由 `mcp/github_auth.py` 按名字门控注入；其它 server 如需请显式配 `mcpServers.<name>.env` |

**测试**：新增 `tests/test_mcp/test_supply_chain_guards.py`（27）、`ApprovalDialog.test.tsx`（2）；插件运行时断言改读常量防 tag 升级再红；`runtime_status().mcp` 精确断言补 `manifest_drift` 键。门禁：mcp/plugin/approval/安全 82 passed、tools/contract 53 passed、test_appserver 767 passed、test_core 分段全绿（credential 顺序依赖 flake 仍为既有问题）、ruff 全过、前端 bun test **386 passed / 0 fail**、tsc 零错。

**已知非本批负债（不静默吸收）**：`test_lazy_import_budget` 在 HEAD（67975be2，剪贴板批次）已红（184 ≥ 181），与本次修改无关（本批模块级导入，懒导入增量为 0），待该批次作者修复 ratchet。

### K3 复审四条接缝（2026-10-12）

GPT 对上一批 MCP 安全加固的复审指出四个真实缺口，全部关闭（fail-open
语义、github 名称门控宽度均为既有设计/风险，不在本批变更范围）：

1. **Schema 漂移漏报**：`signature_for_tools` 原把 `StructuredTool.args_schema`
   （pydantic 类）直接序列化，只剩 repr——参数类型/输出结构变了哈希不变。
   现在 MCP 适配器把原始 `inputSchema`/`outputSchema` 存进
   `metadata['mcp_input_schema']`/`['mcp_output_schema']`，签名优先用原始
   schema；非 MCP 路径语义化回退 `model_json_schema()`。参数类型漂移必然改哈希。
2. **扫描范围不足**：投毒扫描原先只查工具级 description——参数 description
   同样进模型。新增 `scan_schema_descriptions` 递归扫描 schema 图
   （properties/items/anyOf/allOf/oneOf/$defs/definitions/patternProperties），
   命中按参数路径命名（如 `parameter description 'mode': ...`），上限 20 条防洪。
3. **审批描述截断**：弹窗原截 120 字符——投毒文本常藏在中后段。新增 `v` 键
   展开/收起全文（仅当超限时显示提示），底栏快捷键提示同步显示。
4. **清单存储并发/类型**：原来读-改-写合并裸跑，多窗口并发互丢基线；
   顶层非 dict 时 `.get` 抛 AttributeError 被外层 except 吞掉 = 复核静默跳过。
   现在 `update_baseline`/`remove_baseline` 在跨进程锁内读-改-写合并
   （不再调用方手动 load+save）；加载改为逐条类型校验，坏条目按条丢弃并记
   warning，顶层类型错误按空基线处理并明确记 log，不再静默跳过。

测试：`tests/test_mcp/test_supply_chain_guards.py` K3 段 +10（pydantic 类型漂移、
原始 schema 优先、输出结构变化、嵌套参数扫描、12 线程并发写合并、单 server
移除原子性、非 dict 顶层/非字符串 digest 降级）；前端 `ApprovalDialog.test.tsx`
+1（长描述默认截断、按 v 展开含尾部指令段）。门禁：守卫套件 37 passed；
mcp/plugin/approval/安全 92 passed；appserver+bridge+cache 701 passed（1 项
auto-route stdio 时序 flake，单跑绿）；core 分段 7681 passed（懒导入门槛仍为
剪贴板批次遗留红，本批增量为 0；credential/watchdog 两 flake 单跑均绿）；
bun test 387 passed / 0 fail；tsc 零错；ruff 全过。

## 遗留（本轮精准修复未覆盖，后续立项）

- `tasks.json` 单文件巨石（26MB+）应改 append-only 分段存储（JSONL + 独立元数据小文件）——根治病灶，属存储层重构。
- `AppServer.__init__` 冷启动同步全量 parse + 约 20 个 service eager 构造，可懒加载。
- 模型目录同 `(provider_model_id, base_url)` 条目在列表中重复显示的 merge 去重。

## CLI 内存治理记录（2026-10-11）

- 新增 [CLI 内存治理记录](../CLI-MEMORY-MANAGEMENT-2026-10-11.md)：TUI 1000 条 transcript native nodes 由 9354 降至 760；匹配的 100 MB Bash fixture（k=3）峰值 RSS 约低 79%，样本耗时未显示速度提升。
- 独立候选组合 gate 10292 passed、1 skipped、47 warnings（279.94 秒；core/tools/appserver/subagents/integration/contract/system cancellation/packaging）；shell+tools+cancellation 1045 passed，reader/consumer 18 passed，worker owner/parent gates 20/19 passed，Ruff 全绿。
- 内存变更于 2026-10-11 集成到 primary 工作树；primary fresh proof：appserver/subagents/capture-consumers-security/realAgent/cancel 711 passed、1 skipped（75.89 秒），TUI 354 passed、0 failed（70 files，28.52 秒），tsc、Ruff touched files 和 scoped diff check 通过。需重启 RxyCode 加载；不是发布，产品版本仍为 1.4.2。
- K3 基线 `53e5bae5` 未变，primary 与隔离树 normalized code 全部匹配；本次按用户授权仅提交本地 master，不推送、不发布，其他 WIP 与计划文档不纳入。结果不是全仓库/live 覆盖，内存限制与 fixture 边界见报告。

## TUI 剪贴板附件（2026-10-11，实施记录；验收未完成）

主 OpenTUI 提示框支持从本机剪贴板添加文件或截图：在 Explorer 复制文件后回到提示框按 `Ctrl+V`；终端截获快捷键时可用 `Alt+V` 或 `/paste`。附件可在发送前通过 `/removeattachment` 移除。原有 `usePaste` 继续处理普通终端文本粘贴，未废弃；OpenTUI 仍为 0.4.5，Ink 附件交互不属于本轮目标。

### 入口与实现文件

| 位置 | 本轮行为 |
|---|---|
| `frontend/opentui-app/src/App.tsx`、`frontend/opentui-app/src/transport/stdioTransport.ts` | 用户触发粘贴、附件草稿与排队快照、提交前 capability guard；legacy 服务不支持时明确拒绝，不 silent drop |
| `utils/clipboard_capture.py` | 一次性本机 helper 读取文件列表、位图或文本；读取有界，3.5 秒超时及其他失败显式报告，不轮询 |
| `protocol/requests.py` | `PromptRequest.attachments` 为可选 path/name 列表，默认空列表，兼容无附件请求 |
| `appserver/server.py`、`appserver/agent_host.py`、`appserver/agent_worker.py` | stdio `initialize` 声明附件能力，沿既有 `handleprompt → AgentHost → worker` 传递附件 |
| `core/session.py`、`core/agent_v2.py` | Session 校验并准备附件，主 prompt 通过 `_build_prompt_human_message` 单一工厂生成文本或真实 image blocks |
| `api_server.py` | HTTP `/status` 提供附件 capability 并用于发送前 guard；`/chat` 与 `/chat/stream` 进入同一 Session（不是 `/chatstream`），与 stdio 共用既有 headless 入口；旧 server 明确拒绝附件请求 |

旧无附件 prompt 的直接 `HumanMessage` 构造路径已由 `_build_prompt_human_message` 替代，无附件仍产生原有纯文本消息。附件路径经 `PromptRequest → server/AgentHost/worker → Session.prepare → AgentV2`；只在确有附件时将只读准备放入 `asyncio.to_thread`，无附件请求不进入该线程路径。取消后的旧准备结果不绑定，queued turn 冻结自身副本。非视觉模型的文本仍是字符串；真实图像块只在 vision capability 检查通过后构造。`Session._dispatch_user_turn` 对普通附件 turn 跳过旧 team/multi-agent 分派，直接走主 AgentV2，附件不继承到 child；携带附件的显式路由切换命令另有 guard。真正因不能保留附件而 preflight 拒绝的路径包括复杂 Compose、file/download，不能笼统写成 team 状态下的附件请求被拒绝。

### 能力与限制

- 小型 UTF-8 文本有界内联，每文件 32 KiB、每轮合计 64 KiB。图片（包括 BMP/TIFF/ICO）规范化为 PNG，只有模型视觉 capability 允许时才发送真实 `HumanMessage` image blocks；不以路径或 metadata 冒充图像输入，也不自动换模型。
- PDF、视频仅作为文件引用供现有工具使用，不承诺模型原生理解其内容。每轮最多 10 个附件、其中最多 5 张图片；源图像 5 MiB、模型图像 URL 5 MiB、解码 20 MP、最长边 2048 px 等限制使准备过程有界。
- 附件 turn 旁路精确与语义答案缓存，provider prefix 行为未改。图像 occupancy 的约 1024 token reserve 是预算近似，不是实际计量或账单；旧图按 `tail_turns` 压为摘要或引用，当前与最新图像受保护。
- 临时 PNG 保存在持久 temp 目录，保留 queued/history 引用，不在当轮结束时删除。目前没有自动、安全的引用计数清理策略或 GC；后续清理必须先确认引用已解除。冷启动只持久化附件 metadata，不承诺恢复或冷启动后自动重建视觉上下文。

### 验证状态（2026-10-11 阶段记录）

父代理本轮独立运行的阶段回归结果：fresh Bun 380 passed / 0 failed，`tsc` 通过；protocol 29 passed，`tsc` 通过；compaction/attachment Python 97 passed / 1 skipped；provider/tools/subagent Python 2164 passed。当时更广门禁仍在运行，并有失败待查；后续冻结快照结果见 2026-10-12 追加记录。

早期 broker snapshot/backup 预检失败，但证据不能确认 managed clipboard 当时无法完成校验的原因，不推测为 opaque 格式问题。另一次旧预检在没有测试写入时仍进入 restore，缺少原内容 digest，不能确认精确恢复，也不能声称发生了数据丢失。新版 broker 的 backup-failure 记录为零次写入、零次恢复；用户主动复制普通文本后，中间一次运行备份 7 种格式并验证 restored hash 一致。最终三轮均验证剪贴板恢复 hash；前两轮备份 5 种格式，细节见下方验收记录。

### 阶段记录与最终验收（2026-10-12）

已核对源码的修复：`App.tsx` 使用 OpenTUI 0.4.5 实际解析的 `option/meta` 处理 Alt+V；`clipboard.ts` 用 `python -I -X utf8` 隔离启动 helper，避免 `utils/queue` 遮蔽标准库 `queue`，并在非零退出码时解析和透传 helper 的 error JSON。原有文本 `usePaste` 路径保留。

父代理冻结 source 后的 core/appserver/bridge/cache/protocol/packaging 广门禁：8516 passed / 4 skipped / 2 deselected，448.93 秒。两个排除项均在干净 master 基线 `8823266e` 复现：

- `tracked_docs_allowlist`：既有 CLI memory 根报告的文档 allowlist 失败。
- `backfill_missing_api_key_secrets_from_env`：全 core 顺序中返回 0，单独运行通过；基线运行至 272 passed 后也出现同一失败。

上述是有明确范围及基线排除项的门禁结果，不是全仓库全绿。父代理另有 fresh Bun 384 passed / 0 failed（73 files，31.34 秒）及 `tsc` 通过；protocol 29 passed 且 `tsc` 通过；provider/tools/subagent Python 2164 passed；最近一次 Python focused suite 为 138 passed / 2 skipped。各结果对应各自快照，最终修复后的验收仍以正式记录为准。

09:10 的阶段快照历史上为 3/4：前三场景 assertions 通过，PDF/MP4 provider-request assertions 通过；第四场景原始 TUI capture 因 ANSI cursor movement 跳过空白 cells 而出现 false negative，真实 raw render 中完整 Final 可见。采证已在同一 deadline 内改为等待完整 ASCII 序列并归一化 ANSI/空白，缺词仍失败且有回归测试。此前 1/4 图像阶段因 `image_observations` 元数据缺失的记录也保留为历史；均由后续三轮完整结果取代。

最终真实 E2E 三个独立轮次均 4/4 GREEN，所有场景 assertions（含 PDF/MP4 完整免责声明）通过：`clipboard-e2e-20261012-092556` pytest 1 passed / 11.22 s，`clipboard-e2e-20261012-092620` 1 passed / 10.53 s；移除未接线 `sitecustomize` 后的 `clipboard-e2e-20261012-093143` pytest 1 passed / 11.19 s。每轮 13 个 synthetic provider requests；第三轮 clipboard restore/hash 成功，Bun/appserver/worker 三 PID exited、`reader_stopped=true`。第三轮 chip/final timings（ms）：files 176.23/3460，image 214.43/303.09，text 188.91/303，refs 188.2/318.32。100 ms 指标是最终 chip 完成时间，不是首次状态反馈；图像约 214 ms，不能声称所有场景均低于 100 ms。PNG fixture 为 32×24、RGB(23, 167, 91)。模型 fixture 配置 `gpt-5.6-luna`，回答由本地合成 provider 预设，不是 live 模型理解评估。

最终非 E2E fresh 回归：provider + broker units 15 passed / 2.86 s；all-feature suite 60 passed / 2 skipped / 5.90 s；Bun 384 passed / 31.76 s 且 `tsc` 通过；protocol/codegen 29 passed 且 `tsc` 通过。更广 8516 gate 的两项基线排除保持原记录，不代表整个仓库全绿。

**JSON-RPC 采证纠正：** 2026-10-12 曾尝试通过测试 `sitecustomize.py` tee 完整 JSON-RPC；生产 `stdioTransport.start` 固定设置 `PYTHONPATH=this.projectRoot()`，覆盖 harness 加入的测试目录，导致 `sitecustomize.py` 未被导入、前两轮 `evidence/jsonrpc` 目录为空。该次 wire-capture 尝试作废，不能声称存在完整 RPC tee；空目录不是证据。未发布的死钩子已删除，harness 已移除 `RXYCODE_CLIPBOARD_E2E_RPC_TRACE` 与空目录创建，生产传输未改；修正后 units 与第三轮 4/4 suite 均通过。现有证据是 appserver 持久 `task-events.json` 协议事件、provider trace 与 ConPTY terminal 观察，仍不等于完整 wire capture。此前两轮产品行为结果仍有效。

**产物状态：** 父代理确认三轮 evidence 位于 `primary artifacts/tui-clipboard-e2e-2026-10-12/round-1` 至 `round-3`，共 27 files / 478171 bytes，copy hash verified，无 CA keys/config/fixtures。实施 commit `89f7ff48dca1633dfcf902efd91a9d81a396d51e` 已 fast-forward 至干净的本地 master checkout `D:\agent-demo\RxyCode-masterverify` 和 primary `feat/phase-g-backend` checkout `D:\agent-demo\RxyCode\RxyCode1_1_0`，未 push；primary 原有 25 个 tracked 脏文件合并前后 SHA256 完全一致。三个外部目录与本 worktree 均完整未删；执行层拒绝了两次针对外部目录的递归 `Remove-Item` 和一次仅针对 junction 链接的删除。为避免 Git 递归清理误触 primary 依赖，未调用 `git worktree remove`。四处残留路径：`D:\tmp-cursor-probe\rxycode-clipboard-acceptance-20261011`、`D:\tmp-cursor-probe\rxycode-clipboard-snapshot-readonly`、`D:\tmp-cursor-probe\opencode-clipboard-ref-20261011`、`D:\agent-demo\RxyCode-clipboard-e2e`。未调用收费 API，未做 UI 像素级视觉审核；正式验收报告见 [`docs/modules/reports/TUI-CLIPBOARD-ATTACHMENTS-E2E-2026-10-11.md`](../modules/reports/TUI-CLIPBOARD-ATTACHMENTS-E2E-2026-10-11.md)。

产品版本仍为 1.4.2；本文件是 v1.4.3 开发期变更记录，不代表发版。两份跟踪文档另由父流程提交为本地 docs commit；research 仍被忽略、不提交。不预写未来 hash。不发版、不 push。
