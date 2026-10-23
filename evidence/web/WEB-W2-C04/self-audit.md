# WEB-W2-C04 self-audit

- append_event locks the run and writes the next seq plus one outbox row in the same transaction.
- GET /api/v1/runs/{id}/events?after_seq=40 returns SSE ids 41 and 42 once. A later request with after_seq=41 returns only 42 even if Last-Event-ID is 0, because the explicit query wins.
- replay returns CURSOR_EXPIRED and no events when the cursor is older than the oldest retained seq. It does not send the latest payload.
- A different tenant's GET is 404 and does not contain the event payload.
- follow_after_subscribe runs the gap callback after subscribe and before the database read, so seq 43 is included. heartbeat_catchup reads that seq from PostgreSQL when no Redis message was published. The run stays pending.
- Nested whitelist is d65bbf2. The parent commit does not track the embedded plan repository.
