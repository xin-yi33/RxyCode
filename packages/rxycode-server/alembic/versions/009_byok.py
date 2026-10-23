"""BYOK model credentials + per-run model snapshot (WEB BYOK backend).

``model_connections`` holds AES-256-GCM sealed user keys (ciphertext,
nonce, key_id, credential_version — never plaintext); ``user_models`` is
the per-user model catalogue keyed by ``model_ref``. ``runs`` gains the
immutable submission-time snapshot columns the worker resolves its
per-run model gateway from. All DDL guarded so it survives a
partially-applied earlier attempt.

Revision ID: 009_byok
Revises: 008_email_codes
Create Date: 2026-10-22
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "009_byok"
down_revision = "008_email_codes"
branch_labels = None
depends_on = None


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _columns(table: str) -> set[str]:
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns(table)}


def _indexes(table: str) -> set[str]:
    return {i["name"] for i in sa.inspect(op.get_bind()).get_indexes(table)}


def upgrade() -> None:
    tables = _tables()

    if "model_connections" not in tables:
        op.create_table(
            "model_connections",
            sa.Column("id", sa.String(length=64), primary_key=True),
            sa.Column(
                "tenant_id",
                sa.String(length=64),
                sa.ForeignKey("organizations.tenant_id"),
                nullable=False,
            ),
            sa.Column(
                "owner_user_id",
                sa.String(length=64),
                sa.ForeignKey("users.id"),
                nullable=False,
            ),
            sa.Column("provider_id", sa.String(length=64), nullable=False, server_default=""),
            sa.Column("provider_name", sa.String(length=128), nullable=False, server_default=""),
            sa.Column("display_name", sa.String(length=128), nullable=False, server_default=""),
            sa.Column("base_url", sa.String(length=512), nullable=False, server_default=""),
            sa.Column("api_transport", sa.String(length=32), nullable=True),
            sa.Column("ciphertext", sa.LargeBinary(), nullable=True),
            sa.Column("nonce", sa.LargeBinary(), nullable=True),
            sa.Column("key_id", sa.String(length=32), nullable=True),
            sa.Column("encryption_version", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("credential_version", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("state", sa.String(length=16), nullable=False, server_default="active"),
            sa.Column("test_status", sa.String(length=16), nullable=False, server_default="untested"),
            sa.Column("test_error", sa.String(length=256), nullable=True),
            sa.Column("tested_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=True,
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=True,
            ),
        )
        op.create_index(
            "ix_model_connections_tenant_owner",
            "model_connections",
            ["tenant_id", "owner_user_id"],
        )

    if "user_models" not in tables:
        op.create_table(
            "user_models",
            sa.Column("id", sa.String(length=64), primary_key=True),
            sa.Column(
                "tenant_id",
                sa.String(length=64),
                sa.ForeignKey("organizations.tenant_id"),
                nullable=False,
            ),
            sa.Column(
                "owner_user_id",
                sa.String(length=64),
                sa.ForeignKey("users.id"),
                nullable=False,
            ),
            sa.Column(
                "connection_id",
                sa.String(length=64),
                sa.ForeignKey("model_connections.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("model_id", sa.String(length=256), nullable=False),
            sa.Column("display_name", sa.String(length=256), nullable=False, server_default=""),
            sa.Column("max_tokens", sa.Integer(), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=True,
            ),
            sa.UniqueConstraint(
                "connection_id", "model_id", name="uq_user_models_connection_model"
            ),
        )

    if "users" in _tables() and "default_model_ref" not in _columns("users"):
        op.add_column(
            "users",
            sa.Column("default_model_ref", sa.String(length=64), nullable=True),
        )

    if "runs" in _tables():
        columns = _columns("runs")
        additions = {
            "model_ref": sa.String(length=64),
            "model_id": sa.String(length=256),
            "provider_id": sa.String(length=64),
            "provider_name": sa.String(length=128),
            "credential_source": sa.String(length=16),
            "connection_id": sa.String(length=64),
            "credential_version": sa.Integer(),
        }
        with op.batch_alter_table("runs") as batch:
            for name, column_type in additions.items():
                if name not in columns:
                    batch.add_column(sa.Column(name, column_type, nullable=True))


def downgrade() -> None:  # pragma: no cover - forward-only, matching earlier migrations
    pass
