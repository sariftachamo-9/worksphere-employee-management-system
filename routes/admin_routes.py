from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify, current_app
from flask_login import login_required, current_user
from extensions import db
from utils.time_utils import get_nepal_time
import secrets
from datetime import datetime, timedelta
from database.models import User, EmployeeProfile, Attendance, LeaveRequest, Payroll, PayrollRun, LoginToken, ContactQuery, AuditLog, OfficeSettings, AllowedLocation, Notice, OvertimeRequest
from utils.id_generator import generate_staff_id
from utils.email_service import send_notice_broadcast
from werkzeug.security import generate_password_hash
from utils.security_utils import validate_password_strength
from utils.excel_sync import ExcelSyncService
from utils.payroll_service import PayrollService
import re

admin_bp = Blueprint('admin', __name__)
DEFAULT_USER_PASSWORD = 'EmployeE@123'

def validate_nepal_phone_digits(phone_digits):
    phone_digits = (phone_digits or '').strip()
    if re.fullmatch(r'(98|97)\d{8}', phone_digits):
        return True, phone_digits
    return False, None

def admin_required(func):
    from functools import wraps
    @wraps(func)
    def wrapper(*args, **kwargs):
        if not current_user.is_authenticated or current_user.role != 'admin':
            flash('Access denied.', 'danger')
            return redirect(url_for('staff.dashboard'))
        return func(*args, **kwargs)
    return wrapper

@admin_bp.route('/generate-qr-login/<int:user_id>')
@login_required
@admin_required
def generate_qr_login(user_id):
    user = User.query.get_or_404(user_id)
    if not user.profile:
        return jsonify({'success': False, 'message': 'User has no profile.'}), 400

    # Use the same serializer as QRService for consistency
    from itsdangerous import URLSafeSerializer
    s = URLSafeSerializer(current_app.config['SECRET_KEY'])
    token_data = {
        "username": user.profile.full_name,
        "user_id": user.profile.employee_id,
        "role": user.role
    }
    token = s.dumps(token_data)
    
    # Point to the auto_login flow which includes Geofence validation
    qr_url = url_for('qr.auto_login', token=token, _external=True)
    
    # Store Audit Log
    db.session.add(AuditLog(
        user_id=current_user.id,
        action=f"Generated Direct Login Link for {user.username}",
        ip_address=request.remote_addr
    ))
    db.session.commit()
    
    return jsonify({'success': True, 'qr_url': qr_url})

@admin_bp.route('/dashboard')
@login_required
@admin_required
def dashboard():
    return render_template('admin/dashboard.html')

@admin_bp.route('/employees')
@login_required
@admin_required
def employees():
    search = request.args.get('search', '')
    dept = request.args.get('dept', '')
    desig = request.args.get('desig', '')
    
    query = User.query.join(EmployeeProfile).filter(User.role == 'employee', User.is_active == True)
    
    if search:
        query = query.filter(db.or_(
            EmployeeProfile.full_name.ilike(f'%{search}%'),
            EmployeeProfile.employee_id.ilike(f'%{search}%'),
            User.email.ilike(f'%{search}%')
        ))
    if dept:
        query = query.filter(EmployeeProfile.department == dept)
    if desig:
        query = query.filter(EmployeeProfile.designation == desig)
        
    users = query.all()
    # Get unique depts and desigs for filters
    depts = db.session.query(EmployeeProfile.department).distinct().filter(EmployeeProfile.department != None).all()
    desigs = db.session.query(EmployeeProfile.designation).distinct().filter(EmployeeProfile.designation != None).all()
    
    return render_template('admin/staff_directory.html', 
                           users=users, 
                           title="Employees List", 
                           admin_title="Employee Management",
                           add_label="Add Employee",
                           add_endpoint="admin.add_employee",
                           depts=[d[0] for d in depts],
                           desigs=[d[0] for d in desigs],
                           curr_dept=dept,
                           curr_desig=desig,
                           curr_search=search,
                           now=get_nepal_time())

@admin_bp.route('/interns')
@login_required
@admin_required
def interns():
    search = request.args.get('search', '')
    dept = request.args.get('dept', '')
    desig = request.args.get('desig', '')
    
    query = User.query.join(EmployeeProfile).filter(
        User.role == 'intern', 
        db.or_(User.is_active == True, EmployeeProfile.workshop_status == 'Completed')
    )
    
    if search:
        query = query.filter(db.or_(
            EmployeeProfile.full_name.ilike(f'%{search}%'),
            EmployeeProfile.employee_id.ilike(f'%{search}%'),
            User.email.ilike(f'%{search}%')
        ))
    if dept:
        query = query.filter(EmployeeProfile.department == dept)
    if desig:
        query = query.filter(EmployeeProfile.designation == desig)
        
    users = query.all()
    
    # Get unique depts and desigs for filters
    depts = db.session.query(EmployeeProfile.department).distinct().filter(EmployeeProfile.department != None).all()
    desigs = db.session.query(EmployeeProfile.designation).distinct().filter(EmployeeProfile.designation != None).all()
    
    return render_template('admin/staff_directory.html', 
                           users=users, 
                           title="Interns List", 
                           admin_title="Intern Management",
                           add_label="Add Intern",
                           add_endpoint="admin.add_intern",
                           depts=[d[0] for d in depts],
                           desigs=[d[0] for d in desigs],
                           curr_dept=dept,
                           curr_desig=desig,
                           curr_search=search,
                           now=get_nepal_time())

@admin_bp.route('/remove-staff')
@login_required
@admin_required
def remove_staff_list():
    search = request.args.get('search', '')
    dept = request.args.get('dept', '')
    desig = request.args.get('desig', '')
    role = request.args.get('role', '') # 'employee', 'intern', 'student' or ''

    query = User.query.join(EmployeeProfile).filter(
        User.role.in_(['employee', 'intern', 'student']),
        db.or_(User.is_active == True, EmployeeProfile.workshop_status == 'Completed')
    )

    if role:
        query = query.filter(User.role == role)

    if search:
        query = query.filter(db.or_(
            EmployeeProfile.full_name.ilike(f'%{search}%'),
            EmployeeProfile.employee_id.ilike(f'%{search}%'),
            User.email.ilike(f'%{search}%')
        ))
    if dept:
        query = query.filter(EmployeeProfile.department == dept)
    if desig:
        query = query.filter(EmployeeProfile.designation == desig)

    users = query.all()
    depts = db.session.query(EmployeeProfile.department).distinct().filter(EmployeeProfile.department != None).all()
    desigs = db.session.query(EmployeeProfile.designation).distinct().filter(EmployeeProfile.designation != None).all()

    return render_template('admin/staff_directory.html',
                           users=users,
                           title="Remove Staff",
                           admin_title="Remove Staff",
                           add_label=None,
                           add_endpoint=None,
                           depts=[d[0] for d in depts],
                           desigs=[d[0] for d in desigs],
                           curr_dept=dept,
                           curr_desig=desig,
                           curr_search=search,
                           curr_role=role,
                           now=get_nepal_time())

@admin_bp.route('/students')
@login_required
@admin_required
def students():
    search = request.args.get('search', '')
    dept = request.args.get('dept', '')
    desig = request.args.get('desig', '')
    
    query = User.query.join(EmployeeProfile).filter(
        User.role == 'student', 
        db.or_(User.is_active == True, EmployeeProfile.workshop_status == 'Completed')
    )
    
    if search:
        query = query.filter(db.or_(
            EmployeeProfile.full_name.ilike(f'%{search}%'),
            EmployeeProfile.employee_id.ilike(f'%{search}%'),
            User.email.ilike(f'%{search}%')
        ))
    if dept:
        query = query.filter(EmployeeProfile.department == dept)
    if desig:
        query = query.filter(EmployeeProfile.designation == desig)
        
    users = query.all()
    
    # Get unique depts and desigs for filters
    depts = db.session.query(EmployeeProfile.department).distinct().filter(EmployeeProfile.department != None).all()
    desigs = db.session.query(EmployeeProfile.designation).distinct().filter(EmployeeProfile.designation != None).all()
    
    return render_template('admin/staff_directory.html', 
                           users=users, 
                           title="Students List", 
                           admin_title="Student Management",
                           add_label="Add Student",
                           add_endpoint="admin.add_student",
                           depts=[d[0] for d in depts],
                           desigs=[d[0] for d in desigs],
                           curr_dept=dept,
                           curr_desig=desig,
                           curr_search=search,
                           now=get_nepal_time())

@admin_bp.route('/removed-access')
@login_required
@admin_required
def removed_access():
    search = request.args.get('search', '')
    dept = request.args.get('dept', '')
    desig = request.args.get('desig', '')

    query = User.query.join(EmployeeProfile).filter(User.is_active == False)

    if search:
        query = query.filter(db.or_(
            EmployeeProfile.full_name.ilike(f'%{search}%'),
            EmployeeProfile.employee_id.ilike(f'%{search}%'),
            User.email.ilike(f'%{search}%')
        ))
    if dept:
        query = query.filter(EmployeeProfile.department == dept)
    if desig:
        query = query.filter(EmployeeProfile.designation == desig)

    users = query.all()
    depts = db.session.query(EmployeeProfile.department).distinct().filter(EmployeeProfile.department != None).all()
    desigs = db.session.query(EmployeeProfile.designation).distinct().filter(EmployeeProfile.designation != None).all()

    return render_template('admin/staff_directory.html',
                           users=users,
                           title="Removed Access",
                           admin_title="Removed Access",
                           add_label=None,
                           add_endpoint=None,
                           depts=[d[0] for d in depts],
                           desigs=[d[0] for d in desigs],
                           curr_dept=dept,
                           curr_desig=desig,
                           curr_search=search,
                           curr_status='inactive',
                           now=get_nepal_time())

@admin_bp.route('/employee-queries')
@login_required
@admin_required
def employee_queries():
    search = request.args.get('search', '')
    status = request.args.get('status', '')
    priority = request.args.get('priority', '')
    
    query = ContactQuery.query
    
    if search:
        query = query.filter(db.or_(
            ContactQuery.name.ilike(f'%{search}%'),
            ContactQuery.email.ilike(f'%{search}%'),
            ContactQuery.message.ilike(f'%{search}%')
        ))
    if status:
        query = query.filter(ContactQuery.status == status)
    if priority:
        query = query.filter(ContactQuery.priority == priority)
        
    queries = query.order_by(ContactQuery.created_at.desc()).all()
    grouped_queries = {}
    for q in queries:
        key = q.email or q.name or 'Anonymous'
        if key not in grouped_queries:
            grouped_queries[key] = {
                'name': q.name or 'Anonymous',
                'email': q.email,
                'queries': []
            }
        grouped_queries[key]['queries'].append(q)
        
    return render_template('admin/queries.html', grouped_queries=grouped_queries)

@admin_bp.route('/query/update/<int:query_id>', methods=['POST'])
@login_required
@admin_required
def update_query(query_id):
    query = ContactQuery.query.get_or_404(query_id)
    query.status = request.form.get('status')
    query.priority = request.form.get('priority')
    
    reply = request.form.get('reply')
    if reply and reply.strip():
        from database.models import QueryMessage
        query.admin_reply = reply.strip() # Keep for legacy/UI convenience if needed
        admin_msg = QueryMessage(
            query_id=query.id,
            sender_type='admin',
            message=reply.strip()
        )
        db.session.add(admin_msg)
        
    db.session.commit()
    flash('Query updated.', 'success')
    return redirect(url_for('admin.employee_queries'))

@admin_bp.route('/query/reply/<int:query_id>', methods=['POST'])
@login_required
@admin_required
def reply_query(query_id):
    from database.models import QueryMessage
    query = ContactQuery.query.get_or_404(query_id)
    data = request.get_json() or request.form
    reply_text = data.get('reply')
    
    if not reply_text:
        if request.is_json:
            return jsonify({'success': False, 'message': 'Reply text is required'}), 400
        else:
            flash('Reply text is required', 'error')
            return redirect(url_for('admin.employee_queries'))
        
    query.admin_reply = reply_text
    query.status = 'resolved'
    
    admin_msg = QueryMessage(
        query_id=query.id,
        sender_type='admin',
        message=reply_text.strip()
    )
    db.session.add(admin_msg)
    db.session.commit()
    
    if request.is_json:
        return jsonify({'success': True, 'message': 'Reply sent successfully'})
    return redirect(url_for('admin.employee_queries'))

@admin_bp.route('/leave-requests')
@login_required
@admin_required
def leave_requests():
    search = request.args.get('search', '')
    status = request.args.get('status', '')
    leave_type = request.args.get('leave_type', '')
    
    query = LeaveRequest.query.join(User).join(EmployeeProfile)
    
    if search:
        query = query.filter(db.or_(
            EmployeeProfile.full_name.ilike(f'%{search}%'),
            EmployeeProfile.employee_id.ilike(f'%{search}%')
        ))
    if status:
        query = query.filter(LeaveRequest.status == status)
    if leave_type:
        query = query.filter(LeaveRequest.leave_type == leave_type)
        
    requests = query.order_by(LeaveRequest.applied_on.desc()).all()
    
    return render_template('admin/leaves.html', 
                           requests=requests,
                           curr_search=search,
                           curr_status=status,
                           curr_leave_type=leave_type)

@admin_bp.route('/approve-leave/<int:leave_id>/<string:status>', methods=['POST'])
@login_required
@admin_required
def approve_leave(leave_id, status):
    req = LeaveRequest.query.get_or_404(leave_id)
    if status in ['approved', 'rejected']:
        req.status = status
        db.session.commit()
        flash(f'Leave request {status}.', 'success')
    return redirect(url_for('admin.leave_requests'))

@admin_bp.route('/attendance')
@login_required
@admin_required
def attendance():
    search = request.args.get('search', '')
    date_str = request.args.get('date', '')
    dept = request.args.get('dept', '')
    status = request.args.get('status', '') # present, late, absent, on_leave
    user_id = request.args.get('user_id')
    
    today = get_nepal_time().date()
    target_date = datetime.strptime(date_str, '%Y-%m-%d').date() if date_str else today
    
    # Base query for existing attendance records
    query = Attendance.query.join(User).join(EmployeeProfile)
    
    # Filter by date using an index-friendly range (Start of Day to End of Day)
    start_of_day = datetime.combine(target_date, datetime.min.time())
    end_of_day = datetime.combine(target_date, datetime.max.time())
    
    query = query.filter(
        Attendance.check_in >= start_of_day,
        Attendance.check_in <= end_of_day
    )
    
    if user_id:
        query = query.filter(Attendance.user_id == user_id)
    
    if search:
        query = query.filter(db.or_(
            EmployeeProfile.full_name.ilike(f'%{search}%'),
            EmployeeProfile.employee_id.ilike(f'%{search}%')
        ))
    if dept:
        query = query.filter(EmployeeProfile.department == dept)
    if status and status != 'on_leave':
        if status == 'holiday':
            query = query.filter(db.or_(Attendance.status == 'holiday', Attendance.is_weekend == True))
        else:
            query = query.filter(Attendance.status == status)

    records = query.order_by(Attendance.check_in.desc()).all()
    existing_user_ids = {r.user_id for r in records}
    is_weekend = target_date.weekday() == 5

    # Approved leaves covering the target day
    leave_user_ids = set()
    leaves = []
    if not status or status in ['', 'on_leave', 'absent', 'holiday']:
        leaves = LeaveRequest.query.filter(
            LeaveRequest.status == 'approved',
            LeaveRequest.start_date <= target_date,
            LeaveRequest.end_date >= target_date
        ).all()
        leave_user_ids = {leave.user_id for leave in leaves}

    virtual_records = []
    if not status or status == 'on_leave':
        # Find approved leave requests that cover target_date
        for leave in leaves:
            user = leave.user
            profile = user.profile
            if not profile:
                continue

            matches_search = not search or search.lower() in profile.full_name.lower() or search.lower() in profile.employee_id.lower()
            matches_dept = not dept or profile.department == dept

            if matches_search and matches_dept and user.id not in existing_user_ids:
                virtual_records.append({
                    'user': user,
                    'is_virtual': True,
                    'status': 'on_leave',
                    'leave_type': leave.leave_type
                })

    if not status or status in ['', 'absent']:
        if not is_weekend:
            absent_users = User.query.filter(
                User.is_active == True,
                User.role != 'admin',
                ~User.id.in_(existing_user_ids),
                ~User.id.in_(leave_user_ids)
            ).all()

            for user in absent_users:
                profile = user.profile
                if not profile:
                    continue
                matches_search = not search or search.lower() in profile.full_name.lower() or search.lower() in profile.employee_id.lower()
                matches_dept = not dept or profile.department == dept
                if not (matches_search and matches_dept):
                    continue

                virtual_records.append({
                    'user': user,
                    'is_virtual': True,
                    'status': 'absent',
                    'check_in': datetime.combine(target_date, datetime.min.time()).replace(hour=12),
                    'is_weekend': False
                })

    if not status or status in ['', 'holiday']:
        if is_weekend:
            holiday_users = User.query.filter(
                User.is_active == True,
                User.role != 'admin',
                ~User.id.in_(existing_user_ids),
                ~User.id.in_(leave_user_ids)
            ).all()

            for user in holiday_users:
                profile = user.profile
                if not profile:
                    continue
                matches_search = not search or search.lower() in profile.full_name.lower() or search.lower() in profile.employee_id.lower()
                matches_dept = not dept or profile.department == dept
                if not (matches_search and matches_dept):
                    continue

                virtual_records.append({
                    'user': user,
                    'is_virtual': True,
                    'status': 'holiday',
                    'check_in': datetime.combine(target_date, datetime.min.time()).replace(hour=12),
                    'is_weekend': True
                })

    if status == 'on_leave':
        display_records = virtual_records
    else:
        display_records = records + virtual_records

    # Filter metadata for template
    depts = db.session.query(EmployeeProfile.department).distinct().filter(EmployeeProfile.department != None).all()

    return render_template('admin/attendance.html', 
                           records=display_records,
                           depts=[d[0] for d in depts],
                           curr_date=target_date.strftime('%Y-%m-%d'),
                           curr_dept=dept,
                           curr_status=status,
                           curr_search=search)

@admin_bp.route('/notices', methods=['GET', 'POST'])
@login_required
@admin_required
def notices():
    if request.method == 'POST':
        title = request.form.get('title')
        content = request.form.get('content')
        role = request.form.get('role', 'all')
        notice_type = request.form.get('notice_type', 'General Announcement Notices')
        
        notice = Notice(title=title, content=content, role_restriction=role, notice_type=notice_type, is_active=True)
        db.session.add(notice)
        
        # Audit Log
        log = AuditLog(
            user_id=current_user.id,
            action=f"Created Notice: {title} (Target: {role.capitalize()})",
            ip_address=request.remote_addr
        )
        db.session.add(log)
        db.session.commit()
        
        # Background Broadcast
        if role == 'all':
            target_users = User.query.filter(User.role != 'admin').all()
        else:
            target_users = User.query.filter_by(role=role).all()
        
        emails = [u.profile.personal_email or u.email for u in target_users if u.profile]
        if emails:
            send_notice_broadcast(emails, title, content)
            
        flash('Notice broadcasted successfully and emailed to staff.', 'success')
        return redirect(url_for('admin.notices'))
        
    notices_query = Notice.query
    search = request.args.get('search', '')
    filter_date = request.args.get('date', '')
    
    if search:
        notices_query = notices_query.filter(db.or_(
            Notice.title.ilike(f'%{search}%'),
            Notice.content.ilike(f'%{search}%')
        ))
        
    if filter_date:
        from sqlalchemy import cast, Date
        notices_query = notices_query.filter(cast(Notice.created_at, Date) == filter_date)
        
    notices = notices_query.order_by(Notice.created_at.desc()).all()
    return render_template('admin/notices.html', notices=notices, curr_search=search, curr_date=filter_date)

@admin_bp.route('/notices/delete/<int:notice_id>', methods=['POST'])
@login_required
@admin_required
def delete_notice(notice_id):
    notice = Notice.query.get_or_404(notice_id)
    title = notice.title
    db.session.delete(notice)
    
    # Audit Log
    db.session.add(AuditLog(
        user_id=current_user.id,
        action=f"Deleted Notice: {title}",
        ip_address=request.remote_addr
    ))
    db.session.commit()
    
    flash('Notice deleted successfully.', 'success')
    return redirect(url_for('admin.notices'))

@admin_bp.route('/payroll')
@login_required
@admin_required
def payroll():
    try:
        # Sync totals for the current month to ensure consistency
        current_year, current_month = PayrollService.get_cycle_period()
        PayrollService.sync_payroll_totals(current_year, current_month)
        
        analytics = PayrollService.get_dashboard_analytics()
        return render_template('admin/payroll.html', **analytics)
    except Exception as e:
        current_app.logger.exception(f"Error in payroll route: {e}")
        flash('An error occurred while loading the payroll page. Please try again.', 'danger')
        return render_template('admin/payroll.html', 
                             trend_labels=[], 
                             trend_data=[], 
                             distribution_labels=[], 
                             distribution_data=[], 
                             salary_distribution_labels=[], 
                             salary_distribution_data=[], 
                             history_data=[], 
                             total_monthly_payouts=0.0, 
                             last_refreshed=get_nepal_time().isoformat())


def _build_payroll_manage_context(year, month, search=''):
    query = Payroll.query.join(User).join(EmployeeProfile).filter(
        Payroll.year == year,
        Payroll.month == month
    )

    if search:
        query = query.filter(db.or_(
            EmployeeProfile.full_name.ilike(f'%{search}%'),
            EmployeeProfile.employee_id.ilike(f'%{search}%')
        ))

    payrolls = query.order_by(EmployeeProfile.employee_id.asc()).all()

    def _attach_display_fields(p):
        PayrollService.attach_calculated_fields(p)

        # Fallback: if calculation failed or returned nothing, derive monthly allocation from snapshot
        if p.payment_status == 'Paid' and not p.paid_date:
            p.payment_status = 'Unpaid'
        if p.payment_status is None:
            p.payment_status = 'Unpaid'
        if p.monthly_allocation is None:
            try:
                # If snapshot_base_salary is annual, divide by 12 for employees and 3 for interns
                if getattr(p.user, 'role', '') == 'intern':
                    p.monthly_allocation = float((p.snapshot_base_salary or 0) / 3)
                else:
                    p.monthly_allocation = float((p.snapshot_base_salary or 0) / 12)
                # approximate daily rate using calendar days in the month
                import calendar as _calendar
                days = _calendar.monthrange(year, month)[1]
                p.daily_rate = p.monthly_allocation / days if days else 0.0
                p.absent_days = 0.0
                p.absent_deduction = 0.0
                p.leave_days = 0.0
                p.leave_deduction = 0.0
                p.display_gross_pay = p.gross_pay or 0.0
                p.display_net_pay = p.net_pay or 0.0
                p.display_deductions = p.lop_deduction or 0.0
                p.display_overtime_earnings = p.overtime_earnings or 0.0
                p.advance_payment = 0.0
            except Exception:
                p.monthly_allocation = 0.0
                p.daily_rate = 0.0
                p.absent_days = 0.0
                p.absent_deduction = 0.0
                p.leave_days = 0.0
                p.leave_deduction = 0.0
                p.display_gross_pay = p.gross_pay or 0.0
                p.display_net_pay = p.net_pay or 0.0
                p.display_deductions = p.lop_deduction or 0.0
                p.display_overtime_earnings = p.overtime_earnings or 0.0
                p.advance_payment = 0.0

    for p in payrolls:
        _attach_display_fields(p)

    employee_payrolls = [p for p in payrolls if getattr(p.user, 'role', '') == 'employee']
    intern_payrolls = [p for p in payrolls if getattr(p.user, 'role', '') == 'intern']

    # Prefer using an explicit payroll run summary if available for accuracy
    from sqlalchemy import inspect

    run = None
    try:
        if inspect(db.engine).has_table('payroll_runs'):
            run = PayrollRun.query.filter_by(year=year, month=month).first()
    except Exception:
        # If inspection or query fails (e.g. missing table), fall back to summing payroll records
        run = None

    # Calculate total from individual net pays for consistency
    total_net_salary = sum(float(p.display_net_pay or 0.0) for p in payrolls)

    # Always update or create PayrollRun with the calculated total for consistency
    try:
        if run:
            run.total_payout_amount = total_net_salary
            run.total_employees = len([p for p in payrolls if getattr(p.user, 'role', '') in ['employee', 'intern']])
        else:
            # Create a new PayrollRun if it doesn't exist
            import calendar
            from datetime import date
            start_date = date(year, month, 1)
            last_day = calendar.monthrange(year, month)[1]
            end_date = date(year, month, last_day)
            run = PayrollRun(
                year=year,
                month=month,
                pay_period_start=start_date,
                pay_period_end=end_date,
                total_employees=len([p for p in payrolls if getattr(p.user, 'role', '') in ['employee', 'intern']]),
                total_payout_amount=total_net_salary,
                status='processed'
            )
            db.session.add(run)
        db.session.commit()
    except Exception as e:
        current_app.logger.exception(f"Error updating PayrollRun: {e}")
        db.session.rollback()
        # Continue without updating the run

    latest_processed = db.session.query(db.func.max(Payroll.processed_date)).filter(
        Payroll.year == year,
        Payroll.month == month
    ).scalar()

    last_refreshed = latest_processed.isoformat() if latest_processed else get_nepal_time().isoformat()
    month_str = datetime(year, month, 1).strftime('%B %Y')

    from utils.time_utils import get_nepal_time
    today = get_nepal_time().date()
    
    if year == today.year and month == today.month:
        batch_status = 'Ongoing'
    else:
        all_paid = len(payrolls) > 0 and all(p.payment_status == 'Paid' for p in payrolls)
        batch_status = 'Paid' if all_paid else 'Unpaid'

    return {
        'payrolls': payrolls,
        'employee_payrolls': employee_payrolls,
        'intern_payrolls': intern_payrolls,
        'year': year,
        'month': month,
        'month_str': month_str,
        'curr_search': search,
        'total_net_salary': total_net_salary,
        'last_refreshed': last_refreshed,
        'batch_status': batch_status,
    }

@admin_bp.route('/api/payroll/analytics')
@login_required
@admin_required
def payroll_analytics():
    try:
        filter_year = request.args.get('year', type=int)
        filter_month = request.args.get('month') # string because it can be 'all'
        
        if filter_month and filter_month != 'all':
            filter_month = int(filter_month)
        
        # Sync totals for the current month to ensure consistency
        current_year, current_month = PayrollService.get_cycle_period()
        PayrollService.sync_payroll_totals(current_year, current_month)

        analytics = PayrollService.get_dashboard_analytics(
            month_window=6,
            filter_year=filter_year,
            filter_month=filter_month
        )

        # Add financial analytics from FinancialService
        try:
            from utils.financial_service import FinancialService

            # Generate/update financial summary for current month
            FinancialService.generate_financial_summary(current_month, current_year)

            financial_data = FinancialService.get_financial_analytics(
                month_window=6, 
                filter_year=filter_year, 
                filter_month=filter_month
            )

            # Calculate current month financial metrics
            current_revenue = financial_data.get('current_month', {}).get('revenue', 0)
            current_expenses = financial_data.get('current_month', {}).get('expenses', 0)
            net_profit = current_revenue - current_expenses
            profit_margin = (net_profit / current_revenue * 100) if current_revenue > 0 else 0

            # Add calculated metrics to financial data
            financial_data.update({
                'revenue': current_revenue,
                'expenses': current_expenses,
                'net_profit': net_profit,
                'profit_margin': profit_margin
            })

            analytics['financial'] = financial_data

        except Exception as e:
            current_app.logger.exception(f"Error loading financial analytics: {e}")
            analytics['financial'] = {
                'revenue': 0,
                'expenses': 0,
                'net_profit': 0,
                'profit_margin': 0,
                'revenue_trend': [],
                'expense_trend': [],
                'profit_trend': []
            }

        return jsonify(analytics)
    except Exception as e:
        current_app.logger.exception(f"Error in payroll_analytics: {e}")
        return jsonify({'error': 'Failed to load analytics', 'message': str(e)}), 500

@admin_bp.route('/payroll/batch/<int:year>/<int:month>')
@login_required
@admin_required
def payroll_batch(year, month):
    try:
        search = request.args.get('search', '')
        
        # Sync totals before processing payroll cycle
        PayrollService.sync_payroll_totals(year, month)
        
        PayrollService.process_payroll_cycle(
            year=year,
            month=month,
            triggered_by='batch_page_load',
            actor_id=current_user.id,
            actor_ip=request.remote_addr
        )

        # Generate financial summary for the month
        try:
            from utils.financial_service import FinancialService
            FinancialService.generate_financial_summary(month, year)
        except Exception as e:
            current_app.logger.warning(f"Failed to generate financial summary: {e}")

        context = _build_payroll_manage_context(year, month, search)
        return render_template('admin/payroll_batch.html', **context)
    except Exception as e:
        current_app.logger.exception(f"Error in payroll_batch route: {e}")
        flash('An error occurred while loading the payroll batch. Please try again.', 'danger')
        return redirect(url_for('admin.payroll'))


@admin_bp.route('/payroll/manage')
@login_required
@admin_required
def payroll_manage():
    try:
        year = request.args.get('year', type=int)
        month = request.args.get('month', type=int)

        if not year or not month:
            year, month = PayrollService.get_cycle_period()

        search = request.args.get('search', '')
        
        # Sync totals before processing payroll cycle
        PayrollService.sync_payroll_totals(year, month)
        
        PayrollService.process_payroll_cycle(
            year=year,
            month=month,
            triggered_by='manage_page_load',
            actor_id=current_user.id,
            actor_ip=request.remote_addr
        )

        # Generate financial summary for the month
        try:
            from utils.financial_service import FinancialService
            FinancialService.generate_financial_summary(month, year)
        except Exception as e:
            current_app.logger.warning(f"Failed to generate financial summary: {e}")

        context = _build_payroll_manage_context(year, month, search)
        return render_template('admin/payroll_batch.html', **context)
    except Exception as e:
        current_app.logger.exception(f"Error in payroll_manage route: {e}")
        flash('An error occurred while loading the payroll management page. Please try again.', 'danger')
        return redirect(url_for('admin.payroll'))


@admin_bp.route('/payroll/manage/recalculate', methods=['POST'])
@login_required
@admin_required
def payroll_manage_recalculate():
    year = request.form.get('year', type=int)
    month = request.form.get('month', type=int)
    next_page = request.form.get('next', '')

    if not year or not month:
        year, month = PayrollService.get_cycle_period()

    PayrollService.process_payroll_cycle(
        year=year,
        month=month,
        triggered_by='manual_recalculate',
        actor_id=current_user.id,
        actor_ip=request.remote_addr
    )
    
    # Sync totals after recalculation to ensure consistency
    PayrollService.sync_payroll_totals(year, month)

    # Generate financial summary after recalculation
    try:
        from utils.financial_service import FinancialService
        FinancialService.generate_financial_summary(month, year)
    except Exception as e:
        current_app.logger.warning(f"Failed to generate financial summary: {e}")
    
    flash(f'Payroll recalculated for {datetime(year, month, 1).strftime("%B %Y")}.', 'success')

    # Preserve current batch page including query parameters so refreshed results show immediately.
    if next_page and next_page.startswith('/'):
        return redirect(next_page)

    return redirect(url_for('admin.payroll_manage', year=year, month=month))

@admin_bp.route('/payroll/payslip/<int:payroll_id>')
@login_required
@admin_required
def view_payslip(payroll_id):
    try:
        payroll = Payroll.query.get_or_404(payroll_id)
        if payroll.payment_status == 'Paid' and not payroll.paid_date:
            payroll.payment_status = 'Unpaid'
        from datetime import datetime
        month_str = datetime(payroll.year, payroll.month, 1).strftime('%B %Y')
        
        advance_payment = request.args.get('advance_payment', type=float, default=0.0) or 0.0
        payroll.advance_payment = max(0.0, advance_payment)
        
        PayrollService.attach_calculated_fields(payroll)
        return render_template('admin/payslip_template.html', p=payroll, month_str=month_str)
    except Exception as e:
        current_app.logger.exception("Error in view_payslip")
        return f"Error: {e}", 500

@admin_bp.route('/payroll/toggle-status/<int:payroll_id>', methods=['POST'])
@login_required
@admin_required
def toggle_payroll_status(payroll_id):
    try:
        payroll = Payroll.query.get_or_404(payroll_id)
        
        # If already marked as 'Paid' with a payment date, cannot change back to 'Unpaid' (permanent)
        if payroll.payment_status == 'Paid' and payroll.paid_date:
            flash('This payslip is already marked as Paid and cannot be changed.', 'warning')
            return redirect(url_for('admin.view_payslip', payroll_id=payroll_id))

        # Correct any stale paid flag if there is no paid date
        if payroll.payment_status == 'Paid' and not payroll.paid_date:
            payroll.payment_status = 'Unpaid'

        # Mark as Paid
        current_status = payroll.payment_status or 'Unpaid'
        if current_status == 'Unpaid':
            payroll.payment_status = 'Paid'
            payroll.status = 'paid'
            payroll.paid_date = get_nepal_time()
            db.session.commit()
            flash(f'Payslip marked as Paid successfully.', 'success')
            
            # Log the action
            db.session.add(AuditLog(
                user_id=current_user.id,
                action=f"Marked payslip as Paid - {payroll.user.profile.full_name} ({payroll.month}/{payroll.year})",
                ip_address=request.remote_addr
            ))
            db.session.commit()
        
        return redirect(url_for('admin.view_payslip', payroll_id=payroll_id))
    except Exception as e:
        current_app.logger.exception("Error in toggle_payroll_status")
        flash(f'Error updating payment status: {str(e)}', 'danger')
        return redirect(url_for('admin.view_payslip', payroll_id=payroll_id))

@admin_bp.route('/payroll/generate', methods=['POST'])
@login_required
@admin_required
def generate_payroll():
    month_str = request.form.get('month')
    if not month_str:
        flash('Please select a month.', 'danger')
        return redirect(url_for('admin.payroll'))
        
    try:
        year, month = map(int, month_str.split('-'))
    except ValueError:
        flash('Invalid month format.', 'danger')
        return redirect(url_for('admin.payroll'))
        
    results = PayrollService.process_payroll_cycle(
        year=year,
        month=month,
        triggered_by='manual',
        actor_id=current_user.id,
        actor_ip=request.remote_addr
    )

    # Generate financial summary after payroll processing
    try:
        from utils.financial_service import FinancialService
        FinancialService.generate_financial_summary(month, year)
    except Exception as e:
        current_app.logger.warning(f"Failed to generate financial summary: {e}")

    total_processed = results['generated'] + results['updated']
    if total_processed > 0:
        msg = (
            f"Success! Generated {results['generated']} new records and updated "
            f"{results['updated']} existing records for {month_str}."
        )
        if results['skipped_paid'] > 0:
            msg += f" (Skipped {results['skipped_paid']} already paid)."
        if results['errors'] > 0:
            msg += f" ({results['errors']} errors logged.)"
        flash(msg, 'success')
    else:
        flash('No eligible users with earnings above zero were found for payroll generation.', 'info')
        
    return redirect(url_for('admin.payroll'))




@admin_bp.route('/audit-logs')
@login_required
@admin_required
def audit_logs():
    logs = AuditLog.query.order_by(AuditLog.timestamp.desc()).all()
    return render_template('admin/audit_logs.html', logs=logs)

@admin_bp.route('/office-settings', methods=['GET', 'POST'])
@login_required
@admin_required
def office_settings():
    settings = OfficeSettings.query.first()
    if request.method == 'POST':
        if not settings:
            settings = OfficeSettings()
            db.session.add(settings)
        
        try:
            lat = request.form.get('latitude')
            lng = request.form.get('longitude')
            rad = request.form.get('radius')
            
            if lat: settings.latitude = float(lat)
            if lng: settings.longitude = float(lng)
            if rad: settings.radius = int(rad)
            settings.office_ip = request.form.get('office_ip', '')
            
            # Only update auto-checkout if submitting the second form (which has auto_checkout_time)
            if 'auto_checkout_time' in request.form:
                settings.auto_checkout_enabled = request.form.get('auto_checkout_enabled') == 'on'
                checkout_time_str = request.form.get('auto_checkout_time')
                if checkout_time_str:
                    from datetime import datetime
                    settings.auto_checkout_time = datetime.strptime(checkout_time_str, '%H:%M').time()
                
                # Email reminder settings
                settings.email_reminders_enabled = request.form.get('email_reminders_enabled') == 'on'
                reminder_minutes = request.form.get('reminder_time_before_checkout')
                if reminder_minutes:
                    settings.reminder_time_before_checkout = int(reminder_minutes)
            
            # Create AuditLog for updating settings
            log = AuditLog(
                user_id=current_user.id,
                action="Updated Office Settings (Geofence & Auto-Checkout)",
                ip_address=request.remote_addr
            )
            db.session.add(log)
            
            db.session.commit()
            
            # Restart scheduler with new settings
            if hasattr(current_app, 'scheduler') and current_app.scheduler:
                current_app.scheduler.restart()
            
            flash('Office settings updated successfully.', 'success')
        except ValueError as e:
            flash(f'Invalid input: {str(e)}', 'danger')
            
        return redirect(url_for('admin.office_settings'))
        
    allowed_locations = AllowedLocation.query.all()
    return render_template('admin/settings.html', settings=settings, allowed_locations=allowed_locations)

@admin_bp.route('/allowed-locations/add', methods=['POST'])
@login_required
@admin_required
def add_allowed_location():
    name = request.form.get('name', '').strip()
    lat = request.form.get('latitude', '').strip()
    lng = request.form.get('longitude', '').strip()
    radius = request.form.get('radius', '100').strip()

    if not name or not lat or not lng:
        flash('Name, latitude, and longitude are required for a secondary location.', 'danger')
        return redirect(url_for('admin.office_settings'))

    try:
        loc = AllowedLocation(
            name=name,
            latitude=float(lat),
            longitude=float(lng),
            radius=int(radius),
            is_active=True
        )
        db.session.add(loc)
        db.session.add(AuditLog(
            user_id=current_user.id,
            action=f"Added secondary office location: {name}",
            ip_address=request.remote_addr
        ))
        db.session.commit()
        flash(f'Secondary location "{name}" added successfully.', 'success')
    except ValueError:
        flash('Invalid coordinates or radius value.', 'danger')

    return redirect(url_for('admin.office_settings'))


@admin_bp.route('/allowed-locations/delete/<int:loc_id>', methods=['POST'])
@login_required
@admin_required
def delete_allowed_location(loc_id):
    loc = AllowedLocation.query.get_or_404(loc_id)
    name = loc.name
    db.session.delete(loc)
    db.session.add(AuditLog(
        user_id=current_user.id,
        action=f"Deleted secondary office location: {name}",
        ip_address=request.remote_addr
    ))
    db.session.commit()
    flash(f'Location "{name}" removed.', 'info')
    return redirect(url_for('admin.office_settings'))


@admin_bp.route('/allowed-locations/toggle/<int:loc_id>', methods=['POST'])
@login_required
@admin_required
def toggle_allowed_location(loc_id):
    loc = AllowedLocation.query.get_or_404(loc_id)
    loc.is_active = not loc.is_active
    db.session.commit()
    status = 'enabled' if loc.is_active else 'disabled'
    flash(f'Location "{loc.name}" {status}.', 'success')
    return redirect(url_for('admin.office_settings'))


@admin_bp.route('/add-employee', methods=['GET', 'POST'])
@login_required
@admin_required
def add_employee():
    if request.method == 'POST':
        return _internal_onboard_logic(request, role='employee', target='admin.employees')
    return render_template('admin/add_employee.html')

@admin_bp.route('/add-intern', methods=['GET', 'POST'])
@login_required
@admin_required
def add_intern():
    if request.method == 'POST':
        return _internal_onboard_logic(request, role='intern', target='admin.interns')
    return render_template('admin/add_intern.html')

@admin_bp.route('/add-student', methods=['GET', 'POST'])
@login_required
@admin_required
def add_student():
    if request.method == 'POST':
        return _internal_onboard_logic(request, role='student', target='admin.students')
    return render_template('admin/add_student.html')

def _internal_onboard_logic(request, role, target):
    login_email = request.form.get('login_email')
    password = request.form.get('password')
    first_name = request.form.get('first_name')
    middle_name = request.form.get('middle_name', '').strip()
    last_name = request.form.get('last_name')
    personal_email = request.form.get('personal_email')
    department = request.form.get('department')
    designation = request.form.get('designation')
    phone_digits = request.form.get('phone_digits', '').strip()
    is_valid_phone, normalized_phone = validate_nepal_phone_digits(phone_digits)
    if not is_valid_phone:
        flash('Please enter a valid phone number. It must be 10 digits and start with 98 or 97 after +977.', 'danger')
        return redirect(url_for(f'admin.add_{role}'))
    phone = f"+977 {normalized_phone}"
    salary = float(request.form.get('salary', 0))
    ot_rate = float(request.form.get('ot_rate', 0))
    leave_days = float(request.form.get('leave_days', 15.0))
    
    # Workshop fields for students
    workshop_end_date = None
    payment_status = None
    hra_amount = float(request.form.get('hra', 0)) # Used as Paid Amount for students
    
    if role == 'student':
        joining_date_str = request.form.get('workshop_start_date')
        workshop_end_date_str = request.form.get('workshop_end_date')
        if joining_date_str:
            joining_date = datetime.strptime(joining_date_str, '%Y-%m-%d').date()
        else:
            joining_date = get_nepal_time().date()
            
        if workshop_end_date_str:
            workshop_end_date = datetime.strptime(workshop_end_date_str, '%Y-%m-%d').date()
            
        payment_status = request.form.get('payment_status', 'Unpaid')
        workshop_status = request.form.get('workshop_status', 'Ongoing')
    else:
        joining_date = get_nepal_time().date()
        workshop_status = 'N/A' # Not applicable for employees/interns
    
    # Validation
    if not login_email.endswith('@ems.com'):
        flash('Login email must end with @ems.com', 'danger')
        return redirect(url_for(f'admin.add_{role}'))
        
        
    if User.query.filter_by(email=login_email).first():
        flash('User already exists with this login email.', 'danger')
        return redirect(url_for(f'admin.add_{role}'))

    # Security: Backend Password Strength Validation
    is_valid, msg = validate_password_strength(password)
    if not is_valid:
        flash(msg, 'danger')
        return redirect(url_for(f'admin.add_{role}'))

    # 1. Create User
    new_user = User(
        email=login_email,
        password_hash=generate_password_hash(password, method='pbkdf2:sha256'),
        role=role
    )
    db.session.add(new_user)
    db.session.flush() # Get user ID
    
    # 2. Generate Staff ID
    staff_id = generate_staff_id(role, department)
    
    # 3. Create Profile
    full_name = f"{first_name} {middle_name} {last_name}" if middle_name else f"{first_name} {last_name}"
    
    new_profile = EmployeeProfile(
        user_id=new_user.id,
        full_name=full_name,
        employee_id=staff_id,
        department=department,
        designation=designation,
        joining_date=joining_date,
        base_salary=salary,
        hra=hra_amount,
        personal_email=personal_email,
        phone=phone,
        overtime_rate=ot_rate,
        leave_allowance=leave_days,
        workshop_end_date=workshop_end_date,
        payment_status=payment_status,
        workshop_status=workshop_status
    )
    db.session.add(new_profile)
    db.session.commit()
    
    # Sync to Excel
    ExcelSyncService.sync_role_to_excel(role)
    
    flash(f'Staff created successfully! ID: {staff_id}', 'success')
    return redirect(url_for(target))

@admin_bp.route('/staff/edit/<int:user_id>', methods=['GET', 'POST'])
@login_required
@admin_required
def edit_staff(user_id):
    user = User.query.get_or_404(user_id)
    profile = user.profile
    
    if request.method == 'POST':
        first_name = request.form.get('first_name')
        middle_name = request.form.get('middle_name', '').strip()
        last_name = request.form.get('last_name')
        personal_email = request.form.get('personal_email')
        department = request.form.get('department')
        designation = request.form.get('designation')
        phone_digits = request.form.get('phone_digits', '').strip()
        is_valid_phone, normalized_phone = validate_nepal_phone_digits(phone_digits)
        if not is_valid_phone:
            flash('Please enter a valid phone number. It must be 10 digits and start with 98 or 97 after +977.', 'danger')
            return redirect(url_for('admin.edit_staff', user_id=user_id))
        phone = f"+977 {normalized_phone}"
        salary = float(request.form.get('salary', 0))
        ot_rate = float(request.form.get('ot_rate', 0))
        leave_days = float(request.form.get('leave_days', 15.0))
        role = request.form.get('role', 'employee')
        
        # Student specific fields
        hra_amount = float(request.form.get('hra', 0))
        if role == 'student':
            joining_date_str = request.form.get('workshop_start_date')
            workshop_end_date_str = request.form.get('workshop_end_date')
            if joining_date_str:
                profile.joining_date = datetime.strptime(joining_date_str, '%Y-%m-%d').date()
            if workshop_end_date_str:
                profile.workshop_end_date = datetime.strptime(workshop_end_date_str, '%Y-%m-%d').date()
            profile.payment_status = request.form.get('payment_status', 'Unpaid')
            profile.workshop_status = request.form.get('workshop_status', 'Ongoing')
        
        # We don't allow changing login email easily here for security/complexity
        # but we update the profile and user role
        user.role = role
        
        profile.full_name = f"{first_name} {middle_name} {last_name}" if middle_name else f"{first_name} {last_name}"
        profile.personal_email = personal_email
        profile.department = department
        profile.designation = designation
        profile.phone = phone
        profile.base_salary = salary
        profile.hra = hra_amount
        profile.overtime_rate = ot_rate
        profile.leave_allowance = leave_days
        
        db.session.commit()

        PayrollService.refresh_upcoming_payroll_for_user(
            user.id,
            actor_id=current_user.id,
            actor_ip=request.remote_addr
        )
        
        # Enhanced Audit Logging
        db.session.add(AuditLog(
            user_id=current_user.id,
            action=f"Updated Staff Profile: {profile.full_name} ({profile.employee_id})",
            details=f"Edited by {current_user.email}. Fields updated: Name, Dept, Desig, Salary, etc.",
            ip_address=request.remote_addr
        ))
        db.session.commit()
        
        # Sync to Excel
        ExcelSyncService.sync_role_to_excel(role)
        
        flash('Staff profile updated successfully.', 'success')
        
        if role == 'employee':
            target = 'admin.employees'
        elif role == 'intern':
            target = 'admin.interns'
        else:
            target = 'admin.students'
        return redirect(url_for(target))
        
    return render_template('admin/edit_staff.html', user=user, profile=profile)

@admin_bp.route('/staff/reset-password/<int:user_id>', methods=['POST'])
@login_required
@admin_required
def reset_staff_password(user_id):
    user = User.query.get_or_404(user_id)
    if user.role == 'admin':
        flash('Cannot reset the password for an admin account from this tool.', 'danger')
        return redirect(url_for('admin.edit_staff', user_id=user_id))

    user.password_hash = generate_password_hash(DEFAULT_USER_PASSWORD, method='pbkdf2:sha256')
    user.otp = None
    user.otp_expiry = None

    db.session.add(AuditLog(
        user_id=current_user.id,
        action=f"Reset Password: {user.profile.full_name if user.profile else user.email}",
        details=f"Password reset to the default onboarding password for {user.email}.",
        ip_address=request.remote_addr
    ))
    db.session.commit()

    flash(f"Password reset successfully. Temporary default password: {DEFAULT_USER_PASSWORD}", 'success')
    return redirect(url_for('admin.edit_staff', user_id=user_id))

@admin_bp.route('/staff/delete/<int:user_id>', methods=['POST'])
@login_required
@admin_required
def delete_staff(user_id):
    user = User.query.get_or_404(user_id)
    if user.role == 'admin':
        flash('Cannot delete admin user.', 'danger')
        return redirect(url_for('admin.employees'))
        
    role = user.role
    db.session.delete(user) # Cascade delete will handle profile
    
    # Enhanced Audit Logging
    db.session.add(AuditLog(
        user_id=current_user.id,
        action=f"Deleted User: {user.email} (Role: {role})",
        ip_address=request.remote_addr
    ))
    db.session.commit()
    
    # Sync to Excel
    ExcelSyncService.sync_role_to_excel(role)
    
    flash('Staff member deleted successfully.', 'success')
    
    if role == 'employee':
        target = 'admin.employees'
    elif role == 'intern':
        target = 'admin.interns'
    else:
        target = 'admin.students'
    return redirect(url_for(target))

@admin_bp.route('/staff/complete/<int:user_id>')
@login_required
@admin_required
def complete_role(user_id):
    user = User.query.get_or_404(user_id)
    profile = user.profile
    
    if user.role not in ['student', 'intern']:
        flash('Only students or interns can be marked as completed.', 'warning')
        return redirect(url_for('admin.employees'))
        
    if user.role == 'student':
        remaining = (profile.base_salary or 0) - (profile.hra or 0)
        if remaining > 0:
            flash(f'Cannot complete workshop. Student has a remaining balance of Rs.{remaining:,.2f}', 'danger')
            return redirect(url_for('admin.students'))
        msg = f'Workshop marked as completed for {profile.full_name}. Student account is now inactive.'
    else:
        # For interns, we just complete without balance check
        msg = f'Internship marked as completed for {profile.full_name}. Intern account is now inactive.'
        
    profile.workshop_status = 'Completed'
    user.is_active = False # Disable account after completion
    
    # Enhanced Audit Logging
    db.session.add(AuditLog(
        user_id=current_user.id,
        action=f"Marked Role Completed: {profile.full_name} ({user.role})",
        details=f"Account deactivated for {profile.full_name}.",
        ip_address=request.remote_addr
    ))
    db.session.commit()
    
    # Sync to Excel
    ExcelSyncService.sync_role_to_excel(user.role)
    
    flash(msg, 'success')
    target = 'admin.students' if user.role == 'student' else 'admin.interns'
    return redirect(url_for(target))

@admin_bp.route('/api/stats')
@login_required
@admin_required
def get_stats():
    now = get_nepal_time()
    today = now.date()

    # ── 1. Head Counts ─────────────────────────────────────────────────────────
    total_employees = User.query.filter_by(role='employee', is_active=True).count()
    total_interns   = User.query.filter_by(role='intern',   is_active=True).count()
    total_students  = User.query.filter_by(role='student',  is_active=True).count()
    total_active    = total_employees + total_interns + total_students

    # ── 1b. All-time totals (active + inactive) ────────────────────────────────
    all_employees   = User.query.filter_by(role='employee').count()
    all_interns     = User.query.filter_by(role='intern').count()
    all_students    = User.query.filter_by(role='student').count()
    
    # ── 1c. Inactive counts and new metrics ────────────────────────────────────
    inactive_employees = all_employees - total_employees
    inactive_interns   = all_interns - total_interns
    inactive_students  = all_students - total_students

    completed_courses = User.query.join(EmployeeProfile).filter(EmployeeProfile.workshop_status == 'Completed').count()
    removed_staff = User.query.filter(User.is_active == False).count() - completed_courses

    # ── 2. Attendance Today ────────────────────────────────────────────────────
    start_of_day = datetime.combine(today, datetime.min.time())
    end_of_day   = datetime.combine(today, datetime.max.time())

    present_user_ids = {
        user_id for (user_id,) in db.session.query(Attendance.user_id).filter(
            Attendance.check_in >= start_of_day,
            Attendance.check_in <= end_of_day,
            ~Attendance.status.in_(['absent', 'holiday'])
        ).distinct().all()
    }

    holiday_user_ids = {
        user_id for (user_id,) in db.session.query(Attendance.user_id).filter(
            Attendance.check_in >= start_of_day,
            Attendance.check_in <= end_of_day,
            db.or_(Attendance.status == 'holiday', Attendance.is_weekend == True)
        ).distinct().all()
    }

    leave_user_ids = {
        user_id for (user_id,) in db.session.query(LeaveRequest.user_id).filter(
            LeaveRequest.status == 'approved',
            LeaveRequest.start_date <= today,
            LeaveRequest.end_date >= today
        ).distinct().all()
    }

    if today.weekday() == 5:
        holiday_today = max(total_active - len(leave_user_ids), 0)
        absent_today = 0
        attendance_today = len(present_user_ids)
    else:
        accounted_ids = present_user_ids.union(holiday_user_ids, leave_user_ids)
        absent_today = max(total_active - len(accounted_ids), 0)
        holiday_today = len(holiday_user_ids)
        attendance_today = len(present_user_ids)

    attendance_rate = round((attendance_today / total_active * 100), 1) if total_active > 0 else 0.0

    # ── 3. Leaves ──────────────────────────────────────────────────────────────
    pending_leaves  = LeaveRequest.query.filter_by(status='pending').count()
    approved_leaves = LeaveRequest.query.filter_by(status='approved').count()
    on_leave_today  = LeaveRequest.query.filter(
        LeaveRequest.status == 'approved',
        LeaveRequest.start_date <= today,
        LeaveRequest.end_date >= today
    ).count()
    rejected_leaves = LeaveRequest.query.filter_by(status='rejected').count()
    total_decided   = approved_leaves + rejected_leaves
    leave_approval_rate = round((approved_leaves / total_decided * 100), 1) if total_decided > 0 else 0.0

    # ── 4. Open Queries ────────────────────────────────────────────────────────
    open_queries = ContactQuery.query.count()

    # ── 5. New Joinings This Month ─────────────────────────────────────────────
    new_joinings = db.session.query(EmployeeProfile.id).join(User).filter(
        db.extract('month', EmployeeProfile.joining_date) == today.month,
        db.extract('year',  EmployeeProfile.joining_date) == today.year,
        User.is_active == True
    ).count()

    # ── 6. Completed Interns & Students (workshop_status = 'Completed') ────────────
    completed_interns = db.session.query(EmployeeProfile.id).join(User).filter(
        User.role == 'intern',
        EmployeeProfile.workshop_status == 'Completed'
    ).count()

    completed_students = db.session.query(EmployeeProfile.id).join(User).filter(
        User.role == 'student',
        EmployeeProfile.workshop_status == 'Completed'
    ).count()

    # ── 7. Department Distribution (Doughnut) ──────────────────────────────────
    dept_query = db.session.query(
        EmployeeProfile.department,
        db.func.count(EmployeeProfile.id)
    ).join(User).filter(User.is_active == True).group_by(EmployeeProfile.department).all()

    dept_labels = [d[0] for d in dept_query if d[0]]
    dept_values = [d[1] for d in dept_query if d[0]]

    # ── 8. Monthly Leave Trends (Bar – last 6 months) ─────────────────────────
    leave_trends  = []
    trend_labels  = []
    for i in range(5, -1, -1):
        target_month = now.month - i
        target_year  = now.year
        while target_month <= 0:
            target_month += 12
            target_year  -= 1
        month_name = datetime(target_year, target_month, 1).strftime('%b')
        count = LeaveRequest.query.filter(
            db.extract('month', LeaveRequest.applied_on) == target_month,
            db.extract('year',  LeaveRequest.applied_on) == target_year,
            LeaveRequest.status == 'approved'
        ).count()
        trend_labels.append(month_name)
        leave_trends.append(count)

    # ── 9. Recent Activity Feed (last 6 audit logs) ───────────────────────────
    recent_logs = AuditLog.query.order_by(AuditLog.timestamp.desc()).limit(6).all()
    recent_activity = []
    for log in recent_logs:
        actor = User.query.get(log.user_id)
        actor_name = (actor.profile.full_name.split()[0] if actor and actor.profile and actor.profile.full_name else (actor.email.split('@')[0] if actor else 'System'))
        recent_activity.append({
            'action':  log.action,
            'actor':   actor_name,
            # Use 12-hour format with AM/PM for display
            'time':    log.timestamp.strftime('%d %b, %I:%M %p') if log.timestamp else '—',
            'ip':      log.ip_address or '—'
        })

    # ── 10. Upcoming Approved Leaves (next 7 days) ────────────────────────────
    next_week = today + timedelta(days=7)
    upcoming_leaves_q = LeaveRequest.query.join(User).join(EmployeeProfile).filter(
        LeaveRequest.status == 'approved',
        LeaveRequest.start_date >= today,
        LeaveRequest.start_date <= next_week
    ).order_by(LeaveRequest.start_date.asc()).limit(6).all()

    upcoming_leaves = []
    for lr in upcoming_leaves_q:
        profile = lr.user.profile
        upcoming_leaves.append({
            'name':       profile.full_name if profile else lr.user.email,
            'dept':       profile.department if profile else '—',
            'leave_type': lr.leave_type.title() if lr.leave_type else '—',
            'start':      lr.start_date.strftime('%d %b'),
            'end':        lr.end_date.strftime('%d %b'),
        })

    return jsonify({
        # Head counts (active)
        'total_employees':      total_employees,
        'total_interns':        total_interns,
        'total_students':       total_students,
        'total_active':         total_active,
        # Head counts (all-time totals)
        'all_employees':        all_employees,
        'all_interns':          all_interns,
        'all_students':         all_students,
        # Inactive counts
        'inactive_employees':   inactive_employees,
        'inactive_interns':     inactive_interns,
        'inactive_students':    inactive_students,
        # Completed
        'completed_interns':    completed_interns,
        'completed_students':   completed_students,
        'completed_courses':    completed_courses,
        'removed_staff':        removed_staff,
        # Attendance
        'attendance_today':     attendance_today,
        'absent_today':         absent_today,
        'holiday_today':        holiday_today,
        'attendance_rate':      attendance_rate,
        # Leaves
        'pending_leaves':       pending_leaves,
        'on_leave_today':       on_leave_today,
        'leave_approval_rate':  leave_approval_rate,
        # Operations
        'open_queries':         open_queries,
        'new_joinings':         new_joinings,
        # Charts
        'dept_labels':          dept_labels,
        'dept_values':          dept_values,
        'trend_labels':         trend_labels,
        'leave_trends':         leave_trends,
        # Feeds
        'recent_activity':      recent_activity,
        'upcoming_leaves':      upcoming_leaves,
    })

@admin_bp.route('/api/dashboard/details')
@login_required
@admin_required
def dashboard_details():
    detail_type = request.args.get('type')
    now = get_nepal_time()
    today = now.date()
    start_of_day = datetime.combine(today, datetime.min.time())
    end_of_day = datetime.combine(today, datetime.max.time())
    
    users = []
    
    if detail_type == 'employees':
        users = User.query.filter_by(role='employee', is_active=True).all()
    elif detail_type == 'interns':
        users = User.query.filter_by(role='intern', is_active=True).all()
    elif detail_type == 'students':
        users = User.query.filter_by(role='student', is_active=True).all()
    elif detail_type == 'completed_students':
        users = User.query.join(EmployeeProfile).filter(
            User.role == 'student',
            EmployeeProfile.workshop_status == 'Completed'
        ).all()
    elif detail_type == 'completed_interns':
        users = User.query.join(EmployeeProfile).filter(
            User.role == 'intern',
            EmployeeProfile.workshop_status == 'Completed'
        ).all()
    elif detail_type == 'completed_all':
        users = User.query.join(EmployeeProfile).filter(
            User.role.in_(['student', 'intern']),
            EmployeeProfile.workshop_status == 'Completed'
        ).all()
    elif detail_type == 'removed_staff':
        completed_ids = db.session.query(User.id).join(EmployeeProfile).filter(
            EmployeeProfile.workshop_status == 'Completed'
        ).subquery()
        users = User.query.filter(
            User.is_active == False,
            ~User.id.in_(completed_ids)
        ).all()
    elif detail_type == 'present':
        attendance_user_ids = db.session.query(Attendance.user_id).filter(
            Attendance.check_in >= start_of_day,
            Attendance.check_in <= end_of_day,
            ~Attendance.status.in_(['absent', 'holiday'])
        )
        users = User.query.filter(User.id.in_(attendance_user_ids)).all()
    elif detail_type == 'leave':
        leave_user_ids = db.session.query(LeaveRequest.user_id).filter(
            LeaveRequest.status == 'approved',
            LeaveRequest.start_date <= today,
            LeaveRequest.end_date >= today
        ).distinct()
        users = User.query.filter(User.id.in_(leave_user_ids)).all()
    elif detail_type == 'absent':
        active_user_ids = {
            user.id for user in User.query.filter(User.is_active == True, User.role != 'admin').all()
        }
        leave_user_ids = {
            user_id for (user_id,) in db.session.query(LeaveRequest.user_id).filter(
                LeaveRequest.status == 'approved',
                LeaveRequest.start_date <= today,
                LeaveRequest.end_date >= today
            ).distinct().all()
        }
        present_user_ids = {
            user_id for (user_id,) in db.session.query(Attendance.user_id).filter(
                Attendance.check_in >= start_of_day,
                Attendance.check_in <= end_of_day,
                ~Attendance.status.in_(['absent', 'holiday'])
            ).distinct().all()
        }
        holiday_user_ids = {
            user_id for (user_id,) in db.session.query(Attendance.user_id).filter(
                Attendance.check_in >= start_of_day,
                Attendance.check_in <= end_of_day,
                db.or_(Attendance.status == 'holiday', Attendance.is_weekend == True)
            ).distinct().all()
        }
        absent_user_ids = active_user_ids - present_user_ids - holiday_user_ids - leave_user_ids
        if today.weekday() == 5:
            absent_user_ids = set()
        users = User.query.filter(User.id.in_(absent_user_ids)).all()
    elif detail_type == 'holiday':
        leave_user_ids = {
            user_id for (user_id,) in db.session.query(LeaveRequest.user_id).filter(
                LeaveRequest.status == 'approved',
                LeaveRequest.start_date <= today,
                LeaveRequest.end_date >= today
            ).distinct().all()
        }
        if today.weekday() == 5:
            holiday_user_ids = {
                user.id for user in User.query.filter(User.is_active == True, User.role != 'admin').filter(~User.id.in_(leave_user_ids)).all()
            }
        else:
            holiday_user_ids = {
                user_id for (user_id,) in db.session.query(Attendance.user_id).filter(
                    Attendance.check_in >= start_of_day,
                    Attendance.check_in <= end_of_day,
                    db.or_(Attendance.status == 'holiday', Attendance.is_weekend == True)
                ).distinct().all()
            }
        users = User.query.filter(User.id.in_(holiday_user_ids)).all()
    elif detail_type == 'joinings':
        users = User.query.join(EmployeeProfile).filter(
            db.extract('month', EmployeeProfile.joining_date) == today.month,
            db.extract('year',  EmployeeProfile.joining_date) == today.year,
            User.is_active == True
        ).all()
        
    result = []
    
    if detail_type == 'queries':
        queries = ContactQuery.query.all()
        for q in queries:
            result.append({
                'name': q.name or 'Anonymous',
                'role': q.category or 'Query',
                'course': q.subject or 'No Subject provided',
                'message': q.message or ''
            })
        return jsonify(result)

    for u in users:
        result.append({
            'name': u.profile.full_name if u.profile else u.email,
            'role': u.role.capitalize(),
            'course': u.profile.designation if u.role == 'student' and u.profile else (u.profile.department if u.profile else 'N/A')
        })
        
    return jsonify(result)

# ─── Staff Detail Views (New) ────────────────────────────────────────────────
@admin_bp.route('/staff/attendance/<int:user_id>')
@login_required
@admin_required
def staff_attendance_detail(user_id):
    user = User.query.get_or_404(user_id)
    return render_template('admin/staff_attendance_detail.html', user=user)

@admin_bp.route('/staff/payroll/<int:user_id>')
@login_required
@admin_required
def staff_payroll_detail(user_id):
    user = User.query.get_or_404(user_id)
    payrolls = Payroll.query.filter_by(user_id=user_id).order_by(Payroll.year.desc(), Payroll.month.desc()).all()
    for payroll in payrolls:
        salary_data = PayrollService.calculate_monthly_salary(payroll.user_id, payroll.month, payroll.year, force_zero_deductions=False)
        if salary_data:
            payroll.display_deductions = salary_data.get('deductions', payroll.lop_deduction or 0.0)
            payroll.display_overtime_earnings = salary_data.get('overtime_earnings', payroll.overtime_earnings or 0.0)
            payroll.monthly_allocation = salary_data.get('monthly_allocation', 0.0)
            # Net Monthly Salary = (base + snapshot_HRA + snapshot_Auto + OT) - deductions
            net_monthly_before_deductions = (
                (payroll.monthly_allocation or 0) +
                (payroll.snapshot_hra or 0) +
                (payroll.snapshot_transport or 0) +
                (payroll.display_overtime_earnings or 0)
            )
            payroll.display_net_pay = max(0, net_monthly_before_deductions - payroll.display_deductions)
        else:
            payroll.display_net_pay = payroll.net_pay or 0.0
    return render_template('admin/staff_payroll_detail.html', user=user, payrolls=payrolls)

@admin_bp.route('/api/staff/attendance-events/<int:user_id>')
@login_required
@admin_required
def staff_attendance_events(user_id):
    start_str = request.args.get('start')
    end_str = request.args.get('end')
    
    events = []
    
    # 1. Fetch Attendance Records
    query = Attendance.query.filter_by(user_id=user_id)
    start_date = None
    end_date = None
    if start_str and end_str:
        try:
            start_date = datetime.fromisoformat(start_str.replace('Z', '+00:00')).date()
            end_date = datetime.fromisoformat(end_str.replace('Z', '+00:00')).date()
            try:
                AttendanceService.sync_saturdays_for_period(user_id, start_date, end_date)
            except Exception as e:
                current_app.logger.warning(f"Saturday sync failed for user {user_id}: {e}")
            query = query.filter(db.func.date(Attendance.check_in) >= start_date, 
                                 db.func.date(Attendance.check_in) <= end_date)
        except (ValueError, TypeError):
            pass
                             
    attendances = query.all()
    
    for att in attendances:
        color = '#10b981' # Green (present by default)
        title = att.status.title()
        
        if att.status == 'absent':
            color = '#ef4444' # Red
        elif att.is_weekend and att.status != 'absent':
            color = '#3b82f6' # Blue for holiday
            title = 'Holiday'
        elif att.status in ['half-day', 'late']:
            color = '#f59e0b' # Amber
            
        # Add Time Information to Title
        if att.check_in and att.status not in ['absent', 'holiday', 'weekend']:
            # Use consistent 12-hour formatting across admin calendar titles
            time_str = att.check_in.strftime('%I:%M %p')
            if att.check_out:
                time_str += f" - {att.check_out.strftime('%I:%M %p')}"
            title = f"{title} - {time_str}"
            
        event = {
            'id': f'att_{att.id}',
            'title': title,
            'color': color,
        }
        
        if att.check_out:
            event['start'] = att.check_in.isoformat()
            event['end'] = att.check_out.isoformat()
            event['allDay'] = False
        elif att.status not in ['absent', 'weekend']:
            event['start'] = att.check_in.isoformat()
            event['allDay'] = False
        else: # absent / weekend fallback to all day
            event['start'] = att.check_in.strftime('%Y-%m-%d')
            event['allDay'] = True
            
        events.append(event)
        
    # 2. Fetch Approved Leave Requests
    leave_query = LeaveRequest.query.filter_by(user_id=user_id, status='approved')
    if start_str and end_str and start_date and end_date:
        try:
            leave_query = leave_query.filter(
                db.or_(
                    db.and_(LeaveRequest.start_date >= start_date, LeaveRequest.start_date <= end_date),
                    db.and_(LeaveRequest.end_date >= start_date, LeaveRequest.end_date <= end_date)
                )
            )
        except (ValueError, TypeError):
            pass
        
    approved_leaves = leave_query.all()
    for leave in approved_leaves:
        events.append({
            'id': f'leave_{leave.id}',
            'title': f'On Leave ({leave.leave_type.title()})',
            'start': leave.start_date.isoformat(),
            'end': (leave.end_date + timedelta(days=1)).isoformat(),
            'color': '#8b5cf6', # Purple
            'allDay': True
        })
        
    return jsonify(events)


@admin_bp.route('/staff/reactivate/<int:user_id>', methods=['POST'])
@login_required
@admin_required
def reactivate_staff(user_id):
    """Reactivate a previously deactivated student or intern account."""
    user = User.query.get_or_404(user_id)
    if user.role == 'admin':
        flash('Cannot modify admin accounts.', 'danger')
        return redirect(url_for('admin.employees'))

    profile = user.profile
    user.is_active = True
    if profile and profile.workshop_status == 'Completed':
        profile.workshop_status = 'Ongoing'

    db.session.add(AuditLog(
        user_id=current_user.id,
        action=f"Reactivated Account: {profile.full_name if profile else user.email} (Role: {user.role})",
        details=f"Account manually reactivated by {current_user.email}.",
        ip_address=request.remote_addr
    ))
    db.session.commit()

    ExcelSyncService.sync_role_to_excel(user.role)

    flash(f'Account for {profile.full_name if profile else user.email} has been reactivated.', 'success')
    return redirect(request.referrer or url_for('admin.employees'))

@admin_bp.route('/overtime-requests')
@login_required
@admin_required
def overtime_requests():
    status_filter = request.args.get('status', '')
    query = OvertimeRequest.query
    
    if status_filter:
        query = query.filter_by(status=status_filter)
    
    overtime_requests = query.order_by(OvertimeRequest.applied_on.desc()).all()
    return render_template('admin/overtime_requests.html', overtime_requests=overtime_requests, status_filter=status_filter)

@admin_bp.route('/overtime/approve/<int:request_id>', methods=['POST'])
@login_required
@admin_required
def approve_overtime(request_id):
    from database.models import OvertimeRequest
    ot_request = OvertimeRequest.query.get_or_404(request_id)
    
    if ot_request.status != 'pending':
        flash('This request has already been processed.', 'warning')
        return redirect(url_for('admin.overtime_requests'))
    
    ot_request.status = 'approved'
    ot_request.approved_by = current_user.id
    ot_request.approved_at = get_nepal_time()

    if ot_request.overtime_type == 'remote':
        user = ot_request.user
        login_time = get_nepal_time()
        bypass_end = login_time + timedelta(hours=ot_request.hours)
        user.overtime_bypass_until = bypass_end

        notice = Notice(
            title="Overtime Request Approved - Location Bypass Activated",
            content=f"Your remote overtime request for {ot_request.hours} hours has been approved. Location bypass is active from {login_time.strftime('%I:%M %p %d %b')} until {bypass_end.strftime('%I:%M %p %d %b')}.",
            target_user_id=user.id,
            is_active=True,
            notice_type="System Alert"
        )
        db.session.add(notice)
    
    db.session.add(AuditLog(
        user_id=current_user.id,
        action=f"Approved Overtime Request #{ot_request.id} for {ot_request.user.email}",
        ip_address=request.remote_addr
    ))
    db.session.commit()
    
    flash(f'Overtime request approved for {ot_request.user.email}.', 'success')
    return redirect(url_for('admin.overtime_requests'))

@admin_bp.route('/overtime/reject/<int:request_id>', methods=['POST'])
@login_required
@admin_required
def reject_overtime(request_id):
    from database.models import OvertimeRequest
    ot_request = OvertimeRequest.query.get_or_404(request_id)
    
    if ot_request.status != 'pending':
        flash('This request has already been processed.', 'warning')
        return redirect(url_for('admin.overtime_requests'))
    
    ot_request.status = 'rejected'
    ot_request.approved_by = current_user.id
    ot_request.approved_at = get_nepal_time()
    
    user = ot_request.user
    notice = Notice(
        title="Overtime Request Rejected",
        content=f"Your overtime request for {ot_request.hours} hours on {ot_request.requested_date.strftime('%d %b %Y')} has been rejected by admin.",
        target_user_id=user.id,
        is_active=True,
        notice_type="System Alert"
    )
    db.session.add(notice)
    
    db.session.add(AuditLog(
        user_id=current_user.id,
        action=f"Rejected Overtime Request #{ot_request.id} for {ot_request.user.email}",
        ip_address=request.remote_addr
    ))
    db.session.commit()
    
    flash(f'Overtime request rejected for {ot_request.user.email}.', 'success')
    return redirect(url_for('admin.overtime_requests'))

@admin_bp.route('/grant-location-bypass', methods=['POST'])
@login_required
@admin_required
def grant_location_bypass():
    data = request.get_json()
    user_id = data.get('user_id')
    hours = float(data.get('hours', 24))
    
    user = User.query.get_or_404(user_id)
    
    if hours == -1:
        user.location_bypass_until = datetime(2099, 12, 31, 23, 59, 59)
        bypass_text = "until manually revoked"
    else:
        user.location_bypass_until = get_nepal_time() + timedelta(hours=hours)
        bypass_text = user.location_bypass_until.strftime('%I:%M %p %d %b')
    
    notice = Notice(
        title="Location Bypass Granted",
        content=f"Admin has granted you a location bypass. You can now check in from any location {bypass_text}.",
        target_user_id=user.id,
        is_active=True,
        notice_type="System Alert"
    )
    db.session.add(notice)
    
    db.session.add(AuditLog(
        user_id=current_user.id,
        action=f"Granted Location Bypass ({hours}h) to {user.email}" if hours != -1 else f"Granted Unlimited Location Bypass to {user.email}",
        ip_address=request.remote_addr
    ))
    db.session.commit()
    
    return jsonify({'success': True, 'message': f'Location bypass granted to {user.email} ({hours}h)' if hours != -1 else 'Location bypass granted to ' + user.email})


@admin_bp.route('/revoke-location-bypass', methods=['POST'])
@login_required
@admin_required
def revoke_location_bypass():
    data = request.get_json()
    user_id = data.get('user_id')

    user = User.query.get_or_404(user_id)
    user.location_bypass_until = None

    notice = Notice(
        title="Location Bypass Revoked",
        content="Admin has revoked your location bypass. Location verification is now required again during login.",
        target_user_id=user.id,
        is_active=True,
        notice_type="System Alert"
    )
    db.session.add(notice)

    db.session.add(AuditLog(
        user_id=current_user.id,
        action=f"Revoked Location Bypass for {user.email}",
        ip_address=request.remote_addr
    ))
    db.session.commit()

    return jsonify({'success': True, 'message': f'Location bypass revoked for {user.email}'})


@admin_bp.route('/staff/remove/<int:user_id>', methods=['POST'])
@login_required
@admin_required
def remove_staff(user_id):
    user = User.query.get_or_404(user_id)

    # Prevent removing admin users
    if user.role == 'admin':
        flash('Cannot remove admin users.', 'danger')
        return redirect(request.referrer or url_for('admin.employees'))

    # Mark user as inactive instead of deleting and revoke login access
    user.is_active = False
    user.current_session_id = None
    user.location_bypass_until = None
    user.overtime_bypass_until = None
    user.otp = None
    user.otp_expiry = None

    # Create notice for the user
    notice = Notice(
        title="Account Deactivated",
        content="Your account has been deactivated by admin. You will no longer be able to access the system.",
        target_user_id=user.id,
        is_active=True,
        notice_type="System Alert"
    )
    db.session.add(notice)

    # Audit log
    db.session.add(AuditLog(
        user_id=current_user.id,
        action=f"Removed staff member: {user.email} ({user.role})",
        ip_address=request.remote_addr
    ))

    db.session.commit()

    flash('Staff member removed successfully. Historical records are preserved and the account is now inactive.', 'success')
    return redirect(request.referrer or url_for('admin.employees'))


@admin_bp.route('/staff/complete/<int:user_id>', methods=['POST'])
@login_required
@admin_required
def complete_staff(user_id):
    user = User.query.get_or_404(user_id)

    if user.role not in ['intern', 'student']:
        flash('Only Interns and Students can be marked as completed.', 'danger')
        return redirect(request.referrer or url_for('admin.remove_staff_list'))

    # Mark user as inactive and revoke login access
    user.is_active = False
    user.current_session_id = None
    user.location_bypass_until = None
    user.overtime_bypass_until = None
    user.otp = None
    user.otp_expiry = None

    # Set workshop_status to 'Completed'
    if user.profile:
        user.profile.workshop_status = 'Completed'

    # Create notice for the user
    notice = Notice(
        title="Course/Internship Completed",
        content="Congratulations! Your course/internship has been marked as completed. Your system access is now deactivated, but your records are safely preserved.",
        target_user_id=user.id,
        is_active=True,
        notice_type="System Alert"
    )
    db.session.add(notice)

    # Audit log
    db.session.add(AuditLog(
        user_id=current_user.id,
        action=f"Marked {user.role} as completed: {user.email}",
        ip_address=request.remote_addr
    ))

    db.session.commit()

    flash(f'{user.role.capitalize()} marked as completed successfully. Access revoked and records preserved.', 'success')
    return redirect(request.referrer or url_for('admin.remove_staff_list'))
