# WEB-W2-C01 self-audit

- upgrade_head / downgrade_base call Alembic. env.py sets transaction_per_migration. The revision calls apply_web_schema / drop_web_schema.
- test_w2_c01_contract checks the fifteen business tables, uq_runs_tenant_request, and the partial index uq_runs_one_active_per_session. downgrade leaves the desktop task directory in place. A rolled-back apply_web_schema does not leave runs behind.
- test_w2_c01_negative rejects a second run with the same tenant_id and request_id, then rejects a second active run (pending/running/leased) on the same session. The count stays at the rows that committed.
- test_w2_c01_integration inserts the same project name in two tenants, calls seed_demo twice, and imports a DesktopTaskStore row through upsert and read_legacy_rows. tasks.json bytes do not change.
- test_w2_c01_installed_migration installs a wheel built from git archive HEAD and runs upgrade_head and downgrade_base with PYTHONPATH cleared. migrate.py and the Alembic directory resolve inside the venv.
- relationship() rows exist so one Session.commit inserts a parent before a child. organizations.tenant_id is the unique tenant key and is not the primary key, so those relationships name the primaryjoin.
- read_legacy_rows copies task dicts and does not call _save. The old JSON shape is unchanged.
- JSON files are not used as the cloud user store. RiskLevel is unchanged. No second agent loop.
- Parent commit 357b8a33 accidentally recorded the nested plan repository as a gitlink. ef3ad475 removes that gitlink. The whitelist amendments are nested commits f9a3ca5 and 5ac3f54, inside docs/plans/opus5-plan, and are not parent blobs.
- Codex returned VERDICT: PROBLEMS. 3812ad79 answers those four items: composite foreign keys keep a child in its parent's tenant; requirements.txt declares SQLAlchemy, Alembic, and psycopg; database URLs escape % before ConfigParser; the two package __init__.py files are on the whitelist.
- A session cannot reference another tenant's project, and a run cannot reference another tenant's session. The integration test inserts both and expects IntegrityError.
- Unrelated dirty files, including appserver/tui.py and the desktop launcher hunks, stay unstaged. See worktree-status.txt.
