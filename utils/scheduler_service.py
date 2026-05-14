from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from flask import current_app
from extensions import db
from database.models import Attendance, User, OfficeSettings, LeaveRequest, AuditLog
from utils.attendance_service import AttendanceService
from utils.email_service import send_email
from utils.time_utils import get_nepal_time
from utils.payroll_service import PayrollService
from utils.overtime_service import complete_elapsed_overtimes
from datetime import datetime, time, timedelta
import pytz

class SchedulerService:
    def __init__(self, app=None):
        self.timezone = pytz.timezone('Asia/Kathmandu')
        self.scheduler = BackgroundScheduler(timezone=self.timezone)
        self.app = app

    def init_app(self, app):
        self.app = app
        with app.app_context():
            self._setup_jobs()
        # Don't start automatically to avoid context issues

    def _setup_jobs(self):
        """Setup scheduled jobs based on office settings"""
        # Clear existing jobs
        self.scheduler.remove_all_jobs()

        try:
            # Get office settings
            settings = OfficeSettings.query.first()
            if not settings:
                # Create default settings if none exist
                settings = OfficeSettings()
                db.session.add(settings)
                db.session.commit()
        except Exception as e:
            # If there's a database error (e.g., columns don't exist yet), use defaults
            current_app.logger.warning(f"Could not load office settings for scheduler: {e}. Using defaults.")
            # Create a mock settings object with defaults
            from types import SimpleNamespace
            settings = SimpleNamespace()
            settings.auto_checkout_enabled = True
            settings.auto_checkout_time = datetime.strptime('18:00', '%H:%M').time()
            settings.email_reminders_enabled = True
            settings.reminder_time_before_checkout = 30

        # Schedule Daily Leave Cleanup at 12:05 AM
        self.scheduler.add_job(
            func=self._cleanup_expired_leaves,
            trigger=CronTrigger(hour=0, minute=5, timezone=self.timezone),
            id='leave_cleanup',
            name='Expired Leaves Cleanup',
            replace_existing=True
        )

        self.scheduler.add_job(
            func=self._process_monthly_payroll,
            trigger=CronTrigger(day=5, hour=0, minute=10, timezone=self.timezone),
            id='monthly_payroll',
            name='Monthly Payroll Processing',
            replace_existing=True
        )

        if settings.auto_checkout_enabled:
            self.scheduler.add_job(
                func=self._perform_auto_checkout,
                trigger=IntervalTrigger(minutes=1, timezone=self.timezone),
                id='auto_checkout',
                name='Auto Checkout Due Check',
                replace_existing=True,
                coalesce=True,
                max_instances=1
            )

            if settings.email_reminders_enabled:
                # Schedule email reminders before checkout
                reminder_minutes = settings.reminder_time_before_checkout
                reminder_time = (datetime.combine(datetime.today(), settings.auto_checkout_time) -
                               timedelta(minutes=reminder_minutes)).time()

                self.scheduler.add_job(
                    func=self._send_checkout_reminders,
                    trigger=CronTrigger(hour=reminder_time.hour, minute=reminder_time.minute, timezone=self.timezone),
                    id='checkout_reminders',
                    name='Checkout Email Reminders',
                    replace_existing=True
                )

        # Schedule daily absent marking for users who did not check in today.
        self.scheduler.add_job(
            func=self._mark_absent_no_shows,
            trigger=CronTrigger(hour=23, minute=45, timezone=self.timezone),
            id='mark_absent_no_shows',
            name='Daily Absent Marking',
            replace_existing=True
        )

        # Schedule daily auto-completion of roles for students and interns who finished their duration
        self.scheduler.add_job(
            func=self._auto_complete_roles,
            trigger=CronTrigger(hour=0, minute=30, timezone=self.timezone),  # Run daily at 12:30 AM
            id='auto_complete_roles',
            name='Daily Auto Complete Roles',
            replace_existing=True
        )

    def _perform_auto_checkout(self):
        """Automatically check out users who are still checked in"""
        with self.app.app_context():
            try:
                current_time = get_nepal_time()
                complete_elapsed_overtimes(current_time)
                settings = OfficeSettings.query.first()
                if not settings or not settings.auto_checkout_enabled or not settings.auto_checkout_time:
                    return

                checkout_time = settings.auto_checkout_time.replace(second=0, microsecond=0)
                checkout_at = datetime.combine(current_time.date(), checkout_time)
                if current_time < checkout_at:
                    return

                # Find all users who are currently checked in (no check_out time)
                checked_in_users = Attendance.query.filter(
                    Attendance.check_out.is_(None),
                    Attendance.check_in >= current_time.replace(hour=0, minute=0, second=0, microsecond=0)
                ).all()

                checked_out_count = 0
                for attendance in checked_in_users:
                    from database.models import OvertimeRequest
                    has_ot = OvertimeRequest.query.filter_by(
                        user_id=attendance.user_id,
                        status='in-progress'
                    ).first()
                    if has_ot:
                        continue

                    # Auto-checkout the user
                    attendance.check_out = checkout_at

                    # Calculate final status
                    user = attendance.user
                    attendance.status = AttendanceService.calculate_status(
                        attendance.check_in, attendance.check_out, user.role
                    )

                    # Calculate overtime if applicable
                    duration = (attendance.check_out - attendance.check_in).total_seconds() / 3600
                    if duration > 9:  # More than 9 hours worked
                        attendance.overtime_hours = duration - 9
                    checked_out_count += 1

                    current_app.logger.info(f"Auto-checked out user {user.id} ({user.profile.full_name if user.profile else user.email})")

                db.session.commit()
                current_app.logger.info(f"Auto-checkout due check completed for {checked_out_count} users")

            except Exception as e:
                current_app.logger.error(f"Error during auto-checkout: {e}")
                db.session.rollback()

    def _send_checkout_reminders(self):
        """Send email reminders to users who are still checked in"""
        with self.app.app_context():
            try:
                current_time = get_nepal_time()

                # Find all users who are currently checked in
                checked_in_users = Attendance.query.filter(
                    Attendance.check_out.is_(None),
                    Attendance.check_in >= current_time.replace(hour=0, minute=0, second=0, microsecond=0)
                ).join(User).all()

                reminder_count = 0
                for attendance in checked_in_users:
                    user = attendance.user
                    if user.profile and user.profile.personal_email:
                        # Send reminder email
                        send_email(
                            subject="EMS Reminder: Please Check Out",
                            recipient=user.profile.personal_email,
                            template="emails/checkout_reminder",
                            user=user,
                            attendance=attendance
                        )
                        reminder_count += 1

                current_app.logger.info(f"Sent checkout reminders to {reminder_count} users")

            except Exception as e:
                current_app.logger.error(f"Error sending checkout reminders: {e}")

    def _mark_absent_no_shows(self):
        """Automatically create absent or holiday records for active users with no attendance or approved leave."""
        with self.app.app_context():
            try:
                today = get_nepal_time().date()
                start_of_day = datetime.combine(today, time.min)
                end_of_day = datetime.combine(today, time.max)

                attended_user_ids = {
                    user_id for (user_id,) in db.session.query(Attendance.user_id).filter(
                        Attendance.check_in >= start_of_day,
                        Attendance.check_in <= end_of_day
                    ).all()
                }

                leave_user_ids = {
                    leave.user_id for leave in LeaveRequest.query.filter(
                        LeaveRequest.status == 'approved',
                        LeaveRequest.start_date <= today,
                        LeaveRequest.end_date >= today
                    ).all()
                }

                users_to_mark = User.query.filter(
                    User.is_active == True,
                    User.role != 'admin'
                ).all()

                absent_count = 0
                holiday_count = 0

                is_saturday = (today.weekday() == 5)
                for user in users_to_mark:
                    if user.id in attended_user_ids or user.id in leave_user_ids:
                        continue

                    if is_saturday:
                        holiday_record = Attendance(
                            user_id=user.id,
                            check_in=datetime.combine(today, time(hour=12, minute=0)),
                            check_out=datetime.combine(today, time(hour=12, minute=0)),
                            status='holiday',
                            is_weekend=True
                        )
                        db.session.add(holiday_record)
                        holiday_count += 1
                    else:
                        absent_record = Attendance(
                            user_id=user.id,
                            check_in=datetime.combine(today, time(hour=12, minute=0)),
                            status='absent'
                        )
                        db.session.add(absent_record)
                        db.session.add(AuditLog(
                            user_id=user.id,
                            action=f"Auto-marked absent for no check-in on {today.isoformat()}",
                            details='Daily attendance automation',
                            ip_address='SYSTEM_SCHEDULER'
                        ))
                        absent_count += 1

                if holiday_count or absent_count:
                    db.session.commit()
                    if absent_count:
                        current_app.logger.info(f"Marked {absent_count} users absent for {today}.")
                    if holiday_count:
                        current_app.logger.info(f"Marked {holiday_count} users holiday for {today}.")

            except Exception as e:
                current_app.logger.error(f"Error while auto-marking absent users: {e}")
                db.session.rollback()

    def _cleanup_expired_leaves(self):
        """Automatically reject pending leave requests whose start dates have passed."""
        with self.app.app_context():
            try:
                today = get_nepal_time().date()
                
                # Find all LeaveRequests that are 'pending' but the start date is in the past
                expired_leaves = LeaveRequest.query.filter(
                    LeaveRequest.status == 'pending',
                    LeaveRequest.start_date < today
                ).all()

                for leave in expired_leaves:
                    leave.status = 'rejected'
                    
                    # Add an audit trace
                    log = AuditLog(
                        user_id=leave.user_id,
                        action=f"Auto-Rejected Leave Request (ID: {leave.id}) because the start date passed without Admin approval.",
                        ip_address="SYSTEM_SCHEDULER"
                    )
                    db.session.add(log)
                    
                    current_app.logger.info(f"Cleaned up expired leave request for User {leave.user_id}")

                if expired_leaves:
                    db.session.commit()
                    current_app.logger.info(f"Cleaned up {len(expired_leaves)} expired leave requests.")

            except Exception as e:
                current_app.logger.error(f"Error during leave cleanup: {e}")
                db.session.rollback()

    def _process_monthly_payroll(self):
        """Automatically process payroll on the 5th day of each month."""
        with self.app.app_context():
            try:
                now = get_nepal_time()
                results = PayrollService.process_payroll_cycle(
                    year=now.year,
                    month=now.month,
                    triggered_by='scheduler',
                    actor_id=None,
                    actor_ip='SYSTEM_SCHEDULER'
                )
                current_app.logger.info(f"Monthly payroll scheduler completed with results: {results}")
            except Exception as e:
                current_app.logger.exception(f"Error during monthly payroll processing: {e}")
                db.session.rollback()

    def _auto_complete_roles(self):
        """Automatically complete the course/internship for active interns and students whose duration has passed."""
        from database.models import Notice, EmployeeProfile
        with self.app.app_context():
            try:
                today = get_nepal_time().date()
                
                # Query all active students and interns
                candidates = User.query.join(EmployeeProfile).filter(
                    User.role.in_(['intern', 'student']),
                    User.is_active == True
                ).all()
                
                completed_count = 0
                for user in candidates:
                    profile = user.profile
                    if not profile:
                        continue
                        
                    is_completed = False
                    completion_reason = ""
                    
                    # 1. Check if specific end date is reached
                    if profile.workshop_end_date:
                        if today >= profile.workshop_end_date:
                            is_completed = True
                            completion_reason = f"Reached workshop end date ({profile.workshop_end_date})"
                    # 2. Fallback to 3-month duration if only joining date exists
                    elif profile.joining_date:
                        days_passed = (today - profile.joining_date).days
                        months_passed = days_passed / 30.44
                        if months_passed >= 3.0:
                            is_completed = True
                            completion_reason = f"3-month default duration passed (Joined: {profile.joining_date})"
                    
                    if is_completed:
                        # Mark as completed
                        user.is_active = False
                        user.current_session_id = None
                        user.location_bypass_until = None
                        user.overtime_bypass_until = None
                        user.otp = None
                        user.otp_expiry = None
                        
                        profile.workshop_status = 'Completed'
                        
                        # Generate notice
                        notice = Notice(
                            title="Course/Internship Automatically Completed",
                            content=f"Congratulations! Your records have been automatically marked as completed ({completion_reason}). Your system access is now deactivated.",
                            target_user_id=user.id,
                            is_active=True,
                            notice_type="System Alert"
                        )
                        db.session.add(notice)
                        
                        # Generate Audit Log
                        log = AuditLog(
                            user_id=user.id,
                            action=f"System Automatically Completed {user.role.capitalize()}",
                            details=completion_reason,
                            ip_address="SYSTEM_SCHEDULER"
                        )
                        db.session.add(log)
                        
                        completed_count += 1
                        current_app.logger.info(f"Auto-completed {user.role} {profile.full_name} ({user.id}): {completion_reason}")
                
                if completed_count > 0:
                    db.session.commit()
                    current_app.logger.info(f"Successfully auto-completed {completed_count} users.")
                
            except Exception as e:
                current_app.logger.exception(f"Error during role auto-completion: {e}")
                db.session.rollback()

    def start(self):
        """Start the scheduler"""
        if not self.scheduler.running:
            self.scheduler.start()
            print("Scheduler started")  # Use print instead of logger since context might not be available

    def stop(self):
        """Stop the scheduler"""
        if self.scheduler.running:
            self.scheduler.shutdown()
            print("Scheduler stopped")

    def restart(self):
        """Restart the scheduler with updated settings"""
        with self.app.app_context():
            self.stop()
            self._setup_jobs()
        self.start()
