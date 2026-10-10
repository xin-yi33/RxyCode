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

### 遗留（本轮精准修复未覆盖，后续立项）

- `tasks.json` 单文件巨石（26MB+）应改 append-only 分段存储（JSONL + 独立元数据小文件）——根治病灶，属存储层重构。
- `AppServer.__init__` 冷启动同步全量 parse + 约 20 个 service eager 构造，可懒加载。
- 模型目录同 `(provider_model_id, base_url)` 条目在列表中重复显示的 merge 去重。
