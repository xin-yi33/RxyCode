# WEB-W6-C04 handoff

Parent branch feat/rxycode-web. Not pushed.
Audit model for this card: gpt-6-luna, reasoning effort max.
Codex session stays 01a140a7-2cc1-7f61-bdab-2af627f08e80.
Latest product commit under audit: 95ad93ebdfcf482dcd1ab11d78333f3f780d9106.
Latest log: w6c04-audit-5.json. Last line: VERDICT: PROBLEMS.
The card is not closed. Do not check the four 完成判据.

Locked tests are green: unit 2 and module 1 call Coordinator.run_team, project_run, AgentWorker._handle_steer, and ChildSessionManager.cancel_session. E2E-TEAM-01 is the span round-trip in the integration test. No separate harness. Not claimed as 已落实.

Remaining audit findings:
- POST /steer writes steer.accepted and an outbox row. No worker consumes that row or calls accept_steer.
- POST /children/{session_id}/cancel writes child.cancel. No worker calls cancel_session for that id.
- The web reducer accepts event/agent_started and event/agent_done, but the run event log does not persist those notifications, so ChatPage does not receive the team projection from a live run.
