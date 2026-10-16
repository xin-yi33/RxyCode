"""Keep a run that is waiting for approval as the session's active run.

Revision ID: 004_waiting_approval
Revises: 003_event_seq
"""

from __future__ import annotations

from alembic import op

revision = "004_waiting_approval"
down_revision = "003_event_seq"
branch_labels = None
depends_on = None

_PREDICATE = (
    "status IN ('pending', 'running', 'leased', 'cancel_requested', 'waiting_approval')"
)
_PREVIOUS = "status IN ('pending', 'running', 'leased', 'cancel_requested')"


def upgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_runs_one_active_per_session")
    op.execute(
        "CREATE UNIQUE INDEX uq_runs_one_active_per_session ON runs (session_id) "
        f"WHERE {_PREDICATE}"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_runs_one_active_per_session")
    op.execute(
        "CREATE UNIQUE INDEX uq_runs_one_active_per_session ON runs (session_id) "
        f"WHERE {_PREVIOUS}"
    )
