"""status lifecycle rename, failed_stage and attempts

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-10-31

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b2c3d4e5f6a7"
down_revision: Union[str, None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("documents") as batch:
        batch.add_column(sa.Column("failed_stage", sa.String(length=16), nullable=True))
        batch.add_column(sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"))
    # Statuses are stored as VARCHAR, so the lifecycle rename is a data migration.
    op.execute("UPDATE documents SET status = 'queued' WHERE status = 'uploaded'")
    op.execute(
        "UPDATE documents SET status = 'validating' WHERE status = 'processing' "
        "AND id IN (SELECT document_id FROM extracted_entities)"
    )
    op.execute("UPDATE documents SET status = 'extracting' WHERE status = 'processing'")
    op.execute("UPDATE documents SET status = 'extracted' WHERE status = 'validated'")


def downgrade() -> None:
    op.execute("UPDATE documents SET status = 'uploaded' WHERE status = 'queued'")
    op.execute("UPDATE documents SET status = 'processing' WHERE status IN ('extracting', 'validating')")
    with op.batch_alter_table("documents") as batch:
        batch.drop_column("attempts")
        batch.drop_column("failed_stage")
