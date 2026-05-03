from app import create_app
from database.models import User, LeaveRequest
app = create_app('development')
with app.app_context():
    users = User.query.filter(User.email.ilike('%ngawang%')).all()
    for u in users:
        print("User:", u.email, u.profile.full_name if u.profile else "No Profile")
    
    leaves = LeaveRequest.query.all()
    for l in leaves:
        if l.user and 'ngawang' in (l.user.profile.full_name.lower() if l.user.profile else ''):
            print(f"Leave ID: {l.id}, User ID: {l.user_id}, Name: {l.user.profile.full_name}")
