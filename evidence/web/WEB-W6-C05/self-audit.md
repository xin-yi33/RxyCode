# WEB-W6-C05 self-audit

- usage_statement sums UsageRecord rows for the signed-in tenant. Model and day filters narrow those rows. cost_kind uses the existing price table.
- Memory and notices are selected by tenant. Tenant B does not receive tenant A's body. A foreign session cannot be scheduled.
- create_web_schedule uses ScheduleService.create for the rule, then stores the job in Postgres. fire_due_schedules writes a Run, run.created, and a pending outbox row. Each job commits on its own.
- commit_terminal calls notify_run_terminal after a successful lease update. A second commit is LeaseRejected. One notice remains.
- publish_run_status does not replace a different terminal status. Unsubscribe suppresses the next notice.
- MemoryPage posts, edits, and deletes with x-csrf-token. Bodies render as text. memoryMarkup escapes HTML.
- The web lifespan calls fire_due_schedules. That loop is not the appserver process.
- No live jest binary.
- w6c05-audit-4.json ends VERDICT: NO_REMAINING_PROBLEMS.
