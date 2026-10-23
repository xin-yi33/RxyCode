# WEB-W1-C05 self-audit

- core_for_surface("cli" | "opentui" | "desktop" | "web") returns one Session class, one AgentRuntime class, and one ToolOrchestrator class. The unit test asserts those are the objects in core.session, core.agents.runtime, and the worker helper.
- session_type_for_worker() is what bind_core_session and the interrupt path construct. It calls core_for_surface("desktop").
- rxycode --help still lists gui, config, and --model. rxycode web --help says the entry is not delivered and lists connect. rxycode web connect --help says device connect is not implemented. Running connect raises ClickException and does not start a device.
- browser_entry_status returns BLOCKED when source imports electron or a preload path. frontend/protocol-client/src/webTransport.ts has neither. index.ts exports the reserved adapter.
- The unrelated desktop executable filter in main.py stays unstaged.
- open_shared_core creates one mechanical AgentRuntime and every surface calls memory_set on that same object. creations stays 1.
- browser_entry_status rejects import "electron", await import("electron"), require ("electron"), and preload imports.
- Installed wheel of HEAD: core_for_surface('cli') and core_for_surface('web') share Session and AgentRuntime classes, and rxycode web --help says not delivered. That run is in integration.txt after commit 403c8e4a.
- Cache plus team isolation: 51 passed, 2 skipped. See cache-isolation.txt. The skips are the pre-existing registry gap.
- protocol-client tsc --noEmit exited 0. See typecheck.txt.
- Desktop UI was not launched. Device connect is not implemented. No second agent loop. RiskLevel was not changed.
