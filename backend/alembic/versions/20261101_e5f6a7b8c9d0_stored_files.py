"""stored_files: database-backed storage for uploaded originals (STORAGE_BACKEND=db)

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-11-01

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql


revision: str = "e5f6a7b8c9d0"
down_revision: Union[str, None] = "d4e5f6a7b8c9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "stored_files",
        sa.Column("path", sa.String(length=512), nullable=False),
        sa.Column("content", sa.LargeBinary().with_variant(mysql.LONGBLOB(), "mysql"), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("path"),
    )


def downgrade() -> None:
    op.drop_table("stored_files")
