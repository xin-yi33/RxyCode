# WEB-W6-C03 self-audit

Scope is the card whitelist plus the nested ruling for the empty browser package marker and the pyproject package entry.

- core/cu/browser.py was read. browser_open, browser_snapshot, and browser_act are still there. The file was not edited.
- tools/virtual_browser.py still registers browser_navigate, browser_snapshot, and browser_click. Those names were not rewritten.
- Agent and preview contexts use different persistent Chromium profiles on one Playwright driver. A second sync driver is not started.
- request_user_cookies does not read or copy the user Chrome directory. open_agent_context refuses a path that is a Chrome/Edge/Chromium/Brave User Data directory.
- Handoff continues the same agent session only after authorize_handoff. continue_session before that returns refused.
- The contract page token is not in the static HTML. It appears after a real click navigates to /done.
- E2E-BROWSER-01 ran inside test_w6_c03_integration: navigate https://example.com/, click a, snapshot contained iana.org. The planted Chrome secret was not in the snapshot or the agent Cookies file. There is no separate harness.
- A live jest binary was not run. gVisor was not involved. This card does not say 已落实.
- Cache: 30 passed, 2 skipped. The skips are the pre-existing global test registry messages at tests/test_cache/test_stable_prefix.py:142 and :158.
- ruff check on the new Python files passed.
- Audit with gpt-6-luna max is the next step. No verdict is claimed in this file yet.
