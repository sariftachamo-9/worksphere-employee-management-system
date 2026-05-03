from app import create_app
from extensions import db
from database.models import User, EmployeeProfile

app = create_app('development')
with app.app_context():
    # Mark Ashim and Abhishek as completed
    students_to_complete = EmployeeProfile.query.filter(EmployeeProfile.full_name.in_(['Ashim Nepal', 'Abhishek Dhungana'])).all()
    for profile in students_to_complete:
        profile.workshop_status = 'Completed'
        profile.user.is_active = False
        print(f"Completed and deactivated: {profile.full_name}")
        
    # Reactivate interns
    interns = User.query.filter_by(role='intern').all()
    for i in interns:
        i.is_active = True
        print(f"Reactivated intern: {i.email}")
        if i.profile:
            i.profile.workshop_status = 'Ongoing'

    db.session.commit()
    print("Database updated successfully")
