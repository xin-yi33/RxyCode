# WEB-W6-C03 self-audit

Scope is the card whitelist plus the nested ruling for the empty browser package marker and the pyproject package entry.

- core/cu/browser.py was read. browser_open, browser_snapshot, and browser_act are still there. The file was not edited.
- tools/virtual_browser.py still registers browser_navigate, browser_snapshot, and browser_click. Those names were not rewritten.
- Agent and preview contexts use different persistent Chromium profiles on one Playwright driver. A second sync driver is not started.
- request_user_cookies does not read or copy the user Chrome directory. open_agent_context refuses a Chrome/Edge/Chromium/Brave User Data path, including after resolve() and realpath(), and a junction whose own name does not contain those words.
- The handoff button's onClick awaits window.rxyAuthorizeHandoff. present_handoff exposes that function, and click_handoff clicks the bundled shipped component. The test does not call authorize_handoff itself. continue_session stays refused until that click.
- The contract page token is not in the static HTML. It appears after a real click navigates to /done.
- E2E-BROWSER-01 ran inside test_w6_c03_integration: navigate https://example.com/, click a, snapshot contained iana.org. The planted Chrome secret was not in the snapshot or the agent Cookies file. There is no separate harness.
- A live jest binary was not run. gVisor was not involved. This card does not say 已落实.
- Cache: 30 passed, 2 skipped. The skips are the pre-existing global test registry messages at tests/test_cache/test_stable_prefix.py:142 and :158.
- ruff check on the new Python files passed.
- First gpt-6-luna max audit (w6c03-audit-1.json) returned VERDICT: PROBLEMS. The button had no handler, and the profile check did not resolve symlinks or junctions. This fix is the response. The re-audit has not returned a verdict yet.
