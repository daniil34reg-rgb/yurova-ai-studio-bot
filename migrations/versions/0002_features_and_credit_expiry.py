"""Feature flags and expiring paid credits.

Revision ID: 0002
Revises: 0001
Create Date: 2026-07-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from portrait_bot.models import FeatureFlag

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    FeatureFlag.__table__.create(bind=bind, checkfirst=True)
    columns = {item["name"] for item in sa.inspect(bind).get_columns("ledger_entries")}
    if "expires_at" not in columns:
        op.add_column(
            "ledger_entries",
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        )


def downgrade() -> None:
    bind = op.get_bind()
    columns = {item["name"] for item in sa.inspect(bind).get_columns("ledger_entries")}
    if "expires_at" in columns:
        op.drop_column("ledger_entries", "expires_at")
    FeatureFlag.__table__.drop(bind=bind, checkfirst=True)
