"""
Financial Service - Handles Revenue (Student Fees) and Expense (Payroll) Logic
"""
from extensions import db
from database.models import (
    Revenue, Expense, PayrollRun, FinancialSummary, Payslip,
    User, EmployeeProfile, Attendance
)
from utils.time_utils import get_nepal_time
from sqlalchemy import func
import calendar
from datetime import date


class FinancialService:
    
    # ==================== PAYROLL RUN OPERATIONS ====================
    
    @staticmethod
    def create_payroll_run(month, year):
        """Create a new payroll run for processing"""
        existing = PayrollRun.query.filter_by(month=month, year=year).first()
        if existing:
            return existing
        
        # Calculate pay period dates
        start_date = date(year, month, 1)
        last_day = calendar.monthrange(year, month)[1]
        end_date = date(year, month, last_day)
        
        payroll_run = PayrollRun(
            month=month,
            year=year,
            pay_period_start=start_date,
            pay_period_end=end_date,
            status='draft'
        )
        db.session.add(payroll_run)
        db.session.commit()
        return payroll_run
    
    # ==================== EXPENSE (PAYROLL) OPERATIONS ====================
    
    @staticmethod
    def calculate_monthly_salary(user_id, month, year):
        """
        Calculate monthly salary with TWO-STEP DISTRIBUTION:
        Step 1: yearly_salary / 12 = monthly_allocation
        Step 2: monthly_allocation / workdays_in_month = daily_rate
        """
        user = User.query.get(user_id)
        if not user or not user.is_active or user.role not in ['employee', 'intern']:
            return None

        profile = EmployeeProfile.query.filter_by(user_id=user_id).first()
        if not profile or (profile.base_salary or 0) <= 0:
            return None
        
        # STEP 1: Divide yearly salary by 12 months
        # STEP 1: Divide salary by duration (3 for interns, 12 for employees)
        base_salary = float(profile.base_salary or 0)
        if user.role == 'intern':
            monthly_allocation = base_salary / 3
        else:
            monthly_allocation = base_salary / 12
        
        # STEP 2: Calculate workdays in month
        _, days_in_month = calendar.monthrange(year, month)
        first_day_weekday, _ = calendar.monthrange(year, month)
        
        total_working_days = 0
        for i in range(days_in_month):
            if (first_day_weekday + i) % 7 != 5:  # Exclude only Saturday for Nepal
                total_working_days += 1
        
        total_days = total_working_days if total_working_days > 0 else 22
        
        # STEP 2: Divide monthly allocation by workdays
        daily_rate = monthly_allocation / total_days if total_days else 0
        
        # Get actual attendance
        start_date = date(year, month, 1)
        if month == 12:
            end_date = date(year + 1, 1, 1)
        else:
            end_date = date(year, month + 1, 1)
        
        attendances = Attendance.query.filter_by(user_id=user_id).filter(
            Attendance.check_in >= start_date,
            Attendance.check_in < end_date
        ).all()
        
        # Calculate effective worked days
        effective_worked_days = 0.0
        overtime_hours = 0.0
        for att in attendances:
            if att.status in ['present', 'late', 'weekend']:
                effective_worked_days += 1.0
            elif att.status == 'half-day':
                effective_worked_days += 0.5
            overtime_hours += float(att.overtime_hours or 0)
        
        # Calculate deductions (LOP - Loss of Pay)
        absent_days = max(0, total_days - effective_worked_days)
        deductions = absent_days * daily_rate
        
        # Overtime earnings
        overtime_earnings = overtime_hours * float(profile.overtime_rate or 0)
        
        # Gross pay = monthly_allocation + allowances + overtime
        gross_pay = (
            monthly_allocation +
            float(profile.hra or 0) +
            float(profile.transport_allowance or 0) +
            float(profile.other_allowances or 0) +
            overtime_earnings
        )
        
        # Net pay
        net_pay = gross_pay - deductions
        
        return {
            'monthly_allocation': monthly_allocation,
            'daily_rate': daily_rate,
            'base_salary_portion': monthly_allocation,
            'hra': float(profile.hra or 0),
            'transport_allowance': float(profile.transport_allowance or 0),
            'other_allowances': float(profile.other_allowances or 0),
            'overtime_pay': overtime_earnings,
            'gross_pay': round(gross_pay, 2),
            'lop_deduction': round(deductions, 2),
            'total_deductions': round(deductions, 2),
            'net_payment': round(net_pay, 2),
            'effective_worked_days': effective_worked_days,
            'absent_days': absent_days,
            'total_workdays': total_days,
            'overtime_hours': overtime_hours,
        }
    
    @staticmethod
    def create_expense_entry(user_id, month, year, payroll_run_id=None, salary_data=None):
        """Create an expense entry for employee/intern"""
        user = User.query.get(user_id)
        if not user or user.role not in ['employee', 'intern']:
            return None
        
        if salary_data is None:
            salary_data = FinancialService.calculate_monthly_salary(user_id, month, year)
            if not salary_data:
                return None
        
        # Check if expense already exists
        expense = Expense.query.filter_by(
            user_id=user_id,
            month=month,
            year=year
        ).first()
        
        if expense:
            return expense
        
        expense = Expense(
            user_id=user_id,
            payroll_run_id=payroll_run_id,
            month=month,
            year=year,
            base_salary=salary_data['base_salary_portion'],
            hra=salary_data['hra'],
            transport_allowance=salary_data['transport_allowance'],
            other_allowances=salary_data['other_allowances'],
            overtime_pay=salary_data['overtime_pay'],
            unpaid_leave_deduction=salary_data['lop_deduction'],
            gross_salary=salary_data['gross_pay'],
            total_deductions=salary_data['total_deductions'],
            net_payment=salary_data['net_payment'],
            status='pending'
        )
        
        db.session.add(expense)
        db.session.commit()
        return expense
    
    @staticmethod
    def process_payroll_batch(month, year, processed_by_id=None):
        """Process entire payroll batch for all employees/interns"""
        payroll_run = FinancialService.create_payroll_run(month, year)
        
        # Get all eligible employees/interns
        employees = User.query.join(EmployeeProfile).filter(
            User.role.in_(['employee', 'intern']),
            User.is_active.is_(True),
            EmployeeProfile.base_salary > 0
        ).all()
        
        results = {
            'created': 0,
            'skipped': 0,
            'errors': 0,
            'total_payout': 0.0
        }
        
        for employee in employees:
            try:
                salary_data = FinancialService.calculate_monthly_salary(employee.id, month, year)
                if salary_data:
                    expense = FinancialService.create_expense_entry(
                        employee.id, month, year, payroll_run.id, salary_data
                    )
                    if expense:
                        results['created'] += 1
                        results['total_payout'] += expense.net_payment
                else:
                    results['skipped'] += 1
            except Exception as e:
                results['errors'] += 1
                print(f"Error processing payroll for user {employee.id}: {str(e)}")
        
        # Update payroll run
        payroll_run.total_employees = results['created']
        payroll_run.total_payout_amount = results['total_payout']
        payroll_run.status = 'processed'
        if processed_by_id:
            payroll_run.processed_by = processed_by_id
            payroll_run.processed_at = get_nepal_time()
        
        db.session.commit()
        return payroll_run, results
    
    # ==================== REVENUE (STUDENT FEES) OPERATIONS ====================
    
    @staticmethod
    def create_revenue_entry(user_id, month, year):
        """Create a revenue entry for student fees"""
        user = User.query.get(user_id)
        profile = EmployeeProfile.query.filter_by(user_id=user_id).first()
        
        if not user or user.role != 'student' or not profile:
            return None
        
        fee_amount = float(profile.base_salary or 0)
        
        # Check if revenue entry exists
        revenue = Revenue.query.filter_by(
            user_id=user_id,
            month=month,
            year=year
        ).first()
        
        if revenue:
            return revenue
        
        # Assume fee is fully collected for revenue tracking since there's no FeePayment system yet
        total_collected = fee_amount
        
        outstanding = fee_amount - total_collected
        
        # Determine status
        if total_collected >= fee_amount:
            status = 'collected'
        elif total_collected > 0:
            status = 'partial'
        else:
            status = 'pending'
        
        revenue = Revenue(
            user_id=user_id,
            month=month,
            year=year,
            fee_amount=fee_amount,
            amount_collected=total_collected,
            outstanding_balance=outstanding,
            status=status,
            last_payment_date=profile.last_fee_payment if hasattr(profile, 'last_fee_payment') else None
        )
        
        db.session.add(revenue)
        db.session.commit()
        return revenue
    
    @staticmethod
    def update_revenue_collection(user_id, month, year, amount_paid):
        """Update revenue entry with payment"""
        revenue = Revenue.query.filter_by(
            user_id=user_id,
            month=month,
            year=year
        ).first()
        
        if not revenue:
            revenue = FinancialService.create_revenue_entry(user_id, month, year)
        
        if revenue:
            revenue.amount_collected += amount_paid
            revenue.outstanding_balance = revenue.fee_amount - revenue.amount_collected
            
            if revenue.outstanding_balance <= 0:
                revenue.status = 'collected'
            elif revenue.amount_collected > 0:
                revenue.status = 'partial'
            
            revenue.last_payment_date = get_nepal_time()
            db.session.commit()
        
        return revenue
    
    # ==================== FINANCIAL SUMMARY OPERATIONS ====================
    
    @staticmethod
    def generate_financial_summary(month, year):
        """Generate monthly financial summary (revenue - expenses = profit)"""
        
        # Get revenue data
        revenue_data = db.session.query(
            func.sum(Revenue.fee_amount).label('expected'),
            func.sum(Revenue.amount_collected).label('collected'),
            func.sum(Revenue.outstanding_balance).label('outstanding')
        ).filter(
            Revenue.year == year,
            Revenue.month == month
        ).first()
        
        # Get expense data directly from live Payroll
        from database.models import Payroll
        expense_data = db.session.query(
            func.sum(Payroll.net_pay).label('total_paid'),
            func.sum(Payroll.gross_pay).label('total_gross'),
            func.count(Payroll.id).label('count')
        ).filter(
            Payroll.year == year,
            Payroll.month == month
        ).first()
        
        total_revenue_expected = float(revenue_data.expected or 0)
        total_revenue_collected = float(revenue_data.collected or 0)
        total_outstanding = float(revenue_data.outstanding or 0)
        
        total_expenses = float(expense_data.total_paid or 0)
        
        # Calculate profit/loss
        net_profit = total_revenue_collected - total_expenses
        profit_margin = (net_profit / total_revenue_expected * 100) if total_revenue_expected > 0 else 0
        
        # Create or update summary
        summary = FinancialSummary.query.filter_by(month=month, year=year).first()
        
        if not summary:
            summary = FinancialSummary(month=month, year=year)
            db.session.add(summary)
        
        summary.total_revenue_expected = total_revenue_expected
        summary.total_revenue_collected = total_revenue_collected
        summary.total_outstanding = total_outstanding
        summary.total_expenses = total_expenses
        summary.net_profit = net_profit
        summary.profit_margin = profit_margin
        summary.generated_at = get_nepal_time()
        
        db.session.commit()
        return summary
    
    @staticmethod
    def get_financial_analytics(month_window=6, filter_year=None, filter_month=None):
        """Get financial analytics for dashboard"""
        today = get_nepal_time().date()
        current_year = filter_year if filter_year else today.year
        current_month = filter_month if filter_month and filter_month != 'all' else today.month
        is_yearly = filter_month == 'all'
        
        # Revenue trend
        revenue_trend = []
        # Expense trend
        expense_trend = []
        # Profit trend
        profit_trend = []
        
        if is_yearly:
            periods = [(current_year, m) for m in range(1, 13)]
        else:
            periods = []
            for i in range(month_window - 1, -1, -1):
                m = current_month - i
                y = current_year
                while m <= 0:
                    m += 12
                    y -= 1
                periods.append((y, m))

        for y, m in periods:
            period = f"{y}-{m:02d}"
            
            # Revenue
            rev = db.session.query(
                func.sum(Revenue.amount_collected).label('collected')
            ).filter(Revenue.year == y, Revenue.month == m).first()
            
            # Expense
            from database.models import Payroll
            exp = db.session.query(
                func.sum(Payroll.net_pay).label('paid')
            ).filter(Payroll.year == y, Payroll.month == m).first()
            
            rev_amount = float(rev.collected or 0)
            exp_amount = float(exp.paid or 0)
            profit = rev_amount - exp_amount
            
            revenue_trend.append({'period': period, 'amount': rev_amount})
            expense_trend.append({'period': period, 'amount': exp_amount})
            profit_trend.append({'period': period, 'amount': profit})
        
        if is_yearly:
            # Yearly view: Sum up everything for the filter_year
            current_revenue = float(db.session.query(func.sum(Revenue.amount_collected)).filter(
                Revenue.year == current_year
            ).scalar() or 0)
            
            from database.models import Payroll
            current_expenses = float(db.session.query(func.sum(Payroll.net_pay)).filter(
                Payroll.year == current_year
            ).scalar() or 0)
        else:
            # Monthly view
            current_revenue = float(db.session.query(func.sum(Revenue.amount_collected)).filter(
                Revenue.year == current_year, Revenue.month == current_month
            ).scalar() or 0)
            
            from database.models import Payroll
            current_expenses = float(db.session.query(func.sum(Payroll.net_pay)).filter(
                Payroll.year == current_year, Payroll.month == current_month
            ).scalar() or 0)

        return {
            'revenue_trend': revenue_trend,
            'expense_trend': expense_trend,
            'profit_trend': profit_trend,
            'current_month': {
                'revenue': current_revenue,
                'expenses': current_expenses,
                'is_yearly': is_yearly,
                'filtered_year': current_year,
                'filtered_month': current_month if not is_yearly else None
            }
        }
