# G-PROTOCOL-014 · PhaseG-B16 schedule

```yaml
protocol_change:
  request_id: G-PROTOCOL-014
  producer: appserver
  consumers: [frontend/protocol-client, frontend/desktop-app, opentui, linkagent]
  current_schema_version: "1.1.0"
  change_kind: new_method
  method_or_event: "schedule/list|create|update|delete|toggle"
  compatibility: "Additive. Application-layer asyncio scheduler. No OS cron/launchd/Task Scheduler. Execution uses B5 Thread + B7 permission."
  generated_types: "cd frontend/protocol-client && bun run generate"
  fixtures:
    success: tests/test_schedule.py
  migration: none
  rollback: revert this card commit
  owner: composer-2.5
```
