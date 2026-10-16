# WEB-W3-C07 self-audit

- RED: RunStatusBanner.tsx was missing. 3 failed in 0.89s. See red.txt.
- The run page mounts RunStatusBanner. 打开审批 opens a dialog, Tab stays inside it, and Escape returns focus to that button.
- When the run request fails, the page shows an alert with 重试 instead of a blank screen.
- At 375px the run page shows status, 批准, and 取消, without a horizontal scrollbar.
- Status text is written in words, not by color alone.
- Not claimed as 已落实. E2E-WEB-06 screenshots and axe-core stay BLOCKED.
