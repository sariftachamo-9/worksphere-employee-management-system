from datetime import datetime


STATUS_RANK = {
    'present': 5,
    'late': 4,
    'half-day': 3,
    'holiday': 2,
    'weekend': 2,
    'absent': 1,
}


def _rank(attendance):
    status = attendance.status or 'present'
    rank = STATUS_RANK.get(status, 0)
    has_real_work_time = bool(attendance.check_out and attendance.check_out != attendance.check_in)
    return (
        rank,
        1 if has_real_work_time else 0,
        attendance.check_in or datetime.min,
        attendance.id or 0,
    )


def dedupe_attendance_by_date(attendances):
    by_date = {}
    for attendance in attendances:
        if not attendance.check_in:
            continue

        day = attendance.check_in.date()
        current = by_date.get(day)
        if current is None or _rank(attendance) > _rank(current):
            by_date[day] = attendance

    return [by_date[day] for day in sorted(by_date)]
