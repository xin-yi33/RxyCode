# WEB-W5-C01 self-audit

- RED: the sandbox package did not exist. 3 failed in 0.53s with ModuleNotFoundError: rxycode_runner.sandbox. See red.txt.
- Unit: 2 passed in 6.23s. Module: 1 passed in 1.12s. No skip.
- Contract calls GVisorSandbox.create and SandboxControl.sandboxd_exec. The tool argv is `python -c ...` passed only as `docker exec` arguments. An independent `docker exec` read `/tmp/proof.txt` back out of that container. The host marker file was not created. The printed hostname was `rxy-isolated`, not the Windows host name.
- docker inspect of that container: not privileged, network none, mounts empty, tenant and workspace labels match tenant A. The selected runtime is runc because `docker info` has no runsc. This host did not run gVisor.
- Closing a retained run leaves the container running. stop then destroy removes it. A second sandbox with retain false is removed by close_run. Ledger kinds include start, bill, and destroy.
- A new GVisorSandbox instance reads ownership from container labels. Tenant B attach and sandboxd_exec raise AttachRefused. Tenant A still sees the sandbox running.
- Integration selects runsc when it is absent (this host) and otherwise a runtime class the daemon does not list. sandboxd_exec raises ToolBlocked. The message contains "unavailable" and the target is `cloud:tenant-a:<workspace>`. No container with that workspace label was created. The host marker was not written. The ledger records blocked and does not record start.
- The only subprocess in the adapter is the docker CLI. There is no host fallback for the tool argv.
- No independent UI E2E. core/ was not touched. RiskLevel was not changed. Not claimed as 已落实.
- Nested ruling dd1602dc90dfa77fba07c26af43dd3e1093ebf40 names the package markers, exec, and the fail-closed runtime choice.
- gpt-6-luna max, session 01a140a7-2cc1-7f61-bdab-2af627f08e80. Final log w5c01-audit-1.json. Last line: VERDICT: NO_REMAINING_PROBLEMS.
