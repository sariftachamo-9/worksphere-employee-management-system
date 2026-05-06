"""merge heads

Revision ID: 910cf079d791
Revises: 001_financial_models, add_leave_deductions
Create Date: 2026-05-03 13:24:06.333842

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '910cf079d791'
down_revision = ('001_financial_models', 'add_leave_deductions')
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass
