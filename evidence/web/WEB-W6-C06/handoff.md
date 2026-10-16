# WEB-W6-C06 handoff

Parent branch feat/rxycode-web. Not pushed.
Audit model: gpt-6-luna, reasoning effort max.
Codex session: 01a140a7-2cc1-7f61-bdab-2af627f08e80.
Audited parent commit: 02d8962efeaec2b51b645f60faebb58e368b22d6.
Audit verdict: VERDICT: NO_REMAINING_PROBLEMS (w6c06-audit-4.json).

red.txt is ModuleNotFoundError: No module named rxycode_server.release. 3 failed in 0.67s.
green.txt is pytest of the two C06 files after the journey module existed: 3 passed.

cloud_release_journey calls github_start, local_login, create_project, create_session,
WorkspaceProvision.import_repo, create_run, then claims the run through
rxycode_worker.supervisor.claim and executes its marker test through
rxycode_worker.recovery.run_shell_before_ack — the production leased-shell path
(lease view, checkpointer_ready probe, RemoteJournalAdapter state, ToolOrchestrator
plus bash_tool, permission_profile read from the run.created event). The shell writes
real tool_invocations rows. commit_terminal commits succeeded on the same epoch.
The artifact bytes are that journaled shell's stdout plus stderr, stored through
store_artifact and read back through open_download/read_download. replay runs twice.

import_repo received https://example.invalid/not-a-github-repo and a 40-zero revision.
The allowlist raises RepoRefused before any clone. The saved status is blocked, with
that exception text as the reason. No GitHub clone ran. No gVisor sandbox was launched.

The run's workdir and the Local Full workdir must sit inside execution.workspace_root
(the repo), matching the shipped sandbox rule; the tests use repo-local scratch dirs
like W4's _bash_c06 and remove them afterwards.

remote_full_unpaired builds the real device app (create_device_app), mints a real
session record, and POSTs /api/v1/devices/{id}/invocations through TestClient with a
bash + permission full payload. The production route raises the real 404 NOT_FOUND
for the unpaired device. remote-full.txt is never written.

local_full_journey binds a real ProcessSupervisor, installs a real GrantStore,
records the grant through confirm_from_local_ui, then runs _run_remote_full with
tool bash and permission full; the grant is evaluated through
store_for(device_id).evaluate before run_bash writes harmless.txt.

OnboardingPage renders journeyState(mode, authKind), where authKind is user.kind
from /api/v1/me. Local after login shows empty permission / local /
waiting_for_local_confirmation — the browser only sees the GrantMirror state, never
"full" itself. Cloud shows cloud / cloud / ready only when authKind is github;
a local session keeps cloud at needs-github. Remote shows empty permission /
remote / waiting_for_local_confirmation. Logged-out local shows needs-login.
Disconnect still shows the existing retry button.

apps/web/e2e/coding-workflow.spec.ts and remote-full.spec.ts were not executed.
apps/web has no Playwright dependency. playwright.config.ts keeps testDir at
tests/web/w3. Browser E2E for this card is BLOCKED.

docs/product/user-guide.md is version 1.4.3. No screenshots were captured.

No live jest binary. No gVisor.
