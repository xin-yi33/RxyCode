# WEB-W5-C02 self-audit

- RED: policy and egress were missing. 3 failed in 0.21s. See red.txt.
- Unit: 2 passed in 6.12s. Module: 1 passed in 2.52s. No skip.
- Contract launches a sandbox from sandbox-policy.yaml. The tool reads a host sentinel and another project path. Neither nonce appears. /etc/hostname inside the sandbox is rxy-isolated. inspect shows no mounts, not privileged, user 65534:65534. A host RXY_API_KEY is not in the container environment.
- A one-second ttl stops that sandbox. destroy removes it.
- Negative: privileged, docker.sock, and a host mount are refused before create. Inside a normal sandbox, a connect to 169.254.169.254 fails and /var/run/docker.sock is absent.
- Integration: tenant A with a 128m ceiling cannot allocate 256MB. Tenant B still prints tenant-b-alive. Raising memory above the yaml ceiling is refused.
- The adapter still uses runc. runsc is not installed. This is not a gVisor syscall run.
- No separate E2E-CLOUD-01 harness. The module test is the two-sandbox process check. core/ was not touched. Not claimed as 已落实.
- Nested ruling 581c1c4cf476110ef5c53989d18937759ea43afa lets gvisor.create apply SandboxPolicy.
- Audit w5c02-audit-1.json returned PROBLEMS: create accepted a policy above the yaml ceiling. create and launch now reject memory, cpu, pids, and ttl above that file. The negative test calls GVisorSandbox.create with those policies. Unit re-run: 2 passed in 6.73s.
- gpt-6-luna max, session 01a140a7-2cc1-7f61-bdab-2af627f08e80. Final log w5c02-audit-2.json. Last line: VERDICT: NO_REMAINING_PROBLEMS.
