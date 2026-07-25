"""Add the ruble wallet, product pricing modes and manual payment review.

Revision ID: 0005
Revises: 0004
Create Date: 2026-07-25
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _columns(table: str) -> set[str]:
    return {item["name"] for item in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "wallet_entries" not in tables:
        op.create_table(
            "wallet_entries",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("user_id", sa.String(length=36), nullable=False),
            sa.Column("amount_rub", sa.Numeric(12, 2), nullable=False),
            sa.Column("entry_type", sa.String(length=40), nullable=False),
            sa.Column("reference_type", sa.String(length=40), nullable=True),
            sa.Column("reference_id", sa.String(length=36), nullable=True),
            sa.Column("idempotency_key", sa.String(length=255), nullable=False),
            sa.Column("comment", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("idempotency_key"),
        )
        op.create_index(
            op.f("ix_wallet_entries_user_id"),
            "wallet_entries",
            ["user_id"],
            unique=False,
        )

    package_columns = _columns("packages")
    if "pricing_mode" not in package_columns:
        op.add_column(
            "packages",
            sa.Column(
                "pricing_mode",
                sa.String(length=24),
                nullable=False,
                server_default="custom",
            ),
        )
    if "discount_percent" not in package_columns:
        op.add_column(
            "packages",
            sa.Column(
                "discount_percent",
                sa.Numeric(5, 2),
                nullable=False,
                server_default="0",
            ),
        )

    payment_columns = _columns("payments")
    additions = (
        ("purpose", sa.String(length=32), "wallet_topup"),
        ("proof_file_id", sa.Text(), None),
        ("proof_file_type", sa.String(length=24), None),
        ("user_note", sa.Text(), None),
        ("submitted_at", sa.DateTime(timezone=True), None),
        ("reviewed_at", sa.DateTime(timezone=True), None),
        ("reviewed_by", sa.BigInteger(), None),
    )
    for name, column_type, default in additions:
        if name in payment_columns:
            continue
        kwargs: dict[str, object] = {"nullable": name != "purpose"}
        if default is not None:
            kwargs["server_default"] = default
        op.add_column("payments", sa.Column(name, column_type, **kwargs))

    generation_columns = _columns("generations")
    if "price_rub" not in generation_columns:
        op.add_column(
            "generations",
            sa.Column("price_rub", sa.Numeric(12, 2), nullable=False, server_default="0"),
        )

    with op.batch_alter_table("payments") as batch:
        batch.alter_column("package_id", existing_type=sa.String(length=36), nullable=True)


def downgrade() -> None:
    bind = op.get_bind()
    if "price_rub" in _columns("generations"):
        op.drop_column("generations", "price_rub")
    for name in (
        "reviewed_by",
        "reviewed_at",
        "submitted_at",
        "user_note",
        "proof_file_type",
        "proof_file_id",
        "purpose",
    ):
        if name in _columns("payments"):
            op.drop_column("payments", name)
    for name in ("discount_percent", "pricing_mode"):
        if name in _columns("packages"):
            op.drop_column("packages", name)
    if "wallet_entries" in set(sa.inspect(bind).get_table_names()):
        op.drop_index(op.f("ix_wallet_entries_user_id"), table_name="wallet_entries")
        op.drop_table("wallet_entries")
