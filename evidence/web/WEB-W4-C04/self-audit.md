# WEB-W4-C04 self-audit

- RED: rxycode_runner.transport was missing. 3 failed in 0.34s. See red.txt.
- `rxycode connect` binds local_tool on a journal directory that stays under the data dir for that device.
- `rxycode connect` installs SseApproval and publishes approval_request on the device socket. The browser tenant approves with POST /api/v1/devices/{id}/approvals/{approval_id}. Device bash goes through ToolOrchestrator with safety.enabled and confirm_all. workdir and timeout, including 0, are passed through. permission full is not used.
- The tool-lane read waits for the 120s approval window, the tool timeout, and 15s. An approval that arrives after 5 seconds still completes. If that read times out, the caller sends cancel and returns recovery_required. Cancel rejects only the approval published by that call's thread. A later approve does not append, and a second pending bash call keeps its own approval.
- Tool replies are queued per call id, so two in-flight calls do not read each other's frames.
- Tool frames travel on the paired outbound device socket. The runner does not open a second listen port.
- The journal attempt is derived from device id and call id, so a later attempt id cannot run that call again.
- A completed call_id is reserved again through RemoteJournalAdapter and the original result is returned. The write runs once.
- Chunks are packed by UTF-8 bytes. The client acks each chunk so a result longer than two chunks can finish.
- A result whose ack never arrives stays pending. The journal reports that as unknown, the retry is recovery_required, and the file is not written again.
- Cancel before the write returns sets the in-flight flag and does not append another write.
- Stdout larger than 4096 bytes is split with sequence numbers. Two chunks can leave before an ack. After the socket drops, resume replays only later sequence numbers. The write still ran once.
- Outbound frames for one socket are sent by one writer task.
- Cache tests: 30 passed, 2 skipped in 2.06s. The skips are the existing global tool-registry skips. core/ was not edited.
- Unit: 2 passed, 5 warnings in 17.63s. Module: 1 passed, 4 warnings in 1.35s. C03 unit and module after this bind fix: 3 passed, 10 warnings in 2.15s. Warnings are uvicorn and websockets.legacy.
- gpt-6-luna max, session 01a140a7-2cc1-7f61-bdab-2af627f08e80. Final log w4c04-audit-12.json. Last line: VERDICT: NO_REMAINING_PROBLEMS.
- Not claimed as 已落实. E2E-FULL-04 stays BLOCKED.
