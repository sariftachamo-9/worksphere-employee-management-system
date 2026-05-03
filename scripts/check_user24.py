from app import create_app
from database.models import User, EmployeeProfile
app = create_app('development')
with app.app_context():
    u = User.query.get(24)
    print("User 24 exists:", u is not None)
    if u:
        print("User 24 name:", u.profile.full_name if u.profile else "No profile")
