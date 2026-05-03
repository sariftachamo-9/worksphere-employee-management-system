from app import app
from extensions import db
from database.models import User, EmployeeProfile

with app.app_context():
    users = EmployeeProfile.query.filter(EmployeeProfile.full_name.in_(['Ashim Nepal', 'Abishek Dhungana'])).all()
    for profile in users:
        print(f"Found {profile.full_name}")
        profile.workshop_status = 'Completed'
        profile.user.is_active = False
    
    db.session.commit()
    print("Done")
