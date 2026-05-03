from flask import current_app
from extensions import db
from database.models import Attendance, User, OfficeSettings
from datetime import datetime, timedelta
from utils.time_utils import get_nepal_time
import math

class AttendanceService:
    @staticmethod
    def calculate_distance(lat1, lon1, lat2, lon2):
        if lat1 is None or lon1 is None or lat2 is None or lon2 is None:
            return float('inf')
        # Haversine formula
        R = 6371e3 # Earth radius in meters
        phi1 = math.radians(float(lat1))
        phi2 = math.radians(float(lat2))
        dphi = math.radians(float(lat2 - lat1))
        dlambda = math.radians(float(lon2 - lon1))
        
        a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * (math.sin(dlambda / 2) ** 2)
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
        return R * c

    @staticmethod
    def is_within_geofence(user_lat, user_lon, office_lat, office_lon, radius):
        # Check primary office
        distance = AttendanceService.calculate_distance(user_lat, user_lon, office_lat, office_lon)
        if distance <= radius:
            return True, distance
            
        # Check secondary offices (AllowedLocation)
        from database.models import AllowedLocation
        allowed_locs = AllowedLocation.query.filter_by(is_active=True).all()
        for loc in allowed_locs:
            dist = AttendanceService.calculate_distance(user_lat, user_lon, loc.latitude, loc.longitude)
            if dist <= loc.radius:
                return True, dist
                
        return False, distance

    @staticmethod
    def calculate_status(check_in, check_out, role='employee'):
        """
        Calculates attendance status based on check-in time.
        - Present: Check-in before or at 10:00 AM
        - Late: Check-in after 10:00 AM
        """
        if not check_in:
            return 'absent'
            
        # Standard office start time is 10:00 AM in Nepal
        late_threshold = check_in.replace(hour=10, minute=0, second=0, microsecond=0)
        
        if check_in > late_threshold:
            return 'late'
            
        return 'present'

    @staticmethod
    def sync_attendance_for_period(user_id, start_date, end_date):
        """
        Auto-syncs daily attendance up to today.
        Rules:
        - Saturday -> Holiday (never absent)
        - Approved Leave -> Ignored by Absent checker
        - Missing Check-in (Weekday) -> Absent
        """
        from database.models import LeaveRequest
        
        # Enforce fresh start from May 4, 2026 (Tomorrow)
        fresh_start = datetime(2026, 5, 4).date()
        if start_date < fresh_start:
            start_date = fresh_start

        # Restrict sync up to YESTERDAY (don't mark today as absent yet)
        yesterday = get_nepal_time().date() - timedelta(days=1)
        if end_date > yesterday:
            end_date = yesterday

        # Fetch all attendance records for the period in bulk
        records = Attendance.query.filter_by(user_id=user_id).filter(
            Attendance.check_in >= datetime.combine(start_date, datetime.min.time()),
            Attendance.check_in <= datetime.combine(end_date, datetime.max.time())
        ).all()
        
        # Fetch approved leaves for the period
        leaves = LeaveRequest.query.filter_by(user_id=user_id, status='approved').filter(
            db.or_(
                db.and_(LeaveRequest.start_date >= start_date, LeaveRequest.start_date <= end_date),
                db.and_(LeaveRequest.end_date >= start_date, LeaveRequest.end_date <= end_date),
                db.and_(LeaveRequest.start_date <= start_date, LeaveRequest.end_date >= end_date)
            )
        ).all()
        
        # Pre-calculate leave dates set for O(1) lookup
        leave_dates = set()
        for leave in leaves:
            curr_leave = leave.start_date
            while curr_leave <= leave.end_date:
                leave_dates.add(curr_leave)
                curr_leave += timedelta(days=1)

        # Index records by date for O(1) lookup
        record_map = {att.check_in.date(): att for att in records}
        
        has_changes = False
        curr = start_date
        
        while curr <= end_date:
            # Note: end_date is capped at yesterday, so 'curr' will never be today.
            existing = record_map.get(curr)
            is_saturday = (curr.weekday() == 5)
            
            if is_saturday:
                calculated_status = 'holiday'
                is_weekend = True
                
                if existing:
                    if existing.status != calculated_status or existing.is_weekend != is_weekend:
                        existing.status = calculated_status
                        existing.is_weekend = is_weekend
                        has_changes = True
                else:
                    dummy_time = datetime.combine(curr, datetime.min.time()).replace(hour=12)
                    weekend_att = Attendance(
                        user_id=user_id, 
                        check_in=dummy_time, 
                        check_out=dummy_time, 
                        status=calculated_status, 
                        is_weekend=is_weekend
                    )
                    db.session.add(weekend_att)
                    has_changes = True
            else:
                # It's a weekday
                if not existing and curr not in leave_dates:
                    # Missing check-in -> Absent
                    dummy_time = datetime.combine(curr, datetime.min.time()).replace(hour=12)
                    absent_att = Attendance(
                        user_id=user_id, 
                        check_in=dummy_time, 
                        check_out=dummy_time, 
                        status='absent', 
                        is_weekend=False
                    )
                    db.session.add(absent_att)
                    has_changes = True
                elif existing and not existing.check_out and curr < today:
                    # Checked in, but never checked out, and the day is already over (Server offline at 6PM)
                    from database.models import OfficeSettings
                    settings = OfficeSettings.query.first()
                    checkout_time = settings.auto_checkout_time if settings and settings.auto_checkout_time else datetime.strptime('18:00', '%H:%M').time()
                    existing.check_out = datetime.combine(curr, checkout_time)
                    
                    # Calculate overtime if applicable
                    duration = (existing.check_out - existing.check_in).total_seconds() / 3600
                    if duration > 9:
                        existing.overtime_hours = duration - 9
                    has_changes = True
                    
            curr += timedelta(days=1)
        
        if has_changes:
            db.session.commit()

    @staticmethod
    def calculate_attendance_score(user_id, current_date):
        """
        Calculates the attendance score % for the current month.
        Score = (Present Days / Total Working Days) * 100
        Saturdays are excluded from total working days.
        """
        first_of_month = current_date.replace(day=1)
        
        # Count working days excluding Saturdays up to TODAY
        total_work_days = 0
        curr = first_of_month
        while curr <= current_date:
            if curr.weekday() != 5: # Skip Saturdays
                total_work_days += 1
            curr += timedelta(days=1)
            
        # Count present days in DB (Optimized query with raw datetime ranges for indexing)
        start_of_month_dt = datetime.combine(first_of_month, datetime.min.time())
        end_of_period_dt = datetime.combine(current_date, datetime.max.time())
        
        present_count = Attendance.query.filter_by(user_id=user_id).filter(
            Attendance.check_in >= start_of_month_dt,
            Attendance.check_in <= end_of_period_dt,
            Attendance.status.in_(['present', 'half-day', 'late'])
        ).count()

        # Edge Case Handle: On the first day of the month, show 100% (Neutral) 
        # until the first workday concludes or is missed.
        if total_work_days <= 1 and present_count == 0:
            return 100
            
        if total_work_days == 0:
            return 100
            
        score = (present_count / total_work_days) * 100
        return round(min(100, score))

class AttendanceMonitor:
    _instance_active = False

    def __init__(self, app):
        self.app = app

    def run(self):
        import os, time, subprocess
        # Moved to database/ folder to avoid triggering Flask's reloader in the root folder.
        db_dir = os.path.join(self.app.root_path, 'database')
        if not os.path.exists(db_dir):
            os.makedirs(db_dir)
        lock_file = os.path.join(db_dir, 'attendance_monitor.lock')
        
        def is_pid_alive(pid):
            if os.name == 'posix':
                # POSIX way to check for process existence without killing it
                try:
                    os.kill(pid, 0)
                    return True
                except OSError:
                    return False
            else:
                try:
                    # Windows fallback check
                    output = subprocess.check_output(['tasklist', '/FI', f'PID eq {pid}', '/NH'], 
                                                  stderr=subprocess.STDOUT, 
                                                  creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0).decode()
                    return str(pid) in output
                except Exception:
                    return False

        if os.path.exists(lock_file):
            try:
                with open(lock_file, 'r') as f:
                    old_pid = int(f.read().strip())
                if not is_pid_alive(old_pid):
                    # print(f"Stale monitor lock found (PID {old_pid} is dead). Cleaning up...")
                    try: os.remove(lock_file)
                    except: pass
                else:
                    # print(f"Attendance Monitor already running under PID {old_pid}. Exiting.")
                    return
            except (ValueError, OSError):
                # File corrupted or locked, try to remove it
                try: 
                    os.remove(lock_file)
                except:
                    return

        try:
            # Atomic creation to prevent race condition
            self.lock_fd = os.open(lock_file, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(self.lock_fd, str(os.getpid()).encode())
        except OSError:
            # print("Could not acquire monitor lock. Another instance may have just started.")
            return

        print(f"Attendance Monitor started successfully (Lock acquired by PID {os.getpid()}).")
        while True:
            with self.app.app_context():
                try:
                    pass  # Monitor running (heartbeat removed)
                except Exception as e:
                    print(f"Monitor error: {e}")
            time.sleep(60) # Run every minute


