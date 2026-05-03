from app import create_app
from database.models import User, EmployeeProfile
app = create_app('development')
with app.app_context():
    users = User.query.filter(User.email.ilike('%ngawang%')).all()
    for u in users:
        print(u.email, u.profile.full_name if u.profile else "No Profile")
