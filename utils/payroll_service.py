from flask import current_app
from extensions import db
from database.models import Payroll, Attendance, EmployeeProfile, User, AuditLog, LeaveRequest, OvertimeRequest, PayrollRun
from datetime import datetime, date, timedelta
import os
import calendar
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
from sqlalchemy.exc import IntegrityError
from utils.time_utils import get_nepal_time


class PayrollService:
    @staticmethod
    def _month_window(year, month):
        start_date = date(year, month, 1)
        if month == 12:
            end_date = date(year + 1, 1, 1)
        else:
            end_date = date(year, month + 1, 1)
        return start_date, end_date

    @staticmethod
    def _monthly_allocation(profile, user_role):
        base_salary = float(profile.base_salary or 0) if profile else 0.0
        if user_role == 'intern':
            return base_salary / 3 if base_salary else 0.0
        return base_salary / 12 if base_salary else 0.0

    @staticmethod
    def _get_approved_leave_dates(user_id, start_date, end_date):
        approved_leaves = LeaveRequest.query.filter_by(
            user_id=user_id,
            status='approved'
        ).filter(
            LeaveRequest.end_date >= start_date,
            LeaveRequest.start_date < end_date
        ).all()

        approved_leave_dates = []
        for leave in approved_leaves:
            current_day = max(leave.start_date, start_date)
            last_day = min(leave.end_date, end_date - timedelta(days=1))
            while current_day <= last_day:
                if current_day.weekday() != 5:
                    approved_leave_dates.append(current_day)
                current_day += timedelta(days=1)

        return approved_leave_dates

    @staticmethod
    def _count_paid_leave_days(user_id, start_date, end_date):
        return float(len(PayrollService._get_approved_leave_dates(user_id, start_date, end_date)))

    @staticmethod
    def _approved_tracker_ot_hours(user_id, start_date, end_date):
        total_hours = db.session.query(db.func.sum(OvertimeRequest.hours)).filter(
            OvertimeRequest.user_id == user_id,
            OvertimeRequest.status == 'approved',
            OvertimeRequest.requested_date >= start_date,
            OvertimeRequest.requested_date < end_date
        ).scalar()
        return float(total_hours or 0.0)

    @staticmethod
    def get_cycle_period(target_date=None):
        target_date = target_date or get_nepal_time().date()
        return target_date.year, target_date.month

    @staticmethod
    def get_upcoming_cycle_period(reference_date=None):
        reference_date = reference_date or get_nepal_time().date()
        if reference_date.day <= 5:
            return reference_date.year, reference_date.month
        if reference_date.month == 12:
            return reference_date.year + 1, 1
        return reference_date.year, reference_date.month + 1

    @staticmethod
    def cycle_label(year, month):
        return f"{year}-{month:02d}"

    @staticmethod
    def eligible_users_query():
        # Restrict to only Employee and Intern roles as per requirements
        return User.query.join(EmployeeProfile).filter(
            User.role.in_(['employee', 'intern']),
            User.is_active.is_(True),
            EmployeeProfile.base_salary > 0
        )

    @staticmethod
    def _working_days_in_month(year, month):
        first_day_weekday, days_in_month = calendar.monthrange(year, month)
        total_working_days = 0

        for day_offset in range(days_in_month):
            if (first_day_weekday + day_offset) % 7 != 5: # Exclude only Saturday for Nepal
                total_working_days += 1

        return total_working_days if total_working_days > 0 else 22

    @staticmethod
    def _month_name(year, month):
        return datetime(year, month, 1).strftime('%B %Y')

    @staticmethod
    def calculate_ytd_payroll(user_id, year=None, month=None):
        today = get_nepal_time().date()
        year = year or today.year
        month = month or today.month

        profile = EmployeeProfile.query.filter_by(user_id=user_id).first()
        payrolls = Payroll.query.filter_by(user_id=user_id, year=year).filter(
            Payroll.month <= month
        ).order_by(Payroll.month.asc()).all()

        ytd_gross_pay = 0.0
        ytd_net_pay = 0.0
        ytd_hra = 0.0
        ytd_transport = 0.0
        ytd_overtime_earnings = 0.0
        ytd_lop_deduction = 0.0
        ytd_total_absent_days = 0.0
        ytd_total_ot_hours = 0.0
        monthly_breakdown = []

        current_overtime_rate = float(profile.overtime_rate or 0) if profile else 0.0

        for payroll in payrolls:
            base_salary = float(payroll.snapshot_base_salary or (profile.base_salary if profile else 0) or 0)
            user_role = payroll.user.role if payroll.user else 'employee'
            monthly_allocation = PayrollService._monthly_allocation(profile, user_role)
            working_days = PayrollService._working_days_in_month(payroll.year, payroll.month)
            daily_rate = monthly_allocation / working_days if working_days else 0.0
            lop_deduction = float(payroll.lop_deduction or 0)
            absent_days = lop_deduction / daily_rate if daily_rate else 0.0
            overtime_earnings = float(payroll.overtime_earnings or 0)
            ot_hours = overtime_earnings / current_overtime_rate if current_overtime_rate else 0.0

            ytd_gross_pay += float(payroll.gross_pay or 0)
            ytd_net_pay += float(payroll.net_pay or 0)
            ytd_hra += float(payroll.snapshot_hra or 0)
            ytd_transport += float(payroll.snapshot_transport or 0)
            ytd_overtime_earnings += overtime_earnings
            ytd_lop_deduction += lop_deduction
            ytd_total_absent_days += absent_days
            ytd_total_ot_hours += ot_hours

            monthly_breakdown.append({
                'month': datetime(payroll.year, payroll.month, 1).strftime('%B'),
                'month_num': payroll.month,
                'net_pay': round(float(payroll.net_pay or 0), 2),
                'gross_pay': round(float(payroll.gross_pay or 0), 2),
                'ot_earnings': round(overtime_earnings, 2),
                'lop_deduction': round(lop_deduction, 2),
                'absent_days': round(absent_days, 2),
                'ot_hours': round(ot_hours, 2),
            })

        months_processed = len(payrolls)
        avg_monthly_salary = ytd_gross_pay / months_processed if months_processed else 0.0
        projected_annual_salary = ytd_gross_pay * 12 / months_processed if months_processed else 0.0
        remaining_months = max(0, 12 - months_processed)

        if months_processed:
            start_month_name = monthly_breakdown[0]['month']
            end_month_name = monthly_breakdown[-1]['month']
            period_label = f"{start_month_name} - {end_month_name} {year}"
        else:
            period_label = PayrollService._month_name(year, month)

        return {
            'user_id': user_id,
            'year': year,
            'month': month,
            'period': period_label,
            'months_processed': months_processed,
            'ytd_summary': {
                'ytd_net_pay': round(ytd_net_pay, 2),
                'ytd_gross_pay': round(ytd_gross_pay, 2),
                'ytd_lop_deduction': round(ytd_lop_deduction, 2),
                'ytd_overtime_earnings': round(ytd_overtime_earnings, 2),
                'ytd_hra': round(ytd_hra, 2),
                'ytd_transport': round(ytd_transport, 2),
                'avg_monthly_salary': round(avg_monthly_salary, 2),
            },
            'statistics': {
                'ytd_absent_days': round(ytd_total_absent_days, 2),
                'ytd_total_ot_hours': round(ytd_total_ot_hours, 2),
                'projected_annual_salary': round(projected_annual_salary, 2),
                'remaining_months': remaining_months,
            },
            'monthly_breakdown': monthly_breakdown,
        }

    @staticmethod
    def get_admin_ytd_analytics(year=None, month=None):
        today = get_nepal_time().date()
        year = year or today.year
        month = month or today.month

        employee_rows = db.session.query(
            Payroll.user_id.label('user_id'),
            EmployeeProfile.full_name.label('full_name'),
            EmployeeProfile.employee_id.label('employee_id'),
            EmployeeProfile.department.label('department'),
            db.func.sum(Payroll.net_pay).label('ytd_net_pay'),
            db.func.sum(Payroll.gross_pay).label('ytd_gross_pay'),
            db.func.sum(Payroll.overtime_earnings).label('ytd_overtime_earnings'),
            db.func.sum(Payroll.lop_deduction).label('ytd_lop_deduction'),
            db.func.count(Payroll.id).label('months_processed')
        ).join(User, User.id == Payroll.user_id).join(EmployeeProfile, EmployeeProfile.user_id == User.id).filter(
            Payroll.year == year,
            Payroll.month <= month,
            User.role.in_(['employee', 'intern'])
        ).group_by(
            Payroll.user_id,
            EmployeeProfile.full_name,
            EmployeeProfile.employee_id,
            EmployeeProfile.department
        ).all()

        employee_rows = sorted(employee_rows, key=lambda row: float(row.ytd_net_pay or 0), reverse=True)

        total_employees = len(employee_rows)
        total_net_pay = sum(float(row.ytd_net_pay or 0) for row in employee_rows)
        total_gross_pay = sum(float(row.ytd_gross_pay or 0) for row in employee_rows)
        total_ot_spent = sum(float(row.ytd_overtime_earnings or 0) for row in employee_rows)
        total_deductions = sum(float(row.ytd_lop_deduction or 0) for row in employee_rows)

        department_map = {}
        for row in employee_rows:
            department_name = row.department or 'Unassigned'
            bucket = department_map.setdefault(department_name, {
                'department': department_name,
                'employee_count': 0,
                'ytd_total': 0.0,
            })
            bucket['employee_count'] += 1
            bucket['ytd_total'] += float(row.ytd_net_pay or 0)

        department_breakdown = []
        for bucket in department_map.values():
            employee_count = bucket['employee_count'] or 0
            bucket['avg_per_employee'] = round(bucket['ytd_total'] / employee_count, 2) if employee_count else 0.0
            bucket['ytd_total'] = round(bucket['ytd_total'], 2)
            department_breakdown.append(bucket)

        department_breakdown.sort(key=lambda item: item['ytd_total'], reverse=True)

        monthly_labels = []
        monthly_totals = []
        for month_num in range(1, month + 1):
            monthly_labels.append(datetime(year, month_num, 1).strftime('%b'))
            monthly_total = db.session.query(db.func.sum(Payroll.net_pay)).join(User, User.id == Payroll.user_id).filter(
                Payroll.year == year,
                Payroll.month == month_num,
                User.role.in_(['employee', 'intern'])
            ).scalar() or 0.0
            monthly_totals.append(round(float(monthly_total), 2))

        return {
            'period_year': year,
            'period_month': month,
            'period_label': f"January - {datetime(year, month, 1).strftime('%B %Y')}",
            'organization_ytd': {
                'total_employees': total_employees,
                'total_gross_pay': round(total_gross_pay, 2),
                'total_net_pay': round(total_net_pay, 2),
                'avg_per_employee': round(total_net_pay / total_employees, 2) if total_employees else 0.0,
                'total_ot_spent': round(total_ot_spent, 2),
                'total_deductions': round(total_deductions, 2),
            },
            'department_breakdown': department_breakdown,
            'top_earners': [
                {
                    'user_id': row.user_id,
                    'full_name': row.full_name,
                    'employee_id': row.employee_id,
                    'department': row.department or 'Unassigned',
                    'ytd_net_pay': round(float(row.ytd_net_pay or 0), 2),
                    'months_processed': int(row.months_processed or 0),
                }
                for row in employee_rows[:10]
            ],
            'trends': {
                'labels': monthly_labels,
                'data': monthly_totals,
            },
        }

    @staticmethod
    def calculate_monthly_salary(user_id, month, year, force_zero_deductions=False):
        profile = EmployeeProfile.query.filter_by(user_id=user_id).first()
        if not profile or (profile.base_salary or 0) <= 0:
            return None

        user = User.query.get(user_id)
        user_role = user.role if user else 'employee'

        # Use calendar days for per-day calculations: monthly allocation / days_in_month
        first_day_weekday, days_in_month = calendar.monthrange(year, month)
        total_days = days_in_month if days_in_month > 0 else 30
        start_date, end_date = PayrollService._month_window(year, month)

        attendances = Attendance.query.filter_by(user_id=user_id).filter(
            Attendance.check_in >= start_date,
            Attendance.check_in < end_date
        ).all()

        present_days = 0.0
        weekend_paid_days = 0.0
        half_days = 0.0
        attendance_ot_hours = 0.0
        for att in attendances:
            status = att.status or 'present'
            if att.is_weekend:
                if status != 'absent':
                    weekend_paid_days += 1.0
            elif status in ['present', 'late']:
                present_days += 1.0
            elif status == 'half-day':
                half_days += 1.0
            attendance_ot_hours += float(att.overtime_hours or 0)

        approved_leave_dates = PayrollService._get_approved_leave_dates(user_id, start_date, end_date)
        approved_leave_paid_days = float(len(approved_leave_dates))
        approved_tracker_ot_hours = PayrollService._approved_tracker_ot_hours(user_id, start_date, end_date)

        monthly_allocation = PayrollService._monthly_allocation(profile, user_role)
        # Use working days (Mon-Fri) for daily rate and LOP calculations
        working_days = PayrollService._working_days_in_month(year, month)
        daily_rate = monthly_allocation / working_days if working_days else 0
        effective_payable_days = present_days + weekend_paid_days + approved_leave_paid_days + (half_days * 0.5)
        absent_days = float(len([att for att in attendances if (att.status or 'present') == 'absent']))
        absent_deduction = absent_days * daily_rate
        
        # Approved Leave is a paid day, so we do not add it to deductions.
        # It is already part of the monthly_allocation.
        leave_deduction = 0.0 
        
        deductions = absent_deduction
        if force_zero_deductions:
            deductions = 0.0
        total_overtime_hours = attendance_ot_hours + approved_tracker_ot_hours
        overtime_earnings = total_overtime_hours * float(profile.overtime_rate or 0)
        absent_dates = [att.check_in.date() for att in attendances if (att.status or 'present') == 'absent']

        hra_amt = float(profile.hra or 0)
        transport_amt = float(profile.transport_allowance or 0)
        other_amt = float(profile.other_allowances or 0)

        gross_pay = (
            monthly_allocation
            + hra_amt
            + transport_amt
            + other_amt
            + overtime_earnings
        )
        net_pay = gross_pay - deductions

        # Net Month Earning per requested formula: base monthly allocation + HRA + Auto(transport) [+ overtime]
        net_month_earning = monthly_allocation + hra_amt + transport_amt + overtime_earnings

        return {
            'annual_base_salary': float(profile.base_salary or 0),
            'monthly_allocation': monthly_allocation,
            'daily_rate': daily_rate,
            'gross_pay': round(gross_pay, 2),
            'deductions': round(deductions, 2),
            'absent_deduction': round(absent_deduction, 2),
            'leave_deduction': round(leave_deduction, 2),
            'net_pay': round(net_pay, 2),
            'net_month_earning': round(net_month_earning, 2),
            'overtime_earnings': round(overtime_earnings, 2),
            'present_days': present_days,
            'weekend_paid_days': weekend_paid_days,
            'approved_leave_paid_days': approved_leave_paid_days,
            'approved_leave_dates': [d.strftime('%Y-%m-%d') for d in approved_leave_dates],
            'half_days': half_days,
            'effective_payable_days': effective_payable_days,
            'absent_days': absent_days,
            'absent_dates': [d.strftime('%Y-%m-%d') for d in absent_dates],
            'total_workdays': working_days,
            'attendance_ot_hours': attendance_ot_hours,
            'approved_tracker_ot_hours': approved_tracker_ot_hours,
            'total_overtime_hours': total_overtime_hours,
        }

    @staticmethod
    def upsert_payroll_for_user(user, month, year, allow_paid_updates=False):
        if not user or not user.profile or (user.profile.base_salary or 0) <= 0:
            return 'skipped', None

        salary_data = PayrollService.calculate_monthly_salary(user.id, month, year)
        if not salary_data:
            return 'skipped', None

        profile = user.profile
        cycle_label = PayrollService.cycle_label(year, month)
        payroll = Payroll.query.filter_by(user_id=user.id, month=month, year=year).first()

        if payroll and payroll.status == 'paid' and not allow_paid_updates:
            return 'skipped_paid', payroll

        if payroll is None:
            payroll = Payroll(user_id=user.id, month=month, year=year, status='generated', payment_status='Unpaid')
            db.session.add(payroll)
            action = 'generated'
        else:
            if payroll.payment_status is None:
                payroll.payment_status = 'Paid' if payroll.paid_date else 'Unpaid'
            if payroll.status is None:
                payroll.status = 'generated'
            # Preserve explicit payment status; do not auto-convert payrolls to Paid from status alone.
            action = 'updated'

        payroll.snapshot_base_salary = float(profile.base_salary or 0)
        payroll.snapshot_hra = float(profile.hra or 0)
        payroll.snapshot_transport = float(profile.transport_allowance or 0)
        payroll.overtime_earnings = salary_data['overtime_earnings']
        payroll.absent_days = salary_data.get('absent_days', 0.0)
        payroll.leave_days = salary_data.get('approved_leave_paid_days', 0.0)
        payroll.absent_deduction = salary_data.get('absent_deduction', 0.0)
        payroll.leave_deduction = salary_data.get('leave_deduction', 0.0)
        payroll.lop_deduction = salary_data['deductions']
        payroll.gross_pay = salary_data['gross_pay']
        payroll.net_pay = salary_data['net_pay']
        payroll.net_month_earning = salary_data.get('net_month_earning', salary_data['net_pay'])
        payroll.processed_date = get_nepal_time()
        payroll.earnings_last_updated = profile.last_updated or get_nepal_time()
        payroll.cycle_label = cycle_label

        return action, payroll

    @staticmethod
    def process_payroll_cycle(year=None, month=None, triggered_by='manual', actor_id=None, actor_ip='SYSTEM'):
        if year is None or month is None:
            year, month = PayrollService.get_cycle_period()

        results = {'generated': 0, 'updated': 0, 'skipped': 0, 'skipped_paid': 0, 'errors': 0}
        users = PayrollService.eligible_users_query().all()

        for user in users:
            try:
                action, _ = PayrollService.upsert_payroll_for_user(user, month, year)
                results[action] = results.get(action, 0) + 1
            except IntegrityError:
                db.session.rollback()
                current_app.logger.warning(
                    "Payroll upsert hit unique constraint for user_id=%s cycle=%s",
                    user.id,
                    PayrollService.cycle_label(year, month)
                )
                results['updated'] += 1
            except Exception as exc:
                db.session.rollback()
                results['errors'] += 1
                current_app.logger.exception(
                    "Payroll processing failed for user_id=%s cycle=%s: %s",
                    user.id,
                    PayrollService.cycle_label(year, month),
                    exc
                )

        # Process revenue entries for students
        try:
            from utils.financial_service import FinancialService
            students = User.query.join(EmployeeProfile).filter(
                User.role == 'student',
                User.is_active.is_(True),
                EmployeeProfile.base_salary > 0
            ).all()

            for student in students:
                try:
                    FinancialService.create_revenue_entry(student.id, month, year)
                except Exception as e:
                    current_app.logger.warning(f"Failed to create revenue entry for student {student.id}: {e}")
        except Exception as e:
            current_app.logger.exception(f"Error processing student revenue entries: {e}")

        db.session.commit()

        db.session.add(AuditLog(
            user_id=actor_id,
            action=f"Payroll cycle processed for {PayrollService.cycle_label(year, month)} via {triggered_by}",
            details=(
                f"Generated={results['generated']}, Updated={results['updated']}, "
                f"Skipped={results['skipped']}, SkippedPaid={results['skipped_paid']}, Errors={results['errors']}"
            ),
            ip_address=actor_ip
        ))
        db.session.commit()

        current_app.logger.info(
            "Payroll cycle %s finished via %s. Results=%s",
            PayrollService.cycle_label(year, month),
            triggered_by,
            results
        )
        return results

    @staticmethod
    def sync_payroll_totals(year=None, month=None):
        """
        Ensure all payroll totals are synchronized and consistent.
        This method recalculates and updates PayrollRun totals to match
        the sum of individual employee net salaries.
        """
        if year is None or month is None:
            year, month = PayrollService.get_cycle_period()

        try:
            # Get all payrolls for the month
            payrolls = Payroll.query.join(User).filter(
                Payroll.year == year,
                Payroll.month == month,
                User.role.in_(['employee', 'intern'])
            ).all()

            # Calculate total from individual net pays
            total_net_salary = 0.0
            for payroll in payrolls:
                try:
                    salary_data = PayrollService.calculate_monthly_salary(payroll.user_id, month, year, force_zero_deductions=False)
                    if salary_data:
                        # Calculate net pay the same way as in _build_payroll_manage_context
                        monthly_allocation = salary_data.get('monthly_allocation', 0.0)
                        hra = float(payroll.snapshot_hra or 0)
                        transport = float(payroll.snapshot_transport or 0)
                        ot = salary_data.get('overtime_earnings', 0.0)
                        deductions = salary_data.get('deductions', 0.0)
                        
                        net_monthly_before_deductions = monthly_allocation + hra + transport + ot
                        net_pay = max(0, net_monthly_before_deductions - deductions)
                        total_net_salary += net_pay
                    else:
                        # Fallback to stored value
                        total_net_salary += float(payroll.net_pay or 0.0)
                except Exception as e:
                    current_app.logger.warning(f"Error calculating salary for user {payroll.user_id}: {e}")
                    total_net_salary += float(payroll.net_pay or 0.0)

            # Update or create PayrollRun
            run = PayrollRun.query.filter_by(year=year, month=month).first()
            if run:
                run.total_payout_amount = total_net_salary
                run.total_employees = len(payrolls)
            else:
                from datetime import date
                import calendar
                start_date = date(year, month, 1)
                last_day = calendar.monthrange(year, month)[1]
                end_date = date(year, month, last_day)
                
                run = PayrollRun(
                    year=year,
                    month=month,
                    pay_period_start=start_date,
                    pay_period_end=end_date,
                    total_employees=len(payrolls),
                    total_payout_amount=total_net_salary,
                    status='processed'
                )
                db.session.add(run)
            
            db.session.commit()
            current_app.logger.info(f"Synchronized payroll totals for {year}-{month}: Rs. {total_net_salary:,.2f}")
            return total_net_salary
            
        except Exception as e:
            current_app.logger.exception(f"Error syncing payroll totals for {year}-{month}: {e}")
            db.session.rollback()
            return 0.0

    @staticmethod
    def refresh_upcoming_payroll_for_user(user_id, actor_id=None, actor_ip='SYSTEM'):
        user = User.query.get(user_id)
        if not user or not user.profile:
            return None

        year, month = PayrollService.get_upcoming_cycle_period()
        action, payroll = PayrollService.upsert_payroll_for_user(user, month, year)
        db.session.commit()

        db.session.add(AuditLog(
            user_id=actor_id,
            action=f"Upcoming payroll refreshed for {PayrollService.cycle_label(year, month)}",
            details=f"Target user_id={user_id}, action={action}",
            ip_address=actor_ip
        ))
        db.session.commit()

        current_app.logger.info(
            "Upcoming payroll refresh for user_id=%s cycle=%s action=%s",
            user_id,
            PayrollService.cycle_label(year, month),
            action
        )
        return {'action': action, 'payroll_id': payroll.id if payroll else None, 'year': year, 'month': month}

    @staticmethod
    def get_dashboard_analytics(month_window=6, filter_year=None, filter_month=None):
        today = get_nepal_time().date()
        current_year = filter_year if filter_year else today.year
        current_month = filter_month if filter_month and filter_month != 'all' else today.month
        is_yearly = filter_month == 'all'

        trend_labels = []
        trend_data = []
        try:
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
                trend_labels.append(f"{y}-{m:02d}")
                total_salary = db.session.query(db.func.sum(Payroll.net_pay)).filter(
                    Payroll.year == y,
                    Payroll.month == m
                ).scalar() or 0.0
                trend_data.append(float(total_salary))
        except Exception as e:
            current_app.logger.exception(f"Error calculating trend data: {e}")
            trend_labels = [f"{current_year}-{current_month:02d}"]
            trend_data = [0.0]

        distribution_labels = []
        distribution_data = []
        try:
            distribution_query = db.session.query(
                User.role,
                db.func.sum(Payroll.net_pay).label('total_pay')
            ).join(User, User.id == Payroll.user_id).filter(
                Payroll.year == current_year,
                Payroll.month == current_month,
                User.role.in_(['employee', 'intern']) # Focus on relevant payroll roles
            ).group_by(User.role).all()

            distribution_labels = [row[0].title() for row in distribution_query if row[0]]
            distribution_data = [float(row.total_pay or 0) for row in distribution_query]
        except Exception as e:
            current_app.logger.exception(f"Error calculating distribution data: {e}")
            distribution_labels = []
            distribution_data = []

        latest_month_query = db.session.query(
            Payroll.year,
            Payroll.month
        ).order_by(Payroll.year.desc(), Payroll.month.desc()).first()

        salary_distribution = []
        try:
            if latest_month_query:
                salary_distribution = db.session.query(
                    Payroll.user_id,
                    EmployeeProfile.full_name,
                    Payroll.net_pay
                ).join(User, User.id == Payroll.user_id).join(EmployeeProfile, EmployeeProfile.user_id == User.id).filter(
                    Payroll.year == latest_month_query.year,
                    Payroll.month == latest_month_query.month
                ).order_by(Payroll.net_pay.desc()).all()
        except Exception as e:
            current_app.logger.exception(f"Error calculating salary distribution: {e}")
            salary_distribution = []

        history_data = []
        try:
            history_query = db.session.query(
                Payroll.year,
                Payroll.month,
                db.func.count(Payroll.id).label('employees'),
                db.func.sum(Payroll.net_pay).label('total_salary'),
                db.func.sum(db.case((Payroll.payment_status == 'Paid', 1), else_=0)).label('paid_count')
            ).group_by(Payroll.year, Payroll.month).order_by(Payroll.year.desc(), Payroll.month.desc()).all()

            # Get PayrollRun data for accurate totals - always prioritize this
            payroll_runs = {}
            try:
                # Get all PayrollRun records for the last 6 months to ensure we have current data
                six_months_ago = today.replace(month=today.month-6 if today.month > 6 else today.month+6, 
                                             year=today.year if today.month > 6 else today.year-1)
                payroll_runs = {f"{run.year}-{run.month}": run.total_payout_amount 
                               for run in PayrollRun.query.filter(
                                   db.or_(
                                       db.and_(PayrollRun.year == six_months_ago.year, PayrollRun.month >= six_months_ago.month),
                                       db.and_(PayrollRun.year > six_months_ago.year)
                                   )
                               ).all() if run.total_payout_amount and run.total_payout_amount > 0}
            except Exception as e:
                current_app.logger.warning(f"Failed to load PayrollRun data: {e}")
                payroll_runs = {}

            for row in history_query:
                month_key = f"{row.year}-{row.month}"
                # Use PayrollRun total if available, otherwise use sum of net_pay
                total_salary = float(payroll_runs.get(month_key, row.total_salary or 0))
                # Determine status
                if row.year == current_year and row.month == current_month:
                    display_status = 'Ongoing'
                elif row.paid_count == row.employees and row.employees > 0:
                    display_status = 'Paid'
                else:
                    display_status = 'Unpaid'
                    
                history_data.append({
                    'month_str': f"{row.year}-{row.month:02d}",
                    'year': row.year,
                    'month': row.month,
                    'employees': row.employees,
                    'total_salary': total_salary,
                    'status': display_status
                })
        except Exception as e:
            current_app.logger.exception(f"Error calculating history data: {e}")
            history_data = []

        monthly_total = 0.0
        try:
            if latest_month_query:
                month_key = f"{latest_month_query.year}-{latest_month_query.month}"
                # Use PayrollRun total if available, otherwise sum net_pay
                if month_key in payroll_runs:
                    monthly_total = float(payroll_runs[month_key])
                else:
                    monthly_total = db.session.query(db.func.sum(Payroll.net_pay)).filter(
                        Payroll.year == latest_month_query.year,
                        Payroll.month == latest_month_query.month
                    ).scalar() or 0.0
        except Exception as e:
            current_app.logger.exception(f"Error calculating monthly total: {e}")
            monthly_total = 0.0

        return {
            'trend_labels': trend_labels,
            'trend_data': trend_data,
            'distribution_labels': distribution_labels,
            'distribution_data': distribution_data,
            'salary_distribution_labels': [row.full_name for row in salary_distribution[:10]],
            'salary_distribution_data': [float(row.net_pay or 0) for row in salary_distribution[:10]],
            'history_data': history_data,
            'total_monthly_payouts': float(monthly_total),
            'last_refreshed': get_nepal_time().isoformat()
        }

    @staticmethod
    def attach_calculated_fields(p, year=None, month=None):
        """
        Unified helper to attach 'live' calculated fields to a Payroll object for display.
        This ensures consistency between Admin, Staff, and Payslip views.
        """
        if year is None: year = p.year
        if month is None: month = p.month
        
        try:
            salary_data = PayrollService.calculate_monthly_salary(p.user_id, month, year, force_zero_deductions=False)
            if salary_data:
                p.monthly_allocation = salary_data.get('monthly_allocation', 0.0)
                p.daily_rate = salary_data.get('daily_rate', 0.0)
                p.absent_days = salary_data.get('absent_days', 0.0)
                p.absent_dates = salary_data.get('absent_dates', [])
                p.leave_days = salary_data.get('approved_leave_paid_days', 0.0)
                p.approved_leave_days = salary_data.get('approved_leave_paid_days', 0.0)
                p.approved_leave_dates = salary_data.get('approved_leave_dates', [])
                p.absent_deduction = salary_data.get('absent_deduction', 0.0)
                p.leave_deduction = salary_data.get('leave_deduction', 0.0)
                p.display_gross_pay = salary_data.get('gross_pay', p.gross_pay or 0.0)
                p.display_deductions = salary_data.get('deductions', p.lop_deduction or 0.0)
                p.display_overtime_earnings = salary_data.get('overtime_earnings', p.overtime_earnings or 0.0)
                p.advance_payment = getattr(p, 'advance_payment', 0.0)
                
                # Net Monthly Salary = (base + snapshot_HRA + snapshot_Auto + OT) - deductions
                net_monthly_before_deductions = (
                    (p.monthly_allocation or 0) +
                    (p.snapshot_hra or 0) +
                    (p.snapshot_transport or 0) +
                    (p.display_overtime_earnings or 0)
                )
                p.display_net_pay = max(0, net_monthly_before_deductions - p.display_deductions - p.advance_payment)
            else:
                # Fallback to snapshot values if calculation fails
                p.monthly_allocation = float((p.snapshot_base_salary or 0) / 3) if p.user and p.user.role == 'intern' else float((p.snapshot_base_salary or 0) / 12)
                p.daily_rate = p.monthly_allocation / 30 if p.monthly_allocation else 0.0
                p.absent_days = 0.0
                p.absent_dates = []
                p.leave_days = 0.0
                p.approved_leave_days = 0.0
                p.approved_leave_dates = []
                p.absent_deduction = 0.0
                p.leave_deduction = 0.0
                p.display_gross_pay = p.gross_pay or 0.0
                p.display_net_pay = p.net_pay or 0.0
                p.display_deductions = p.lop_deduction or 0.0
                p.display_overtime_earnings = p.overtime_earnings or 0.0
                p.advance_payment = 0.0
        except Exception as exc:
            current_app.logger.warning(f"Failed to attach live fields for payroll {p.id}: {exc}")
            # Ensure minimal fields are present to avoid TemplateErrors
            p.display_net_pay = p.net_pay or 0.0
            p.display_gross_pay = p.gross_pay or 0.0
        return p

    @staticmethod
    def generate_payslip_pdf(payroll_id):
        payroll = Payroll.query.get(payroll_id)
        user = User.query.get(payroll.user_id)
        profile = user.profile

        filename = f"payslip_{user.id}_{payroll.month}_{payroll.year}.pdf"
        filepath = os.path.join(current_app.root_path, 'static', 'payslips', filename)

        if not os.path.exists(os.path.dirname(filepath)):
            os.makedirs(os.path.dirname(filepath))

        c = canvas.Canvas(filepath, pagesize=letter)
        c.drawString(100, 750, f"EMS Payslip - {payroll.month}/{payroll.year}")
        c.drawString(100, 730, f"Employee: {profile.full_name}")
        c.drawString(100, 710, f"Base Salary: {payroll.snapshot_base_salary}")
        c.drawString(100, 690, f"Net Pay: {payroll.net_pay}")
        c.save()

        payroll.payslip_path = filename
        db.session.commit()
        return filename

    @staticmethod
    def backfill_net_month_earning(actor_id=None, actor_ip='SYSTEM'):
        """Persist net_month_earning for all payroll rows using the live monthly formula."""
        payrolls = Payroll.query.all()
        updated = 0
        errors = 0

        for payroll in payrolls:
            try:
                salary_data = PayrollService.calculate_monthly_salary(
                    payroll.user_id,
                    payroll.month,
                    payroll.year,
                    force_zero_deductions=False
                )
                if salary_data:
                    payroll.net_month_earning = salary_data.get('net_month_earning', payroll.net_pay or payroll.gross_pay or 0.0)
                else:
                    payroll.net_month_earning = payroll.net_pay or payroll.gross_pay or 0.0
                updated += 1
            except Exception as exc:
                current_app.logger.exception(
                    "Failed to backfill net_month_earning for payroll id=%s: %s",
                    getattr(payroll, 'id', None),
                    exc
                )
                errors += 1

        db.session.commit()
        db.session.add(AuditLog(
            user_id=actor_id,
            action="Backfilled net_month_earning for payroll rows",
            details=f"Updated={updated}, Errors={errors}",
            ip_address=actor_ip
        ))
        db.session.commit()
        current_app.logger.info("Backfilled net_month_earning across payroll rows. updated=%s errors=%s", updated, errors)
        return {'updated': updated, 'errors': errors}

    @staticmethod
    def persist_force_zero_deductions_for_month(year=None, month=None, actor_id=None, actor_ip='SYSTEM'):
        """
        One-time updater: for the given year/month, set lop_deduction to 0.0
        and recompute gross_pay and net_pay using the monthly calculation
        with deductions forced to zero. Commits changes and logs an AuditLog.
        """
        if year is None or month is None:
            year, month = PayrollService.get_cycle_period()

        from database.models import Payroll, AuditLog, User

        payrolls = Payroll.query.filter_by(year=year, month=month).all()
        updated = 0
        errors = 0

        for p in payrolls:
            try:
                salary_data = PayrollService.calculate_monthly_salary(p.user_id, p.month, p.year, force_zero_deductions=True)
                if not salary_data:
                    continue
                p.lop_deduction = 0.0
                p.overtime_earnings = salary_data.get('overtime_earnings', p.overtime_earnings or 0.0)
                p.gross_pay = salary_data.get('gross_pay', p.gross_pay or 0.0)
                p.net_pay = salary_data.get('net_pay', p.net_pay or 0.0)
                p.processed_date = get_nepal_time()
                updated += 1
            except Exception as exc:
                current_app.logger.exception("Failed to persist zero deduction for payroll id=%s: %s", getattr(p, 'id', None), exc)
                errors += 1

        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
            current_app.logger.exception("Failed to commit payroll zero-deduction updates for %s-%s", year, month)
            return {'updated': updated, 'errors': errors + 1}

        # Audit log
        try:
            db.session.add(AuditLog(
                user_id=actor_id,
                action=f"Force-zero deductions persisted for {PayrollService.cycle_label(year, month)}",
                details=f"Updated {updated} payroll records, errors={errors}",
                ip_address=actor_ip
            ))
            db.session.commit()
        except Exception:
            db.session.rollback()

        current_app.logger.info("Persisted force-zero deductions for %s-%s: updated=%s errors=%s", year, month, updated, errors)
        return {'updated': updated, 'errors': errors}
