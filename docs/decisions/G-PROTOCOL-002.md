# G-PROTOCOL-002 · PhaseG-B3 process lifecycle

```yaml
protocol_change:
  request_id: G-PROTOCOL-002
  producer: appserver
  consumers:
    - frontend/protocol-client
    - frontend/desktop-app
    - opentui
    - linkagent
  current_schema_version: "1.1.0"
  change_kind: new_event
  method_or_event: "event/process_started | event/process_shutdown | event/process_failed | event/recovery_required"
  compatibility: "Additive notifications. No existing field removed or redefined."
  generated_types: "cd frontend/protocol-client && bun run generate"
  fixtures:
    success: tests/test_appserver/test_b3_lifecycle.py::test_process_started_on_run
    denied: tests/test_appserver/test_b3_lifecycle.py::test_start_fails_when_instance_in_use
    timeout: "none (watchdog already emits TIMEOUT)"
    reconnect: tests/test_appserver/test_b3_lifecycle.py::test_restart_recovers_running_task
  migration: none
  rollback: revert this card commit
  owner: composer-2.5
```

单实例策略：每个 data dir 一把锁。活着的持有者不会被后到进程杀掉。未完成 turn 重启后只能是 `recovery_required`，禁止写成 succeeded。
