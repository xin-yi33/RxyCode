# WEB-W6-C01 self-audit

- RED: capability catalog missing, and select_tools rejected target. 3 failed in 0.39s. See red.txt. Parent HEAD at RED was b6fb9ca2.
- Unit: 2 passed in 0.77s. Module: 1 passed in 0.35s. No skip. See unit.txt and integration.txt.
- Cloud selection with profile full keeps read and drops click and type_text. The report says the cloud target does not expose local desktop input.
- Inventory rows carry tool_name, capability, target, risk, timeout, and idempotent. click is desktop.input, local, DANGER, not idempotent. read uses the orchestrator stall table.
- A default PermissionPolicy denies click even when the local target declares desktop.input. The reason is the policy deny, not a missing capability.
- register_builtin_tools does not put click or type_text into the default orchestrator. read stays registered.
- Remote target declaring only fs.read keeps read and reports click unavailable because remote does not declare desktop.input.
- classify_mcp sends readOnlyHint through apply_mcp_hint. A new MCP tool stays WRITE. destructiveHint raises that tool to DANGER. Risk is not lowered to READ.
- Cache regression: 30 passed, 2 skipped. The skips say "no tools registered in global test registry" and are the existing stable-prefix conditions. See regression.txt.
- No separate UI E2E for this card. core/builtin_tool_registration.py was checked and not rewritten. Not claimed as 已落实.
- Audit 1 returned VERDICT: PROBLEMS because pyproject.toml did not ship rxycode_core.tools. The module test now builds a wheel with pip and checks the zip contains capability_catalog.py. The src path insert is not that check.
- gpt-6-luna max, session 01a140a7-2cc1-7f61-bdab-2af627f08e80. Final log w6c01-audit-2.json. Last line: VERDICT: NO_REMAINING_PROBLEMS.
