# G-BACKEND-HANDOFF · Phase G 后端出口

```yaml
handoff_id: D-B-HANDOFF-001
card: PhaseG-B1-B18
source_baseline: PHASE-G-DESKTOP.md
branch: feat/phase-g-backend
commit: feat/phase-g-backend
protocol_version: "1.1.0"
verdict: READY_FOR_FULL_D_INTEGRATION
capabilities:
  - threads
  - thread_fork
  - thread_trash
  - multi_agent
  - approval.auto_review
  - settings
  - capabilities
  - recovery
  - schedule
  - cli_hub
  - plugins
fixtures:
  success: tests/test_threads/fixtures/h5-success.json
  denied: tests/test_approval/fixtures/b7-denied.json
  timeout: tests/test_threads/fixtures/h5-timeout.json
  reconnect: tests/test_threads/fixtures/h5-reconnect.json
  child_tree: tests/test_threads/fixtures/h5-child-tree.json
generated_types: frontend/protocol-client/src/generated/types.ts
tests: "card gates B1-B18 green; combined 512 passed; 3 pre-existing stdio watchdog TimeoutError; 1 live bootstrap skipped"
security_review: "workspace canonicalize; purge confirm_purge is True; plugin path/symlink/zip guards; crash redaction via settings.redact_text"
known_limitations:
  - "tests/test_appserver/test_stdio_integration.py three watchdog stall cases TimeoutError (pre-existing UTF-8 reader / session/prompt hang); not a B17/B18 regression"
  - "Phase B cache hit 91.22% < 99%; B15 generate remains BLOCKED_PREREQUISITE"
  - "GX2-GX18 enhancement cards are post-export; not part of B1-B18 construction cards"
  - "frontend H cards must consume this package; this document cannot mark full Phase G complete"
rollback: revert to 7ff77d8 then this handoff commit
owner: composer-2.5
```
