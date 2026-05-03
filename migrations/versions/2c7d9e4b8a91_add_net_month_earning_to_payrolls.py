"""add net_month_earning to payrolls

Revision ID: 2c7d9e4b8a91
Revises: 41ba0d75df90
Create Date: 2026-05-01 13:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '2c7d9e4b8a91'
down_revision = '41ba0d75df90'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('payrolls', schema=None) as batch_op:
        batch_op.add_column(sa.Column('net_month_earning', sa.Float(), nullable=True))


def downgrade():
    with op.batch_alter_table('payrolls', schema=None) as batch_op:
        batch_op.drop_column('net_month_earning')
