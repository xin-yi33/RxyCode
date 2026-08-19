# PHASE-G-BACKEND-GX · 增强卡后端拆分

> 后端执行者 · 只在 `feat/phase-g-backend` 上做这些卡
> 权威产品定义仍是 [`PHASE-G-DESKTOP.md`](../PHASE-G-DESKTOP.md) Part 3。
> **不要**把增强卡写回主链 B1–B18 / H1–H13 文档，避免再跟主链分支解冲突。
> **不要**为每张 GX 从 master 另开 `feat/gxN` 再和前后端分支互合并。

## 分支纪律

在 `feat/phase-g-backend` 一张一张做 GX*\-B。协议变更仍走变更单。合入 master 时只带 `docs/phase-g/backend/` + `appserver/` + `protocol/` + Python 测试。不要 merge `feat/phase-g-frontend`。

## 卡表

| 卡 | 本端 | 对端 |
|---|---|---|
| GX2-B | 本文件 | GX2-H |
| GX3-B | 本文件 | GX3-H |
| GX4-B | 本文件 | GX4-H |
| GX5-B | 本文件 | GX5-H |
| GX7-B | 本文件 | GX7-H |
| GX8-B | 本文件 | GX8-H |
| GX9-B | 本文件 | GX9-H |
| GX13-B | 本文件 | GX13-H |
| GX14-B | 本文件 | GX14-H |
| GX16-B | 本文件 | GX16-H |
| GX18-B | 本文件 | GX18-H |
| GX19-B | 本文件 | GX19-H |
| GX20-B | 本文件 | GX20-H |
| GX23-B | 本文件 | GX23-H |
| GX24-B | 本文件 | GX24-H |
| GX25-B | 本文件 | GX25-H |
| GX26-B | 本文件 | GX26-H |
| GX28-B | 本文件 | GX28-H |

## GX2-B · 审批卡片内嵌对话流 + 权限三档模式

**owner: backend（Composer 2.5）** · 分支 `feat/phase-g-backend`

**配对卡**：GX2-H（另一端施工文档） · **产品原文**：[`../PHASE-G-DESKTOP.md`](../PHASE-G-DESKTOP.md) 的 GX2

**本端必须实现**：
- 协议：`approval/mode_set`（UI 预设 → B7 策略）；`appserver/approval_router.py`；禁止建 handlers/
- M2：禁止 `appserver/handlers/`
- 禁碰 `core/agent_v2.py`、前端业务组件
- 只添加不改主链字段语义

**本端涉及文件**：
- `protocol/schema.json` + `protocol/*.py`（扩展：`approval/mode_set` 方法，new_method）
- `appserver/permission.py`（新增：权限模式会话状态 + approval request 路由：卡片/弹窗互斥 + request_id 幂等）  （M2：禁止新建 handlers/，用 `*_routes.py` / `*_service.py`）
- `appserver/approval_router.py`（新增：审批事件的通道路由与幂等处理——事件名以 B7/B12 实际为准，消费主链 B7 审批服务事件）
- `tests/test_permission_mode.py`、`tests/test_approval_router.py`（新增）

**本端协议要点**：`approval/mode_set`（UI 预设 → B7 策略）；`appserver/approval_router.py`；禁止建 handlers/

**本端验收**：
```powershell
# 本端：协议/appserver 定向测试（命令以卡内 pytest 为准，勿跑前端 npm）
python -m pytest tests/test_protocol -q
```
前端验收不在本卡。

**本端完成判据**：
- [x] 本端协议/服务落地（或探针路径 A 纯消费）
- [x] GXn-PROTO 变更单（若 new_method/event/field）
- [x] 定向 pytest 通过
- [x] 单 commit 到 `feat/phase-g-backend`（不要开 `feat/gxN`，不要跟前端分支互合并）

<details>
<summary>产品卡原文（验收细节以原文为准，本端只做本端条目）</summary>

## GX2 · 审批卡片内嵌对话流 + 权限三档模式

**借鉴来源**：TRAE 审批卡片（调研 §8.3-3/4）；Codex 权限三档模式（§2.3-1）；Qoder 命令审批（§9.3-4）。
**优先级/工时**：P0 / 3–4d / 依赖：B7 + H8 完成 / **owner: frontend 为主 + backend 协议扩展**
**背景**：主链 H8 的审批是模态弹窗（模态打断流）。Codex/TRAE/Qoder 三家共同证明：**审批=模式而非弹窗**——权限请求以卡片内嵌对话流（不断流），配合 Composer 下方常驻的三档权限模式切换（Ask / Auto-review / Full access）。

**涉及文件**：
- `frontend/desktop-app/src/features/approvals/ApprovalCard.tsx`（新增，流内审批卡片）
- `frontend/desktop-app/src/features/approvals/PermissionModeSwitcher.tsx`（新增，输入框旁三档切换）
- `frontend/desktop-app/src/features/approvals/approval.mode.ts`（新增：模式状态管理）
- `frontend/desktop-app/src/features/approvals/ApprovalCard.test.tsx`（新增）
- `protocol/schema.json` + `protocol/*.py`（扩展：`approval/mode_set` 方法，new_method）
- `appserver/handlers/permission.py`（新增：权限模式会话状态 + approval request 路由：卡片/弹窗互斥 + request_id 幂等）
- `appserver/approval_router.py`（新增：审批事件的通道路由与幂等处理——事件名以 B7/B12 实际为准，消费主链 B7 审批服务事件）
- `tests/test_permission_mode.py`、`tests/test_approval_router.py`（新增）

**规范限制**：
- **权限模型（单一规范，不新建平行状态）**：权限策略**沿用主链 B7 的五态模型**（`read_only` / `workspace_write` / `ask_for_each_risky_action` / `allow_scoped_actions` / `full_access`，`full_access` 默认不可选，重启只恢复明确持久化策略）。GX2 的三档是 **UI 预设**，映射到 B7 五态：`Ask`→`ask_for_each_risky_action`（默认）、`Auto`→`allow_scoped_actions`（LLM 代审语义，若 B7 无等价策略则映射回 `ask_for_each_risky_action` 并注明）、`Full`→`full_access`（沿用 B7 显式启用与默认不可选语义）；**不得新增第三套权限状态**。`approval/mode_set` 只写「UI 预设名 + 目标 B7 策略名」，实际生效策略始终来自 B7 服务
- 模式是**会话级**状态（存 appserver，非前端 localStorage）；切换走 `approval/mode_set` 协议
- **full_access 启用（探针决定，闭环要求）**：开工前先核对主链 B7 是否已有 `full_access` 启用方法/字段——**核对结论二选一**：①B7 已有 → 只复用（写出真实方法/字段/验收命令，UI 入口 + 设置页接线）；②B7 没有 → 拆 **GX2-PROTO** 子卡：`approval/full_access_enable` 的 request/response、权限主体（仅设置页已认证会话）、审计字段（actor/时间/来源）、启用生命周期（会话级，重启清除）、调用权限与失败错误码、验收命令全部冻结在协议变更单。`approval/mode_set` 对 `full` 的「未启用」错误码固定为 `full_access_not_enabled`。核对前不得同时写两种方案；结论写入 PR
- **审批幂等（防重复审批/竞态）**：审批事件名**以主链 B7/B12 实际事件为准**（事件命名空间 `event/agent_*`；探针确认后替换占位名 `approval/requested`）；事件带 `request_id`；卡片与模态弹窗**互斥展示**（同一 `request_id` 只在一个通道呈现，路由规则：模式=ask 且风险非高危 → 卡片；高危 → 弹窗）；响应（allow/deny/cancel）以 `request_id` 幂等，重复响应返回 `request_id already handled` 错误；两侧同时打开时状态同步由 appserver 单事件源保证
- 审批卡片**不替代**主链的模态弹窗——弹窗保留为"紧急/高危"动作路径（B7 的 `full_access` 默认不可选逻辑不变）；卡片是新增的低干扰路径
- 卡片动作只发 `allow` / `deny` / `cancel`，不修改后端 policy（与主链 H8 一致）
- 高危命令（rm/删除/写 .env 等，复用主链 B7 风险分级）无论模式如何都走弹窗

**开发步骤**：
1. 后端先行（协议）：`tests/test_permission_mode.py`（red）→ `protocol/` 新增 `approval/mode_set`（**请求/响应结构全文档唯一冻结**：request `{preset: "ask"|"auto"|"full"}`；response `{preset, effective_policy, writable_roots}`；不出现 `{mode}` 变体）→ `appserver/handlers/permission.py` 会话级预设状态（默认 `ask`，重启恢复 `ask`——不持久化高风险预设）
2. 前端：`ApprovalCard.test.tsx`（red）→ 组件（命令/路径/风险徽标/允许/拒绝/取消 + 后台运行标记，五态覆盖）
3. `PermissionModeSwitcher`（输入框旁下拉 + 当前模式徽标，参照 Claude 模式徽章体系 §3.4）
4. 接线：主链事件流（B7 approval 事件）同时投递到卡片渲染器和弹窗渲染器，按模式路由

**示例代码**（后端模式状态 + 协议 handler）：

```python
# appserver/handlers/permission.py —— UI 预设 → B7 策略映射（GX2 新增，不新建权限状态）
from typing import Literal

# UI 预设三档（§规范限制）——映射到主链 B7 五态策略，实际生效策略来自 B7 服务
UIPreset = Literal["ask", "auto", "full"]
# 预设 → B7 策略映射冻结；full 需 B7 显式启用（默认不可选，沿用 B7 语义）
PRESET_TO_B7: dict[UIPreset, str] = {
    "ask": "ask_for_each_risky_action",   # 默认
    "auto": "allow_scoped_actions",       # 若 B7 无等价策略则映射回 ask_for_each_risky_action
    "full": "full_access",                # 显式启用后才可选
}

# approval/mode_set request: {preset: UIPreset}
# response: {"preset": ..., "effective_policy": <B7 策略名>, "writable_roots": [...]}
# 校验：full 未启用（B7 默认不可选）时拒绝，错误码走主链审批审计
```

**验收命令**：
```powershell
python -m pytest tests/test_permission_mode tests/test_approval_router -q
cd frontend\desktop-app
npm run typecheck && npm run test -- --run
# 契约：模式切换往返、重启回默认 ask、full_access 启用后可选/未启用拒绝/重启清除、
#       审批卡片五态、request_id 幂等（重复响应报错）、卡片/弹窗互斥路由、事件名探针结论
# baseline: 按 §1-12 批次出口执行一次（卡级不跑，防双人覆盖）
```

**完成判据**：
- [ ] `approval/mode_set` 协议落地（含 schema 冻结 + contract test）
- [ ] 三档切换生效；full_access 未启用时拒绝、启用后可选、重启后清除
- [ ] 审批卡片在对话流内渲染（非模态），动作只发 allow/deny/cancel
- [ ] request_id 幂等（重复响应返回已处理错误）；卡片/弹窗互斥路由正确
- [ ] 高危动作仍走主链模态弹窗（双路径并存）
- [ ] 五态测试通过；单 commit（批次 baseline 按 §1-12/§2 出口执行）

**Commit**：
```
feat(desktop): GX2 inline approval cards + permission presets

TRAE/Codex-inspired inline approval cards in the thread stream and
UI presets (ask/auto/full) mapped onto the B7 policy model via new
approval/mode_set protocol method. Modal path retained for high-risk.
```

---


</details>


## GX3-B · diff 行内注释闭环 + Review scope 五档

**owner: backend（Composer 2.5）** · 分支 `feat/phase-g-backend`

**配对卡**：GX3-H（另一端施工文档） · **产品原文**：[`../PHASE-G-DESKTOP.md`](../PHASE-G-DESKTOP.md) 的 GX3

**本端必须实现**：
- 协议：`review/comment/add`、`review/comment/resolve`；行级 comment 绑定 B8 review/finding
- M2：禁止 `appserver/handlers/`
- 禁碰 `core/agent_v2.py`、前端业务组件
- 只添加不改主链字段语义

**本端涉及文件**：
- `protocol/schema.json` + `protocol/*.py`（扩展：`review/comment/add`、`review/comment/resolve`，new_method）
- `appserver/review_comments.py`（新增：评论持久化到 review 记录）  （M2：禁止新建 handlers/，用 `*_routes.py` / `*_service.py`）
- `tests/test_review_comments.py`（新增）

**本端协议要点**：`review/comment/add`、`review/comment/resolve`；行级 comment 绑定 B8 review/finding

**本端验收**：
```powershell
# 本端：协议/appserver 定向测试（命令以卡内 pytest 为准，勿跑前端 npm）
python -m pytest tests/test_protocol -q
```
前端验收不在本卡。

**本端完成判据**：
- [x] 本端协议/服务落地（或探针路径 A 纯消费）
- [x] GXn-PROTO 变更单（若 new_method/event/field）
- [x] 定向 pytest 通过
- [x] 单 commit 到 `feat/phase-g-backend`（不要开 `feat/gxN`，不要跟前端分支互合并）

<details>
<summary>产品卡原文（验收细节以原文为准，本端只做本端条目）</summary>

## GX3 · diff 行内注释闭环 + Review scope 五档

**借鉴来源**：Codex diff 行内注释闭环与五档 scope（调研 §2.3-5/6）；Claude 行注释批量提交（§3.3-7）；Copilot Range-based Feedback（§4.3-9）。
**优先级/工时**：P0 / 3–4d / 依赖：B8 + H9 完成 / **owner: frontend 为主 + backend 协议扩展**
**强 Protocol probe（§1-16 固定字段）**：实现前必须确认 B8 checkpoint restore 的真实方法名与字段（`name`/`user_prompt`/`seq`/对话截断相关字段是否存在于 B8 schema）——确认前整卡状态 `BLOCKED_PREREQUISITE`；示例中的 `CheckpointService.*`/`ThreadService.truncate_projection_at` 为占位 API，以探针结论替换；缺失能力拆协议卡（如 `GX4-PROTO`）
**背景**：主链 H9 的 diff review 只能看和接受/拒绝，无法"以行为单位反馈"。Codex 的闭环是各家最强：悬停行尾→写评论→回聊天下达→agent 修复→resolve。五档 scope（Unstaged/Staged/Commit/Branch/Last turn）让"审什么"由用户定义，Last turn 完美映射我们的 Thread 回合模型。

**涉及文件**：
- `frontend/desktop-app/src/features/review/InlineComment.tsx`（新增：行内评论气泡）
- `frontend/desktop-app/src/features/review/ReviewScopeSelector.tsx`（新增：五档下拉）
- `frontend/desktop-app/src/features/review/review.comments.ts`（新增：评论状态 store）
- `frontend/desktop-app/src/features/review/InlineComment.test.tsx`（新增）
- `protocol/schema.json` + `protocol/*.py`（扩展：`review/comment/add`、`review/comment/resolve`，new_method）
- `appserver/handlers/review_comments.py`（新增：评论持久化到 review 记录）
- `tests/test_review_comments.py`（新增）

**规范限制**：
- 五档 scope 冻结：`unstaged` / `staged` / `commit` / `branch` / `last_turn`（last_turn = 最近一个 agent 回合的变更）
- **scope 与主链 B8 的对照纪律**：实现前先逐项核对主链 B8 的 `review/start` paths scope 实际支持项——已存在的直接复用；不存在的（如 `last_turn` 的 turn↔diff 关联）**必须走协议变更单**：若缺的是关联字段 → new_optional_field；若缺的是 scope 枚举值/查询语义 → 冻结新增 scope 值的枚举定义、排序规则、空 diff 行为与验收样例（new 枚举值变更，不能只加字段了事）。对照结论写进 PR 描述，未核对前卡状态 `BLOCKED_PREREQUISITE`
- 评论**只读消费** B8 的 diff hash 定位（`file:line` 锚点 + hunk hash），评论本身不进入 git，持久化在 appserver review 记录
- **评论状态机冻结**：`open` → `resolved`（人工 resolve）；hunk 因后续 diff 失效时 `open` → `stale`；`stale` 可 resolve（标记已确认），不可 reopen；`stale` 不删除
- 回聊天下达：评论提交后生成一条**可编辑的**用户消息草稿（"请处理以下内联评论：…"），用户确认后发送——不自动发送
- 后端复用 B8 的 review/read 语义；`review/comment/*` 为 B8 协议的追加方法，不改 B8 字段

**开发步骤**：
1. 后端先行：`tests/test_review_comments.py`（red）→ `protocol/` 新增 `review/comment/add`（request: `{review_id, file, line, hunk_hash, body}`）、`review/comment/resolve`（`{comment_id}`）→ `appserver/handlers/review_comments.py`
2. 前端：`InlineComment.test.tsx`（red）→ hover 行尾按钮（+）→ 评论气泡（textarea + 提交/取消 + 折叠）→ 评论列表（open/stale 徽标 + resolve 按钮）
3. `ReviewScopeSelector`：五档下拉，默认 `last_turn`；切换后 diff 面板按 scope 重投影（复用 B8 review/start 的 paths scope）
4. 下达闭环：评论提交 → 生成消息草稿 → 用户发送 → agent 修复（新 diff）→ 原评论 hunk 失效标记 stale → resolve 入口

**示例代码**（评论组件核心交互）：

```tsx
// InlineComment.tsx —— 行内评论（GX3 核心交互：hover → 评论 → resolve）
export function InlineComment({ file, line, hunkHash }: CommentAnchorProps) {
  const [open, setOpen] = useState(false);
  const [body, setBody] = useState('');
  const comments = useCommentsForAnchor(file, line, hunkHash); // 只读消费 B8 diff hash

  return (
    <div className="inline-comment" data-line={line}>
      <button className="anchor-btn" onClick={() => setOpen(true)} title="Add comment">+</button>
      {comments.map((c) => (
        <div key={c.id} className={`comment ${c.status}`}>
          <p>{c.body}</p>
          {c.status === 'stale' && <span className="badge">stale</span>}
          {c.status === 'open' && (
            <button onClick={() => dispatch(resolveComment(c.id))}>Resolve</button>
          )}
        </div>
      ))}
      {open && (
        <div className="comment-editor">
          <textarea value={body} onChange={(e) => setBody(e.target.value)} />
          <button onClick={() => { dispatch(addComment({ file, line, hunkHash, body })); setOpen(false); }}>
            Comment
          </button>
        </div>
      )}
    </div>
  );
}
```

**验收命令**：
```powershell
python -m pytest tests/test_review_comments -q
python -m pytest tests/test_review -q   # 主链 B8 回归门禁（GX3 复用 B8 能力）
cd frontend\desktop-app
npm run typecheck && npm run test -- --run
# 契约：五档 scope 投影、评论 add/resolve、hunk 失效 stale 标记、下达草稿生成
# baseline: 按 §1-12 批次出口执行一次（卡级不跑，防双人覆盖）
```

**完成判据**：
- [ ] `review/comment/add` / `review/comment/resolve` 协议落地（contract test 通过）
- [ ] 五档 scope 按探针路径执行：B8 已有 scope 直接消费；缺失的 scope 走枚举扩展子卡（GX3-PROTO）
- [ ] hover 行尾按钮 → 评论 → 下达草稿 → 修复 → stale → resolve 全闭环可走通
- [ ] 评论不进 git、不改变 B8 字段语义
- [ ] 五态测试通过；单 commit（批次 baseline 按 §1-12/§2 出口执行）

**Commit**：
```
feat(desktop): GX3 inline diff comments with five-tier review scope

Codex-inspired comment loop (hover -> comment -> draft message -> fix ->
resolve) and review scope selector including last_turn. Comments persist
in appserver review records; git untouched.
```

---


</details>


## GX4-B · Checkpoint 回滚 UI（revert 挂消息 / 命名快照 / 双向导航）

**owner: backend（Composer 2.5）** · 分支 `feat/phase-g-backend`

**配对卡**：GX4-H（另一端施工文档） · **产品原文**：[`../PHASE-G-DESKTOP.md`](../PHASE-G-DESKTOP.md) 的 GX4

**本端必须实现**：
- 协议：`checkpoint/snapshot/create`、`checkpoint/rewind`（三步编排）；复用 B8 checkpoint
- M2：禁止 `appserver/handlers/`
- 禁碰 `core/agent_v2.py`、前端业务组件
- 只添加不改主链字段语义

**本端涉及文件**：
- `protocol/schema.json` + `protocol/*.py`（扩展：`checkpoint/snapshot/create`、`checkpoint/rewind`，new_method）
- `appserver/checkpoint_rewind.py`（新增：rewind 编排 = checkpoint restore + 对话回填）  （M2：禁止新建 handlers/，用 `*_routes.py` / `*_service.py`）
- `tests/test_checkpoint_rewind.py`（新增）

**本端协议要点**：`checkpoint/snapshot/create`、`checkpoint/rewind`（三步编排）；复用 B8 checkpoint

**本端验收**：
```powershell
# 本端：协议/appserver 定向测试（命令以卡内 pytest 为准，勿跑前端 npm）
python -m pytest tests/test_protocol -q
```
前端验收不在本卡。

**本端完成判据**：
- [x] 本端协议/服务落地（或探针路径 A 纯消费）
- [x] GXn-PROTO 变更单（若 new_method/event/field）
- [x] 定向 pytest 通过
- [x] 单 commit 到 `feat/phase-g-backend`（不要开 `feat/gxN`，不要跟前端分支互合并）

<details>
<summary>产品卡原文（验收细节以原文为准，本端只做本端条目）</summary>

## GX4 · Checkpoint 回滚 UI（revert 挂消息 / 命名快照 / 双向导航）

**借鉴来源**：Devin Desktop 检查点与回滚（调研 §6.3-4）；Replit Checkpoints 双向导航（§10.3-7）；Claude rewind 菜单（§3.3-5/6）；Copilot Restore/Redo（§4.3-7）。
**优先级/工时**：P0 / 3–4d / 依赖：B8 + H9 完成 / **owner: frontend 为主 + backend 扩展**
**背景**：主链 B8 已有 checkpoint（创建/列出/读取/恢复，checkpoint restore 后 diff hash 变化），但 UI 上没有回滚入口——用户找不到"怎么退回去"。四家共识：**回滚入口必须挂在每条消息上（hover revert 箭头）**，配命名快照与不可逆警告，恢复时对话上下文一并回填。

**涉及文件**：
- `frontend/desktop-app/src/features/checkpoints/MessageRevertButton.tsx`（新增：消息 hover revert 箭头）
- `frontend/desktop-app/src/features/checkpoints/CheckpointTimeline.tsx`（新增：检查点时间轴）
- `frontend/desktop-app/src/features/checkpoints/NamedSnapshotDialog.tsx`（新增：命名快照）
- `frontend/desktop-app/src/features/checkpoints/CheckpointTimeline.test.tsx`（新增）
- `protocol/schema.json` + `protocol/*.py`（扩展：`checkpoint/snapshot/create`、`checkpoint/rewind`，new_method）
- `appserver/handlers/checkpoint_rewind.py`（新增：rewind 编排 = checkpoint restore + 对话回填）
- `tests/test_checkpoint_rewind.py`（新增）

**规范限制**：
- **rewind 语义冻结（状态模型一致）**：`checkpoint/rewind` = ①创建新的恢复点（当前状态快照，避免不可逆）②代码恢复到目标 checkpoint ③对话读取面截断到目标点 ④目标 checkpoint 的用户消息回填输入框（可重发）。**历史 checkpoint 全部保留**（时间轴可前滚——"双向导航"指恢复点在时间轴上的双向选择，不是删除历史）；命名快照与自动 checkpoint 同存储（`~/.rxycode/checkpoints/`，运行时数据目录规则见 §1-18）
- **回滚确认**：rewind 前弹确认（含影响文件数/对话条数/可前滚提示）；确认参数 `confirm: true` 必须由用户 UI 动作显式携带
- 命名快照数据结构冻结（appserver 持久化，复用 B8 checkpoint 表追加 `name` 可空字段——协议 new_optional_field）：`{checkpoint_id, seq, name?, file_count, diff_hash, user_prompt, created_at}`
- **回滚后生成新 checkpoint**（记录"回滚动作"本身，保持版本链连续）；前滚 = 选择时间轴后续的 checkpoint 执行同一 rewind 流程
- 只读消费主链 B8 的 checkpoint 数据模型（代码恢复语义复用 B8 `checkpoint restore`）；本卡新增的是「命名快照 + 对话截断投影 + 消息回填」三个能力。**`checkpoint/snapshot/create` 命名快照探针**：先核对 B8 既有 checkpoint 创建方法——已有创建能力且仅需命名参数 → 复用 + new_optional_field（`name`）；语义不同（如手动命名快照与自动打点分离）才新增 `checkpoint/snapshot/create`（new_method）；探针结论写入 PR
- 每 prompt 自动打点沿用主链 B8（本卡不改变打点时机）
- 时间轴默认折叠，hover 展开；30 天清理沿用主链

**开发步骤**（先探针，A/B 路径）：
1. **Protocol probe**（§1-16 固定字段）：核对 B8 checkpoint 创建/恢复的真实方法名与字段（name/user_prompt/seq/对话截断相关字段）——**PASS 前本卡 BLOCKED_PREREQUISITE，不进入实现**
2. 路径 A（B8 已有）：仅实现 UI/投影（revert 箭头/时间轴/命名快照 UI 层），后端零新增
3. 路径 B（缺失）：登记 GX4-PROTO（§2）→ `checkpoint/snapshot/create`（`{name}`）、`checkpoint/rewind`（`{checkpoint_id, confirm: true}`）协议变更单 → `appserver/handlers/checkpoint_rewind.py`（调 B8 服务 + 对话回填）
2. 前端：`MessageRevertButton`（消息 hover 出现 ↶ 箭头 → rewind 确认对话框 → 执行后对话回填）
3. `CheckpointTimeline`（消息流左侧时间轴：自动点 + 命名快照图标，点击跳转预览）→ 五态
4. 双向导航：回滚后时间轴保留后续点（可前滚，Replit 语义）

**示例代码**（rewind 后端编排）：

```python
# appserver/handlers/checkpoint_rewind.py —— rewind 编排（GX4 新增）
# 复用点标注：主链 B8 checkpoint restore（方法名/字段以 B8 schema 实际为准，缺失则 BLOCKED）
from appserver.handlers.checkpoints import CheckpointService  # 主链 B8，只读复用


async def handle_checkpoint_rewind(checkpoint_id: str, confirm: bool) -> dict:
    """rewind = 恢复前快照 + 代码恢复 + 对话截断 + 消息回填（保持版本链连续）。"""
    if not confirm:
        raise ProtocolError("rewind requires explicit confirm=true")
    target = await CheckpointService.get(checkpoint_id)
    # 0) 恢复前快照：把当前状态打成新 checkpoint（版本链连续，前滚入口保留）
    restore_point = await CheckpointService.snapshot(reason="pre-rewind")
    # 1) 代码恢复（B8 既有语义，checkpoint restore 后新 diff hash）
    await CheckpointService.restore(checkpoint_id)
    # 2) 对话截断：该 checkpoint 之后的 user/assistant 消息从会话读取面隐藏（投影，不删除）
    truncated = await ThreadService.truncate_projection_at(checkpoint_id)
    # 3) 回填：checkpoint 对应的用户消息原文回填输入框（前端消费事件）
    return {"restore_point": restore_point.id, "restored_files": target.file_count,
            "truncated_messages": truncated, "refill_prompt": target.user_prompt}
```

**验收命令**：
```powershell
python -m pytest tests/test_checkpoint_rewind -q
python -m pytest tests/test_review -q   # 主链 B8 回归门禁（GX4 复用 B8 checkpoint）
cd frontend\desktop-app
npm run typecheck && npm run test -- --run
# 契约：rewind 三步编排、确认必需、回滚后新 diff hash（沿用 B8 断言）、不可逆警告、失败恢复/幂等
# baseline: 按 §1-12 批次出口执行一次（卡级不跑，防双人覆盖）
```

**完成判据**：
- [ ] 按探针路径执行：B8 复用 + new_optional_field，或 GX4-PROTO 新增 `checkpoint/rewind` / `checkpoint/snapshot/create`（协议变更单）
- [ ] revert 箭头挂在消息 hover 上；确认框含影响范围
- [ ] rewind 后代码恢复 + 对话截断 + 原消息回填输入框
- [ ] 命名快照可创建/列示；时间轴双向导航
- [ ] 五态测试通过；单 commit（批次 baseline 按 §1-12/§2 出口执行）

**Commit**：
```
feat(desktop): GX4 checkpoint rewind UI with named snapshots

Devin/Replit/Claude-inspired: revert arrow on message hover, rewind =
code restore + conversation truncation + prompt refill via single
checkpoint/rewind protocol method. Requires explicit confirm.
```

---


</details>


## GX5-B · 消息排队/打断（Send 三态下拉）

**owner: backend（Composer 2.5）** · 分支 `feat/phase-g-backend`

**配对卡**：GX5-H（另一端施工文档） · **产品原文**：[`../PHASE-G-DESKTOP.md`](../PHASE-G-DESKTOP.md) 的 GX5

**本端必须实现**：
- 协议：核对 B5 `turn/steer` / interrupt；仅当缺失时拆 GX5-PROTO，默认纯消费
- M2：禁止 `appserver/handlers/`
- 禁碰 `core/agent_v2.py`、前端业务组件
- 只添加不改主链字段语义

**本端涉及文件**：
- 见原文涉及文件中的本端路径

**本端协议要点**：核对 B5 `turn/steer` / interrupt；仅当缺失时拆 GX5-PROTO，默认纯消费

**本端验收**：
```powershell
# 本端：协议/appserver 定向测试（命令以卡内 pytest 为准，勿跑前端 npm）
python -m pytest tests/test_protocol -q
```
前端验收不在本卡。

**本端完成判据**：
- [x] 本端协议/服务落地（或探针路径 A 纯消费）
- [x] GXn-PROTO 变更单（若 new_method/event/field）
- [x] 定向 pytest 通过
- [x] 单 commit 到 `feat/phase-g-backend`（不要开 `feat/gxN`，不要跟前端分支互合并）

<details>
<summary>产品卡原文（验收细节以原文为准，本端只做本端条目）</summary>

## GX5 · 消息排队/打断（Send 三态下拉）

**借鉴来源**：Copilot Queue/Steer/Stop-and-send（调研 §4.3-1）；Cursor Alt+Enter 排队 / Cmd+Enter 打断（§5.3-9）；Codex Tab 排队 / Enter 注入（§2.3-12）。
**优先级/工时**：P0 / 2–3d / 依赖：H5 完成 / **owner: frontend**
**背景**：主链 H5 的对话输入在 agent 运行时是禁用的（用户只能等或停）。Copilot 的"运行中 Send 变下拉"是三家中语义最清晰的运行中干预：Add to Queue（完成后发）/ Steer with Message（当前工具执行完即停，处理新消息）/ Stop and Send。pending 消息可拖拽重排。

**涉及文件**（全部新增）：
- `frontend/desktop-app/src/features/composer/SendDropdown.tsx`（新增：Send 三态下拉）
- `frontend/desktop-app/src/features/composer/pending.queue.ts`（新增：pending 队列 store，可拖拽重排）
- `frontend/desktop-app/src/features/composer/Composer.test.tsx`（新增：三态 + 重排测试）
- `frontend/desktop-app/src/features/composer/steer.message.ts`（新增：steer 协议客户端封装）

**规范限制**：
- 三态语义冻结：`queue`（agent 完成后按序发送）/ `steer`（当前工具调用完成即中断处理新消息）/ `stop_and_send`（停止当前回合并发送）；默认 `queue`；**空闲时 Send = 立即发送**（`send` 即 queue 的立即发送语义，空闲态下拉不出现）
- **steer/stop 的后端语义（先核对，缺失则 BLOCKED 登记制）**：主链 B5 的必须实现含 "Turn start/steer/interruption/retry"（G-B B5 卡）；实现本卡时先核对 `turn/steer`、`turn/interrupt` 方法与中断语义在 schema 中真实存在——存在则直接消费（路径 A）；**不存在（路径 B）→ 本卡报告 `BLOCKED_PREREQUISITE` 并走 §1-17 的 GX*-PROTO 登记流程**（新增子卡须正式列入卡表/依赖图/owner/验收命令/协议变更单，不得在本卡内临时新增协议）。**排期**：先完成协议探针——路径 A 纯前端执行；路径 B 待 GX5-PROTO 登记完成后另行排期。本卡**不做「协议零变更」承诺**（完成判据以实际核对结论为准）
- pending 队列是**前端 UI 状态**（不新增协议方法；发送仍走主链 `agent/invoke`），最多 10 条（借鉴 v0 排队上限）
- 拖拽重排仅限 pending 队列内部；已发送消息不可重排
- 键盘：Alt+Enter = 排队、Ctrl+Enter = 打断并发送（默认，可在设置改）
- 不修改主链 H5 的输入框组件文件——新增 Composer 包装组件（`ComposerGX.tsx`）包裹原输入框

**开发步骤**：
1. `Composer.test.tsx`（red）：三态下拉渲染、pending 队列 push/重排/删除、快捷键映射
2. `pending.queue.ts`（队列状态 + 重排逻辑）
3. `SendDropdown`（agent 运行时 Send 变下拉，非运行时保持普通 Send；带 pending 计数徽标）
4. `ComposerGX` 包装接入主链输入框（props 透传，不碰原组件）
5. 五态：空闲/运行中/队列非空/窄窗（下拉变图标）/深色

**示例代码**（三态下拉核心）：

```tsx
// SendDropdown.tsx —— 运行中 Send 变三态下拉（GX5）
type SendIntent = 'queue' | 'steer' | 'stop_and_send';

export function SendDropdown({ running, onSend }: { running: boolean; onSend: (i: SendIntent) => void }) {
  // 空闲时：Send = 立即发送（queue 的立即发送语义，不出现下拉）
  if (!running) return <button className="btn-primary" onClick={() => onSend('queue')}>Send</button>;
  return (
    <div className="send-menu">
      <button onClick={() => onSend('steer')}>Steer with Message</button>
      <button onClick={() => onSend('stop_and_send')}>Stop and Send</button>
      <button onClick={() => onSend('queue')}>Add to Queue</button>
    </div>
  );
}
// 键盘：Alt+Enter -> queue；Ctrl+Enter -> stop_and_send（挂 ComposerGX keydown）
```

**验收命令**：
```powershell
cd frontend\desktop-app
npm run typecheck && npm run test -- --run
# 契约：三态语义、pending 重排/删除/上限 10、快捷键、运行/空闲两态渲染
# baseline: 按 §1-12 批次出口执行一次（卡级不跑，防双人覆盖）
```

**完成判据**：
- [ ] 运行中 Send 变三态下拉；空闲保持普通 Send
- [ ] pending 队列可 push/重排/删除，上限 10 条
- [ ] Alt+Enter / Ctrl+Enter 快捷键生效
- [ ] steer/stop 的协议核对结论写入 PR（B5 已有 → 直接消费；缺失 → GX5-B 协议变更单落地）
- [ ] 五态测试通过；单 commit（批次 baseline 按 §1-12/§2 出口执行）

**Commit**：
```
feat(desktop): GX5 send three-state dropdown (queue/steer/stop-and-send)

Copilot/Cursor-inspired mid-run intervention. Pending queue is pure
frontend state (max 10, draggable); steer/stop semantics per B5
turn-steering protocol check (GX5-B protocol change if absent).
```

---


</details>


## GX7-B · 上下文用量/成本指示器 + statusline

**owner: backend（Composer 2.5）** · 分支 `feat/phase-g-backend`

**配对卡**：GX7-H（另一端施工文档） · **产品原文**：[`../PHASE-G-DESKTOP.md`](../PHASE-G-DESKTOP.md) 的 GX7

**本端必须实现**：
- 协议：`event/agent_usage`（new_event）；消费 Phase 3 usage，禁止硬编码 8192
- M2：禁止 `appserver/handlers/`
- 禁碰 `core/agent_v2.py`、前端业务组件
- 只添加不改主链字段语义

**本端涉及文件**：
- `protocol/schema.json` + `protocol/*.py`（扩展：`event/agent_usage` 事件，new_event，符合原版 `event/agent_*` 命名空间；复用 B10 模型摘要）
- `appserver/usage_tracker.py`（新增：会话级 token/成本聚合，消费 Phase 3 摘要；产出 `event/agent_usage`）
- `tests/test_usage_tracker.py`（新增）

**本端协议要点**：`event/agent_usage`（new_event）；消费 Phase 3 usage，禁止硬编码 8192

**本端验收**：
```powershell
# 本端：协议/appserver 定向测试（命令以卡内 pytest 为准，勿跑前端 npm）
python -m pytest tests/test_protocol -q
```
前端验收不在本卡。

**本端完成判据**：
- [x] 本端协议/服务落地（或探针路径 A 纯消费）
- [x] GXn-PROTO 变更单（若 new_method/event/field）
- [x] 定向 pytest 通过
- [x] 单 commit 到 `feat/phase-g-backend`（不要开 `feat/gxN`，不要跟前端分支互合并）

<details>
<summary>产品卡原文（验收细节以原文为准，本端只做本端条目）</summary>

## GX7 · 上下文用量/成本指示器 + statusline

**借鉴来源**：Codex statusline 与 /usage（调研 §2.3-14/15）；Claude Usage ring（§3.3-12）；Cursor 用量汇总超 50% 提醒（§5.3-12）。
**优先级/工时**：P0 / 2–3d / 依赖：B10 + H11 完成 / **owner: frontend + backend 协议扩展**
**背景**：主链 B10 已有模型摘要（limit_source/fallback）但 UI 不展示消耗。Codex 的 footer statusline（model/tokens/context left/git/task progress）与 Claude 的 usage ring 是"隐性消耗可视化"标准件；Cursor 的超 50% 配额提醒是防爆细节。

**涉及文件**：
- `frontend/desktop-app/src/components/statusbar/Statusline.tsx`（新增：底部状态条，可配置项）
- `frontend/desktop-app/src/components/statusbar/UsageRing.tsx`（新增：用量环）
- `frontend/desktop-app/src/components/statusbar/statusline.config.ts`（新增：可配置项/顺序）
- `frontend/desktop-app/src/components/statusbar/Statusline.test.tsx`（新增）
- `protocol/schema.json` + `protocol/*.py`（扩展：`event/agent_usage` 事件，new_event，符合原版 `event/agent_*` 命名空间；复用 B10 模型摘要）
- `appserver/usage_tracker.py`（新增：会话级 token/成本聚合，消费 Phase 3 摘要；产出 `event/agent_usage`）
- `tests/test_usage_tracker.py`（新增）

**规范限制**：
- statusline 项冻结并可配置（顺序可拖拽/开关）：`model` / `context`（用量环）/ `tokens` / `git_branch` / `task_progress` / `cost`；默认前三项
- 用量数据**唯一来源**是 appserver（`event/agent_usage` 事件），前端不自行计算成本（Phase 3 摘要唯一真相，与主链 B10/H11 一致）
- **成本字段降级规则**：实现前核对主链 schema 的 usage/limit 字段实际存在哪些——**只有 Phase 3 摘要确实提供定价字段时才显示 `cost` 项**；若 schema 无定价字段，`cost` 项隐藏并在 PR 注明（`PENDING_PRICING`），只展示 token/context 用量；不得虚构定价
- 超 50% 上下文：用量环变琥珀色 + 会话内一次性提醒（不打断流）
- 会话切换/恢复后用量从 appserver 重取（不本地缓存跨会话）
- 事件去重：`event/agent_usage` 事件带 `seq`（单调递增），前端以 seq 去重；推送频率：每工具调用 + 每 30s 心跳
- 成本显示单位：本次会话累计（币种以 Phase 3 摘要定价字段为准）

**开发步骤**：
1. 后端先行：`tests/test_usage_tracker.py`（red）→ `appserver/usage_tracker.py`（从 Phase 3 resolver 的 usage accumulator 聚合）→ `event/agent_usage` 事件（new_event，推送频率：每工具调用 + 每 30s 心跳）
2. 前端：`Statusline.test.tsx`（red）→ 组件（默认项渲染/配置开关/顺序）→ `UsageRing`（SVG 环：上下文用量占比 + 阈值变色）→ 50% 提醒
3. 接线：消费 `event/agent_usage` 事件更新状态条；会话切换重取
4. 五态：无会话（隐藏）/加载/错误/窄窗（只显 model+ring）/深色

**示例代码**（用量环组件）：

```tsx
// UsageRing.tsx —— 上下文用量环（GX7，数据来自 event/agent_usage 事件，不自行计算）
export function UsageRing({ usedPct }: { usedPct: number }) {
  const R = 8, C = 2 * Math.PI * R;
  // 阈值冻结：50% 琥珀、90% 红（借鉴 Cursor 超 50% 提醒）；clamp 防非法值
  const pct = Math.min(100, Math.max(0, usedPct));
  const color = pct > 90 ? 'var(--error)' : pct > 50 ? 'var(--warn)' : 'var(--ok)';
  return (
    <svg width="20" height="20" viewBox="0 0 20 20" aria-label={`context ${pct}% used`}>
      <circle cx="10" cy="10" r={R} fill="none" stroke="var(--border)" strokeWidth="3" />
      <circle cx="10" cy="10" r={R} fill="none" stroke={color} strokeWidth="3"
              strokeDasharray={`${C * pct / 100} ${C}`} transform="rotate(-90 10 10)" />
    </svg>
  );
}
```

**验收命令**：
```powershell
python -m pytest tests/test_usage_tracker -q
python -m pytest tests/test_settings -q   # 主链 B10 回归门禁（GX7 消费 Phase 3 摘要）
cd frontend\desktop-app
npm run typecheck && npm run test -- --run
# 契约：usage 事件推送频率、50/90 阈值变色、statusline 配置顺序、会话切换重取
# baseline: 按 §1-12 批次出口执行一次（卡级不跑，防双人覆盖）
```

**完成判据**：
- [ ] `event/agent_usage` 事件落地（每工具调用 + 30s 心跳，符合 event/agent_* 命名空间）
- [ ] statusline 默认三项 + 可配置排序/开关
- [ ] 用量环 50%/90% 阈值变色；50% 提醒一次
- [ ] 前端零成本计算（数据全来自 appserver）
- [ ] 五态测试通过；单 commit（批次 baseline 按 §1-12/§2 出口执行）

**Commit**：
```
feat(desktop): GX7 usage ring + configurable statusline

Codex/Claude/Cursor-inspired. event/agent_usage from appserver (single
source of truth, Phase 3 summaries); frontend never computes cost.
```

---


</details>


## GX8-B · 会话管理四件套 + 消息级 fork

**owner: backend（Composer 2.5）** · 分支 `feat/phase-g-backend`

**配对卡**：GX8-H（另一端施工文档） · **产品原文**：[`../PHASE-G-DESKTOP.md`](../PHASE-G-DESKTOP.md) 的 GX8

**本端必须实现**：
- 协议：`thread/fork`（若 B5 已有则路径 A 纯消费）；索引/搜索排除纪律
- M2：禁止 `appserver/handlers/`
- 禁碰 `core/agent_v2.py`、前端业务组件
- 只添加不改主链字段语义

**本端涉及文件**：
- `protocol/schema.json` + `protocol/*.py`（扩展：`thread/fork`，new_method；`thread/pin`、`thread/archive` 为 B5 既有方法的追加字段语义或 new_optional_field）
- `appserver/thread_fork.py`（新增）  （M2：禁止新建 handlers/，用 `*_routes.py` / `*_service.py`）
- `tests/test_thread_fork.py`（新增）

**本端协议要点**：`thread/fork`（若 B5 已有则路径 A 纯消费）；索引/搜索排除纪律

**本端验收**：
```powershell
# 本端：协议/appserver 定向测试（命令以卡内 pytest 为准，勿跑前端 npm）
python -m pytest tests/test_protocol -q
```
前端验收不在本卡。

**本端完成判据**：
- [x] 本端协议/服务落地（或探针路径 A 纯消费）
- [x] GXn-PROTO 变更单（若 new_method/event/field）
- [x] 定向 pytest 通过
- [x] 单 commit 到 `feat/phase-g-backend`（不要开 `feat/gxN`，不要跟前端分支互合并）

<details>
<summary>产品卡原文（验收细节以原文为准，本端只做本端条目）</summary>

## GX8 · 会话管理四件套 + 消息级 fork

**借鉴来源**：Codex 会话管理与消息级 fork（调研 §2.3-9/10）；Claude 会话过滤分组（§3.3-14）。
**优先级/工时**：P0 / 3–4d / 依赖：B5 + H5 完成 / **owner: frontend + backend 协议扩展**
**背景**：主链 H5 会话中心只有列表/新建/恢复。Codex 四件套（重命名/钉选/归档/搜索）+ 消息级 fork（编辑上一条消息从该点分叉新会话）是低成本高感知价值的会话能力全集，也是多任务用户的核心诉求。

**涉及文件**：
- `frontend/desktop-app/src/features/sessions/SessionMenu.tsx`（新增：右键/三点菜单：Rename/Pin/Archive/Search）
- `frontend/desktop-app/src/features/sessions/SessionSearchBar.tsx`（新增：Cmd+G 搜索）
- `frontend/desktop-app/src/features/sessions/ForkConversation.tsx`（新增：消息级 fork 入口）
- `frontend/desktop-app/src/features/sessions/session.search.ts`（新增：本地索引，标题+消息文本）
- `frontend/desktop-app/src/features/sessions/SessionMenu.test.tsx`（新增）
- `protocol/schema.json` + `protocol/*.py`（扩展：`thread/fork`，new_method；`thread/pin`、`thread/archive` 为 B5 既有方法的追加字段语义或 new_optional_field）
- `appserver/handlers/thread_fork.py`（新增）
- `tests/test_thread_fork.py`（新增）

**规范限制**：
- 四件套协议归属冻结（**操作 = new_method，字段 ≠ 操作**）：`rename` / `pin` / `archive` 是**状态变更操作**——先核对主链 B5 是否已有对应 mutation 方法：有 → 直接复用（注明方法名/字段/原版验收）；只有资源字段、无 mutation 方法 → 新增 `thread/rename`、`thread/pin`、`thread/archive`（new_method，探针后提交协议变更单）；**禁止**用 `new_optional_field` 替代操作语义。`search` 为本地索引，不入协议
- **消息级 fork 语义冻结**：`thread/fork`（`{thread_id, message_id, edited_text?}`）→ 新 Thread 从该消息分叉，原 Thread 不变；**fork 点必须是 user message**（assistant 消息 / 工具调用 / 附件不可作 fork 点，请求无效返回协议错误）；空输入 Esc Esc = 编辑上一条用户消息并从该点 fork（Codex 语义）
- **fork 复制规则冻结**：复制到 fork 点为止的 user/assistant 消息（含文本与附件引用）；**不复制**工具调用历史、审批策略、Child 会话（子代理树在原 Thread 保留）
- fork 出的新 Thread 继承原会话的 workspace 绑定（B5 语义），不继承审批策略
- 搜索索引本地构建（sqlite/内存），不入协议；索引构建失败降级为标题搜索；**索引生命周期**：新消息增量入索引、归档/删除线程从索引清除（或标记不可命中）、fork 新线程继承到 fork 点的索引片段；**隐私边界**：索引落盘仅存线程标题与消息文本（含脱敏规则：不含密钥/路径全文，遵循主链 B13 crash 脱敏纪律），索引文件属于用户本地数据（`~/.rxycode/`，运行时数据目录规则见 §1-18），不入协议传输
- 不修改主链 H5 会话列表组件——新增 `SessionMenu` 挂接点（context menu 注册）

**开发步骤**：
1. 后端先行：`tests/test_thread_fork.py`（red）→ `thread/fork` 协议 → `appserver/handlers/thread_fork.py`（复用 B5 Thread 服务：复制到 message_id 的消息 + workspace 绑定）
2. 前端：`SessionMenu.test.tsx`（red）→ 三点菜单四件套 → `SessionSearchBar`（Cmd+G 打开，标题+内容匹配）→ `ForkConversation`（消息 hover "fork" 按钮 + Esc Esc 快捷）
3. 接线：pin 状态存 B5 thread 元数据（new_optional_field）；fork 结果跳转新 Thread
4. 五态：空/加载/错误/窄窗/深色

**示例代码**（fork 协议 handler）：

```python
# appserver/handlers/thread_fork.py —— 消息级 fork（GX8）
async def handle_thread_fork(thread_id: str, message_id: str, edited_text: str | None = None) -> dict:
    """从 message_id 分叉新 Thread；原 Thread 不变（Codex fork 语义）。"""
    src = await ThreadService.get(thread_id)
    cutoff = await MessageService.index_of(message_id)
    new_thread = await ThreadService.create(
        workspace_id=src.workspace_id,          # 继承 workspace 绑定（B5 语义）
        title=f"{src.title} (fork)",
        messages=await MessageService.slice(src.id, 0, cutoff + 1),
    )
    if edited_text:                             # Esc Esc 编辑重发路径
        await MessageService.replace_last(new_thread.id, edited_text)
    return {"thread_id": new_thread.id}
```

**验收命令**：
```powershell
python -m pytest tests/test_thread_fork -q
python -m pytest tests/test_threads -q   # 主链 B5 回归门禁（GX8 复用 B5 Thread 服务）
cd frontend\desktop-app
npm run typecheck && npm run test -- --run
# 契约：fork 三动作（原样/编辑重发/空输入 Esc Esc）、原 Thread 不变、pin/archive/search
# baseline: 按 §1-12 批次出口执行一次（卡级不跑，防双人覆盖）
```

**完成判据**：
- [ ] `thread/fork` 协议落地（含 edited_text 路径）
- [ ] 四件套可用：重命名/钉选/归档/搜索（Cmd+G）
- [ ] 消息 hover fork 入口 + Esc Esc 快捷（空输入时）
- [ ] fork 继承 workspace、不继承审批策略；原 Thread 不变
- [ ] 搜索索引失败降级标题搜索
- [ ] 五态测试通过；单 commit（批次 baseline 按 §1-12/§2 出口执行）

**Commit**：
```
feat(desktop): GX8 session management (rename/pin/archive/search) + message-level fork

Codex-inspired. thread/fork protocol method: fork from message id with
optional edited text; Esc-Esc edits last message and forks.
```

**P3 对接（追加，2026-08-12）**：pin 语义由 **GX20 会话三分类**整合——置顶会话归入"置顶"分类（固定分类顶部），pin 操作结果同步刷新分类投影；删除动作改为**软删除映射**（B17，进回收站），本卡归档/搜索语义不变；搜索索引的删除线程排除纪律由 B17 落实。

---

# P1 批（GX9–GX14）


</details>


## GX9-B · Plan 文件持久化 + Implement 按钮

**owner: backend（Composer 2.5）** · 分支 `feat/phase-g-backend`

**配对卡**：GX9-H（另一端施工文档） · **产品原文**：[`../PHASE-G-DESKTOP.md`](../PHASE-G-DESKTOP.md) 的 GX9

**本端必须实现**：
- 协议：`plan/persist`、`plan/implement`；数据目录 `RXYCODE_DATA_DIR` 注入
- M2：禁止 `appserver/handlers/`
- 禁碰 `core/agent_v2.py`、前端业务组件
- 只添加不改主链字段语义

**本端涉及文件**：
- `protocol/schema.json` + `protocol/*.py`（扩展：`plan/persist`、`plan/implement`，new_method）
- `appserver/plan_files.py`（新增：`~/.rxycode/plans/` 计划文件管理）  （M2：禁止新建 handlers/，用 `*_routes.py` / `*_service.py`）
- `tests/test_plan_files.py`（新增）

**本端协议要点**：`plan/persist`、`plan/implement`；数据目录 `RXYCODE_DATA_DIR` 注入

**本端验收**：
```powershell
# 本端：协议/appserver 定向测试（命令以卡内 pytest 为准，勿跑前端 npm）
python -m pytest tests/test_protocol -q
```
前端验收不在本卡。

**本端完成判据**：
- [x] 本端协议/服务落地（或探针路径 A 纯消费）
- [x] GXn-PROTO 变更单（若 new_method/event/field）
- [x] 定向 pytest 通过
- [x] 单 commit 到 `feat/phase-g-backend`（不要开 `feat/gxN`，不要跟前端分支互合并）

<details>
<summary>产品卡原文（验收细节以原文为准，本端只做本端条目）</summary>

## GX9 · Plan 文件持久化 + Implement 按钮

**借鉴来源**：Devin Desktop 计划文件持久化（调研 §6.3-2）；TRAE Plan/Spec 文档化工作流（§8.3-7/8）。
**优先级/工时**：P1 / 3–4d / 依赖：GX8 完成 / **owner: frontend + backend 协议扩展**
**背景**：主链的 plan（B5 的 planning 状态）不落盘、不可复用。Devin Desktop 证明：**计划成为外部持久 markdown 文件（会话间可 @ 复用），点 Implement 一键转执行**——是"规划与执行分离"的最强制度化形态；TRAE 的 Spec 三件套（大纲/任务/验收清单）是文档即资产的进一步佐证。

**涉及文件**：
- `frontend/desktop-app/src/features/plan/PlanFilePanel.tsx`（新增：计划文件查看/编辑/Implement）
- `frontend/desktop-app/src/features/plan/PlanImplementButton.tsx`（新增）
- `frontend/desktop-app/src/features/plan/PlanFilePanel.test.tsx`（新增）
- `protocol/schema.json` + `protocol/*.py`（扩展：`plan/persist`、`plan/implement`，new_method）
- `appserver/handlers/plan_files.py`（新增：`~/.rxycode/plans/` 计划文件管理）
- `tests/test_plan_files.py`（新增）

**规范限制**：
- 计划文件存放冻结：`~/.rxycode/plans/<thread_id>-<slug>.md`（运行时数据目录规则见 §1-18；不随 git 走，用户目录独立）
- `plan/persist`：把主链 plan 状态导出为 markdown（结构冻结：目标/步骤/验收清单三节）；`plan/implement`：读取计划文件 → 生成 Thread turn（计划作为首条上下文注入）→ 转执行
- 计划文件**只读复用**：@ 引用计划文件 = 注入文件内容进上下文（复用主链 @ 机制，不新增协议）
- Implement 前必须确认（防误触）；实施中的计划文件标记 `implementing` 状态
- 不修改主链 plan 状态机（B5）——persist 是导出视图，implement 是入口

**开发步骤**：
1. 后端先行：`tests/test_plan_files.py`（red）→ `plan/persist` / `plan/implement` → `appserver/handlers/plan_files.py`
2. 前端：`PlanFilePanel.test.tsx`（red）→ 面板（文件树/预览/编辑 markdown/Implement 按钮）→ 接线 @ 引用
3. 五态：无计划/加载/错误/窄窗/深色

**示例代码**（计划文件结构冻结）：

```md
<!-- 计划文件结构冻结（GX9）：目标 / 步骤 / 验收清单 三节 -->
# Plan: <title>
## 目标
<单段目标描述>
## 步骤
- [ ] 1. <step>
## 验收清单
- [ ] <acceptance criterion>
```

**验收命令**：
```powershell
python -m pytest tests/test_plan_files -q
cd frontend\desktop-app
npm run typecheck && npm run test -- --run
# 契约：persist 三节结构、implement 生成 turn、@ 引用注入、implementing 状态
# baseline: 按 §1-12 批次出口执行一次（卡级不跑，防双人覆盖）
```

> ⚠️ **2026-08-18 追加注记（四）· 本卡的 `goal` 节与 `/goal` 命令已被裁定为同一个东西**
>
> 本卡把计划文件冻结为三节 `goal` / `steps` / `acceptance`。**同时** Desktop 里已经有一个 `/goal` 命令（`lib/goalSettings.mts`，存 localStorage 的一段文本），两者同名但互不相干——这是典型的同名异物。
>
> [`PHASE-N-CLI-PARITY-LONGRUN.md`](./PHASE-N-CLI-PARITY-LONGRUN.md) **DN3 已裁定合并**：`/goal` 的目标本体写进本卡的 `goal` 节，完成判据写进 `acceptance` 节，长任务的检查点写进 `steps` 节的完成态。**从此是同一个东西，不建第二套存储。**
>
> **对本卡的影响：零。** 三节结构、存放路径、协议方法、完成判据全部照原样执行——Phase N 的 N5 是本卡的**下游消费方**，不是修改方。反过来说：**N5 依赖本卡，本卡未合入时 N5 输出 `BLOCKED_PREREQUISITE` 且禁止建临时存储**。所以本卡的优先级对 Phase N 的长任务线是硬约束。

**完成判据**：
- [ ] `plan/persist` / `plan/implement` 协议落地
- [ ] 计划文件三节结构冻结；存放于 `~/.rxycode/plans/`
- [ ] Implement 确认框 + implementing 状态
- [ ] @ 引用计划文件注入上下文
- [ ] 五态测试通过；单 commit（批次 baseline 按 §1-12/§2 出口执行）

**Commit**：
```
feat(desktop): GX9 persistent plan files with Implement flow

Devin-Desktop-inspired. plan/persist exports thread plan to
~/.rxycode/plans (goal/steps/acceptance); plan/implement starts execution
with the plan as first-turn context.
```

---


</details>


## GX13-B · OS 通知双档（回复到达 / 需要确认）

**owner: backend（Composer 2.5）** · 分支 `feat/phase-g-backend`

**配对卡**：GX13-H（另一端施工文档） · **产品原文**：[`../PHASE-G-DESKTOP.md`](../PHASE-G-DESKTOP.md) 的 GX13

**本端必须实现**：
- 协议：`event/agent_needs_input`（B12 流判定，new_event）
- M2：禁止 `appserver/handlers/`
- 禁碰 `core/agent_v2.py`、前端业务组件
- 只添加不改主链字段语义

**本端涉及文件**：
- `protocol/schema.json` + `protocol/*.py`（扩展：`event/agent_needs_input` 事件，new_event，符合原版 `event/agent_*` 命名空间）
- `appserver/needs_input.py`（新增：B12 事件流上的 needs_input 判定；产出 `event/agent_needs_input`）
- `tests/test_needs_input.py`（新增）

**本端协议要点**：`event/agent_needs_input`（B12 流判定，new_event）

**本端验收**：
```powershell
# 本端：协议/appserver 定向测试（命令以卡内 pytest 为准，勿跑前端 npm）
python -m pytest tests/test_protocol -q
```
前端验收不在本卡。

**本端完成判据**：
- [x] 本端协议/服务落地（或探针路径 A 纯消费）
- [x] GXn-PROTO 变更单（若 new_method/event/field）
- [x] 定向 pytest 通过
- [x] 单 commit 到 `feat/phase-g-backend`（不要开 `feat/gxN`，不要跟前端分支互合并）

<details>
<summary>产品卡原文（验收细节以原文为准，本端只做本端条目）</summary>

## GX13 · OS 通知双档（回复到达 / 需要确认）

**借鉴来源**：Copilot 通知双档（调研 §4.3-13）；Claude OS 通知（§3.3-14）；Cursor 通知（§5.3-15）。
**优先级/工时**：P1 / 2–3d / 依赖：B12 + H12 完成 / **owner: frontend + backend 事件扩展**
**背景**：agent 后台运行时用户切到别的窗口，任务完成或需要审批时没有在场感。Copilot 的双档语义最清晰：①回复到达（含预览，点击聚焦会话）②**需要输入/确认时**（agent 停下来等用户）。off/非聚焦/始终 三档开关。

**涉及文件**：
- `frontend/desktop-app/src/main/notifier.ts`（新增：Electron Main 侧 Notification 封装）
- `frontend/desktop-app/src/features/notifications/NotificationSettings.tsx`（新增：三档设置）
- `frontend/desktop-app/src/features/notifications/NotificationSettings.test.tsx`（新增）
- `protocol/schema.json` + `protocol/*.py`（扩展：`event/agent_needs_input` 事件，new_event，符合原版 `event/agent_*` 命名空间）
- `appserver/needs_input.py`（新增：B12 事件流上的 needs_input 判定；产出 `event/agent_needs_input`）
- `tests/test_needs_input.py`（新增）

**规范限制**：
- 双档语义冻结：`response`（**回合/回复完成时**触发，含 80 字符预览——逐 token 流式事件不触发，防通知轰炸）/ `needs_input`（agent 停等审批/提问）；needs_input 优先级高于 response
- **事件名对照纪律（未完成前卡级 BLOCKED 且不进入排期，二选一流程）**：`B12 事件对照表` + Protocol probe 是本卡正式前置产物——列出：B12 实际事件名 / 本卡用途 / 通知档位 / 去重字段；**探针结论二选一**：①B12 已有完整「等待输入」事件 → 本卡只消费既有事件，**不新增 `event/agent_needs_input`**；②不存在 → 新增 `event/agent_needs_input`（new_event 协议变更单，冻结来源事件、去重字段、验收样例）。对照表与探针未完成前本卡**不进入排期与实现**，状态恒为 `BLOCKED_PREREQUISITE`：`NEEDS_INPUT_EVENTS` 与 `RESPONSE_EVENTS` 的事件名必须逐项核对主链 B12 schema 实际事件名（事件命名空间 `event/agent_*`；占位名 `approval/requested` 不得使用）；**对照完成并更新本卡判定表之前，本卡状态为 `BLOCKED_PREREQUISITE`**——示例中的事件名是占位，不得直接照抄；B12 中不存在的事件名不得使用，改用 B12 实际事件并更新判定表
- 三档开关冻结：off / 非聚焦时 / 始终（默认"非聚焦时"）
- `event/agent_needs_input` 事件由 appserver 在 B12 事件流上判定发出（agent 停等/审批请求时），前端不自行猜测
- 通知点击聚焦对应会话窗口
- 通知内容脱敏（不含密钥/完整工具输出，遵循主链 B13 crash 脱敏纪律）
- 事件去重：同一 `request_id` / 同一 turn 只通知一次

**开发步骤**：
1. 后端先行：`tests/test_needs_input.py`（red）→ `appserver/needs_input.py`（监听 B12 事件流，输出 needs_input 事件）→ 协议 new_event
2. 前端：`NotificationSettings.test.tsx`（red）→ Main 侧 notifier（Electron Notification API）→ 设置页三档
3. 接线：response 事件（消费 B12）/ needs_input 事件 → 通知 + 点击聚焦
4. 五态

**示例代码**（needs_input 判定）：

```python
# appserver/needs_input.py —— 需要确认通知判定（GX13）
# ⚠ 伪代码：事件名一律用 <B12_EVENT_NAME> 占位；实现前必须替换为 B12 事件对照表中的实际事件名
#（事件命名空间 event/agent_*；对照表未完成前本卡 BLOCKED_PREREQUISITE，不进入排期）
NEEDS_INPUT_EVENTS = {"<B12_EVENT_NAME>"}   # 审批请求/agent 提问等（对照表确定）
RESPONSE_EVENTS = {"<B12_EVENT_NAME>"}      # 回合/线程完成（对照表确定）


def classify_notify(event: dict) -> str | None:
    """双档冻结：needs_input 优先于 response；逐 token 流式事件返回 None。"""
    if event.get("type") in NEEDS_INPUT_EVENTS:
        return "needs_input"
    if event.get("type") in RESPONSE_EVENTS:
        return "response"
    return None
```

**验收命令**：
```powershell
python -m pytest tests/test_needs_input -q
cd frontend\desktop-app
npm run typecheck && npm run test -- --run
# 契约：双档判定、三档开关、点击聚焦、脱敏
# baseline: 按 §1-12 批次出口执行一次（卡级不跑，防双人覆盖）
```

**完成判据**：
- [ ] B12 事件对照表 + Protocol probe 随 PR 提交（实际事件名逐项核对，无占位名）
- [ ] 按探针结论执行：B12 已有 → 只消费既有事件（零新增）；缺失 → `event/agent_needs_input` 变更单落地
- [ ] 双档通知 + 三档开关（默认非聚焦）
- [ ] 通知点击聚焦会话；内容脱敏
- [ ] 五态测试通过；单 commit（批次 baseline 按 §1-12/§2 出口执行）

**Commit**：
```
feat(desktop): GX13 two-tier OS notifications (response/needs_input)

Copilot-inspired. Per protocol probe: consumes existing B12 wait-input
events when present, or adds event/agent_needs_input via change request
when absent. Click-to-focus, sanitized.
```

**P3 对接（追加，2026-08-12）**：通知机制由 **GX27 运行状态视觉**扩展——"会话停止/异常"触发通知（复用本卡双档通道 + 三档开关）；通知三端实现（Windows toast / macOS UserNotifications / Linux libnotify，Electron `new Notification()` 统一，Linux 缺失降级应用内横幅，2026-08-12 报告 §6.9）。

---


</details>


## GX14-B · 模式选择器（Ask / Edit / Agent）

**owner: backend（Composer 2.5）** · 分支 `feat/phase-g-backend`

**配对卡**：GX14-H（另一端施工文档） · **产品原文**：[`../PHASE-G-DESKTOP.md`](../PHASE-G-DESKTOP.md) 的 GX14

**本端必须实现**：
- 协议：`agent/invoke` 可选字段 `capability`：`no_tools`/`edit_only`/`full`，工具注册层强制校验
- M2：禁止 `appserver/handlers/`
- 禁碰 `core/agent_v2.py`、前端业务组件
- 只添加不改主链字段语义

**本端涉及文件**：
- `protocol/schema.json` + `protocol/*.py`（扩展：`agent/invoke` 新增 optional field `capability`，new_optional_field）
- `appserver/tool_registry_capability.py`（新增：capability 白名单强制校验，工具注册层）
- `tests/test_invoke_capability.py`（新增：edit_only 会话拒绝 bash/delete/git 的 contract test）

**本端协议要点**：`agent/invoke` 可选字段 `capability`：`no_tools`/`edit_only`/`full`，工具注册层强制校验

**本端验收**：
```powershell
# 本端：协议/appserver 定向测试（命令以卡内 pytest 为准，勿跑前端 npm）
python -m pytest tests/test_protocol -q
```
前端验收不在本卡。

**本端完成判据**：
- [x] 本端协议/服务落地（或探针路径 A 纯消费）
- [x] GXn-PROTO 变更单（若 new_method/event/field）
- [x] 定向 pytest 通过
- [x] 单 commit 到 `feat/phase-g-backend`（不要开 `feat/gxN`，不要跟前端分支互合并）

<details>
<summary>产品卡原文（验收细节以原文为准，本端只做本端条目）</summary>

## GX14 · 模式选择器（Ask / Edit / Agent）

**借鉴来源**：Qoder Ask/Edit/Agent 三模式（调研 §9.3-1）；Devin Desktop 模式选择器（§6.3-1）；TRAE 权限模式（§8.3-4）。
**优先级/工时**：P1 / 3–4d 单人（双人并行 1.5-2d，含协议变更/生成类型/契约测试/联调）/ 依赖：H5 + B5 完成 / **owner: frontend + backend**
**背景**：主链会话只有一种"全能力 Agent 模式"。Qoder 证明同一会话流内切换 Ask（只问答）/ Edit（精确编辑不超预期）/ Agent（自主执行）让用户按问题难度匹配成本与自主度——对桌面工作台是刚需：查个问题不必启动完整 agent 回路。

**涉及文件**：
- `frontend/desktop-app/src/features/composer/ModeSelector.tsx`（新增：Ask/Edit/Agent 下拉）
- `frontend/desktop-app/src/features/composer/mode.ts`（新增：会话模式状态，发送时携带 capability 参数）
- `frontend/desktop-app/src/features/composer/ModeSelector.test.tsx`（新增）
- `protocol/schema.json` + `protocol/*.py`（扩展：`agent/invoke` 新增 optional field `capability`，new_optional_field）
- `appserver/tool_registry_capability.py`（新增：capability 白名单强制校验，工具注册层）
- `tests/test_invoke_capability.py`（新增：edit_only 会话拒绝 bash/delete/git 的 contract test）

**优先级/工时**：P1 / 3–4d（后端协议 1-2d + 前端 1-2d）/ 依赖：H5 + B5 完成（capability 后端校验） / **owner: frontend + backend**

**规范限制**：
- 三模式语义冻结：`ask`（只问答，**零工具**，capability=`no_tools`——注意与 B7 的 `read_only` 策略区分，read_only 允许读取类工具）/ `edit`（仅文件编辑工具，capability=`edit_only`）/ `agent`（全工具，capability=`full`，默认）
- **能力限制是后端安全边界，不是前端状态**：模式映射为 `agent/invoke` 请求新增 **optional field `capability`**（**枚举唯一冻结：`no_tools` / `edit_only` / `full`**，对应 ask/edit/agent 三模式），**由 appserver 在工具注册层强制校验**——`edit_only` 会话收到 `bash` / `delete` / `git` 工具调用**直接拒绝（协议错误，不进审批）**；`no_tools` 会话收到任何工具调用直接拒绝。能力是硬边界，审批（GX2 策略）不改变能力边界。前端只负责展示当前模式与发送参数，**前端状态不构成安全边界**
- **与 GX2 的权限预设组合关系（优先级矩阵，冻结）**：GX2 的 UI 预设（Ask/Auto/Full）与 GX14 的能力（ask/edit/agent）是**两个正交维度**——GX2 决定「动作到达边界时怎么审」（策略），GX14 决定「这个 turn 允许调什么工具」（能力）；组合生效规则：①能力是硬边界（edit 模式禁 bash/delete/git，后端强制，与预设无关）②策略是软边界（预设只改变审批通道）③冲突处理：`full_access` 策略不绕过能力硬边界（B7 full_access 与 GX14 能力校验叠加，取更严者）
- 走 GX2 的协议变更单流程扩展 `agent/invoke`（new_optional_field `capability`，request/response/错误码/contract test 在协议变更单中冻结）；若主链 `agent/invoke` 已有等价参数则复用并注明
- Edit 模式的写工具白名单冻结（后端校验）：`edit`/`write` 可、`bash`/`delete`/`git` 禁（直接拒绝（协议错误），不进审批（能力硬边界，与上方一致））
- 模式是**会话级**前端状态，切换不打断运行中 turn（下次发送生效）

> ⚠️ **2026-08-18 追加注记（三）· 本卡定义了与 GX2 的关系，但漏了与 `mode == "plan"` 的关系**
>
> 上面那条「与 GX2 的权限预设组合关系（优先级矩阵，冻结）」写得很好——两个正交维度、取更严者，这正是应该做的。**问题是它只覆盖了三分之二。**
>
> 系统里将有**三套独立的工具门**，全在后端，全会拒绝工具调用：
>
> 1. `mode == "plan"` 的只读门（`core/agent_v2.py:5097`，`PLAN_READONLY_TOOL_NAMES`）——**已实现，正在跑**
> 2. 本卡的 capability 白名单（`edit_only` 禁 `bash`/`delete`/`git`）
> 3. PHASE-K 极简 profile 的工具白名单
>
> 本卡定义了 1↔2 之外的那对（自己 ↔ GX2 审批策略），**但没定义 1↔2 本身**。具体会撞在这里：用户在 `plan` 模式（只读）+ `agent` 能力（全工具）下调 `write`，两道门一个拒一个放。**谁先执行？** `plan` 门返回的是 `[blocked: plan mode is read-only; write was not executed]`，本卡返回的是协议错误——同一个用户动作会因为门的执行顺序不同拿到两种完全不同的反馈，而两种都"合规"。
>
> **要求**：本卡实施前，把上面那张「优先级矩阵（冻结）」补上 `mode` 维度（至少覆盖 `plan × ask/edit/agent` 六格），错误信息取哪一条也要定死。**裁定权在本卡 owner**，[`PHASE-N-CLI-PARITY-LONGRUN.md`](./PHASE-N-CLI-PARITY-LONGRUN.md) DN7 只负责指出撞点，不代为决定。
>
> **另一处更要紧的：`capability` 挂在了错误的协议方法上。**
>
> 本卡把 `capability` 加为 **`agent/invoke` 的 optional field**。但 `agent/invoke` 是 **@ 提及某个子代理时的分派方法**（`useConversation.ts:780`，只在 `mention.agentIds` 分支里调用）；主对话走的是 **`session/prompt`**（同文件 `:809`）。
>
> 而本卡的 ModeSelector 装在 **composer** 上——那是主对话的输入框。**照本卡实施的结果是：用户在主对话切到 Edit 模式，`capability` 却只会跟着 @ 提及的子代理调用走，主对话这一轮压根不带这个字段。** 用户会看到「我明明选了 Edit，它还是跑了 bash」。
>
> `session/prompt` 已经在携带 `mode` 与 `permission_mode` 两个同类字段（`useConversation.ts:812-813`），**`capability` 属于同一族，应当加在那里**。若确实也需要覆盖 @ 提及路径，则两个方法都加，并在协议变更单里写明两处的优先级。
>
> 顺带一条命名提示：本卡的 Ask/Edit/Agent 叫「模式」，但系统里已经有 `mode`（`build`/`plan`/`compose`）、`permission_mode`（三档审批）、PHASE-K 的 profile（极简/标准）也常被叫「模式」——**四个东西同名**。本卡不必改名（它已冻结），但新文档一律避开这个词。

**开发步骤**：
1. 后端先行（协议）：`tests/test_invoke_capability.py`（red）→ `agent/invoke` 增加 optional field `capability`（默认 `full`，向后兼容）→ `appserver/tool_registry_capability.py` 在工具注册层校验（`edit_only` 会话收到 bash/delete/git 工具调用返回协议错误，走审计）→ contract test
2. 前端：`ModeSelector.test.tsx`（red）→ `mode.ts` + 组件（输入框左上角下拉 + 当前模式徽标）
3. 接线：发送时携带 `capability` 参数 → 主链 invoke；会话级模式状态
4. 五态

**示例代码**（模式→invoke 映射；能力限制由后端强制校验，前端仅展示）：

```ts
// mode.ts —— 三模式语义冻结（GX14）
export const MODE_TO_CAPABILITY: Record<SessionMode, string> = {
  ask: 'no_tools',       // 只问答（零工具；与 B7 read_only 策略区分）
  edit: 'edit_only',     // 仅编辑类工具（后端白名单校验）
  agent: 'full',         // 全工具（默认）
};
// 协议枚举唯一冻结：no_tools / edit_only / full（协议变更单 + schema + 生成类型一致）
// 发送：await invoke({ threadId, text, capability: MODE_TO_CAPABILITY[mode] })
// 安全边界在后端 tool_registry_capability.py，前端状态不构成安全边界
```

**验收命令**：
```powershell
python -m pytest tests/test_invoke_capability -q
cd frontend\desktop-app
npm run typecheck && npm run test -- --run
# 契约：三模式映射、后端 capability 白名单强制校验（edit_only 拒绝 bash/delete/git）、
#       schema 生成/contract test、切换不打断、默认 agent
# baseline: 按 §1-12 批次出口执行一次（卡级不跑，防双人覆盖）
```

**完成判据**：
- [ ] 三模式映射正确（capability 枚举 no_tools/edit_only/full 在 schema/生成类型/契约测试中一致）
- [ ] Edit 模式工具白名单生效（bash/delete/git 禁）
- [ ] 切换不打断运行中 turn
- [ ] 五态测试通过；单 commit（批次 baseline 按 §1-12/§2 出口执行）

**Commit**：
```
feat(desktop): GX14 Ask/Edit/Agent mode selector

Qoder-inspired session modes mapping to invoke capability param.
Edit mode tool allowlist freezes edit/write only. Default agent.
```

---

# P2 批（GX15–GX18）


</details>


## GX16-B · 侧聊 /side（不污染主线程的追问）

**owner: backend（Composer 2.5）** · 分支 `feat/phase-g-backend`

**配对卡**：GX16-H（另一端施工文档） · **产品原文**：[`../PHASE-G-DESKTOP.md`](../PHASE-G-DESKTOP.md) 的 GX16

**本端必须实现**：
- 协议：`thread/side_chat/create`、`thread/side_chat/close`（只读派生，不污染主线程）
- M2：禁止 `appserver/handlers/`
- 禁碰 `core/agent_v2.py`、前端业务组件
- 只添加不改主链字段语义

**本端涉及文件**：
- `protocol/schema.json` + `protocol/*.py`（扩展：`thread/side_chat/create`，new_method；`thread/side_chat/close`）
- `appserver/side_chat.py`（新增：只读上下文派生会话）  （M2：禁止新建 handlers/，用 `*_routes.py` / `*_service.py`）
- `tests/test_side_chat.py`（新增）

**本端协议要点**：`thread/side_chat/create`、`thread/side_chat/close`（只读派生，不污染主线程）

**本端验收**：
```powershell
# 本端：协议/appserver 定向测试（命令以卡内 pytest 为准，勿跑前端 npm）
python -m pytest tests/test_protocol -q
```
前端验收不在本卡。

**本端完成判据**：
- [x] 本端协议/服务落地（或探针路径 A 纯消费）
- [x] GXn-PROTO 变更单（若 new_method/event/field）
- [x] 定向 pytest 通过
- [x] 单 commit 到 `feat/phase-g-backend`（不要开 `feat/gxN`，不要跟前端分支互合并）

<details>
<summary>产品卡原文（验收细节以原文为准，本端只做本端条目）</summary>

## GX16 · 侧聊 /side（不污染主线程的追问）

**借鉴来源**：Codex /side（调研 §2.3-11）；Claude side chat /btw（§3.3-8）；Cursor /side（§5.3-15）。
**优先级/工时**：P2 / 2–3d / 依赖：GX8 完成 / **owner: frontend + backend 协议扩展**
**背景**：agent 干着长任务，用户想追问"这个方案有风险吗"又不想污染主转录。Codex/Claude/Cursor 三家都有 side chat：从当前会话派生临时对话（只读继承上下文），完成后回主 chat，主转录不变。且 side chat 复用缓存、成本极低。

**涉及文件**：
- `frontend/desktop-app/src/features/sidechat/SideChat.tsx`（新增：侧聊窗口）
- `frontend/desktop-app/src/features/sidechat/SideChat.test.tsx`（新增）
- `protocol/schema.json` + `protocol/*.py`（扩展：`thread/side_chat/create`，new_method；`thread/side_chat/close`）
- `appserver/handlers/side_chat.py`（新增：只读上下文派生会话）
- `tests/test_side_chat.py`（新增）

**规范限制**：
- 侧聊语义冻结：`thread/side_chat/create`（`{thread_id}`）→ 派生临时会话，**只读继承**主会话上下文（历史消息投影，不复制），独立 message 流
- 侧聊完成的结论可 `promote` 回主会话（追加为一条 assistant 摘要消息，需用户确认）；默认不写回
- 侧聊的生命周期绑定主会话（主会话归档/删除 → 侧聊关闭）
- 复用主链缓存（上下文前缀一致 → 缓存命中），成本不计入主会话 usage（独立计数，GX7 的 event/agent_usage 按会话隔离）

**开发步骤**：
1. 后端先行：`tests/test_side_chat.py`（red）→ 协议两方法 → `appserver/handlers/side_chat.py`
2. 前端：`SideChat.test.tsx`（red）→ 侧聊窗口（浮层 + 输入 + 结论 promote 按钮）
3. 接线：消息 hover 菜单"在侧聊中追问"入口
4. 五态

**示例代码**（侧聊派生语义）：

```python
# appserver/handlers/side_chat.py —— 只读派生（GX16）
async def handle_side_chat_create(thread_id: str) -> dict:
    """侧聊 = 只读上下文投影 + 独立消息流（Codex /side 语义）。"""
    parent = await ThreadService.get(thread_id)
    side = await ThreadService.create_side_session(
        parent_id=thread_id,
        context_projection=await MessageService.project_context(parent.id),  # 只读投影
        budget_tag="side",          # 独立 usage 计数（GX7 会话隔离）
    )
    return {"side_thread_id": side.id, "context_tokens": side.context_tokens}
```

**验收命令**：
```powershell
python -m pytest tests/test_side_chat -q
cd frontend\desktop-app
npm run typecheck && npm run test -- --run
# 契约：只读派生、独立消息流/usage、promote 需确认、生命周期绑定
# baseline: 按 §1-12 批次出口执行一次（卡级不跑，防双人覆盖）
```

**完成判据**：
- [ ] `thread/side_chat/create|close` 协议落地
- [ ] 只读上下文投影（不复制）；独立 usage 计数
- [ ] promote 需确认；默认不写回主会话
- [ ] 主会话归档/删除联动关闭侧聊
- [ ] 五态测试通过；单 commit（批次 baseline 按 §1-12/§2 出口执行）

**Commit**：
```
feat(desktop): GX16 side chat (read-only derived session)

Codex/Claude/Cursor-inspired. thread/side_chat/create projects parent
context read-only, independent message stream and usage accounting;
promote back requires confirmation.
```

---


</details>


## GX18-B · Follow-up 任务推荐

**owner: backend（Composer 2.5）** · 分支 `feat/phase-g-backend`

**配对卡**：GX18-H（另一端施工文档） · **产品原文**：[`../PHASE-G-DESKTOP.md`](../PHASE-G-DESKTOP.md) 的 GX18

**本端必须实现**：
- 协议：followup_scanner 纯规则零 LLM；无新协议，消费 B12 事件
- M2：禁止 `appserver/handlers/`
- 禁碰 `core/agent_v2.py`、前端业务组件
- 只添加不改主链字段语义

**本端涉及文件**：
- `appserver/followup_scanner.py`（新增：turn 完成事件的规则扫描器——纯规则，不调 LLM）
- `tests/test_followup_scanner.py`（新增）

**本端协议要点**：followup_scanner 纯规则零 LLM；无新协议，消费 B12 事件

**本端验收**：
```powershell
# 本端：协议/appserver 定向测试（命令以卡内 pytest 为准，勿跑前端 npm）
python -m pytest tests/test_protocol -q
```
前端验收不在本卡。

**本端完成判据**：
- [x] 本端协议/服务落地（或探针路径 A 纯消费）
- [x] GXn-PROTO 变更单（若 new_method/event/field）
- [x] 定向 pytest 通过
- [x] 单 commit 到 `feat/phase-g-backend`（不要开 `feat/gxN`，不要跟前端分支互合并）

<details>
<summary>产品卡原文（验收细节以原文为准，本端只做本端条目）</summary>

## GX18 · Follow-up 任务推荐

**借鉴来源**：Replit Follow-up tasks（调研 §10.3-11）；Claude Task chips（§3.3-11）。
**优先级/工时**：P2 / 2–3d / 依赖：GX1 完成 / **owner: frontend + backend 事件扩展**
**背景**：agent 完成主任务后发现"范围外但值得做"的事（如测试缺失、遗留 TODO、潜在重构），Replit 在任务完成后推荐 follow-up 任务（可批量接受）；Claude 以 task chips 出现在对话中，点击即新会话启动。主动但不抢。

**涉及文件**：
- `frontend/desktop-app/src/features/followup/FollowUpSuggestions.tsx`（新增：完成后的建议卡）
- `frontend/desktop-app/src/features/followup/FollowUpSuggestions.test.tsx`（新增）
- `appserver/followup_scanner.py`（新增：turn 完成事件的规则扫描器——纯规则，不调 LLM）
- `tests/test_followup_scanner.py`（新增）

**规范限制**：
- 扫描器**纯规则零 LLM**（成本为零）：turn 完成事件 + 工作区扫描（未覆盖测试文件 / 遗留 TODO / 未提交变更）→ 最多 3 条建议
- 建议卡动作冻结：`Accept`（新建 Thread，建议文本为首条消息）/ `Dismiss` / `Ignore all`；批量接受上限 3
- 建议卡只在主任务完成后出现一次（同一 turn 不重复推荐）
- 建议不进主转录（独立浮层，点击接受才创建 Thread）——Claude Task chips 语义
- 新 Thread 继承 workspace 绑定（B5 语义），不自动执行

**开发步骤**：
1. 后端先行：`tests/test_followup_scanner.py`（red）→ `appserver/followup_scanner.py`（规则扫描 + 上限 3 + 去重）
2. 前端：`FollowUpSuggestions.test.tsx`（red）→ 建议卡（Accept/Dismiss/Ignore all）→ 接受后新建 Thread
3. 接线：消费 B12 的 turn 完成事件
4. 五态

**示例代码**（规则扫描器）：

```python
# appserver/followup_scanner.py —— 纯规则零 LLM（GX18）
RULES = [
    ("missing_tests", lambda ws: ws.untracked_py_files_without_test()),
    ("leftover_todo", lambda ws: ws.find_todo_markers(limit=5)),
    ("uncommitted", lambda ws: ws.git_uncommitted()),
]


def scan(ws) -> list[str]:
    out = []
    for name, fn in RULES:
        if len(out) >= 3:                      # 上限 3 冻结
            break
        for item in fn(ws) or []:
            out.append(f"{name}: {item}")
    return out[:3]
```

**验收命令**：
```powershell
python -m pytest tests/test_followup_scanner -q
cd frontend\desktop-app
npm run typecheck && npm run test -- --run
# 契约：三条规则、上限 3、去重、一次推荐、Accept 建 Thread
# baseline: 按 §1-12 批次出口执行一次（卡级不跑，防双人覆盖）
```

**完成判据**：
- [ ] 规则扫描器落地（零 LLM、上限 3、去重）
- [ ] 建议卡在 turn 完成后出现一次；Accept 新建 Thread
- [ ] 建议不进主转录；新 Thread 继承 workspace
- [ ] 五态测试通过；单 commit（批次 baseline 按 §1-12/§2 出口执行）

**Commit**：
```
feat(desktop): GX18 follow-up task suggestions

Replit/Claude-inspired. Rule-based scanner (zero LLM, max 3, deduped)
on turn completion; Accept creates a new thread inheriting workspace.
```

---

# P3 批（GX19–GX28 · Codex 对齐批）

> **批性质**：本批为 **P3 · Codex 对齐批**（新增批次），追加于 P2（GX15–GX18）之后。立项依据：`research/2026-08-12-agent-native-computer-use-research.md`（Agent-Native Computer Use + GUI Codex 对齐 + CLI-Anything 混合集成）。前端基建依赖 H14–H19（PHASE-G-FRONTEND.md 追加卡），后端依赖 B14–B18（PHASE-G-BACKEND.md 追加卡）。**主链出口门槛与 P0/P1/P2 批次不变**；本批出口定义见 §3。
> **跨平台（通用约束，所有 P3 卡生效）**：Windows/Linux/macOS 三端适配——系统 API（通知/语言/安全存储）按报告 §6.9 平台差异表实现；打包 smoke 覆盖 macOS/Linux 构建目标；禁止仅 Windows 可用依赖（直接 subprocess 调 python/pip，规避 CLI-Anything 的 cygpath 已知坑）。


</details>


## GX19-B · 多 Agent 活动可视化

**owner: backend（Composer 2.5）** · 分支 `feat/phase-g-backend`

**配对卡**：GX19-H（另一端施工文档） · **产品原文**：[`../PHASE-G-DESKTOP.md`](../PHASE-G-DESKTOP.md) 的 GX19

**本端必须实现**：
- 协议：多 Agent 活动事件投影；依赖 F12/E4；禁止 mock 团队协议
- M2：禁止 `appserver/handlers/`
- 禁碰 `core/agent_v2.py`、前端业务组件
- 只添加不改主链字段语义

**本端涉及文件**：
- `protocol/schema.json` + `protocol/*.py`（E4 `agent_*` 事件域——**E 阶段合入后消费，本卡不新增字段**）
- `tests/test_team_view.tsx`（新增）

**本端协议要点**：多 Agent 活动事件投影；依赖 F12/E4；禁止 mock 团队协议

**本端验收**：
```powershell
# 本端：协议/appserver 定向测试（命令以卡内 pytest 为准，勿跑前端 npm）
python -m pytest tests/test_protocol -q
```
前端验收不在本卡。

**本端完成判据**：
- [x] 本端协议/服务落地（或探针路径 A 纯消费）
- [x] GXn-PROTO 变更单（若 new_method/event/field）
- [x] 定向 pytest 通过
- [x] 单 commit 到 `feat/phase-g-backend`（不要开 `feat/gxN`，不要跟前端分支互合并）

<details>
<summary>产品卡原文（验收细节以原文为准，本端只做本端条目）</summary>

## GX19 · 多 Agent 活动可视化

**借鉴来源**：DeerFlow SSE + Last-Event-ID（调研报告 §3.5）；Vibe-Trading events.jsonl + live callback（8 项目报告）；多 Agent 专家团设计（2026-08-11 报告 C5/GX19 立项）。
**优先级/工时**：P1 / 3–4d / 依赖：PHASE-F F12（委派树）+ PHASE-E E4（AgentEvent 事件域）+ H18（前端契约预留）/ **owner: frontend + backend 协议扩展**
**背景**：多 Agent 专家团（F）的"看得见才算真"判据（2026-08-11 报告 FM3 可视化证据）——委派树、成员独立状态、团长中转消息流、预算条必须在前端呈现；E/F 未实施前本卡输出 BLOCKED_PREREQUISITE（禁止 mock 假协议）。

**涉及文件**：
- `frontend/desktop-app/src/features/team/TeamView.tsx`（新增：委派树 + 成员状态灯 + 消息流 + 预算条；H18 挂载点填充）
- `frontend/desktop-app/src/lib/agentEvents.ts`（H18 骨架实现：E4 事件投影）
- `protocol/schema.json` + `protocol/*.py`（E4 `agent_*` 事件域——**E 阶段合入后消费，本卡不新增字段**）
- `tests/test_team_view.tsx`（新增）

> ### 追加注记（2026-08-18）：PHASE-E 前置已复核**通过**，本卡的 E 侧门控可以放行
>
> 下方门控说「PHASE-E/F 未合入 → BLOCKED」。为本卡实测了 E 侧：**E3 的 `appserver/agent_runtime.py`（19,100 B，`class AgentRuntime`）与 E4 的 `AgentEvent` / `event/agent` 均在位**，后者覆盖 `protocol/notifications.py`、`protocol/schema.json` 与 `frontend/protocol-client/src/generated/types.ts`（TS 生成物也已同步），E 阶段 165 个契约测试全绿。
>
> 所以本卡「涉及文件」里那句「E 阶段合入后消费」的前提**成立**，`agent_*` 事件域可以直接消费。
>
> **开工前仍建议跑一次**（30 秒，比读 PHASE-E 的勾可靠）：
> ```powershell
> cd D:\agent-demo\RxyCode\RxyCode1_1_0
> Select-String -Path protocol\notifications.py,protocol\schema.json,frontend\protocol-client\src\generated\types.ts -Pattern 'AgentEvent|event/agent' -List
> # 三处全中 = E4 就位。零命中才输出 BLOCKED_PREREQUISITE
> ```
>
> **F 侧门控不受本注记影响**，仍需自行确认 F12（委派树）状态。
>
> **本注记是一次更正。** 同日早些时候此处曾贴出相反结论（称 E4 全仓零命中、门控会错误放行），那是**基于一次过时观测**的误判，已撤回；原委见 [`PHASE-G-CONFLICT-AUDIT.md`](./PHASE-G-CONFLICT-AUDIT.md) 的 X8。

**规范限制**：
- **门控**：PHASE-E/F 未合入 → 本卡 BLOCKED_PREREQUISITE（不 mock、不显示入口）
- 委派树为**真树**（F12 数据消费），禁止前端自造层级；成员状态灯 = E4 AgentEvent 投影（agent_started/tool/progress/done/paused/cancelled/budget_exceeded）
- 预算条 = E3 每 agent 预算池投影（只显示，不计算）；中转消息流 = 团长转发的 ConsultRequest 投影（F7）
- 视觉与 §5.2 铁律一致（纯投影不改变业务语义）；五态覆盖

**开发步骤**：
1. 后端先行：E4 事件域 + F12 委派树协议（E/F 卡范围，本卡等待）
2. 前端：`agentEvents.ts` reducer（H18）→ `TeamView.tsx`（树/状态灯/消息流/预算条）→ `tests/test_team_view.tsx`
3. 接线：capability 门控开关（F10 `settings.agents.enabled`）
4. 五态

**示例代码**（AgentEvent 投影，消费侧）：

```ts
// frontend/desktop-app/src/lib/agentEvents.ts —— E4 AgentEvent 投影（GX19）
type AgentEvent = { session_id: string; agent_id: string; run_id: string; method: AgentMethod; seq: number };
type AgentMethod =
  | "agent_started" | "tool" | "progress" | "done"
  | "paused" | "cancelled" | "budget_exceeded" | "denied";

export const projectAgentState = (events: AgentEvent[]) =>
  events.reduce<Record<string, AgentStatus>>((acc, e) => {
    acc[e.agent_id] = eventToStatus(e.method);   // 纯投影，不产生业务状态
    return acc;
  }, {});
```

**验收命令**：
```powershell
python -m pytest tests/test_protocol -q
cd frontend\desktop-app
npm run typecheck && npm run test -- --run
# 契约：E/F 未合入 → BLOCKED_PREREQUISITE（零 mock 路径）；合入后：树/状态灯/预算条随事件流实时投影
# baseline: 按 §1-12 批次出口执行一次（卡级不跑，防双人覆盖）
```

**完成判据**：
- [ ] E/F 合入后委派树/成员状态/预算条随事件流投影
- [ ] capability 门控生效（未合入零痕迹，无 mock）
- [ ] 纯投影验证（前端不产生业务状态）
- [ ] 五态测试通过；单 commit

**Commit**：
```
feat(desktop): GX19 multi-agent activity visualization

DeerFlow/MAST-informed. Delegation tree + member status + budget bar
projected from E4 AgentEvent stream; capability-gated, no mock paths.
```

---


</details>


## GX20-B · 会话三分类 + 折叠交互（置顶 / 项目 / 最近）

**owner: backend（Composer 2.5）** · 分支 `feat/phase-g-backend`

**配对卡**：GX20-H（另一端施工文档） · **产品原文**：[`../PHASE-G-DESKTOP.md`](../PHASE-G-DESKTOP.md) 的 GX20

**本端必须实现**：
- 协议：会话分类字段（置顶/项目/最近）；优先复用 B5 既有 archive/list filter
- M2：禁止 `appserver/handlers/`
- 禁碰 `core/agent_v2.py`、前端业务组件
- 只添加不改主链字段语义

**本端涉及文件**：
- `protocol/schema.json`（B5 thread 元数据 pin/`deleted_at` 消费——探针确认已有字段则直接复用）
- `tests/test_session_categories.tsx`（新增）

**本端协议要点**：会话分类字段（置顶/项目/最近）；优先复用 B5 既有 archive/list filter

**本端验收**：
```powershell
# 本端：协议/appserver 定向测试（命令以卡内 pytest 为准，勿跑前端 npm）
python -m pytest tests/test_protocol -q
```
前端验收不在本卡。

**本端完成判据**：
- [x] 本端协议/服务落地（或探针路径 A 纯消费）
- [x] GXn-PROTO 变更单（若 new_method/event/field）
- [x] 定向 pytest 通过
- [x] 单 commit 到 `feat/phase-g-backend`（不要开 `feat/gxN`，不要跟前端分支互合并）

<details>
<summary>产品卡原文（验收细节以原文为准，本端只做本端条目）</summary>

## GX20 · 会话三分类 + 折叠交互（置顶 / 项目 / 最近）

**借鉴来源**：Codex 会话侧栏（布局/折叠/hover 直接照搬，亮度取样为准）；2026-08-12 报告 §6.1–6.2 规格。
**优先级/工时**：P0 / 3–4d / 依赖：B5（Thread 元数据）+ H15（会话栏重构基建）+ GX8（pin 语义）/ **owner: frontend + backend 协议扩展**
**背景**：会话栏按 **置顶 / 项目 / 最近** 三分类（自上而下）组织：置顶 = pin 会话（固定分类顶部）；项目 = 项目目录树（每项目展开其会话）；最近 = 未归类未置顶会话。折叠/展开与 hover 高亮对齐 Codex（用户确认规格：收起时标题右侧 `>` 符号，与标题间距 4px）。

**涉及文件**：
- `frontend/desktop-app/src/components/SessionList.tsx`（H15 重构产物上实现分类区）
- `frontend/desktop-app/src/lib/sessionCategories.ts`（分类归属规则；H15 已建）
- `protocol/schema.json`（B5 thread 元数据 pin/`deleted_at` 消费——探针确认已有字段则直接复用）
- `tests/test_session_categories.tsx`（新增）

**规范限制**：
- **分类归属规则冻结**：置顶（pin）→ 项目（workspace 绑定）→ 最近（其余）；删除会话 → 回收站投影（B17）
- **折叠交互冻结**：分类标题点击折叠/展开；收起态标题右侧 `>`（展开态 `v`/向下），间距 4px；折叠状态本地持久化（localStorage），不影响后端
- **hover 亮度**：浅色 ≈ rgba(0,0,0,0.06)、深色 ≈ rgba(255,255,255,0.08)，**以 Codex 实机取样为准**（验收含截图对照）
- 分类标题次要灰字体（design token secondary text）；状态色语义不改（沿用现有约定）
- 纯前端投影（不改 B5 数据）；pin 语义复用 GX8（本卡不新增协议方法；若 B5 缺 pin/deleted 字段 → GXn-PROTO 登记 new_optional_field）

**开发步骤**：
1. 后端先行：探针 B5 元数据（pin/deleted_at 是否存在）→ 缺失则 GXn-PROTO 登记
2. 前端：`sessionCategories.ts` 分类规则（red）→ SessionList 三分类区 + 折叠 → hover 取样落地
3. 接线：GX8 pin 操作 → 置顶分类刷新；B17 软删除 → 回收站投影
4. 五态 + 截图对照

**示例代码**（分类归属规则）：

```ts
// frontend/desktop-app/src/lib/sessionCategories.ts —— 三分类归属（GX20）
export type SessionCategory = "pinned" | "project" | "recent";

export function categorize(thread: ThreadMeta, projectId: string | null): SessionCategory {
  if (thread.pinned) return "pinned";                       // 置顶优先
  if (projectId && thread.workspaceId) return "project";    // 项目归属
  return "recent";                                          // 最近兜底
}
```

**验收命令**：
```powershell
python -m pytest tests/test_threads -q
cd frontend\desktop-app
npm run typecheck && npm run test -- --run
# 契约：三分类归属、折叠/`>` 方向、hover 取样值（截图对照）、pin 进置顶、删除进回收站投影
# baseline: 按 §1-12 批次出口执行一次（卡级不跑，防双人覆盖）
```

**完成判据**：
- [ ] 三分类归属规则生效（置顶/项目/最近）
- [ ] 折叠/展开 + `>` 符号 + 4px 间距 + 状态持久化
- [ ] hover 亮度取样值落地（截图对照记录）
- [ ] pin/软删除联动（B5/B17 探针结论记录）
- [ ] 五态测试通过；单 commit

**Commit**：
```
feat(desktop): GX20 session sidebar categories (pinned/project/recent)

Codex-inspired. Three-category sidebar with fold/unfold chevron and
hover highlight sampled from Codex; pin and trash projection wired.
```

---


</details>


## GX23-B · 定时任务 UI

**owner: backend（Composer 2.5）** · 分支 `feat/phase-g-backend`

**配对卡**：GX23-H（另一端施工文档） · **产品原文**：[`../PHASE-G-DESKTOP.md`](../PHASE-G-DESKTOP.md) 的 GX23

**本端必须实现**：
- 协议：消费 B16 `schedule/*`；禁止再造调度器
- M2：禁止 `appserver/handlers/`
- 禁碰 `core/agent_v2.py`、前端业务组件
- 只添加不改主链字段语义

**本端涉及文件**：
- `tests/test_schedule_section.tsx`（新增）

**本端协议要点**：消费 B16 `schedule/*`；禁止再造调度器

**本端验收**：
```powershell
# 本端：协议/appserver 定向测试（命令以卡内 pytest 为准，勿跑前端 npm）
python -m pytest tests/test_protocol -q
```
前端验收不在本卡。

**本端完成判据**：
- [x] 本端协议/服务落地（或探针路径 A 纯消费）
- [x] GXn-PROTO 变更单（若 new_method/event/field）
- [x] 定向 pytest 通过
- [x] 单 commit 到 `feat/phase-g-backend`（不要开 `feat/gxN`，不要跟前端分支互合并）

<details>
<summary>产品卡原文（验收细节以原文为准，本端只做本端条目）</summary>

## GX23 · 定时任务 UI

**借鉴来源**：用户规格（2026-08-12 报告 §6.7）：任务列表/触发规则/动作/启停/编辑/删除；间隔 + 指定时间触发。
**优先级/工时**：P2 / 2–3d / 依赖：B16（定时任务调度器）/ **owner: frontend + backend 协议消费**
**背景**：后端 B16 提供应用层调度（asyncio，三端一致），前端提供管理界面：创建/编辑/启停/删除定时任务。

**涉及文件**：
- `frontend/desktop-app/src/features/settings/ScheduleSection.tsx`（新增：设置页分区或独立面板）
- `frontend/desktop-app/src/components/ScheduleForm.tsx`（新增：触发规则 + 动作表单）
- `tests/test_schedule_section.tsx`（新增）

**规范限制**：
- 表单字段：名称、触发规则（间隔 N 分钟/小时/天 或 指定时间）、动作（运行指定会话/命令/技能——选择器复用现有 Thread/技能数据源）
- 列表：启停开关、下次触发预览（B16 返回）、编辑/删除
- 消费 `schedule/*` 协议（B16，GXn-PROTO 登记）；B16 未合入 → BLOCKED_PREREQUISITE
- 执行中任务的状态展示（复用 B12 长任务语义）；删除/停用确认（非风险级，普通确认即可）

**开发步骤**：
1. 后端先行：B16（本卡等待）
2. 前端：`ScheduleForm.test.tsx`（red）→ 表单 + 列表 + 启停
3. 接线：`schedule/*` 协议消费；下次触发预览
4. 五态

**验收命令**：
```powershell
python -m pytest tests/test_schedule -q
cd frontend\desktop-app
npm run typecheck && npm run test -- --run
# 契约：两种触发规则、启停、编辑、删除、下次触发预览
```

**完成判据**：
- [ ] 创建/编辑表单（间隔 + 指定时间 + 动作选择器）
- [ ] 列表 + 启停 + 下次触发预览
- [ ] 删除/停用确认
- [ ] 五态测试通过；单 commit

**Commit**：
```
feat(desktop): GX23 scheduled tasks UI

Interval and fixed-time triggers; run session/command/skill actions;
next-run preview from B16; BLOCKED until scheduler lands.
```

---


</details>


## GX24-B · 插件生态（市场 + 管理）

**owner: backend（Composer 2.5）** · 分支 `feat/phase-g-backend`

**配对卡**：GX24-H（另一端施工文档） · **产品原文**：[`../PHASE-G-DESKTOP.md`](../PHASE-G-DESKTOP.md) 的 GX24

**本端必须实现**：
- 协议：消费 B18 `plugin/*`；toggle 转发 B11 `capability/set_enabled`
- M2：禁止 `appserver/handlers/`
- 禁碰 `core/agent_v2.py`、前端业务组件
- 只添加不改主链字段语义

**本端涉及文件**：
- `tests/test_plugin_section.tsx`（新增）

**本端协议要点**：消费 B18 `plugin/*`；toggle 转发 B11 `capability/set_enabled`

**本端验收**：
```powershell
# 本端：协议/appserver 定向测试（命令以卡内 pytest 为准，勿跑前端 npm）
python -m pytest tests/test_protocol -q
```
前端验收不在本卡。

**本端完成判据**：
- [x] 本端协议/服务落地（或探针路径 A 纯消费）
- [x] GXn-PROTO 变更单（若 new_method/event/field）
- [x] 定向 pytest 通过
- [x] 单 commit 到 `feat/phase-g-backend`（不要开 `feat/gxN`，不要跟前端分支互合并）

<details>
<summary>产品卡原文（验收细节以原文为准，本端只做本端条目）</summary>

## GX24 · 插件生态（市场 + 管理）

**借鉴来源**：Codex plugins 形态 + CLI-Anything SKILL.md 机制（2026-08-12 报告 §6.6）。
**优先级/工时**：P2 / 3–4d / 依赖：B18（插件注册与市场后端）/ **owner: frontend + backend 协议消费**
**背景**：插件 = 命令 + 技能 + 工具/MCP 配置的组合包（manifest 声明）。市场页浏览/安装/卸载/启停；与 G13 能力面板（已安装能力统一入口）、设置页技能/MCP 管理（细粒度控制）三者并存不冲突。

**涉及文件**：
- `frontend/desktop-app/src/features/settings/PluginSection.tsx`（新增：已装插件管理）
- `frontend/desktop-app/src/features/market/MarketPage.tsx`（新增：市场浏览/搜索/安装）
- `tests/test_plugin_section.tsx`（新增）

**规范限制**：
- 市场数据源：B18（本地目录 + 远程 registry）；安装 = 后端校验 + 注册（manifest 校验失败显示原因）
- 已装列表：名称/版本/来源/启停开关/卸载（卸载确认：保留用户配置语义）
- 插件声明的能力（技能/工具/MCP）安装后出现在 G13 能力面板——本卡不重复渲染，只显示"包含能力"摘要
- 消费 `plugin/*` 协议（B18，GXn-PROTO 登记）；B18 未合入 → BLOCKED_PREREQUISITE

**开发步骤**：
1. 后端先行：B18（本卡等待）
2. 前端：`MarketPage.test.tsx`（red）→ 市场列表/搜索/安装 → `PluginSection`（启停/卸载）
3. 接线：`plugin/*` 消费 + G13 面板联动验证
4. 五态

**验收命令**：
```powershell
python -m pytest tests/test_plugin -q
cd frontend\desktop-app
npm run typecheck && npm run test -- --run
# 契约：市场浏览/搜索/安装、manifest 失败原因展示、启停、卸载确认、G13 联动
```

**完成判据**：
- [ ] 市场页（浏览/搜索/安装 + 失败原因展示）
- [ ] 已装管理（启停/卸载确认/包含能力摘要）
- [ ] G13 能力面板联动验证
- [ ] 五态测试通过；单 commit

**Commit**：
```
feat(desktop): GX24 plugin market and management

Manifest-driven plugins (commands + skills + tool/MCP configs);
market browse/install with failure reasons; G13 capability panel sync.
```

---


</details>


## GX25-B · CLI-Anything 工具接入 + 预览画廊

**owner: backend（Composer 2.5）** · 分支 `feat/phase-g-backend`

**配对卡**：GX25-H（另一端施工文档） · **产品原文**：[`../PHASE-G-DESKTOP.md`](../PHASE-G-DESKTOP.md) 的 GX25

**本端必须实现**：
- 协议：消费 B14 `cli/list|install|launch`；禁止 `cli:` 进入 tools/registry
- M2：禁止 `appserver/handlers/`
- 禁碰 `core/agent_v2.py`、前端业务组件
- 只添加不改主链字段语义

**本端涉及文件**：
- `tests/test_cli_tool_panel.tsx`（新增）

**本端协议要点**：消费 B14 `cli/list|install|launch`；禁止 `cli:` 进入 tools/registry

**本端验收**：
```powershell
# 本端：协议/appserver 定向测试（命令以卡内 pytest 为准，勿跑前端 npm）
python -m pytest tests/test_protocol -q
```
前端验收不在本卡。

**本端完成判据**：
- [x] 本端协议/服务落地（或探针路径 A 纯消费）
- [x] GXn-PROTO 变更单（若 new_method/event/field）
- [x] 定向 pytest 通过
- [x] 单 commit 到 `feat/phase-g-backend`（不要开 `feat/gxN`，不要跟前端分支互合并）

<details>
<summary>产品卡原文（验收细节以原文为准，本端只做本端条目）</summary>

## GX25 · CLI-Anything 工具接入 + 预览画廊

**借鉴来源**：CLI-Anything（Apache-2.0）预览栈协议 + 混合集成决策（2026-08-12 报告 §3.4/§5）。
**优先级/工时**：P1 / 3–4d / 依赖：B14（CLI 桥接器）+ H19（工具面板与画廊基建）/ **owner: frontend + backend 协议消费**
**背景**：消费 B14 的 `cli:*` 工具（来源标签 内置/CLI-Hub/自生成），画廊渲染 CLI-Anything 预览 bundle（hero/gallery/video/JSON）——软件控制"软联系"的 GUI 呈现面。

> ⚠️ **2026-08-18 追加注记（二）· 本卡没问题，但它依赖的 B14 有一处会击穿缓存基线**
>
> **先说结论：本卡一个字都不用改。** 表单化调用（`cli/list` + `cli/<tool>/schema` + `cli/launch`）本来就是按需拉 schema，这是对的。
>
> 问题在 **B14**（`PHASE-G-BACKEND.md:493`）：「CLI 工具以 `cli:<软件名>` 前缀**注册进 `tools/registry.py`**」。那个 registry 是进 LLM 工具 schema 的，于是**用户每装一个软件，冻结前缀里就多一个工具定义**——`cli/install` 会当场改变 `tools_digest`，**整个前缀缓存失效**。用户做了一件与对话无关的事，下一轮命中率归零，97%/95% 的基线扛不住。
>
> 处置见 [`PHASE-N-CLI-PARITY-LONGRUN.md`](./PHASE-N-CLI-PARITY-LONGRUN.md) §6.4 与 HN2：B14 改为只注册恒定两个 agent 工具（`cli_list` / `cli_run`），具体软件的 schema 走既有的 `cli/<tool>/schema` 按需拉取。`cli:` 命名空间、同名冻结纪律、来源标签**全部保留**。**本卡消费的协议方法与数据形状不变**，所以本卡的涉及文件、规范限制、完成判据一律照原样执行。

**涉及文件**：
- `frontend/desktop-app/src/components/ToolCard.tsx`（来源分组展示；H19 已扩展）
- `frontend/desktop-app/src/features/preview/PreviewGallery.tsx`（bundle 渲染；H19 已建，本卡补数据源接线）
- `frontend/desktop-app/src/components/CliToolLauncher.tsx`（新增：`cli:gimp <subcommand> --json` 表单化调用）
- `tests/test_cli_tool_panel.tsx`（新增）

**规范限制**：
- **来源分组**：内置 / CLI-Hub / 自生成（B14 来源标签）；B14 未合入 → 仅内置组（不 BLOCKED）
- **画廊边界（硬约束）**：文件渲染（本地 bundle 目录），**不隐含 PHASE-I 图片附件协议**（PHASE-I 未实施，零依赖）
- 决策规则（报告 §5.3）前端提示：registry 有 → 提示"CLI-Hub 现成"；无 → 提示"生成"入口（B15 合入后）
- 预览性能预算沿用 CLI-Anything 规范（hero ≤1280px / ≤25MB / 懒加载）；`summary.json` 紧凑展示
- 跨平台：本地路径三端（file:// 归一化）；禁止平台特有依赖

**开发步骤**：
1. 后端先行：B14（本卡等待其 `cli:*` 协议）
2. 前端：`CliToolLauncher.test.tsx`（red）→ 表单化调用 → 来源分组接线 → 画廊数据源接线
3. 接线：`cli/list` + bundle 目录扫描；B14 未合入时分组降级
4. 五态

**示例代码**（表单化调用）：

```tsx
// frontend/desktop-app/src/components/CliToolLauncher.tsx —— cli: 工具调用（GX25）
// 命令面 → 表单：参数从 cli/<tool>/schema 派生（B14 返回），提交走 cli/launch
const run = () =>
  rpc.request("cli/launch", {
    tool: `cli:${tool.name}`,
    args: fieldValues,            // --json 默认附加
    workspace_id: activeWorkspace,
  });
```

**验收命令**：
```powershell
python -m pytest tests/test_cli_bridge -q
cd frontend\desktop-app
npm run typecheck && npm run test -- --run
# 契约：来源分组（B14 未合入仅内置）、表单化调用、画廊四类 artifact、性能预算、零 PHASE-I 依赖
```

**完成判据**：
- [ ] 工具来源分组（内置/CLI-Hub/自生成）生效
- [ ] `cli:launch` 表单化调用（参数派生 + --json）
- [ ] 画廊渲染 hero/gallery/video/JSON + 性能预算 + 懒加载
- [ ] 零 PHASE-I 附件协议依赖（边界声明验证）
- [ ] 五态测试通过；单 commit

**Commit**：
```
feat(desktop): GX25 CLI tool panel and preview gallery

CLI-Anything bridge consumer: source-grouped tools, form-based launch,
bundle gallery (file-rendering only, no PHASE-I dependency).
```

---


</details>


## GX26-B · 设置页重构（8 分区）

**owner: backend（Composer 2.5）** · 分支 `feat/phase-g-backend`

**配对卡**：GX26-H（另一端施工文档） · **产品原文**：[`../PHASE-G-DESKTOP.md`](../PHASE-G-DESKTOP.md) 的 GX26

**本端必须实现**：
- 协议：设置分区注册项；消费 B10 settings；禁止第二套 settings 真相
- M2：禁止 `appserver/handlers/`
- 禁碰 `core/agent_v2.py`、前端业务组件
- 只添加不改主链字段语义

**本端涉及文件**：
- `tests/test_settings_sections.tsx`（新增）

**本端协议要点**：设置分区注册项；消费 B10 settings；禁止第二套 settings 真相

**本端验收**：
```powershell
# 本端：协议/appserver 定向测试（命令以卡内 pytest 为准，勿跑前端 npm）
python -m pytest tests/test_protocol -q
```
前端验收不在本卡。

**本端完成判据**：
- [x] 本端协议/服务落地（或探针路径 A 纯消费）
- [x] GXn-PROTO 变更单（若 new_method/event/field）
- [x] 定向 pytest 通过
- [x] 单 commit 到 `feat/phase-g-backend`（不要开 `feat/gxN`，不要跟前端分支互合并）

<details>
<summary>产品卡原文（验收细节以原文为准，本端只做本端条目）</summary>

## GX26 · 设置页重构（8 分区）

**借鉴来源**：Codex 设置页交互（左下角入口 + 分区导航）；2026-08-12 报告 §6.4。
**优先级/工时**：P0 / 4–5d / 依赖：H16（设置重构框架）+ B10（Settings 后端）+ D5（模型管理已实现）/ **owner: frontend + backend**
**背景**：设置页重构为 8 分区：回收站 / 常规 / 外观 / 模型选择 / 模型添加 / 技能管理 / MCP 服务管理 / 团队与模型（预留）。入口 = 左下角"设置"图标 + 文字（圆角框 + hover 高亮）。

**涉及文件**：
- `frontend/desktop-app/src/components/SettingsPage.tsx`（H16 重构产物，各分区填充）
- `frontend/desktop-app/src/features/settings/AppearanceSection.tsx`（新增：主题扩展/自定义/字体/密度）
- `frontend/desktop-app/src/features/settings/GeneralSection.tsx`（新增：语言/启动/默认目录）
- `frontend/desktop-app/src/features/settings/ModelSection.tsx`（新增：选择 + AddModelPanel 复用 + **思考强度选择器**）
- `frontend/desktop-app/src/features/settings/SkillSection.tsx`（新增：对接 B11 skill_manager）
- `frontend/desktop-app/src/features/settings/McpSection.tsx`（新增：对接 B11 mcp/）
- `tests/test_settings_sections.tsx`（新增）

**规范限制**：
- **入口冻结**：左下角圆角矩形（圆角 ≈ 6px 取样），设置图标 + "设置"文字，hover 高亮（同 GX20 亮度规格）
- 分区职责冻结：回收站（GX21 挂载）、常规（语言=H14/GX22、启动行为、默认目录、开发者选项）、外观（theme system/light/dark/high-contrast 扩展、自定义、字体/字号、密度）、模型选择（D5 `models/set_active`）、模型添加（**AddModelPanel 直接复用，后端零改动**）、技能管理（B11 skill_manager——**不新造后端**）、MCP 管理（B11 mcp/）、团队与模型（**预留：F10 开关 + H10 三层折叠对齐；Auto 开关独立设置项与开启时 token 消耗弹窗由 GX28 Team Manager 落地；未合入 → BLOCKED_PREREQUISITE 不 mock**）
- **思考强度选择器（2026-08-12 追加，与 CLI `/effort` 共用同一后端通道）**：
  - 位置：**模型选择**分区（模型选择下方）；控件 = 档位下拉/选择列表（英文档位名）
  - 档位来源：**当前激活模型的 `effort_options`**（`models/list` 返回；空列表 = 不支持档位选择 → 控件禁用并显示"当前模型不支持档位选择"）
  - 提交：`models/set_active` 带 `effort` optional_field（或 `/effort` 命令语义），**全局生效**（切换模型后档位随模型能力自动回退，不报错）
  - 显示：当前档位高亮（`models/list` 返回的 `effort` 字段；未设置显示默认 balanced）
  - 与 CLI 一致性：CLI `/effort` 与 GUI 选择器读写同一全局设置（`config/model_manager` 的 `effort` 键），切换即时生效
- 分区注册表：新增分区只加注册项不改骨架（H16 机制）；设置层级（global/project/workspace/thread）既有语义不变（B10）
- 跨平台：安全存储复用 credential_store（DPAPI/Keychain/Secret Service 已跨平台）

**开发步骤**：
1. 后端探针：B11 skill/mcp 接口存在性（已存在——tools/skill_manager.py、mcp/ 代码实证）；`models/list` 的 `effort`/`effort_options` 字段（2026-08-12 已实现）
2. 前端：分区逐个（General → Appearance → Model → Skill → Mcp）→ 入口 → 团队预留；ModelSection 内接思考强度选择器（消费 `effort_options`/`effort`，提交 `models/set_active` 带 effort）
3. 接线：D5/B11 协议消费；AddModelPanel 复用验证；effort 与 CLI `/effort` 互通验证
4. 五态

**验收命令**：
```powershell
python -m pytest tests/test_settings -q; python -m pytest tests/test_capabilities -q
python -m pytest tests/test_appserver/test_model_routes.py -q   # set_active effort + list effort/effort_options
cd frontend\desktop-app
npm run typecheck && npm run test -- --run
# 契约：8 分区导航/懒加载、模型添加复用 D5（后端零改动）、技能/MCP 对接现有后端、
#       思考强度选择器（档位随模型/无档位禁用/全局生效/与 CLI 互通）、团队预留 BLOCKED
```

**完成判据**：
- [ ] 左下角入口（图标+文字+圆角框+hover）落地
- [ ] 8 分区填充完成（含常规/外观/模型/技能/MCP）
- [ ] AddModelPanel 复用（后端零改动验证）
- [ ] **思考强度选择器：档位随当前模型 `effort_options` 渲染、无档位禁用、提交 `models/set_active` 带 effort、与 CLI `/effort` 读写互通**
- [ ] 团队与模型预留分区 BLOCKED（不 mock）
- [ ] 五态测试通过；单 commit

**Commit**：
```
feat(desktop): GX26 settings rebuild (8 sections)

Codex-inspired entry and nav; model add reuses D5 panel; skills/MCP
consume existing B11 backends; team section capability-gated.
```

---


</details>


## GX28-B · Team Manager（专家团管理与选择）

**owner: backend（Composer 2.5）** · 分支 `feat/phase-g-backend`

**配对卡**：GX28-H（另一端施工文档） · **产品原文**：[`../PHASE-G-DESKTOP.md`](../PHASE-G-DESKTOP.md) 的 GX28

**本端必须实现**：
- 协议：消费 F18b `team/*` 若存在；缺失则 BLOCKED，禁止伪造 team RPC
- M2：禁止 `appserver/handlers/`
- 禁碰 `core/agent_v2.py`、前端业务组件
- 只添加不改主链字段语义

**本端涉及文件**：
- `protocol/schema.json` + `protocol/*.py`（F18 `team_*` 协议消费——**F18 合入后消费，本卡不新增字段**）
- `tests/test_team_picker.tsx` / `tests/test_team_manager.tsx` / `tests/test_team_section.tsx`（新增）

**本端协议要点**：消费 F18b `team/*` 若存在；缺失则 BLOCKED，禁止伪造 team RPC

**本端验收**：
```powershell
# 本端：协议/appserver 定向测试（命令以卡内 pytest 为准，勿跑前端 npm）
python -m pytest tests/test_protocol -q
```
前端验收不在本卡。

**本端完成判据**：
- [ ] 本端协议/服务落地（或探针路径 A 纯消费）
- [ ] GXn-PROTO 变更单（若 new_method/event/field）
- [ ] 定向 pytest 通过
- [ ] 单 commit 到 `feat/phase-g-backend`（不要开 `feat/gxN`，不要跟前端分支互合并）

<details>
<summary>产品卡原文（验收细节以原文为准，本端只做本端条目）</summary>

## GX28 · Team Manager（专家团管理与选择）

**借鉴来源**：Claude Code Skills 双控规范（`disable-model-invocation`/`user-invocable`，2026-08-11 调研）；多 Agent 专家团设计报告 §9.3/C8（2026-08-11）；F18 生态后端（TeamRegistry/TeamImporter/team_install）。
**优先级/工时**：P3 / 5–6d / 依赖：F18（TeamRegistry/TeamImporter/team_install）+ GX19（多 Agent 活动可视化）+ GX26（设置页"团队与模型"分区）/ **owner: frontend + backend 协议消费**
**背景**：专家团生态的"用户侧"落地（F18 是后端）：CLI `/team` 三层窗口流（像选模型一样选专家团）、GUI 分组管理（other / 自定义组 rename/delete）、**Auto 开关（Team 分组下独立设置项 + 开启时 token 消耗弹窗提示）**、team_install 前端（模型主导安装，两步询问：确认 + 选分组）。F18 未合入前本卡输出 BLOCKED_PREREQUISITE（禁止 mock 假生态）。

**涉及文件**：
- `frontend/opentui-app/`（CLI `/team` 命令：复用 CommandPalette + `Command.category` 分组字段，不新造路由）
- `frontend/desktop-app/src/features/team/TeamPicker.tsx`（新增：三层窗口流——分组列表 → 组内团队列表 → 团队详情）
- `frontend/desktop-app/src/features/team/TeamManager.tsx`（新增：分组管理 other/rename/delete）
- `frontend/desktop-app/src/features/team/TeamInstallPanel.tsx`（新增：安装两步询问——确认 + 选分组）
- `frontend/desktop-app/src/features/settings/TeamSection.tsx`（新增：GX26"团队与模型"分区的 Auto 开关独立设置项）
- `protocol/schema.json` + `protocol/*.py`（F18 `team_*` 协议消费——**F18 合入后消费，本卡不新增字段**）
- `tests/test_team_picker.tsx` / `tests/test_team_manager.tsx` / `tests/test_team_section.tsx`（新增）

**规范限制**：
- **门控**：PHASE-F F18 未合入 → 本卡 BLOCKED_PREREQUISITE（不 mock、不显示入口；与 GX19 同款门控纪律）
- **PROTO 登记说明**：本卡**无协议扩展**（F18 的 `team_*` 协议由 PHASE-F 定义，本卡纯消费）——按 §1 通用纪律**无需 GXn-PROTO 登记**；若实施时发现 F18 未提供所需协议方法，挂起等待并走协议变更单，禁止前端自造协议
- **F18b 追加注记（2026-08-19）**：`team/list` `team/groups` `team/group_rename` `team/install` `team/set_active` 已由 PHASE-F F18b 交付。本卡判据不变，仍只消费、不自造协议。
- **/team 三层窗口流（冻结）**：窗口 1 分组列表（内置组 + 用户组 + other）→ Enter 进窗口 2 组内团队列表 → Enter 进窗口 3 团队详情（成员角色/各自职责/团队 description/成本提示：预估 token 倍数 3–5x）→ **Enter 确认使用 / Esc 逐级返回**；CLI 与 GUI 同构
- **分组语义**：内置组不可删；用户组可 rename/delete；**delete 后组内团队自动归 `other` 组**（F18 `teams.groups.yaml` 后端语义，前端只投影不计算）
- **Auto 开关**：位于 GX26"团队与模型"分区内、独立设置项（on/off）；**点击 on 时弹窗提示**："开启后系统将自动判断任务是否使用子代理/多 Agent 专家团并选择合适专家团；可能产生更多 token 消耗（实测 3–15x）。是否开启？"；关闭时整块隐藏（F13 Settings 分层纪律）
- **双控路由与组合语义**：`disable_model_invocation: true` 的团队只可由用户显式选（`/team`），模型自动选择（`/auto`）时不可见（F18 路由索引语义）；**组合状态冻结**——Auto 开启但某团队 disable_model_invocation：该团队不出现在自动路由候选，但 `/team` 手动选择与 token 弹窗不受影响（弹窗提示的是整体 token 消耗，与单团队双控无关）；模型主导安装对被禁团队一律拒绝（仅手动安装可用）
- **安装双路径**：手动（本地目录/zip，4 步：来源→路径→校验预览→确认+选分组）与模型主导（告诉模型名字/URL → 模型安装 → **询问用户确认 + 询问选分组，默认 other**）并存；复用 `download_skill` 的确认交互模式
- 视觉与 §5.2 铁律一致（纯投影不改变业务语义）；五态覆盖

**开发步骤**：
1. 后端先行：F18 TeamRegistry/TeamImporter/team_install（F 卡范围，本卡等待）
2. CLI：`/team` 命令注册（复用 CommandPalette + category）→ 三层窗口流
3. GUI：TeamPicker → TeamManager（分组管理）→ TeamSection（Auto 开关 + 弹窗）→ TeamInstallPanel（两步询问）
4. 接线：capability 门控（F18 未合入零痕迹）；F10 `settings.agents.enabled` 联动 Auto 开关
5. 五态

**示例代码**（CLI /team 窗口流骨架，复用 CommandPalette）：

```tsx
// frontend/opentui-app —— /team 三层窗口流（分组 → 团队 → 详情）
const [view, setView] = useState<"groups" | "teams" | "detail">("groups");
const [group, setGroup] = useState<Group | null>(null);
const [team, setTeam] = useState<TeamSpec | null>(null);

// 窗口 1：分组列表（含 other）→ Enter 进窗口 2
<CommandPalette commands={groups.map(g => ({
  name: g.name, description: `${g.teamIds.length} 个团队`, category: "team",
}))} ... />
// 窗口 3：团队详情（成员角色/职责/成本提示）→ Enter 确认 / Esc 返回
<TeamDetail team={team} onConfirm={() => setActiveTeam(team.id)} onBack={() => setView("teams")} />
// 双控：disable_model_invocation 的团队不出现在模型自动选择索引（F18 路由索引）
```

**验收命令**：
```powershell
python -m pytest tests/test_protocol -q
cd frontend\desktop-app
npm run typecheck && npm run test -- --run
# 契约：F18 未合入 → BLOCKED_PREREQUISITE（零 mock 路径）；合入后：/team 三层流可走通、
# 分组 rename/delete 归 other、Auto 开关 on 弹 token 提示、安装两步询问
# baseline: 按 §1-12 批次出口执行一次（卡级不跑，防双人覆盖）
```

**完成判据**：
- [ ] F18 合入后 `/team` 三层窗口流走通（Enter 确认 / Esc 返回逐级）
- [ ] 分组管理：自定义组 rename/delete，delete 后归 other（纯投影验证）
- [ ] Auto 开关独立设置项 + on 时 token 弹窗提示（文案冻结）
- [ ] 双控路由：`disable_model_invocation` 团队在 `/auto` 不可见
- [ ] 安装双路径（手动 4 步 + 模型主导 2 步询问）走通
- [ ] capability 门控生效（F18 未合入零痕迹，无 mock）；五态测试通过；单 commit

**Commit**：
```
feat(desktop): GX28 team manager (picker/groups/auto-toggle/install)

F18-backed team ecosystem UX: /team three-level picker, group mgmt
(other fallback), auto-toggle with token-cost dialog, dual-path install.
Capability-gated, no mock paths.
```

---


</details>

