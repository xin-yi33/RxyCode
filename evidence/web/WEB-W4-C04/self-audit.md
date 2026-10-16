# WEB-W4-C04 self-audit

- RED: rxycode_runner.transport was missing. 3 failed in 0.34s. See red.txt.
- A completed call_id is reserved again through RemoteJournalAdapter and the original result is returned. The write runs once.
- A result whose ack never arrives stays pending. The journal reports that as unknown, the retry is recovery_required, and the file is not written again.
- Cancel before the write returns sets the in-flight flag and does not append another write.
- Stdout larger than 4096 bytes is split with sequence numbers. Two chunks can leave before an ack. After the socket drops, resume replays only later sequence numbers. The write still ran once.
- Outbound frames for one socket are sent by one writer task.
- Cache tests: 30 passed, 2 skipped in 2.03s. The skips are the existing global tool-registry skips. core/ was not edited.
- Not claimed as 已落实. E2E-FULL-04 stays BLOCKED.
