from app import create_app
from extensions import db
from database.models import Attendance
from datetime import datetime

app = create_app()
with app.app_context():
    # Only delete past records, just to be safe. But the user said "all absent cute and start fresh"
    # I'll just delete ALL absent and holiday records.
    # If they are from past, they won't be recreated because of the fresh_start date!
    count = Attendance.query.filter(Attendance.status.in_(['absent', 'holiday'])).delete()
    db.session.commit()
    print(f"Deleted {count} absent/holiday records.")

