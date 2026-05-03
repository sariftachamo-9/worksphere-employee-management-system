from app import create_app
from database.models import EmployeeProfile

app = create_app('development')
with app.app_context():
    profiles = EmployeeProfile.query.filter(EmployeeProfile.full_name.in_(['Jenik Shrestha'])).all()
    for p in profiles:
        print(f"Name: {p.full_name}, Active: {p.user.is_active}, Status: '{p.workshop_status}'")
