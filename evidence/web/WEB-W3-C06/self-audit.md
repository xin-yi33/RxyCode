# WEB-W3-C06 self-audit

- RED: ApprovalCard.tsx was missing. See red.txt.
- The card reads GET /api/v1/runs/{id}/approvals and shows the server tool, path, and deadline.
- 批准 and 拒绝 POST that same approval id and revision. A 409 shows 冲突 and does not mark the run succeeded.
- While the POST is still open, the page does not say succeeded. The server decision is approved or pending, not succeeded.
- Plan, todo, and agent rows come from the existing event reducer. Artifacts come from the artifact list API.
- Not claimed as 已落实. WEB-W1 CW03 and CW04 stay open. Device connect is not implemented.
