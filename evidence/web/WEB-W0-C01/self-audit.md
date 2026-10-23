# WEB-W0-C01 self-audit

The shipped scanner is `docs/plans/opus5-plan/rxycode -web/scripts/check_plan.py`.
`test_w0_c01_contract` calls `scan_contract` on the real plan directory.
`test_w0_c01_negative` calls `authority_status` on a missing path and on the real DEV-ORDER.
`test_w0_c01_integration` calls `tracking_status` on the real repository.

Red run failed because those functions did not exist (`evidence/web/WEB-W0-C01/red.txt`).
Green run: unit 2 passed, integration 1 passed, static audit errors=0.

`.gitignore` re-includes only `docs/plans/opus5-plan/rxycode -web/`. The RAR, `.env`, and the old `rxycode/` tree stay ignored.

`docs/plans/opus5-plan` is an embedded git repository, so the parent repository cannot store those Markdown blobs. The Web files are untracked and not ignored inside that repository. This is recorded in `16-DOC-AUDIT-CHANGE-CONTROL.md` §4.1.
