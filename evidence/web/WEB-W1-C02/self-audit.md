# WEB-W1-C02 self-audit

- RunContext fields are the nine frozen names. run_id is minted with uuid4. The client mapping is not copied.
- from_authenticated ignores the claimed body. A forged tenant_id stays out. api_key and device_token on the authenticated mapping raise ValueError. Those secrets are not stored.
- Session.open_run forces session_id to the existing Session and does not construct a new Session. Session.prompt accepts run_context and keeps the old arguments working. emit is unchanged.
- bind_prompt_context still accepts the old session_id and tui arguments and also stores an optional RunContext in a ContextVar. reset_prompt_context clears it. No os.chdir.
- The module test calls ToolOrchestrator.execute_tool twice concurrently. Each task binds its own RunContext. The tool reads current_run_context. This card does not edit tool_orchestrator.py because that file is not on the card whitelist.
- Cancel propagation past the existing Session.interrupt path was not changed. That is not a pass.
- Protocol schema tests passed. No JSON-RPC method was added. TS codegen was not run. That is not a protocol-pass claim.
- Desktop UI was not run. The card has no UI E2E.
- Cache: 30 passed, 2 skipped. The skips are the pre-existing missing tool registry. core/session.py behavior other than open_run and the optional prompt argument was not changed.
- Prompt emits a pre-existing DeprecationWarning for __package__ != __spec__.parent. The same warning appears in tests/test_core/test_session.py::test_session_prompt_binds_workspace_for_tools. This card did not change those imports.
