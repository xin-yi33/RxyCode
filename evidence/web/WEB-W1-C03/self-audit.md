# WEB-W1-C03 self-audit

- ExecutionPort, Capabilities, and ToolSpec live in rxycode_core.runtime. ToolSpec.allows_execute always returns False. A declaration does not authorize a call.
- A bound port rejects screenshot when the named target lacks desktop. The tool coroutine does not run. The same call is allowed when the target has desktop, and that path calls NativeBackend only after ToolOrchestrator has authorized the task.
- NativeBackend.invoke outside the orchestrator returns BLOCKED and does not run the supplied callable.
- apply_mcp_hint never lowers RiskLevel. Unknown annotated MCP stays at least WRITE. destructiveHint raises to DANGER. readOnlyHint does not make the gate READ. The module test drives execute_tool with safety enabled and no approval broker.
- The native-dispatch grant is a mutable object. Closing it is visible to child tasks that copied the context. A task created during read and released after execute_tool returns is BLOCKED.
- bash, read, edit, write, and patch, plus any tool with a bound ToolSpec, call NativeBackend.ainvoke. The tool body is the runner. Sync executor submissions copy the current context. A synchronous tool that calls NativeBackend receives OK only inside that call.
- Capabilities and ToolSpec round-trip through to_dict/from_dict. Version 0 and empty capability names raise ValueError.
- The wheel probe archives HEAD, not the dirty working tree. integration.txt is the run after commit b3c03972.
- pyproject.toml lists rxycode_core.runtime. The installed-wheel probe imports ExecutionPort from the venv. The nested card table names the new __init__.py and pyproject.toml.
- RiskLevel integer values were not changed. Cache: 30 passed, 2 skipped, the same pre-existing registry skips. Protocol schema: 7 passed. No JSON-RPC method was added. TS codegen was not run. That is not a pass of a TypeScript client change.
- Desktop UI was not run. The card has no UI E2E. Existing cancellation inside _invoke_and_finish still raises CancelledError after _finish. This card did not add a new cancel path.
