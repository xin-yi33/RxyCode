"""Single-device login lock (W11).

``device_locks`` holds one row per user naming the ``auth_sessions`` token
digest that currently owns the data plane. ``last_seen_at`` is the
keepalive — a lock idle past 10 minutes is implicitly released, so a dead
device can never strand the account. Guarded so it survives a
partially-applied earlier attempt.

Revision ID: 010_device_locks
Revises: 009_byok
Create Date: 2026-10-23
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "010_device_locks"
down_revision = "009_byok"
branch_labels = None
depends_on = None


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def upgrade() -> None:
    if "device_locks" not in _tables():
        op.create_table(
            "device_locks",
            sa.Column(
                "user_id",
                sa.String(length=64),
                sa.ForeignKey("users.id"),
                primary_key=True,
            ),
            sa.Column("token_hash", sa.String(length=128), nullable=False),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=True,
            ),
            sa.Column(
                "last_seen_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=True,
            ),
        )


def downgrade() -> None:  # pragma: no cover - forward-only, matching earlier migrations
    pass
