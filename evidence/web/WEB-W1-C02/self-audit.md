# WEB-W1-C02 self-audit

- RunContext fields are the nine frozen names. run_id is minted with uuid4. The client mapping is not copied.
- from_authenticated ignores the claimed body. A forged tenant_id stays out. api_key and device_token on the authenticated mapping raise ValueError. Those secrets are not stored.
- Session.open_run forces session_id to the existing Session and does not construct a new Session. Session.prompt accepts run_context and keeps the old arguments working. emit is unchanged.
- bind_prompt_context still accepts the old session_id and tui arguments and also stores an optional RunContext in a ContextVar. reset_prompt_context clears it. No os.chdir.
- pyproject.toml registers rxycode_protocol. The nested card table names that file and appserver/agent_worker.py. Nested commit 746885d.
- appserver/agent_worker.py builds the run with server_run_context(session_id, claimed=params). Client run_id and tenant_id are not copied. Session.prompt receives that same object. When run_context is set, emitted notifications use its run_id.
- Session.prompt binds the contextvar for the turn and resets it in the existing finally. bind_prompt_context also binds it, and mints a server context when the caller omits one.
- A checkout that has not installed the package inserts packages/rxycode-protocol/src only after ImportError. The installed-wheel test does not do that. It archives HEAD, installs the wheel, and checks both module files live under the venv.
- The module test calls ToolOrchestrator.execute_tool twice concurrently. Each task binds its own RunContext. The tool reads current_run_context. tool_orchestrator.py stays unedited because it is not on the card whitelist.
- Cancel propagation past the existing Session.interrupt path was not changed. That is not a pass.
- Protocol schema tests passed. No JSON-RPC method was added. TS codegen was not run. That is not a protocol-pass claim.
- Desktop UI was not run. The card has no UI E2E.
- Cache: 30 passed, 2 skipped. The skips are the pre-existing missing tool registry. core/session.py behavior other than open_run and the optional prompt argument was not changed.
- Prompt emits a pre-existing DeprecationWarning for __package__ != __spec__.parent. The same warning appears in tests/test_core/test_session.py::test_session_prompt_binds_workspace_for_tools. This card did not change those imports.
