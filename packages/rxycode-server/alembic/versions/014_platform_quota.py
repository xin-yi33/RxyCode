"""Platform-funded free quota: ten pre-seeded grant slots.

``platform_grants`` reserves slots 1..10 at migration time (unclaimed,
``user_id NULL``) so the promise "first 10 registered users" is durable
from the start — the backfill script claims them for existing users in
``users.created_at`` order and registration claims the lowest open slot
for new users. ``tokens_used`` is the durable spend counter settled from
real run metering; the conditional ``LEAST(..., token_cap)`` update in
platform_quota.service keeps it at or below the cap.

All DDL is guarded so a partially-applied earlier attempt can be re-run;
slot seeding is ``WHERE NOT EXISTS``-guarded so re-running never
duplicates or clobbers a claimed slot.

Revision ID: 014_platform_quota
Revises: 013_feedback
Create Date: 2026-11-13
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "014_platform_quota"
down_revision = "013_feedback"
branch_labels = None
depends_on = None

_PLATFORM_MODEL_ID = "deepseek-v4.1-flash"
_PLATFORM_TOKEN_CAP = 10_000_000
_PLATFORM_SLOTS = 10


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _indexes(table: str) -> set[str]:
    return {i["name"] for i in sa.inspect(op.get_bind()).get_indexes(table)}


def _constraints(table: str) -> set[str]:
    return {c["name"] for c in sa.inspect(op.get_bind()).get_check_constraints(table)}


def upgrade() -> None:
    tables = _tables()

    if "platform_grants" not in tables:
        op.create_table(
            "platform_grants",
            sa.Column("id", sa.String(length=64), primary_key=True),
            sa.Column("slot_no", sa.Integer(), nullable=False),
            sa.Column(
                "user_id",
                sa.String(length=64),
                sa.ForeignKey("users.id"),
                nullable=True,
            ),
            sa.Column("tenant_id", sa.String(length=64), server_default="", nullable=False),
            sa.Column("model_id", sa.String(length=256), server_default="", nullable=False),
            sa.Column("token_cap", sa.BigInteger(), server_default="0", nullable=False),
            sa.Column("tokens_used", sa.BigInteger(), server_default="0", nullable=False),
            sa.Column("status", sa.String(length=16), server_default="active", nullable=False),
            sa.Column("granted_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
            sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
            sa.UniqueConstraint("slot_no", name="uq_platform_grants_slot"),
            sa.CheckConstraint(
                "slot_no >= 1 AND slot_no <= 10", name="ck_platform_grants_slot_range"
            ),
            sa.CheckConstraint("tokens_used >= 0", name="ck_platform_grants_used_nonneg"),
        )
    indexes = _indexes("platform_grants")
    # One grant per user — NULLs stay unclaimed. Partial unique index so
    # several open slots can coexist (a plain unique column would also
    # allow it in PG, but the partial form documents the intent).
    if "uq_platform_grants_user" not in indexes:
        op.create_index(
            "uq_platform_grants_user",
            "platform_grants",
            ["user_id"],
            unique=True,
            postgresql_where=sa.text("user_id IS NOT NULL"),
        )
    if "ix_platform_grants_open" not in indexes:
        op.create_index(
            "ix_platform_grants_open",
            "platform_grants",
            ["slot_no"],
            postgresql_where=sa.text("user_id IS NULL"),
        )

    # Reserve all ten slots durably. Deterministic ids keep re-runs safe;
    # a claimed row is never rewritten by the seed.
    bind = op.get_bind()
    for slot in range(1, _PLATFORM_SLOTS + 1):
        bind.execute(
            sa.text(
                "INSERT INTO platform_grants (id, slot_no, user_id, tenant_id, "
                "model_id, token_cap, tokens_used, status, granted_at) "
                "SELECT :id, :slot, NULL, '', :model, :cap, 0, 'active', now() "
                "WHERE NOT EXISTS (SELECT 1 FROM platform_grants WHERE slot_no = :slot)"
            ),
            {
                "id": f"pg_slot_{slot:02d}",
                "slot": slot,
                "model": _PLATFORM_MODEL_ID,
                "cap": _PLATFORM_TOKEN_CAP,
            },
        )


def downgrade() -> None:
    tables = _tables()
    if "platform_grants" in tables:
        for name in ("ix_platform_grants_open", "uq_platform_grants_user"):
            if name in _indexes("platform_grants"):
                op.drop_index(name, table_name="platform_grants")
        op.drop_table("platform_grants")
