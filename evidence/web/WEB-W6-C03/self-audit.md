# WEB-W6-C03 self-audit

Scope is the card whitelist plus the nested ruling for the empty browser package marker and the pyproject package entry.

- core/cu/browser.py was read. browser_open, browser_snapshot, and browser_act are still there. The file was not edited.
- tools/virtual_browser.py still registers browser_navigate, browser_snapshot, and browser_click. Those names were not rewritten.
- Agent and preview contexts use different persistent Chromium profiles on one Playwright driver. A second sync driver is not started.
- request_user_cookies does not read or copy the user Chrome directory. open_agent_context refuses a Chrome/Edge/Chromium/Brave User Data path, including after resolve() and realpath(), and a junction whose own name does not contain those words.
- The handoff button awaits onAuthorize and window.rxyAuthorizeHandoff. The UI stays unauthorized unless both that exist return true. A Promise that resolves false does not grant the session.
- present_handoff only mounts the page and exposes the bridge. It does not click. The integration test's own functions click the button. run_on_handoff_page runs that caller action.
- open_agent_context refuses to reuse one resolved profile path for both agent and preview, including a junction whose name does not say preview.
- The contract page token is not in the static HTML. It appears after a real click navigates to /done.
- E2E-BROWSER-01 ran inside test_w6_c03_integration: navigate https://example.com/, click a, snapshot contained iana.org. The planted Chrome secret was not in the snapshot or the agent Cookies file. There is no separate harness.
- A live jest binary was not run. gVisor was not involved. This card does not say 已落实.
- Cache: 30 passed, 2 skipped. The skips are the pre-existing global test registry messages at tests/test_cache/test_stable_prefix.py:142 and :158.
- ruff check on the new Python files passed.
- Later audits fixed the app route, foreign Chrome profiles, the same-origin token, and framing. w6c03-audit-7.json on commit 20189e28 ends with VERDICT: NO_REMAINING_PROBLEMS. Thread 01a140a7-2cc1-7f61-bdab-2af627f08e80.
