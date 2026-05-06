from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify, current_app, session
from flask_login import login_required, current_user
from extensions import db
from database.models import Attendance, LeaveRequest, EmployeeProfile, Notice, TimeLog, AuditLog
from utils.time_utils import get_nepal_time
from utils.attendance_service import AttendanceService
from utils.qr_service import QRService
from database.models import Payroll
from utils.payroll_service import PayrollService
from datetime import datetime, timedelta
from werkzeug.security import check_password_hash, generate_password_hash
from utils.security_utils import validate_password_strength, validate_nepal_phone_digits

staff_bp = Blueprint('staff', __name__)

from functools import wraps
def check_lockout(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if current_user.is_authenticated and current_user.is_locked_out():
            if request.is_json:
                return jsonify({'success': False, 'message': 'System access locked until tomorrow.', 'locked': True}), 403
            return redirect(url_for('staff.locked'))
        return f(*args, **kwargs)
    return decorated_function



@staff_bp.route('/dashboard')
@login_required
@check_lockout
def dashboard():
    today = get_nepal_time().date()
    
    today_str = today.strftime('%Y-%m-%d')
    
    attendance = Attendance.query.filter_by(user_id=current_user.id).filter(db.func.date(Attendance.check_in) == today).first()
    leaves = LeaveRequest.query.filter_by(user_id=current_user.id).limit(5).all()
    
    # Fetch Notices
    cutoff_date = get_nepal_time() - timedelta(days=30)
    notices = Notice.query.filter(
        Notice.is_active == True,
        Notice.created_at >= cutoff_date,
        db.or_(
            Notice.role_restriction == 'all', 
            Notice.role_restriction == current_user.role,
            Notice.target_user_id == current_user.id
        )
    ).order_by(Notice.created_at.desc()).limit(5).all()
    
    # Smart Popup Logic
    latest_notice = notices[0] if notices else None
    show_notice_popup = False
    if latest_notice:
        now_dt = get_nepal_time()
        time_diff = (now_dt - latest_notice.created_at).total_seconds()
        is_recent = time_diff < 86400  # 24 hours
        already_seen = session.get(f'notice_seen_{latest_notice.id}', False)
        if is_recent and not already_seen:
            show_notice_popup = True
            session[f'notice_seen_{latest_notice.id}'] = True
    
    qr_path = QRService.generate_employee_badge(current_user.id)

    # PRE-LOAD STATS FOR ULTRA-FAST INITIAL RENDERING
    from utils.leave_service import LeaveService
    profile = current_user.profile
    annual_allowance = profile.leave_allowance if profile else 15.0
    
    initial_stats = {
        'attendance_score': AttendanceService.calculate_attendance_score(current_user.id, today),
        'leave_balance': LeaveService.calculate_leave_balance(current_user.id, annual_allowance),
        'workshop_status': profile.workshop_status if profile else 'Ongoing',
        'payment_status': profile.payment_status if profile else 'Pending'
    }
    
    return render_template('employee/dashboard.html', 
                           attendance=attendance, 
                           leaves=leaves, 
                           qr_path=qr_path, 
                           notices=notices,
                           latest_notice=latest_notice,
                           show_notice_popup=show_notice_popup,
                           today_date=today,
                           initial_stats=initial_stats,
                           now=get_nepal_time())

@staff_bp.route('/api/attendance-stats', methods=['GET'])
@login_required
@check_lockout
def get_attendance_stats():
    """
    Asynchronous endpoint to fetch dashboard statistics without blocking page load.
    """
    today = get_nepal_time().date()
    today_str = today.strftime('%Y-%m-%d')
    
    # Auto-sync past 30 days and next 7 days for attendance (Moved to async stats API to prevent UI blocking)
    if session.get('last_attendance_sync') != today_str:
        try:
            AttendanceService.sync_attendance_for_period(current_user.id, today - timedelta(days=30), today + timedelta(days=7))
            session['last_attendance_sync'] = today_str
        except Exception as e:
            current_app.logger.error(f"Attendance sync error: {e}")

    # Calculate Attendance Score
    attendance_score = AttendanceService.calculate_attendance_score(current_user.id, today)
    
    # Calculate dynamic leave balance
    from utils.leave_service import LeaveService
    profile = current_user.profile
    annual_allowance = profile.leave_allowance if profile else 15.0
    workshop_status = profile.workshop_status if profile else 'Ongoing'
    payment_status = profile.payment_status if profile else 'Pending'
    
    leave_balance = LeaveService.calculate_leave_balance(current_user.id, annual_allowance)
    
    return jsonify({
        'attendance_score': attendance_score,
        'leave_balance': leave_balance,
        'workshop_status': workshop_status,
        'payment_status': payment_status,
        'has_profile': profile is not None
    })

@staff_bp.route('/check-in', methods=['POST'])
@login_required
@check_lockout
def check_in():
    # Day-based Check-In Logic: Prevent duplicate attendance records for the same day
    from database.models import AuditLog, OfficeSettings, AllowedLocation
    from utils.time_utils import get_nepal_time
    import pytz

    def parse_client_timestamp(raw_timestamp):
        if not raw_timestamp:
            return None
        try:
            parsed_time = datetime.fromisoformat(raw_timestamp.replace('Z', '+00:00'))
            if parsed_time.tzinfo is not None:
                nepal_tz = pytz.timezone('Asia/Kathmandu')
                return parsed_time.astimezone(nepal_tz).replace(tzinfo=None)
            return parsed_time
        except (ValueError, TypeError):
            return None

    data = request.get_json() or {}
    now = parse_client_timestamp(data.get('client_timestamp')) or get_nepal_time()
    today = now.date()
    
    # Check for any attendance record today (active or completed)
    existing = Attendance.query.filter_by(user_id=current_user.id).filter(
        db.func.date(Attendance.check_in) == today
    ).first()
    
    if existing:
        # User already has an attendance record today
        db.session.add(AuditLog(
            user_id=current_user.id, 
            action=f"Duplicate check-in attempt (Already attending)", 
            ip_address=request.remote_addr
        ))
        db.session.commit()
        return jsonify({'success': False, 'message': 'You have already checked in for today.'}), 400

    # GPS Location Verification
    lat = data.get('latitude')
    lon = data.get('longitude')
    
    # Check Location Bypasses (Admin Grant or Office IP limit or Overtime)
    has_bypass = False
    if current_user.location_bypass_until is not None and current_user.location_bypass_until > get_nepal_time():
        has_bypass = True
    elif current_user.overtime_bypass_until and current_user.overtime_bypass_until > get_nepal_time():
        has_bypass = True
        
    settings = OfficeSettings.query.first()
    office_ip = settings.office_ip if settings and settings.office_ip else current_app.config.get('OFFICE_PUBLIC_IP', '')
    if office_ip and request.remote_addr == office_ip:
        has_bypass = True

    if not has_bypass:
        if lat is None or lon is None:
            # Audit failure
            db.session.add(AuditLog(
                user_id=current_user.id, 
                action="Check-in Blocked: Location Services Denied", 
                ip_address=request.remote_addr
            ))
            db.session.commit()
            return jsonify({'success': False, 'message': 'Location access required for Check-In. Please allow GPS access.'}), 403
            
        from utils.location_utils import verify_location_access
        is_allowed, msg, dist = verify_location_access(lat, lon, data.get('accuracy'))
        if not is_allowed:
            db.session.add(AuditLog(
                user_id=current_user.id, 
                action=f"Check-in Blocked: Outside Geofence (Dist: {int(dist)}m)", 
                ip_address=request.remote_addr
            ))
            db.session.commit()
            return jsonify({'success': False, 'message': f"Geofence Rejected: {msg}"}), 403
    
    attendance = Attendance(user_id=current_user.id, check_in=now)
    db.session.add(attendance)
    db.session.flush() # Get attendance ID
    
    # Create TimeLog entry with GPS data
    db.session.add(TimeLog(
        user_id=current_user.id,
        attendance_id=attendance.id,
        timestamp=now,
        ip_address=request.remote_addr,
        device_type=request.headers.get('User-Agent'),
        action='check-in'
    ))
    
    # Audit log
    db.session.add(AuditLog(
        user_id=current_user.id, 
        action=f"Checked in successfully via Dashboard", 
        ip_address=request.remote_addr
    ))
    
    # Trigger Attendance Sync for current week (last 7 days and next 7 days)
    AttendanceService.sync_attendance_for_period(current_user.id, today - timedelta(days=7), today + timedelta(days=7))

    try:
        PayrollService.refresh_upcoming_payroll_for_user(current_user.id, actor_id=current_user.id, actor_ip=request.remote_addr or 'SYSTEM')
    except Exception as e:
        current_app.logger.warning(f"Payroll refresh failed after check-in for user {current_user.id}: {e}")
    
    db.session.commit()
    
    return jsonify({'success': True, 'message': 'Checked in successfully.'})

@staff_bp.route('/check-out', methods=['POST'])
@login_required
def check_out():
    today = get_nepal_time().date()
    attendance = Attendance.query.filter_by(user_id=current_user.id).filter(
        db.func.date(Attendance.check_in) == today, 
        Attendance.check_out.is_(None)
    ).first()
    
    if not attendance:
        return jsonify({'success': False, 'message': 'No active session.'}), 404

    now = get_nepal_time()
    attendance.check_out = now
    attendance.status = AttendanceService.calculate_status(attendance.check_in, now, role=current_user.role)
    
    # Create TimeLog entry
    db.session.add(TimeLog(
        user_id=current_user.id,
        attendance_id=attendance.id,
        timestamp=now,
        ip_address=request.remote_addr,
        device_type=request.headers.get('User-Agent'),
        action='check-out'
    ))
    
    # Trigger Attendance Sync for current week
    today_dt = get_nepal_time().date()
    AttendanceService.sync_attendance_for_period(current_user.id, today_dt - timedelta(days=7), today_dt + timedelta(days=7))

    try:
        PayrollService.refresh_upcoming_payroll_for_user(current_user.id, actor_id=current_user.id, actor_ip=request.remote_addr or 'SYSTEM')
    except Exception as e:
        current_app.logger.warning(f"Payroll refresh failed after check-out for user {current_user.id}: {e}")
    
    db.session.commit()
    
    return jsonify({'success': True, 'message': f'Checked out successfully. Status: {attendance.status}'})

@staff_bp.route('/check-location', methods=['POST'])
@login_required
def check_location():
    """
    Utility endpoint for the frontend dashboard to verify if the user is 
    inside the geofence or has an active bypass.
    """
    from database.models import OfficeSettings
    data = request.get_json() or {}
    lat = data.get('latitude')
    lon = data.get('longitude')
    
    # Check Bypass Status (Admin Grant or Office IP or Overtime)
    has_bypass = False
    if current_user.location_bypass_until is not None and current_user.location_bypass_until > get_nepal_time():
        has_bypass = True
    elif current_user.overtime_bypass_until and current_user.overtime_bypass_until > get_nepal_time():
        has_bypass = True
        
    settings = OfficeSettings.query.first()
    office_ip = settings.office_ip if settings and settings.office_ip else current_app.config.get('OFFICE_PUBLIC_IP', '')
    if office_ip and request.remote_addr == office_ip:
        has_bypass = True
        
    if has_bypass:
        return jsonify({
            'success': True,
            'allowed': True,
            'message': 'Location Bypass Active',
            'distance': 0
        })
        
    if lat is None or lon is None:
        return jsonify({
            'success': False,
            'allowed': False,
            'message': 'Coordinates missing',
            'distance': None
        })
        
    from utils.location_utils import verify_location_access
    allowed, msg, dist = verify_location_access(lat, lon, data.get('accuracy'))
    
    return jsonify({
        'success': True,
        'allowed': allowed,
        'message': msg,
        'distance': int(dist) if dist is not None else None
    })

@staff_bp.route('/start-break', methods=['POST'])
@login_required
def start_break():
    now = get_nepal_time()
    
    # Restriction 1: Must be after 2:00 PM (14:00) Nepali Time
    if now.hour < 14:
        return jsonify({'success': False, 'message': 'Break can only be taken after 2:00 PM Nepali time.'}), 400

    today = now.date()
    attendance = Attendance.query.filter_by(user_id=current_user.id).filter(
        db.func.date(Attendance.check_in) == today, 
        Attendance.check_out.is_(None)
    ).first()
    
    if not attendance:
        return jsonify({'success': False, 'message': 'No active session.'}), 404
        
    # Restriction 2: Once per day
    if attendance.break_start:
        return jsonify({'success': False, 'message': 'You have already taken your break for today.'}), 400
        
    attendance.break_start = now
    db.session.commit()
    return jsonify({'success': True, 'message': 'Break started.'})

@staff_bp.route('/end-break', methods=['POST'])
@login_required
def end_break():
    today = get_nepal_time().date()
    attendance = Attendance.query.filter_by(user_id=current_user.id).filter(
        db.func.date(Attendance.check_in) == today, 
        Attendance.check_out.is_(None)
    ).first()
    
    if not attendance:
        return jsonify({'success': False, 'message': 'No active session.'}), 404
        
    now = get_nepal_time()
    attendance.break_end = now
    db.session.commit()
    return jsonify({'success': True, 'message': 'Break ended.'})

# ─── My Profile ───────────────────────────────────────────────────────────────
@staff_bp.route('/profile', methods=['GET', 'POST'])
@login_required
def my_profile():
    profile = current_user.profile
    if request.method == 'POST':
        form_action = request.form.get('form_action', 'profile')

        if form_action == 'password':
            current_password = (request.form.get('current_password') or '').strip()
            new_password = (request.form.get('new_password') or '').strip()
            confirm_password = (request.form.get('confirm_password') or '').strip()

            if not current_password or not new_password or not confirm_password:
                flash('Please complete all password fields.', 'danger')
                return redirect(url_for('staff.my_profile'))

            if not check_password_hash(current_user.password_hash, current_password):
                flash('Your current password is incorrect.', 'danger')
                return redirect(url_for('staff.my_profile'))

            if new_password != confirm_password:
                flash('New password and confirmation do not match.', 'danger')
                return redirect(url_for('staff.my_profile'))

            if current_password == new_password:
                flash('New password must be different from your current password.', 'danger')
                return redirect(url_for('staff.my_profile'))

            is_valid, msg = validate_password_strength(new_password)
            if not is_valid:
                flash(msg, 'danger')
                return redirect(url_for('staff.my_profile'))

            current_user.password_hash = generate_password_hash(new_password, method='pbkdf2:sha256')
            current_user.otp = None
            current_user.otp_expiry = None
            db.session.add(AuditLog(
                user_id=current_user.id,
                action='password-change',
                details='Password changed successfully from profile settings.',
                ip_address=request.remote_addr
            ))
            db.session.commit()
            flash('Password updated successfully.', 'success')
            return redirect(url_for('staff.my_profile'))

        if profile:
            profile.personal_email = request.form.get('personal_email', profile.personal_email)
            phone_digits = request.form.get('phone_digits', '').strip()
            if phone_digits:
                is_valid_phone, normalized_phone = validate_nepal_phone_digits(phone_digits)
                if not is_valid_phone:
                    flash('Please enter a valid phone number. It must be 10 digits and start with 98 or 97 after +977.', 'danger')
                    return redirect(url_for('staff.my_profile'))
                profile.phone = f"+977 {normalized_phone}"
            elif request.form.get('phone_digits') == '':
                profile.phone = None
            db.session.commit()
            flash('Profile updated successfully.', 'success')
        else:
            flash('Profile record was not found for this account.', 'danger')
        return redirect(url_for('staff.my_profile'))
    if current_user.role == 'student':
        return render_template('employee/student_profile.html', profile=profile)
    return render_template('employee/my_profile.html', profile=profile)

# ─── My Queries ───────────────────────────────────────────────────────────────
@staff_bp.route('/queries', methods=['GET', 'POST'])
@login_required
def my_queries():
    from database.models import ContactQuery, QueryMessage
    if request.method == 'POST':
        category = request.form.get('category')
        priority = request.form.get('priority')
        message = request.form.get('message')
        query = ContactQuery(
            user_id=current_user.id,
            name=current_user.profile.full_name if current_user.profile else current_user.email,
            email=current_user.email,
            category=category,
            priority=priority,
            message=message
        )
        db.session.add(query)
        db.session.flush() # To get query.id
        
        user_msg = QueryMessage(
            query_id=query.id,
            sender_type='user',
            message=message
        )
        db.session.add(user_msg)
        db.session.commit()
        flash('Query submitted successfully. Admin will respond soon.', 'success')
        return redirect(url_for('staff.my_queries'))
    
    queries = ContactQuery.query.filter_by(email=current_user.email).order_by(ContactQuery.created_at.desc()).all()
    return render_template('employee/my_queries.html', queries=queries)

@staff_bp.route('/query/reply/<int:query_id>', methods=['POST'])
@login_required
def reply_query(query_id):
    from database.models import ContactQuery, QueryMessage
    query = ContactQuery.query.get_or_404(query_id)
    if query.email != current_user.email:
        return jsonify({'success': False, 'message': 'Unauthorized'}), 403
        
    reply_text = request.form.get('reply')
    if reply_text and reply_text.strip():
        user_msg = QueryMessage(
            query_id=query.id,
            sender_type='user',
            message=reply_text.strip()
        )
        db.session.add(user_msg)
        db.session.commit()
        flash('Reply sent successfully.', 'success')
        
    return redirect(url_for('staff.my_queries'))

# ─── Leaves ───────────────────────────────────────────────────────────────────
@staff_bp.route('/leaves', methods=['GET', 'POST'])
@login_required
def my_leaves():
    from utils.leave_service import LeaveService
    annual_allowance = current_user.profile.leave_allowance if current_user.profile else 15.0
    leave_balance = LeaveService.calculate_leave_balance(current_user.id, annual_allowance)
    
    if request.method == 'POST':
        leave_type = request.form.get('leave_type')
        start_date_str = request.form.get('start_date')
        end_date_str = request.form.get('end_date')
        reason = request.form.get('reason')
        from datetime import date
        
        start_date = date.fromisoformat(start_date_str)
        end_date = date.fromisoformat(end_date_str)
        
        # Guard: No past leaves
        if start_date < get_nepal_time().date():
            flash('Cannot apply for leave on a past date.', 'error')
            return redirect(url_for('staff.my_leaves'))
            
        # Guard: End date before start date
        if end_date < start_date:
            flash('End date must be after start date.', 'error')
            return redirect(url_for('staff.my_leaves'))
            
        leave = LeaveRequest(
            user_id=current_user.id,
            leave_type=leave_type,
            start_date=start_date,
            end_date=end_date,
            reason=reason,
            status='pending'
        )
        db.session.add(leave)
        db.session.commit()
        flash('Leave request submitted successfully.', 'success')
        return redirect(url_for('staff.my_leaves'))
        
    leaves = LeaveRequest.query.filter_by(user_id=current_user.id).order_by(LeaveRequest.applied_on.desc()).all()
    return render_template('employee/my_leaves.html', leaves=leaves, leave_balance=leave_balance)

# ─── Overtime Requests ─────────────────────────────────────────────────────────
@staff_bp.route('/overtime', methods=['GET', 'POST'])
@login_required
def my_overtime():
    from database.models import OvertimeRequest
    from datetime import date
    
    if request.method == 'POST':
        overtime_type = request.form.get('overtime_type')  # 'remote' or 'onsite'
        hours = float(request.form.get('hours', 0))
        requested_date_str = request.form.get('requested_date')
        reason = request.form.get('reason')
        
        if overtime_type not in ['remote', 'onsite']:
            flash('Invalid overtime type.', 'error')
            return redirect(url_for('staff.my_overtime'))
        
        if hours <= 0 or hours > 12:
            flash('Overtime hours must be between 0 and 12.', 'error')
            return redirect(url_for('staff.my_overtime'))
        
        requested_date = date.fromisoformat(requested_date_str)
        
        if requested_date < get_nepal_time().date():
            flash('Cannot apply for overtime on a past date.', 'error')
            return redirect(url_for('staff.my_overtime'))
        
        ot_request = OvertimeRequest(
            user_id=current_user.id,
            overtime_type=overtime_type,
            hours=hours,
            requested_date=requested_date,
            reason=reason,
            status='pending'
        )
        db.session.add(ot_request)
        db.session.commit()
        flash('Overtime request submitted successfully.', 'success')
        return redirect(url_for('staff.my_overtime'))
    
    overtime_requests = OvertimeRequest.query.filter_by(user_id=current_user.id).order_by(OvertimeRequest.applied_on.desc()).all()
    return render_template('employee/my_overtime.html', overtime_requests=overtime_requests)

# ─── Calendar Events API ──────────────────────────────────────────────────────
@staff_bp.route('/attendance/events')
@login_required
def attendance_events():
    start_str = request.args.get('start')
    end_str = request.args.get('end')
    
    events = []
    
    # 1. Fetch Attendance Records
    query = Attendance.query.filter_by(user_id=current_user.id)
    if start_str and end_str:
        start_date = datetime.fromisoformat(start_str.replace('Z', '+00:00')).date()
        end_date = datetime.fromisoformat(end_str.replace('Z', '+00:00')).date()
        try:
            AttendanceService.sync_attendance_for_period(current_user.id, start_date, end_date)
        except Exception as e:
            current_app.logger.warning(f"Attendance sync failed for user {current_user.id}: {e}")
        query = query.filter(db.func.date(Attendance.check_in) >= start_date, 
                             db.func.date(Attendance.check_in) <= end_date)
                             
    attendances = query.all()
    
    for att in attendances:
        color = '#10b981' # Green (present by default)
        title = att.status.title() if att.status else 'Present'
        
        if att.status == 'absent':
            color = '#ef4444' # Red
        elif att.status == 'holiday' or att.is_weekend:
            color = '#3b82f6' # Blue for holiday
            title = 'Holiday'
        elif att.status in ['half-day', 'late']:
            color = '#f59e0b' # Amber/Orange for Late/Half-day
            title = att.status.title()
            
        # Add Time Information to Title
        if att.check_in and att.status not in ['absent', 'holiday', 'weekend']:
            # Requirement: ONLY ONE time (Check-in) in 12-hour format
            time_str = att.check_in.strftime('%I:%M %p')
            title = f"{title} - {time_str}"
        event = {
            'id': f'att_{att.id}',
            'title': title,
            'color': color
        }
        
        # Ensure consistent date/time format for FullCalendar
        if att.status in ['absent', 'holiday', 'weekend']:
            event['start'] = att.check_in.strftime('%Y-%m-%d')
            event['allDay'] = True
        else:
            event['start'] = att.check_in.isoformat()
            event['allDay'] = False
            
        events.append(event)
        
    # 2. Fetch Approved Leave Requests
    leave_query = LeaveRequest.query.filter_by(user_id=current_user.id, status='approved')
    if start_str and end_str:
        leave_query = leave_query.filter(
            db.or_(
                db.and_(LeaveRequest.start_date >= start_date, LeaveRequest.start_date <= end_date),
                db.and_(LeaveRequest.end_date >= start_date, LeaveRequest.end_date <= end_date),
                db.and_(LeaveRequest.start_date <= start_date, LeaveRequest.end_date >= end_date)
            )
        )
        
    approved_leaves = leave_query.all()
    
    for leave in approved_leaves:
        # FullCalendar needs end date to be exclusive for range
        end_dt = leave.end_date + timedelta(days=1)
        
        events.append({
            'id': f'leave_{leave.id}',
            'title': f'On Leave ({leave.leave_type.title()})',
            'start': leave.start_date.isoformat(),
            'end': end_dt.isoformat(),
            'color': '#8b5cf6', # Purple for Leave
            'allDay': True
        })
        
    return jsonify(events)

# ─── Payslips ─────────────────────────────────────────────────────────────────
@staff_bp.route('/payslips')
@login_required
def my_payslips():
    payslips = Payroll.query.filter_by(user_id=current_user.id).order_by(Payroll.generated_on.desc()).all()
    for payslip in payslips:
        PayrollService.attach_calculated_fields(payslip)
    return render_template('employee/my_payslips.html', payslips=payslips, profile=current_user.profile)

@staff_bp.route('/payslip/<int:payroll_id>')
@login_required
def view_my_payslip(payroll_id):
    payroll = Payroll.query.get_or_404(payroll_id)
    if payroll.user_id != current_user.id:
        flash('Unauthorized access.', 'danger')
        return redirect(url_for('staff.my_payslips'))
        
    from datetime import datetime
    month_str = datetime(payroll.year, payroll.month, 1).strftime('%B %Y')
    
    advance_payment = request.args.get('advance_payment', type=float, default=0.0) or 0.0
    payroll.advance_payment = max(0.0, advance_payment)
    
    PayrollService.attach_calculated_fields(payroll)
    return render_template('admin/payslip_template.html', p=payroll, month_str=month_str)
    
@staff_bp.route('/api/payroll', methods=['GET'])
@login_required
def get_payroll():
    payroll = Payroll.query.filter_by(user_id=current_user.id).order_by(Payroll.generated_on.desc()).first()
    if not payroll:
        return jsonify({'error': 'No payroll data found'}), 404
    
    PayrollService.attach_calculated_fields(payroll)
    return jsonify({
        'id': payroll.id,
        'month': payroll.month,
        'year': payroll.year,
        'base_salary': payroll.base_salary,
        'hra': payroll.hra,
        'conveyance': payroll.conveyance,
        'medical': payroll.medical,
        'lta': payroll.lta,
        'special_allowance': payroll.special_allowance,
        'overtime_earnings': payroll.overtime_earnings,
        'gross_salary': payroll.gross_salary,
        'absent_days': payroll.absent_days,
        'absent_deduction': payroll.absent_deduction,
        'leave_days': payroll.leave_days,
        'leave_deduction': payroll.leave_deduction,
        'advance_payment': payroll.advance_payment,
        'total_deductions': payroll.total_deductions,
        'net_salary': payroll.net_salary,
        'generated_on': payroll.generated_on.isoformat() if payroll.generated_on else None
    })

@staff_bp.route('/locked')
@login_required
def locked():
    if not current_user.is_locked_out():
        return redirect(url_for('staff.dashboard'))
    return render_template('auth/locked.html', lockout_until=current_user.lockout_until)

@staff_bp.route('/start-overtime', methods=['POST'])
@login_required
@check_lockout
def start_overtime():
    from database.models import OvertimeRequest
    # Find approved OT for today
    today = get_nepal_time().date()
    ot = OvertimeRequest.query.filter_by(user_id=current_user.id, status='approved').filter(OvertimeRequest.requested_date == today).first()
    
    if not ot:
        return jsonify({'success': False, 'message': 'No approved overtime found for today.'}), 404
    
    ot.status = 'in-progress'
    ot.actual_start_time = get_nepal_time()
    db.session.commit()
    
    return jsonify({'success': True, 'planned_hours': ot.hours})

@staff_bp.route('/finish-overtime', methods=['POST'])
@login_required
def finish_overtime():
    from database.models import OvertimeRequest
    ot = OvertimeRequest.query.filter_by(user_id=current_user.id, status='in-progress').first()
    
    if ot:
        ot.status = 'completed'
        ot.actual_end_time = get_nepal_time()
    
    # Set Hard Lockout until 12:01 AM tomorrow
    tomorrow = get_nepal_time() + timedelta(days=1)
    current_user.lockout_until = datetime(tomorrow.year, tomorrow.month, tomorrow.day, 0, 1)
    db.session.commit()
    
    # Logout session
    from flask_login import logout_user
    logout_user()
    
    return jsonify({'success': True, 'message': 'Overtime completed. System locked until tomorrow.'})
