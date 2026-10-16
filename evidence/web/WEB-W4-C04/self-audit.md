# WEB-W4-C04 self-audit

- RED: rxycode_runner.transport was missing. 3 failed in 0.34s. See red.txt.
- `rxycode connect` binds the local tool body when the device has none. The worker calls dispatch_device_call.
- Tool replies are queued per call id, so two in-flight calls do not read each other's frames.
- Tool frames travel on the paired outbound device socket. The runner does not open a second listen port.
- The journal attempt is derived from device id and call id, so a later attempt id cannot run that call again.
- A completed call_id is reserved again through RemoteJournalAdapter and the original result is returned. The write runs once.
- Chunks are packed by UTF-8 bytes. The client acks each chunk so a result longer than two chunks can finish.
- A result whose ack never arrives stays pending. The journal reports that as unknown, the retry is recovery_required, and the file is not written again.
- Cancel before the write returns sets the in-flight flag and does not append another write.
- Stdout larger than 4096 bytes is split with sequence numbers. Two chunks can leave before an ack. After the socket drops, resume replays only later sequence numbers. The write still ran once.
- Outbound frames for one socket are sent by one writer task.
- Cache tests: 30 passed, 2 skipped in 2.03s. The skips are the existing global tool-registry skips. core/ was not edited.
- Not claimed as 已落实. E2E-FULL-04 stays BLOCKED.
