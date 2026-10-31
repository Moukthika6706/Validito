"""entity provenance bounding boxes

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-11-01

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c3d4e5f6a7b8"
down_revision: Union[str, None] = "b2c3d4e5f6a7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("extracted_entities") as batch:
        batch.add_column(sa.Column("bbox", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("extracted_entities") as batch:
        batch.drop_column("bbox")
