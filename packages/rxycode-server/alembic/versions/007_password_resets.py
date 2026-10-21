"""password-reset tokens (WEB-W9-A1)

Single-use reset rows — only the HMAC digest of the emailed token is stored,
so a database read never yields a usable link.

Revision ID: 007_password_resets
Revises: 006_auth_and_runs
Create Date: 2026-10-22
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "007_password_resets"
down_revision = "006_auth_and_runs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if "password_resets" in set(sa.inspect(op.get_bind()).get_table_names()):
        return
    op.create_table(
        "password_resets",
        sa.Column("token_hash", sa.String(length=128), primary_key=True),
        sa.Column("user_id", sa.String(length=64), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_password_resets_user", "password_resets", ["user_id"])


def downgrade() -> None:  # pragma: no cover - forward-only, matching earlier migrations
    pass
