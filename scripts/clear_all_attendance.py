from app import create_app
from extensions import db
from database.models import Attendance, TimeLog

app = create_app()
with app.app_context():
    # First delete TimeLog because of foreign key constraint
    time_logs_deleted = TimeLog.query.delete()
    db.session.commit()
    
    # Then delete all attendance records
    attendance_deleted = Attendance.query.delete()
    db.session.commit()
    
    print(f"Deleted {time_logs_deleted} time logs and {attendance_deleted} attendance records.")

