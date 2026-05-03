from app import create_app
from extensions import db
from database.models import User, EmployeeProfile

app = create_app('development')
with app.app_context():
    query = User.query.join(EmployeeProfile).filter(
        User.role == 'student', 
        db.or_(User.is_active == True, EmployeeProfile.workshop_status == 'Completed')
    )
    users = query.all()
    print("Query Students:")
    for u in users:
        print(f"- {u.profile.full_name}")

    query2 = User.query.join(EmployeeProfile).filter(
        User.role.in_(['employee', 'intern', 'student'])
    )
    users2 = query2.all()
    print("All Students (ignore active):")
    for u in users2:
        if u.role == 'student':
            print(f"- {u.profile.full_name}")
