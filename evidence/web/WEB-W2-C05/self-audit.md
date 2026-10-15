# WEB-W2-C05 self-audit

- RED, before the modules existed: collection failed with `No module named 'rxycode_worker.checkpoints'` and `No module named 'rxycode_worker.recovery'`. See red.txt.
- A pure-read node is stored with AsyncPostgresSaver. A second Python process calls resume_readonly and gets that snapshot. Run A keeps `alpha-snapshot` and run B keeps `beta-snapshot`. The side node does not create the marker file.
- Graph thread ids are `rxy:{len}:{session}:{len}:{run}`, so two runs do not share a graph.
- On Windows, psycopg async cannot use ProactorEventLoop. The saver work runs on a selector loop. The checkpoint is still PostgreSQL; the subprocess reads it back.
- Remote call ids use the existing journal. pending is reported as unknown. A second call id with the same shell arguments stays uncertain. completed is reused and is not executed again.
- A corrupt journal raises ToolJournalCorruptionError. recover_unknown_shell does not start the shell.
- The integration test runs pwsh Add-Content once, skips the ACK, then recover_unknown_shell. The file still contains one `shell-write`. runs.status becomes recovery_required. tool_invocations.journal_state is unknown.
- accept_run calls the effect only after AsyncPostgresSaver.setup and a read succeed. A closed port returns recovery_required and does not create the marker.
- execution/tool_orchestrator.py is not on this card's whitelist. WRITE/DANGER already reserve before the external action. This card's remote path is RemoteJournalAdapter, and recover_unknown_shell reserves again before any retry.
- Cache files: 30 passed, 2 skipped. Those skips are the existing "no tools registered in global test registry" marks in test_stable_prefix.py. This card did not add them.
- Nested whitelist is e8aa3d8. Parent code is 12662832. Neither branch is pushed.
- Not claimed as 已落实. WEB-W1 CW03 and CW04 stay open. Device connect is not implemented.
