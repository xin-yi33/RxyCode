# WEB-W2-C06 self-audit

- RED, before the package existed: collection failed with `No module named 'rxycode_server.approvals'`. See red.txt.
- `class JsonRpcApproval` is unchanged. The legacy broker still waits on the JSON-RPC client.
- request_approval writes the approval row, `approval.requested`, and the outbox in one transaction, sets the run to `waiting_approval`, and clears the worker lease. The partial unique index includes `waiting_approval`, so the same session cannot start a second run.
- list_pending the next day still returns the original tool and permission_scope.
- An expired or cancelled approval raises ApprovalStale with HTTP 409 and code APPROVAL_STALE. resume_approved does not run the shell.
- A full_auto run does not create a per-call ask and pause_for_approval does not run the tool.
- pause_for_approval stops on a LangGraph interrupt before the effect node. The shell file does not exist until resume_approved. After approve, the first resume runs bash once through ToolOrchestrator. A second process sees the completed journal and does not run it again.
- Nested whitelist is 390e8fc. Parent code is 3abc977d. Neither branch is pushed.
- Not claimed as 已落实. WEB-W1 CW03 and CW04 stay open. Device connect is not implemented.
