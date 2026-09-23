# ARCH-001: 单一 JSON-RPC 与 Session 假面

## Status
Accepted

## Date
2026-09-01

## Context
OpenTUI/Desktop 走 appserver stdio JSON-RPC；Ink 仍可走 `api_server.py` HTTP/SSE。风险是为插件/Connect/CU 再开一套聊天脑，或 UI import `core/`。

## Decision
- Headless `Session`（`core/session.py`）不做 TUI/HTTP I/O，只 `emit()` 协议事件。
- 所有表面共用 **一份** JSON-RPC（`protocol/` + `appserver/`）。
- Ink+SSE 是同一 Session 的后备适配器，不是第二大脑。禁止为插件/CU 再开 `/chat`。
- UI 不得 import Python `core/`。

## Alternatives Considered

### 每表面一个 loop
- Rejected：CLI/GUI 必然漂移（备忘 P1）。

### MCP tools/call 当产品会话
- Rejected：MCP 是能力线，不是 TUI/GUI 聊天传输（crew Pairing）。

## Consequences
允许改：`protocol/`、`appserver/` 方法域、`core/session.py`。  
禁止顺手改：`agent_v2.py` 业务分支、TUI chrome、OS 沙箱剖面。

## 允许改 / 禁止顺手改
见 [`MODULE-BOUNDARIES.md`](../plans/opus5-plan/rxycode/architecture/MODULE-BOUNDARIES.md)。
