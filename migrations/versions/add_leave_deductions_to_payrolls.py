"""add leave_days, leave_deduction, absent_days, absent_deduction to payrolls

Revision ID: add_leave_deductions
Revises: 2c7d9e4b8a91
Create Date: 2026-05-02 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'add_leave_deductions'
down_revision = '2c7d9e4b8a91'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('payrolls', schema=None) as batch_op:
        batch_op.add_column(sa.Column('absent_days', sa.Float(), server_default='0.0'))
        batch_op.add_column(sa.Column('leave_days', sa.Float(), server_default='0.0'))
        batch_op.add_column(sa.Column('absent_deduction', sa.Float(), server_default='0.0'))
        batch_op.add_column(sa.Column('leave_deduction', sa.Float(), server_default='0.0'))


def downgrade():
    with op.batch_alter_table('payrolls', schema=None) as batch_op:
        batch_op.drop_column('leave_deduction')
        batch_op.drop_column('absent_deduction')
        batch_op.drop_column('leave_days')
        batch_op.drop_column('absent_days')
