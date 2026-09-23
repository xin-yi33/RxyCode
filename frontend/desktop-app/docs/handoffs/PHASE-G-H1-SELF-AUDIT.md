# PhaseG-H1 开发者自审

对照：`PHASE-G-FRONTEND.md` PhaseG-H1 + 八条硬规则 DC-J1–J8；完整基线 `PHASE-G-DESKTOP.md` G1。

## 卡级回路

| 步骤 | 结果 |
|---|---|
| LOCATE | 壳已存在，未创建假壳 |
| READ | 已读 H1 / G1 / §0–§3 / §1.2 白名单 |
| WRITE | 仅前端白名单：desktop-app + protocol-client |
| TYPECHECK | `frontend/desktop-app` npm run typecheck 通过；`protocol-client` tsc 通过 |
| UNIT | h1-baseline 6 pass；handshake.placeholder 2 pass |
| PROCESS/E2E | 本卡验收命令不含进程门；G1 进程验收归后端 B1。记录 `npm run smoke` 为既有 Phase4 命令，H1 未宣称 smoke 新通过 |
| VISUAL | 卡内 Grok=无 |
| HANDOFF | `docs/handoffs/PHASE-G-H1-HANDOFF.yaml` |
| COMMIT | luna 通过后提交 |

## 完成判据（H1 原文）

| 判据 | 自审 |
|---|---|
| Desktop 入口、Renderer、Main、preload、protocol-client 目录边界已记录 | 通过（BASELINE.md） |
| 生成类型来源和 schema 版本已记录 | 通过（schema 1.1.0，generate 产物 commit af0adee） |
| 没有 renderer → Python/HTTP 直连 | 通过（静态扫描测试） |
| 可独立回滚 commit | 待 luna 通过后提交 |

## G1 额外项

| 项 | 自审 |
|---|---|
| 缺失路径记录 | 无缺失壳；`src/protocol/` 与 `tests/` 为 H1 新增而非假壳 |
| 启动方式 / Node/Bun/Python / 构建命令 | 已记录 |
| OpenTUI 与 Desktop 共享生成类型 | 已记录，二者均 file:../protocol-client |
| capability/version handshake 测试占位 | 已加，未实现 H2 全量错误模型 |
| 可复用 / 需补齐 / 禁止重写清单 | 已输出 |
| 未重排整个 frontend/ | 通过 |
| 未改 schema / appserver / 后端测试 | 通过 |
| 未声明能力不显示为可用 | 占位函数 + 测试；UI 门控仍属 H2 |

## DC-J 抽查

- DC-J1：Renderer 经 protocol-client + preload，无 Python/HTTP。
- DC-J2：占位只做版本匹配与 capability===true，不复制权限/resolver。
- DC-J3：`isDeclaredCapability` 仅 `true` 视为启用。
- DC-J7：webPreferences 三件套有测试锁定。
- DC-J8：无截图替代测试。

## 不在本卡宣称完成

H2–H13 缺口已列入「需要补齐」，不打钩。
