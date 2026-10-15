"""Keep a cancelling run active until the worker confirms it.

Revision ID: 002_cancel_active
Revises: 001_web_base
"""

from __future__ import annotations

from alembic import op

revision = "002_cancel_active"
down_revision = "001_web_base"
branch_labels = None
depends_on = None

_PREDICATE = "status IN ('pending', 'running', 'leased', 'cancel_requested')"
_PREVIOUS = "status IN ('pending', 'running', 'leased')"


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
