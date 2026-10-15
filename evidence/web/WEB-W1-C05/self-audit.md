# WEB-W1-C05 self-audit

- core_for_surface("cli" | "opentui" | "desktop" | "web") returns one Session class, one AgentRuntime class, and one ToolOrchestrator class. The unit test asserts those are the objects in core.session, core.agents.runtime, and the worker helper.
- session_type_for_worker() is what bind_core_session and the interrupt path construct. It calls core_for_surface("desktop").
- rxycode --help still lists gui, config, and --model. rxycode web --help says the entry is not delivered and lists connect. rxycode web connect --help says device connect is not implemented. Running connect raises ClickException and does not start a device.
- browser_entry_status returns BLOCKED when source imports electron or a preload path. frontend/protocol-client/src/webTransport.ts has neither. index.ts exports the reserved adapter.
- The unrelated desktop executable filter in main.py stays unstaged.
- Desktop UI was not launched. Cache and protocol schema tests were not required because this card does not change core/ tool selection or the protocol schema. No second agent loop. RiskLevel was not changed.
