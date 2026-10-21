"""email verification codes (register/login/reset)

6-digit codes for register, code-login and password-reset — only the HMAC
digest of ``{purpose}:{email}:{code}`` is stored. ``user_id`` is nullable so
register codes can exist before the account does.

Revision ID: 008_email_codes
Revises: 007_password_resets
Create Date: 2026-10-21
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "008_email_codes"
down_revision = "007_password_resets"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if "email_codes" in set(sa.inspect(op.get_bind()).get_table_names()):
        return
    op.create_table(
        "email_codes",
        sa.Column("code_hash", sa.String(length=128), primary_key=True),
        sa.Column("purpose", sa.String(length=16), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("user_id", sa.String(length=64), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_email_codes_purpose_email", "email_codes", ["purpose", "email"]
    )


def downgrade() -> None:  # pragma: no cover - forward-only, matching earlier migrations
    pass
