from app import create_app
from database.models import LeaveRequest
app = create_app('development')
with app.app_context():
    leaves = LeaveRequest.query.all()
    for l in leaves:
        if l.user and 'ngawang' in (l.user.profile.full_name.lower() if l.user.profile else ''):
            print(f"Leave ID: {l.id}, User ID: {l.user_id}, Name: {l.user.profile.full_name}, Dates: {l.start_date} to {l.end_date}, Type: {l.leave_type}, Status: {l.status}")
