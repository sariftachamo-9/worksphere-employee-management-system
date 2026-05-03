from app import create_app
from extensions import db
from database.models import User, EmployeeProfile

app = create_app('development')
with app.app_context():
    users = EmployeeProfile.query.filter(EmployeeProfile.full_name.in_(['Ashim Nepal', 'Abhishek Dhungana'])).all()
    for profile in users:
        print(f"Name: {profile.full_name}, Active: {profile.user.is_active}, Status: '{profile.workshop_status}'")
