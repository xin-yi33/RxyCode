"""Catch up from the database when a Redis notify is lost."""

from __future__ import annotations

from rxycode_server.events.store import replay


def heartbeat_catchup(
    database_url: str,
    *,
    tenant_id: str,
    run_id: str,
    after_seq: int,
) -> list[dict]:
    """Poll the event rows. A missing notify does not cancel the run or skip seqs."""
    result = replay(
        database_url,
        tenant_id=tenant_id,
        run_id=run_id,
        after_seq=after_seq,
    )
    return list(result.get("events") or [])
