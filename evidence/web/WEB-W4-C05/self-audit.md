# WEB-W4-C05 self-audit

- RED: grant_store was missing. 3 failed in 0.19s. See red.txt.
- The runner stores a grant only when confirm_from_local_ui runs. A cloud request or a forged permission=full does not write that grant.
- Each full call checks session, run, capability, workspace, expiry, and revoke_epoch. A miss is recovery_required and an audit line. The command is not run.
- A covering grant runs shell through run_bash and click through click(). The approval sink is not called.
- An omitted workdir is the granted workspace for both the check and run_bash. A cancel flag set before that shell or click refuses the call.
- The browser component shows waiting_for_local_confirmation until the mirror is acked, then the device id and capabilities.
- Local full remains the existing native backend entry. This card's entry is the local confirm.
- gpt-6-luna max, session 01a140a7-2cc1-7f61-bdab-2af627f08e80. Final log w4c05-audit-2.json. Last line: VERDICT: NO_REMAINING_PROBLEMS.
- Not claimed as 已落实. E2E-FULL-05 stays BLOCKED.
