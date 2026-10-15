# WEB-W0-C03 self-audit

test_w0_c03_contract calls reuse_or_create_session.
test_w0_c03_integration calls notification_to_sse_event, FinalAnswer, and RecoveryStarted, then checks protocol/schema.json.
test_w0_c03_negative calls baseline_file_status.
The first run failed only the negative test, because the helper did not exist yet. Contract and integration were already green. red.txt keeps that.
Cache regression is cache.txt. Two skips are pre-existing.
