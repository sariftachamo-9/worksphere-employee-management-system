from app import create_app
from database.models import Payroll
app = create_app('development')
with app.app_context():
    payrolls = Payroll.query.all()
    for p in payrolls:
        print(f"User: {p.user.profile.full_name}, Absent: {p.absent_days}, Leave: {p.leave_days}")
