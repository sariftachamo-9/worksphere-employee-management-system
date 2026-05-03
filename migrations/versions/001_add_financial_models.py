"""Add financial models: Revenue, Expense, PayrollRun, FinancialSummary, Payslip

Revision ID: 001_financial_models
Revises: 41ba0d75df90
Create Date: 2026-04-28

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers
revision = '001_financial_models'
down_revision = '41ba0d75df90'
branch_labels = None
depends_on = None


def upgrade():
    # Create payroll_runs table
    op.create_table('payroll_runs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('month', sa.Integer(), nullable=False),
        sa.Column('year', sa.Integer(), nullable=False),
        sa.Column('pay_period_start', sa.Date(), nullable=False),
        sa.Column('pay_period_end', sa.Date(), nullable=False),
        sa.Column('total_employees', sa.Integer(), nullable=True, server_default='0'),
        sa.Column('total_payout_amount', sa.Float(), nullable=True, server_default='0.0'),
        sa.Column('processed_by', sa.Integer(), nullable=True),
        sa.Column('processed_at', sa.DateTime(), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=True, server_default='draft'),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['processed_by'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('month', 'year', name='uq_payroll_run_period')
    )
    op.create_index('idx_payroll_run_period_status', 'payroll_runs', ['year', 'month', 'status'], unique=False)

    # Create expenses table
    op.create_table('expenses',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('payroll_run_id', sa.Integer(), nullable=True),
        sa.Column('month', sa.Integer(), nullable=False),
        sa.Column('year', sa.Integer(), nullable=False),
        sa.Column('base_salary', sa.Float(), nullable=True, server_default='0.0'),
        sa.Column('hra', sa.Float(), nullable=True, server_default='0.0'),
        sa.Column('transport_allowance', sa.Float(), nullable=True, server_default='0.0'),
        sa.Column('other_allowances', sa.Float(), nullable=True, server_default='0.0'),
        sa.Column('overtime_pay', sa.Float(), nullable=True, server_default='0.0'),
        sa.Column('bonus', sa.Float(), nullable=True, server_default='0.0'),
        sa.Column('tax_deduction', sa.Float(), nullable=True, server_default='0.0'),
        sa.Column('unpaid_leave_deduction', sa.Float(), nullable=True, server_default='0.0'),
        sa.Column('insurance_deduction', sa.Float(), nullable=True, server_default='0.0'),
        sa.Column('other_deductions', sa.Float(), nullable=True, server_default='0.0'),
        sa.Column('gross_salary', sa.Float(), nullable=True, server_default='0.0'),
        sa.Column('total_deductions', sa.Float(), nullable=True, server_default='0.0'),
        sa.Column('net_payment', sa.Float(), nullable=True, server_default='0.0'),
        sa.Column('payment_date', sa.DateTime(), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=True, server_default='pending'),
        sa.Column('payment_method', sa.String(length=50), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['payroll_run_id'], ['payroll_runs.id'], ),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'month', 'year', name='uq_expense_user_period')
    )
    op.create_index('idx_expense_period_status', 'expenses', ['year', 'month', 'status'], unique=False)

    # Create revenues table
    op.create_table('revenues',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('month', sa.Integer(), nullable=False),
        sa.Column('year', sa.Integer(), nullable=False),
        sa.Column('fee_amount', sa.Float(), nullable=True, server_default='0.0'),
        sa.Column('amount_collected', sa.Float(), nullable=True, server_default='0.0'),
        sa.Column('outstanding_balance', sa.Float(), nullable=True, server_default='0.0'),
        sa.Column('status', sa.String(length=20), nullable=True, server_default='pending'),
        sa.Column('last_payment_date', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'month', 'year', name='uq_revenue_user_period')
    )
    op.create_index('idx_revenue_period_status', 'revenues', ['year', 'month', 'status'], unique=False)

    # Create payslips table
    op.create_table('payslips',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('expense_id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('month', sa.Integer(), nullable=False),
        sa.Column('year', sa.Integer(), nullable=False),
        sa.Column('gross_salary', sa.Float(), nullable=False),
        sa.Column('total_deductions', sa.Float(), nullable=False),
        sa.Column('net_salary', sa.Float(), nullable=False),
        sa.Column('generated_at', sa.DateTime(), nullable=True),
        sa.Column('download_url', sa.String(length=255), nullable=True),
        sa.ForeignKeyConstraint(['expense_id'], ['expenses.id'], ),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'month', 'year', name='uq_payslip_user_period')
    )
    op.create_index('idx_payslip_period', 'payslips', ['year', 'month'], unique=False)

    # Create financial_summaries table
    op.create_table('financial_summaries',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('month', sa.Integer(), nullable=False),
        sa.Column('year', sa.Integer(), nullable=False),
        sa.Column('total_revenue_expected', sa.Float(), nullable=True, server_default='0.0'),
        sa.Column('total_revenue_collected', sa.Float(), nullable=True, server_default='0.0'),
        sa.Column('total_outstanding', sa.Float(), nullable=True, server_default='0.0'),
        sa.Column('total_expenses', sa.Float(), nullable=True, server_default='0.0'),
        sa.Column('total_salaries_paid', sa.Float(), nullable=True, server_default='0.0'),
        sa.Column('expenses_pending', sa.Float(), nullable=True, server_default='0.0'),
        sa.Column('net_profit', sa.Float(), nullable=True, server_default='0.0'),
        sa.Column('profit_margin', sa.Float(), nullable=True, server_default='0.0'),
        sa.Column('generated_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('month', 'year', name='uq_financial_summary_period')
    )
    op.create_index('idx_financial_summary_period', 'financial_summaries', ['year', 'month'], unique=False)


def downgrade():
    op.drop_index('idx_financial_summary_period', table_name='financial_summaries')
    op.drop_table('financial_summaries')
    
    op.drop_index('idx_payslip_period', table_name='payslips')
    op.drop_table('payslips')
    
    op.drop_index('idx_revenue_period_status', table_name='revenues')
    op.drop_table('revenues')
    
    op.drop_index('idx_expense_period_status', table_name='expenses')
    op.drop_table('expenses')
    
    op.drop_index('idx_payroll_run_period_status', table_name='payroll_runs')
    op.drop_table('payroll_runs')
