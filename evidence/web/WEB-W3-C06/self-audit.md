# WEB-W3-C06 self-audit

- RED: ApprovalCard.tsx was missing. See red.txt.
- The card reads GET /api/v1/runs/{id}/approvals and shows the server tool, path, and deadline.
- 批准 and 拒绝 POST that same approval id and revision. A 409 shows 冲突 and does not mark the run succeeded.
- While the POST is still open, the page does not say succeeded. The server decision is approved or pending, not succeeded.
- Plan, todo, and agent rows come from the existing event reducer. Artifacts come from the artifact list API.
- A waiting worker question is registered in the home mailbox for its session. The web answer is published only for that session, as one complete file, and the worker ask returns that answer.
- A second answer does not replace the first. The run is not marked succeeded by the click, the approval POST, or the question answer.
- gpt-6-luna max in session 01a140a7-2cc1-7f61-bdab-2af627f08e80 returned VERDICT: NO_REMAINING_PROBLEMS on 0d3bd5d8.
- Not claimed as 已落实. WEB-W1 CW03 and CW04 stay open. Device connect is not implemented.
- E2E-WEB-03 screenshots are not produced. That item stays BLOCKED.
