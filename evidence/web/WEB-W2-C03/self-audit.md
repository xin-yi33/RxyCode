# WEB-W2-C03 self-audit

- create_run inserts the Run, the first run_event, and one outbox row in one transaction, then returns HTTP 202 and status queued. The database status stays pending so the existing partial unique index applies.
- The same tenant and request_id with the same payload returns the same run id and does not insert a second row. A different payload raises RunConflict. A second request_id on that session raises RunAlreadyActive. A claimed tenant id in the call is ignored.
- claim is one UPDATE. Two threads racing it produce a single epoch 1. The loser gets None.
- The negative test starts a real process that claims the lease, kills that process, expires lease_until, and runs a second process. commit_terminal raises LeaseRejected and the row stays leased under epoch 1.
- dispatch_pending writes a Redis stream. A publisher that raises ConnectionError leaves the outbox pending and increments attempts. The retry publishes once. A second dispatch does not add another stream entry.
- attempt_tool calls ToolExecutionJournal.reserve. After a ConnectionError the journal entry stays pending, and the next call is uncertain without executing the tool again.
- Nested whitelist is fa7d5f4. The parent commit does not track the embedded plan repository.
- Codex first returned VERDICT: PROBLEMS. 719cadc0 stores the message and permission profile on the first event, includes session_id in the idempotency digest, compares lease time with clock_timestamp() at update time, refuses to rewrite a terminal status, renews the same epoch, and records cancel_requested once before confirm_cancel.
