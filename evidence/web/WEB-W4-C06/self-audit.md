# WEB-W4-C06 self-audit

- RED: emergency and audit modules were missing. 3 failed in 0.31s. See red.txt.
- ProcessSupervisor puts each spawned process in a Windows job while it is still suspended, then resumes it. TerminateJobObject ends that process and the children it starts. This job is only a kill tree. It is not a sandbox.
- press_local_hotkey and EmergencyStop.press kill the tree before they talk to the cloud. A failed cloud ack is still a successful local stop, and the audit line keeps the cloud error.
- After the stop, spawn returns started false.
- AuditLog replaces sk- tokens and the clipboard field. The note text stays.
- Not claimed as 已落实. E2E-FULL-06 stays BLOCKED. A visible tray icon is not claimed.
