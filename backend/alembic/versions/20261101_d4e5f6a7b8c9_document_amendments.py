"""document amendment link and declared amended fields

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-11-01

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d4e5f6a7b8c9"
down_revision: Union[str, None] = "c3d4e5f6a7b8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("documents") as batch:
        batch.add_column(sa.Column("amendment_of_id", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("amended_fields", sa.JSON(), nullable=True))
        batch.create_foreign_key("fk_documents_amendment_of_documents", "documents", ["amendment_of_id"], ["id"])


def downgrade() -> None:
    with op.batch_alter_table("documents") as batch:
        batch.drop_constraint("fk_documents_amendment_of_documents", type_="foreignkey")
        batch.drop_column("amended_fields")
        batch.drop_column("amendment_of_id")
