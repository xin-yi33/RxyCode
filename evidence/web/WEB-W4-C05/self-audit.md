# WEB-W4-C05 self-audit

- RED: grant_store was missing. 3 failed in 0.19s. See red.txt.
- The runner stores a grant only when confirm_from_local_ui runs. A cloud request or a forged permission=full does not write that grant.
- Each full call checks session, run, capability, workspace, expiry, and revoke_epoch. A miss is recovery_required and an audit line. The command is not run.
- A covering grant runs shell through run_bash and click through click(). The approval sink is not called.
- The browser component shows waiting_for_local_confirmation until the mirror is acked, then the device id and capabilities.
- Local full remains the existing native backend entry. This card's entry is the local confirm.
- Not claimed as 已落实. E2E-FULL-05 stays BLOCKED.
