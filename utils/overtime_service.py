from datetime import datetime, timedelta

from extensions import db
from database.models import AuditLog, OvertimeRequest, User
from utils.time_utils import get_nepal_time

MAX_DAILY_OVERTIME_HOURS = 5


def overtime_end_time(ot_request):
    if not ot_request or not ot_request.actual_start_time:
        return None
    return ot_request.actual_start_time + timedelta(hours=float(ot_request.hours or 0))


def overtime_remaining_seconds(ot_request, now=None):
    end_time = overtime_end_time(ot_request)
    if not end_time:
        return 0
    now = now or get_nepal_time()
    return max(0, int((end_time - now).total_seconds()))


def complete_overtime(ot_request, actor_ip='SYSTEM', lock_user=True, now=None):
    if not ot_request or ot_request.status != 'in-progress':
        return False

    now = now or get_nepal_time()
    end_time = overtime_end_time(ot_request) or now
    completed_at = min(now, end_time)

    ot_request.status = 'completed'
    ot_request.actual_end_time = completed_at

    user = User.query.get(ot_request.user_id)
    if user:
        user.overtime_bypass_until = None
        if lock_user:
            tomorrow = now + timedelta(days=1)
            user.lockout_until = datetime(tomorrow.year, tomorrow.month, tomorrow.day, 0, 1)

        db.session.add(AuditLog(
            user_id=user.id,
            action='Overtime auto-completed' if actor_ip == 'SYSTEM' else 'Overtime completed',
            details=f"Overtime request #{ot_request.id} ended at {completed_at.strftime('%I:%M %p')}.",
            ip_address=actor_ip
        ))

    return True


def complete_elapsed_overtimes(now=None):
    now = now or get_nepal_time()
    completed = 0

    active_requests = OvertimeRequest.query.filter_by(status='in-progress').all()
    for ot_request in active_requests:
        end_time = overtime_end_time(ot_request)
        if end_time and now >= end_time:
            if complete_overtime(ot_request, actor_ip='SYSTEM', now=now):
                completed += 1

    if completed:
        db.session.commit()

    return completed
