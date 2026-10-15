# WEB-W2-C05 self-audit

- RED, before the modules existed: collection failed with `No module named 'rxycode_worker.checkpoints'` and `No module named 'rxycode_worker.recovery'`. See red.txt.
- First audit (same Codex session) returned VERDICT: PROBLEMS. The shell helpers ignored a dead database URL, a new attempt id could pass a pending entry, recovery_required ignored lease epoch, and the shell did not go through ToolOrchestrator.
- Fix 488b7dee: the worker must hold the current lease epoch; AsyncPostgresSaver must open before a new shell; every attempt for one run shares `remote_checkpoint_id`; bash runs through ToolOrchestrator.execute_tool with the remote call id on the journal binding. A stale epoch does not change the row and does not run the shell.
- Fix 54787481: lease time is sampled in Python after SELECT FOR UPDATE, so a lock wait that outlives the lease cannot write recovery_required. A blocked fresh attempt marks the run recovery_required. permission_mode comes from the run.created payload and is not forced to full_auto. confirm_all does not run the shell.
- A pure-read node is stored with AsyncPostgresSaver. A second Python process calls resume_readonly and gets that snapshot. Run A keeps `alpha-snapshot` and run B keeps `beta-snapshot`. The side node does not create the marker file.
- On Windows, psycopg async cannot use ProactorEventLoop. The saver work runs on a selector loop. The checkpoint is still PostgreSQL.
- The integration test uses the shipped bash tool inside the repo workspace. The journal complete call raises, which is the orchestrator's existing "side effect completed but ACK was not committed" path. A second attempt and a later recover do not append another `shell-write`. runs.status becomes recovery_required only for the owning epoch. tool_invocations.journal_state is unknown.
- A closed database URL does not create the shell file.
- Cache files: 30 passed, 2 skipped. Those skips are the existing "no tools registered in global test registry" marks in test_stable_prefix.py. This card did not add them.
- Nested whitelist: e8aa3d8 and 399f23e. Parent code: 12662832 then 488b7dee. Neither branch is pushed.
- Not claimed as 已落实. WEB-W1 CW03 and CW04 stay open. Device connect is not implemented.
