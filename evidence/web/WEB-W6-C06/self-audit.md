# WEB-W6-C06 self-audit

- The contract test calls cloud_release_journey. That function calls the shipped
  auth, project, run, artifact, and replay functions, and the run's work is executed
  through the real worker path: claim takes the fenced lease, run_shell_before_ack
  checks the lease view, the checkpointer, and the ToolExecutionJournal, then runs
  the command through ToolOrchestrator + bash_tool with the permission_profile
  stored on run.created. commit_terminal writes the terminal status on the same
  epoch. It does not return a hard-coded artifact or a hard-coded pytest exit.
- Import of a non-GitHub URL stops at RepoRefused. Status blocked is the recorded
  result. A successful clone is not claimed.
- Local Full goes through the real grant path: GrantStore installed per device,
  confirm_from_local_ui records the grant, _run_remote_full evaluates it before
  run_bash writes harmless.txt. The page markup comes from journeyMarkup through
  bun using the result that path returned.
- Remote Full without a paired device is refused by the real device route with a
  404 and does not write a file.
- The onboarding page shows permission and target from journeyState. After login,
  local reports the mirror status waiting_for_local_confirmation with empty
  permission; it does not claim full from session auth alone. Cloud reports ready
  only for a github-kind session.
- Cleanup deletes the project, session, run, events, outbox, artifact, and
  tool_invocations rows created for the journey. It does not delete the shared
  local user.
- MinIO is reused at 127.0.0.1:59000 when that port is healthy. The journey does
  not remove rxy-w2c07-minio.
- Browser specs under apps/web/e2e were not run. That path stays BLOCKED.
- No live jest binary. No gVisor.
- gpt-6-luna max audit of parent commit 02d8962efeaec2b51b645f60faebb58e368b22d6
  returned VERDICT: NO_REMAINING_PROBLEMS (w6c06-audit-4.json). Earlier passes
  returned PROBLEMS and each finding was fixed in a separate commit: 01d044f8
  (real worker lease), e49ea156 (leased worker shell + real grant store), 02d8962e
  (browser mirrors the on-device grant).
