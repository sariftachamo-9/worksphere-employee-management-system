from app import create_app
from database.models import Attendance, User
from extensions import db

app = create_app('development')
with app.app_context():
    student_attendance = db.session.query(Attendance).join(User).filter(User.role == 'student').count()
    print(f"Total student attendance records: {student_attendance}")
