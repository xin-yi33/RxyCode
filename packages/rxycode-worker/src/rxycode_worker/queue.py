"""Publish pending outbox rows to a Redis stream. A failed publish stays pending."""

from __future__ import annotations

from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool


def dispatch_pending(database_url: str, client, *, stream: str = "rxycode:runs") -> int:
    """Send each pending outbox row once. A transport error increments attempts only."""
    engine = create_engine(database_url, poolclass=NullPool)
    sent = 0
    try:
        with engine.begin() as conn:
            rows = conn.execute(
                text(
                    """
                    SELECT o.id, o.event_id, e.run_id, e.seq, e.type
                    FROM outbox o
                    JOIN run_events e ON e.event_id = o.event_id
                    WHERE o.dispatch_status = 'pending'
                    ORDER BY e.seq
                    FOR UPDATE OF o
                    """
                )
            ).all()
            for row in rows:
                try:
                    client.xadd(
                        stream,
                        {
                            "event_id": row.event_id,
                            "run_id": row.run_id,
                            "seq": str(row.seq),
                            "type": row.type,
                        },
                    )
                except Exception:
                    conn.execute(
                        text("UPDATE outbox SET attempts = attempts + 1 WHERE id = :id"),
                        {"id": row.id},
                    )
                    continue
                conn.execute(
                    text("UPDATE outbox SET dispatch_status = 'sent' WHERE id = :id"),
                    {"id": row.id},
                )
                sent += 1
    finally:
        engine.dispose()
    return sent
