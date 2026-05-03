from app import create_app
from extensions import db
from database.models import User, EmployeeProfile

app = create_app('development')
with app.app_context():
    users = User.query.join(EmployeeProfile).filter(
        User.role == 'student',
        EmployeeProfile.workshop_status == 'Completed'
    ).all()
    print("Completed Students in DB:")
    for u in users:
        print(f"- {u.profile.full_name} ({u.role}, {u.profile.workshop_status})")
