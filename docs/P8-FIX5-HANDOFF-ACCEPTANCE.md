# P8 / FIX5 Handoff Acceptance

This document records the post-1.4.2 completion of the FIX5-to-P8 handoff. It
is intentionally separate from the frozen 1.4.2 release notes and audit.

## Gap

FIX5 already persisted the authoritative `protocol.todo.TodoSnapshot` through
the existing session `tasks.json` ledger and rendered it through the status
band. The timeout decision protocol already had a `progress: str` field and
`core.timeout_decision.todo_progress_snapshot`, but the four production
evidence construction paths still supplied `progress=""`. The prior Phase P8
composition test projected an in-memory snapshot into a test factory, so it did
not prove that a real decision consumer read the ledger.

## Minimal implementation

- Reuse `tools.todo_events.read_todo_snapshot`, its existing `tasks.json` reader, and
  the authoritative `protocol.todo` schema.
- Add `todo_progress_for_session` beside that reader. It reads on every call,
  checks session/root/list/scope identity and revision validity, and returns
  the existing deterministic item projection. Missing, empty, malformed, or
  cross-scope data produces empty progress.
- Wire the helper immediately before evidence reaches the timeout engine in
  pipeline, graph watchdog, ToolOrchestrator tool timeout, and AppServer stall
  recovery. The fail-closed interrupt-stop evidence uses the same read.
- No new store, protocol type, `latest` fallback, cached-band substitution,
  Todo-summary LLM call, timeout default, grant/cost rule, safety rule, or
  shell-internal clock behavior was added.

## Red / green evidence

The initial five-test real-consumer subset was first run before the production wiring:

```text
python -m pytest tests/test_timeout/test_todo_progress_snapshot.py -q --tb=short -p no:cacheprovider
5 failed in 1.77s
```

After wiring, that initial subset passed:

```text
5 passed in 1.59s
```

The expanded suite now has eleven test cases. It uses `todo_write` to create
the on-disk ledger and captures the actual engine evidence for all four
production paths. It also covers the five-state projection, empty/malformed
handles, latest revision, unchanged files, sibling/child isolation, an
anonymous graph bucket, a rebuilt appserver consumer, the fallback stop
evidence constructor, explicit non-Todo graph progress, and zero Todo-summary
calls.

## Verification commands

```text
python -m pytest tests/test_timeout/test_todo_progress_snapshot.py -q --tb=short -p no:cacheprovider
python -m pytest tests/test_timeout tests/e2e/phase_p/test_e2e_p_08_full_composition.py -q --tb=short -p no:cacheprovider
python scripts/count_lazy_imports.py --budget 181
python -m ruff check core/timeout_decision.py core/agent_v2.py core/graph.py execution/tool_orchestrator.py appserver/server.py tools/todo_events.py tests/test_timeout/test_todo_progress_snapshot.py
```

Observed targeted results: `5 passed`, `42 passed`, `lazy_import_total=180
budget=181`, and Ruff passed. The current expanded results are `11 passed` for
the new regression, `48 passed` for timeout plus P8 composition, `11 passed`
for all `tests/e2e/phase_p`, and `102 passed` for the FIX5/status-band
regressions. The original P8 composition test remains in the suite; the new
test is the production-consumer acceptance layer.

## Independent final acceptance

On 2026-10-09 the main reviewer ran:

```text
python scripts/run_phase1_pytest.py --workers 2 --verbose --junit-dir artifacts/p8-handoff/full-junit
exit 0
```

The five layers passed as `unit231`, `integration7`, `contract873`, `serial8`,
and `legacy12344`: `13463 passed`, `28 skipped`. The separate P8 focused
regression passed `112` cases with no skips and is not counted again above.
The 28 skips are baseline only: 26 ignored plan-tree tests, one explicit live
test, and one duplicate-query test; this handoff added no skip. Whole-repo
Ruff, `lazy_import_total=180 budget=181`, CR-at-EOL whitespace, and secret
scan checks also passed. Logs are in `artifacts/p8-handoff/full-layers.log`,
`artifacts/p8-handoff/focused.log`/XML, and the five-layer JUnit directory.
This completes the P8 follow-up acceptance, but does not close the complete
Phase P or any other card exit without its own recorded acceptance.

## Remaining boundaries

The timeout decision feature remains default-off. Todo progress is self-
reported plan state and never proves a write, tool result, budget, journal
completion, or final verification. Full Phase P and release-wide CI remain
independent integration gates owned by the main review.
