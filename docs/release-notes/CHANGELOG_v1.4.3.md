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

## 遗留（本轮精准修复未覆盖，后续立项）

- `tasks.json` 单文件巨石（26MB+）应改 append-only 分段存储（JSONL + 独立元数据小文件）——根治病灶，属存储层重构。
- `AppServer.__init__` 冷启动同步全量 parse + 约 20 个 service eager 构造，可懒加载。
- 模型目录同 `(provider_model_id, base_url)` 条目在列表中重复显示的 merge 去重。

## CLI 内存治理记录（2026-10-11）

- 新增 [CLI 内存治理记录](../CLI-MEMORY-MANAGEMENT-2026-10-11.md)：TUI 1000 条 transcript native nodes 由 9354 降至 760；匹配的 100 MB Bash fixture（k=3）峰值 RSS 约低 79%，样本耗时未显示速度提升。
- 独立候选组合 gate 10292 passed、1 skipped、47 warnings（279.94 秒；core/tools/appserver/subagents/integration/contract/system cancellation/packaging）；shell+tools+cancellation 1045 passed，reader/consumer 18 passed，worker owner/parent gates 20/19 passed，Ruff 全绿。
- 内存变更于 2026-10-11 集成到 primary 工作树；primary fresh proof：appserver/subagents/capture-consumers-security/realAgent/cancel 711 passed、1 skipped（75.89 秒），TUI 354 passed、0 failed（70 files，28.52 秒），tsc、Ruff touched files 和 scoped diff check 通过。需重启 RxyCode 加载；不是发布，产品版本仍为 1.4.2。
- K3 基线 `53e5bae5` 未变，primary 与隔离树 normalized code 全部匹配；本次按用户授权仅提交本地 master，不推送、不发布，其他 WIP 与计划文档不纳入。结果不是全仓库/live 覆盖，内存限制与 fixture 边界见报告。
