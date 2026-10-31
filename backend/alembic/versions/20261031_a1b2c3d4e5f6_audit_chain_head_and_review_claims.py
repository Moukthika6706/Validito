"""audit chain head and review claims

Revision ID: a1b2c3d4e5f6
Revises: 444218f3420e
Create Date: 2026-10-31

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, None] = "444218f3420e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "audit_chain_head",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("last_hash", sa.String(length=64), nullable=True),
        sa.Column("last_entry_id", sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    # Seed the head from the existing log so verification stays consistent after upgrade.
    op.execute(
        "INSERT INTO audit_chain_head (id, last_hash, last_entry_id) "
        "SELECT 1, hash, id FROM audit_log WHERE id = (SELECT MAX(id) FROM audit_log)"
    )
    with op.batch_alter_table("documents") as batch:
        batch.add_column(sa.Column("claimed_by_id", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True))
        batch.create_foreign_key("fk_documents_claimed_by_users", "users", ["claimed_by_id"], ["id"])


def downgrade() -> None:
    with op.batch_alter_table("documents") as batch:
        batch.drop_constraint("fk_documents_claimed_by_users", type_="foreignkey")
        batch.drop_column("claimed_at")
        batch.drop_column("claimed_by_id")
    op.drop_table("audit_chain_head")
