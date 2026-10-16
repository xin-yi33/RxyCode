# WEB-W3-C07 self-audit

- RED: RunStatusBanner.tsx was missing. 3 failed in 0.89s. See red.txt.
- The run page mounts RunStatusBanner. 打开审批 opens a dialog, Tab stays inside it, and Escape returns focus to that button.
- When the run request fails, the page shows an alert with 重试 instead of a blank screen.
- At 375px the run page shows status, 批准, and 取消, without a horizontal scrollbar.
- Status text is the server status, not color alone. 取消 asks the server for cancel_requested and does not mark the run succeeded. A second click stays cancel_requested. The status, event, and outbox row commit together.
- 重试 reloads the page so useRunEvents starts again.
- The integration test checks 375, 768, and 1440, and axe-core reports no serious or critical violations.
- gpt-6-luna max in session 01a140a7-2cc1-7f61-bdab-2af627f08e80 returned VERDICT: NO_REMAINING_PROBLEMS on d6b8f351.
- Not claimed as 已落实. E2E-WEB-06 screenshot files are not produced.
