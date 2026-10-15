"""Web business tables.

Revision ID: 001_web_base
Revises:
"""

from __future__ import annotations

from alembic import op

revision = "001_web_base"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    from rxycode_server.persistence.models import apply_web_schema

    apply_web_schema(op.get_bind())


def downgrade() -> None:
    from rxycode_server.persistence.models import drop_web_schema

    drop_web_schema(op.get_bind())
