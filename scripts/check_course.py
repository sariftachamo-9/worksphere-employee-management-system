from app import create_app
from database.models import EmployeeProfile

app = create_app('development')
with app.app_context():
    profiles = EmployeeProfile.query.filter(EmployeeProfile.full_name.in_(['Abhishek Dhungana'])).all()
    for p in profiles:
        print(f"Dept: {p.department}, Desig: {p.designation}")
