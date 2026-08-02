# 模型分工（权威）

> **创建**：2026-08-01 · **更新**：2026-08-01  
> **一句话**：**Composer 主写全部代码，Grok 辅助前端（只在写前端用到多模态时才介入）。**  
> 冲突时以本文为准，覆盖各 Phase / L 文档里旧的表述（含「Composer 唯一写代码」「Composer/Grok 前后端分治」）。

---

## §0 谁干什么

| 模型 | 职责 | 纪律手册 |
|---|---|---|
| **Composer 2.5** | **主写全部代码**：后端（Python、协议 schema、appserver、评测、桥接、EKO 引擎）+ 前端（Electron / React / TypeScript / 协议客户端 / UI）。前端默认也由它写 | [`COMPOSER-2.5-PLAYBOOK.md`](./COMPOSER-2.5-PLAYBOOK.md) |
| **Grok 4.5** | **前端辅助**：只在**写前端需要多模态（视觉）** 的环节介入——看 UI 截图自检、图片类 UI（粘贴/预览）、以图片为输入的设计任务。前端无多模态环节时不参与；空闲时仍可查外部资料 | [`GROK-FRONTEND-PLAYBOOK.md`](./GROK-FRONTEND-PLAYBOOK.md) |
| **Sonnet 5**（可选） | Diff 预审，不写功能代码 | — |

**Grok 选型理由**：用它是因为它**多模态**——前端卡里凡是要"看"的环节（渲染截图核对、视觉 bug 定位、图片交互），才轮到 Grok。不是因为它该拥有前端。

**禁止**：

- ❌ Grok 改 `core/`、`tools/`、`api_server.py`、`src/linkagent/**/*.py`（L9-1 / L9-2 是纯后端卡，Composer 的）
- ❌ Grok 在没有多模态环节的前端卡上"顺手帮忙"（那是 Composer 的主写范围）
- ❌ 同一张卡两个模型同时改同一文件（交接点除外）
- ✅ Composer 可以碰任何代码目录——它主写一切

---

## §1 文件归属（Composer 全权，Grok 辅助前端）

### Composer · 主写（默认拥有）

| 路径模式 | 项目 |
|---|---|
| `core/` · `tools/` · `execution/` · `memory/` · `config/` · `evals/` · `api_server.py` · `main.py` | RxyCode |
| `protocol/`（Python + `schema.json`）· `appserver/` | RxyCode Phase 2 |
| `src/linkagent/**/*.py` · `tests/**/*.py` · `pyproject.toml` | LinkAgent |
| `src/linkagent/protocol/` · `src/linkagent/appserver/` | LinkAgent L9-1 / L9-2 |
| `frontend/` · `frontend/opentui-app/` · `frontend/protocol-client/` | RxyCode |
| `desktop/`（Electron 壳、Vite、React、打包脚本） | RxyCode Phase 3 · LinkAgent L9 |
| `*.tsx` · `*.ts`（业务 UI，不含由 schema 生成的类型源） | 两边 |
| 施工文档里标注 `owner: backend` / `owner: frontend` 的卡 | 两边 |

### Grok · 前端辅助（仅在多模态环节）

| 介入场景 | 例子 |
|---|---|
| 视觉验收 | 渲染截图核对（布局/空态/加载态/错误态）、改动前后截图对比、UI 截图找视觉 bug |
| 图片类 UI | 图片粘贴/预览/附件选择器的实现与验收（Phase E 相关） |
| 以图片为输入的任务 | 照着设计稿/竞品截图实现 UI、图标/素材核对 |
| 查外部资料 | 各家 vision API 差异、前端库官方文档（空闲时） |

> Grok 的产出永远落在**前端文件**里，且必须由 Composer 的卡收口（见 GROK-FRONTEND-PLAYBOOK G5）。它没有自己的文件所有权。

### 交接点（协议契约）

| 产物 | 谁产出 | 谁消费 | 规则 |
|---|---|---|---|
| `protocol/schema.json` / `linkagent/protocol/schema.json` | **Composer** | Composer 生成 TS | schema 合并后，前端类型才开工 |
| JSON-RPC 方法/事件名 | Composer 定契约 | 前端只调用 | 前端不得发明协议方法 |
| 审批 / 流式事件形状 | Composer | 前端渲染 | UI 不得改事件语义 |

---

## §2 卡归属速查

> 标注 `owner: backend` 的卡：Composer 独做。  
> 标注 `owner: frontend` 的卡：**Composer 主写**；卡内含多模态环节的，该环节交给 Grok 辅助，卡上会写明。

### RxyCode

| 阶段 | Composer（主写） | Grok（辅助） |
|---|---|---|
| Phase 0 止血 / Phase 1 评测 | **全部** | 空闲 / 查资料 |
| Phase 2 协议 | **P1–P8 全部**（含 P2 协议客户端、P5 OpenTUI 迁移） | P2/P5 里的视觉验收等多模态环节（若有） |
| Phase 3 Desktop | **D1–D8 全部** | D3/D4/D5 等 UI 卡的渲染截图核对（视觉验收） |
| Phase C Desktop | **C1–C16 全部** | C6/C9/C10/C15 等卡的视觉验收和图片/预览环节 |
| Phase A / B / D / F | **全部**（后端架构或接口预留） | — |
| Phase E 多模态 | **全部** | 图片粘贴、附件、视觉 UI 等卡的多模态环节 |

### LinkAgent

| 阶段 | Composer（主写） | Grok（辅助） |
|---|---|---|
| L0–L8 · L10 | **全部** | 空闲时可做预研；**不写 Python** |
| L9-1 / L9-2 协议与 appserver | ✅ | ❌ |
| L9-3 TS 类型 + 传输客户端 | ✅（从 `schema.json` 生成） | ❌（无多模态环节） |
| L9-4 ~ L9-8 Electron / 视图 / 设置 / 打包 | ✅ 主写 | L9-4 壳换肤、L9-5 森林树等卡**视觉验收**环节 |

---

## §3 双窗口怎么开

```
窗口 Composer ── 主链：后端卡 + 前端卡（默认它全写）
窗口 Grok     ── 辅助：前端卡的多模态环节（视觉验收 / 图片 UI / 设计稿核对）
```

- **早期（几乎都是后端卡）**：Grok 窗口做外部资料调研，或空着——**不要为了填满窗口让 Grok 碰后端**。
- **Phase 3 / L9 前端阶段**：Composer 写前端卡，卡里标了「多模态环节」的，把那一环节交给 Grok 并行做（视觉验收、截图对比）；Grok 产出回传 Composer 收口。
- **同仓并行**：仍用 git worktree；前端卡本体是 Composer 的分支，Grok 辅助产出并入该分支，不另开前端分支。

详细顺序与门禁 → [`ENGINEERING-TIMELINE.md`](./ENGINEERING-TIMELINE.md)。

---

## §4 开卡前 10 秒检查

1. 这张卡是 `owner: backend` 还是 `owner: frontend`？没标 → 看 §2 表。
2. 前端卡：卡里有没有「多模态环节」标注？有 → 那一段是 Grok 的活；没有 → 整卡 Composer 独做。
3. 读对应 playbook（后端/前端主写都读 Composer；要委托 Grok 的环节读 Grok 手册 §2）。
4. 涉及交接点？先确认上游产物已合并（schema / Phase 3 壳）。
5. 一次一张卡，一个 commit。

---

## §5 和旧文档的关系

| 旧说法 | 现在 |
|---|---|
| 「Composer 是唯一写代码的模型」 | **作废**。Composer 主写全部；Grok 辅助前端多模态 |
| 「Grok 只查资料，不写代码」 | **作废**。Grok 在写前端用到多模态时介入；查资料是空闲时的副业 |
| 「Composer 写后端，Grok 写前端，两边不跨界」 | **作废**。Composer 主写前端；Grok 只做前端多模态环节，不跨界到后端 |
| 「前端卡 owner 是 Grok」 | **作废**。`owner: frontend` 的执行者是 Composer，Grok 只做卡内标注的多模态环节 |
| 各 Phase §0.2 / L 文档顶部「干活前读 COMPOSER playbook」 | 后端卡与前端卡都读 Composer；委托 Grok 的环节再读 Grok 手册；总入口是本文 |
