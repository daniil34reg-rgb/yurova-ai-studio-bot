"""Editable admin content and ordering.

Revision ID: 0003
Revises: 0002
Create Date: 2026-07-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from portrait_bot.models import BotSetting

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _columns(table: str) -> set[str]:
    return {item["name"] for item in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    bind = op.get_bind()
    BotSetting.__table__.create(bind=bind, checkfirst=True)
    template_columns = _columns("templates")
    if "preview_path" not in template_columns:
        op.add_column("templates", sa.Column("preview_path", sa.Text(), nullable=True))
    if "sort_order" not in template_columns:
        op.add_column(
            "templates",
            sa.Column("sort_order", sa.Integer(), nullable=False, server_default="100"),
        )
    if "sort_order" not in _columns("packages"):
        op.add_column(
            "packages",
            sa.Column("sort_order", sa.Integer(), nullable=False, server_default="100"),
        )


def downgrade() -> None:
    if "sort_order" in _columns("packages"):
        op.drop_column("packages", "sort_order")
    template_columns = _columns("templates")
    if "sort_order" in template_columns:
        op.drop_column("templates", "sort_order")
    if "preview_path" in template_columns:
        op.drop_column("templates", "preview_path")
    BotSetting.__table__.drop(bind=op.get_bind(), checkfirst=True)
